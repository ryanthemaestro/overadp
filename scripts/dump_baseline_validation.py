#!/usr/bin/env python3
"""Run the same walk-forward validation export_static does, but persist the full
per-(position, model, season) results to baseline_validation.csv.

Run after fixing data bugs to refresh the headline numbers used in marketing copy.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data.fetch import load_all_data, fetch_adp_data
from src.data.clean import clean_seasonal_stats, clean_roster_info, clean_team_stats, clean_ol_metrics
from src.features.engineer import (
    build_feature_matrix,
    compute_regression_to_mean_features,
    compute_stacking_features,
    compute_adp_features,
    compute_injury_features,
    compute_sos_features,
    compute_rookie_features,
    compute_teammate_dependency_features,
    compute_depth_chart_features,
    compute_target_competition_features,
)
from src.features.college import compute_college_features
from src.scoring.calculator import add_fantasy_points_to_df
from src.models.pipeline import PositionPipeline
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel
from src.models.catboost_model import CatBoostModel

SEASONS = list(range(2021, 2026))
MAX_STATS = 2025

def main():
    print(f"Loading {SEASONS}...")
    data = load_all_data(SEASONS)
    seasonal = clean_seasonal_stats(data["seasonal"], min_games=3)
    roster = clean_roster_info(data["roster"])
    team = clean_team_stats(data["team"])
    ol = clean_ol_metrics(data["ol"])
    df = build_feature_matrix(seasonal, roster, team, ol)
    df = add_fantasy_points_to_df(df, format="half_ppr")
    df = compute_regression_to_mean_features(df)
    df = compute_stacking_features(df)

    adp = fetch_adp_data(seasons=SEASONS)
    df = compute_adp_features(df, adp)

    try:
        from src.data.fetch import fetch_injury_data
        injury = fetch_injury_data([s for s in SEASONS if s <= MAX_STATS])
        df = compute_injury_features(df, injury)
    except Exception as e:
        print(f"  Warning: injury skipped: {e}")

    df = compute_sos_features(df)
    df = compute_rookie_features(df)
    df = compute_teammate_dependency_features(df)
    try:
        df = compute_college_features(df, draft_df=data.get("draft"), combine_df=data.get("combine"), player_info_df=data.get("player_info"))
    except Exception as e:
        print(f"  Warning: college skipped: {e}")
    try:
        from src.data.fetch import fetch_depth_charts
        depth = fetch_depth_charts(SEASONS)
        df = compute_depth_chart_features(df, depth)
    except Exception as e:
        print(f"  Warning: depth skipped: {e}")
    df = compute_target_competition_features(df)

    pipe = PositionPipeline(models=[RidgeModel(), RandomForestModel(), XGBoostModel(), CatBoostModel()])
    pipe.validate_all(df, min_train_seasons=3)

    vr = pipe.validation_results
    if vr is None or vr.empty:
        print("ERROR: empty validation_results")
        sys.exit(1)

    out = REPO / "baseline_validation.csv"
    vr.to_csv(out, index=False)
    print(f"\n✓ Saved {len(vr)} rows to {out}")
    print("\nWalk-forward avg MAE per (position, model):")
    avg = vr.groupby(["position", "model"]).agg(mae=("mae", "mean"), r2=("r2", "mean")).reset_index()
    print(avg.to_string(index=False))

if __name__ == "__main__":
    main()
