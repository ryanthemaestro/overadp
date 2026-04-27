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

NOT available: import_team_seasonal_data, import_adp, import_rosters
Team stats are derived by aggregating player seasonal data.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

try:
    import nfl_data_py as nfl
except ImportError:
    nfl = None

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


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
        for suffix in ["reg", "post"]:
            url = f"{base_url}stats_player_{suffix}_{season}.parquet"
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=30)
                tmp_path = DATA_DIR / f"stats_player_{suffix}_{season}.parquet"
                tmp_path.write_bytes(resp.read())
                df = pd.read_parquet(tmp_path)
                dfs.append(df)
            except Exception:
                pass
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

    # Try fetching normally first
    try:
        return _load_or_fetch(cache_path, lambda: nfl.import_seasonal_rosters(seasons), cache=cache, required_seasons=seasons)
    except (OSError, Exception) as e:
        # nfl_data_py can fail for future seasons (corrupted parquet, 404, etc.)
        # Fall back to loading whatever we have locally
        print(f"  Warning: nfl_data_py roster fetch failed ({e.__class__.__name__}). Using local cache.")
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            if "season" in df.columns:
                available = set(df["season"].unique())
                missing = set(seasons) - available
                if missing:
                    print(f"  Warning: roster cache missing seasons {sorted(missing)}. Proceeding with available data.")
                return df[df["season"].isin(available & set(seasons))] if available & set(seasons) else df
            return df
        raise


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
        elif "pos_slot" in raw.columns and "dt" in raw.columns:
            # New schema: pick snapshot closest to Sep 5 of that season
            raw["dt"] = pd.to_datetime(raw["dt"])
            target = pd.Timestamp(f"{season}-09-05", tz="UTC")
            raw["_delta"] = (raw["dt"] - target).abs()
            closest_dt = raw.loc[raw["_delta"].idxmin(), "dt"]
            sub = raw[raw["dt"] == closest_dt].copy()
            sub["season"] = season
            sub = sub.rename(columns={
                "pos_abb": "position",
                "pos_slot": "depth_rank",
            })
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


def fetch_adp_data(seasons: list[int] | None = None, cache: bool = True) -> pd.DataFrame:
    """Fetch Average Draft Position data.

    Primary source: Fantasy Football Calculator API (free, JSON, full names,
    has current-year data). Fallback: FantasyPros HTML scraping.
    ADP is the single best predictor of fantasy value — it aggregates
    thousands of real drafts, capturing market wisdom.
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "adp_data.parquet"

    if cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        if seasons and "season" in df.columns:
            if set(seasons).issubset(set(df["season"].unique())):
                return df[df["season"].isin(seasons)]
        else:
            return df

    adp_dfs = []
    import requests as _requests

    for season in (seasons or [2025]):
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
                    if players:
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
                            })
                        adp_dfs.append(pd.DataFrame(rows))
                        ffc_success = True
                        break  # Use first available scoring format
            except Exception:
                pass

        if ffc_success:
            continue

        # --- Fallback: FantasyPros HTML scraping ---
        for scoring in ["half-ppr"]:
            url = f"https://www.fantasypros.com/nfl/adp/{scoring}-overall.php?year={season}"
            try:
                tables = pd.read_html(url)
                if tables:
                    df = tables[0]
                    df["season"] = season
                    df["scoring"] = scoring
                    df["source"] = "fantasypros"
                    if "AVG" in df.columns:
                        df = df.rename(columns={"AVG": "adp"})
                    elif "Avg" in df.columns:
                        df = df.rename(columns={"Avg": "adp"})
                    if "Player Team (Bye)" in df.columns:
                        raw = df["Player Team (Bye)"].astype(str)
                        df["team"] = raw.str.extract(r'\s([A-Z]{2,3})\s*\(')
                        df["player_name"] = raw.str.replace(r'\s[A-Z]{2,3}\s*\(\d+\).*', '', regex=True).str.strip()
                    if "POS" in df.columns:
                        df["position"] = df["POS"].astype(str).str.extract(r'^([A-Z]+)')[0]
                    keep_cols = [c for c in ["player_name", "position", "team", "adp", "season", "scoring", "source"] if c in df.columns]
                    if keep_cols:
                        adp_dfs.append(df[keep_cols])
            except Exception:
                pass

    if not adp_dfs:
        return pd.DataFrame(columns=["player_name", "position", "team", "adp", "season", "scoring", "source"])

    df = pd.concat(adp_dfs, ignore_index=True)
    if cache:
        df.to_parquet(cache_path, index=False)
    return df


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
            df = nfl.import_seasonal_pfr(seasons, s_type=s_type)
            if not df.empty:
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
    """
    _ensure_data_dir()
    cache_path = DATA_DIR / "draft_picks.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)
    if nfl is None:
        raise ImportError("nfl_data_py required: pip install nfl_data_py")
    df = nfl.import_draft_picks(years=years)
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

    return {
        "seasonal": fetch_seasonal_stats(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "weekly": fetch_weekly_stats(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "roster": fetch_roster_info(roster_seasons, cache=cache),
        "team": fetch_team_stats(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "ol": fetch_ol_metrics(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "snap_counts": fetch_snap_counts(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "pfr": fetch_pfr_advanced(stats_seasons, cache=cache) if stats_seasons else pd.DataFrame(),
        "draft": fetch_draft_picks(years=seasons, cache=cache),
        "combine": fetch_combine_data(years=seasons, cache=cache),
        "player_info": fetch_player_info(cache=cache),
    }
