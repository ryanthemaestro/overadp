"""Stacked ensemble: Ridge + RF + XGBoost → Ridge meta-learner."""
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from typing import Optional

from src.models.base import FantasyModel
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel


class StackedEnsembleModel(FantasyModel):
    name = "stacked_ensemble"

    def __init__(self):
        self.base_models = [RidgeModel(), RandomForestModel(), XGBoostModel()]
        self.meta_learner = Ridge(alpha=1.0)
        self._fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> "StackedEnsembleModel":
        self.validate_inputs(X, y)

        # Fit base models on full data
        for model in self.base_models:
            model.fit(X, y)

        # Generate out-of-fold predictions for meta-learner
        from sklearn.model_selection import cross_val_predict
        oof_preds = np.zeros((len(X), len(self.base_models)))
        for i, model in enumerate(self.base_models):
            try:
                estimator = model.pipeline if hasattr(model, "pipeline") else model.model
                oof_preds[:, i] = cross_val_predict(estimator, X, y, cv=3)
            except Exception:
                model.fit(X, y)
                oof_preds[:, i] = model.predict(X)

        self.meta_learner.fit(oof_preds, y)
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
