"""Per-position model pipeline: train and predict separate models for QB, RB, WR, TE.

Each position gets its own model with position-specific feature subsets,
trained via walk-forward validation. The pipeline orchestrates the full
train/predict cycle.
"""
import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path
from pandas.api.types import is_numeric_dtype

from src.models.base import FantasyModel
from src.models.catboost_model import CatBoostModel, POSITION_CATBOOST_PARAMS, POSITION_TEMPORAL_WEIGHTS
from src.models.ensemble import StackedEnsembleModel
from src.models.compare import walk_forward_validate, summarize_comparison
from src.features.engineer import get_feature_columns


# Position-specific feature groups
POSITION_FEATURES = {
    "QB": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "passing_yards_lag1", "passing_yards_lag2", "passing_yards_roll3",
        "passing_tds_lag1", "passing_tds_lag2",
        "interceptions_lag1",
        "ol_pass_block_quality_lag1",
        "rushing_yards_lag1", "rushing_tds_lag1",
        # Regression features (lagged to prevent leakage)
        "pts_lag1", "yoy_change_injury_adj_lag1", "yoy_pct_change_injury_adj_lag1", "regression_risk_injury_adj_lag1", "is_breakout_lag1", "is_bust_injury_adj_lag1",
        "pts_roll2", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back_lag1",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS & rookie features (lagged to prevent leakage)
        "def_rank_lag1", "pass_def_rank_lag1", "is_rookie", "is_2nd_year",
        # Playmaker
        "pts_per_target_lag1",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_pass_yds_per_game", "college_pass_td_per_game",
        "college_rush_yds_per_game", "early_declare", "p5_conference",
        # College × experience interaction (supplements missing lag features)
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
        # Combine data availability flag
        "has_combine_data",
        # Depth chart role (pre-season snapshot)
        "depth_rank", "is_starter", "is_backup",
        # NOTE: coaching features (new_hc, hc_tenure_years) tested and rejected —
        # added noise for RB/TE. Team context features already capture HC signal.
        # ADP-derived market shape/value features.
        "adp_log", "adp_inverse", "is_top12_adp", "is_top24_adp", "is_top48_adp",
        "is_late_or_undrafted_adp", "adp_minus_pts_lag1", "pts_lag1_per_adp",
        "fp_per_game_lag1_per_adp", "age_x_adp",
        # Validated nflverse cached-source additions.
        "snap_offense_snaps_lag1", "snap_offense_pct_lag1",
        "snap_games_lag1", "snap_offense_snaps_per_game_lag1",
        "games_lag2", "games_roll2", "games_roll3",
        "missed_games_lag1", "missed_games_roll2", "played_15plus_lag1",
    ],
    "RB": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "rb_age_risk",
        "rushing_yards_lag1", "rushing_yards_lag2", "rushing_yards_roll3",
        "rushing_tds_lag1", "rushing_tds_lag2",
        "receiving_yards_lag1", "targets_lag1", "receptions_lag1",
        "targets_per_game_lag1",
        "rb_share_of_team_rush_lag1", "rb_share_of_team_rush_td_lag1",
        "ol_quality_tier_lag1",
        # Regression features (lagged to prevent leakage)
        "pts_lag1", "yoy_change_injury_adj_lag1", "yoy_pct_change_injury_adj_lag1", "regression_risk_injury_adj_lag1", "is_breakout_lag1", "is_bust_injury_adj_lag1",
        "pts_roll2", "rec_td_rate_lag1", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back_lag1",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS & rookie features (lagged to prevent leakage)
        "def_rank_lag1", "is_rookie", "is_2nd_year",
        "schedule_opp_def_rank", "schedule_top8_def_games",
        "schedule_bottom8_def_games", "schedule_division_games",
        "schedule_rest_advantage",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_rush_yds_per_game", "college_rush_td_per_game",
        "college_rec_per_game", "combine_forty", "early_declare", "p5_conference",
        # College × experience interaction
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
        # Combine data availability flag
        "has_combine_data",
        # NOTE: depth_rank not included for RB — RBBC (running back by committee)
        # means depth chart labels are unreliable (e.g., Gibbs as "RB2" had 369 pts).
        # Teammate competition (current roster + prior-season volume)
        "teammate_carries_prev",
        # ADP-derived market shape/value features.
        "adp_log", "adp_inverse", "is_top12_adp", "is_top24_adp", "is_top48_adp",
        "is_late_or_undrafted_adp", "adp_minus_pts_lag1", "pts_lag1_per_adp",
        "fp_per_game_lag1_per_adp", "age_x_adp",
        # Validated nflverse draft pick value interactions.
        "draft_value_otc_x_rookie", "draft_value_pff_x_rookie",
    ],
    "WR": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "receiving_yards_lag1", "receiving_yards_lag2", "receiving_yards_roll3",
        "receiving_tds_lag1", "receiving_tds_lag2",
        "targets_lag1", "targets_lag2",
        "receptions_lag1",
        "target_share_lag1", "yards_per_target_lag1", "catch_rate_lag1",
        "targets_per_game_lag1", "rec_td_rate_lag1",
        # Regression features (lagged to prevent leakage)
        "pts_lag1", "yoy_change_injury_adj_lag1", "yoy_pct_change_injury_adj_lag1", "regression_risk_injury_adj_lag1", "is_breakout_lag1", "is_bust_injury_adj_lag1",
        "pts_roll2", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back_lag1",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS, stacking & rookie features (lagged to prevent leakage)
        "pass_def_rank_lag1", "qb_stack_bonus", "team_qb_avg_pts", "is_rookie", "is_2nd_year",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_rec_yds_per_game", "college_rec_td_per_game",
        "college_rush_yds_per_game", "combine_forty", "early_declare", "p5_conference",
        # College × experience interaction
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
        # Combine data availability flag
        "has_combine_data",
        # Depth chart role (pre-season snapshot)
        "depth_rank", "is_starter", "is_backup",
        # Teammate competition (current roster + prior-season volume)
        "teammate_targets_prev", "teammate_rec_yards_prev",
        # Lagged Next Gen Stats receiving efficiency.
        "ngs_receiving_catch_percentage_lag1",
        # Prior-season availability trend.
        "games_lag2", "games_roll2", "games_roll3",
        "missed_games_lag1", "missed_games_roll2", "played_15plus_lag1",
        # ADP-derived market shape/value features.
        "adp_log", "adp_inverse", "is_top12_adp", "is_top24_adp", "is_top48_adp",
        "is_late_or_undrafted_adp", "adp_minus_pts_lag1", "pts_lag1_per_adp",
        "fp_per_game_lag1_per_adp", "age_x_adp",
        # Validated nflverse draft pick value interactions.
        "draft_value_otc_x_rookie", "draft_value_pff_x_rookie",
        # Prior-year contract status; tested as WR-only.
        "contract_years_prev", "contract_years_elapsed_prev",
        "contract_years_remaining_prev", "contract_is_active_prev",
        "contract_year_flag_prev",
    ],
    "TE": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "receiving_yards_lag1", "receiving_yards_lag2", "receiving_yards_roll3",
        "receiving_tds_lag1",
        "targets_lag1", "targets_lag2",
        "receptions_lag1",
        "target_share_lag1", "yards_per_target_lag1", "catch_rate_lag1",
        "targets_per_game_lag1", "rec_td_rate_lag1",
        "receiving_epa_lag1", "receiving_air_yards_lag1",
        "receiving_yards_after_catch_lag1", "receiving_first_downs_lag1",
        "air_yards_share_lag1", "wopr_lag1", "racr_lag1", "pts_per_target_lag1",
        # Regression features (lagged to prevent leakage)
        "pts_lag1", "yoy_change_injury_adj_lag1", "yoy_pct_change_injury_adj_lag1", "regression_risk_injury_adj_lag1", "is_breakout_lag1", "is_bust_injury_adj_lag1",
        "pts_roll2", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back_lag1",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS, stacking & rookie features (lagged to prevent leakage)
        "pass_def_rank_lag1", "qb_stack_bonus", "team_qb_avg_pts", "is_rookie", "is_2nd_year",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_rec_yds_per_game", "college_rec_td_per_game",
        "combine_forty", "early_declare", "p5_conference",
        # College × experience interaction
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
        # Combine data availability flag
        "has_combine_data",
        # Depth chart role (pre-season snapshot)
        "depth_rank", "is_starter", "is_backup",
        # NOTE: teammate competition NOT used for TE — most teams have only 1
        # meaningful TE, so the signal is dominated by WR target share which is
        # already captured by other features. Adding it caused +2% TE MAE.
        # ADP-derived age/market interaction.
        "age_x_adp",
        "adp_log", "adp_inverse", "is_top12_adp", "is_top24_adp", "is_top48_adp",
        "is_late_or_undrafted_adp", "adp_minus_pts_lag1", "pts_lag1_per_adp",
        "fp_per_game_lag1_per_adp",
        # Prior-year contract value/status; tested as TE-only.
        "contract_apy_cap_pct_prev", "contract_apy_log_prev",
        "contract_guaranteed_log_prev", "contract_guaranteed_pct_prev",
        "contract_years_prev", "contract_years_elapsed_prev",
        "contract_years_remaining_prev", "contract_is_active_prev",
        "contract_year_flag_prev",
    ],
}

