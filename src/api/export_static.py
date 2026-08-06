"""Export all draft data as static JSON files for a serverless deployment.

Run this script to regenerate the data files:
    python -m src.api.export_static --seasons 5 --scoring half_ppr

Outputs to src/api/static/data/
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "static" / "data"


NON_TRANSFORMER_PROJECTION_BY_POSITION = {
    # Conservative fallback while historical ADP snapshots are rebuilt. The
    # market-residual QB/RB variants only won on the contaminated 2025 fold.
    "QB": "cat_direct",
    "RB": "cat_direct",
    "WR": "cat_direct",
    "TE": "cat_direct",
}


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


def build_projection_season_scaffold(
    seasonal: pd.DataFrame,
    roster: pd.DataFrame,
    projection_season: int,
    extra_players: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Append raw, zero-stat projection rows before feature engineering.

    This is the train/serve contract: a projection row enters the same lag,
    rolling, schedule, injury, and context pipeline as a historical test row.
    Engineered prior-season rows must never be cloned into the target season.
    """
    if seasonal.empty or roster.empty or "player_id" not in roster.columns:
        return seasonal, roster

    roster_out = roster.copy().dropna(axis=1, how="all")
    extras = extra_players.copy() if extra_players is not None else pd.DataFrame()
    if not extras.empty:
        # Prefer GSIS as the stable cross-source identifier when Sleeper has it.
        if "gsis_id" in extras.columns:
            gsis = extras["gsis_id"].fillna("").astype(str).str.strip()
            extras.loc[gsis.ne(""), "player_id"] = gsis[gsis.ne("")]
        extras["season"] = projection_season
        if "status" in roster_out.columns:
            extras["status"] = "ACT"

        current = roster_out[roster_out["season"].eq(projection_season)].copy()
        if "status" in current.columns and current["status"].notna().any():
            current = current[current["status"].astype(str).str.upper().isin({"ACT", "ACTIVE"})]
        existing_ids = set(current["player_id"].dropna().astype(str))
        existing_sleeper_ids = (
            set(current["sleeper_id"].dropna().astype(str).str.replace(r"\.0$", "", regex=True))
            if "sleeper_id" in current.columns
            else set()
        )

        def _norm_names(series: pd.Series) -> pd.Series:
            return (
                series.fillna("").astype(str).str.lower()
                .str.replace(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", regex=True)
                .str.replace(r"[^a-z ]", "", regex=True)
                .str.replace(r"\s+", " ", regex=True).str.strip()
            )

        name_col = next((c for c in ("player_name", "football_name") if c in current.columns), None)
        extra_name_col = next((c for c in ("player_name", "football_name") if c in extras.columns), None)
        existing_names = set(_norm_names(current[name_col])) if name_col else set()
        extra_names = _norm_names(extras[extra_name_col]) if extra_name_col else pd.Series("", index=extras.index)
        keep = ~extras["player_id"].astype(str).isin(existing_ids) & ~extra_names.isin(existing_names)
        if "sleeper_id" in extras.columns and existing_sleeper_ids:
            extra_sleeper_ids = (
                extras["sleeper_id"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
            )
            keep &= ~extra_sleeper_ids.isin(existing_sleeper_ids)
        extras = extras[keep].copy()

        if not extras.empty:
            for col in roster_out.columns:
                if col not in extras.columns:
                    extras[col] = pd.NA
            extras = extras[roster_out.columns]
            roster_out = pd.concat(
                [roster_out, extras.dropna(axis=1, how="all")],
                ignore_index=True,
            )

    current = roster_out[roster_out["season"].eq(projection_season)].copy()
    if "status" in current.columns and current["status"].notna().any():
        current = current[current["status"].astype(str).str.upper().isin({"ACT", "ACTIVE"})]
    if "position" in current.columns:
        current = current[current["position"].isin(["QB", "RB", "WR", "TE"])]
    current = current.dropna(subset=["player_id"]).drop_duplicates("player_id", keep="last")
    if current.empty:
        raise ValueError(f"No projection roster rows available for {projection_season}")

    stub = pd.DataFrame(index=range(len(current)), columns=seasonal.columns)
    for col in seasonal.columns:
        if pd.api.types.is_numeric_dtype(seasonal[col]):
            stub[col] = 0
        else:
            stub[col] = pd.NA

    identity_cols = [
        "player_id", "player_name", "football_name", "first_name", "last_name",
        "position", "team", "age", "entry_year", "rookie_year",
        "years_exp", "sleeper_id",
    ]
    for col in identity_cols:
        if col in stub.columns and col in current.columns:
            stub[col] = current[col].values
    stub["season"] = projection_season
    if "games" in stub.columns:
        stub["games"] = 0

    historical = seasonal[~seasonal["season"].eq(projection_season)].copy()
    seasonal_out = pd.concat([historical, stub], ignore_index=True)
    print(f"  Raw {projection_season} projection scaffold: {len(stub)} players")
    return seasonal_out, roster_out


def summarize_validation_accuracy(
    validation_results: pd.DataFrame | None,
    quantile_models: dict | None = None,
) -> dict:
    """Aggregate every walk-forward fold for the exact validated base model."""
    if validation_results is None or validation_results.empty:
        return {}

    quantile_models = quantile_models or {}
    accuracy = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        pos_rows = validation_results[validation_results["position"].eq(pos)].copy()
        if pos_rows.empty:
            continue

        candidates = []
        for model_name, model_rows in pos_rows.groupby("model"):
            weights = pd.to_numeric(model_rows.get("n_players", 1), errors="coerce").fillna(1).clip(lower=1)
            candidates.append({
                "model": model_name,
                "mae": float(np.average(model_rows["mae"], weights=weights)),
                "rmse": float(np.sqrt(np.average(np.square(model_rows["rmse"]), weights=weights))),
                "r2": float(np.average(model_rows["r2"], weights=weights)),
                "n_players": int(weights.sum()),
                "test_seasons": sorted(int(s) for s in model_rows["season"].unique()),
            })
        best = min(candidates, key=lambda row: row["mae"])
        entry = {
            "best_model": best["model"],
            "mae": round(best["mae"], 2),
            "rmse": round(best["rmse"], 2),
            "r2": round(best["r2"], 4),
            "n_players": best["n_players"],
            "test_seasons": best["test_seasons"],
            "aggregation": "player_weighted_walk_forward_folds",
        }
        cqr = quantile_models.get(pos)
        if cqr is not None:
            entry["interval"] = {
                "method": "split_conformal_cqr",
                "target_coverage": round(1.0 - float(cqr.alpha), 3),
                "calibration_season": cqr.cal_season,
                "calibration_n": int(cqr.n_cal),
            }
        accuracy[pos] = entry
    return accuracy


def apply_current_adp_to_projection_rows(df, adp_data, projection_season):
    """Overwrite projection-season ADP features with current draft-market ADP."""
    if adp_data is None or adp_data.empty or "season" not in adp_data.columns:
        return df
    if "player_name" not in df.columns or "position" not in df.columns:
        return df

    current = adp_data[adp_data["season"] == projection_season].copy()
    if current.empty or "adp" not in current.columns:
        return df

    def norm_name(s):
        s = pd.Series(s).astype(str).str.lower().str.strip()
        s = s.str.replace(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", regex=True)
        s = s.str.replace("'", "", regex=False).str.replace("-", "", regex=False)
        s = s.str.replace(".", "", regex=False)
        return s

    current["_adp_key"] = norm_name(current["player_name"]) + "|" + current["position"].astype(str).str.upper()
    current = current.dropna(subset=["adp"]).drop_duplicates("_adp_key", keep="first")

    out = df.copy()
    out["_adp_key"] = norm_name(out["player_name"]) + "|" + out["position"].astype(str).str.upper()
    adp_map = current.set_index("_adp_key")["adp"]
    cur_adp = out["_adp_key"].map(adp_map)
    matched = cur_adp.notna()
    if matched.any():
        out.loc[matched, "adp"] = cur_adp[matched].clip(upper=200)
    if "adp" in out.columns:
        out["adp"] = pd.to_numeric(out["adp"], errors="coerce")
        out.loc[out["adp"].isna() | (out["adp"] <= 0), "adp"] = 200
        out["adp"] = out["adp"].clip(upper=200)
    if "adp" in out.columns:
        out["adp_tier"] = pd.cut(
            out["adp"], bins=[0, 12, 24, 48, 100, 300],
            labels=[1, 2, 3, 4, 5],
        ).astype(float).fillna(5)
        out["adp_log"] = np.log1p(out["adp"])
        out["adp_inverse"] = 1 / out["adp"].clip(lower=1)
        out["is_top12_adp"] = (out["adp"] <= 12).astype(int)
        out["is_top24_adp"] = (out["adp"] <= 24).astype(int)
        out["is_top48_adp"] = (out["adp"] <= 48).astype(int)
        out["is_late_or_undrafted_adp"] = (out["adp"] >= 150).astype(int)
        pts_lag = pd.to_numeric(out["pts_lag1"], errors="coerce").fillna(0) if "pts_lag1" in out.columns else 0
        fp_pg_lag = pd.to_numeric(out["fp_per_game_lag1"], errors="coerce").fillna(0) if "fp_per_game_lag1" in out.columns else 0
        age = pd.to_numeric(out["age"], errors="coerce").fillna(0) if "age" in out.columns else 0
        out["adp_minus_pts_lag1"] = out["adp"] - pts_lag
        out["pts_lag1_per_adp"] = pts_lag / out["adp"].clip(lower=1)
        out["fp_per_game_lag1_per_adp"] = fp_pg_lag / out["adp"].clip(lower=1)
        out["age_x_adp"] = age * out["adp"]
        print(f"  Current-season ADP applied to projection rows: {int(matched.sum())}")
    return out.drop(columns=["_adp_key"], errors="ignore")


def _clean_projection_features(X):
    return X.replace([np.inf, -np.inf], np.nan).fillna(0)


def _sample_weight(train, pos, temporal_weights):
    decay = temporal_weights.get(pos, 0.0)
    if decay <= 0:
        return None
    seasons = pd.to_numeric(train["season"], errors="raise")
    years_ago = (seasons.max() - seasons).to_numpy(dtype=float)
    return np.exp(-decay * years_ago)


def _fit_market_model(train, adp_cols):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(StandardScaler(), Ridge(alpha=20.0))
    model.fit(_clean_projection_features(train[adp_cols]), train["fantasy_points"])
    return model


def _fit_catboost_residual(train, target, feat_cols, pos):
    from src.models.catboost_model import CatBoostModel, POSITION_CATBOOST_PARAMS, POSITION_TEMPORAL_WEIGHTS

    model = CatBoostModel(**POSITION_CATBOOST_PARAMS.get(pos, {}))
    model.fit(
        _clean_projection_features(train[feat_cols]),
        pd.Series(target),
        sample_weight=_sample_weight(train, pos, POSITION_TEMPORAL_WEIGHTS),
    )
    return model


def _fit_xgboost_residual(train, target, feat_cols, pos):
    from src.models.catboost_model import POSITION_TEMPORAL_WEIGHTS
    from xgboost import XGBRegressor

    model = XGBRegressor(
        n_estimators=350,
        max_depth=3,
        learning_rate=0.035,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=5.0,
        objective="reg:squarederror",
        random_state=42,
        n_jobs=2,
    )
    model.fit(
        _clean_projection_features(train[feat_cols]),
        target,
        sample_weight=_sample_weight(train, pos, POSITION_TEMPORAL_WEIGHTS),
    )
    return model


def _predict_direct(train, test, feat_cols, pos, fit_fn):
    model = fit_fn(train, train["fantasy_points"].to_numpy(dtype=float), feat_cols, pos)
    return np.clip(model.predict(_clean_projection_features(test[feat_cols])), 0, None)


def _predict_market_residual(train, test, feat_cols, adp_cols, pos, fit_fn):
    market = _fit_market_model(train, adp_cols)
    train_market = market.predict(_clean_projection_features(train[adp_cols]))
    test_market = market.predict(_clean_projection_features(test[adp_cols]))
    residual = train["fantasy_points"].to_numpy(dtype=float) - train_market
    residual_model = fit_fn(train, residual, feat_cols, pos)
    pred = test_market + residual_model.predict(_clean_projection_features(test[feat_cols]))
    return np.clip(pred, 0, None)


def apply_validated_non_transformer_predictions(projections, feature_df, target_season):
    """Override point projections with the best validated non-transformer variant.

    The rest of the export still uses the existing CQR intervals, VBD, scarcity,
    and sleepers/busts machinery. Intervals are recentered on the new point
    projection while preserving their calibrated half-width.
    """
    if projections.empty:
        return projections

    from src.models.pipeline import OFFENSIVE_POSITIONS, _numeric_feature_cols, get_position_features

    out = projections.copy()
    adp_features = ["adp", "adp_log", "adp_inverse", "adp_tier"]
    used = {}

    for pos in OFFENSIVE_POSITIONS:
        pos_df = feature_df[feature_df["position"].eq(pos)].copy()
        train = pos_df[(pos_df["season"] < target_season) & pos_df["fantasy_points"].notna()].copy()
        test = pos_df[pos_df["season"].eq(target_season)].copy()
        if train.empty or test.empty:
            continue

        feat_cols = _numeric_feature_cols(pos_df, get_position_features(pos, list(pos_df.columns)))
        adp_cols = [c for c in adp_features if c in pos_df.columns]
        if not feat_cols or not adp_cols:
            continue

        variant = NON_TRANSFORMER_PROJECTION_BY_POSITION.get(pos, "cat_direct")
        preds = {}
        try:
            if variant in ("cat_direct", "blend_cat_xgb_direct"):
                preds["cat_direct"] = _predict_direct(train, test, feat_cols, pos, _fit_catboost_residual)
            if variant in ("xgb_direct", "blend_cat_xgb_direct"):
                preds["xgb_direct"] = _predict_direct(train, test, feat_cols, pos, _fit_xgboost_residual)
            if variant in ("cat_market_residual", "blend_cat_xgb_market_residual"):
                preds["cat_market_residual"] = _predict_market_residual(train, test, feat_cols, adp_cols, pos, _fit_catboost_residual)
            if variant in ("xgb_market_residual", "blend_cat_xgb_market_residual"):
                preds["xgb_market_residual"] = _predict_market_residual(train, test, feat_cols, adp_cols, pos, _fit_xgboost_residual)
        except Exception as exc:
            print(f"  Warning: non-transformer override skipped for {pos}: {exc}")
            continue

        if not preds:
            continue

        pred = np.mean(list(preds.values()), axis=0)
        pred_map = dict(zip(test["player_id"].astype(str), pred))
        mask = out["position"].eq(pos) & out["player_id"].astype(str).isin(pred_map)
        if not mask.any():
            continue

        old_mid = pd.to_numeric(out.loc[mask, "projected_points"], errors="coerce").fillna(0)
        old_low = pd.to_numeric(out.loc[mask, "ci_low"], errors="coerce").fillna(old_mid)
        old_high = pd.to_numeric(out.loc[mask, "ci_high"], errors="coerce").fillna(old_mid)
        half_width = ((old_high - old_low) / 2.0).clip(lower=0)
        new_pred = out.loc[mask, "player_id"].astype(str).map(pred_map).astype(float).clip(lower=0)
        out.loc[mask, "projected_points"] = new_pred.round(1)
        out.loc[mask, "ci_low"] = (new_pred - half_width).clip(lower=0).round(1)
        out.loc[mask, "ci_high"] = (new_pred + half_width).round(1)
        out.loc[mask, "rel_width"] = np.where(new_pred > 0, (2.0 * half_width) / new_pred, 99.0).round(3)
        out.loc[mask, "model_used"] = variant
        used[pos] = variant

    if used:
        print("  Non-transformer projection overrides: " + ", ".join(f"{p}={m}" for p, m in used.items()))

        out["risk"] = "medium"
        for pos, min_proj in {"QB": 50, "RB": 30, "WR": 30, "TE": 20}.items():
            mask = out["position"].eq(pos) & out["projected_points"].ge(min_proj)
            if mask.sum() >= 4:
                q25, q75 = out.loc[mask, "rel_width"].quantile([0.25, 0.75])
                out.loc[mask & out["rel_width"].le(q25), "risk"] = "low"
                out.loc[mask & out["rel_width"].ge(q75), "risk"] = "high"
            out.loc[out["position"].eq(pos) & out["projected_points"].lt(min_proj), "risk"] = "high"

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, default=5)
    parser.add_argument("--scoring", default="half_ppr", choices=["half_ppr", "ppr", "standard"])
    parser.add_argument(
        "--projection-mode",
        default="catboost",
        choices=["catboost", "validated_non_transformer"],
        help="catboost keeps the existing production model; validated_non_transformer applies the best walk-forward residual/direct variants by position.",
    )
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
        compute_depth_chart_features,
        compute_target_competition_features,
    )
    from src.features.college import compute_college_features
    from src.features.contracts import compute_contract_features
    from src.scoring.calculator import add_fantasy_points_to_df
    from src.models.pipeline import PositionPipeline
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

    # Overlay Sleeper API team assignments on the projection season roster.
    # Catches trades/signings that nfl_data_py hasn't ingested yet (Sleeper
    # typically updates within hours; nflverse can lag by days or weeks).
    # Only the projection-season rows are touched — historical seasons stay
    # exactly as nflverse reported them.
    sleeper_players = None
    try:
        from src.data.sleeper_rosters import fetch_sleeper_players
        sleeper_players = fetch_sleeper_players()
    except Exception as e:
        print(f"  Warning: Sleeper roster fetch skipped: {e}")

    try:
        from src.data.sleeper_rosters import apply_sleeper_team_overrides
        print(f"Overlaying Sleeper roster on {projection_season}...")
        roster = apply_sleeper_team_overrides(
            roster,
            target_season=projection_season,
            sleeper=sleeper_players,
        )
    except Exception as e:
        print(f"  Warning: Sleeper overlay skipped: {e}")

    # Add the target-season row at raw player-stat grain. Every lag and rolling
    # feature below is therefore generated by the same code used in backtests.
    try:
        from src.data.sleeper_rookies import fetch_sleeper_projection_players
        extra_players = fetch_sleeper_projection_players(
            projection_season,
            sleeper=sleeper_players,
            verbose=True,
        )
    except Exception as e:
        print(f"  Warning: Sleeper rookie roster fetch skipped: {e}")
        extra_players = pd.DataFrame()
    seasonal, roster = build_projection_season_scaffold(
        seasonal,
        roster,
        projection_season,
        extra_players=extra_players,
    )

    df = build_feature_matrix(
        seasonal,
        roster,
        team,
        ol,
        snap_df=data.get("snap_counts"),
        schedule_df=data.get("schedules"),
        ngs_data=data.get("ngs"),
        pfr_df=data.get("pfr"),
    )
    df = add_fantasy_points_to_df(df, format=args.scoring)
    df = compute_regression_to_mean_features(df)
    df = compute_stacking_features(df)

    try:
        # Fetch ADP for ALL seasons (training rows need their own season's ADP, not just projection season)
        adp_seasons = list(range(min(seasons), projection_season + 1))
        adp_data = fetch_adp_data(seasons=adp_seasons)
        df = compute_adp_features(df, adp_data)
    except Exception as e:
        print(f"  Warning: ADP fetch/merge failed ({e.__class__.__name__}: {e}). Projections will lack ADP feature.")
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
    # Rookie features BEFORE college so interaction features work
    df = compute_rookie_features(df)
    df = compute_teammate_dependency_features(df)

    # College/draft features (critical for rookies, needs is_rookie/is_2nd_year)
    try:
        df = compute_college_features(
            df,
            draft_df=data.get("draft"),
            combine_df=data.get("combine"),
            player_info_df=data.get("player_info"),
            draft_values_df=data.get("draft_values"),
        )
    except Exception as e:
        print(f"  Warning: college features failed ({e.__class__.__name__}: {e}). Rookies will project from base features only.")

    df = compute_contract_features(df, data.get("contracts"))

    # Depth chart features (QB/WR/TE role identification; RB skipped due to RBBC)
    try:
        from src.data.fetch import fetch_depth_charts
        depth_data = fetch_depth_charts(list(range(min(seasons), projection_season + 1)))

        # Overlay Sleeper's current depth chart on the projection season (Level 3
        # freshness). nflverse depth charts reflect the last regular season's
        # Week-1 snapshot; Sleeper reflects today's team depth. Drop any stale
        # projection-season rows from nflverse and replace with Sleeper.
        try:
            from src.data.sleeper_rosters import build_sleeper_depth_chart
            print(f"Overlaying Sleeper depth chart on {projection_season}...")
            sleeper_depth = build_sleeper_depth_chart(
                roster,
                target_season=projection_season,
                sleeper=sleeper_players,
            )
            if not sleeper_depth.empty:
                depth_data = depth_data[depth_data["season"] != projection_season]
                # Align columns before concat
                for col in depth_data.columns:
                    if col not in sleeper_depth.columns:
                        sleeper_depth[col] = pd.NA
                sleeper_depth = sleeper_depth[depth_data.columns]
                depth_data = pd.concat([depth_data, sleeper_depth], ignore_index=True)
        except Exception as e:
            print(f"  Warning: Sleeper depth overlay skipped: {e}")

        df = compute_depth_chart_features(df, depth_data)
    except Exception as e:
        print(f"  Warning: depth chart unavailable: {e}")

    # Target/carry competition features (orthogonal to depth_rank: measures volume available)
    df = compute_target_competition_features(df)

    # --- Train models ---
    historical_df = df[df["season"] < projection_season].copy()
    if historical_df.empty:
        raise RuntimeError("No historical rows available for training")
    print("Training models...")
    pipeline = PositionPipeline(models=[CatBoostModel()])
    pipeline.validate_all(historical_df, min_train_seasons=3)
    pipeline.train_final(historical_df)

    latest_season = int(historical_df["season"].max())
    if not df["season"].eq(projection_season).any():
        raise RuntimeError(f"Projection feature rows for {projection_season} were not built")

    # --- Generate projections ---
    projections = pipeline.predict(df, target_season=projection_season)
    if projections.empty:
        projections = pipeline.predict(df, target_season=latest_season)
    if args.projection_mode == "validated_non_transformer":
        projections = apply_validated_non_transformer_predictions(projections, df, projection_season)

    # ADP is already included by pipeline.predict() via row.get("adp", 200)
    # Just ensure any remaining NaN is filled
    if "adp" in projections.columns:
        projections["adp"] = projections["adp"].fillna(200)

    coverage = {}
    if sleeper_players:
        from src.data.sleeper_rosters import projection_coverage
        coverage = projection_coverage(projections, sleeper_players)
        missing_current = coverage["missing_active_depth_players"]
        if missing_current:
            preview = ", ".join(
                f"{row['player_name']}|{row['position']}"
                for row in missing_current[:8]
            )
            raise RuntimeError(
                "Projection coverage gate failed: "
                f"{len(missing_current)} active depth-chart players missing "
                f"({preview})"
            )
        print(
            "  Projection coverage: "
            f"{coverage['matched_active_depth_players']}/"
            f"{coverage['expected_active_depth_players']} active depth-chart players"
        )

    # --- Add bye weeks to player records from ADP data ---
    if adp_data is not None and not adp_data.empty and "bye" in adp_data.columns:
        bye_map = adp_data[adp_data["bye"] > 0][["team", "bye"]].drop_duplicates("team")
        bye_dict = dict(zip(bye_map["team"], bye_map["bye"]))
        # Add team-code aliases so roster variants (LA/LAR, JAX/JAC, WAS/WSH)
        # all resolve to the FFC bye week. Without this, LA Rams players
        # (team="LA" in nflverse rosters) miss their bye (keyed as "LAR" in FFC).
        _aliases = {"LAR": "LA", "LA": "LAR", "JAC": "JAX", "JAX": "JAC", "WSH": "WAS", "WAS": "WSH"}
        for src, alias in _aliases.items():
            if src in bye_dict and alias not in bye_dict:
                bye_dict[alias] = bye_dict[src]
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

    # --- Add projected receptions for scoring format adjustments ---
    # Use receptions from the latest season (lag1 data) to estimate projected receptions
    rec_col = None
    for col_candidate in ["receptions_lag1", "receptions"]:
        if col_candidate in projections.columns:
            rec_col = col_candidate
            break
    if rec_col:
        projections["projected_receptions"] = projections[rec_col].fillna(0).clip(lower=0).round(0).astype(int)
    else:
        # Estimate by position averages (rec per game * 17)
        pos_rec = {"QB": 5, "RB": 31, "WR": 54, "TE": 48}
        projections["projected_receptions"] = projections["position"].map(pos_rec).fillna(20).astype(int)

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

    # Normalize team-code variants so the frontend lookup works regardless of
    # which convention the roster data uses. FFC uses LAR/LAC/JAC/WSH etc.;
    # nflverse rosters currently use LA/LAC/JAX/WAS. Populate BOTH keys so
    # players.json team codes always resolve.
    TEAM_CODE_ALIASES = {
        "LAR": "LA",    # Rams — FFC uses LAR, nflverse uses LA
        "LA": "LAR",
        "JAC": "JAX",   # Jaguars — FFC uses JAC, nflverse uses JAX
        "JAX": "JAC",
        "WSH": "WAS",   # Commanders — some sources use WSH
        "WAS": "WSH",
    }
    for src, alias in TEAM_CODE_ALIASES.items():
        if src in bye_data and alias not in bye_data:
            bye_data[alias] = bye_data[src]
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
    accuracy = summarize_validation_accuracy(
        pipeline.validation_results,
        quantile_models=pipeline.quantile_models,
    )
    if args.projection_mode != "catboost":
        for entry in accuracy.values():
            entry["projection_mode"] = args.projection_mode
            entry["metric_scope"] = "base_catboost_before_projection_override"

    with open(OUTPUT_DIR / "accuracy.json", "w") as f:
        json.dump(sanitize(accuracy), f)
    print(f"  accuracy.json: {len(accuracy)} positions")

    projection_metadata = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "projection_season": projection_season,
        "scoring": args.scoring,
        "projection_mode": args.projection_mode,
        "skill_players": len(players),
        "coverage": coverage,
    }
    with open(OUTPUT_DIR / "projection_metadata.json", "w") as f:
        json.dump(sanitize(projection_metadata), f)
    print("  projection_metadata.json: coverage passed")

    print("\nDone! All static data files written.")


if __name__ == "__main__":
    main()
