#!/usr/bin/env python3
"""Compare production CatBoost against an ADP-only model on identical folds.

This script deliberately rebuilds the historical feature frame instead of
loading an experiment cache. Both models are evaluated on the exact eligible
player rows in the 2024 and 2025 walk-forward folds. The ADP baseline is a
predeclared standardized Ridge model over the same four market-shape features
used by the production pipeline.

Outputs:
    exact_adp_baseline_results.csv
    exact_adp_baseline_summary.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data.clean import (  # noqa: E402
    clean_ol_metrics,
    clean_roster_info,
    clean_seasonal_stats,
    clean_team_stats,
)
from src.data.fetch import fetch_adp_data, load_all_data  # noqa: E402
from src.features.college import compute_college_features  # noqa: E402
from src.features.contracts import compute_contract_features  # noqa: E402
from src.features.engineer import (  # noqa: E402
    build_feature_matrix,
    compute_adp_features,
    compute_depth_chart_features,
    compute_injury_features,
    compute_regression_to_mean_features,
    compute_rookie_features,
    compute_sos_features,
    compute_stacking_features,
    compute_target_competition_features,
    compute_teammate_dependency_features,
)
from src.models.catboost_model import CatBoostModel  # noqa: E402
from src.models.pipeline import OFFENSIVE_POSITIONS, PositionPipeline  # noqa: E402
from src.scoring.calculator import add_fantasy_points_to_df  # noqa: E402
from src.api.export_static import build_projection_season_scaffold  # noqa: E402

SEASONS = [2021, 2022, 2023, 2024, 2025]
TEST_SEASONS = [2024, 2025]
PROJECTION_SEASON = 2026
ADP_FEATURES = ["adp", "adp_log", "adp_inverse", "adp_tier"]
OUT_RAW = REPO / "exact_adp_baseline_results.csv"
OUT_SUMMARY = REPO / "exact_adp_baseline_summary.json"


def _clean_x(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.replace([np.inf, -np.inf], np.nan).fillna(0)


def _metrics(y_true: pd.Series, prediction: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, prediction)),
        "rmse": float(mean_squared_error(y_true, prediction) ** 0.5),
        "r2": float(r2_score(y_true, prediction)) if len(y_true) > 1 else 0.0,
    }


def _aggregate(rows: pd.DataFrame) -> dict[str, float | int]:
    weights = rows["n_players"].astype(float)
    total = int(weights.sum())
    return {
        "mae": round(float(np.average(rows["mae"], weights=weights)), 2),
        "rmse": round(float(math.sqrt(np.average(np.square(rows["rmse"]), weights=weights))), 2),
        "r2": round(float(np.average(rows["r2"], weights=weights)), 4),
        "n_players": total,
    }


def build_historical_frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reproduce the production historical feature contract for validation."""
    data = load_all_data([*SEASONS, PROJECTION_SEASON])
    seasonal = clean_seasonal_stats(data["seasonal"], min_games=3)
    roster = clean_roster_info(data["roster"])
    team = clean_team_stats(data["team"])
    ol = clean_ol_metrics(data["ol"])

    from src.data.sleeper_rookies import fetch_sleeper_rookies
    from src.data.sleeper_rosters import apply_sleeper_team_overrides

    roster = apply_sleeper_team_overrides(roster, target_season=PROJECTION_SEASON)
    seasonal, roster = build_projection_season_scaffold(
        seasonal,
        roster,
        PROJECTION_SEASON,
        extra_players=fetch_sleeper_rookies(PROJECTION_SEASON),
    )

    frame = build_feature_matrix(
        seasonal,
        roster,
        team,
        ol,
        snap_df=data.get("snap_counts"),
        schedule_df=data.get("schedules"),
        ngs_data=data.get("ngs"),
        pfr_df=data.get("pfr"),
    )
    frame = add_fantasy_points_to_df(frame, format="half_ppr")
    frame = compute_regression_to_mean_features(frame)
    frame = compute_stacking_features(frame)

    adp = fetch_adp_data(seasons=[*SEASONS, PROJECTION_SEASON])
    frame = compute_adp_features(frame, adp)

    try:
        from src.data.fetch import fetch_injury_data

        frame = compute_injury_features(frame, fetch_injury_data(SEASONS))
    except Exception as exc:
        print(f"  Warning: injury features skipped: {exc}")

    frame = compute_sos_features(frame)
    frame = compute_rookie_features(frame)
    frame = compute_teammate_dependency_features(frame)
    frame = compute_college_features(
        frame,
        draft_df=data.get("draft"),
        combine_df=data.get("combine"),
        player_info_df=data.get("player_info"),
        draft_values_df=data.get("draft_values"),
    )
    frame = compute_contract_features(frame, data.get("contracts"))

    try:
        from src.data.fetch import fetch_depth_charts

        depth = fetch_depth_charts([*SEASONS, PROJECTION_SEASON])
        from src.data.sleeper_rosters import build_sleeper_depth_chart

        sleeper_depth = build_sleeper_depth_chart(roster, target_season=PROJECTION_SEASON)
        if not sleeper_depth.empty:
            depth = depth[depth["season"].ne(PROJECTION_SEASON)]
            sleeper_depth = sleeper_depth.reindex(columns=depth.columns)
            depth = pd.concat([depth, sleeper_depth], ignore_index=True)
        frame = compute_depth_chart_features(frame, depth)
    except Exception as exc:
        print(f"  Warning: depth features skipped: {exc}")

    frame = compute_target_competition_features(frame)
    return frame[frame["season"].lt(PROJECTION_SEASON)].copy(), adp


