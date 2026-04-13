"""Random Forest — robust, less overfit risk than GBTs on small data."""
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from typing import Optional

from src.models.base import FantasyModel


class RandomForestModel(FantasyModel):
    name = "random_forest"

    def __init__(self, n_estimators: int = 200, max_depth: int = 6, min_samples_leaf: int = 5, max_features: str = "sqrt"):
        self.params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "max_features": max_features,
        }
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "RandomForestModel":
        self.validate_inputs(X, y)
        self.model = RandomForestRegressor(**self.params, random_state=42, n_jobs=-1)
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
