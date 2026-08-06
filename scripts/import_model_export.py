#!/usr/bin/env python3
"""Validate and stage a fresh nflmodel export for the production app."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import unicodedata
from collections import Counter
from datetime import datetime, timezone
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
COPIED_FILES = (
    "players.json",
    "accuracy.json",
    "scarcity.json",
    "roster_config.json",
)


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    for token in ("'", ".", "-", "’"):
        text = text.replace(token, "")
    return " ".join(text.split())


def finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate_export(source: Path, max_age_hours: float = 6) -> tuple[list[dict], dict]:
    missing_files = [
        filename
        for filename in (*COPIED_FILES, "projection_metadata.json")
        if not (source / filename).is_file()
    ]
    if missing_files:
        raise ValueError(f"Model export is missing files: {missing_files}")

    players = load(source / "players.json")
    projection_metadata = load(source / "projection_metadata.json")
    if not isinstance(players, list) or len(players) < 800:
        raise ValueError(
            f"Model export has {len(players) if isinstance(players, list) else 'non-list'} players"
        )
    if (
        projection_metadata.get("schema_version") != 1
        or projection_metadata.get("projection_season") != 2026
        or projection_metadata.get("scoring") != "half_ppr"
    ):
        raise ValueError("Model export metadata has the wrong schema, season, or scoring")
    try:
        generated_at = datetime.fromisoformat(
            str(projection_metadata["generated_at"]).replace("Z", "+00:00")
        )
        age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Model export generated_at is missing or invalid") from exc
    if age_hours < -1 or age_hours > max_age_hours:
        raise ValueError(
            f"Model export is {age_hours:.1f}h old (limit {max_age_hours:.1f}h)"
        )

    positions = Counter(str(row.get("position") or "").upper() for row in players)
    minimums = {"QB": 100, "RB": 175, "WR": 325, "TE": 175}
    if set(positions) != SKILL_POSITIONS:
        raise ValueError(f"Model export positions are {sorted(positions)}")
    below = {
        position: positions[position]
        for position, minimum in minimums.items()
        if positions[position] < minimum
    }
    if below:
        raise ValueError(f"Model export position coverage is too small: {below}")

    player_ids = [str(row.get("player_id") or "").strip() for row in players]
    duplicate_ids = [key for key, count in Counter(player_ids).items() if not key or count > 1]
    if duplicate_ids:
        raise ValueError(f"Model export has missing/duplicate player IDs: {duplicate_ids[:8]}")
    name_keys = [
        (normalize_name(row.get("player_name")), str(row.get("position") or "").upper())
        for row in players
    ]
    duplicate_names = [key for key, count in Counter(name_keys).items() if not key[0] or count > 1]
    if duplicate_names:
        raise ValueError(f"Model export has duplicate player names: {duplicate_names[:8]}")

    malformed = [
        row.get("player_name", "<unknown>")
        for row in players
        if not finite_number(row.get("projected_points"))
        or not finite_number(row.get("ci_low"))
        or not finite_number(row.get("ci_high"))
        or float(row.get("ci_low", 0)) > float(row.get("ci_high", 0))
    ]
    if malformed:
        raise ValueError(f"Model export has malformed projections: {malformed[:8]}")
    teams = {str(row.get("team") or "").upper() for row in players}
    if teams != EXPECTED_TEAMS:
        raise ValueError(
            "Model export team coverage differs from 32 teams; "
            f"missing={sorted(EXPECTED_TEAMS - teams)}, extra={sorted(teams - EXPECTED_TEAMS)}"
        )

    coverage = projection_metadata.get("coverage") or {}
    expected = int(coverage.get("expected_active_depth_players", 0))
    matched = int(coverage.get("matched_active_depth_players", 0))
    missing = coverage.get("missing_active_depth_players")
    if expected < 650 or matched != expected or missing != []:
        raise ValueError(f"Model export active-player coverage failed: {coverage!r}")
    if int(projection_metadata.get("skill_players", 0)) != len(players):
        raise ValueError("Model export player count differs from projection metadata")
    return players, projection_metadata


def import_export(source: Path, max_age_hours: float = 6) -> dict:
    players, projection_metadata = validate_export(source, max_age_hours=max_age_hours)
    for filename in COPIED_FILES:
        for destination in (SITE_DATA_DIR, MODEL_DATA_DIR):
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / filename, destination / filename)

    metadata_path = SITE_DATA_DIR / "metadata.json"
    metadata = load(metadata_path) if metadata_path.exists() else {}
    metadata["model"] = {
        "generated_at": projection_metadata["generated_at"],
        "scoring": "half_ppr",
        "method": "validated CatBoost projections with split-conformal 80% target ranges",
        "projection_mode": projection_metadata.get("projection_mode", "catboost"),
        "skill_players": len(players),
        "coverage": projection_metadata["coverage"],
    }
    for destination in (SITE_DATA_DIR, MODEL_DATA_DIR):
        dump(destination / "metadata.json", metadata)
    return projection_metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=6)
    args = parser.parse_args()
    metadata = import_export(args.source, max_age_hours=args.max_age_hours)
    coverage = metadata["coverage"]
    print(
        "Fresh model export staged: "
        f"{metadata['skill_players']} skill players, "
        f"{coverage['matched_active_depth_players']}/"
        f"{coverage['expected_active_depth_players']} active depth-chart players."
    )


if __name__ == "__main__":
    main()
