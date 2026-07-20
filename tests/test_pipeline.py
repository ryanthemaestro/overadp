"""Tests for per-position model pipeline."""
import pytest
import pandas as pd
import numpy as np

from src.models.pipeline import PositionPipeline, get_position_features, POSITION_FEATURES
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel


def _make_pipeline_df():
    """Create synthetic data: 4 seasons, multiple positions, with lag features."""
    np.random.seed(42)
    rows = []
    for season in [2020, 2021, 2022, 2023]:
        for i in range(30):
            pos = ["QB", "RB", "WR", "TE"][i % 4]
            pid = f"{pos}_{i // 4}"
            age = 22 + (i % 10)
            base = {"QB": 250, "RB": 150, "WR": 130, "TE": 100}[pos]
            pts = base + np.random.randn() * 30
            rows.append({
                "player_id": pid, "season": season, "position": pos,
                "team": "KC", "age": age, "age_squared": age ** 2,
                "is_prime": 1 if 23 <= age <= 30 else 0,
                "rushing_yards_lag1": np.random.rand() * 500 if pos == "RB" else 0,
                "rushing_tds_lag1": np.random.rand() * 8 if pos == "RB" else 0,
                "rushing_attempts_lag1": np.random.rand() * 200 if pos == "RB" else 0,
                "receiving_yards_lag1": np.random.rand() * 800 if pos in ("WR", "TE") else np.random.rand() * 200,
                "receiving_tds_lag1": np.random.rand() * 6,
                "targets_lag1": np.random.rand() * 100 if pos in ("WR", "TE") else np.random.rand() * 30,
                "receptions_lag1": np.random.rand() * 70,
                "passing_yards_lag1": np.random.rand() * 2000 if pos == "QB" else 0,
                "passing_tds_lag1": np.random.rand() * 20 if pos == "QB" else 0,
                "interceptions_lag1": np.random.rand() * 8 if pos == "QB" else 0,
                "target_share_lag1": np.random.rand() * 0.3,
                "yards_per_target_lag1": 6 + np.random.rand() * 8,
                "targets_per_game_lag1": np.random.rand() * 8,
                "ol_quality_tier_lag1": np.random.choice([1, 2, 3, 4]),
                "ol_pass_block_quality_lag1": 0.6 + np.random.rand() * 0.3,
                "qb_completion_rate_lag1": 0.6 + np.random.rand() * 0.15,
                "team_pass_volume_lag1": 400 + np.random.rand() * 200,
                "fantasy_points": pts,
            })
    return pd.DataFrame(rows)


class TestPositionFeatures:
    def test_qb_features_include_passing(self):
        feats = POSITION_FEATURES["QB"]
        assert "passing_yards_lag1" in feats
        assert "passing_tds_lag1" in feats

    def test_rb_features_include_ol(self):
        feats = POSITION_FEATURES["RB"]
        assert "ol_quality_tier_lag1" in feats

    def test_wr_features_include_targets(self):
        feats = POSITION_FEATURES["WR"]
        assert "target_share_lag1" in feats
        assert "yards_per_target_lag1" in feats

    def test_get_position_features_filters_to_available(self):
        available = ["age", "age_squared", "is_prime", "rushing_yards_lag1"]
        feats = get_position_features("RB", available)
        assert all(f in available for f in feats)
        assert "passing_yards_lag1" not in feats  # not in available


class TestPositionPipeline:
    def test_validate_all(self):
        df = _make_pipeline_df()
        pipeline = PositionPipeline(models=[RidgeModel()])
        results = pipeline.validate_all(df, min_train_seasons=3)
        assert len(results) > 0
        assert "position" in results.columns
        assert "mae" in results.columns

    def test_best_models_selected(self):
        df = _make_pipeline_df()
        pipeline = PositionPipeline(models=[RidgeModel(), RandomForestModel()])
        pipeline.validate_all(df, min_train_seasons=3)
        # Should have a best model for at least some positions
        assert len(pipeline.best_models) > 0

    def test_train_final(self):
        df = _make_pipeline_df()
        pipeline = PositionPipeline(models=[RidgeModel()])
        pipeline.validate_all(df, min_train_seasons=3)
        trained = pipeline.train_final(df)
        assert len(trained) > 0
        for pos, model in trained.items():
            assert model is not None

    def test_predict(self):
        df = _make_pipeline_df()
        pipeline = PositionPipeline(models=[RidgeModel()])
        pipeline.validate_all(df, min_train_seasons=3)
        pipeline.train_final(df)
        projections = pipeline.predict(df, target_season=2024)
        assert len(projections) > 0
        assert "projected_points" in projections.columns
        assert "position" in projections.columns
        assert "model_used" in projections.columns
