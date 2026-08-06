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


def test_roster_fetch_keeps_healthy_seasons_when_future_file_is_broken(
    monkeypatch,
    tmp_path,
):
    class FakeNFL:
        @staticmethod
        def import_seasonal_rosters(seasons):
            season = seasons[0]
            if season == 2026:
                raise OSError("malformed upstream parquet")
            return pd.DataFrame([{
                "player_id": f"player-{season}",
                "season": season,
                "player_name": f"Player {season}",
                "position": "WR",
                "team": "WAS",
            }])

    monkeypatch.setattr(fetch, "nfl", FakeNFL())
    monkeypatch.setattr(fetch, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        fetch,
        "_read_release_csv",
        lambda _url: (_ for _ in ()).throw(OSError("CSV unavailable")),
    )

    result = fetch.fetch_roster_info([2024, 2025, 2026])

    assert set(result["season"]) == {2024, 2025}
    assert (tmp_path / "roster_info.parquet").exists()


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


def test_sleeper_overlay_synthesizes_recently_added_active_veteran(monkeypatch):
    roster = pd.DataFrame([{
        "player_id": "00-0031588",
        "season": 2025,
        "player_name": "Stefon Diggs",
        "position": "WR",
        "team": "NE",
        "status": "ACT",
    }])
    sleeper = {
        "2449": {
            "gsis_id": "00-0031588",
            "full_name": "Stefon Diggs",
            "position": "WR",
            "team": "WAS",
            "status": "Active",
            "depth_chart_order": 2,
        },
    }
    monkeypatch.setattr(sleeper_rosters, "fetch_sleeper_players", lambda: sleeper)

    result = sleeper_rosters.apply_sleeper_team_overrides(
        roster,
        target_season=2026,
        verbose=False,
    )

    current = result[result["season"].eq(2026)]
    assert len(current) == 1
    assert current.iloc[0]["player_id"] == "00-0031588"
    assert current.iloc[0]["team"] == "WAS"
    assert current.iloc[0]["status"] == "ACT"


def test_sleeper_overlay_uses_sleeper_id_when_public_name_changes(monkeypatch):
    roster = pd.DataFrame([{
        "player_id": "00-0036919",
        "sleeper_id": "7567",
        "season": 2026,
        "player_name": "Kenneth Gainwell",
        "position": "RB",
        "team": "TB",
        "status": "ACT",
    }])
    sleeper = {
        "7567": {
            "full_name": "Kenny Gainwell",
            "position": "RB",
            "team": "TB",
            "status": "Active",
            "depth_chart_order": 2,
        },
    }

    result = sleeper_rosters.apply_sleeper_team_overrides(
        roster,
        target_season=2026,
        sleeper=sleeper,
        verbose=False,
    )

    assert result.iloc[0]["status"] == "ACT"


def test_sleeper_overlay_corrects_current_fantasy_position(monkeypatch):
    roster = pd.DataFrame([{
        "player_id": "00-0041099",
        "sleeper_id": "13533",
        "season": 2026,
        "player_name": "Barion Brown",
        "position": "KR",
        "team": "NO",
        "status": "ACT",
    }])
    sleeper = {
        "13533": {
            "full_name": "Barion Brown",
            "position": "WR",
            "team": "NO",
            "status": "Active",
            "depth_chart_order": 8,
        },
    }

    result = sleeper_rosters.apply_sleeper_team_overrides(
        roster,
        target_season=2026,
        sleeper=sleeper,
        verbose=False,
    )

    assert result.iloc[0]["position"] == "WR"
