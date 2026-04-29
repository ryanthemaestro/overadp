"""Force-refresh depth chart cache with the latest snapshot from nflverse.

Run this after major roster events:
  - Post-NFL-draft (late April)
  - After training camp starts (late July)
  - After final roster cuts (early September)
  - After significant trades during the season

The nflverse current-season CSV updates daily, so re-running this pulls the
most recent snapshot. `fetch_depth_charts` picks the snapshot closest to
Sep 5 (Week 1) for each season, so for the current projection season,
force_refresh=True re-downloads and re-caches the latest snapshots.

Usage:
    python scripts/refresh_depth_charts.py                   # refresh current season only
    python scripts/refresh_depth_charts.py --seasons 2025 2026  # multiple seasons
    python scripts/refresh_depth_charts.py --all             # refresh 2019-current
"""
import argparse
import sys
from pathlib import Path

# Allow running as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.fetch import fetch_depth_charts


def main():
    parser = argparse.ArgumentParser(description="Refresh nflverse depth chart cache")
    parser.add_argument("--seasons", nargs="+", type=int, help="Seasons to refresh")
    parser.add_argument("--all", action="store_true", help="Refresh all seasons 2019-present")
    parser.add_argument("--current", type=int, default=2026, help="Current projection season (default 2026)")
    args = parser.parse_args()

    if args.all:
        seasons = list(range(2019, args.current + 1))
    elif args.seasons:
        seasons = args.seasons
    else:
        seasons = [args.current]

    print(f"Refreshing depth charts for seasons: {seasons}")
    # Delete cache and re-fetch (force_refresh skips cache read)
    dc = fetch_depth_charts(seasons, cache=True, force_refresh=True)

    print(f"\nFetched {len(dc)} rows.")
    if not dc.empty:
        print("\nPer-season coverage (QB/RB/WR/TE):")
        for s in sorted(dc["season"].unique()):
            sub = dc[(dc["season"] == s) & (dc["position"].isin(["QB", "RB", "WR", "TE"]))]
            print(f"  {s}: {len(sub)} rows, {sub['team'].nunique()} teams, {sub['gsis_id'].nunique()} unique players")

        # Spot-check: show one team's WR depth
        latest = max(dc["season"].unique())
        print(f"\nSpot-check — {latest} BUF WRs:")
        wr = dc[(dc["season"] == latest) & (dc["team"] == "BUF") & (dc["position"] == "WR")][["player_name", "depth_rank"]].sort_values("depth_rank")
        print(wr.to_string(index=False))


if __name__ == "__main__":
    main()
