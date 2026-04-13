"""Backtest: measure real-world accuracy of year-over-year projections.

Strategy: For each historical season, train on prior years, project that season,
then compare projected vs actual fantasy points. Also simulates drafting the
top-projected players and checks how they actually performed.
"""
import pandas as pd
import numpy as np
from typing import Optional

from src.data.fetch import load_all_data
from src.data.clean import clean_seasonal_stats, clean_roster_info, clean_team_stats, clean_ol_metrics
from src.features.engineer import build_feature_matrix
from src.scoring.calculator import add_fantasy_points_to_df
from src.models.pipeline import PositionPipeline
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel
from src.optimizer.roster_optimizer import optimize_roster


def run_backtest(
    seasons: list[int],
    scoring_format: str = "half_ppr",
    min_train_seasons: int = 2,
    top_n: int = 20,
    roster_size: int = 14,
) -> pd.DataFrame:
    """Run backtest across multiple seasons.

    For each test season:
    1. Train on all prior seasons (walk-forward)
    2. Generate projections for that season
    3. Compare projected vs actual fantasy points
    4. Simulate drafting top-projected roster and check actual performance

    Returns DataFrame with per-season accuracy metrics.
    """
    results = []

    for i, test_season in enumerate(seasons):
        train_seasons = seasons[:i]
        if len(train_seasons) < min_train_seasons:
            print(f"Skipping {test_season}: only {len(train_seasons)} training seasons")
            continue

        print(f"\n{'='*60}")
        print(f"BACKTEST: {test_season} (trained on {train_seasons})")
        print(f"{'='*60}")

        # Load data
        all_seasons = train_seasons + [test_season]
        data = load_all_data(all_seasons)

        seasonal = clean_seasonal_stats(data["seasonal"], min_games=3)
        roster = clean_roster_info(data["roster"])
        team = clean_team_stats(data["team"])
        ol = clean_ol_metrics(data["ol"])

        df = build_feature_matrix(seasonal, roster, team, ol)
        df = add_fantasy_points_to_df(df, format=scoring_format)
        df = df[df["position"].isin(["QB", "RB", "WR", "TE"])]

        # Split train/test
        train_df = df[df["season"].isin(train_seasons)]
        test_df = df[df["season"] == test_season]

        if train_df.empty or test_df.empty:
            print(f"  Skipping: empty train ({len(train_df)}) or test ({len(test_df)})")
            continue

        # Train models
        pipeline = PositionPipeline(models=[RidgeModel(), RandomForestModel(), XGBoostModel()])
        pipeline.validate_all(train_df, min_train_seasons=min_train_seasons)
        pipeline.train_final(train_df)

        # Generate projections (predict for test season using train data features)
        projections = pipeline.predict(train_df, target_season=test_season)

        if projections.empty:
            print(f"  Skipping: no projections generated")
            continue

        # Get actual points for test season
        actual = test_df[["player_id", "fantasy_points", "position", "team"]].copy()
        actual = actual.rename(columns={"fantasy_points": "actual_points", "position": "actual_position", "team": "actual_team"})

        # Merge projected vs actual
        comparison = projections.merge(actual, on="player_id", how="inner")

        if comparison.empty:
            print(f"  Skipping: no matching players")
            continue

        # --- Per-player accuracy ---
        comparison["error"] = comparison["projected_points"] - comparison["actual_points"]
        comparison["abs_error"] = comparison["error"].abs()
        comparison["pct_error"] = (comparison["abs_error"] / comparison["actual_points"].replace(0, np.nan) * 100)

        mae = float(comparison["abs_error"].mean())
        rmse = float(np.sqrt((comparison["error"] ** 2).mean()))
        ss_res = float((comparison["error"] ** 2).sum())
        ss_tot = float(((comparison["actual_points"] - comparison["actual_points"].mean()) ** 2).sum())
        r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
        median_ae = float(comparison["abs_error"].median())
        within_10pct = (comparison["pct_error"] <= 10).mean() * 100
        within_20pct = (comparison["pct_error"] <= 20).mean() * 100
        within_30pct = (comparison["pct_error"] <= 30).mean() * 100

        # --- Top-N accuracy: if you drafted the top N projected players ---
        top_projected = comparison.nlargest(top_n, "projected_points")
        top_actual = comparison.nlargest(top_n, "actual_points")
        hit_rate = len(set(top_projected["player_id"]) & set(top_actual["player_id"])) / top_n * 100

        top_proj_actual_pts = top_projected["actual_points"].sum()
        best_possible_pts = top_actual["actual_points"].sum()
        efficiency = (top_proj_actual_pts / best_possible_pts * 100) if best_possible_pts > 0 else 0

        # --- Simulated roster: draft best projected, check actual ---
        try:
            roster_result = optimize_roster(projections, remaining_picks=roster_size, scoring_format=scoring_format)
            roster_actual = roster_result.merge(actual, on="player_id", how="left")
            roster_projected_total = roster_result["projected_points"].sum()
            roster_actual_total = roster_actual["actual_points"].sum()
            roster_efficiency = (roster_actual_total / roster_projected_total * 100) if roster_projected_total > 0 else 0
        except Exception:
            roster_projected_total = 0
            roster_actual_total = 0
            roster_efficiency = 0

        result = {
            "season": test_season,
            "n_players": len(comparison),
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "r2": round(r2, 4),
            "median_ae": round(median_ae, 2),
            "within_10pct": round(within_10pct, 1),
            "within_20pct": round(within_20pct, 1),
            "within_30pct": round(within_30pct, 1),
            f"top{top_n}_hit_rate": round(hit_rate, 1),
            f"top{top_n}_efficiency": round(efficiency, 1),
            "roster_projected": round(roster_projected_total, 1),
            "roster_actual": round(roster_actual_total, 1),
            "roster_efficiency": round(roster_efficiency, 1),
        }
        results.append(result)

        print(f"  MAE: {mae:.1f} | RMSE: {rmse:.1f} | R²: {r2:.3f}")
        print(f"  Within 20% of actual: {within_20pct:.0f}%")
        print(f"  Top-{top_n} hit rate: {hit_rate:.0f}% (drafted top-{top_n} that were actually top-{top_n})")
        print(f"  Top-{top_n} efficiency: {efficiency:.0f}% of optimal points captured")
        print(f"  Roster: projected {roster_projected_total:.0f}, actual {roster_actual_total:.0f} ({roster_efficiency:.0f}%)")

        # Show top-5 projected vs actual
        print(f"\n  Top-5 Projected vs Actual:")
        for _, row in top_projected.head(5).iterrows():
            name = row.get("player_name", row.get("player_id", "?"))
            print(f"    {name:20s} {row['position']:3s} proj={row['projected_points']:6.1f} actual={row['actual_points']:6.1f} err={row['error']:+6.1f}")

    return pd.DataFrame(results)


