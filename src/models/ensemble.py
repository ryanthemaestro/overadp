"""Stacked ensemble: Ridge + RF + XGBoost + CatBoost → Ridge meta-learner."""
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from typing import Optional

from src.models.base import FantasyModel
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel
from src.models.catboost_model import CatBoostModel


class StackedEnsembleModel(FantasyModel):
    name = "stacked_ensemble"

    def __init__(self):
        self.base_models = [RidgeModel(), RandomForestModel(), XGBoostModel(), CatBoostModel()]
        self.meta_learner = Ridge(alpha=1.0)
        self._fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None, **kwargs) -> "StackedEnsembleModel":
        self.validate_inputs(X, y)

        # Generate out-of-fold predictions for meta-learner (prevents leakage)
        n_models = len(self.base_models)
        oof_preds = np.zeros((len(X), n_models))
        kf = KFold(n_splits=5, shuffle=True, random_state=42)

        for i, model_class in enumerate([RidgeModel, RandomForestModel, XGBoostModel, CatBoostModel]):
            for fold, (train_idx, val_idx) in enumerate(kf.split(X)):
                m = model_class()
                X_tr = X.iloc[train_idx] if hasattr(X, 'iloc') else X[train_idx]
                y_tr = y.iloc[train_idx] if hasattr(y, 'iloc') else y[train_idx]
                sw_tr = sample_weight[train_idx] if sample_weight is not None else None
                m.fit(X_tr, y_tr, sample_weight=sw_tr)
                X_val = X.iloc[val_idx] if hasattr(X, 'iloc') else X[val_idx]
                oof_preds[val_idx, i] = m.predict(X_val)

        # Fit meta-learner on OOF predictions
        self.meta_learner.fit(oof_preds, y)

        # Re-fit all base models on full data for final predictions
        for model in self.base_models:
            model.fit(X, y, sample_weight=sample_weight)

        self._fitted = True
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("Model not fitted yet")
        base_preds = np.column_stack([m.predict(X) for m in self.base_models])
        return self.meta_learner.predict(base_preds)

    def get_feature_importance(self) -> Optional[pd.Series]:
        if not self._fitted:
            return None
        return pd.Series(self.meta_learner.coef_, index=[m.name for m in self.base_models]).sort_values(key=abs, ascending=False)
