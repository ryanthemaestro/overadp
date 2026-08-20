#!/usr/bin/env python3
"""Refresh draft-market fields without retraining the projection model.

The expensive model export is intentionally separate from this daily job.
This script updates volatile draft-day inputs (ADP, teams, and bye weeks),
rebuilds sleeper/bust labels, records source provenance, and keeps both
published data directories byte-for-byte identical.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_DIR = PROJECT_ROOT / "site" / "app" / "data"
MODEL_DATA_DIR = PROJECT_ROOT / "src" / "api" / "static" / "data"
FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/half-ppr?teams=12&year=2026"
SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
MODEL_BASELINE_GENERATED_AT = "2026-07-20T14:49:24Z"
PROJECTION_SEASON = 2026
NFLVERSE_WEEKLY_ROSTER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/"
    f"roster_weekly_{PROJECTION_SEASON}.csv"
)
NFLVERSE_INJURY_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/injuries/"
    f"injuries_{PROJECTION_SEASON}.csv"
)
NFLVERSE_INJURY_RELEASE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/tag/injuries"
)
NFLVERSE_LICENSE_URL = (
    "https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md"
)
PRESEASON_INJURY_FILE = PROJECT_ROOT / "preseason_injuries.json"
OPENING_WEEK_WEIGHTS = {1: 0.55, 2: 0.30, 3: 0.15}
# Fit on 2021-2024 regular-season data, then checked out of sample on 2025.
KICKER_MODEL = {
    "intercept": 4.7215,
    "own_implied": 0.1446,
    "indoor": 0.6755,
    "home": 0.1218,
}
DEFENSE_MODEL = {
    "intercept": 15.2133,
    "opponent_implied": -0.4041,
}
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
VALID_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}
TEAM_TO_BOARD = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}
TEAM_ALIASES = {
    "JAC": "JAX", "JAX": "JAC",
    "LAR": "LA", "LA": "LAR",
    "WSH": "WAS", "WAS": "WSH",
}
# Fixed-roof venues are known months ahead. Retractable roofs receive partial
# indoor credit until the game-week roof status is available.
FIXED_INDOOR_HOME_TEAMS = {"ATL", "DET", "LA", "LAC", "LV", "MIN", "NO"}
RETRACTABLE_ROOF_HOME_TEAMS = {"ARI", "DAL", "HOU", "IND"}
NAME_ALIASES = {
    ("kenny gainwell", "RB"): ("kenneth gainwell", "RB"),
}
INJURY_EXPORT_FIELDS = {
    "injury_status",
    "injury_body_part",
    "injury_notes",
    "injury_start_date",
    "injury_news_updated",
    "injury_source_updated_at",
    "injury_source_url",
    "injury_source_label",
    "practice_participation",
    "practice_description",
    "roster_status",
    "season_outlook",
    "expected_games_missed",
    "expected_return_date",
    "outlook_confidence",
}
PRESEASON_OUTLOOKS = {
    "expected_week_1",
    "monitor_week_1",
    "expected_absence",
    "season_out",
}
NFLVERSE_INJURY_ROSTER_CODES = {
    "P02": "Practice Squad Injured",
    "R01": "Injured Reserve",
    "R04": "PUP",
    "R05": "NFI",
    "R27": "NFI",
    # Current 2026 Shield roster codes. These are intentionally limited to
    # statuses confirmed against club transaction/roster pages; generic
    # reserve codes (for example unsigned draft choices) remain unclassified.
    "R34": "Injured Reserve",
    "R36": "Injured Reserve",
    "R37": "PUP",
    "R41": "PUP",
    "R46": "NFI",
    "R47": "NFI",
    "R48": "Injured Reserve",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def normalize_team(value: Any) -> str:
    team = str(value or "").strip().upper()
    return TEAM_TO_BOARD.get(team, team)


def normalize_position(value: Any) -> str:
    position = str(value or "").strip().upper()
    return "K" if position == "PK" else position


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    for token in ("'", ".", "-", "’"):
        text = text.replace(token, "")
    return " ".join(text.split())


def normalize_base_name(value: Any) -> str:
    words = normalize_name(value).split()
    while words and words[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        words.pop()
    return " ".join(words)


def player_key(name: Any, position: Any) -> tuple[str, str]:
    key = (normalize_name(name), normalize_position(position))
    return NAME_ALIASES.get(key, key)


def normalize_provider_id(value: Any) -> str:
    if value is None:
        return ""
    result = str(value).strip()
    return result[:-2] if result.endswith(".0") and result[:-2].isdigit() else result


def clean_feed_text(value: Any, max_length: int = 240) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    return text[:max_length] if text else None


def clear_injury_fields(player: dict[str, Any]) -> None:
    for field in INJURY_EXPORT_FIELDS:
        player.pop(field, None)


def row_integer(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def latest_nflverse_week(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int | None]:
    season_rows = [
        row for row in rows
        if row_integer(row.get("season")) == PROJECTION_SEASON
        and row_integer(row.get("week")) is not None
    ]
    if not season_rows:
        return [], None
    latest_week = max(row_integer(row.get("week")) or 0 for row in season_rows)
    return [
        row for row in season_rows
        if row_integer(row.get("week")) == latest_week
    ], latest_week


def nflverse_player_indexes(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    by_gsis: dict[str, dict[str, Any]] = {}
    name_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    base_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        position = normalize_position(row.get("position"))
        if position not in SKILL_POSITIONS | {"K"}:
            continue
        gsis_id = normalize_provider_id(row.get("gsis_id"))
        if gsis_id:
            by_gsis[gsis_id] = row
        full_name = clean_feed_text(row.get("full_name")) or " ".join(
            part for part in (
                clean_feed_text(row.get("first_name")),
                clean_feed_text(row.get("last_name")),
            )
            if part
        )
        if not full_name:
            continue
        name_candidates[player_key(full_name, position)].append(row)
        base_candidates[(normalize_base_name(full_name), position)].append(row)
    unique_names = {
        key: candidates[0]
        for key, candidates in name_candidates.items()
        if len(candidates) == 1
    }
    unique_base_names = {
        key: candidates[0]
        for key, candidates in base_candidates.items()
        if len(candidates) == 1
    }
    return by_gsis, unique_names, unique_base_names


def find_nflverse_player(
    player: dict[str, Any],
    indexes: tuple[
        dict[str, dict[str, Any]],
        dict[tuple[str, str], dict[str, Any]],
        dict[tuple[str, str], dict[str, Any]],
    ],
) -> dict[str, Any] | None:
    by_gsis, by_name, by_base_name = indexes
    position = normalize_position(player.get("position"))
    match = by_gsis.get(normalize_provider_id(player.get("player_id")))
    if not match:
        match = by_name.get(player_key(player.get("player_name"), position))
    if not match:
        match = by_base_name.get(
            (normalize_base_name(player.get("player_name")), position)
        )
    if match and normalize_position(match.get("position")) == position:
        return match
    return None


def apply_nflverse_injury_fields(
    player: dict[str, Any],
    injury_report: dict[str, Any] | None,
    roster: dict[str, Any] | None,
    source_updated_at: str,
) -> str | None:
    """Replace volatile injury fields from nflverse's GitHub releases."""
    clear_injury_fields(player)
    roster_status = clean_feed_text((roster or {}).get("status"), 32)
    if roster_status and roster_status != "ACT":
        player["roster_status"] = roster_status

    injury_status = clean_feed_text((injury_report or {}).get("report_status"), 32)
    if not injury_status and injury_report and any(
        clean_feed_text(injury_report.get(field))
        for field in (
            "report_primary_injury",
            "report_secondary_injury",
            "practice_primary_injury",
            "practice_secondary_injury",
            "practice_status",
        )
    ):
        # Practice participation can be published before the official weekly
        # Q/D/O game designation. Keep it informational rather than inventing
        # a game-status probability.
        injury_status = "INJ"
    if not injury_status:
        roster_code = clean_feed_text(
            (roster or {}).get("status_description_abbr"),
            16,
        )
        injury_status = NFLVERSE_INJURY_ROSTER_CODES.get(roster_code or "")
    if not injury_status:
        return None

    player["injury_status"] = injury_status
    body_parts: list[str] = []
    for field in (
        "report_primary_injury",
        "report_secondary_injury",
        "practice_primary_injury",
        "practice_secondary_injury",
    ):
        value = clean_feed_text((injury_report or {}).get(field))
        if value and value not in body_parts:
            body_parts.append(value)
    if body_parts:
        player["injury_body_part"] = " / ".join(body_parts)[:240]
    practice_status = clean_feed_text((injury_report or {}).get("practice_status"))
    if practice_status:
        player["practice_participation"] = practice_status
        player["practice_description"] = practice_status
    player["injury_source_updated_at"] = source_updated_at
    return injury_status