OFFENSIVE_POSITIONS = ["QB", "RB", "WR", "TE"]


def get_position_features(position: str, available_cols: list[str]) -> list[str]:
    """Get feature columns for a position, filtered to only those present in data."""
    preferred = POSITION_FEATURES.get(position, [])
    # Only use features that actually exist in the data
    usable = [f for f in preferred if f in available_cols]

    # If very few preferred features exist, fall back to all numeric features
    if len(usable) < 5:
        usable = [c for c in available_cols if c not in [
            "player_id", "player_name", "team", "season", "position",
            "fantasy_points", "fantasy_points_per_game",
        ]]

    return usable


def _numeric_feature_cols(df: pd.DataFrame, feature_cols: list[str]) -> list[str]:
    """Keep CatBoost feature columns numeric and stable across pandas dtypes."""
    return [c for c in feature_cols if c in df.columns and is_numeric_dtype(df[c])]


def _clean_feature_matrix(X: pd.DataFrame) -> pd.DataFrame:
    """CatBoost input hygiene: numeric columns only, no inf, deterministic NaNs."""
    return X.replace([np.inf, -np.inf], np.nan).fillna(0)


def _provider_id(value) -> str:
    """Serialize nullable numeric/string provider IDs consistently."""
    if value is None or pd.isna(value):
        return ""
    result = str(value).strip()
    return result[:-2] if result.endswith(".0") and result[:-2].isdigit() else result


