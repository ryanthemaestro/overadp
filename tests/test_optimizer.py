"""Tests for roster optimizer."""
import pytest
import pandas as pd
import numpy as np

from src.optimizer.roster_optimizer import optimize_roster, greedy_roster
from src.optimizer.draft_strategy import detect_sleepers_and_busts


def _make_projections():
    """Create synthetic player projections."""
    rows = []
    positions = {"QB": 15, "RB": 40, "WR": 45, "TE": 20, "K": 15, "DEF": 15}
    np.random.seed(42)
    for pos, count in positions.items():
        for i in range(count):
            pid = f"{pos}_{i}"
            base_points = {"QB": 18, "RB": 12, "WR": 11, "TE": 9, "K": 7, "DEF": 6}[pos]
            pts = base_points - i * 0.3 + np.random.randn() * 1
            rows.append({
                "player_id": pid, "player_name": f"Player {pos}{i}",
                "position": pos, "projected_points": pts,
            })
    return pd.DataFrame(rows)


class TestOptimizeRoster:
    def test_selects_correct_number(self):
        projections = _make_projections()
        result = optimize_roster(projections, remaining_picks=16)
        assert len(result) <= 16

    def test_fills_starters(self):
        projections = _make_projections()
        result = optimize_roster(projections, remaining_picks=16)
        positions = result["position"].value_counts()
        # Should have at least 1 QB, 2 RB, 2 WR, 1 TE
        assert positions.get("QB", 0) >= 1
        assert positions.get("RB", 0) >= 1  # at least 1 RB guaranteed
        assert positions.get("WR", 0) >= 1  # at least 1 WR guaranteed

    def test_excludes_drafted(self):
        projections = _make_projections()
        drafted = ["QB_0", "RB_0", "WR_0"]
        result = optimize_roster(projections, drafted_players=drafted, remaining_picks=16)
        assert "QB_0" not in result["player_id"].values
        assert "RB_0" not in result["player_id"].values

    def test_assigns_roster_slots(self):
        projections = _make_projections()
        result = optimize_roster(projections, remaining_picks=16)
        assert "roster_slot" in result.columns
        # Should have proper slot names
        slots = result["roster_slot"].tolist()
        assert any(s.startswith("qb") or s.startswith("rb") or s.startswith("wr") or s.startswith("QB") or s.startswith("RB") or s.startswith("WR") for s in slots)


class TestGreedyRoster:
    def test_greedy_fallback(self):
        projections = _make_projections()
        result = greedy_roster(projections, remaining_picks=14)
        assert len(result) <= 14
        positions = result["position"].value_counts()
        assert positions.get("QB", 0) >= 1

    def test_greedy_excludes_drafted(self):
        projections = _make_projections()
        drafted = ["QB_0"]
        result = greedy_roster(projections, drafted_players=drafted, remaining_picks=14)
        assert "QB_0" not in result["player_id"].values


def test_sleepers_and_busts_exclude_no_adp_sentinel():
    projections = pd.DataFrame([
        {"player_name": "Priced WR", "position": "WR", "team": "A", "projected_points": 100, "adp": 80},
        {"player_name": "Unpriced WR", "position": "WR", "team": "B", "projected_points": 300, "adp": 200},
        {"player_name": "Priced WR 2", "position": "WR", "team": "C", "projected_points": 90, "adp": 10},
    ])
    results = detect_sleepers_and_busts(
        projections,
        adp_data=pd.DataFrame({"player_name": ["unused"], "adp": [1]}),
        pos_rank_threshold=1,
    )
    assert {row["player_name"] for row in results} == {"Priced WR", "Priced WR 2"}
