#!/usr/bin/env python3
"""Fail closed when draft-board data is stale, incomplete, or inconsistent."""

from __future__ import annotations

import argparse
import json
import math
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_DIR = PROJECT_ROOT / "site" / "app" / "data"
MODEL_DATA_DIR = PROJECT_ROOT / "src" / "api" / "static" / "data"
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
EXPECTED_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate(max_age_hours: float) -> list[str]:
    errors: list[str] = []
    filenames = [
        "players.json", "k_def.json", "bye_weeks.json", "scarcity.json",
        "accuracy.json", "sleepers_busts.json", "roster_config.json", "metadata.json",
    ]
    for filename in filenames:
        site_path = SITE_DATA_DIR / filename
        model_path = MODEL_DATA_DIR / filename
        if not site_path.exists() or not model_path.exists():
            errors.append(f"{filename}: missing from one or both data directories")
            continue
        if site_path.read_bytes() != model_path.read_bytes():
            errors.append(f"{filename}: published and model-static copies differ")
    if errors:
        return errors

    players = load(SITE_DATA_DIR / "players.json")
    k_def = load(SITE_DATA_DIR / "k_def.json")
    byes = load(SITE_DATA_DIR / "bye_weeks.json")
    scarcity = load(SITE_DATA_DIR / "scarcity.json")
    accuracy = load(SITE_DATA_DIR / "accuracy.json")
    metadata = load(SITE_DATA_DIR / "metadata.json")

    if not isinstance(players, list) or len(players) < 800:
        errors.append(f"players.json: expected at least 800 rows, got {len(players) if isinstance(players, list) else 'non-list'}")
        return errors
    if not isinstance(k_def, list) or len(k_def) < 50:
        errors.append(f"k_def.json: expected at least 50 rows, got {len(k_def) if isinstance(k_def, list) else 'non-list'}")
        return errors

    injury_rows = [row for row in players if str(row.get("injury_status") or "").strip()]
    injuries_meta = metadata.get("injuries") or {}
    expected_injury_source = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "weekly_rosters/roster_weekly_2026.csv"
    )
    expected_report_source = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "injuries/injuries_2026.csv"
    )
    if injuries_meta.get("source_url") != expected_injury_source:
        errors.append("metadata.json: injury source provenance is missing")
    if injuries_meta.get("injury_report_source_url") != expected_report_source:
        errors.append("metadata.json: weekly injury-report provenance is missing")
    if injuries_meta.get("license") != "CC BY 4.0" or injuries_meta.get("attribution") != "nflverse":
        errors.append("metadata.json: nflverse injury attribution/license is missing")
    if int(injuries_meta.get("matched_skill_players", 0)) < 650:
        errors.append("metadata.json: fewer than 650 skill players matched nflverse availability data")
    status_counts = injuries_meta.get("status_counts")
    try:
        counted_statuses = sum(int(value) for value in status_counts.values())
    except (AttributeError, TypeError, ValueError):
        counted_statuses = -1
    if counted_statuses != len(injury_rows):
        errors.append("metadata.json: injury status counts are inconsistent")
    report_available = injuries_meta.get("injury_report_available")
    report_week = injuries_meta.get("latest_injury_report_week")
    if not isinstance(report_available, bool) or report_available != (report_week is not None):
        errors.append("metadata.json: injury report availability/week is inconsistent")
    expected_reporting_mode = (
        "official_game_status" if report_available else "preseason_availability"
    )
    if injuries_meta.get("reporting_mode") != expected_reporting_mode:
        errors.append("metadata.json: injury reporting mode is inconsistent")
    try:
        preseason_notes_applied = int(injuries_meta.get("preseason_notes_applied", -1))
    except (TypeError, ValueError):
        preseason_notes_applied = -1
    if preseason_notes_applied < 0 or preseason_notes_applied > len(injury_rows):
        errors.append("metadata.json: preseason note count is inconsistent")
    if int(injuries_meta.get("latest_roster_week", 0)) < 1:
        errors.append("metadata.json: nflverse roster week is missing")
    if int(injuries_meta.get("skill_players_flagged", -1)) != len(injury_rows):
        errors.append(
            "metadata.json: injury designation count does not match players.json "
            f"({injuries_meta.get('skill_players_flagged')} != {len(injury_rows)})"
        )
    if int((metadata.get("counts") or {}).get("current_injury_designations", -1)) != len(injury_rows):
        errors.append("metadata.json: counts.current_injury_designations is inconsistent")
    for row in injury_rows:
        name = row.get("player_name", "<unknown>")
        if len(str(row.get("injury_status") or "")) > 32:
            errors.append(f"players.json: {name} has an invalid injury status")
        for field in (
            "injury_body_part", "injury_notes", "injury_start_date",
            "practice_participation", "practice_description", "roster_status",
            "injury_source_url", "injury_source_label",
        ):
            value = row.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > 240):
                errors.append(f"players.json: {name} has invalid {field}")
        news_updated = row.get("injury_news_updated")
        if news_updated is not None:
            errors.append(f"players.json: {name} retains a legacy injury source timestamp")
        try:
            source_updated = datetime.fromisoformat(
                str(row["injury_source_updated_at"]).replace("Z", "+00:00")
            )
            if source_updated.tzinfo is None:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            errors.append(f"players.json: {name} has invalid injury_source_updated_at")
        season_outlook = row.get("season_outlook")
        if season_outlook is not None:
            if season_outlook not in {
                "expected_week_1", "monitor_week_1", "expected_absence", "season_out",
            }:
                errors.append(f"players.json: {name} has invalid season_outlook")
            try:
                expected_games_missed = float(row["expected_games_missed"])
                if not math.isfinite(expected_games_missed) or not 0 <= expected_games_missed <= 17:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors.append(f"players.json: {name} has invalid expected_games_missed")
            expected_return_date = row.get("expected_return_date")
            if expected_return_date:
                try:
                    date.fromisoformat(str(expected_return_date))
                except ValueError:
                    errors.append(f"players.json: {name} has invalid expected_return_date")

    position_counts = Counter(str(row.get("position") or "").upper() for row in players)
    minimums = {"QB": 100, "RB": 175, "WR": 325, "TE": 175}
    for position, minimum in minimums.items():
        if position_counts[position] < minimum:
            errors.append(f"players.json: {position} count {position_counts[position]} is below {minimum}")
    if set(position_counts) != SKILL_POSITIONS:
        errors.append(f"players.json: unexpected positions {sorted(set(position_counts) - SKILL_POSITIONS)}")

    ids = [str(row.get("player_id") or "") for row in players + k_def]
    duplicate_ids = [key for key, count in Counter(ids).items() if not key or count > 1]
    if duplicate_ids:
        errors.append(f"player ids: missing/duplicate values {duplicate_ids[:8]}")
    name_keys = [
        (normalize_name(row.get("player_name")), str(row.get("position") or "").upper())
        for row in players
    ]
    duplicate_names = [key for key, count in Counter(name_keys).items() if not key[0] or count > 1]
    if duplicate_names:
        errors.append(f"players.json: missing/duplicate normalized name-position keys {duplicate_names[:8]}")

    required = {"player_id", "player_name", "position", "team", "projected_points", "adp", "bye"}
    malformed = []
    for row in players:
        if not required.issubset(row):
            malformed.append(row.get("player_name", "<unknown>"))
            continue
        if not finite_number(row.get("projected_points")) or not finite_number(row.get("adp")):
            malformed.append(row.get("player_name", "<unknown>"))
    if malformed:
        errors.append(f"players.json: malformed required fields for {malformed[:8]}")

    board_teams = {str(row.get("team") or "").upper() for row in players}
    if board_teams != EXPECTED_TEAMS:
        errors.append(
            "players.json: team coverage differs from 32 teams; "
            f"missing={sorted(EXPECTED_TEAMS - board_teams)}, extra={sorted(board_teams - EXPECTED_TEAMS)}"
        )
    missing_byes = sorted(team for team in EXPECTED_TEAMS if not byes.get(team))
    if missing_byes:
        errors.append(f"bye_weeks.json: missing board teams {missing_byes}")

    actionable_skill = [row for row in players if 0 < float(row.get("adp", 200)) < 200]
    actionable_special = [row for row in k_def if 0 < float(row.get("adp", 200)) < 200]
    if len(actionable_skill) < 150:
        errors.append(f"players.json: only {len(actionable_skill)} players have current actionable ADP")
    if len(actionable_special) < 25:
        errors.append(f"k_def.json: only {len(actionable_special)} K/DEF rows have current actionable ADP")

    for position in ("K", "DEF"):
        rows = [
            row for row in k_def
            if str(row.get("position") or "").upper() == position
        ]
        teams = {str(row.get("team") or "").upper() for row in rows}
        if len(rows) != 32 or teams != EXPECTED_TEAMS:
            errors.append(
                f"k_def.json: {position} must contain one current row per team; "
                f"rows={len(rows)}, missing={sorted(EXPECTED_TEAMS - teams)}, "
                f"extra={sorted(teams - EXPECTED_TEAMS)}"
            )
        ranks = sorted(
            int(row.get("stream_rank", 0))
            for row in rows
            if finite_number(row.get("stream_rank"))
        )
        if ranks != list(range(1, 33)):
            errors.append(f"k_def.json: {position} streaming ranks are not 1-32")
        for row in rows:
            name = row.get("player_name", "<unknown>")
            schedule = row.get("opening_schedule")
            required_streaming = {
                "opening_projection", "week1_projection", "stream_score",
                "stream_rank", "stream_tier", "draft_guidance", "stream_model_used",
            }
            if not required_streaming.issubset(row):
                errors.append(f"k_def.json: {name} lacks opening-schedule fields")
                continue
            if (
                not finite_number(row.get("opening_projection"))
                or not finite_number(row.get("week1_projection"))
                or not finite_number(row.get("stream_score"))
            ):
                errors.append(f"k_def.json: {name} has invalid streaming values")
            if not isinstance(schedule, list) or len(schedule) != 3:
                errors.append(f"k_def.json: {name} opening schedule is not three games")
                continue
            weeks = [int(game.get("week", 0)) for game in schedule]
            if weeks != [1, 2, 3]:
                errors.append(f"k_def.json: {name} opening weeks are {weeks}")
            for game in schedule:
                opponent = str(game.get("opponent") or "").upper()
                if opponent not in EXPECTED_TEAMS or opponent == str(row.get("team") or "").upper():
                    errors.append(f"k_def.json: {name} has invalid opponent {opponent!r}")
                if game.get("matchup_grade") not in {"A", "B", "C", "D"}:
                    errors.append(f"k_def.json: {name} has invalid matchup grade")
        if position == "K":
            low_role_confidence = [
                row.get("player_name")
                for row in rows
                if row.get("role_confidence") != "HIGH"
                or int(row.get("depth_chart_order", 0)) != 1
            ]
            if low_role_confidence:
                errors.append(
                    "k_def.json: kicker starters are not depth-chart confirmed "
                    f"{low_role_confidence[:8]}"
                )

    if not isinstance(scarcity, list) or {row.get("position") for row in scarcity} != SKILL_POSITIONS:
        errors.append("scarcity.json: must contain exactly QB/RB/WR/TE")
    if not isinstance(accuracy, dict) or set(accuracy) != SKILL_POSITIONS:
        errors.append("accuracy.json: must contain exactly QB/RB/WR/TE")
    for position, row in accuracy.items():
        if not row.get("test_seasons") or int(row.get("n_players", 0)) < 50:
            errors.append(f"accuracy.json: {position} lacks adequate walk-forward evidence")

    if metadata.get("schema_version") != 1 or metadata.get("projection_season") != 2026:
        errors.append("metadata.json: unsupported schema or projection season")
    if (metadata.get("quality") or {}).get("status") != "passed":
        errors.append("metadata.json: refresh quality status is not passed")
    try:
        fetched_at = datetime.fromisoformat(metadata["market"]["fetched_at"].replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours < -1 or age_hours > max_age_hours:
            errors.append(f"metadata.json: market data age is {age_hours:.1f}h (limit {max_age_hours:.1f}h)")
    except (KeyError, TypeError, ValueError):
        errors.append("metadata.json: market fetched_at is missing or invalid")
    try:
        injury_fetched_at = datetime.fromisoformat(
            injuries_meta["fetched_at"].replace("Z", "+00:00")
        )
        injury_age_hours = (
            datetime.now(timezone.utc) - injury_fetched_at
        ).total_seconds() / 3600
        if injury_age_hours < -1 or injury_age_hours > max_age_hours:
            errors.append(
                "metadata.json: availability data age is "
                f"{injury_age_hours:.1f}h (limit {max_age_hours:.1f}h)"
            )
    except (KeyError, TypeError, ValueError):
        errors.append("metadata.json: availability fetched_at is missing or invalid")
    try:
        source_end = datetime.fromisoformat(metadata["market"]["period_end"] + "T23:59:59+00:00")
        source_age_hours = (datetime.now(timezone.utc) - source_end).total_seconds() / 3600
        if source_age_hours > max_age_hours:
            errors.append(
                f"metadata.json: upstream market period is {source_age_hours:.1f}h old "
                f"(limit {max_age_hours:.1f}h)"
            )
    except (KeyError, TypeError, ValueError):
        errors.append("metadata.json: market period_end is missing or invalid")

    quality = metadata.get("quality") or {}
    if float(quality.get("skill_match_rate", 0)) < 0.98:
        errors.append(f"metadata.json: skill ADP match rate is {quality.get('skill_match_rate')}")
    if int(quality.get("top_24_skill_matches", 0)) != 24:
        errors.append("metadata.json: not all top-24 market players matched the board")
    if int(quality.get("special_teams_matches", 0)) < 25:
        errors.append("metadata.json: fewer than 25 K/DEF market rows matched")
    if int(quality.get("opening_schedule_games", 0)) != 48:
        errors.append("metadata.json: opening schedule does not contain 48 games")
    if int(quality.get("kicker_depth_chart_teams", 0)) != 32:
        errors.append("metadata.json: kicker depth-chart coverage is not 32 teams")
    if int(quality.get("defense_schedule_teams", 0)) != 32:
        errors.append("metadata.json: defense schedule coverage is not 32 teams")
    special_teams = metadata.get("special_teams") or {}
    if special_teams.get("weeks") != [1, 2, 3]:
        errors.append("metadata.json: K/DEF opening weeks are not 1-3")
    if special_teams.get("schedule_source") != "nflverse games and schedules":
        errors.append("metadata.json: K/DEF schedule provenance is missing")
    if int((metadata.get("rosters") or {}).get("matched_skill_players", 0)) < 650:
        errors.append("metadata.json: fewer than 650 skill players matched the live Sleeper roster")
    active_coverage = quality.get("active_player_coverage") or {}
    expected_active = int(active_coverage.get("expected_active_depth_players", 0))
    matched_active = int(active_coverage.get("matched_active_depth_players", 0))
    missing_active = active_coverage.get("missing_active_depth_players")
    if expected_active < 650 or matched_active != expected_active or missing_active != []:
        errors.append(
            "metadata.json: active depth-chart projection coverage failed "
            f"({matched_active}/{expected_active}, missing={missing_active})"
        )
    model_coverage = (metadata.get("model") or {}).get("coverage") or {}
    if (
        int(model_coverage.get("matched_active_depth_players", 0))
        != int(model_coverage.get("expected_active_depth_players", -1))
        or model_coverage.get("missing_active_depth_players") != []
    ):
        errors.append("metadata.json: model export coverage evidence is missing or failed")

    board_lookup = {
        (normalize_name(row.get("player_name")), str(row.get("position") or "").upper()): row
        for row in players
    }
    base_candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in players:
        key = (normalize_base_name(row.get("player_name")), str(row.get("position") or "").upper())
        base_candidates.setdefault(key, []).append(row)
    unique_base_lookup = {
        key: rows[0] for key, rows in base_candidates.items() if len(rows) == 1
    }
    for market_player in (metadata.get("market") or {}).get("top_skill_players", []):
        key = (normalize_name(market_player.get("name")), str(market_player.get("position") or "").upper())
        board_player = board_lookup.get(key)
        if not board_player:
            base_key = (
                normalize_base_name(market_player.get("name")),
                str(market_player.get("position") or "").upper(),
            )
            board_player = unique_base_lookup.get(base_key)
        if not board_player or float(board_player.get("adp", 200)) >= 200:
            errors.append(f"top market player missing/actionless: {market_player.get('name')} {market_player.get('position')}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-hours", type=float, default=72)
    args = parser.parse_args()
    errors = validate(args.max_age_hours)
    if errors:
        print("Draft data validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    metadata = load(SITE_DATA_DIR / "metadata.json")
    counts = metadata["counts"]
    print(
        "Draft data validation passed: "
        f"{counts['skill_players']} skill + {counts['k_def_players']} K/DEF, "
        f"market through {metadata['market']['period_end']}, "
        f"{metadata['quality']['skill_match_rate']:.1%} skill join coverage."
    )


if __name__ == "__main__":
    main()
