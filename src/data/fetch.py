"""Data pipeline: fetch and cache NFL stats via nfl_data_py.

Actual nfl_data_py API (v0.3.x):
- import_seasonal_data(seasons): Player seasonal stats (includes fantasy_points!)
- import_weekly_data(seasons): Player weekly stats
- import_seasonal_rosters(seasons): Roster info (position, age, team)
- import_snap_counts(seasons): Snap count data by week
- import_seasonal_pfr(seasons, s_type): Advanced PFR stats (pass/rec/rush)
- import_players(): Player biographical info
- import_depth_charts(seasons): Depth chart positions
- import_injuries(seasons): Injury reports
- import_schedules(seasons): NFL schedule, rest, venue, and pregame market lines
- import_ngs_data(stat_type, seasons): Next Gen Stats player data

NOT available: import_team_seasonal_data, import_adp, import_rosters
Team stats are derived by aggregating player seasonal data.
"""
from datetime import datetime, timezone
from io import BytesIO, StringIO
import re

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

# nfl_data_py declares fastparquet as its parquet backend. Some environments
# also install pyarrow, causing pandas' ``auto`` selection to choose pyarrow;
# recent nflverse list-encoded assets are currently unreadable in affected
# pyarrow builds. Select the backend nfl_data_py ships for explicitly so clean
# local and CI exports behave the same way.
pd.options.io.parquet.engine = "fastparquet"

try:
    import nfl_data_py as nfl
except ImportError:
    nfl = None

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _read_release_csv(url: str, timeout: int = 45) -> pd.DataFrame:
    """Read an official nflverse CSV release asset with a stable user agent."""
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nflmodel/1.0 (+https://overadp.com)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return pd.read_csv(BytesIO(response.read()))


def _ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _load_or_fetch(cache_path: Path, fetch_fn, cache: bool = True, required_seasons: list[int] | None = None) -> pd.DataFrame:
    """Load from cache if exists and has all required seasons, otherwise fetch."""
    if cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        if required_seasons and "season" in df.columns:
            cached_seasons = set(df["season"].unique())
            missing = set(required_seasons) - cached_seasons
            if not missing:
                return df[df["season"].isin(required_seasons)] if "season" in df.columns else df
            # Cache is missing seasons, re-fetch
        else:
            return df
    df = fetch_fn()
    if cache:
        df.to_parquet(cache_path, index=False)
    return df


def _fetch_seasonal_from_nflverse(seasons: list[int]) -> pd.DataFrame:
    """Fetch seasonal stats directly from nflverse-data GitHub releases.

    Used as fallback for seasons not yet available via nfl_data_py.
    """
    import urllib.request
    dfs = []
    base_url = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"
    for season in seasons:
        # Draft projections target regular-season scoring. Pulling POST here
        # is unnecessary and creates duplicate player-season rows that the
        # cleaner only discards later.
        for suffix in ["reg"]:
            url = f"{base_url}stats_player_{suffix}_{season}.parquet"
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=30)
                tmp_path = DATA_DIR / f"stats_player_{suffix}_{season}.parquet"
                tmp_path.write_bytes(resp.read())
                df = pd.read_parquet(tmp_path)
                dfs.append(df)
            except Exception as parquet_exc:
                # nflverse publishes equivalent CSV assets. Keep the exporter
                # operational if a parquet asset is temporarily malformed or
                # uses an encoding unsupported by the runner's pyarrow build.
                csv_url = f"{base_url}stats_player_{suffix}_{season}.csv"
                try:
                    dfs.append(_read_release_csv(csv_url))
                except Exception as csv_exc:
                    print(
                        f"  Warning: seasonal {season} {suffix} unavailable "
                        f"(parquet {parquet_exc.__class__.__name__}; "
                        f"csv {csv_exc.__class__.__name__})."
                    )
    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()


