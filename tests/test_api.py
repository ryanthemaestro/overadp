"""Tests for the FastAPI draft assistant backend."""
import pytest
from fastapi.testclient import TestClient
import pandas as pd
import numpy as np

from src.api.app import app, state


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def populated_state():
    """Pre-populate state with synthetic player data."""
    np.random.seed(42)
    rows = []
    positions = {"QB": 15, "RB": 40, "WR": 45, "TE": 20}
    for pos, count in positions.items():
        for i in range(count):
            pid = f"{pos}_{i}"
            base = {"QB": 18, "RB": 12, "WR": 11, "TE": 9}[pos]
            pts = base - i * 0.3 + np.random.randn() * 1
            rows.append({
                "player_id": pid, "player_name": f"Player {pos}{i}",
                "position": pos, "team": "KC", "projected_points": pts,
                "model_used": "ridge",
            })
    state.player_pool = rows
    state.my_team = []
    state.opponent_picks = []
    state.models_trained = True
    state.scoring_format = "half_ppr"
    return state


class TestAPIEndpoints:
    def test_status(self, client):
        res = client.get("/api/status")
        assert res.status_code == 200
        data = res.json()
        assert "models_trained" in data
        assert "my_team_size" in data

    def test_get_players_empty(self, client):
        res = client.get("/api/players")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_get_players_populated(self, client, populated_state):
        res = client.get("/api/players")
        assert res.status_code == 200
        players = res.json()
        assert len(players) > 0
        assert "player_id" in players[0]
        assert "projected_points" in players[0]

    def test_filter_by_position(self, client, populated_state):
        res = client.get("/api/players?position=QB")
        assert res.status_code == 200
        players = res.json()
        assert all(p["position"] == "QB" for p in players)

    def test_draft_player_mine(self, client, populated_state):
        pid = "QB_0"
        res = client.post("/api/draft", json={"player_id": pid, "team": "mine"})
        assert res.status_code == 200
        assert pid in state.my_team

    def test_draft_player_opponent(self, client, populated_state):
        pid = "RB_0"
        res = client.post("/api/draft", json={"player_id": pid, "team": "opponent"})
        assert res.status_code == 200
        assert pid in state.opponent_picks

    def test_draft_already_drafted(self, client, populated_state):
        pid = "QB_0"
        client.post("/api/draft", json={"player_id": pid, "team": "mine"})
        res = client.post("/api/draft", json={"player_id": pid, "team": "opponent"})
        assert res.status_code == 400

    def test_undo_draft(self, client, populated_state):
        pid = "QB_0"
        client.post("/api/draft", json={"player_id": pid, "team": "mine"})
        res = client.delete(f"/api/draft/{pid}")
        assert res.status_code == 200
        assert pid not in state.my_team

    def test_my_team(self, client, populated_state):
        client.post("/api/draft", json={"player_id": "QB_0", "team": "mine"})
        res = client.get("/api/my-team")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1

    def test_drafted(self, client, populated_state):
        client.post("/api/draft", json={"player_id": "RB_0", "team": "opponent"})
        res = client.get("/api/drafted")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1

    def test_recommendation(self, client, populated_state):
        res = client.get("/api/recommend")
        assert res.status_code == 200
        data = res.json()
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0

    def test_reset(self, client, populated_state):
        client.post("/api/draft", json={"player_id": "QB_0", "team": "mine"})
        res = client.post("/api/reset")
        assert res.status_code == 200
        assert len(state.my_team) == 0
