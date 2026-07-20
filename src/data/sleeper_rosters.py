"""Fetch current NFL rosters from the Sleeper API and override stale team
assignments in the nflverse-derived roster DataFrame.

nfl_data_py's upstream roster feed lags by days or weeks mid-offseason, so
by the time a trade is reflected there our projections have already been
built on the old team context. Sleeper's API (free, unauthenticated) updates
within hours of transactions.

We match on GSIS ID (the stable identifier nflverse uses as player_id) so
there's no fuzzy name matching. Falls back to name match for players Sleeper
has but hasn't back-linked to a GSIS ID yet (common for rookies in the first
few days after the draft).

Public entrypoint:
    apply_sleeper_team_overrides(roster_df, target_season=2026) -> roster_df

Only patches rows for `target_season` — historical rows are never touched.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import pandas as pd

try:  # urllib is always available; avoid adding a requests dependency
    from urllib.request import Request, urlopen
except Exception:  # pragma: no cover
    Request = urlopen = None  # type: ignore

SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"

logger = logging.getLogger(__name__)

# Franchise-code aliases. nflverse and Sleeper don't always agree on which
# 2- or 3-letter code to use for the same team; these pairs should NOT be
# flagged as a team change.
TEAM_ALIASES = {
    "LAR": {"LA", "LAR", "STL"},
    "LAC": {"LAC", "SD"},
    "LV":  {"LV", "OAK", "LVR"},
    "WAS": {"WAS", "WSH", "WFT"},
    "JAX": {"JAX", "JAC"},
    "BAL": {"BAL", "BLT"},
    "CLE": {"CLE", "CLV"},
    "HOU": {"HOU", "HST"},
    "ARI": {"ARI", "ARZ"},
}


def _canonical_team(team: Optional[str]) -> str:
    if not team:
        return ""
    t = str(team).upper()
    for canon, aliases in TEAM_ALIASES.items():
        if t in aliases:
            return canon
    return t


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", s)
    s = re.sub(r"[^a-z\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_sleeper_players(timeout: int = 30) -> dict:
    """Return Sleeper's full player DB (~11k players). Raises on network error."""
    if Request is None:
        raise RuntimeError("urllib.request not available")
    req = Request(SLEEPER_URL, headers={"User-Agent": "nflmodel/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_override_maps(sleeper: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Return (by_gsis_id, by_normalized_name) team maps for fast lookup."""
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for _pid, p in sleeper.items():
        if not isinstance(p, dict):
            continue
        team = p.get("team")
        if not team:
            continue
        gsis = p.get("gsis_id") or p.get("gsis_player_id")
        if gsis:
            by_id[str(gsis)] = team
        full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
        pos = (p.get("position") or "").upper()
        key = _normalize_name(full)
        if key and pos in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            # Prefer Active players to resolve name collisions with retirees
            if key not in by_name or p.get("status") == "Active":
                by_name[key] = team
    return by_id, by_name


def _build_overlay_maps(sleeper: dict) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """Return (by_gsis_id, by_normalized_name) maps of the full Sleeper record.
    Each value carries at least {team, position, status, full_name}. Used both
    for overriding existing rows and synthesizing missing ones."""
    by_id: dict[str, dict] = {}
    by_name: dict[tuple[str, str], dict] = {}
    for _pid, p in sleeper.items():
        if not isinstance(p, dict):
            continue
        team = p.get("team")
        if not team:
            continue
        pos = (p.get("position") or "").upper()
        if pos not in {"QB", "RB", "WR", "TE"}:  # skip K/DEF/OL/etc for roster use
            continue
        full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
        rec = {
            "team": team,
            "position": pos,
            "status": p.get("status"),
            "full_name": full.strip(),
            "depth_chart_order": p.get("depth_chart_order"),
        }
        # Sleeper retains some retired players as Active with an old team
        # assignment. A current depth-chart slot is the reliable signal that a
        # veteran belongs in the projection universe. True rookies without a
        # slot are added separately by fetch_sleeper_rookies.
        if rec["status"] != "Active" or rec["depth_chart_order"] is None:
            continue
        gsis = p.get("gsis_id") or p.get("gsis_player_id")
        if gsis:
            by_id[str(gsis)] = rec
        key = _normalize_name(full)
        if key:
            by_name[(key, pos)] = rec
    return by_id, by_name


def build_sleeper_depth_chart(
    roster_df: pd.DataFrame,
    target_season: int,
    sleeper: Optional[dict] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Build a depth-chart DataFrame for `target_season` from Sleeper's API.

    Returns the same schema as `fetch_depth_charts`:
      season, team, gsis_id/player_id, player_name, position, depth_rank

    Uses Sleeper's `depth_chart_order` (1=starter, 2=backup, ...). Links to
    nflverse `player_id` via gsis_id when present; falls back to name match
    against `roster_df` (so rookies without a GSIS link still get included).

    Players without a depth_chart_order are skipped (Sleeper marks them as
    None, typically practice-squad / IR / unranked).
    """
    if sleeper is None:
        try:
            sleeper = fetch_sleeper_players()
        except Exception as e:
            if verbose:
                print(f"  Sleeper depth chart skipped — fetch failed: {e}")
            return pd.DataFrame(
                columns=["season", "team", "player_id", "gsis_id", "player_name",
                         "position", "depth_rank"]
            )

    # Build name -> player_id map from the roster for name-based fallback
    name_to_pid: dict[str, str] = {}
    if roster_df is not None and not roster_df.empty:
        latest = (roster_df.sort_values("season")
                            .drop_duplicates("player_id", keep="last"))
        name_col = next(
            (c for c in ("player_name", "full_name", "display_name") if c in latest.columns),
            None,
        )
        if name_col:
            for pid, nm in zip(latest["player_id"].astype(str), latest[name_col]):
                key = _normalize_name(str(nm))
                if key:
                    name_to_pid.setdefault(key, pid)

    rows: list[dict] = []
    missing = 0
    no_order = 0
    matched_gsis = 0
    matched_name = 0

    for _pid, p in sleeper.items():
        if not isinstance(p, dict):
            continue
        team = p.get("team")
        order = p.get("depth_chart_order")
        if not team or order is None:
            no_order += 1
            continue
        pos = (p.get("position") or "").upper()
        if pos not in {"QB", "RB", "WR", "TE"}:
            continue
        full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
        full = full.strip()

        gsis = p.get("gsis_id") or p.get("gsis_player_id")
        pid = None
        if gsis and str(gsis) in {str(k) for k in name_to_pid.values()}:
            # Already a valid nflverse player_id
            pid = str(gsis)
            matched_gsis += 1
        elif gsis:
            pid = str(gsis)   # trust Sleeper's gsis even if we haven't seen it
            matched_gsis += 1
        else:
            key = _normalize_name(full)
            pid = name_to_pid.get(key)
            if pid:
                matched_name += 1
            else:
                missing += 1
                continue

        rows.append({
            "season": target_season,
            "team": team,
            "player_id": pid,
            "gsis_id": pid,
            "player_name": full,
            "position": pos,
            "depth_rank": int(order),
        })

    df = pd.DataFrame(rows)
    if verbose:
        print(f"  Sleeper depth chart ({target_season}): {len(df)} entries "
              f"(gsis: {matched_gsis}, name: {matched_name}, no_order: {no_order}, unmatched: {missing})")

    return df


def apply_sleeper_team_overrides(
    roster_df: pd.DataFrame,
    target_season: int,
    verbose: bool = True,
) -> pd.DataFrame:
    """Ensure `roster_df` has correct team assignments for `target_season`.

    Behavior:
      1. If `target_season` rows already exist: patch their `team` field from
         Sleeper (by GSIS id, then by name). Historical rows are never touched.
      2. If `target_season` rows are missing (common when nflverse hasn't yet
         published the upcoming season), synthesize them from the player's most
         recent historical row with season + team swapped to the current values.
    """
    if roster_df is None or roster_df.empty:
        return roster_df
    if "season" not in roster_df.columns or "team" not in roster_df.columns:
        return roster_df

    try:
        sleeper = fetch_sleeper_players()
    except Exception as e:
        if verbose:
            print(f"  Sleeper override skipped — fetch failed: {e}")
        return roster_df

    by_id, by_name = _build_overlay_maps(sleeper)
    if verbose:
        print(f"  Sleeper: {len(by_id):,} players indexed by gsis_id, "
              f"{len(by_name):,} by name (QB/RB/WR/TE only)")

    df = roster_df.copy()
    existing_mask = df["season"] == target_season
    existing_count = int(existing_mask.sum())

    def resolve(row) -> Optional[dict]:
        pid = row.get("player_id")
        if pid and str(pid) in by_id:
            return by_id[str(pid)]
        for name_col in ("player_name", "full_name", "display_name"):
            nm = row.get(name_col)
            if nm:
                key = _normalize_name(nm)
                name_pos = (key, str(row.get("position") or "").upper())
                if name_pos in by_name:
                    return by_name[name_pos]
        return None

    # ----- Case 1: patch existing rows -----
    trades = 0
    alias_fixes = 0
    if existing_count > 0:
        fantasy_mask = existing_mask & df["position"].isin({"QB", "RB", "WR", "TE"})
        if "status" in df.columns:
            # nflverse's preseason roster file includes stale ACT records. Only
            # rows resolved to Sleeper's current depth chart are reactivated.
            df.loc[fantasy_mask, "status"] = "INA"
        for idx in df.index[existing_mask]:
            row = df.loc[idx]
            hit = resolve(row)
            if not hit:
                continue
            if "status" in df.columns:
                df.at[idx, "status"] = "ACT"
            new_team = hit["team"]
            old_team = row.get("team")
            canon_new = _canonical_team(new_team)
            canon_old = _canonical_team(old_team)
            if canon_new == canon_old:
                if new_team != old_team:
                    df.at[idx, "team"] = new_team
                    alias_fixes += 1
            else:
                df.at[idx, "team"] = new_team
                trades += 1

    # ----- Case 2: synthesize rows if the target season is missing/sparse -----
    synth_rows: list[dict] = []
    existing_ids = set(df.loc[existing_mask, "player_id"].astype(str)) if existing_count else set()

    # Most-recent historical row per player — used as the template for synthesized rows
    latest_by_pid = (df.sort_values("season")
                       .drop_duplicates("player_id", keep="last")
                       .set_index("player_id", drop=False))

    # Name + position -> player_id reverse index so we can link Sleeper players
    # without GSIS without confusing same-name players at other positions.
    name_col_used = next(
        (c for c in ("player_name", "full_name", "display_name") if c in latest_by_pid.columns),
        None,
    )
    name_to_pid: dict[tuple[str, str], str] = {}
    if name_col_used:
        for pid, nm, pos in zip(
            latest_by_pid.index.astype(str),
            latest_by_pid[name_col_used],
            latest_by_pid["position"],
        ):
            key = _normalize_name(str(nm))
            if not key:
                continue
            # Prefer first match (latest row is already deduped per player_id)
            name_to_pid.setdefault((key, str(pos).upper()), pid)

    matched_by = {"gsis": 0, "name": 0, "missing": 0}
    linked_pids: set[str] = set()  # avoid double-synthesizing via gsis + name

    def _emit_synth(pid: str, rec: dict):
        if pid in existing_ids or pid in linked_pids:
            return
        linked_pids.add(pid)
        template = latest_by_pid.loc[pid].to_dict()
        template["season"] = target_season
        template["team"] = rec["team"]
        template["position"] = rec["position"] or template.get("position")
        if "status" in template:
            template["status"] = "ACT"
        synth_rows.append(template)

    # Pass 1: gsis_id match (most reliable)
    for gsis_id, rec in by_id.items():
        if gsis_id in latest_by_pid.index.astype(str):
            _emit_synth(gsis_id, rec)
            matched_by["gsis"] += 1

    # Pass 2: name match for everything else (covers players without GSIS in Sleeper)
    for (key, pos), rec in by_name.items():
        pid = name_to_pid.get((key, pos))
        if pid and pid not in linked_pids:
            _emit_synth(pid, rec)
            matched_by["name"] += 1
        elif not pid:
            matched_by["missing"] += 1

    if synth_rows:
        new_df = pd.DataFrame(synth_rows)
        # Align columns with roster_df so pd.concat doesn't explode
        for col in df.columns:
            if col not in new_df.columns:
                new_df[col] = pd.NA
        new_df = new_df[df.columns]
        df = pd.concat([df, new_df], ignore_index=True)

    if verbose:
        print(f"  Sleeper overlay ({target_season}):")
        print(f"    existing rows patched : {existing_count}")
        print(f"      trades/moves        : {trades}")
        print(f"      alias normalized    : {alias_fixes}")
        print(f"    synthesized new rows  : {len(synth_rows)}")
        print(f"      matched via gsis_id : {matched_by['gsis']}")
        print(f"      matched via name    : {matched_by['name']}")
        print(f"      sleeper w/o nflverse: {matched_by['missing']}")
        total_proj = int((df["season"] == target_season).sum())
        print(f"    total {target_season} roster rows now: {total_proj}")

    return df