def main() -> None:
    print("Building uncached historical validation frame...")
    frame, adp = build_historical_frame()

    production = PositionPipeline(models=[CatBoostModel()])
    production.validate_all(frame, min_train_seasons=3)
    model_rows = production.validation_results
    if model_rows is None or model_rows.empty:
        raise RuntimeError("Production validation returned no rows")

    source_by_season = {
        int(season): sorted(group["source"].dropna().astype(str).unique().tolist())
        for season, group in adp.groupby("season")
    }
    raw_rows: list[dict] = []
    for pos in OFFENSIVE_POSITIONS:
        pos_frame = frame[frame["position"].eq(pos)].copy()
        for test_season in TEST_SEASONS:
            train = pos_frame[pos_frame["season"].lt(test_season)].copy()
            test = pos_frame[pos_frame["season"].eq(test_season)].copy()
            train = train[train["fantasy_points"].notna() & np.isfinite(train["fantasy_points"])]
            test = test[test["fantasy_points"].notna() & np.isfinite(test["fantasy_points"])]
            if train.empty or test.empty:
                continue

            expected = model_rows[
                model_rows["position"].eq(pos) & model_rows["season"].eq(test_season)
            ]
            if len(expected) != 1:
                raise AssertionError(f"Missing production fold for {pos} {test_season}")
            expected_n = int(expected.iloc[0]["n_players"])
            if len(test) != expected_n:
                raise AssertionError(
                    f"Cohort mismatch for {pos} {test_season}: baseline={len(test)} model={expected_n}"
                )

            baseline = make_pipeline(StandardScaler(), Ridge(alpha=20.0))
            baseline.fit(_clean_x(train[ADP_FEATURES]), train["fantasy_points"])
            prediction = np.clip(baseline.predict(_clean_x(test[ADP_FEATURES])), 0, None)
            market_metrics = _metrics(test["fantasy_points"], prediction)
            ranked_n = int(pd.to_numeric(test["adp"], errors="coerce").lt(200).sum())

            raw_rows.append({
                "model": "adp_ridge",
                "position": pos,
                "season": test_season,
                "n_players": len(test),
                "ranked_adp_n": ranked_n,
                "ranked_adp_rate": ranked_n / len(test),
                "adp_sources": ",".join(source_by_season.get(test_season, [])),
                **market_metrics,
            })
            raw_rows.append({
                "model": "catboost",
                "position": pos,
                "season": test_season,
                "n_players": expected_n,
                "ranked_adp_n": ranked_n,
                "ranked_adp_rate": ranked_n / len(test),
                "adp_sources": ",".join(source_by_season.get(test_season, [])),
                "mae": float(expected.iloc[0]["mae"]),
                "rmse": float(expected.iloc[0]["rmse"]),
                "r2": float(expected.iloc[0]["r2"]),
            })

    raw = pd.DataFrame(raw_rows).sort_values(["position", "season", "model"])
    raw.to_csv(OUT_RAW, index=False)

    by_position: dict[str, dict] = {}
    for pos in OFFENSIVE_POSITIONS:
        market = _aggregate(raw[raw["position"].eq(pos) & raw["model"].eq("adp_ridge")])
        model = _aggregate(raw[raw["position"].eq(pos) & raw["model"].eq("catboost")])
        by_position[pos] = {
            "catboost": model,
            "adp_ridge": market,
            "mae_improvement": round(1.0 - model["mae"] / market["mae"], 4),
        }

    market_overall = _aggregate(raw[raw["model"].eq("adp_ridge")])
    model_overall = _aggregate(raw[raw["model"].eq("catboost")])
    test_sources = sorted({s for season in TEST_SEASONS for s in source_by_season.get(season, [])})
    actual_adp_sources = {"ffc", "fantasypros"}
    summary = {
        "cohort": {
            "test_seasons": TEST_SEASONS,
            "n_players": model_overall["n_players"],
            "aggregation": "player_weighted_walk_forward_folds",
            "adp_sources": {str(s): source_by_season.get(s, []) for s in TEST_SEASONS},
        },
        "overall": {
            "catboost": model_overall,
            "adp_ridge": market_overall,
            "mae_improvement": round(1.0 - model_overall["mae"] / market_overall["mae"], 4),
        },
        "by_position": by_position,
        "public_comparison_eligible": set(test_sources).issubset(actual_adp_sources),
        "public_comparison_note": (
            "All test folds use true preseason ADP snapshots."
            if set(test_sources).issubset(actual_adp_sources)
            else "At least one test fold uses an explicitly labeled preseason rank proxy; keep public market-beating claims disabled."
        ),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")

    print(raw.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nExact-cohort summary:")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {OUT_RAW.name} and {OUT_SUMMARY.name}")


if __name__ == "__main__":
    main()
