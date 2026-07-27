#!/usr/bin/env python3
"""Refresh draft-market fields without retraining the projection model.

The expensive model export is intentionally separate from this daily job.
This script updates volatile draft-day inputs (ADP, teams, and bye weeks),
rebuilds sleeper/bust labels, records source provenance, and keeps both
published data directories byte-for-byte identical.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_DIR = PROJECT_ROOT / "site" / "app" / "data"
MODEL_DATA_DIR = PROJECT_ROOT / "src" / "api" / "static" / "data"
FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/half-ppr?teams=12&year=2026"
SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
MODEL_BASELINE_GENERATED_AT = "2026-07-20T14:49:24Z"
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
NAME_ALIASES = {
    ("kenny gainwell", "RB"): ("kenneth gainwell", "RB"),
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


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def refresh(
    ffc_payload: Any,
    sleeper_payload: Any,
    now: datetime,
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

    sleepers_busts = rebuild_sleepers_busts(players)
    generated_at = now.isoformat().replace("+00:00", "Z")
    prior_model = previous_metadata.get("model") or {}
    metadata = {
        "schema_version": 1,
        "projection_season": 2026,
        "model": {
            "generated_at": prior_model.get("generated_at", MODEL_BASELINE_GENERATED_AT),
            "scoring": "half_ppr",
            "method": "validated CatBoost projections with split-conformal 80% target ranges",
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
        "counts": {
            "skill_players": len(players),
            "k_def_players": len(k_def),
            "total_players": len(players) + len(k_def),
            "actionable_skill_adp": sum(1 for row in players if 0 < positive_number(row.get("adp")) < 200),
            "actionable_k_def_adp": sum(1 for row in k_def if 0 < positive_number(row.get("adp")) < 200),
            "sleepers_busts": len(sleepers_busts),
        },
        "quality": {
            "status": "passed",
            "skill_feed_rows": skill_feed_rows,
            "skill_matches": skill_matches,
            "skill_match_rate": round(skill_match_rate, 4),
            "top_24_skill_matches": top_skill_matches,
            "special_teams_feed_rows": len(special_rows),
            "special_teams_matches": special_matches,
            "bye_team_codes": len(bye_weeks),
            "missing_skill_rows": missing_skill,
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
    args = parser.parse_args()

    now = utc_now()
    ffc_payload = load_json(args.ffc_file) if args.ffc_file else fetch_json(FFC_URL)
    sleeper_payload = load_json(args.sleeper_file) if args.sleeper_file else fetch_json(SLEEPER_URL)
    metadata = refresh(ffc_payload, sleeper_payload, now)
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
