#!/usr/bin/env python3
"""Refresh team assignments in players_compact.json from the Sleeper API.

Sleeper's player database is free, unauthenticated, and updates within hours
of NFL trades and signings. nfl_data_py's upstream rosters lag by days/weeks
mid-offseason, so this fills the gap.

Usage:
    python refresh_teams.py               # update players_compact.json in place
    python refresh_teams.py --dry-run     # show changes without writing

The script also sets a "team_updated" flag on any player whose team changed,
so the LLM prompt can know the projection is built on a stale team assumption.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

import urllib.request

SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
COMPACT = Path(__file__).resolve().parent / "players_compact.json"
SITE_PLAYERS = Path(__file__).resolve().parent.parent.parent / "site" / "app" / "data" / "players.json"

# Different data sources use different codes for the same franchise.
# Canonical -> all known aliases.
TEAM_ALIASES = {
    "LAR": ["LA", "LAR", "STL"],
    "LAC": ["LAC", "SD"],
    "LV":  ["LV", "OAK", "LVR"],
    "WAS": ["WAS", "WSH", "WFT"],
    "JAX": ["JAX", "JAC"],
    "TEN": ["TEN", "OTI"],
    "BAL": ["BAL", "BLT"],
    "CLE": ["CLE", "CLV"],
    "HOU": ["HOU", "HST"],
    "ARI": ["ARI", "ARZ"],
}


def canonical_team(team: str) -> str:
    """Collapse aliases to one canonical code per franchise."""
    if not team:
        return ""
    t = team.upper()
    for canon, aliases in TEAM_ALIASES.items():
        if t in aliases:
            return canon
    return t


def normalize_name(name: str) -> str:
    """Strip suffixes, special chars, lowercase for robust matching."""
    if not name:
        return ""
    s = name.lower().strip()
    # Remove Jr / Sr / II / III / IV
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", s)
    # Remove punctuation and extra whitespace
    s = re.sub(r"[^a-z\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_sleeper() -> dict:
    print(f"Fetching Sleeper player DB from {SLEEPER_URL} ...")
    req = urllib.request.Request(SLEEPER_URL, headers={"User-Agent": "OverADP/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(f"  Got {len(data):,} players from Sleeper")
    return data


def build_sleeper_index(sleeper: dict) -> dict[str, list[dict]]:
    """Index Sleeper players by normalized full_name.

    Names are not unique in Sleeper (for example an RB and DB can share a full
    name), so each key stores every candidate and the update step filters by
    fantasy position before changing a team.
    """
    index: dict[str, list[dict]] = {}
    for _pid, p in sleeper.items():
        if not isinstance(p, dict):
            continue
        if p.get("status") not in (None, "Active"):
            # Still include but lower priority — some "Inactive" are just suspended
            pass
        full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
        key = normalize_name(full)
        if not key:
            continue
        entry = {
            "team": p.get("team"),
            "position": p.get("position"),
            "fantasy_positions": p.get("fantasy_positions") or [],
            "status": p.get("status"),
        }
        index.setdefault(key, []).append(entry)
    return index


def _pick_sleeper_match(entries: list[dict], position: str) -> dict | None:
    """Return the best Sleeper candidate for a player name and position."""
    if not entries:
        return None
    pos = (position or "").upper()
    if pos:
        compatible = [
            e for e in entries
            if (e.get("position") or "").upper() == pos
            or pos in [str(p).upper() for p in e.get("fantasy_positions", [])]
        ]
        if compatible:
            entries = compatible
        elif len(entries) > 1:
            return None
    elif len(entries) > 1:
        return None

    active = [e for e in entries if e.get("status") == "Active"]
    return (active or entries)[0]


def update_file(path: Path, idx: dict, name_key: str, dry_run: bool, label: str,
                flag_key: str = "team_updated", compact: bool = False,
                pos_key: str = "position") -> int:
    """Apply Sleeper team updates to a JSON file of player dicts.

    name_key: field holding the player's full name (e.g. "name" or "player_name")
    flag_key: field to set True when team was changed (None to skip flagging)
    compact:  if True, write as compact JSON (no spaces)
    """
    if not path.exists():
        print(f"  [{label}] SKIP — file not found: {path}")
        return 0

    players = json.loads(path.read_text())
    if not isinstance(players, list):
        print(f"  [{label}] SKIP — not a list")
        return 0

    updated = 0
    missing = 0
    changes: list[str] = []

    for p in players:
        nm = p.get(name_key, "")
        key = normalize_name(nm)
        hit = _pick_sleeper_match(idx.get(key, []), p.get(pos_key, ""))
        if not hit or not hit.get("team"):
            missing += 1
            continue
        new_team = canonical_team(hit["team"])
        old_team = canonical_team(p.get("team", ""))
        if new_team and new_team != old_team:
            changes.append(f"    {nm:<25} {old_team or '?'} -> {new_team}")
            p["team"] = new_team
            if flag_key:
                p[flag_key] = True
            updated += 1
        elif new_team and new_team != (p.get("team") or ""):
            # Alias normalization only (LA -> LAR etc.) — don't flag as a trade
            p["team"] = new_team

    print(f"\n[{label}] matched {len(players) - missing}/{len(players)}, team changes: {updated}")
    if changes and len(changes) <= 80:
        for c in changes:
            print(c)

    if dry_run:
        print(f"  (dry run — not written)")
        return updated

    if updated or any(True for _ in []):
        if compact:
            path.write_text(json.dumps(players, separators=(",", ":")))
        else:
            path.write_text(json.dumps(players, indent=2))
        print(f"  wrote {path} ({path.stat().st_size // 1024} KB)")
    return updated


def refresh(dry_run: bool = False) -> int:
    sleeper = fetch_sleeper()
    idx = build_sleeper_index(sleeper)

    total = 0
    # Extension compact file
    total += update_file(
        COMPACT, idx, name_key="name", dry_run=dry_run,
        label="reply-helper compact", flag_key="team_updated", compact=True,
        pos_key="pos",
    )
    # Site draft board
    total += update_file(
        SITE_PLAYERS, idx, name_key="player_name", dry_run=dry_run,
        label="site players.json", flag_key="team_updated", compact=False,
        pos_key="position",
    )

    print(f"\nTotal team changes across all files: {total}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = ap.parse_args()
    sys.exit(refresh(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
