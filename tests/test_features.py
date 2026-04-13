"""Tests for feature engineering."""
import pytest
import pandas as pd
import numpy as np

from src.features.engineer import (
    compute_ol_rb_features, compute_qb_wr_features,
    compute_age_experience_features, compute_volume_features,
    compute_lag_features, compute_rolling_features,
    build_feature_matrix, get_feature_columns,
)


def _make_seasonal_df():
    return pd.DataFrame([
        {"player_id": "P1", "season": 2023, "team": "KC", "rushing_yards": 1200, "rushing_tds": 12,
         "rushing_attempts": 280, "receiving_yards": 400, "receiving_tds": 2,
         "targets": 50, "receptions": 40, "games": 16, "passing_yards": 0, "passing_td": 0, "passing_int": 0},
        {"player_id": "P2", "season": 2023, "team": "KC", "rushing_yards": 200, "rushing_tds": 1,
         "rushing_attempts": 50, "receiving_yards": 1100, "receiving_tds": 8,
         "targets": 120, "receptions": 85, "games": 16, "passing_yards": 0, "passing_td": 0, "passing_int": 0},
        {"player_id": "P1", "season": 2022, "team": "KC", "rushing_yards": 1000, "rushing_tds": 10,
         "rushing_attempts": 250, "receiving_yards": 350, "receiving_tds": 1,
         "targets": 45, "receptions": 35, "games": 16, "passing_yards": 0, "passing_td": 0, "passing_int": 0},
    ])


def _make_roster_df():
    return pd.DataFrame([
        {"player_id": "P1", "position": "RB", "age": 25, "team": "KC"},
        {"player_id": "P2", "position": "WR", "age": 28, "team": "KC"},
    ])


def _make_team_df():
    return pd.DataFrame([
        {"team": "KC", "season": 2023, "rushing_yards": 2200, "passing_yards": 4500},
        {"team": "KC", "season": 2022, "rushing_yards": 2100, "passing_yards": 4200},
    ])


def _make_ol_df():
    return pd.DataFrame([
        {"team": "KC", "season": 2023, "team_rush_ypa": 4.5, "team_sack_rate": 0.05, "team_rush_td_rate": 0.04},
        {"team": "KC", "season": 2022, "team_rush_ypa": 4.3, "team_sack_rate": 0.06, "team_rush_td_rate": 0.035},
    ])


class TestOLRBFeatures:
    def test_rb_share_computed(self):
        df = _make_seasonal_df().copy()
        df["team_rush_ypa"] = 4.5
        result = compute_ol_rb_features(df)
        assert "rb_share_of_team_rush" in result.columns
        # P1 (RB) should have a larger share than P2 (WR)
        p1_share = result[result["player_id"] == "P1"]["rb_share_of_team_rush"].iloc[0]
        p2_share = result[result["player_id"] == "P2"]["rb_share_of_team_rush"].iloc[0]
        assert p1_share > p2_share

    def test_ol_quality_tier(self):
        df = _make_seasonal_df().copy()
        df["team_rush_ypa"] = 4.5
        result = compute_ol_rb_features(df)
        assert "ol_quality_tier" in result.columns
        assert result["ol_quality_tier"].notna().all()


class TestQBWRFeatures:
    def test_target_share_computed(self):
        df = _make_seasonal_df().copy()
        result = compute_qb_wr_features(df)
        assert "target_share" in result.columns
        # WR (P2) should have higher target share
        p2_share = result[result["player_id"] == "P2"]["target_share"].iloc[0]
        p1_share = result[result["player_id"] == "P1"]["target_share"].iloc[0]
        assert p2_share > p1_share

    def test_yards_per_target(self):
        df = _make_seasonal_df().copy()
        result = compute_qb_wr_features(df)
        assert "yards_per_target" in result.columns
        assert result["yards_per_target"].notna().any()


class TestAgeFeatures:
    def test_age_squared(self):
        df = _make_seasonal_df().copy()
        df["age"] = 25
        df["position"] = "RB"
        result = compute_age_experience_features(df)
        assert "age_squared" in result.columns
        assert result["age_squared"].iloc[0] == 625

    def test_is_prime(self):
        df = _make_seasonal_df().copy()
        df["age"] = 25
        df["position"] = "RB"
        result = compute_age_experience_features(df)
        assert "is_prime" in result.columns
        assert result["is_prime"].iloc[0] == 1  # 25 is in RB prime range (23-27)


class TestVolumeFeatures:
    def test_rush_att_per_game(self):
        df = _make_seasonal_df().copy()
        result = compute_volume_features(df)
        assert "rush_att_per_game" in result.columns
        expected = 280 / 16
        assert abs(result[result["player_id"] == "P1"]["rush_att_per_game"].iloc[0] - expected) < 0.01

    def test_targets_per_game(self):
        df = _make_seasonal_df().copy()
        result = compute_volume_features(df)
        assert "targets_per_game" in result.columns


class TestLagFeatures:
    def test_lag1_computed(self):
        df = _make_seasonal_df().copy()
        result = compute_lag_features(df, ["rushing_yards"])
        assert "rushing_yards_lag1" in result.columns
        # 2023 row should have 2022 value as lag1
        p1_2023 = result[(result["player_id"] == "P1") & (result["season"] == 2023)]
        assert p1_2023["rushing_yards_lag1"].iloc[0] == 1000

    def test_lag2_is_nan_for_short_history(self):
        df = _make_seasonal_df().copy()
        result = compute_lag_features(df, ["rushing_yards"], lags=[1, 2])
        assert "rushing_yards_lag2" in result.columns
        # Only 2 seasons, so lag2 should be NaN
        p1_2023 = result[(result["player_id"] == "P1") & (result["season"] == 2023)]
        assert pd.isna(p1_2023["rushing_yards_lag2"].iloc[0])


class TestBuildFeatureMatrix:
    def test_full_pipeline(self):
        seasonal = _make_seasonal_df()
        roster = _make_roster_df()
        team = _make_team_df()
        ol = _make_ol_df()

        result = build_feature_matrix(seasonal, roster, team, ol)
        assert "position" in result.columns
        assert "target_share" in result.columns
        assert "rb_share_of_team_rush" in result.columns
        assert len(result) > 0

    def test_feature_columns_extraction(self):
        seasonal = _make_seasonal_df()
        roster = _make_roster_df()
        team = _make_team_df()
        ol = _make_ol_df()

        result = build_feature_matrix(seasonal, roster, team, ol)
        feat_cols = get_feature_columns(result)
        # Should not include metadata columns
        assert "player_id" not in feat_cols
        assert "season" not in feat_cols
        assert "position" not in feat_cols
        # Should include engineered features
        assert len(feat_cols) > 0