def apply_preseason_injury_note(
    player: dict[str, Any],
    note: dict[str, Any] | None,
    refreshed_at: str,
) -> str | None:
    """Apply a reviewed, informational preseason note from this repository."""
    if not note:
        return None
    expires_on = clean_feed_text(note.get("expires_on"), 10)
    try:
        if expires_on and date.fromisoformat(expires_on) < date.fromisoformat(refreshed_at[:10]):
            return None
    except ValueError:
        return None

    player["injury_status"] = "INJ"
    body_part = clean_feed_text(note.get("injury_body_part"))
    notes = clean_feed_text(note.get("injury_notes"))
    if body_part:
        player["injury_body_part"] = body_part
    if notes:
        player["injury_notes"] = notes
    season_outlook = clean_feed_text(note.get("season_outlook"), 32)
    if season_outlook in PRESEASON_OUTLOOKS:
        player["season_outlook"] = season_outlook
    try:
        expected_games_missed = float(note.get("expected_games_missed"))
    except (TypeError, ValueError):
        expected_games_missed = 0.0
    player["expected_games_missed"] = expected_games_missed
    expected_return_date = clean_feed_text(note.get("expected_return_date"), 10)
    if expected_return_date:
        player["expected_return_date"] = expected_return_date
    outlook_confidence = clean_feed_text(note.get("outlook_confidence"), 16)
    if outlook_confidence:
        player["outlook_confidence"] = outlook_confidence
    player["injury_source_updated_at"] = (
        clean_feed_text(note.get("source_updated_at"), 32) or refreshed_at
    )
    source_url = clean_feed_text(note.get("source_url"))
    source_label = clean_feed_text(note.get("source_label"), 64)
    if source_url:
        player["injury_source_url"] = source_url
    if source_label:
        player["injury_source_label"] = source_label
    return "INJ"


