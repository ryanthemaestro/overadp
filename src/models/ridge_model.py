"""Ridge regression — baseline for small, noisy NFL data."""
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from typing import Optional

from src.models.base import FantasyModel


class RidgeModel(FantasyModel):
    name = "ridge"

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("ridge", Ridge(alpha=alpha)),
        ])
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "RidgeModel":
        self.validate_inputs(X, y)
        self._feature_names = list(X.columns)
        self.pipeline.fit(X, y, ridge__sample_weight=sample_weight)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict(X)

    def get_feature_importance(self) -> Optional[pd.Series]:
        coefs = self.pipeline.named_steps["ridge"].coef_
        return pd.Series(coefs, index=self._feature_names).sort_values(key=abs, ascending=False)
