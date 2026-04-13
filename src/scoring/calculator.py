"""Fantasy scoring calculator: convert player stats to fantasy points."""
import pandas as pd
from src.utils.config import get_scoring_rules


STAT_TO_RULE = {
    "passing_yards": "passing_yards",
    "passing_td": "passing_td",
    "passing_int": "passing_int",
    "rushing_yards": "rushing_yards",
    "rushing_td": "rushing_td",
    "receiving_yards": "receiving_yards",
    "receiving_td": "receiving_td",
    "receptions": "receptions",
    "fumble_lost": "fumble_lost",
    "two_point_conversion": "two_point_conversion",
}


def calculate_fantasy_points(stats: dict | pd.Series, format: str = "half_ppr") -> float:
    """Calculate fantasy points for a single player stat line."""
    rules = get_scoring_rules(format)
    points = 0.0
    for stat_key, rule_key in STAT_TO_RULE.items():
        points += float(stats.get(stat_key, 0)) * rules.get(rule_key, 0)
    return points


def add_fantasy_points_to_df(df: pd.DataFrame, format: str = "half_ppr") -> pd.DataFrame:
    """Add fantasy_points and fantasy_points_per_game columns."""
    df = df.copy()
    rules = get_scoring_rules(format)

    points = pd.Series(0.0, index=df.index)
    for stat_col, rule_key in STAT_TO_RULE.items():
        if stat_col in df.columns:
            points += df[stat_col].fillna(0) * rules.get(rule_key, 0)

    df["fantasy_points"] = points
    if "games" in df.columns:
        df["fantasy_points_per_game"] = points / df["games"].replace(0, pd.NA)

    return df


def add_all_scoring_formats(df: pd.DataFrame) -> pd.DataFrame:
    """Add fantasy points for all three scoring formats."""
    for fmt in ["standard", "half_ppr", "ppr"]:
        rules = get_scoring_rules(fmt)
        points = pd.Series(0.0, index=df.index)
        for stat_col, rule_key in STAT_TO_RULE.items():
            if stat_col in df.columns:
                points += df[stat_col].fillna(0) * rules.get(rule_key, 0)
        df[f"fantasy_points_{fmt}"] = points

    return df
