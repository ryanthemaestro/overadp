"""Per-position model pipeline: train and predict separate models for QB, RB, WR, TE.

Each position gets its own model with position-specific feature subsets,
trained via walk-forward validation. The pipeline orchestrates the full
train/predict cycle.
"""
import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path

from src.models.base import FantasyModel
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel
from src.models.compare import walk_forward_validate, summarize_comparison
from src.features.engineer import get_feature_columns


# Position-specific feature groups
POSITION_FEATURES = {
    "QB": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "passing_yards_lag1", "passing_yards_lag2", "passing_yards_roll3",
        "passing_td_lag1", "passing_td_lag2",
        "passing_int_lag1",
        "qb_completion_rate", "team_pass_volume",
        "team_sack_rate", "ol_pass_block_quality",
        "rushing_yards_lag1", "rushing_td_lag1",
        # Regression features
        "pts_lag1", "yoy_change_injury_adj", "yoy_pct_change_injury_adj", "regression_risk_injury_adj", "is_breakout", "is_bust_injury_adj",
        "pts_roll2", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS & rookie features
        "def_rank", "pass_def_rank", "is_rookie", "is_2nd_year",
        # Teammate dependency
        "wr_corps_rank_lag1", "wr_total_pts_lag1",
        # Playmaker
        "pts_per_opportunity_lag1", "pts_per_target_lag1",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_pass_yds_per_game", "college_pass_td_per_game",
        "college_rush_yds_per_game", "early_declare", "p5_conference",
        # College × experience interaction (supplements missing lag features)
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
    ],
    "RB": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "rb_age_risk",
        "rushing_yards_lag1", "rushing_yards_lag2", "rushing_yards_roll3",
        "rushing_tds_lag1", "rushing_tds_lag2",
        "rushing_attempts_lag1",
        "receiving_yards_lag1", "targets_lag1", "receptions_lag1",
        "rush_att_per_game", "targets_per_game",
        "rb_share_of_team_rush", "rb_share_of_team_rush_td",
        "ol_quality_tier", "team_rush_ypa", "team_rush_td_rate",
        # Regression features
        "pts_lag1", "yoy_change_injury_adj", "yoy_pct_change_injury_adj", "regression_risk_injury_adj", "is_breakout", "is_bust_injury_adj",
        "pts_roll2", "rush_td_rate_lag1", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS & rookie features
        "def_rank", "is_rookie", "is_2nd_year",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_rush_yds_per_game", "college_rush_td_per_game",
        "college_rec_per_game", "combine_forty", "early_declare", "p5_conference",
        # College × experience interaction
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
    ],
    "WR": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "receiving_yards_lag1", "receiving_yards_lag2", "receiving_yards_roll3",
        "receiving_tds_lag1", "receiving_tds_lag2",
        "targets_lag1", "targets_lag2", "targets_roll3",
        "receptions_lag1",
        "target_share", "yards_per_target", "catch_rate",
        "targets_per_game", "rec_td_rate",
        "team_pass_volume", "qb_completion_rate",
        # Regression features
        "pts_lag1", "yoy_change_injury_adj", "yoy_pct_change_injury_adj", "regression_risk_injury_adj", "is_breakout", "is_bust_injury_adj",
        "pts_roll2", "rec_td_rate_lag1", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS, stacking & rookie features
        "pass_def_rank", "qb_stack_bonus", "team_qb_avg_pts", "is_rookie", "is_2nd_year",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_rec_yds_per_game", "college_rec_td_per_game",
        "college_rush_yds_per_game", "combine_forty", "early_declare", "p5_conference",
        # College × experience interaction
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
    ],
    "TE": [
        "age", "age_squared", "is_prime",
        "years_from_prime", "years_from_prime_sq", "is_pre_prime", "is_prime_age", "is_post_prime",
        "receiving_yards_lag1", "receiving_yards_lag2", "receiving_yards_roll3",
        "receiving_tds_lag1",
        "targets_lag1", "targets_lag2", "targets_roll3",
        "receptions_lag1",
        "target_share", "yards_per_target", "catch_rate",
        "targets_per_game", "rec_td_rate",
        "team_pass_volume", "qb_completion_rate",
        # Regression features
        "pts_lag1", "yoy_change_injury_adj", "yoy_pct_change_injury_adj", "regression_risk_injury_adj", "is_breakout", "is_bust_injury_adj",
        "pts_roll2", "rec_td_rate_lag1", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1", "is_injury_bounce_back",
        # ADP & injury features
        "adp", "adp_tier", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3",
        # SOS, stacking & rookie features
        "pass_def_rank", "qb_stack_bonus", "team_qb_avg_pts", "is_rookie", "is_2nd_year",
        # College/draft features
        "draft_capital", "athletic_score", "college_dominance",
        "college_rec_yds_per_game", "college_rec_td_per_game",
        "combine_forty", "early_declare", "p5_conference",
        # College × experience interaction
        "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
        "college_x_2nd_year", "draft_cap_x_2nd_year",
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


class PositionPipeline:
    """Orchestrates per-position model training and prediction.

    For each position:
    1. Filter data to that position
    2. Select position-specific features
    3. Walk-forward validate to pick best model
    4. Train final model on all available data
    5. Generate next-season projections
    """

    def __init__(self, models: Optional[list[FantasyModel]] = None):
        self.models = models or [RidgeModel(), RandomForestModel(), XGBoostModel()]
        self.best_models: dict[str, FantasyModel] = {}
        self.validation_results: Optional[pd.DataFrame] = None

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
            feat_cols = [c for c in feat_cols if c in pos_df.columns and pos_df[c].dtype in [np.float64, np.int64, float, int]]

            if not feat_cols:
                print(f"Skipping {pos}: no valid features")
                continue

            print(f"\n=== {pos} ({len(pos_df)} rows, {len(feat_cols)} features) ===")

            for model in self.models:
                print(f"  Validating: {model.name}...")
                results = walk_forward_validate(
                    model, pos_df, feat_cols, target_col,
                    season_col=season_col, position_col=None,
                    min_train_seasons=min_train_seasons,
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
            pos_summary = summary[summary["position"] == pos]
            if not pos_summary.empty:
                best_name = pos_summary.iloc[0]["model"]
                for m in self.models:
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
            temporal_weight: Decay rate for older seasons. 0 = no weighting,
                higher = more aggressive discounting of old data.
                0.15 means each year older gets 15% less weight.
        """
        available_cols = list(df.columns)
        trained = {}

        for pos in OFFENSIVE_POSITIONS:
            if pos not in self.best_models:
                # Default to Ridge if no validation done
                self.best_models[pos] = RidgeModel()

            pos_df = df[df["position"] == pos].copy()
            feat_cols = get_position_features(pos, available_cols)
            feat_cols = [c for c in feat_cols if c in pos_df.columns and pos_df[c].dtype in [np.float64, np.int64, float, int]]

            if not feat_cols or pos_df.empty:
                continue

            # Fill NaN features with 0, only train on rows with actual fantasy points
            # (exclude projection-season rows which have fantasy_points=0)
            X = pos_df[feat_cols].fillna(0)
            valid = pos_df[target_col].notna() & (pos_df[target_col] > 0)
            X = X[valid]
            y = pos_df.loc[valid, target_col]

            if X.empty:
                continue

            # Compute sample weights: recent seasons weighted more heavily
            # Combats concept drift (rule changes, usage patterns shift over time)
            sample_weight = None
            if "season" in pos_df.columns and temporal_weight > 0:
                max_season = pos_df.loc[valid, "season"].max()
                seasons = pos_df.loc[valid, "season"]
                years_ago = max_season - seasons
                # Exponential decay: most recent season = 1.0, each year older decays
                sample_weight = np.exp(-temporal_weight * years_ago)

            # Fresh model instance via deepcopy
            import copy
            model = copy.deepcopy(self.best_models[pos])
            if hasattr(model, 'model'):
                model.model = None
            model.fit(X, y, sample_weight=sample_weight)
            trained[pos] = model
            print(f"Trained {model.name} for {pos} on {len(X)} rows")

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
            feat_cols = [c for c in feat_cols if c in predict_df.columns and predict_df[c].dtype in [np.float64, np.int64, float, int]]

            # Fill NaN features with 0 for prediction
            X = predict_pos[feat_cols].fillna(0)

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
                    X_train = pos_df[feat_cols].fillna(0)
                    valid = pos_df["fantasy_points"].notna()
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

            for i, (_, row) in enumerate(predict_pos.iterrows()):
                proj_pts = float(pred_mean[i])

                # Post-prediction regression adjustment:
                # If player is coming off a breakout (>30% above 2yr avg),
                # shrink projection toward their recent average.
                regression_risk = row.get("regression_risk", 0)
                is_breakout = row.get("is_breakout", 0)
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

                # Widen uncertainty for rookies/2nd-year players
                is_rookie = row.get("is_rookie", 0)
                is_2nd_year = row.get("is_2nd_year", 0)
                rookie_multiplier = 1.0
                if is_rookie:
                    rookie_multiplier = 1.8  # 80% wider CI for rookies
                elif is_2nd_year:
                    rookie_multiplier = 1.3  # 30% wider for 2nd year

                # Uncertainty: 80% confidence interval
                std = float(pred_std[i]) if i < len(pred_std) else 0
                std *= rookie_multiplier
                ci_low = max(proj_pts - 1.28 * std, 0)
                ci_high = proj_pts + 1.28 * std

                # Risk tier based on relative uncertainty (coefficient of variation)
                # The ensemble std measures model disagreement, not true prediction error.
                # Top players naturally have CV 20-40% — that's normal, not "high risk".
                # Truly risky players have CV > 60% (models strongly disagree).
                # Injury history also factors in via injury features in the model.
                if proj_pts > 0:
                    cv = std / proj_pts  # coefficient of variation
                else:
                    cv = 1.0
                if cv > 0.60:
                    risk = "high"
                elif cv > 0.25:
                    risk = "medium"
                else:
                    risk = "low"

                projections.append({
                    "player_id": row.get("player_id", f"player_{i}"),
                    "player_name": row.get("player_name") or row.get("football_name") or row.get("player_display_name", ""),
                    "position": pos,
                    "team": row.get("team", ""),
                    "projected_points": round(proj_pts, 1),
                    "ci_low": round(ci_low, 1),
                    "ci_high": round(ci_high, 1),
                    "uncertainty": round(std, 1),
                    "risk": risk,
                    "adp": row.get("adp", 200),
                    "model_used": f"ensemble({'+'.join(ensemble_preds.keys())})" if len(ensemble_preds) > 1 else self.best_models[pos].name,
                })

        return pd.DataFrame(projections)
