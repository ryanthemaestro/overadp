"""Pull 2026-class rookies from Sleeper when nflverse hasn't published yet.

Why this exists
---------------
nflverse's `import_draft_picks` and `import_seasonal_rosters` typically lag the
NFL Draft by 1-2 weeks. In that window, our pipeline has no way to know a
rookie exists, let alone which team drafted them. Sleeper's free players
endpoint, by contrast, updates within hours of roster transactions.

`apply_sleeper_team_overrides` already synthesizes projection-season rows for
Sleeper players we've seen before (matched via gsis_id or name). Rookies are
the one case it can't handle — they have no historical row to template from.

This module fills that gap by producing **stub projection rows** for rookies
that Sleeper knows about but nflverse doesn't. Lag/rolling features are all
zero (they'd be meaningless anyway: no NFL history). The rookie + college +
combine feature paths then populate the meaningful signals:

  - is_rookie = 1                  (set by compute_rookie_features via rookie_year)
  - college_* and athletic_score    (set by compute_college_features via combine)
  - draft_capital                    (null until nflverse publishes picks;
                                      model is already robust to NaN draft_capital)

Public entrypoint:
    build_rookie_stub_rows(target_season, combine_df=None) -> DataFrame
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, date
from typing import Optional

import pandas as pd

from src.data.sleeper_rosters import fetch_sleeper_players, _normalize_name

logger = logging.getLogger(__name__)

# Positions the model actually projects
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE"}


def _age_from_birth_date(bd_str: Optional[str], as_of: date) -> Optional[float]:
    if not bd_str:
        return None
    try:
        bd = datetime.strptime(bd_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    years = (as_of - bd).days / 365.25
    return round(years, 1)


def _parse_height_inches(ht) -> Optional[float]:
    """Sleeper stores height as '72' (inches) or '6-0'. Combine uses '6-0' strings."""
    if ht is None:
        return None
    s = str(ht).strip()
    if not s:
        return None
    if "-" in s:
        try:
            feet, inches = s.split("-")
            return float(feet) * 12 + float(inches)
        except (ValueError, TypeError):
            return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def fetch_sleeper_rookies(
    target_season: int,
    sleeper: Optional[dict] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Return a DataFrame of likely `target_season` rookies from Sleeper.

    Filters:
      - status == "Active"
      - team assigned (on an NFL roster)
      - position in {QB, RB, WR, TE}
      - years_exp in (None, 0)  → rookie or first pro season

    Columns: player_id (synthetic 'SL-<sleeper_id>'), sleeper_id, gsis_id,
    player_name, first_name, last_name, position, team, college, age,
    height_in, weight_lb, rookie_year (= target_season).
    """
    if sleeper is None:
        try:
            sleeper = fetch_sleeper_players()
        except Exception as e:
            if verbose:
                print(f"  Sleeper rookies skipped — fetch failed: {e}")
            return pd.DataFrame()

    today = date.today()
    rows: list[dict] = []
    for sid, p in sleeper.items():
        if not isinstance(p, dict):
            continue
        if p.get("status") != "Active":
            continue
        team = p.get("team")
        if not team:
            continue
        pos = (p.get("position") or "").upper()
        if pos not in FANTASY_POSITIONS:
            continue
        yrs = p.get("years_exp")
        if yrs not in (None, 0):
            continue

        full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
        full = full.strip()
        if not full:
            continue

        gsis = p.get("gsis_id") or p.get("gsis_player_id") or ""
        rows.append({
            "player_id": f"SL-{sid}",
            "sleeper_id": sid,
            "gsis_id": str(gsis) if gsis else "",
            "player_name": full,
            "first_name": p.get("first_name") or "",
            "last_name": p.get("last_name") or "",
            "football_name": full,
            "position": pos,
            "team": team,
            "college": p.get("college") or "",
            "age": _age_from_birth_date(p.get("birth_date"), today),
            "height_in": _parse_height_inches(p.get("height")),
            "weight_lb": float(p["weight"]) if p.get("weight") else None,
            "rookie_year": target_season,
            "season": target_season,
        })

    df = pd.DataFrame(rows)
    if verbose:
        by_pos = df.groupby("position").size().to_dict() if not df.empty else {}
        print(f"  Sleeper rookies ({target_season}): {len(df)} players "
              f"[{', '.join(f'{k}:{v}' for k,v in sorted(by_pos.items()))}]")
    return df


