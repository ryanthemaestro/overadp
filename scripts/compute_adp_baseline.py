#!/usr/bin/env python3
"""
Compute ADP-as-predictor baseline R² and MAE on the same walk-forward folds.

For each test season (2022-2025), treat ADP as a predictor of fantasy points:
  predicted_points = f(ADP) where f is learned on train seasons (simple per-pos
  regression: actual ~= a - b*adp + c*adp²)

This gives a FAIR apples-to-apples comparison:
  - Same held-out test seasons as the model
  - Same cohort of players (those with valid ADP + fantasy points)
  - Converts ADP rank to expected points using historical train data

Prints per-position + overall R²/MAE for ADP baseline.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Load the engineered feature frame (what the model trains on).
# Easiest: rerun the pipeline's data assembly to get adp + fantasy_points per season.
from src.data.fetch import (
    fetch_seasonal_stats,
    fetch_roster_info,
    fetch_adp_data,
)
from src.features.engineer import compute_adp_features


def _mae(y_true, y_pred):
    return float(np.mean(np.abs(y_true - y_pred)))


def _r2(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def _norm(s):
    """Lowercase + strip suffixes + strip punctuation."""
    import re
    s = str(s).lower().strip()
    s = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", s)
    return s.replace("'", "").replace("-", "").replace(".", "").strip()


def build_frame():
    """Load seasonal stats + ADP, merge by (name, position, season). Returns DataFrame."""
    print("Loading seasonal stats...")
    stats = fetch_seasonal_stats(seasons=list(range(2019, 2026)))
    print(f"  {len(stats):,} player-seasons")

    print("Loading ADP...")
    adp = fetch_adp_data(seasons=list(range(2019, 2026)))
    print(f"  {len(adp):,} ADP rows")

    # Filter offense
    stats = stats[stats["position"].isin(["QB", "RB", "WR", "TE"])].copy()
    stats = stats[stats["fantasy_points"].notna() & (stats["fantasy_points"] > 0)].copy()

    # Use player_display_name (or player_name) for ADP matching
    name_col = "player_display_name" if "player_display_name" in stats.columns else "player_name"
    stats["_key"] = stats[name_col].apply(_norm) + "|" + stats["position"] + "|" + stats["season"].astype(str)

    adp = adp[adp["position"].isin(["QB", "RB", "WR", "TE"])].copy()
    adp["_key"] = adp["player_name"].apply(_norm) + "|" + adp["position"] + "|" + adp["season"].astype(str)
    adp_map = adp.drop_duplicates(subset=["_key"], keep="first").set_index("_key")["adp"].to_dict()

    stats["adp"] = stats["_key"].map(adp_map)
    stats["has_adp"] = stats["adp"].notna() & (stats["adp"] < 200)

    return stats[["player_id", name_col, "season", "position", "fantasy_points", "adp", "has_adp"]].rename(
        columns={name_col: "player_name"}
    )


def fit_adp_predictor(train_df: pd.DataFrame, pos: str):
    """Fit a simple predictor: fantasy_points ~ f(adp) for this position, on train seasons.
    Uses a quadratic in log-ADP (smooth, monotonic in the relevant range).
    Returns callable that takes adp -> predicted points.
    """
    pos_train = train_df[(train_df["position"] == pos) & train_df["has_adp"]]
    if len(pos_train) < 10:
        return None

    # Feature: log(adp + 1). Target: fantasy_points.
    X = np.log(pos_train["adp"].values + 1).reshape(-1, 1)
    y = pos_train["fantasy_points"].values
    # Quadratic in log(adp)
    Xf = np.hstack([np.ones_like(X), X, X ** 2])
    # OLS
    beta, *_ = np.linalg.lstsq(Xf, y, rcond=None)

    def predict(adp):
        adp = np.asarray(adp, dtype=float)
        x = np.log(adp + 1).reshape(-1, 1)
        xf = np.hstack([np.ones_like(x), x, x ** 2])
        return xf @ beta

    return predict


def main():
    df = build_frame()
    print(f"\nTotal player-seasons with fantasy_points > 0: {len(df):,}")
    print(f"  with ADP matched: {df['has_adp'].sum():,} ({df['has_adp'].mean()*100:.1f}%)")

    test_seasons = [2022, 2023, 2024, 2025]
    positions = ["QB", "RB", "WR", "TE"]

    rows = []
    for test_season in test_seasons:
        train = df[df["season"] < test_season].copy()
        test = df[df["season"] == test_season].copy()

        for pos in positions:
            predictor = fit_adp_predictor(train, pos)
            if predictor is None:
                continue
            pos_test = test[(test["position"] == pos) & test["has_adp"]]
            if len(pos_test) < 5:
                continue
            preds = predictor(pos_test["adp"].values)
            actual = pos_test["fantasy_points"].values
            rows.append({
                "season": test_season,
                "position": pos,
                "mae": _mae(actual, preds),
                "r2": _r2(actual, preds),
                "n": len(pos_test),
            })

    adp_df = pd.DataFrame(rows)
    print("\n=== ADP Baseline per (position, season) ===")
    print(adp_df.to_string(index=False))

    print("\n=== ADP Baseline averaged 2022-2025 ===")
    avg = adp_df.groupby("position").agg(mae=("mae", "mean"), r2=("r2", "mean"), n=("n", "mean")).reset_index()
    print(avg.to_string(index=False))

    print("\n=== ADP Baseline 2025 only ===")
    print(adp_df[adp_df["season"] == 2025].to_string(index=False))

    # Save
    adp_df.to_csv(REPO / "adp_baseline_validation.csv", index=False)
    print(f"\n✓ Saved to {REPO}/adp_baseline_validation.csv")


if __name__ == "__main__":
    main()
