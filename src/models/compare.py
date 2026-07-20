"""Model comparison with walk-forward cross-validation.

Walk-forward: train on seasons [1..N], predict N+1, roll forward.
This is the correct validation for time-series/seasonal data.
"""
import pandas as pd
import numpy as np
from typing import Optional
from pandas.api.types import is_numeric_dtype
from src.models.base import FantasyModel


def _mae(y_true, y_pred): return float(np.mean(np.abs(y_true - y_pred)))
def _rmse(y_true, y_pred): return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
def _r2(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def walk_forward_validate(
    model: FantasyModel,
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    season_col: str = "season",
    position_col: Optional[str] = "position",
    min_train_seasons: int = 3,
    temporal_weight: float = 0.0,
) -> pd.DataFrame:
    """Walk-forward validation for a single model.

    Returns DataFrame: season, position, mae, rmse, r2, n_players, model
    """
    seasons = sorted(df[season_col].unique())
    results = []

    for i in range(min_train_seasons, len(seasons)):
        test_season = seasons[i]
        train_seasons = seasons[:i]

        train_mask = df[season_col].isin(train_seasons)
        test_mask = df[season_col] == test_season

        numeric_cols = [c for c in feature_cols if c in df.columns and is_numeric_dtype(df[c])]
        X_train = df.loc[train_mask, numeric_cols]
        y_train = df.loc[train_mask, target_col]
        X_test = df.loc[test_mask, numeric_cols]
        y_test = df.loc[test_mask, target_col]

        # Fill NaN features with 0 (lag features are naturally NaN for new players)
        # and keep true zero-point historical rows; projection placeholder rows are
        # not present in walk-forward historical folds.
        X_train = X_train.replace([np.inf, -np.inf], np.nan).fillna(0)
        X_test = X_test.replace([np.inf, -np.inf], np.nan).fillna(0)
        valid_train = y_train.notna() & np.isfinite(y_train)
        valid_test = y_test.notna() & np.isfinite(y_test)

        X_tr, y_tr = X_train[valid_train], y_train[valid_train]
        X_te, y_te = X_test[valid_test], y_test[valid_test]

        if X_tr.empty or X_te.empty:
            continue

        # Fresh model instance via deepcopy (avoids fragile constructor re-init)
        import copy
        model_clone = copy.deepcopy(model)
        # Reset fitted state so it re-trains
        if hasattr(model_clone, "model"):
            model_clone.model = None
        if hasattr(model_clone, "pipeline") and hasattr(model_clone.pipeline, "fit"):
            # Re-create pipeline from scratch for sklearn-based models
            model_clone = type(model)(**{k: v for k, v in getattr(model, "params", {}).items()
                                          if k in type(model).__init__.__code__.co_varnames})

        # Apply temporal weighting if specified
        sw = None
        if temporal_weight > 0 and season_col in df.columns:
            train_season_values = pd.to_numeric(
                df.loc[train_mask & valid_train, season_col], errors="raise"
            )
            max_s = train_season_values.max()
            years_ago = (max_s - train_season_values).to_numpy(dtype=float)
            sw = np.exp(-temporal_weight * years_ago)

        model_clone.fit(X_tr, y_tr, sample_weight=sw)
        preds = model_clone.predict(X_te)

        # Overall
        results.append({
            "season": test_season, "position": "ALL",
            "mae": _mae(y_te.values, preds), "rmse": _rmse(y_te.values, preds),
            "r2": _r2(y_te.values, preds), "n_players": len(y_te),
            "model": model.name,
        })

        # Per-position
        if position_col and position_col in df.columns:
            test_df = df.loc[test_mask & valid_test].copy()
            test_df["pred"] = preds
            for pos in test_df[position_col].unique():
                pos_mask = test_df[position_col] == pos
                if pos_mask.sum() < 5:
                    continue
                yt = test_df.loc[pos_mask, target_col].values
                yp = test_df.loc[pos_mask, "pred"].values
                results.append({
                    "season": test_season, "position": pos,
                    "mae": _mae(yt, yp), "rmse": _rmse(yt, yp),
                    "r2": _r2(yt, yp), "n_players": int(pos_mask.sum()),
                    "model": model.name,
                })

    return pd.DataFrame(results)


def compare_models(
    models: list[FantasyModel],
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    season_col: str = "season",
    position_col: Optional[str] = "position",
    min_train_seasons: int = 3,
) -> pd.DataFrame:
    """Compare multiple models using walk-forward validation."""
    all_results = []
    for model in models:
        print(f"Validating: {model.name}...")
        results = walk_forward_validate(
            model, df, feature_cols, target_col,
            season_col=season_col, position_col=position_col,
            min_train_seasons=min_train_seasons,
        )
        all_results.append(results)
    return pd.concat(all_results, ignore_index=True) if all_results else pd.DataFrame()


def summarize_comparison(results: pd.DataFrame) -> pd.DataFrame:
    """Aggregate walk-forward results: mean metrics by model and position."""
    return results.groupby(["model", "position"]).agg(
        mae_mean=("mae", "mean"), mae_std=("mae", "std"),
        rmse_mean=("rmse", "mean"), r2_mean=("r2", "mean"),
        total_players=("n_players", "sum"), n_seasons=("season", "nunique"),
    ).reset_index().sort_values(["position", "mae_mean"])