def fetch_seasonal_stats(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch player seasonal stats for given seasons.

    Includes: passing, rushing, receiving, fantasy_points, fantasy_points_ppr,
    target_share, carries, games, etc.

    Tries nfl_data_py first, falls back to direct nflverse-data download
    for seasons not yet available in the package.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "seasonal_stats.parquet"

    # Try loading from cache first
    if cache and cache_path.exists():
        cached = pd.read_parquet(cache_path)
        if "season" in cached.columns:
            cached_seasons = set(cached["season"].unique())
            missing = set(seasons) - cached_seasons
            if not missing:
                return cached[cached["season"].isin(seasons)]
            # Fetch only missing seasons and append
            new_df = None
            if nfl is not None:
                try:
                    new_df = nfl.import_seasonal_data(list(missing))
                except Exception:
                    pass
            if new_df is None or new_df.empty:
                new_df = _fetch_seasonal_from_nflverse(list(missing))
            if not new_df.empty:
                # Standardize column names to match nfl_data_py format
                col_map = {
                    "passing_interceptions": "interceptions",
                    "sacks_suffered": "sacks",
                    "sack_yards_lost": "sack_yards",
                    "recent_team": "team",
                }
                new_df = new_df.rename(columns={k: v for k, v in col_map.items() if k in new_df.columns})
                combined = pd.concat([cached, new_df], ignore_index=True)
                combined.to_parquet(cache_path, index=False)
                return combined[combined["season"].isin(seasons)]
        else:
            return cached

    # No cache — fetch all seasons
    df = None
    if nfl is not None:
        try:
            df = nfl.import_seasonal_data(seasons)
        except Exception:
            pass
    if df is None or df.empty:
        df = _fetch_seasonal_from_nflverse(seasons)
    if df is not None and not df.empty:
        # CSV fallbacks represent list-valued kicking details as a mixture of
        # text and blank floats. They are not model inputs, but normalizing
        # them keeps the reusable parquet cache Arrow-compatible.
        for column in [col for col in df.columns if col.endswith("_list")]:
            df[column] = df[column].astype("string")
        col_map = {
            "passing_interceptions": "interceptions",
            "sacks_suffered": "sacks",
            "sack_yards_lost": "sack_yards",
            "recent_team": "team",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if cache:
            df.to_parquet(cache_path, index=False)
    return df[df["season"].isin(seasons)] if df is not None and "season" in df.columns else df


def fetch_weekly_stats(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch player weekly stats for given seasons.

    Tries nfl_data_py first, falls back to direct nflverse-data download.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "weekly_stats.parquet"

    # Try cache first
    if cache and cache_path.exists():
        cached = pd.read_parquet(cache_path)
        if "season" in cached.columns:
            cached_seasons = set(cached["season"].unique())
            missing = set(seasons) - cached_seasons
            if not missing:
                return cached[cached["season"].isin(seasons)]
            # Fetch missing seasons
            new_df = None
            if nfl is not None:
                try:
                    new_df = nfl.import_weekly_data(list(missing))
                except Exception:
                    pass
            if new_df is None or new_df.empty:
                # Fallback to nflverse-data releases
                import urllib.request
                dfs = []
                base_url = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"
                for s in list(missing):
                    url = f"{base_url}stats_player_week_{s}.parquet"
                    try:
                        req = urllib.request.Request(url)
                        req.add_header("User-Agent", "Mozilla/5.0")
                        resp = urllib.request.urlopen(req, timeout=30)
                        tmp = DATA_DIR / f"stats_player_week_{s}.parquet"
                        tmp.write_bytes(resp.read())
                        dfs.append(pd.read_parquet(tmp))
                    except Exception:
                        pass
                if dfs:
                    new_df = pd.concat(dfs, ignore_index=True)
            if new_df is not None and not new_df.empty:
                combined = pd.concat([cached, new_df], ignore_index=True)
                combined.to_parquet(cache_path, index=False)
                return combined[combined["season"].isin(seasons)]
        else:
            return cached

    # No cache
    df = None
    if nfl is not None:
        try:
            df = nfl.import_weekly_data(seasons)
        except Exception:
            pass
    if df is None or df.empty:
        import urllib.request
        dfs = []
        base_url = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"
        for s in seasons:
            url = f"{base_url}stats_player_week_{s}.parquet"
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=30)
                tmp = DATA_DIR / f"stats_player_week_{s}.parquet"
                tmp.write_bytes(resp.read())
                dfs.append(pd.read_parquet(tmp))
            except Exception:
                pass
        if dfs:
            df = pd.concat(dfs, ignore_index=True)
    if df is not None and not df.empty:
        if cache:
            df.to_parquet(cache_path, index=False)
    return df[df["season"].isin(seasons)] if df is not None and "season" in df.columns else df


def fetch_roster_info(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch roster info: positions, teams, ages, etc.

    Uses import_seasonal_rosters (not import_rosters which doesn't exist).
    Falls back to local cache if nfl_data_py fails for future seasons.
    """
    _ensure_data_dir()
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    cache_path = DATA_DIR / "roster_info.parquet"

    # Fetch each season separately. One newly published/future parquet can be
    # missing or malformed while every completed-season file is healthy. A
    # single bulk call would otherwise prevent a clean CI runner from building
    # any projections at all. The Sleeper overlay later synthesizes the target
    # season from the most recent historical roster when that target file is
    # unavailable.
    frames: list[pd.DataFrame] = []
    cached_seasons: set[int] = set()
    if cache and cache_path.exists():
        try:
            cached = pd.read_parquet(cache_path)
            if "season" in cached.columns:
                cached_seasons = set(
                    pd.to_numeric(cached["season"], errors="coerce")
                    .dropna()
                    .astype(int)
                )
                frames.append(cached[cached["season"].isin(seasons)].copy())
            elif not cached.empty:
                frames.append(cached.copy())
        except Exception as exc:
            print(
                "  Warning: roster cache is unreadable "
                f"({exc.__class__.__name__}). Re-fetching."
            )

    failed: list[int] = []
    for season in sorted(set(seasons) - cached_seasons):
        try:
            season_df = nfl.import_seasonal_rosters([season])
        except Exception as exc:
            csv_url = (
                "https://github.com/nflverse/nflverse-data/releases/download/"
                f"rosters/roster_{season}.csv"
            )
            try:
                season_df = _read_release_csv(csv_url)
                season_df = season_df.rename(
                    columns={"gsis_id": "player_id", "full_name": "player_name"}
                )
                if "birth_date" in season_df.columns:
                    season_df["birth_date"] = pd.to_datetime(
                        season_df["birth_date"], errors="coerce"
                    )
                print(
                    f"  Roster {season}: using nflverse CSV fallback "
                    f"after {exc.__class__.__name__}."
                )
            except Exception as csv_exc:
                failed.append(season)
                print(
                    f"  Warning: roster {season} unavailable "
                    f"(parquet {exc.__class__.__name__}; "
                    f"csv {csv_exc.__class__.__name__})."
                )
                continue
        if season_df is None or season_df.empty:
            failed.append(season)
            print(f"  Warning: roster {season} returned no rows.")
            continue
        frames.append(season_df)

    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        raise RuntimeError(f"No roster seasons available for {sorted(set(seasons))}")

    combined = pd.concat(frames, ignore_index=True)
    if "season" in combined.columns:
        combined = combined[combined["season"].isin(seasons)].copy()
        combined = combined.drop_duplicates(
            subset=[col for col in ("player_id", "season") if col in combined.columns],
            keep="last",
        )
    # CSV and parquet roster releases infer some identifier columns
    # differently across seasons (for example, numeric ESPN IDs in one year
    # and blank strings in another). Roster object columns are categorical
    # text, so a nullable string representation is lossless and cache-safe.
    for column in combined.select_dtypes(include=["object", "string"]).columns:
        combined[column] = combined[column].astype("string")
    if cache and not combined.empty:
        combined.to_parquet(cache_path, index=False)
    if failed:
        print(
            f"  Warning: roster seasons {failed} are unavailable; "
            "continuing with the available seasons."
        )
    return combined


def fetch_team_stats(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Derive team-level stats by aggregating player seasonal data.

    nfl_data_py doesn't have import_team_seasonal_data, so we aggregate
    from player-level stats grouped by team and season.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "team_stats.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    player_df = fetch_seasonal_stats(seasons, cache=cache)
    roster_df = fetch_roster_info(seasons, cache=cache)

    # Merge team info onto player stats
    # First try player_id + season (exact match)
    if "player_id" in roster_df.columns and "player_id" in player_df.columns:
        roster_sub = roster_df[["player_id", "season", "team"]].drop_duplicates(subset=["player_id", "season"])
        if "team" in player_df.columns:
            player_df = player_df.merge(roster_sub, on=["player_id", "season"], how="left", suffixes=("", "_roster"))
            player_df["team"] = player_df["team_roster"].fillna(player_df["team"])
            player_df = player_df.drop(columns=["team_roster"], errors="ignore")
        else:
            player_df = player_df.merge(roster_sub, on=["player_id", "season"], how="left")

    # Fallback: for players still missing team, use latest roster entry
    if "team" not in player_df.columns or player_df["team"].isna().any():
        if "player_id" in roster_df.columns:
            roster_latest = roster_df.sort_values("season").drop_duplicates("player_id", keep="last")
            roster_fb = roster_latest[["player_id", "team"]].rename(columns={"team": "team_fb"})
            player_df = player_df.merge(roster_fb, on="player_id", how="left")
            if "team" in player_df.columns:
                player_df["team"] = player_df["team"].fillna(player_df["team_fb"])
            else:
                player_df["team"] = player_df["team_fb"]
            player_df = player_df.drop(columns=["team_fb"], errors="ignore")

    if "team" not in player_df.columns or player_df["team"].isna().all():
        return pd.DataFrame(columns=["team", "season"])

    # Aggregate to team level
    agg_cols = {}
    for col in ["passing_yards", "passing_tds", "interceptions", "sacks",
                 "carries", "rushing_yards", "rushing_tds",
                 "receptions", "targets", "receiving_yards", "receiving_tds",
                 "attempts", "completions", "games"]:
        if col in player_df.columns:
            agg_cols[col] = "sum"

    if agg_cols:
        team_df = player_df.groupby(["team", "season"]).agg(agg_cols).reset_index()
    else:
        team_df = player_df[["team", "season"]].drop_duplicates()

    # Rename for clarity
    rename_map = {
        "carries": "rushing_attempts",
        "attempts": "passing_attempts",
        "interceptions": "passing_int",
    }
    team_df = team_df.rename(columns={k: v for k, v in rename_map.items() if k in team_df.columns})

    if cache:
        team_df.to_parquet(cache_path, index=False)
    return team_df


def fetch_snap_counts(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch snap count data — crucial for usage/volume features."""
    _ensure_data_dir()
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    cache_path = DATA_DIR / "snap_counts.parquet"
    return _load_or_fetch(cache_path, lambda: nfl.import_snap_counts(seasons), cache=cache, required_seasons=seasons)


def fetch_injury_data(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch injury history — critical for risk assessment."""
    _ensure_data_dir()
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    cache_path = DATA_DIR / "injury_data.parquet"
    return _load_or_fetch(cache_path, lambda: nfl.import_injuries(seasons), cache=cache, required_seasons=seasons)


def fetch_coaches(seasons: list[int], cache: bool = True, extra_rows: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Fetch head coach per team per season from nfl_data_py schedules.

    nfl_data_py.import_schedules() populates `home_coach` and `away_coach`
    per game. We aggregate to one HC per (team, season) using the mode (most
    common coach across all that team's games), which handles mid-season
    firings correctly — the interim is only picked up if they coached more
    games than the original HC.

    Args:
        seasons: seasons to fetch
        cache: use parquet cache
        extra_rows: optional DataFrame with columns [season, team, hc] to
            manually add rows for seasons not yet in the schedule data (e.g.,
            the upcoming projection season before games are played)

    Returns:
        DataFrame with columns: season, team, hc
    """
    _ensure_data_dir()
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    cache_path = DATA_DIR / "coaches.parquet"

    def _fetch() -> pd.DataFrame:
        sch = nfl.import_schedules(seasons)
        if sch.empty or "home_coach" not in sch.columns:
            return pd.DataFrame(columns=["season", "team", "hc"])
        home = sch[["season", "home_team", "home_coach"]].rename(
            columns={"home_team": "team", "home_coach": "hc"}
        )
        away = sch[["season", "away_team", "away_coach"]].rename(
            columns={"away_team": "team", "away_coach": "hc"}
        )
        long = pd.concat([home, away], ignore_index=True).dropna()
        # Head coach per (season, team) = mode across the team's games
        hc = (
            long.groupby(["season", "team"])["hc"]
            .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0])
            .reset_index()
        )
        return hc

    df = _load_or_fetch(cache_path, _fetch, cache=cache, required_seasons=seasons)

    if extra_rows is not None and not extra_rows.empty:
        df = pd.concat([df, extra_rows], ignore_index=True).drop_duplicates(
            subset=["season", "team"], keep="last"
        )
    return df


def fetch_schedules(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch NFL schedules.

    The schedule is safe to use for pre-season projection features when combined
    only with information known before that season, such as each opponent's
    prior-season defensive quality. Do not use game results from this table as
    model features.
    """
    _ensure_data_dir()
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    cache_path = DATA_DIR / "schedules.parquet"
    return _load_or_fetch(cache_path, lambda: nfl.import_schedules(seasons), cache=cache, required_seasons=seasons)


def fetch_ngs_data(stat_type: str, seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch Next Gen Stats data for passing, rushing, or receiving.

    nfl_data_py reads these parquet files through pyarrow, which can fail on
    some environments with a repetition-level metadata error. The fallback uses
    fastparquet against the same official nflverse release file.
    """
    _ensure_data_dir()
    if stat_type not in {"passing", "rushing", "receiving"}:
        raise ValueError("stat_type must be one of passing, rushing, receiving")
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")

    cache_path = DATA_DIR / f"ngs_{stat_type}.parquet"

    def _fetch() -> pd.DataFrame:
        try:
            return nfl.import_ngs_data(stat_type, seasons)
        except Exception:
            url = f"https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{stat_type}.parquet"
            df = pd.read_parquet(url, engine="fastparquet")
            return df[df["season"].isin(seasons)] if "season" in df.columns else df

    return _load_or_fetch(cache_path, _fetch, cache=cache, required_seasons=seasons)


def fetch_depth_charts(seasons: list[int], cache: bool = True, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch NFL depth chart data — critical for role identification (WR1 vs WR3).

    Handles two nflverse schemas:
      - 2019-2024 (old): columns season, week, club_code, gsis_id, position, depth_team, ...
        Filter to week=1 for pre-season snapshot.
      - 2025+ (new): columns dt, team, gsis_id, pos_abb, pos_slot, pos_rank, ...
        Multiple daily snapshots; for each season, pick snapshot closest to Sep 5
        (≈ Week 1). For the projection season (most recent), this captures
        pre-Week-1 roles; for a live refresh post-roster-cuts, set force_refresh=True.

    Returns a harmonized DataFrame with columns:
      season, team, gsis_id, player_name, position, depth_rank (1=starter, 2=backup, 3+=depth)

    Args:
        seasons: seasons to fetch
        cache: whether to use cached parquet
        force_refresh: re-download current-season CSV to get latest snapshots
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "depth_charts.parquet"

    if cache and cache_path.exists() and not force_refresh:
        cached = pd.read_parquet(cache_path)
        if set(seasons).issubset(set(cached["season"].unique())):
            return cached[cached["season"].isin(seasons)]

    dfs = []
    for season in seasons:
        url = f"https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv"
        try:
            raw = pd.read_csv(url)
        except Exception as e:
            print(f"  depth_charts {season}: FAILED ({e})")
            continue

        # Detect schema
        if "club_code" in raw.columns and "depth_team" in raw.columns:
            # Old schema: week=1 snapshot
            sub = raw[raw["week"] == 1].copy()
            sub = sub.rename(columns={
                "club_code": "team",
                "depth_team": "depth_rank",
                "full_name": "player_name",
            })
            keep = ["season", "team", "gsis_id", "player_name", "position", "depth_rank"]
            sub = sub[[c for c in keep if c in sub.columns]]
        elif "pos_abb" in raw.columns and "dt" in raw.columns:
            # New schema: pick snapshot closest to Sep 5 of that season
            raw["dt"] = pd.to_datetime(raw["dt"], utc=True)
            target = pd.Timestamp(f"{season}-09-05", tz="UTC")
            raw["_delta"] = (raw["dt"] - target).abs()
            closest_dt = raw.loc[raw["_delta"].idxmin(), "dt"]
            sub = raw[raw["dt"] == closest_dt].copy()
            sub["season"] = season
            sub = sub.rename(columns={"pos_abb": "position"})
            if "pos_rank" in sub.columns:
                sub = sub.rename(columns={"pos_rank": "depth_rank"})
            elif "pos_slot" in sub.columns:
                # pos_slot is a roster-wide slot, not a position depth rank.
                # If an older new-schema file lacks pos_rank, derive the order
                # within each team/position instead of using the raw slot.
                slot = pd.to_numeric(sub["pos_slot"], errors="coerce")
                sub["depth_rank"] = slot.groupby([sub["team"], sub["position"]]).rank(
                    method="dense", ascending=True
                )
            else:
                sub["depth_rank"] = pd.NA
            keep = ["season", "team", "gsis_id", "player_name", "position", "depth_rank"]
            sub = sub[[c for c in keep if c in sub.columns]]
        else:
            print(f"  depth_charts {season}: unknown schema, cols={list(raw.columns)}")
            continue

        dfs.append(sub)

    if not dfs:
        return pd.DataFrame(columns=["season","team","gsis_id","player_name","position","depth_rank"])

    combined = pd.concat(dfs, ignore_index=True)
    combined["depth_rank"] = pd.to_numeric(combined["depth_rank"], errors="coerce").fillna(99).astype(int)

    # Deduplicate: a player may appear in multiple formation slots (LWR/RWR/SLOT, 1st-down/3rd-down RB).
    # Keep MIN depth_rank per (season, gsis_id, position) — the player's best role.
    combined = (
        combined.sort_values("depth_rank")
        .drop_duplicates(subset=["season", "gsis_id", "position"], keep="first")
        .reset_index(drop=True)
    )

    if cache:
        combined.to_parquet(cache_path, index=False)
    return combined


ADP_COLUMNS = [
    "player_name", "position", "team", "adp", "bye", "season", "scoring",
    "source", "source_url", "source_period_end", "requested_season", "fetched_at",
]


def _adp_cache_rows_reusable(
    rows: pd.DataFrame,
    season: int,
    now: datetime,
    max_cache_age_hours: float,
) -> bool:
    """Return whether cached ADP rows have trustworthy provenance and freshness."""
    if rows.empty:
        return False
    required = {
        "requested_season", "source_url", "fetched_at",
        "player_name", "position", "adp",
    }
    if not required.issubset(rows.columns):
        return False
    valid_rows = rows["player_name"].notna() & rows["position"].notna()
    valid_rows &= pd.to_numeric(rows["adp"], errors="coerce").notna()
    if int(valid_rows.sum()) < 50:
        return False
    requested = pd.to_numeric(rows["requested_season"], errors="coerce")
    if requested.isna().any() or not requested.eq(season).all():
        return False

    # Historical preseason snapshots are immutable once captured. The current
    # draft market is live data and must expire quickly.
    if season < now.year:
        return True
    fetched = pd.to_datetime(rows["fetched_at"], utc=True, errors="coerce").max()
    if pd.isna(fetched):
        return False
    age_hours = (pd.Timestamp(now) - fetched).total_seconds() / 3600
    return 0 <= age_hours <= max_cache_age_hours


def _fantasypros_page_matches_season(html: str, season: int) -> bool:
    """Guard against FantasyPros silently serving the current page for a bad URL."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return False
    title = re.sub(r"\s+", " ", match.group(1))
    return re.search(rf"\b{int(season)}\b", title) is not None


def _fetch_espn_preseason_rank_proxy(season: int, requests_module, now: datetime) -> pd.DataFrame:
    """Fetch a complete season-pinned market-rank proxy from ESPN.

    ESPN retains PPR and standard preseason draft ranks after its live ADP
    field resets. Their midpoint is an explicit half-PPR proxy, used only when
    neither FFC nor a complete FantasyPros historical table is available.
    """
    import json as _json

    url = (
        "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/"
        f"seasons/{season}/segments/0/leaguedefaults/1?view=kona_player_info"
    )
    player_filter = {
        "players": {
            "limit": 2000,
            "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "PPR"},
        }
    }
    resp = requests_module.get(
        url,
        timeout=20,
        headers={"User-Agent": "nflmodel/1.0", "x-fantasy-filter": _json.dumps(player_filter)},
    )
    resp.raise_for_status()
    payload = resp.json()
    position_map = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
    rows = []
    for wrapper in payload.get("players", []):
        player = wrapper.get("player", {}) or {}
        position = position_map.get(player.get("defaultPositionId"))
        if position is None:
            continue
        ranks = player.get("draftRanksByRankType", {}) or {}
        std = (ranks.get("STANDARD") or {}).get("rank")
        ppr = (ranks.get("PPR") or {}).get("rank")
        rank_values = [float(v) for v in (std, ppr) if v is not None and float(v) > 0]
        if not rank_values:
            continue
        rows.append({
            "player_name": player.get("fullName", ""),
            "position": position,
            "team": "",
            "adp": float(np.mean(rank_values)),
            "bye": 0,
            "season": season,
            "scoring": "half-ppr-rank-proxy",
            "source": "espn_preseason_rank_proxy",
            "source_url": url,
            "source_period_end": f"{season}-preseason-rank",
            "requested_season": season,
            "fetched_at": now.isoformat(),
        })
    result = pd.DataFrame(rows, columns=ADP_COLUMNS)
    if len(result) < 50:
        return pd.DataFrame(columns=ADP_COLUMNS)
    return result.sort_values("adp").drop_duplicates(["player_name", "position"]).reset_index(drop=True)


def fetch_adp_data(
    seasons: list[int] | None = None,
    cache: bool = True,
    force_refresh: bool = False,
    max_cache_age_hours: float = 12.0,
) -> pd.DataFrame:
    """Fetch Average Draft Position data.

    Primary source: Fantasy Football Calculator API (free, JSON, full names,
    has current-year data). Fallback: FantasyPros HTML scraping.
    ADP is the single best predictor of fantasy value — it aggregates
    thousands of real drafts, capturing market wisdom.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "adp_data.parquet"
    now = datetime.now(timezone.utc)
    requested_seasons = sorted(set(seasons or [now.year]))
    cached = pd.DataFrame(columns=ADP_COLUMNS)
    if cache and cache_path.exists():
        try:
            cached = pd.read_parquet(cache_path)
        except Exception as exc:
            print(f"  ADP cache ignored: {exc}")

    reusable = []
    seasons_to_fetch = []
    for season in requested_seasons:
        rows = cached[cached["season"].eq(season)].copy() if "season" in cached.columns else pd.DataFrame()
        if not force_refresh and _adp_cache_rows_reusable(rows, season, now, max_cache_age_hours):
            reusable.append(rows)
        else:
            seasons_to_fetch.append(season)

    adp_dfs = []
    import requests as _requests

    for season in seasons_to_fetch:
        # --- Primary: Fantasy Football Calculator API ---
        # Free, JSON response, uses full player names (Ja'Marr Chase),
        # has team/position/bye, updates daily.
        # Attribution: fantasyfootballcalculator.com
        ffc_success = False
        for scoring in ["half-ppr", "ppr", "standard"]:
            try:
                url = f"https://fantasyfootballcalculator.com/api/v1/adp/{scoring}?teams=12&year={season}"
                resp = _requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    players = data.get("players", [])
                    meta = data.get("meta", {}) or {}
                    period_end = pd.to_datetime(meta.get("end_date"), errors="coerce")
                    # FFC can answer an unavailable historical-year request with
                    # a different draft period. Reject rather than relabel it.
                    period_matches = pd.isna(period_end) or int(period_end.year) == season
                    if players and period_matches:
                        fetched_at = now.isoformat()
                        rows = []
                        for p in players:
                            rows.append({
                                "player_name": p.get("name", ""),
                                "position": p.get("position", ""),
                                "team": p.get("team", ""),
                                "adp": p.get("adp", 300),
                                "bye": p.get("bye", 0),
                                "season": season,
                                "scoring": scoring,
                                "source": "ffc",
                                "source_url": url,
                                "source_period_end": meta.get("end_date", ""),
                                "requested_season": season,
                                "fetched_at": fetched_at,
                            })
                        adp_dfs.append(pd.DataFrame(rows))
                        ffc_success = True
                        break  # Use first available scoring format
            except Exception:
                pass

        if ffc_success:
            continue

        # --- Fallback: FantasyPros HTML scraping ---
        fantasypros_success = False
        for scoring in ["half-ppr"]:
            # FantasyPros uses "half-point-ppr", not "half-ppr". The latter
            # silently resolves to the current season and caused mislabeled data.
            url = f"https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php?year={season}"
            try:
                resp = _requests.get(url, timeout=15, headers={"User-Agent": "nflmodel/1.0"})
                resp.raise_for_status()
                if not _fantasypros_page_matches_season(resp.text, season):
                    print(f"  FantasyPros ADP rejected for {season}: page title did not match requested year")
                    continue
                tables = pd.read_html(StringIO(resp.text))
                if tables:
                    df = tables[0]
                    df["season"] = season
                    df["scoring"] = scoring
                    df["source"] = "fantasypros"
                    df["source_url"] = url
                    df["source_period_end"] = f"{season}-preseason"
                    df["requested_season"] = season
                    df["fetched_at"] = now.isoformat()
                    if "AVG" in df.columns:
                        df = df.rename(columns={"AVG": "adp"})
                    elif "Avg" in df.columns:
                        df = df.rename(columns={"Avg": "adp"})
                    player_col = next((c for c in ["Player Team (Bye)", "Player (Bye)"] if c in df.columns), None)
                    if player_col:
                        raw = df[player_col].astype(str)
                        df["team"] = raw.str.extract(r'\s([A-Z]{2,3})\s*\(')
                        df["player_name"] = raw.str.replace(r'\s[A-Z]{2,3}\s*\(\d+\).*', '', regex=True).str.strip()
                    if "POS" in df.columns:
                        df["position"] = df["POS"].astype(str).str.extract(r'^([A-Z]+)')[0]
                    keep_cols = [c for c in ADP_COLUMNS if c in df.columns]
                    valid = {"player_name", "position", "adp"}.issubset(keep_cols)
                    valid_count = int(df["adp"].notna().sum()) if valid else 0
                    if valid and valid_count >= 50:
                        adp_dfs.append(df[keep_cols])
                        fantasypros_success = True
                        break
            except Exception:
                pass

        if fantasypros_success:
            continue

        # Final historical fallback: a season-pinned ESPN preseason rank proxy.
        # This is labeled distinctly so evaluation can segment or exclude it.
        try:
            espn = _fetch_espn_preseason_rank_proxy(season, _requests, now)
            if not espn.empty:
                adp_dfs.append(espn)
        except Exception as exc:
            print(f"  ESPN preseason rank proxy failed for {season}: {exc}")

    fresh = pd.concat(adp_dfs, ignore_index=True) if adp_dfs else pd.DataFrame(columns=ADP_COLUMNS)
    available_parts = [part for part in reusable if not part.empty]
    if not fresh.empty:
        available_parts.append(fresh)
    available = (
        pd.concat(available_parts, ignore_index=True)
        if available_parts else pd.DataFrame(columns=ADP_COLUMNS)
    )
    available = available[available["season"].isin(requested_seasons)] if not available.empty else available

    missing = sorted(set(requested_seasons) - set(available["season"].unique())) if not available.empty else requested_seasons
    if missing:
        print(f"  Warning: no trustworthy ADP snapshot available for seasons {missing}")

    if cache and not fresh.empty:
        refreshed_seasons = set(fresh["season"].unique())
        preserved = cached[~cached["season"].isin(refreshed_seasons)] if "season" in cached.columns else cached
        cache_out = pd.concat([preserved, fresh], ignore_index=True)
        cache_out.to_parquet(cache_path, index=False)

    return available.reset_index(drop=True)


def fetch_pfr_advanced(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Fetch Pro Football Reference advanced stats.

    Requires s_type parameter: 'pass', 'rec', or 'rush'.
    We fetch all three and concatenate.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "pfr_advanced.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")

    dfs = []
    for s_type in ["pass", "rec", "rush"]:
        try:
            df = nfl.import_seasonal_pfr(s_type, seasons)
        except Exception:
            try:
                url = f"https://github.com/nflverse/nflverse-data/releases/download/pfr_advstats/advstats_season_{s_type}.parquet"
                df = pd.read_parquet(url, engine="fastparquet")
                df = df[df["season"].isin(seasons)] if "season" in df.columns else df
            except Exception:
                df = pd.DataFrame()
        try:
            if not df.empty:
                df = df.copy()
                df["pfr_stat_type"] = s_type
                dfs.append(df)
        except Exception:
            pass

    if dfs:
        combined = pd.concat(dfs, ignore_index=True)
    else:
        combined = pd.DataFrame()

    if cache and not combined.empty:
        combined.to_parquet(cache_path, index=False)
    return combined


def fetch_ol_metrics(seasons: list[int], cache: bool = True) -> pd.DataFrame:
    """Derive OL quality metrics from aggregated team data.

    - team_rush_ypa: yards per carry (run-blocking proxy)
    - team_sack_rate: sacks per pass attempt (pass-blocking proxy)
    - team_rush_td_rate: rushing TD rate (goal-line OL proxy)
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "ol_metrics.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    team_df = fetch_team_stats(seasons, cache=cache)
    if team_df.empty or "team" not in team_df.columns:
        return pd.DataFrame(columns=["team", "season", "team_rush_ypa", "team_sack_rate", "team_rush_td_rate"])

    ol = team_df[["team", "season"]].drop_duplicates().copy()

    # Run-blocking: yards per attempt
    if "rushing_yards" in team_df.columns and "rushing_attempts" in team_df.columns:
        ol["team_rush_ypa"] = team_df["rushing_yards"] / team_df["rushing_attempts"].replace(0, np.nan)

    # Pass-blocking: sack rate
    if "sacks" in team_df.columns and "passing_attempts" in team_df.columns:
        ol["team_sack_rate"] = team_df["sacks"] / team_df["passing_attempts"].replace(0, np.nan)

    # Goal-line: rushing TD rate
    if "rushing_tds" in team_df.columns and "rushing_attempts" in team_df.columns:
        ol["team_rush_td_rate"] = team_df["rushing_tds"] / team_df["rushing_attempts"].replace(0, np.nan)

    ol = ol.drop_duplicates(subset=["team", "season"]).reset_index(drop=True)
    if cache:
        ol.to_parquet(cache_path, index=False)
    return ol


def fetch_draft_picks(years: list[int] | None = None, cache: bool = True) -> pd.DataFrame:
    """Fetch NFL draft pick data including college stats.

    Columns: season, round, pick, team, gsis_id, position, college,
    college passing/rushing/receiving stats, career approximate value.

    Cache behaviour: if the cache exists but is missing requested seasons, this
    function attempts to fetch only those missing seasons from nflverse and
    appends them.  This means running the pipeline after nflverse publishes a
    new draft class automatically updates the local cache without a full
    re-download.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "draft_picks.parquet"

    if cache and cache_path.exists():
        cached = pd.read_parquet(cache_path)
        if years and "season" in cached.columns:
            available = set(cached["season"].unique())
            missing = set(years) - available
            if not missing:
                return cached[cached["season"].isin(years)]

            # Try to fetch the missing seasons and append to cache
            print(f"  draft_picks: fetching missing seasons {sorted(missing)} from nflverse …")
            if nfl is not None:
                try:
                    new_df = nfl.import_draft_picks(years=list(missing))
                    if new_df is not None and not new_df.empty:
                        # Normalize gsis_id "None" strings
                        if "gsis_id" in new_df.columns:
                            new_df["gsis_id"] = new_df["gsis_id"].replace("None", None)
                        # Align columns before concat
                        for col in cached.columns:
                            if col not in new_df.columns:
                                new_df[col] = None
                        new_df = new_df[[c for c in cached.columns if c in new_df.columns]]
                        combined = pd.concat([cached, new_df], ignore_index=True)
                        combined.to_parquet(cache_path, index=False)
                        print(f"  draft_picks cache updated → seasons {sorted(combined['season'].unique())}")
                        return combined[combined["season"].isin(years)]
                except Exception as exc:
                    print(f"  draft_picks fetch for {sorted(missing)} failed: {exc}")

            # nflverse failed — return whatever we have and warn
            print(f"  Warning: draft_picks cache missing seasons {sorted(missing)}. "
                  "Proceeding with available data only.")
            return cached[cached["season"].isin(available & set(years))] if available & set(years) else cached
        return cached

    # No cache at all — fetch everything
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    df = nfl.import_draft_picks(years=years)
    if df is not None and not df.empty and "gsis_id" in df.columns:
        df["gsis_id"] = df["gsis_id"].replace("None", None)
    if cache and df is not None and not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def fetch_draft_values(cache: bool = True) -> pd.DataFrame:
    """Fetch draft pick value curves from nflverse.

    This is a tiny static table keyed by overall pick.  It is safe for rookie
    and prospect features because pick value is known as soon as the draft
    selection is made.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "draft_values.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    if nfl is not None:
        try:
            df = nfl.import_draft_values()
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    if df.empty:
        url = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/draft_values.csv"
        try:
            df = pd.read_csv(url)
        except Exception as exc:
            print(f"  Warning: draft_values fetch failed ({exc.__class__.__name__}). Skipping.")
            return pd.DataFrame(columns=["pick", "stuart", "johnson", "hill", "otc", "pff"])

    if cache and not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def fetch_contracts(cache: bool = True) -> pd.DataFrame:
    """Fetch historical contract data from nflverse.

    The contract table is not automatically loaded into production data paths.
    Experiments should apply an as-of-season filter before using these rows.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "contracts.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    if nfl is not None:
        try:
            df = nfl.import_contracts()
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    if df.empty:
        url = "https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet"
        try:
            df = pd.read_parquet(url, engine="fastparquet")
        except Exception as exc:
            print(f"  Warning: contracts fetch failed ({exc.__class__.__name__}). Skipping.")
            return pd.DataFrame()

    if cache and not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def fetch_combine_data(years: list[int] | None = None, cache: bool = True) -> pd.DataFrame:
    """Fetch NFL combine data: 40yd, bench, vertical, broad jump, cone, shuttle, ht, wt.

    Key columns: season, draft_round, draft_ovr, pfr_id, player_name, pos, school,
    ht, wt, forty, bench, vertical, broad_jump, cone, shuttle.

    Source: nflverse-data CSV (parquet has pyarrow schema error as of 2026).
    Always fetches full history (2000+) since combine data is small and older
    combine results are needed to match veteran players in the feature matrix.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "combine_data.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    # Prefer nflverse CSV (robust, full history)
    url = "https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv"
    try:
        df = pd.read_csv(url)
    except Exception:
        # Fallback to nfl_data_py import_combine_data
        if nfl is None:
            raise ImportError("nfl_data_py required: pip install nfl_data_py")
        df = nfl.import_combine_data(years=years)

    if cache and not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def fetch_player_info(cache: bool = True) -> pd.DataFrame:
    """Fetch player biographical info: college, draft position, experience.

    Key columns: gsis_id, position, college_name, college_conference,
    draft_year, draft_round, draft_pick, years_of_experience, height, weight.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "player_info.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    df = nfl.import_players()
    if cache and not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def load_all_data(seasons: list[int], cache: bool = True) -> dict[str, pd.DataFrame]:
    """Load all data sources into a dict of DataFrames.

    For future seasons (no stats yet), still loads roster and combine data
    so the model can project returning veterans using their historical stats
    plus current team/position info.
    """
    # Separate historical vs future seasons
    # Stats that require completed seasons
    stats_seasons = [s for s in seasons if s <= 2025]
    # Roster/combine data available for current year too
    roster_seasons = seasons  # roster available for current year

    ngs_data = {}
    if stats_seasons:
        for stat_type in ["passing", "rushing", "receiving"]:
            try:
                ngs_data[stat_type] = fetch_ngs_data(stat_type, stats_seasons, cache=cache)
            except Exception as exc:
                print(f"  Warning: NGS {stat_type} fetch failed ({exc.__class__.__name__}). Skipping.")

    return {
        "seasonal": fetch_seasonal_stats(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "weekly": fetch_weekly_stats(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "roster": fetch_roster_info(roster_seasons, cache=cache),
        "team": fetch_team_stats(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "ol": fetch_ol_metrics(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "snap_counts": fetch_snap_counts(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "pfr": fetch_pfr_advanced(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "schedules": fetch_schedules(seasons, cache=cache),
        "draft": fetch_draft_picks(years=seasons, cache=cache),
        "draft_values": fetch_draft_values(cache=cache),
        "contracts": fetch_contracts(cache=cache),
        "combine": fetch_combine_data(years=seasons, cache=cache),
        "player_info": fetch_player_info(cache=cache),
        "ngs": ngs_data,
    }
