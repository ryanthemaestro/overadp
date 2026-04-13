"""XGBoost — captures non-linear interactions, with regularization for small data."""
import pandas as pd
import numpy as np
from typing import Optional

from src.models.base import FantasyModel


class XGBoostModel(FantasyModel):
    name = "xgboost"

    def __init__(self, max_depth: int = 3, n_estimators: int = 100, learning_rate: float = 0.05):
        self.params = {
            "max_depth": max_depth,
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "reg_alpha": 1.0,
            "reg_lambda": 1.0,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        }
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "XGBoostModel":
        self.validate_inputs(X, y)
        from xgboost import XGBRegressor
        self.model = XGBRegressor(**self.params, random_state=42)
        self.model.fit(X, y, sample_weight=sample_weight)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not fitted yet")
        return self.model.predict(X)

    def get_feature_importance(self) -> Optional[pd.Series]:
        if self.model is None:
            return None
        return pd.Series(self.model.feature_importances_, index=self.model.feature_names_in_).sort_values(ascending=False)
