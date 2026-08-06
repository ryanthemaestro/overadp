"""Fantasy scoring calculator: convert player stats to fantasy points."""
import pandas as pd
from src.utils.config import get_scoring_rules


STAT_TO_RULE = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_td",
    "interceptions": "passing_int",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_td",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_td",
    "receptions": "receptions",
    "sack_fumbles_lost": "fumble_lost",
    "rushing_fumbles_lost": "fumble_lost",
    "passing_2pt": "two_point_conversion",
    "rushing_2pt": "two_point_conversion",
    "receiving_2pt": "two_point_conversion",
}

LEGACY_STAT_ALIASES = {
    "passing_tds": "passing_td",
    "interceptions": "passing_int",
    "rushing_tds": "rushing_td",
    "receiving_tds": "receiving_td",
    "sack_fumbles_lost": "fumble_lost",
    "rushing_fumbles_lost": "fumble_lost",
}


def calculate_fantasy_points(stats: dict | pd.Series, format: str = "half_ppr") -> float:
    """Calculate fantasy points for a single player stat line."""
    rules = get_scoring_rules(format)
    points = 0.0
    used_aliases: set[str] = set()
    for stat_key, rule_key in STAT_TO_RULE.items():
        if stat_key in stats:
            value = stats.get(stat_key, 0)
        else:
            alias = LEGACY_STAT_ALIASES.get(stat_key)
            if not alias or alias in used_aliases:
                value = 0
            else:
                value = stats.get(alias, 0)
                if alias in stats:
                    used_aliases.add(alias)
        points += float(value or 0) * rules.get(rule_key, 0)
    return points


def add_fantasy_points_to_df(df: pd.DataFrame, format: str = "half_ppr") -> pd.DataFrame:
    """Add fantasy_points and fantasy_points_per_game columns.
    
    Uses nflverse-provided fantasy_points when available (already correctly
    calculated per scoring format). Falls back to manual calculation only
    when the column is missing or all-NaN.
    """
    df = df.copy()

    # nflverse provides fantasy_points (standard) and fantasy_points_ppr
    # For half-PPR, we derive: half_ppr = standard + 0.5 * receptions
    if format == "half_ppr" and "fantasy_points" in df.columns and "receptions" in df.columns:
        if df["fantasy_points"].notna().any():
            df["fantasy_points"] = df["fantasy_points"].fillna(0) + df["receptions"].fillna(0) * 0.5
            if "games" in df.columns:
                df["fantasy_points_per_game"] = df["fantasy_points"] / df["games"].replace(0, pd.NA)
            return df

    if format == "ppr" and "fantasy_points_ppr" in df.columns:
        if df["fantasy_points_ppr"].notna().any():
            df["fantasy_points"] = df["fantasy_points_ppr"].fillna(0)
            if "games" in df.columns:
                df["fantasy_points_per_game"] = df["fantasy_points"] / df["games"].replace(0, pd.NA)
            return df

    if format == "standard" and "fantasy_points" in df.columns:
        if df["fantasy_points"].notna().any():
            if "games" in df.columns:
                df["fantasy_points_per_game"] = df["fantasy_points"] / df["games"].replace(0, pd.NA)
            return df

    # Fallback: manual calculation
    rules = get_scoring_rules(format)
    points = pd.Series(0.0, index=df.index)
    used_aliases: set[str] = set()
    for stat_col, rule_key in STAT_TO_RULE.items():
        if stat_col in df.columns:
            points += df[stat_col].fillna(0) * rules.get(rule_key, 0)
            continue
        alias = LEGACY_STAT_ALIASES.get(stat_col)
        if alias and alias in df.columns and alias not in used_aliases:
            points += df[alias].fillna(0) * rules.get(rule_key, 0)
            used_aliases.add(alias)

    df["fantasy_points"] = points
    if "games" in df.columns:
        df["fantasy_points_per_game"] = points / df["games"].replace(0, pd.NA)

    return df


def add_all_scoring_formats(df: pd.DataFrame) -> pd.DataFrame:
    """Add fantasy points for all three scoring formats."""
    for fmt in ["standard", "half_ppr", "ppr"]:
        rules = get_scoring_rules(fmt)
        points = pd.Series(0.0, index=df.index)
        used_aliases: set[str] = set()
        for stat_col, rule_key in STAT_TO_RULE.items():
            if stat_col in df.columns:
                points += df[stat_col].fillna(0) * rules.get(rule_key, 0)
                continue
            alias = LEGACY_STAT_ALIASES.get(stat_col)
            if alias and alias in df.columns and alias not in used_aliases:
                points += df[alias].fillna(0) * rules.get(rule_key, 0)
                used_aliases.add(alias)
        df[f"fantasy_points_{fmt}"] = points

    return df
