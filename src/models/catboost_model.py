"""CatBoost — ordered boosting reduces overfitting, handles small datasets well."""
import pandas as pd
import numpy as np
from typing import Optional

from src.models.base import FantasyModel


# Per-position tuned hyperparameters (walk-forward grid search, 2022-2025)
POSITION_CATBOOST_PARAMS = {
    "QB": {"depth": 6, "iterations": 300, "learning_rate": 0.03, "l2_leaf_reg": 7.0, "subsample": 0.7},
    "RB": {"depth": 4, "iterations": 500, "learning_rate": 0.03, "l2_leaf_reg": 3.0, "subsample": 0.8},
    "WR": {"depth": 4, "iterations": 400, "learning_rate": 0.04, "l2_leaf_reg": 5.0, "subsample": 0.75},
    "TE": {"depth": 4, "iterations": 400, "learning_rate": 0.04, "l2_leaf_reg": 5.0, "subsample": 0.75},
}

# Per-position temporal weights (exponential decay for older training seasons)
POSITION_TEMPORAL_WEIGHTS = {
    "QB": 0.30,
    "RB": 0.40,
    "WR": 0.05,
    "TE": 0.15,
}


# Monotonic constraints per feature (conservative set — only features where
# the direction is unambiguous). CatBoost enforces these during tree splits,
# guaranteeing the prediction is monotonic in each constrained feature.
# +1 = non-decreasing (more feature → more projection)
# -1 = non-increasing (more feature → less projection)
# Absent from dict = unconstrained (age curves, injury flags, interactions, etc.)
MONOTONIC_CONSTRAINTS = {
    # Conservative set: only aggregate-production lags where direction is
    # unambiguous AND interactions with other features are minimal. Volume
    # lags (targets_lag1, rushing_yards_lag1, etc.) are INTENTIONALLY omitted
    # because their effect is context-dependent (e.g., 300 targets on a pass-happy
    # team may project differently than 300 on a run-heavy team).
    "pts_lag1": 1,          # last year's total fantasy points
    "pts_roll2": 1,         # 2-year rolling avg
    "fp_per_game_lag1": 1,  # per-game rate (injury-adjusted)
    "fp_adj_17games_lag1": 1,
}


def get_monotone_constraints(feature_names: list[str]) -> dict:
    """Return the subset of MONOTONIC_CONSTRAINTS that matches the given feature names."""
    return {f: c for f, c in MONOTONIC_CONSTRAINTS.items() if f in feature_names}


class CatBoostModel(FantasyModel):
    name = "catboost"

    def __init__(self, depth: int = 4, iterations: int = 200, learning_rate: float = 0.05,
                 l2_leaf_reg: float = 3.0, subsample: float = 0.8,
                 use_monotonic: bool = True):
        self.params = {
            "depth": depth,
            "iterations": iterations,
            "learning_rate": learning_rate,
            "l2_leaf_reg": l2_leaf_reg,
            "subsample": subsample,
            "verbose": 0,
        }
        self.use_monotonic = use_monotonic
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "CatBoostModel":
        self.validate_inputs(X, y)
        from catboost import CatBoostRegressor
        params = dict(self.params)
        if self.use_monotonic:
            constraints = get_monotone_constraints(list(X.columns))
            if constraints:
                params["monotone_constraints"] = constraints
        self.model = CatBoostRegressor(**params, random_seed=42)
        self.model.fit(X, y, sample_weight=sample_weight)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not fitted yet")
        return self.model.predict(X)

    def get_feature_importance(self) -> Optional[pd.Series]:
        if self.model is None:
            return None
        return pd.Series(self.model.feature_importances_, index=self.model.feature_names_).sort_values(ascending=False)
