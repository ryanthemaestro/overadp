"""Tests for data cleaning pipeline."""
import pytest
import pandas as pd
import numpy as np

from src.data.clean import clean_seasonal_stats, clean_roster_info, clean_team_stats


class TestCleanSeasonalStats:
    def test_fills_nans(self):
        df = pd.DataFrame([{"player_id": "1", "season": 2023, "games": 5, "rushing_yards": np.nan}])
        result = clean_seasonal_stats(df, min_games=1)
        assert result["rushing_yards"].iloc[0] == 0

    def test_filters_min_games(self):
        df = pd.DataFrame([
            {"player_id": "1", "season": 2023, "games": 2, "rushing_yards": 100},
            {"player_id": "2", "season": 2023, "games": 10, "rushing_yards": 500},
        ])
        result = clean_seasonal_stats(df, min_games=3)
        assert len(result) == 1
        assert result["player_id"].iloc[0] == "2"

    def test_lowercase_columns(self):
        df = pd.DataFrame([{"Player ID": "1", "Season": 2023, "Games": 5}])
        result = clean_seasonal_stats(df, min_games=1)
        assert "player_id" in result.columns or "player_id" in [c.replace(" ", "_") for c in result.columns]


class TestCleanRosterInfo:
    def test_position_normalization(self):
        df = pd.DataFrame([{"player_id": "1", "position": "fb", "team": "kc"}])
        result = clean_roster_info(df)
        assert result["position"].iloc[0] == "RB"

    def test_team_uppercase(self):
        df = pd.DataFrame([{"player_id": "1", "position": "RB", "team": "  kc  "}])
        result = clean_roster_info(df)
        assert result["team"].iloc[0] == "KC"

    def test_deduplication(self):
        df = pd.DataFrame([
            {"player_id": "1", "position": "RB", "team": "KC", "age": 25},
            {"player_id": "1", "position": "RB", "team": "LV", "age": 26},
        ])
        result = clean_roster_info(df)
        assert len(result) == 1


class TestCleanTeamStats:
    def test_fills_nans(self):
        df = pd.DataFrame([{"team": "KC", "season": 2023, "rushing_yards": np.nan}])
        result = clean_team_stats(df)
        assert result["rushing_yards"].iloc[0] == 0