def print_backtest_summary(results: pd.DataFrame) -> None:
    """Print a readable summary of backtest results across seasons."""
    if results.empty:
        print("No backtest results.")
        return

    print(f"\n{'='*70}")
    print(f"BACKTEST SUMMARY ({len(results)} seasons)")
    print(f"{'='*70}")

    avg = results.mean(numeric_only=True)
    print(f"  Average MAE:          {avg['mae']:.1f} fantasy points")
    print(f"  Average RMSE:         {avg['rmse']:.1f}")
    print(f"  Average R²:           {avg['r2']:.3f}")
    print(f"  Avg within 20%:       {avg['within_20pct']:.0f}%")
    print(f"  Avg within 30%:       {avg['within_30pct']:.0f}%")
    print(f"  Avg Top-20 hit rate:  {avg['top20_hit_rate']:.0f}%")
    print(f"  Avg Top-20 efficiency:{avg['top20_efficiency']:.0f}%")
    print(f"  Avg roster efficiency: {avg['roster_efficiency']:.0f}%")

    print(f"\n  Per-season breakdown:")
    for _, row in results.iterrows():
        print(f"    {int(row['season'])}: MAE={row['mae']:.1f} R²={row['r2']:.3f} "
              f"Top20 hit={row['top20_hit_rate']:.0f}% roster_eff={row['roster_efficiency']:.0f}%")
