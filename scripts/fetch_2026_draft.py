"""Refresh the draft_picks cache to include the 2026 rookie class.

Why this exists
---------------
nflverse (and nfl_data_py) typically lags the NFL Draft by 1-2 weeks while
PFR's database ingests gsis_ids.  In that window the local draft_picks.parquet
cache has no 2026 rows, so fetch_draft_picks() warns and skips 2026 — meaning
every 2026 rookie gets draft_capital = 0 in the feature matrix.

As of ~April 28, 2026 nflverse already has the full 2026 pick table with
gsis_ids for most players.  This script:

  1. Pulls 2026 picks from nfl_data_py (primary).
  2. Falls back to ESPN's unofficial draft API if nflverse returns nothing.
  3. Appends the new rows to data/draft_picks.parquet (cache update).
  4. Prints a summary so you can see which skill-position players landed.

Usage
-----
    # One-shot refresh (safe to re-run; skips if 2026 already in cache)
    python scripts/fetch_2026_draft.py

    # Force overwrite even if 2026 is already in cache
    python scripts/fetch_2026_draft.py --force

    # After nflverse re-publishes with updated gsis_ids / college stats
    python scripts/fetch_2026_draft.py --force

After running this script, the full pipeline is:
    python -m src.api.export_static --seasons 5 --scoring half_ppr
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CACHE_PATH = DATA_DIR / "draft_picks.parquet"
DRAFT_YEAR = 2026
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}

# ESPN unofficial draft API — one endpoint per round
ESPN_ROUND_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/draft"
    "/{year}/rounds/{round_num}"
)

ESPN_TO_NFL_TEAM: dict[str, str] = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BUF": "BUF",
    "CAR": "CAR", "CHI": "CHI", "CIN": "CIN", "CLE": "CLE",
    "DAL": "DAL", "DEN": "DEN", "DET": "DET", "GB":  "GB",
    "HOU": "HOU", "IND": "IND", "JAX": "JAX", "JAC": "JAX",
    "KC":  "KC",  "LAC": "LAC", "LAR": "LA",  "LV":  "LV",
    "LVR": "LV",  "MIA": "MIA", "MIN": "MIN", "NE":  "NE",
    "NWE": "NE",  "NO":  "NO",  "NOR": "NO",  "NYG": "NYG",
    "NYJ": "NYJ", "PHI": "PHI", "PIT": "PIT", "SEA": "SEA",
    "SF":  "SF",  "TB":  "TB",  "TEN": "TEN", "WSH": "WSH",
    "KAN": "KC",
}


# ---------------------------------------------------------------------------
# Source 1: nfl_data_py (nflverse)
# ---------------------------------------------------------------------------

def fetch_nflverse(year: int) -> pd.DataFrame:
    """Pull draft picks from nfl_data_py.import_draft_picks."""
    try:
        import nfl_data_py as nfl
    except ImportError:
        print("  nfl_data_py not installed — skipping nflverse source")
        return pd.DataFrame()

    try:
        df = nfl.import_draft_picks(years=[year])
    except Exception as exc:
        print(f"  nflverse import_draft_picks failed: {exc}")
        return pd.DataFrame()

    if df.empty:
        print("  nflverse returned 0 rows for 2026")
        return pd.DataFrame()

    # Normalize gsis_id: nflverse returns "None" string for some
    if "gsis_id" in df.columns:
        df["gsis_id"] = df["gsis_id"].replace("None", None)

    print(f"  nflverse: {len(df)} picks, {df['gsis_id'].notna().sum()} with gsis_id")
    return df


# ---------------------------------------------------------------------------
# Source 2: ESPN unofficial API (fallback)
# ---------------------------------------------------------------------------

def fetch_espn(year: int) -> pd.DataFrame:
    """Pull draft picks from ESPN's unofficial round-by-round API."""
    try:
        import requests
    except ImportError:
        print("  requests not installed — skipping ESPN source")
        return pd.DataFrame()

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    rows: list[dict] = []

    for rnd in range(1, 8):
        url = ESPN_ROUND_URL.format(year=year, round_num=rnd)
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"  ESPN round {rnd}: FAILED ({exc})")
            continue

        picks = data.get("picks") or data.get("round", {}).get("picks", [])
        if not picks:
            continue

        for p in picks:
            athlete = p.get("athlete") or {}
            team_info = p.get("team") or {}
            pos_info = athlete.get("position") or {}
            college_info = (athlete.get("college") or {})

            raw_team = (team_info.get("abbreviation") or "").upper()
            team = ESPN_TO_NFL_TEAM.get(raw_team, raw_team)
            full_name = (
                athlete.get("displayName")
                or f"{athlete.get('firstName','')} {athlete.get('lastName','')}".strip()
            )
            position = (pos_info.get("abbreviation") or pos_info.get("name") or "").upper()
            rows.append({
                "season": year,
                "round": rnd,
                "pick": p.get("overallPickNumber") or p.get("pickNumber"),
                "team": team,
                "gsis_id": None,
                "pfr_player_name": full_name,
                "position": position,
                "college": (college_info.get("name") or ""),
                "age": float(athlete["age"]) if athlete.get("age") else None,
            })
        print(f"  ESPN round {rnd}: {len(picks)} picks")
        time.sleep(0.3)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    print(f"  ESPN: {len(df)} picks total")
    return df


