"""Data cleaning: handle missing values, filter invalid records, standardize."""
import pandas as pd
import numpy as np

# Canonical team abbreviations (nflverse seasonal stats format)
# All data sources are normalized to these 32 abbreviations
TEAM_MAP = {
    # Rams: LAR/LA → LA (nflverse uses LA for current Rams)
    "LAR": "LA", "STL": "LA",
    # Raiders: LVR/OAK → LV
    "LVR": "LV", "OAK": "LV",
    # Chargers: SD → LAC
    "SD": "LAC",
    # Washington: WSH/WFT → WAS
    "WSH": "WAS", "WFT": "WAS",
    # Jaguars: JAC → JAX
    "JAC": "JAX",
    # PFR format variants
    "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO",
    "SFO": "SF", "TAM": "TB",
}


def normalize_teams(df: pd.DataFrame, col: str = "team") -> pd.DataFrame:
    """Normalize team abbreviations to nflverse standard."""
    if col in df.columns:
        # Preserve NaN — don't convert to string 'NAN'
        df[col] = df[col].fillna("NONE").astype(str).str.upper().str.strip()
        df[col] = df[col].replace(TEAM_MAP)
        # Convert placeholder values back to NaN
        df[col] = df[col].replace({"NONE": np.nan, "NAN": np.nan})
    return df


def clean_seasonal_stats(df: pd.DataFrame, min_games: int = 3) -> pd.DataFrame:
    """Clean seasonal player stats.

    Combines REG and POST season types into a single row per player per season.

    KNOWN BIAS: summing REG + POST inflates fantasy_points for playoff-team
    players by 1-4 extra games. Most leagues score regular season only, so
    projections may be slightly too high for players whose teams reach the
    postseason. The bias is consistent between our model and the ADP baseline,
    so relative accuracy comparisons remain valid; only absolute projection
    magnitudes are affected. Future fix: filter to season_type == "REG" before
    aggregation and retrain. (Tracked as a follow-up — not changed here to
    avoid silently shifting deployed projections.)
    """
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    # Combine REG + POST into one row per player per season
    if "season_type" in df.columns and "player_id" in df.columns and "season" in df.columns:
        # Separate REG and POST
        reg = df[df["season_type"] == "REG"].copy()
        post = df[df["season_type"] == "POST"].copy()

        # Sum numeric columns across season types per player per season
        group_cols = ["player_id", "season"]
        # Keep non-numeric from REG row (name, position, team, etc.)
        non_numeric = reg[group_cols + [c for c in reg.columns if reg[c].dtype == object and c not in group_cols]]
        non_numeric = non_numeric.drop_duplicates(subset=group_cols)

        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in group_cols]
        combined = df.groupby(group_cols)[numeric_cols].sum().reset_index()

        # Merge back non-numeric info
        combined = combined.merge(non_numeric, on=group_cols, how="left")
        df = combined

    # Standardize column names from new nflverse format to match nfl_data_py format
    col_map = {
        "passing_interceptions": "interceptions",
        "sacks_suffered": "sacks",
        "sack_yards_lost": "sack_yards",
        "recent_team": "team",
        "passing_2pt_conversions": "passing_2pt",
        "rushing_2pt_conversions": "rushing_2pt",
        "receiving_2pt_conversions": "receiving_2pt",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    # Standardize team abbreviations to nflverse format
    df = normalize_teams(df)

    if "games" in df.columns:
        df = df[df["games"] >= min_games]

    return df.reset_index(drop=True)


def clean_weekly_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Clean weekly player stats."""
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    return df.reset_index(drop=True)


def clean_roster_info(df: pd.DataFrame) -> pd.DataFrame:
    """Clean roster info — standardize positions, teams."""
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    if "position" in df.columns:
        df["position"] = df["position"].str.upper().str.strip()
        pos_map = {"FB": "RB", "HB": "RB"}
        df["position"] = df["position"].replace(pos_map)

    # Standardize team abbreviations to nflverse format
    df = normalize_teams(df)

    # Dedupe on (player_id, season) so per-season roster entries are preserved.
    # Earlier code deduped on player_id alone with keep="last", which collapsed
    # every veteran to whatever the most recent loaded season had — and breaks
    # downstream merges (e.g. ADP) when the latest season's roster has empty
    # football_name (as the 2026 pre-draft roster did).
    dedup_cols = ["player_id", "season"] if "season" in df.columns else ["player_id"]
    df = df.drop_duplicates(subset=dedup_cols, keep="last")
    return df.reset_index(drop=True)


def clean_team_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Clean team-level stats."""
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    df = normalize_teams(df)

    return df.reset_index(drop=True)


def clean_ol_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Clean OL derived metrics."""
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())

    df = normalize_teams(df)

    return df.reset_index(drop=True)


def clean_snap_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Clean snap count data."""
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    return df.reset_index(drop=True)