def build_rookie_stub_rows(
    target_season: int,
    template_row: pd.Series,
    existing_player_ids: set,
    existing_names: set,
    sleeper: Optional[dict] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Build projection-row stubs for Sleeper rookies missing from the pipeline.

    Parameters
    ----------
    target_season : int
        The season we're projecting (e.g. 2026).
    template_row : pd.Series
        One row from the projection DataFrame — used to get the full column
        schema. All numeric columns will be zeroed; string columns emptied.
    existing_player_ids : set[str]
        Player IDs already in proj_rows — avoid duplicating.
    existing_names : set[str]
        Normalized player names already in proj_rows — avoid duplicating
        rookies that nflverse already has (e.g. via a partial ingest).
    sleeper : dict, optional
        Pre-fetched Sleeper players dict; fetched fresh if None.

    Returns
    -------
    pd.DataFrame
        Same columns as `template_row`, one row per new rookie.
    """
    rookies = fetch_sleeper_rookies(target_season, sleeper=sleeper, verbose=verbose)
    if rookies.empty:
        return pd.DataFrame(columns=template_row.index)

    # Filter out rookies we've already captured via nflverse
    keep = []
    for _, r in rookies.iterrows():
        pid = str(r["player_id"])
        gsis = str(r.get("gsis_id") or "")
        name_key = _normalize_name(r["player_name"])
        if gsis and gsis in existing_player_ids:
            continue
        if pid in existing_player_ids:
            continue
        if name_key and name_key in existing_names:
            continue
        keep.append(r)

    if not keep:
        if verbose:
            print(f"  Sleeper rookie stubs: 0 new (all already in proj_rows)")
        return pd.DataFrame(columns=template_row.index)

    rookies = pd.DataFrame(keep)

    # Build stub rows matching the template schema
    schema = template_row.index.tolist()
    stub = pd.DataFrame(index=range(len(rookies)), columns=schema)

    # Zero fill numeric-ish columns, empty string for object
    for col in schema:
        dtype = template_row[col] if template_row is not None else None
        if isinstance(dtype, (int, float)) or pd.api.types.is_number(dtype):
            stub[col] = 0.0
        else:
            stub[col] = ""

    # Populate the identity columns from Sleeper. Set every year-marker the
    # pipeline might use to decide rookie status — compute_rookie_features
    # checks draft_year first, then entry_year, then rookie_year. If any of
    # them is zero (our numeric default), yrs_since_* is huge and is_rookie
    # stays 0. Setting all three to target_season makes the flag robust.
    for col, vals in [
        ("player_id", rookies["player_id"].values),
        ("player_name", rookies["player_name"].values),
        ("first_name", rookies["first_name"].values),
        ("last_name", rookies["last_name"].values),
        ("football_name", rookies["football_name"].values),
        ("position", rookies["position"].values),
        ("team", rookies["team"].values),
        ("season", [target_season] * len(rookies)),
        ("rookie_year", [target_season] * len(rookies)),
        # Copy height/weight from Sleeper directly (better than combine merge)
        ("combine_ht", rookies["height_in"].values if "height_in" in rookies.columns else [0] * len(rookies)),
        ("combine_wt", rookies["weight_lb"].values if "weight_lb" in rookies.columns else [0] * len(rookies)),
        ("draft_year", [target_season] * len(rookies)),
        ("entry_year", [target_season] * len(rookies)),
        ("years_of_experience", [0] * len(rookies)),
        ("age", rookies["age"].fillna(22.0).values),
    ]:
        if col in schema:
            stub[col] = vals

    # college_name: use Sleeper's `college` field if the schema has it
    if "college_name" in schema:
        stub["college_name"] = rookies["college"].values
    if "college" in schema:
        stub["college"] = rookies["college"].values

    if verbose:
        print(f"  Sleeper rookie stubs: {len(stub)} new rows injected into proj_rows")

    return stub
