"""Focused tests for time-sensitive external data adapters."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.data import fetch
from src.data import sleeper_rosters


def test_fantasypros_title_must_match_requested_season():
    assert fetch._fantasypros_page_matches_season("<title>2025 Fantasy Football ADP</title>", 2025)
    assert not fetch._fantasypros_page_matches_season("<title>2026 Fantasy Football ADP</title>", 2025)


def test_current_adp_cache_expires_but_historical_snapshot_does_not():
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    rows = pd.DataFrame([{
        "season": 2026,
        "requested_season": 2026,
        "source_url": "https://example.test/2026",
        "fetched_at": (now - timedelta(hours=13)).isoformat(),
        "player_name": f"Player {i}",
        "position": "WR",
        "adp": i + 1,
    } for i in range(50)])
    assert not fetch._adp_cache_rows_reusable(rows, 2026, now, 12)

    historical = rows.assign(
        season=2025,
        requested_season=2025,
        source_url="https://example.test/2025",
    )
    assert fetch._adp_cache_rows_reusable(historical, 2025, now, 12)


def test_new_depth_schema_uses_position_rank(monkeypatch, tmp_path):
    raw = pd.DataFrame([
        {"dt": "2025-09-05T00:00:00Z", "team": "KC", "gsis_id": "q1", "player_name": "QB One", "pos_abb": "QB", "pos_slot": 9, "pos_rank": 1},
        {"dt": "2025-09-05T00:00:00Z", "team": "KC", "gsis_id": "q2", "player_name": "QB Two", "pos_abb": "QB", "pos_slot": 10, "pos_rank": 2},
    ])
    monkeypatch.setattr(fetch, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pd, "read_csv", lambda _url: raw.copy())
    result = fetch.fetch_depth_charts([2025], cache=False)
    assert result.set_index("gsis_id")["depth_rank"].to_dict() == {"q1": 1, "q2": 2}


def test_sleeper_name_fallback_requires_same_position(monkeypatch):
    roster = pd.DataFrame([
        {"player_id": "db-lamar", "season": 2025, "player_name": "Lamar Jackson", "position": "DB", "team": "CAR", "status": "ACT"},
        {"player_id": "qb-lamar", "season": 2025, "player_name": "Lamar Jackson", "position": "QB", "team": "BAL", "status": "ACT"},
    ])
    sleeper = {
        "1": {
            "full_name": "Lamar Jackson",
            "position": "QB",
            "team": "BAL",
            "status": "Active",
            "depth_chart_order": 1,
        },
    }
    monkeypatch.setattr(sleeper_rosters, "fetch_sleeper_players", lambda: sleeper)
    result = sleeper_rosters.apply_sleeper_team_overrides(roster, target_season=2026, verbose=False)
    current = result[result["season"].eq(2026)]
    assert set(current["player_id"]) == {"qb-lamar"}
    assert current.iloc[0]["position"] == "QB"


def test_sleeper_overlay_excludes_stale_active_player_without_depth_slot(monkeypatch):
    roster = pd.DataFrame([
        {"player_id": "old-qb", "season": 2026, "player_name": "Old Quarterback", "position": "QB", "team": "PIT", "status": "ACT"},
        {"player_id": "new-qb", "season": 2026, "player_name": "Current Quarterback", "position": "QB", "team": "PIT", "status": "ACT"},
    ])
    sleeper = {
        "1": {"full_name": "Old Quarterback", "position": "QB", "team": "PIT", "status": "Active", "depth_chart_order": None},
        "2": {"full_name": "Current Quarterback", "position": "QB", "team": "PIT", "status": "Active", "depth_chart_order": 1},
    }
    monkeypatch.setattr(sleeper_rosters, "fetch_sleeper_players", lambda: sleeper)
    result = sleeper_rosters.apply_sleeper_team_overrides(roster, target_season=2026, verbose=False)
    statuses = result.set_index("player_id")["status"].to_dict()
    assert statuses == {"old-qb": "INA", "new-qb": "ACT"}


def test_sleeper_overlay_handles_aliases_unicode_and_position_changes(monkeypatch):
    roster = pd.DataFrame([
        {"player_id": "gainwell", "season": 2026, "player_name": "Kenneth Gainwell", "position": "RB", "team": "PIT", "status": "ACT"},
        {"player_id": "estime", "season": 2026, "player_name": "Audric Estimé", "position": "RB", "team": "NO", "status": "ACT"},
        {"player_id": "hunter", "season": 2025, "player_name": "Travis Hunter", "position": "WR", "team": "JAX", "status": "RES"},
        {"player_id": "hunter", "season": 2026, "player_name": "Travis Hunter", "position": "DB", "team": "JAX", "status": "ACT"},
        {"player_id": "beck", "season": 2026, "player_name": "Andrew Beck", "position": "FB", "team": "NYJ", "status": "ACT"},
    ])
    sleeper = {
        "1": {"full_name": "Kenny Gainwell", "position": "RB", "team": "TB", "status": "Active", "depth_chart_order": 2},
        "2": {"full_name": "Audric Estime", "position": "RB", "team": "NO", "status": "Active", "depth_chart_order": 6},
        "3": {"full_name": "Travis Hunter", "position": "WR", "team": "JAX", "status": "Active", "depth_chart_order": 4},
        "4": {"full_name": "Andrew Beck", "position": "RB", "team": "NYJ", "status": "Active", "depth_chart_order": 4, "gsis_id": " beck "},
    }
    monkeypatch.setattr(sleeper_rosters, "fetch_sleeper_players", lambda: sleeper)
    result = sleeper_rosters.apply_sleeper_team_overrides(roster, target_season=2026, verbose=False)
    current = result[result["season"].eq(2026)].set_index("player_id")

    assert current.loc["gainwell", "team"] == "TB"
    assert current.loc["gainwell", "status"] == "ACT"
    assert current.loc["estime", "status"] == "ACT"
    assert current.loc["hunter", "position"] == "WR"
    assert current.loc["beck", "position"] == "RB"