def apply_injury_overlay(
    players: list[dict[str, Any]],
    roster_rows: list[dict[str, Any]],
    injury_report_rows: list[dict[str, Any]],
    source_updated_at: str,
    preseason_injury_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_rosters, roster_week = latest_nflverse_week(roster_rows)
    current_injuries, injury_week = latest_nflverse_week(injury_report_rows)
    if len(current_rosters) < 2000:
        raise ValueError(
            "nflverse weekly roster feed is missing or unexpectedly small: "
            f"{len(current_rosters)} rows"
        )
    if injury_week is not None and injury_week <= 18 and len(current_injuries) < 100:
        raise ValueError(
            "nflverse weekly injury report appears partial: "
            f"week {injury_week} has {len(current_injuries)} rows"
        )
    roster_indexes = nflverse_player_indexes(current_rosters)
    injury_indexes = nflverse_player_indexes(current_injuries)
    preseason_indexes = nflverse_player_indexes(preseason_injury_rows or [])
    matches = 0
    preseason_notes_applied = 0
    status_counts: Counter[str] = Counter()
    for player in players:
        clear_injury_fields(player)
        roster = find_nflverse_player(player, roster_indexes)
        if not roster:
            continue
        matches += 1
        injury_report = find_nflverse_player(player, injury_indexes)
        injury_status = apply_nflverse_injury_fields(
            player,
            injury_report,
            roster,
            source_updated_at,
        )
        if not injury_status and not current_injuries:
            preseason_note = find_nflverse_player(player, preseason_indexes)
            injury_status = apply_preseason_injury_note(
                player,
                preseason_note,
                source_updated_at,
            )
            if injury_status:
                preseason_notes_applied += 1
        if injury_status:
            status_counts[injury_status] += 1
    if matches < 650:
        raise ValueError(
            f"nflverse injury roster join failed quality gate: {matches}/{len(players)}"
        )
    return {
        "matched_skill_players": matches,
        "status_counts": status_counts,
        "latest_roster_week": roster_week,
        "latest_injury_report_week": injury_week,
        "injury_report_rows": len(current_injuries),
        "preseason_notes_applied": preseason_notes_applied,
    }


def injury_metadata(now: datetime, overlay: dict[str, Any]) -> dict[str, Any]:
    status_counts: Counter[str] = overlay["status_counts"]
    return {
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "source": "nflverse GitHub data releases",
        "source_url": NFLVERSE_WEEKLY_ROSTER_URL,
        "injury_report_source_url": NFLVERSE_INJURY_URL,
        "injury_release_url": NFLVERSE_INJURY_RELEASE_URL,
        "license": "CC BY 4.0",
        "license_url": NFLVERSE_LICENSE_URL,
        "attribution": "nflverse",
        "refresh_cadence": "daily",
        "matched_skill_players": overlay["matched_skill_players"],
        "skill_players_flagged": sum(status_counts.values()),
        "status_counts": dict(sorted(status_counts.items())),
        "latest_roster_week": overlay["latest_roster_week"],
        "latest_injury_report_week": overlay["latest_injury_report_week"],
        "injury_report_available": overlay["injury_report_rows"] > 0,
        "preseason_notes_applied": overlay["preseason_notes_applied"],
        "preseason_notes_source": "repository-reviewed public reports",
        "preseason_coverage_scope": (
            "reviewed fantasy-relevant reports; no badge is not a health guarantee"
        ),
        "reporting_mode": (
            "official_game_status"
            if overlay["injury_report_rows"] > 0
            else "preseason_availability"
        ),
        "draft_adjustment_policy": (
            "reviewed preseason return outlooks adjust recommendations from "
            "expected games missed; official reserve-list statuses remain hard penalties"
        ),
    }


def refresh_injuries_only(
    roster_rows: list[dict[str, Any]],
    injury_report_rows: list[dict[str, Any]],
    now: datetime,
    preseason_injury_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update volatile injury fields without weakening the full release gates."""
    players = load_json(SITE_DATA_DIR / "players.json")
    metadata = load_json(SITE_DATA_DIR / "metadata.json")
    if not isinstance(players, list) or len(players) < 800:
        raise ValueError("Current skill-player board is missing or unexpectedly small")
    if not isinstance(metadata, dict):
        raise ValueError("Current metadata is missing or invalid")

    fetched_at = now.isoformat().replace("+00:00", "Z")
    overlay = apply_injury_overlay(
        players,
        roster_rows,
        injury_report_rows,
        fetched_at,
        preseason_injury_rows,
    )
    status_counts: Counter[str] = overlay["status_counts"]
    metadata["injuries"] = injury_metadata(now, overlay)
    metadata.setdefault("counts", {})["current_injury_designations"] = sum(
        status_counts.values()
    )
    for directory in (SITE_DATA_DIR, MODEL_DATA_DIR):
        dump_json(directory / "players.json", players)
        dump_json(directory / "metadata.json", metadata)
    return metadata


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "OverADP-DraftReadiness/1.0 (+https://overadp.com)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.load(response)


def fetch_csv(url: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/csv",
            "User-Agent": "OverADP-DraftReadiness/1.0 (+https://overadp.com)",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        text = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def fetch_optional_csv(url: str) -> list[dict[str, str]]:
    try:
        return fetch_csv(url)
    except HTTPError as exc:
        if exc.code == 404:
            return []
        raise


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_preseason_injury_file(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, dict) or payload.get("season") != PROJECTION_SEASON:
        raise ValueError("Preseason injury file has the wrong season or schema")
    rows = payload.get("players")
    if not isinstance(rows, list):
        raise ValueError("Preseason injury file must contain a players list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Preseason injury rows must be objects")
        if normalize_position(row.get("position")) not in SKILL_POSITIONS:
            raise ValueError(f"Invalid preseason injury position: {row!r}")
        if not clean_feed_text(row.get("full_name")):
            raise ValueError(f"Preseason injury row is missing full_name: {row!r}")
        if not str(row.get("source_url") or "").startswith("https://"):
            raise ValueError(f"Preseason injury row is missing an HTTPS source: {row!r}")
        if row.get("season_outlook") not in PRESEASON_OUTLOOKS:
            raise ValueError(f"Invalid preseason season outlook: {row!r}")
        try:
            expected_games_missed = float(row["expected_games_missed"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid expected games missed: {row!r}") from exc
        if not math.isfinite(expected_games_missed) or not 0 <= expected_games_missed <= 17:
            raise ValueError(f"Invalid expected games missed: {row!r}")
        if row.get("outlook_confidence") not in {"reported", "estimated"}:
            raise ValueError(f"Invalid preseason outlook confidence: {row!r}")
        try:
            date.fromisoformat(str(row["expires_on"]))
            if row.get("expected_return_date"):
                date.fromisoformat(str(row["expected_return_date"]))
            updated = datetime.fromisoformat(
                str(row["source_updated_at"]).replace("Z", "+00:00")
            )
            if updated.tzinfo is None:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid preseason injury dates: {row!r}") from exc
    return rows


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def positive_number(value: Any, default: float = 200.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number <= 0:
        return default
    return number


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def expected_indoor_share(roof: Any, home_team: str) -> float:
    roof_name = str(roof or "").strip().lower()
    if roof_name in {"dome", "closed"}:
        return 1.0
    if roof_name in {"outdoors", "open"}:
        return 0.0
    normalized_home = normalize_team(home_team)
    if normalized_home in FIXED_INDOOR_HOME_TEAMS:
        return 1.0
    if normalized_home in RETRACTABLE_ROOF_HOME_TEAMS:
        return 0.65
    return 0.0


def kicker_expected_points(
    own_implied: float,
    indoor_share: float,
    is_home: bool,
) -> float:
    return (
        KICKER_MODEL["intercept"]
        + KICKER_MODEL["own_implied"] * own_implied
        + KICKER_MODEL["indoor"] * indoor_share
        + KICKER_MODEL["home"] * int(is_home)
    )


def defense_expected_points(opponent_implied: float) -> float:
    return (
        DEFENSE_MODEL["intercept"]
        + DEFENSE_MODEL["opponent_implied"] * opponent_implied
    )


def opening_schedule_contexts(
    schedule_rows: list[dict[str, Any]],
    season: int = PROJECTION_SEASON,
) -> dict[str, list[dict[str, Any]]]:
    opening_rows = [
        row
        for row in schedule_rows
        if int(finite_number(row.get("season")) or 0) == season
        and str(row.get("game_type") or "").upper() == "REG"
        and int(finite_number(row.get("week")) or 0) in OPENING_WEEK_WEIGHTS
    ]
    expected_games = 16 * len(OPENING_WEEK_WEIGHTS)
    if len(opening_rows) != expected_games:
        raise ValueError(
            f"nflverse opening schedule has {len(opening_rows)} games "
            f"(expected {expected_games})"
        )

    contexts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in opening_rows:
        week = int(float(row["week"]))
        home_team = normalize_team(row.get("home_team"))
        away_team = normalize_team(row.get("away_team"))
        spread = finite_number(row.get("spread_line"))
        total = finite_number(row.get("total_line"))
        if (
            home_team not in VALID_TEAMS
            or away_team not in VALID_TEAMS
            or home_team == away_team
            or spread is None
            or total is None
            or total <= 0
        ):
            raise ValueError(f"Malformed nflverse opening game: {row!r}")
        indoor_share = expected_indoor_share(row.get("roof"), home_team)
        home_implied = total / 2 + spread / 2
        away_implied = total / 2 - spread / 2
        shared = {
            "week": week,
            "total": round(total, 1),
            "indoor_share": round(indoor_share, 2),
            "venue": (
                "INDOOR"
                if indoor_share >= 0.95
                else "ROOF TBD"
                if indoor_share > 0
                else "OUTDOOR"
            ),
        }
        contexts[home_team].append({
            **shared,
            "opponent": away_team,
            "location": "VS",
            "home": True,
            "own_implied": round(home_implied, 2),
            "opponent_implied": round(away_implied, 2),
        })
        contexts[away_team].append({
            **shared,
            "opponent": home_team,
            "location": "AT",
            "home": False,
            "own_implied": round(away_implied, 2),
            "opponent_implied": round(home_implied, 2),
        })

    if set(contexts) != VALID_TEAMS:
        raise ValueError(
            "nflverse opening schedule team coverage differs from 32 teams; "
            f"missing={sorted(VALID_TEAMS - set(contexts))}, "
            f"extra={sorted(set(contexts) - VALID_TEAMS)}"
        )
    for team, games in contexts.items():
        games.sort(key=lambda game: game["week"])
        weeks = [game["week"] for game in games]
        if weeks != sorted(OPENING_WEEK_WEIGHTS):
            raise ValueError(f"{team} opening schedule weeks are {weeks}")
    return dict(contexts)


def validate_ffc_payload(payload: Any, today: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("players"), list):
        raise ValueError("FFC response is missing the players list")
    meta = payload.get("meta") or {}
    rows = payload["players"]
    if meta.get("type") != "Half-PPR" or int(meta.get("teams", 0)) != 12:
        raise ValueError(f"Unexpected FFC format: {meta!r}")
    if len(rows) < 180:
        raise ValueError(f"FFC row count dropped to {len(rows)} (expected at least 180)")

    skill_rows = [row for row in rows if normalize_position(row.get("position")) in SKILL_POSITIONS]
    special_rows = [row for row in rows if normalize_position(row.get("position")) in {"K", "DEF"}]
    if len(skill_rows) < 150 or len(special_rows) < 25:
        raise ValueError(
            f"FFC position coverage is too small: {len(skill_rows)} skill, "
            f"{len(special_rows)} K/DEF"
        )

    period_end = meta.get("end_date")
    try:
        end_date = date.fromisoformat(str(period_end))
    except ValueError as exc:
        raise ValueError(f"FFC end_date is invalid: {period_end!r}") from exc
    lag_days = (today - end_date).days
    if lag_days < 0 or lag_days > 3:
        raise ValueError(f"FFC snapshot is stale or future-dated: {period_end}")
    if int(meta.get("total_drafts", 0)) < 50:
        raise ValueError("FFC sample contains fewer than 50 drafts")

    for row in rows:
        if not row.get("name") or normalize_position(row.get("position")) not in SKILL_POSITIONS | {"K", "DEF"}:
            raise ValueError(f"Malformed FFC player row: {row!r}")
        if positive_number(row.get("adp")) >= 200:
            raise ValueError(f"Invalid FFC ADP for {row.get('name')!r}")
    return meta, rows


def sleeper_indexes(
    payload: Any,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    if not isinstance(payload, dict) or len(payload) < 5000:
        raise ValueError("Sleeper player feed is unexpectedly small")
    by_gsis: dict[str, dict[str, Any]] = {}
    name_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    base_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        gsis_id = str(row.get("gsis_id") or "").strip()
        if gsis_id:
            by_gsis[gsis_id] = row
        position = normalize_position(row.get("position"))
        if position not in SKILL_POSITIONS:
            continue
        full_name = row.get("full_name") or " ".join(
            part for part in (str(row.get("first_name") or "").strip(), str(row.get("last_name") or "").strip())
            if part
        )
        if not full_name:
            continue
        name_candidates[player_key(full_name, position)].append(row)
        base_candidates[(normalize_base_name(full_name), position)].append(row)
    if len(by_gsis) < 1000:
        raise ValueError("Sleeper feed has too few GSIS identifiers")
    unique_names = {
        key: rows[0] for key, rows in name_candidates.items() if len(rows) == 1
    }
    unique_base_names = {
        key: rows[0] for key, rows in base_candidates.items() if len(rows) == 1
    }
    return by_gsis, unique_names, unique_base_names


def active_depth_projection_coverage(
    players: list[dict[str, Any]],
    sleeper_payload: Any,
) -> dict[str, Any]:
    """Require every reliable active Sleeper depth-chart player on the board."""
    if not isinstance(sleeper_payload, dict):
        raise ValueError("Sleeper player feed is not an object")
    board_ids = {normalize_provider_id(row.get("player_id")) for row in players}
    board_sleeper_ids = {
        normalize_provider_id(row.get("sleeper_id")) for row in players
    }
    board_names = {
        player_key(row.get("player_name"), row.get("position")) for row in players
    }

    expected = 0
    missing: list[str] = []
    for sleeper_id, row in sleeper_payload.items():
        if not isinstance(row, dict):
            continue
        position = normalize_position(row.get("position"))
        if (
            row.get("status") != "Active"
            or not row.get("team")
            or row.get("depth_chart_order") is None
            or position not in SKILL_POSITIONS
        ):
            continue
        expected += 1
        full_name = row.get("full_name") or " ".join(
            part
            for part in (
                str(row.get("first_name") or "").strip(),
                str(row.get("last_name") or "").strip(),
            )
            if part
        )
        gsis_id = normalize_provider_id(row.get("gsis_id") or row.get("gsis_player_id"))
        matched = (
            (gsis_id and gsis_id in board_ids)
            or normalize_provider_id(sleeper_id) in board_sleeper_ids
            or player_key(full_name, position) in board_names
        )
        if not matched:
            missing.append(f"{full_name}|{position}")
    return {
        "expected_active_depth_players": expected,
        "matched_active_depth_players": expected - len(missing),
        "missing_active_depth_players": missing,
    }


def tied_ranks(rows: list[dict[str, Any]], field: str, reverse: bool) -> dict[int, int]:
    ordered = sorted(
        enumerate(rows),
        key=lambda item: positive_number(item[1].get(field), 0.0),
        reverse=reverse,
    )
    ranks: dict[int, int] = {}
    prior_value: float | None = None
    prior_rank = 0
    for ordinal, (original_index, row) in enumerate(ordered, start=1):
        value = positive_number(row.get(field), 0.0)
        if prior_value is None or value != prior_value:
            prior_rank = ordinal
            prior_value = value
        ranks[original_index] = prior_rank
    return ranks


def rebuild_sleepers_busts(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        player for player in players
        if normalize_position(player.get("position")) in SKILL_POSITIONS
        and 0 < positive_number(player.get("adp")) < 200
        and positive_number(player.get("projected_points"), 0.0) >= 40
    ]
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in candidates:
        by_position[normalize_position(player.get("position"))].append(player)

    results: list[dict[str, Any]] = []
    for position, rows in by_position.items():
        model_ranks = tied_ranks(rows, "projected_points", reverse=True)
        adp_ranks = tied_ranks(rows, "adp", reverse=False)
        for index, row in enumerate(rows):
            model_rank = model_ranks[index]
            adp_rank = adp_ranks[index]
            gap = adp_rank - model_rank
            if abs(gap) < 6:
                continue
            label = "SLEEPER" if gap > 0 else "BUST"
            if (
                label == "BUST"
                and int(row.get("is_2nd_year") or 0) == 1
                and positive_number(row.get("pts_lag1"), 0.0) > 100
            ):
                continue
            results.append({
                "player_name": row.get("player_name", ""),
                "position": position,
                "team": row.get("team", ""),
                "projected_points": round(positive_number(row.get("projected_points"), 0.0), 1),
                "model_rank": model_rank,
                "model_pos_rank": model_rank,
                "adp": round(positive_number(row.get("adp")), 1),
                "adp_pos_rank": adp_rank,
                "adp_gap": float(gap),
                "label": label,
                "reason": (
                    f"Model {position}{model_rank} · ADP {position}{adp_rank} "
                    f"({'undervalued' if label == 'SLEEPER' else 'overvalued'} "
                    f"by {abs(gap)} spots)"
                ),
            })
    return sorted(results, key=lambda row: abs(row["adp_gap"]), reverse=True)


def market_kicker_row(
    source: dict[str, Any],
    current_kickers: list[dict[str, Any]],
) -> dict[str, Any]:
    projections = [
        positive_number(row.get("projected_points"), 0.0)
        for row in current_kickers
        if positive_number(row.get("projected_points"), 0.0) > 0
    ]
    half_widths = [
        (
            positive_number(row.get("ci_high"), 0.0)
            - positive_number(row.get("ci_low"), 0.0)
        ) / 2
        for row in current_kickers
        if (
            positive_number(row.get("ci_high"), 0.0)
            > positive_number(row.get("ci_low"), 0.0)
        )
    ]
    projection = round(statistics.median(projections), 1)
    half_width = round(statistics.median(half_widths), 1)
    name = str(source.get("name") or "").strip()
    team = normalize_team(source.get("team"))
    bye = int(positive_number(source.get("bye"), 0.0))
    slug = normalize_name(name).replace(" ", "_").upper()
    return {
        "player_id": f"K_{slug}",
        "player_name": name,
        "position": "K",
        "team": team,
        "projected_points": projection,
        "ci_low": round(max(0.0, projection - half_width), 1),
        "ci_high": round(projection + half_width, 1),
        "uncertainty": 0.5,
        "risk": "high",
        "adp": round(positive_number(source.get("adp")), 1),
        "pts_lag1": 0,
        "model_used": "position_median_market_add",
        "bye": bye,
        "vbd": 0,
        "projected_receptions": 0,
    }


def current_kicker_rows(
    sleeper_payload: Any,
    previous_kickers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(sleeper_payload, dict):
        raise ValueError("Sleeper player feed is not an object")
    candidates: dict[str, list[tuple[int, str, dict[str, Any]]]] = defaultdict(list)
    for sleeper_id, row in sleeper_payload.items():
        if not isinstance(row, dict):
            continue
        if normalize_position(row.get("position")) != "K" or not row.get("active"):
            continue
        team = normalize_team(row.get("team"))
        if team not in VALID_TEAMS:
            continue
        depth_value = finite_number(row.get("depth_chart_order"))
        depth = int(depth_value) if depth_value is not None and depth_value > 0 else 99
        name = str(row.get("full_name") or "").strip()
        if not name:
            name = " ".join(
                part
                for part in (
                    str(row.get("first_name") or "").strip(),
                    str(row.get("last_name") or "").strip(),
                )
                if part
            )
        if not name:
            continue
        candidates[team].append((depth, str(sleeper_id), {**row, "full_name": name}))

    selected: dict[str, tuple[str, dict[str, Any]]] = {}
    for team, rows in candidates.items():
        rows.sort(key=lambda item: (item[0], item[2]["full_name"]))
        _, sleeper_id, row = rows[0]
        selected[team] = (sleeper_id, row)
    if set(selected) != VALID_TEAMS:
        raise ValueError(
            "Sleeper starting-kicker coverage differs from 32 teams; "
            f"missing={sorted(VALID_TEAMS - set(selected))}, "
            f"extra={sorted(set(selected) - VALID_TEAMS)}"
        )

    prior_by_name = {
        player_key(row.get("player_name"), "K"): row
        for row in previous_kickers
    }
    rebuilt: list[dict[str, Any]] = []
    for team in sorted(VALID_TEAMS):
        sleeper_id, source = selected[team]
        name = source["full_name"]
        prior = prior_by_name.get(player_key(name, "K"))
        if prior:
            row = dict(prior)
        else:
            row = market_kicker_row(
                {"name": name, "team": team, "adp": 200, "bye": 0},
                previous_kickers,
            )
            gsis_id = str(source.get("gsis_id") or "").strip()
            row["player_id"] = gsis_id or f"K_{normalize_name(name).replace(' ', '_').upper()}"
            row["model_used"] = "position_median_roster_add"
        clear_injury_fields(row)
        row.update({
            "player_name": name,
            "position": "K",
            "team": team,
            "depth_chart_order": int(finite_number(source.get("depth_chart_order")) or 1),
            "role_confidence": "HIGH",
            "roster_source": "Sleeper depth chart",
            "sleeper_id": sleeper_id,
        })
        rebuilt.append(row)
    return rebuilt


def matchup_grade(rank: int) -> str:
    if rank <= 6:
        return "A"
    if rank <= 12:
        return "B"
    if rank <= 20:
        return "C"
    return "D"


def apply_opening_streaming_model(
    k_def: list[dict[str, Any]],
    contexts: dict[str, list[dict[str, Any]]],
) -> None:
    position_rows = {
        position: [
            row for row in k_def
            if normalize_position(row.get("position")) == position
        ]
        for position in ("K", "DEF")
    }
    for position, rows in position_rows.items():
        if len(rows) != 32 or {normalize_team(row.get("team")) for row in rows} != VALID_TEAMS:
            raise ValueError(
                f"{position} streaming board must contain one row for each NFL team"
            )

        weekly_rank: dict[int, dict[str, int]] = {}
        weekly_projection: dict[int, dict[str, float]] = {}
        for week in OPENING_WEEK_WEIGHTS:
            projections: list[tuple[str, float]] = []
            for team, games in contexts.items():
                game = next(item for item in games if item["week"] == week)
                if position == "K":
                    projection = kicker_expected_points(
                        game["own_implied"],
                        game["indoor_share"],
                        game["home"],
                    )
                else:
                    projection = defense_expected_points(game["opponent_implied"])
                projections.append((team, projection))
            projections.sort(key=lambda item: (-item[1], item[0]))
            weekly_projection[week] = dict(projections)
            weekly_rank[week] = {
                team: rank for rank, (team, _) in enumerate(projections, start=1)
            }

        for row in rows:
            team = normalize_team(row.get("team"))
            opening_games = []
            weighted_projection = 0.0
            for game in contexts[team]:
                week = game["week"]
                projection = weekly_projection[week][team]
                rank = weekly_rank[week][team]
                weighted_projection += OPENING_WEEK_WEIGHTS[week] * projection
                opening_games.append({
                    "week": week,
                    "opponent": game["opponent"],
                    "location": game["location"],
                    "own_implied": game["own_implied"],
                    "opponent_implied": game["opponent_implied"],
                    "venue": game["venue"],
                    "projection": round(projection, 2),
                    "matchup_rank": rank,
                    "matchup_grade": matchup_grade(rank),
                })
            row.update({
                "opening_projection": round(weighted_projection, 2),
                "week1_projection": opening_games[0]["projection"],
                "opening_schedule": opening_games,
                "stream_model_used": "opening_schedule_v1",
            })

        ordered = sorted(
            rows,
            key=lambda row: (
                -float(row["opening_projection"]),
                positive_number(row.get("adp")),
                str(row.get("player_name") or ""),
            ),
        )
        denominator = max(1, len(ordered) - 1)
        for rank, row in enumerate(ordered, start=1):
            row["stream_rank"] = rank
            row["stream_score"] = round(100 * (len(ordered) - rank) / denominator, 1)
            row["stream_tier"] = (
                "TARGET"
                if rank <= 6
                else "PLAYABLE"
                if rank <= 12
                else "STREAM"
                if rank <= 20
                else "FADE"
            )
            row["draft_guidance"] = (
                "LAST ROUND"
                if position == "K"
                else "FINAL 2 ROUNDS"
                if rank <= 6
                else "LAST ROUND / STREAM"
            )


def refresh(
    ffc_payload: Any,
    sleeper_payload: Any,
    schedule_rows: list[dict[str, Any]],
    injury_roster_rows: list[dict[str, Any]],
    injury_report_rows: list[dict[str, Any]],
    now: datetime,
    preseason_injury_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    players = load_json(SITE_DATA_DIR / "players.json")
    k_def = load_json(SITE_DATA_DIR / "k_def.json")
    previous_metadata_path = SITE_DATA_DIR / "metadata.json"
    previous_metadata = load_json(previous_metadata_path) if previous_metadata_path.exists() else {}
    if not isinstance(players, list) or len(players) < 800:
        raise ValueError("Current skill-player board is missing or unexpectedly small")
    if not isinstance(k_def, list) or len(k_def) < 50:
        raise ValueError("Current K/DEF board is missing or unexpectedly small")

    ffc_meta, ffc_rows = validate_ffc_payload(ffc_payload, now.date())
    sleeper_gsis, sleeper_names, sleeper_base_names = sleeper_indexes(sleeper_payload)
    active_coverage = active_depth_projection_coverage(players, sleeper_payload)
    if active_coverage["missing_active_depth_players"]:
        raise ValueError(
            "Active-player projection coverage failed: "
            f"{active_coverage['matched_active_depth_players']}/"
            f"{active_coverage['expected_active_depth_players']}; "
            f"missing={active_coverage['missing_active_depth_players'][:8]}"
        )
    schedule_contexts = opening_schedule_contexts(schedule_rows)

    generated_at = now.isoformat().replace("+00:00", "Z")
    injury_overlay = apply_injury_overlay(
        players,
        injury_roster_rows,
        injury_report_rows,
        generated_at,
        preseason_injury_rows,
    )
    injury_status_counts: Counter[str] = injury_overlay["status_counts"]
    sleeper_matches = 0
    for player in players:
        player["adp"] = 200.0
        position = normalize_position(player.get("position"))
        sleeper = sleeper_gsis.get(str(player.get("player_id") or ""))
        if not sleeper:
            sleeper = sleeper_names.get(player_key(player.get("player_name"), position))
        if not sleeper:
            sleeper = sleeper_base_names.get((normalize_base_name(player.get("player_name")), position))
        if not sleeper:
            continue
        sleeper_position = normalize_position(sleeper.get("position"))
        if sleeper_position != position:
            continue
        team = normalize_team(sleeper.get("team"))
        if team in VALID_TEAMS:
            player["team"] = team
        sleeper_matches += 1
    if sleeper_matches < 650:
        raise ValueError(
            f"Sleeper roster join failed quality gate: {sleeper_matches}/{len(players)}"
        )

    player_index: dict[tuple[str, str], dict[str, Any]] = {}
    base_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        key = player_key(player.get("player_name"), player.get("position"))
        if key in player_index:
            raise ValueError(f"Duplicate normalized board key: {key}")
        player_index[key] = player
        base_candidates[
            (normalize_base_name(player.get("player_name")), normalize_position(player.get("position")))
        ].append(player)
    unique_base_index = {
        key: rows[0] for key, rows in base_candidates.items() if len(rows) == 1
    }

    bye_weeks: dict[str, int] = {}
    skill_matches = 0
    missing_skill: list[str] = []
    special_rows: list[dict[str, Any]] = []
    top_skill_rows: list[dict[str, Any]] = []
    for row in sorted(ffc_rows, key=lambda item: positive_number(item.get("adp"))):
        position = normalize_position(row.get("position"))
        source_team = str(row.get("team") or "").upper()
        board_team = normalize_team(source_team)
        bye = int(positive_number(row.get("bye"), 0.0))
        if board_team in VALID_TEAMS and bye > 0:
            bye_weeks[board_team] = bye
            bye_weeks[source_team] = bye
        if position not in SKILL_POSITIONS:
            special_rows.append(row)
            continue
        if len(top_skill_rows) < 24:
            top_skill_rows.append(row)
        player = player_index.get(player_key(row.get("name"), position))
        if not player:
            player = unique_base_index.get((normalize_base_name(row.get("name")), position))
        if not player:
            missing_skill.append(f"{row.get('name')}|{position}")
            continue
        player["adp"] = round(positive_number(row.get("adp")), 1)
        if board_team in VALID_TEAMS:
            player["team"] = board_team
        if bye > 0:
            player["bye"] = bye
        skill_matches += 1

    for source, alias in TEAM_ALIASES.items():
        if source in bye_weeks and alias not in bye_weeks:
            bye_weeks[alias] = bye_weeks[source]
    for player in players:
        bye = bye_weeks.get(str(player.get("team") or "").upper())
        if bye:
            player["bye"] = int(bye)

    skill_feed_rows = sum(
        1 for row in ffc_rows
        if normalize_position(row.get("position")) in SKILL_POSITIONS
    )
    skill_match_rate = skill_matches / max(1, skill_feed_rows)
    top_skill_matches = sum(
        1 for row in top_skill_rows
        if (
            player_key(row.get("name"), row.get("position")) in player_index
            or (normalize_base_name(row.get("name")), normalize_position(row.get("position")))
            in unique_base_index
        )
    )
    if skill_match_rate < 0.98 or top_skill_matches != len(top_skill_rows):
        raise ValueError(
            f"FFC skill join failed quality gate: {skill_matches}/{skill_feed_rows}; "
            f"top 24 {top_skill_matches}/{len(top_skill_rows)}; missing={missing_skill[:8]}"
        )

    current_defenses = [
        row for row in k_def
        if normalize_position(row.get("position")) == "DEF"
    ]
    previous_kickers = [
        row for row in k_def
        if normalize_position(row.get("position")) == "K"
    ]
    k_def = current_defenses + current_kicker_rows(sleeper_payload, previous_kickers)
    for row in k_def:
        row["adp"] = 200.0
    k_by_name = {
        player_key(row.get("player_name"), "K"): row
        for row in k_def if normalize_position(row.get("position")) == "K"
    }
    def_by_team = {
        normalize_team(row.get("team")): row
        for row in k_def if normalize_position(row.get("position")) == "DEF"
    }
    special_matches = 0
    for source in special_rows:
        position = normalize_position(source.get("position"))
        team = normalize_team(source.get("team"))
        target = (
            def_by_team.get(team)
            if position == "DEF"
            else k_by_name.get(player_key(source.get("name"), "K"))
        )
        if not target and position == "K":
            current_kickers = [
                row for row in k_def if normalize_position(row.get("position")) == "K"
            ]
            target = market_kicker_row(source, current_kickers)
            k_def.append(target)
            k_by_name[player_key(target.get("player_name"), "K")] = target
        if not target:
            continue
        target["adp"] = round(positive_number(source.get("adp")), 1)
        if team in VALID_TEAMS:
            target["team"] = team
        bye = int(positive_number(source.get("bye"), 0.0))
        if bye > 0:
            target["bye"] = bye
        special_matches += 1
    if special_matches / max(1, len(special_rows)) < 0.90:
        raise ValueError(
            f"FFC K/DEF join failed quality gate: {special_matches}/{len(special_rows)}"
        )
    for row in k_def:
        bye = bye_weeks.get(str(row.get("team") or "").upper())
        if bye:
            row["bye"] = int(bye)
    apply_opening_streaming_model(k_def, schedule_contexts)

    sleepers_busts = rebuild_sleepers_busts(players)
    prior_model = previous_metadata.get("model") or {}
    metadata = {
        "schema_version": 1,
        "projection_season": 2026,
        "model": {
            "generated_at": prior_model.get("generated_at", MODEL_BASELINE_GENERATED_AT),
            "scoring": "half_ppr",
            "method": "validated CatBoost projections with split-conformal 80% target ranges",
            "projection_mode": prior_model.get("projection_mode", "catboost"),
            "skill_players": prior_model.get("skill_players", len(players)),
            "coverage": prior_model.get("coverage", active_coverage),
        },
        "market": {
            "fetched_at": generated_at,
            "source": "Fantasy Football Calculator",
            "source_url": FFC_URL,
            "scoring": "half_ppr",
            "teams": 12,
            "drafts": int(ffc_meta.get("total_drafts", 0)),
            "period_start": ffc_meta.get("start_date"),
            "period_end": ffc_meta.get("end_date"),
            "rows": len(ffc_rows),
            "top_skill_players": [
                {
                    "name": row.get("name"),
                    "position": normalize_position(row.get("position")),
                    "adp": round(positive_number(row.get("adp")), 1),
                }
                for row in top_skill_rows
            ],
        },
        "rosters": {
            "fetched_at": generated_at,
            "source": "Sleeper public NFL player feed",
            "source_url": SLEEPER_URL,
            "matched_skill_players": sleeper_matches,
        },
        "injuries": injury_metadata(now, injury_overlay),
        "special_teams": {
            "fetched_at": generated_at,
            "schedule_source": "nflverse games and schedules",
            "schedule_source_url": SCHEDULE_URL,
            "roster_source": "Sleeper public NFL depth charts",
            "weeks": sorted(OPENING_WEEK_WEIGHTS),
            "week_weights": {
                str(week): weight for week, weight in OPENING_WEEK_WEIGHTS.items()
            },
            "method": (
                "2021-2024 calibrated matchup model: team implied scoring and "
                "indoor venue for kickers; opponent implied scoring for defenses"
            ),
            "validation": {
                "holdout_season": 2025,
                "evaluation_weeks": [1, 2, 3],
                "top_8_kicker_lift_points_per_game": 1.21,
                "top_8_defense_lift_points_per_game": 2.81,
            },
        },
        "counts": {
            "skill_players": len(players),
            "k_def_players": len(k_def),
            "total_players": len(players) + len(k_def),
            "actionable_skill_adp": sum(1 for row in players if 0 < positive_number(row.get("adp")) < 200),
            "actionable_k_def_adp": sum(1 for row in k_def if 0 < positive_number(row.get("adp")) < 200),
            "sleepers_busts": len(sleepers_busts),
            "current_injury_designations": sum(injury_status_counts.values()),
        },
        "quality": {
            "status": "passed",
            "skill_feed_rows": skill_feed_rows,
            "skill_matches": skill_matches,
            "skill_match_rate": round(skill_match_rate, 4),
            "top_24_skill_matches": top_skill_matches,
            "special_teams_feed_rows": len(special_rows),
            "special_teams_matches": special_matches,
            "opening_schedule_games": sum(
                len(games) for games in schedule_contexts.values()
            ) // 2,
            "kicker_depth_chart_teams": len({
                normalize_team(row.get("team"))
                for row in k_def
                if normalize_position(row.get("position")) == "K"
            }),
            "defense_schedule_teams": len({
                normalize_team(row.get("team"))
                for row in k_def
                if normalize_position(row.get("position")) == "DEF"
            }),
            "bye_team_codes": len(bye_weeks),
            "missing_skill_rows": missing_skill,
            "active_player_coverage": active_coverage,
        },
    }

    outputs = {
        "players.json": players,
        "k_def.json": k_def,
        "bye_weeks.json": dict(sorted(bye_weeks.items())),
        "sleepers_busts.json": sleepers_busts,
        "metadata.json": metadata,
    }
    for filename, value in outputs.items():
        dump_json(SITE_DATA_DIR / filename, value)
        dump_json(MODEL_DATA_DIR / filename, value)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffc-file", type=Path, help="Use a saved FFC response instead of the network")
    parser.add_argument("--sleeper-file", type=Path, help="Use a saved Sleeper response instead of the network")
    parser.add_argument("--schedule-file", type=Path, help="Use a saved nflverse games CSV instead of the network")
    parser.add_argument(
        "--injury-roster-file",
        type=Path,
        help="Use a saved nflverse weekly roster CSV for availability status",
    )
    parser.add_argument(
        "--injury-report-file",
        type=Path,
        help="Use a saved nflverse weekly injury report CSV",
    )
    parser.add_argument(
        "--preseason-injury-file",
        type=Path,
        default=PRESEASON_INJURY_FILE,
        help="Use reviewed preseason injury notes from a local JSON file",
    )
    parser.add_argument(
        "--injury-only",
        action="store_true",
        help="Refresh only the cached nflverse availability overlay and its metadata",
    )
    args = parser.parse_args()

    now = utc_now()
    injury_roster_rows = (
        load_csv(args.injury_roster_file)
        if args.injury_roster_file
        else fetch_csv(NFLVERSE_WEEKLY_ROSTER_URL)
    )
    injury_report_rows = (
        load_csv(args.injury_report_file)
        if args.injury_report_file
        else fetch_optional_csv(NFLVERSE_INJURY_URL)
    )
    preseason_injury_rows = load_preseason_injury_file(args.preseason_injury_file)
    if args.injury_only:
        metadata = refresh_injuries_only(
            injury_roster_rows,
            injury_report_rows,
            now,
            preseason_injury_rows,
        )
        injuries = metadata["injuries"]
        print(
            "Injury refresh passed: "
            f"{injuries['matched_skill_players']} matched skill players, "
            f"{injuries['skill_players_flagged']} current designations."
        )
        return
    sleeper_payload = load_json(args.sleeper_file) if args.sleeper_file else fetch_json(SLEEPER_URL)
    ffc_payload = load_json(args.ffc_file) if args.ffc_file else fetch_json(FFC_URL)
    schedule_rows = load_csv(args.schedule_file) if args.schedule_file else fetch_csv(SCHEDULE_URL)
    metadata = refresh(
        ffc_payload,
        sleeper_payload,
        schedule_rows,
        injury_roster_rows,
        injury_report_rows,
        now,
        preseason_injury_rows,
    )
    counts = metadata["counts"]
    quality = metadata["quality"]
    print(
        "Draft market refresh passed: "
        f"{counts['total_players']} players, "
        f"{quality['skill_matches']}/{quality['skill_feed_rows']} skill ADP matches, "
        f"{quality['special_teams_matches']}/{quality['special_teams_feed_rows']} K/DEF matches, "
        f"market through {metadata['market']['period_end']}."
    )


if __name__ == "__main__":
    main()
