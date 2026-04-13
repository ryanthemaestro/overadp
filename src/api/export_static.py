"""Export all draft data as static JSON files for a serverless deployment.

Run this script to regenerate the data files:
    python -m src.api.export_static --seasons 5 --scoring half_ppr

Outputs to src/api/static/data/
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "static" / "data"


def sanitize(obj):
    """Recursively replace NaN/Inf with 0 for JSON."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        if math.isnan(obj) or math.isinf(obj):
            return 0
        return round(float(obj), 2)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, default=5)
    parser.add_argument("--scoring", default="half_ppr", choices=["half_ppr", "ppr", "standard"])
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load & process data ---
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
    )
    from src.features.college import compute_college_features
    from src.scoring.calculator import add_fantasy_points_to_df
    from src.models.pipeline import PositionPipeline
    from src.models.ridge_model import RidgeModel
    from src.models.rf_model import RandomForestModel
    from src.models.xgboost_model import XGBoostModel
    from src.models.catboost_model import CatBoostModel
    from src.optimizer.draft_strategy import (
        compute_vbd,
        compute_positional_scarcity,
        compute_bye_weeks,
        detect_sleepers_and_busts,
        detect_position_runs,
        find_handcuffs,
    )
    from src.utils.config import get_roster_config

    seasons_back = args.seasons
    max_stats_season = 2025  # Latest season with completed stats
    projection_season = max_stats_season + 1  # Season we're projecting
    seasons = list(range(max_stats_season - seasons_back + 1, max_stats_season + 1))

    print(f"Loading data for seasons {seasons} + {projection_season} roster...")
    data = load_all_data(list(range(min(seasons), projection_season + 1)))

    seasonal = clean_seasonal_stats(data["seasonal"], min_games=3)
    roster = clean_roster_info(data["roster"])
    team = clean_team_stats(data["team"])
    ol = clean_ol_metrics(data["ol"])

    df = build_feature_matrix(seasonal, roster, team, ol)
    df = add_fantasy_points_to_df(df, format=args.scoring)
    df = compute_regression_to_mean_features(df)
    df = compute_stacking_features(df)

    try:
        adp_data = fetch_adp_data(seasons=[projection_season])
        df = compute_adp_features(df, adp_data)
    except Exception:
        adp_data = None

    try:
        from src.data.fetch import fetch_injury_data
        # Only fetch injury data for past seasons (API returns 404 for future)
        injury_seasons = [s for s in seasons if s <= 2025]
        if injury_seasons:
            injury_data = fetch_injury_data(injury_seasons)
            df = compute_injury_features(df, injury_data)
    except Exception as e:
        print(f"  Warning: injury data unavailable: {e}")

    df = compute_sos_features(df)
    df = compute_rookie_features(df)
    df = compute_teammate_dependency_features(df)

    # College/draft features (critical for rookies)
    try:
        df = compute_college_features(
            df,
            draft_df=data.get("draft"),
            combine_df=data.get("combine"),
            player_info_df=data.get("player_info"),
        )
    except Exception:
        pass

    # --- Train models ---
    print("Training models...")
    pipeline = PositionPipeline(models=[RidgeModel(), RandomForestModel(), XGBoostModel(), CatBoostModel()])
    pipeline.validate_all(df, min_train_seasons=3)
    pipeline.train_final(df)

    # --- Create projection-season rows ---
    latest_season = df["season"].max()
    if projection_season > latest_season and not roster.empty:
        latest_rows = df[df["season"] == latest_season].copy()
        roster_proj = roster[roster["season"] == projection_season] if "season" in roster.columns else pd.DataFrame()

        proj_rows = latest_rows.copy()
        proj_rows["season"] = projection_season

        # Save previous season's fantasy points for pts_lag1 BEFORE zeroing
        prev_fp = proj_rows["fantasy_points"].copy() if "fantasy_points" in proj_rows.columns else None

        # Zero out current-season stats (they haven't happened yet)
        for c in ["fantasy_points", "games", "pts_lag0"]:
            if c in proj_rows.columns:
                proj_rows[c] = 0

        # Fix pts_lag1: should be the PREVIOUS season's fantasy points.
        # The 2025 row's pts_lag1 was 2024's FP (from the shift in compute_regression).
        # For 2026 projection, pts_lag1 should be 2025's FP.
        if "pts_lag1" in proj_rows.columns and prev_fp is not None:
            proj_rows["pts_lag1"] = prev_fp

        # Keep all other lag features (passing_yards_lag1, etc.) from the 2025 row.
        # These use 2024 stats as lag1, which is actually the best available data
        # for projecting 2026 performance. Shifting to 2025 stats would use
        # injury-shortened data and make projections worse.

        # Regression features (yoy_change, pts_roll2, etc.) are kept from the 2025 row.
        # Don't recompute — yoy_change = 0 - pts_lag1 is always negative (meaningless).

        # Update team/position/age from projection-season roster
        if not roster_proj.empty and "player_id" in roster_proj.columns:
            ru = roster_proj[["player_id", "team", "position", "age"]].drop_duplicates("player_id")
            ru = ru.rename(columns={"team": "tn", "position": "pn", "age": "an"})
            proj_rows = proj_rows.merge(ru, on="player_id", how="left")
            for old, new in [("team", "tn"), ("position", "pn"), ("age", "an")]:
                if new in proj_rows.columns:
                    proj_rows[old] = proj_rows[new].fillna(proj_rows[old])
                    proj_rows = proj_rows.drop(columns=[new])

        try:
            proj_rows = compute_college_features(proj_rows, draft_df=data.get("draft"), combine_df=data.get("combine"), player_info_df=data.get("player_info"))
        except Exception:
            pass
        proj_rows = compute_rookie_features(proj_rows)
        df = pd.concat([df, proj_rows], ignore_index=True)

    # --- Generate projections ---
    projections = pipeline.predict(df, target_season=projection_season)
    if projections.empty:
        projections = pipeline.predict(df, target_season=latest_season)

    # ADP is already included by pipeline.predict() via row.get("adp", 200)
    # Just ensure any remaining NaN is filled
    if "adp" in projections.columns:
        projections["adp"] = projections["adp"].fillna(200)

    # --- Add bye weeks to player records from ADP data ---
    if adp_data is not None and not adp_data.empty and "bye" in adp_data.columns:
        bye_map = adp_data[adp_data["bye"] > 0][["team", "bye"]].drop_duplicates("team")
        bye_dict = dict(zip(bye_map["team"], bye_map["bye"]))
        projections["bye"] = projections["team"].map(bye_dict).fillna(0).astype(int)

    # --- Add injury data to player records from feature matrix ---
    if "player_id" in df.columns:
        latest = df[df["season"] == projection_season] if projection_season in df["season"].values else df[df["season"] == df["season"].max()]
        injury_cols = ["player_id", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3"]
        available_injury = [c for c in injury_cols if c in latest.columns]
        if len(available_injury) > 1:
            inj_sub = latest[available_injury].drop_duplicates("player_id")
            projections = projections.merge(inj_sub, on="player_id", how="left")
            for c in available_injury[1:]:
                projections[c] = projections[c].fillna(0)

    # Clean NaN
    for col in projections.columns:
        if projections[col].dtype in ["float64", "float32", "int64", "int32"]:
            projections[col] = projections[col].fillna(0)

    players = sanitize(projections.to_dict("records"))

    # --- Compute VBD ---
    roster_config = get_roster_config()
    num_teams = roster_config.get("num_teams", 12)
    vbd_df = compute_vbd(projections, num_teams=num_teams, roster_config=roster_config)
    vbd_map = dict(zip(vbd_df["player_name"], vbd_df["vbd"]))

    # Add VBD to player records
    for p in players:
        p["vbd"] = round(vbd_map.get(p.get("player_name", ""), 0), 1)

    # --- Compute positional scarcity ---
    scarcity = compute_positional_scarcity(projections, num_teams=num_teams, roster_config=roster_config)
    scarcity_data = sanitize(scarcity.to_dict("records") if hasattr(scarcity, "to_dict") else scarcity)

    # --- Compute bye weeks ---
    # Prefer bye weeks from FFC ADP data (already has them per team)
    bye_data = {}
    if adp_data is not None and not adp_data.empty and "bye" in adp_data.columns:
        bye_rows = adp_data[adp_data["bye"] > 0][["team", "bye"]].drop_duplicates("team")
        bye_data = dict(zip(bye_rows["team"], bye_rows["bye"].astype(int)))
    if not bye_data:
        bye_weeks = compute_bye_weeks(season=projection_season)
        if bye_weeks:
            for k, v in bye_weeks.items():
                if isinstance(v, list):
                    bye_data[k] = v
                else:
                    try:
                        bye_data[k] = int(v)
                    except (ValueError, TypeError):
                        bye_data[k] = v

    # --- Detect sleepers & busts ---
    sleepers_busts = detect_sleepers_and_busts(projections, adp_data)
    sb_data = sanitize(sleepers_busts)

    # --- Roster config ---
    roster_data = {
        "roster_slots": roster_config.get("roster_slots", {}),
        "flex_eligible": roster_config.get("flex_eligible", ["rb", "wr", "te"]),
        "bench_size": roster_config.get("bench_size", 6),
        "num_teams": roster_config.get("draft", {}).get("num_teams", 12),
        "scoring_format": args.scoring,
    }

    # --- Write files ---
    print(f"Writing to {OUTPUT_DIR}...")

    with open(OUTPUT_DIR / "players.json", "w") as f:
        json.dump(players, f)
    print(f"  players.json: {len(players)} players")

    with open(OUTPUT_DIR / "scarcity.json", "w") as f:
        json.dump(scarcity_data, f)
    print(f"  scarcity.json: {len(scarcity_data) if isinstance(scarcity_data, list) else 'dict'} entries")

    with open(OUTPUT_DIR / "bye_weeks.json", "w") as f:
        json.dump(bye_data, f)
    print(f"  bye_weeks.json: {len(bye_data)} teams")

    with open(OUTPUT_DIR / "sleepers_busts.json", "w") as f:
        json.dump(sb_data, f)

    with open(OUTPUT_DIR / "roster_config.json", "w") as f:
        json.dump(roster_data, f)

    # --- Model accuracy summary ---
    vr = pipeline.validation_results
    accuracy = {}
    if vr is not None and not vr.empty:
        for pos in ["QB", "RB", "WR", "TE"]:
            pos_vr = vr[vr["position"] == pos]
            if not pos_vr.empty:
                best = pos_vr.loc[pos_vr["mae"].idxmin()]
                accuracy[pos] = {
                    "best_model": best["model"],
                    "mae": round(float(best["mae"]), 2),
                    "rmse": round(float(best["rmse"]), 2),
                    "r2": round(float(best["r2"]), 4),
                }

    with open(OUTPUT_DIR / "accuracy.json", "w") as f:
        json.dump(sanitize(accuracy), f)
    print(f"  accuracy.json: {len(accuracy)} positions")

    print("\nDone! All static data files written.")


if __name__ == "__main__":
    main()
