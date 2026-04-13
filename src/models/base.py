"""Base model interface — all models must implement this."""
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from typing import Optional


class FantasyModel(ABC):
    """Abstract base class for fantasy point prediction models."""

    name: str = "base"

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "FantasyModel":
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        ...

    @abstractmethod
    def get_feature_importance(self) -> Optional[pd.Series]:
        ...

    def validate_inputs(self, X: pd.DataFrame, y: pd.Series) -> None:
        if X.empty:
            raise ValueError("Feature matrix X is empty")
        if y.empty:
            raise ValueError("Target y is empty")
        if len(X) != len(y):
            raise ValueError(f"X length ({len(X)}) != y length ({len(y)})")