# ---------------------------------------------------------------------------
# Cache update
# ---------------------------------------------------------------------------

def load_existing_cache() -> pd.DataFrame:
    if CACHE_PATH.exists():
        return pd.read_parquet(CACHE_PATH)
    return pd.DataFrame()


def append_to_cache(new_rows: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    """Append new_rows to the parquet cache, deduplicating on (season, pick)."""
    existing = load_existing_cache()

    if existing.empty:
        combined = new_rows
    else:
        if not force:
            already = set(existing["season"].unique()) if "season" in existing.columns else set()
            if DRAFT_YEAR in already:
                print(f"  {DRAFT_YEAR} already in cache ({len(existing[existing['season']==DRAFT_YEAR])} rows). Use --force to overwrite.")
                return existing

        # Drop stale 2026 rows if force-overwriting
        if "season" in existing.columns:
            existing = existing[existing["season"] != DRAFT_YEAR]

        # Align columns (add missing cols as NaN, drop extras)
        for col in existing.columns:
            if col not in new_rows.columns:
                new_rows[col] = None
        new_rows = new_rows[[c for c in existing.columns if c in new_rows.columns]]
        combined = pd.concat([existing, new_rows], ignore_index=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(CACHE_PATH, index=False)
    print(f"  Cache updated → {CACHE_PATH} ({len(combined)} total rows, seasons: {sorted(combined['season'].unique())})")
    return combined


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_skill_summary(df: pd.DataFrame, year: int) -> None:
    picks = df[df["season"] == year] if "season" in df.columns else df
    skill = picks[picks["position"].isin(SKILL_POSITIONS)]
    name_col = "pfr_player_name" if "pfr_player_name" in skill.columns else (
        "player_name" if "player_name" in skill.columns else skill.columns[0]
    )
    print(f"\n2026 skill-position picks ({len(skill)} total):")
    for pos in ["QB", "RB", "WR", "TE"]:
        pos_df = skill[skill["position"] == pos].sort_values("pick")
        if pos_df.empty:
            continue
        cap_vals = []
        for _, r in pos_df.iterrows():
            rnd = int(r.get("round", 0) or 0)
            pk = int(r.get("pick", 0) or 0)
            cap = round(8 - rnd + (1 - pk / 260), 2) if rnd > 0 else 0.0
            cap_vals.append(f"  #{pk:>3d} {r[name_col]:<22s} ({r.get('team','?'):>3s})  draft_capital={cap:.2f}")
        print(f"\n  {pos} ({len(pos_df)}):")
        for v in cap_vals[:10]:
            print(v)
        if len(cap_vals) > 10:
            print(f"    ... and {len(cap_vals)-10} more")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh 2026 draft picks cache")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite 2026 rows even if already cached")
    parser.add_argument("--year", type=int, default=DRAFT_YEAR)
    args = parser.parse_args()

    # Quick exit if already cached and not forcing
    if not args.force:
        existing = load_existing_cache()
        if not existing.empty and "season" in existing.columns:
            if args.year in set(existing["season"].unique()):
                n = len(existing[existing["season"] == args.year])
                print(f"{args.year} already in draft_picks cache ({n} rows).")
                print("Use --force to re-fetch and overwrite.")
                print_skill_summary(existing, args.year)
                return

    print(f"Fetching {args.year} NFL Draft picks …\n")

    # Try nflverse first
    df = fetch_nflverse(args.year)

    # Fall back to ESPN
    if df.empty:
        print("\n  nflverse empty — trying ESPN …")
        df = fetch_espn(args.year)

    if df.empty:
        print("\nERROR: Could not fetch 2026 draft picks from any source.")
        print("Try again in a few minutes, or check network access.")
        sys.exit(1)

    print(f"\nFetched {len(df)} picks for {args.year}")
    combined = append_to_cache(df, force=args.force)
    print_skill_summary(combined, args.year)

    print(f"""
Done. Next step — regenerate projections and push to the site:

    python -m src.api.export_static --seasons 5 --scoring half_ppr
""")


if __name__ == "__main__":
    main()
