"""Tests for fantasy scoring calculator."""
import pytest
import pandas as pd
import numpy as np

from src.scoring.calculator import calculate_fantasy_points, add_fantasy_points_to_df, add_all_scoring_formats


class TestCalculateFantasyPoints:
    def test_standard_qb_game(self):
        stats = {
            "passing_yards": 300, "passing_td": 2, "passing_int": 1,
            "rushing_yards": 20, "rushing_td": 0, "receiving_yards": 0,
            "receiving_td": 0, "receptions": 0, "fumble_lost": 0,
        }
        pts = calculate_fantasy_points(stats, format="standard")
        # 300*0.04 + 2*4 + 1*(-2) + 20*0.1 = 12 + 8 - 2 + 2 = 20
        assert abs(pts - 20.0) < 0.01

    def test_half_ppr_rb_game(self):
        stats = {
            "passing_yards": 0, "passing_td": 0, "passing_int": 0,
            "rushing_yards": 100, "rushing_td": 1, "receiving_yards": 50,
            "receiving_td": 0, "receptions": 5, "fumble_lost": 0,
        }
        pts = calculate_fantasy_points(stats, format="half_ppr")
        # 100*0.1 + 1*6 + 50*0.1 + 5*0.5 = 10 + 6 + 5 + 2.5 = 23.5
        assert abs(pts - 23.5) < 0.01

    def test_ppr_wr_game(self):
        stats = {
            "passing_yards": 0, "passing_td": 0, "passing_int": 0,
            "rushing_yards": 0, "rushing_td": 0, "receiving_yards": 120,
            "receiving_td": 2, "receptions": 8, "fumble_lost": 1,
        }
        pts = calculate_fantasy_points(stats, format="ppr")
        # 120*0.1 + 2*6 + 8*1.0 + 1*(-2) = 12 + 12 + 8 - 2 = 30
        assert abs(pts - 30.0) < 0.01

    def test_zero_stats(self):
        stats = {k: 0 for k in [
            "passing_yards", "passing_td", "passing_int",
            "rushing_yards", "rushing_td", "receiving_yards",
            "receiving_td", "receptions", "fumble_lost",
        ]}
        assert calculate_fantasy_points(stats, "standard") == 0.0
        assert calculate_fantasy_points(stats, "half_ppr") == 0.0
        assert calculate_fantasy_points(stats, "ppr") == 0.0

    def test_ppr_vs_half_ppr_difference(self):
        stats = {
            "passing_yards": 0, "passing_td": 0, "passing_int": 0,
            "rushing_yards": 0, "rushing_td": 0, "receiving_yards": 0,
            "receiving_td": 0, "receptions": 10, "fumble_lost": 0,
        }
        ppr = calculate_fantasy_points(stats, "ppr")
        half = calculate_fantasy_points(stats, "half_ppr")
        assert abs(ppr - half - 5.0) < 0.01  # 10 * 0.5 difference


class TestAddFantasyPointsToDF:
    def test_adds_columns(self):
        df = pd.DataFrame([
            {"player_id": "1", "passing_yards": 200, "passing_td": 1, "games": 1},
            {"player_id": "2", "rushing_yards": 80, "rushing_td": 1, "receptions": 3, "games": 1},
        ])
        result = add_fantasy_points_to_df(df, format="half_ppr")
        assert "fantasy_points" in result.columns
        assert "fantasy_points_per_game" in result.columns
        assert len(result) == 2

    def test_all_scoring_formats(self):
        df = pd.DataFrame([
            {"player_id": "1", "receptions": 10, "receiving_yards": 100, "games": 1},
        ])
        result = add_all_scoring_formats(df)
        assert "fantasy_points_standard" in result.columns
        assert "fantasy_points_half_ppr" in result.columns
        assert "fantasy_points_ppr" in result.columns
        # PPR should be highest for a receiver
        assert result["fantasy_points_ppr"].iloc[0] > result["fantasy_points_half_ppr"].iloc[0]
        assert result["fantasy_points_half_ppr"].iloc[0] > result["fantasy_points_standard"].iloc[0]
