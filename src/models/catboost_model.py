"""CatBoost — ordered boosting reduces overfitting, handles small datasets well."""
import pandas as pd
import numpy as np
from typing import Optional

from src.models.base import FantasyModel


class CatBoostModel(FantasyModel):
    name = "catboost"

    def __init__(self, depth: int = 4, iterations: int = 200, learning_rate: float = 0.05):
        self.params = {
            "depth": depth,
            "iterations": iterations,
            "learning_rate": learning_rate,
            "l2_leaf_reg": 3.0,
            "subsample": 0.8,
            "verbose": 0,
        }
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "CatBoostModel":
        self.validate_inputs(X, y)
        from catboost import CatBoostRegressor
        self.model = CatBoostRegressor(**self.params, random_seed=42)
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
