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

    When a source contains separate regular- and postseason rows, retain only
    ``REG``. Draft projections target regular-season fantasy scoring; adding
    playoff games would inflate both historical targets and lagged features for
    players on successful NFL teams.
    """
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    # nflverse seasonal releases can contain separate REG and POST rows. Never
    # sum them for a season-long fantasy target.
    if "season_type" in df.columns and "player_id" in df.columns and "season" in df.columns:
        regular = df[df["season_type"].astype(str).str.upper().eq("REG")].copy()
        if not regular.empty:
            df = regular

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
