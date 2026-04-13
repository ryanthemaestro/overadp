"""Tests for model training, prediction, and comparison."""
import pytest
import pandas as pd
import numpy as np

from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.compare import walk_forward_validate, compare_models, summarize_comparison


def _make_model_df():
    """Create synthetic data for model testing: 4 seasons, 20 players each."""
    np.random.seed(42)
    rows = []
    for season in [2020, 2021, 2022, 2023]:
        for i in range(20):
            pid = f"P{i}"
            pos = ["QB", "RB", "WR", "TE"][i % 4]
            base = np.random.randn() * 50 + 150
            age = 22 + (i % 10)
            rows.append({
                "player_id": pid, "season": season, "position": pos,
                "age": age, "age_squared": age ** 2, "is_prime": 1 if 23 <= age <= 30 else 0,
                "rushing_yards_lag1": base * 0.8, "targets_lag1": base * 0.3,
                "target_share": 0.1 + np.random.rand() * 0.2,
                "rush_att_per_game": 5 + np.random.rand() * 10,
                "targets_per_game": 3 + np.random.rand() * 8,
                "ol_quality_tier": np.random.choice([1, 2, 3, 4]),
                "fantasy_points": base + np.random.randn() * 20,
            })
    return pd.DataFrame(rows)


class TestRidgeModel:
    def test_fit_predict(self):
        df = _make_model_df()
        feat_cols = [c for c in df.columns if c not in ["player_id", "position", "season", "fantasy_points"]]
        model = RidgeModel()
        model.fit(df[feat_cols], df["fantasy_points"])
        preds = model.predict(df[feat_cols])
        assert len(preds) == len(df)
        assert not np.any(np.isnan(preds))

    def test_feature_importance(self):
        df = _make_model_df()
        feat_cols = [c for c in df.columns if c not in ["player_id", "position", "season", "fantasy_points"]]
        model = RidgeModel()
        model.fit(df[feat_cols], df["fantasy_points"])
        importance = model.get_feature_importance()
        assert importance is not None
        assert len(importance) == len(feat_cols)

    def test_input_validation(self):
        model = RidgeModel()
        with pytest.raises(ValueError):
            model.fit(pd.DataFrame(), pd.Series(dtype=float))


class TestRandomForestModel:
    def test_fit_predict(self):
        df = _make_model_df()
        feat_cols = [c for c in df.columns if c not in ["player_id", "position", "season", "fantasy_points"]]
        model = RandomForestModel()
        model.fit(df[feat_cols], df["fantasy_points"])
        preds = model.predict(df[feat_cols])
        assert len(preds) == len(df)


class TestWalkForwardValidation:
    def test_produces_results(self):
        df = _make_model_df()
        feat_cols = [c for c in df.columns if c not in ["player_id", "position", "season", "fantasy_points"]]
        results = walk_forward_validate(
            RidgeModel(), df, feat_cols, "fantasy_points",
            season_col="season", position_col="position", min_train_seasons=3,
        )
        assert len(results) > 0
        assert "mae" in results.columns
        assert "rmse" in results.columns
        assert "r2" in results.columns

    def test_compare_multiple_models(self):
        df = _make_model_df()
        feat_cols = [c for c in df.columns if c not in ["player_id", "position", "season", "fantasy_points"]]
        results = compare_models(
            [RidgeModel(), RandomForestModel()],
            df, feat_cols, "fantasy_points",
            season_col="season", min_train_seasons=3,
        )
        assert len(results) > 0
        model_names = results["model"].unique()
        assert "ridge" in model_names
        assert "random_forest" in model_names

    def test_summarize(self):
        df = _make_model_df()
        feat_cols = [c for c in df.columns if c not in ["player_id", "position", "season", "fantasy_points"]]
        results = compare_models(
            [RidgeModel(), RandomForestModel()],
            df, feat_cols, "fantasy_points",
            season_col="season", min_train_seasons=3,
        )
        summary = summarize_comparison(results)
        assert "mae_mean" in summary.columns
        assert len(summary) > 0