class PositionPipeline:
    """Orchestrates per-position model training and prediction.

    For each position:
    1. Filter data to that position
    2. Select position-specific features
    3. Walk-forward validate to pick best model
    4. Train final model on all available data
    5. Generate next-season projections
    """

    def __init__(self, models: Optional[list[FantasyModel]] = None, use_ensemble: bool = False,
                 use_tuned_catboost: bool = True, use_conformal: bool = True, conformal_alpha: float = 0.2):
        self.models = models or [CatBoostModel()]
        self.use_ensemble = use_ensemble
        self.use_tuned_catboost = use_tuned_catboost
        self.use_conformal = use_conformal
        self.conformal_alpha = conformal_alpha
        self.best_models: dict[str, FantasyModel] = {}
        self.quantile_models: dict = {}  # pos -> ConformalQuantileModel
        self.validation_results: Optional[pd.DataFrame] = None

    def _get_models_for_position(self, pos: str) -> list[FantasyModel]:
        """Get model list, substituting per-position tuned CatBoost if enabled."""
        if not self.use_tuned_catboost or pos not in POSITION_CATBOOST_PARAMS:
            return self.models
        tuned_params = POSITION_CATBOOST_PARAMS[pos]
        models = []
        for m in self.models:
            if isinstance(m, CatBoostModel):
                models.append(CatBoostModel(**tuned_params))
            else:
                models.append(m)
        return models

    def validate_all(
        self,
        df: pd.DataFrame,
        target_col: str = "fantasy_points",
        season_col: str = "season",
        min_train_seasons: int = 3,
    ) -> pd.DataFrame:
        """Run walk-forward validation for each position and model.

        Returns combined validation results. Stores best model per position.
        """
        all_results = []
        available_cols = list(df.columns)

        for pos in OFFENSIVE_POSITIONS:
            pos_df = df[df["position"] == pos].copy()
            if len(pos_df) < 20:
                print(f"Skipping {pos}: only {len(pos_df)} rows")
                continue

            feat_cols = get_position_features(pos, available_cols)
            # Filter to features that exist and are numeric
            feat_cols = _numeric_feature_cols(pos_df, feat_cols)

            if not feat_cols:
                print(f"Skipping {pos}: no valid features")
                continue

            print(f"\n=== {pos} ({len(pos_df)} rows, {len(feat_cols)} features) ===")

            pos_models = self._get_models_for_position(pos)
            temporal_weight = POSITION_TEMPORAL_WEIGHTS.get(pos, 0.0) if self.use_tuned_catboost else 0.0
            for model in pos_models:
                print(f"  Validating: {model.name}...")
                results = walk_forward_validate(
                    model, pos_df, feat_cols, target_col,
                    season_col=season_col, position_col=None,
                    min_train_seasons=min_train_seasons,
                    temporal_weight=temporal_weight,
                )
                if not results.empty:
                    results["position"] = pos
                    all_results.append(results)

        if not all_results:
            return pd.DataFrame()

        combined = pd.concat(all_results, ignore_index=True)
        self.validation_results = combined

        # Pick best model per position (lowest MAE)
        summary = summarize_comparison(combined)
        for pos in OFFENSIVE_POSITIONS:
            if self.use_ensemble:
                # Use stacked ensemble for production (combines all base models)
                self.best_models[pos] = StackedEnsembleModel()
            else:
                pos_summary = summary[summary["position"] == pos]
                if not pos_summary.empty:
                    best_name = pos_summary.iloc[0]["model"]
                    pos_models = self._get_models_for_position(pos)
                    for m in pos_models:
                        if m.name == best_name:
                            self.best_models[pos] = m
                            break

        return combined

    def train_final(
        self,
        df: pd.DataFrame,
        target_col: str = "fantasy_points",
        temporal_weight: float = 0.15,
    ) -> dict[str, FantasyModel]:
        """Train final models on all available data using best model per position.

        Args:
            temporal_weight: Default decay rate for older seasons. Overridden by
                per-position POSITION_TEMPORAL_WEIGHTS when use_tuned_catboost is enabled.
                0 = no weighting, higher = more aggressive discounting of old data.
        """
        available_cols = list(df.columns)
        trained = {}

        for pos in OFFENSIVE_POSITIONS:
            if pos not in self.best_models:
                # Default to ensemble if enabled, else CatBoost.
                self.best_models[pos] = StackedEnsembleModel() if self.use_ensemble else CatBoostModel()

            pos_df = df[df["position"] == pos].copy()
            feat_cols = get_position_features(pos, available_cols)
            feat_cols = _numeric_feature_cols(pos_df, feat_cols)

            if not feat_cols or pos_df.empty:
                continue

            # Fill NaN features with 0, only train on rows with actual fantasy points
            # (exclude projection-season rows which have fantasy_points=0)
            X = _clean_feature_matrix(pos_df[feat_cols])
            valid = pos_df[target_col].notna() & np.isfinite(pos_df[target_col])
            X = X[valid]
            y = pos_df.loc[valid, target_col]

            if X.empty:
                continue

            # Compute sample weights: recent seasons weighted more heavily
            # Combats concept drift (rule changes, usage patterns shift over time)
            # Use per-position tuned weights when available
            tw = POSITION_TEMPORAL_WEIGHTS.get(pos, temporal_weight) if self.use_tuned_catboost else temporal_weight
            sample_weight = None
            if "season" in pos_df.columns and tw > 0:
                seasons = pd.to_numeric(pos_df.loc[valid, "season"], errors="raise")
                max_season = seasons.max()
                years_ago = (max_season - seasons).to_numpy(dtype=float)
                # Exponential decay: most recent season = 1.0, each year older decays
                sample_weight = np.exp(-tw * years_ago)

            # Fresh model instance via deepcopy
            import copy
            model = copy.deepcopy(self.best_models[pos])
            if hasattr(model, 'model'):
                model.model = None
            model.fit(X, y, sample_weight=sample_weight)
            trained[pos] = model
            print(f"Trained {model.name} for {pos} on {len(X)} rows")

            # Train conformal quantile model for calibrated CIs
            if self.use_conformal and "season" in pos_df.columns:
                try:
                    from src.models.conformal import ConformalQuantileModel
                    seasons_series = pos_df.loc[valid, "season"].reset_index(drop=True)
                    cat_params = POSITION_CATBOOST_PARAMS.get(pos, {}) if self.use_tuned_catboost else {}
                    cqr = ConformalQuantileModel(alpha=self.conformal_alpha, cat_params=cat_params)
                    cqr.fit(X.reset_index(drop=True), y.reset_index(drop=True),
                            seasons=seasons_series, sample_weight=sample_weight)
                    self.quantile_models[pos] = cqr
                    ec = cqr.empirical_coverage
                    print(f"  CQR {pos}: Q={cqr.Q:.2f}, n_cal={ec['n_cal']}, "
                          f"cal-coverage {ec['pre_conformal']*100:.0f}% → {ec['post_conformal']*100:.0f}% (target {ec['target']*100:.0f}%)")
                except Exception as e:
                    print(f"  CQR {pos}: failed ({e})")

        self.best_models = trained
        return trained

    def predict(
        self,
        df: pd.DataFrame,
        target_season: int,
    ) -> pd.DataFrame:
        """Generate fantasy point projections for a target season.

        Uses the trained per-position models to predict next-season
        fantasy points for all players in the target season.
        Also computes uncertainty via ensemble variance across all models.
        """
        available_cols = list(df.columns)
        projections = []

        # Determine which season to predict for
        if "season" in df.columns:
            latest_season = df["season"].max()
            predict_df = df[df["season"] == latest_season].copy()
        else:
            predict_df = df.copy()

        for pos in OFFENSIVE_POSITIONS:
            if pos not in self.best_models:
                continue

            pos_mask = predict_df["position"] == pos
            predict_pos = predict_df[pos_mask].copy()

            if predict_pos.empty:
                continue

            feat_cols = get_position_features(pos, available_cols)
            feat_cols = _numeric_feature_cols(predict_df, feat_cols)

            # Fill NaN features with 0 for prediction
            X = _clean_feature_matrix(predict_pos[feat_cols])

            # Best model prediction
            best_preds = self.best_models[pos].predict(X)

            # Ensemble predictions for uncertainty estimation
            all_preds = [best_preds]
            for m in self.models:
                if m.name == self.best_models[pos].name:
                    continue
                try:
                    import copy
                    # Use the trained model if available, otherwise skip
                    if pos in self.best_models and hasattr(self.best_models[pos], 'predict'):
                        # We need all models trained — train them on the fly
                        pass
                except Exception:
                    pass

            # Simpler approach: use all 3 models trained on same data
            ensemble_preds = {}
            for m in self.models:
                try:
                    import copy
                    m_clone = copy.deepcopy(m)
                    if hasattr(m_clone, 'model'):
                        m_clone.model = None
                    # Quick train on same data as best model
                    pos_df = df[df["position"] == pos]
                    X_train = _clean_feature_matrix(pos_df[feat_cols])
                    valid = pos_df["fantasy_points"].notna() & np.isfinite(pos_df["fantasy_points"])
                    if "season" in pos_df.columns:
                        valid &= pos_df["season"] < target_season
                    X_train = X_train[valid]
                    y_train = pos_df.loc[valid, "fantasy_points"]
                    if not X_train.empty:
                        m_clone.fit(X_train, y_train)
                        ensemble_preds[m.name] = m_clone.predict(X)
                except Exception:
                    pass

            # Add best model to ensemble
            ensemble_preds[self.best_models[pos].name] = best_preds

            # Compute uncertainty: std of ensemble predictions
            if len(ensemble_preds) > 1:
                pred_matrix = np.column_stack(list(ensemble_preds.values()))
                pred_std = np.std(pred_matrix, axis=1)
                pred_mean = np.mean(pred_matrix, axis=1)
            else:
                pred_std = np.zeros(len(best_preds))
                pred_mean = best_preds

            # Conformal quantile intervals (calibrated ~80% coverage) —
            # replaces the ad-hoc ensemble-std 1.28σ approximation when available.
            cqr = self.quantile_models.get(pos) if self.use_conformal else None
            if cqr is not None:
                try:
                    cqr_lo, cqr_hi = cqr.predict_interval(X)
                except Exception:
                    cqr_lo = cqr_hi = None
            else:
                cqr_lo = cqr_hi = None

            for i, (_, row) in enumerate(predict_pos.iterrows()):
                proj_pts = float(pred_mean[i])

                # Post-prediction regression adjustment:
                # If player is coming off a breakout (>30% above 2yr avg),
                # shrink projection toward their recent average.
                # Use lagged features to prevent leakage (previous season's regression risk)
                regression_risk = row.get("regression_risk_lag1", 0) or row.get("regression_risk", 0)
                is_breakout = row.get("is_breakout_lag1", 0) or row.get("is_breakout", 0)
                pts_roll2 = row.get("pts_roll2", 0)

                if is_breakout and regression_risk > 30 and pts_roll2 > 0:
                    # Shrink 30% toward 2-year rolling average
                    shrinkage = 0.3
                    proj_pts = proj_pts * (1 - shrinkage) + pts_roll2 * shrinkage

                # RB age cliff: reduce projections for RBs over 28
                if pos == "RB" and row.get("age", 0) >= 28:
                    age_penalty = 0.97 ** (row["age"] - 27)  # ~3% per year over 27
                    proj_pts *= age_penalty

                # Shrink fringe players: if prior year was <10 pts and projection is >3x that,
                # they're likely a backup getting overprojected
                pts_lag1 = row.get("pts_lag1", 0) or 0
                if pts_lag1 > 0 and pts_lag1 < 10 and proj_pts > pts_lag1 * 3:
                    # Shrink toward prior year — these are backups, not breakout candidates
                    shrinkage = 0.5
                    proj_pts = proj_pts * (1 - shrinkage) + pts_lag1 * shrinkage

                # Floor at 0
                proj_pts = max(proj_pts, 0)

                # Widen uncertainty for rookies/2nd-year players (less historical data)
                is_rookie = row.get("is_rookie", 0)
                is_2nd_year = row.get("is_2nd_year", 0)
                rookie_multiplier = 1.0
                if is_rookie:
                    rookie_multiplier = 1.8  # 80% wider CI for rookies
                elif is_2nd_year:
                    rookie_multiplier = 1.3  # 30% wider for 2nd year

                std = float(pred_std[i]) if i < len(pred_std) else 0

                # Prefer calibrated CQR intervals (~80% coverage guarantee);
                # fall back to ensemble-std 1.28σ approximation when unavailable.
                if cqr_lo is not None and cqr_hi is not None and i < len(cqr_lo):
                    # Recenter CQR interval on the post-shrinkage proj_pts so the
                    # width reflects uncertainty around the actual point prediction.
                    half_width = (float(cqr_hi[i]) - float(cqr_lo[i])) / 2.0
                    half_width *= rookie_multiplier
                    ci_low = max(proj_pts - half_width, 0)
                    ci_high = proj_pts + half_width
                    interval_source = "cqr"
                else:
                    std_eff = std * rookie_multiplier
                    ci_low = max(proj_pts - 1.28 * std_eff, 0)
                    ci_high = proj_pts + 1.28 * std_eff
                    interval_source = "ensemble_std"

                # Risk tier computed LATER via position-relative percentiles (after all
                # projections are built). Store raw rel_width and placeholder now.
                if proj_pts > 0:
                    rel_width = (ci_high - ci_low) / proj_pts
                else:
                    rel_width = 99.0
                risk = "medium"  # placeholder — overwritten in post-processing below

                projections.append({
                    "player_id": row.get("player_id", f"player_{i}"),
                    "sleeper_id": _provider_id(row.get("sleeper_id", "")),
                    "player_name": row.get("player_name") or row.get("football_name") or row.get("player_display_name", ""),
                    "position": pos,
                    "team": row.get("team", ""),
                    "projected_points": round(proj_pts, 1),
                    "ci_low": round(ci_low, 1),
                    "ci_high": round(ci_high, 1),
                    "uncertainty": round(std, 1),
                    "risk": risk,
                    "rel_width": round(rel_width, 3),
                    "interval_source": interval_source,
                    "adp": row.get("adp", 200),
                    "pts_lag1": row.get("pts_lag1", 0) or 0,
                    "is_rookie": int(row.get("is_rookie", 0) or 0),
                    "is_2nd_year": int(row.get("is_2nd_year", 0) or 0),
                    "model_used": f"ensemble({'+'.join(ensemble_preds.keys())})" if len(ensemble_preds) > 1 else self.best_models[pos].name,
                })

        result = pd.DataFrame(projections)
        if result.empty:
            return result

        # === Position-relative risk tiers ===
        # Absolute rel_width thresholds over-penalize high-variance positions (QB)
        # and under-penalize low-variance ones (TE). Use within-position quartiles:
        # bottom 25% rel_width → low, top 25% → high, middle 50% → medium. Only
        # rank players with meaningful projections (> position-specific min) so
        # depth-chart afterthoughts don't crowd the tiering.
        result["risk"] = "medium"
        min_proj_for_tier = {"QB": 50, "RB": 30, "WR": 30, "TE": 20}
        for pos in OFFENSIVE_POSITIONS:
            mask = (result["position"] == pos) & (result["projected_points"] >= min_proj_for_tier.get(pos, 20))
            if mask.sum() < 4:
                continue
            sub = result.loc[mask, "rel_width"]
            q25, q75 = sub.quantile(0.25), sub.quantile(0.75)
            low_mask = mask & (result["rel_width"] <= q25)
            high_mask = mask & (result["rel_width"] >= q75)
            result.loc[low_mask, "risk"] = "low"
            result.loc[high_mask, "risk"] = "high"
            # Everything else stays "medium"

        # Players below the per-position min_proj are low-impact; label them "high"
        # since backups are inherently uncertain and shouldn't rank as "low"
        for pos, min_p in min_proj_for_tier.items():
            low_vol = (result["position"] == pos) & (result["projected_points"] < min_p)
            result.loc[low_vol, "risk"] = "high"

        return result
