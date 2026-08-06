"""Feature engineering: cross-position and contextual features.

Relationships modeled:
- OL quality → RB production (run-blocking → YPC, TDs)
- OL quality → QB production (pass-blocking → sack rate, efficiency)
- QB efficiency → WR/TE target share and production
- Team pace/volume → positional floor
- Age/experience curves → career trajectory
- Snap count → usage/volume
"""
import pandas as pd
import numpy as np
from typing import Optional


def merge_player_context(
    player_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    team_df: pd.DataFrame,
    ol_df: pd.DataFrame,
    snap_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Merge player stats with roster, team, OL, and snap data."""
    df = player_df.copy()

    # Roster info (position, age, team, name)
    # Strategy: First merge on player_id + season (correct team/age per season),
    # then fall back to player_id-only for players missing from that season's roster.
    if "player_id" in roster_df.columns and "player_id" in df.columns:
        roster_cols = ["player_id", "position", "age", "team"]
        # Preserve Sleeper's stable provider ID through the feature matrix so
        # coverage checks survive public-name and hybrid-position changes.
        if "sleeper_id" in roster_df.columns:
            roster_cols.append("sleeper_id")
        # Add draft/entry year for accurate rookie detection
        for c in ["entry_year", "rookie_year", "draft_club", "draft_number"]:
            if c in roster_df.columns and c not in roster_cols:
                roster_cols.append(c)
        for c in ["player_name", "football_name", "first_name", "last_name"]:
            if c in roster_df.columns and c not in roster_cols:
                roster_cols.append(c)

        # Try season-specific merge first
        if "season" in df.columns and "season" in roster_df.columns:
            roster_season = roster_df[roster_cols + ["season"]].drop_duplicates(["player_id", "season"])
            df = df.merge(roster_season, on=["player_id", "season"], how="left", suffixes=("", "_roster"))

            # Fill unmatched rows with the BEST available roster info for that player.
            # Prefer rows where name fields are populated — pre-season rosters (e.g. 2026
            # before the season opens) ship with empty football_name, and naively taking
            # keep="last" would prefer those over a 2025 row that has full data.
            unmatched = df["position_roster"].isna()
            if unmatched.any():
                fb_cols = roster_df[roster_cols].copy()
                # Rank rows by completeness so the most-populated row per player wins
                # the dedup. football_name is the most consequential field downstream
                # (drives ADP merge), so weight it heavily.
                completeness = pd.Series(0, index=fb_cols.index)
                for col, weight in [("football_name", 4), ("first_name", 1), ("last_name", 1), ("position", 1), ("team", 1)]:
                    if col in fb_cols.columns:
                        completeness = completeness + fb_cols[col].notna().astype(int) * weight
                fb_cols = fb_cols.assign(_completeness=completeness)
                if "season" in roster_df.columns:
                    fb_cols["_season"] = roster_df["season"].values
                    fb_cols = fb_cols.sort_values(["_completeness", "_season"], ascending=[False, False])
                else:
                    fb_cols = fb_cols.sort_values("_completeness", ascending=False)
                fb_cols = fb_cols.drop_duplicates("player_id", keep="first").drop(columns=[c for c in ["_completeness", "_season"] if c in fb_cols.columns])
                fb_cols = fb_cols.rename(columns={c: f"{c}_fb" for c in roster_cols if c != "player_id"})
                df = df.merge(fb_cols, on="player_id", how="left", suffixes=("", "_fb2"))

                # Fill null roster cols from fallback
                for c in roster_cols:
                    if c == "player_id":
                        continue
                    roster_col = f"{c}_roster" if f"{c}_roster" in df.columns else c
                    fb_col = f"{c}_fb"
                    if roster_col in df.columns and fb_col in df.columns:
                        df[roster_col] = df[roster_col].fillna(df[fb_col])
                        df = df.drop(columns=[fb_col], errors="ignore")
                    elif c in df.columns and fb_col in df.columns:
                        df[c] = df[c].fillna(df[fb_col])
                        df = df.drop(columns=[fb_col], errors="ignore")

            # Promote roster columns
            for c in roster_cols:
                if c == "player_id":
                    continue
                roster_col = f"{c}_roster"
                if roster_col in df.columns:
                    if c in df.columns:
                        df[c] = df[roster_col].fillna(df[c])
                    else:
                        df[c] = df[roster_col]
                    df = df.drop(columns=[roster_col], errors="ignore")
        else:
            # No season column — use simple player_id merge
            roster_sub = roster_df[roster_cols].drop_duplicates("player_id")
            df = df.merge(roster_sub, on="player_id", how="left", suffixes=("", "_roster"))
            # Prefer roster position over stats position
            if "position_roster" in df.columns:
                df["position"] = df["position_roster"].fillna(df.get("position", pd.NA))

    # Filter out non-fantasy positions (punters, defensive players, OL)
    fantasy_positions = {"QB", "RB", "WR", "TE", "K", "DEF"}
    if "position" in df.columns:
        before = len(df)
        df = df[df["position"].isin(fantasy_positions)]
        removed = before - len(df)
        if removed:
            import logging
            logging.info(f"Filtered {removed} non-fantasy position players")

    # Fill null ages with position-season median
    if "age" in df.columns and df["age"].isna().any():
        df["age"] = df.groupby(["position", "season"])["age"].transform(
            lambda x: x.fillna(x.median())
        )
        # Final fallback
        if df["age"].isna().any():
            df["age"] = df["age"].fillna(df["age"].median())

    # Team stats
    if "team" in df.columns and "season" in df.columns:
        team_cols = ["team", "season"] + [c for c in team_df.columns if c not in df.columns]
        team_cols = list(set(team_cols) & set(team_df.columns))
        df = df.merge(team_df[team_cols], on=["team", "season"], how="left", suffixes=("", "_team"))

    # OL metrics
    if "team" in df.columns and "season" in df.columns:
        df = df.merge(ol_df, on=["team", "season"], how="left", suffixes=("", "_ol"))

    # Snap counts (aggregate to season level)
    if snap_df is not None and "player_id" in snap_df.columns:
        if "week" in snap_df.columns:
            snap_agg = snap_df.groupby(["player_id", "season"]).agg(
                total_snaps=("offense_snaps", "sum") if "offense_snaps" in snap_df.columns else ("snaps", "sum"),
                total_off_pct=("offense_pct", "mean") if "offense_pct" in snap_df.columns else ("snap_pct", "mean"),
            ).reset_index()
        else:
            snap_agg = snap_df
        if "player_id" in snap_agg.columns and "season" in snap_agg.columns:
            df = df.merge(snap_agg, on=["player_id", "season"], how="left", suffixes=("", "_snap"))

    return df


def compute_ol_rb_features(df: pd.DataFrame) -> pd.DataFrame:
    """OL quality → RB production features.

    - rb_share_of_team_rush: RB's slice of team rushing yards
    - ol_quality_tier: binned run-blocking quality
    """
    df = df.copy()

    if "team_rush_ypa" in df.columns and "rushing_yards" in df.columns:
        team_rush_total = df.groupby(["team", "season"])["rushing_yards"].transform("sum")
        df["rb_share_of_team_rush"] = df["rushing_yards"] / team_rush_total.replace(0, np.nan)
        df["rb_share_of_team_rush"] = df["rb_share_of_team_rush"].fillna(0)

        df["ol_quality_tier"] = pd.cut(
            df["team_rush_ypa"], bins=[0, 3.5, 4.2, 5.0, 99], labels=[1, 2, 3, 4],
        ).astype(float).fillna(2)
        team_ol = (
            df[["team", "season", "team_rush_ypa"]]
            .drop_duplicates(["team", "season"])
            .sort_values(["team", "season"])
        )
        team_ol["team_rush_ypa_lag1"] = team_ol.groupby("team")["team_rush_ypa"].shift(1)
        team_ol["ol_quality_tier_lag1"] = pd.cut(
            team_ol["team_rush_ypa_lag1"], bins=[0, 3.5, 4.2, 5.0, 99], labels=[1, 2, 3, 4],
        ).astype(float)
        df = df.merge(
            team_ol[["team", "season", "team_rush_ypa_lag1", "ol_quality_tier_lag1"]],
            on=["team", "season"],
            how="left",
        )
        df["team_rush_ypa_lag1"] = df["team_rush_ypa_lag1"].fillna(df["team_rush_ypa_lag1"].median()).fillna(0)
        df["ol_quality_tier_lag1"] = df["ol_quality_tier_lag1"].fillna(2)

    if "team_rush_td_rate" in df.columns and "rushing_tds" in df.columns:
        team_rush_tds = df.groupby(["team", "season"])["rushing_tds"].transform("sum")
        df["rb_share_of_team_rush_td"] = df["rushing_tds"] / team_rush_tds.replace(0, np.nan)
        df["rb_share_of_team_rush_td"] = df["rb_share_of_team_rush_td"].fillna(0)

    # === LEAKAGE PREVENTION: Lag current-season share features ===
    for c in ["rb_share_of_team_rush", "rb_share_of_team_rush_td"]:
        if c in df.columns:
            df[f"{c}_lag1"] = df.groupby("player_id")[c].shift(1)
            df[f"{c}_lag1"] = df[f"{c}_lag1"].fillna(0)

    return df


def compute_qb_wr_features(df: pd.DataFrame) -> pd.DataFrame:
    """QB efficiency → WR/TE production features.

    - target_share: WR/TE share of team targets
    - yards_per_target: efficiency metric
    - team_pass_volume: team passing attempts (pace proxy)
    """
    df = df.copy()

    if "targets" in df.columns:
        team_targets = df.groupby(["team", "season"])["targets"].transform("sum")
        df["target_share"] = df["targets"] / team_targets.replace(0, np.nan)
        df["target_share"] = df["target_share"].fillna(0)

    if "receiving_yards" in df.columns and "targets" in df.columns:
        df["yards_per_target"] = df["receiving_yards"] / df["targets"].replace(0, np.nan)
        df["yards_per_target"] = df["yards_per_target"].fillna(0)

    if "passing_attempts" in df.columns:
        df["team_pass_volume"] = df.groupby(["team", "season"])["passing_attempts"].transform("sum")

    if "passing_completions" in df.columns and "passing_attempts" in df.columns:
        df["qb_completion_rate"] = df["passing_completions"] / df["passing_attempts"].replace(0, np.nan)
        df["qb_completion_rate"] = df["qb_completion_rate"].fillna(0)

    if "team_sack_rate" in df.columns:
        df["ol_pass_block_quality"] = 1 - df["team_sack_rate"].fillna(0)

    # === LEAKAGE PREVENTION: Lag current-season WR/QB features ===
    for c in ["target_share", "yards_per_target", "team_pass_volume",
              "qb_completion_rate", "ol_pass_block_quality"]:
        if c in df.columns:
            df[f"{c}_lag1"] = df.groupby("player_id")[c].shift(1)
            df[f"{c}_lag1"] = df[f"{c}_lag1"].fillna(0)

    return df


def compute_age_experience_features(df: pd.DataFrame) -> pd.DataFrame:
    """Age/experience features for career arc modeling."""
    df = df.copy()

    if "age" in df.columns:
        df["age_squared"] = df["age"] ** 2

    if "position" in df.columns and "age" in df.columns:
        prime_ranges = {"QB": (27, 33), "RB": (23, 27), "WR": (24, 29), "TE": (25, 30)}
        df["is_prime"] = df.apply(
            lambda r: 1 if prime_ranges.get(r["position"], (25, 30))[0]
            <= r.get("age", 0) <= prime_ranges.get(r["position"], (25, 30))[1] else 0,
            axis=1,
        )

    return df


def compute_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Volume/usage features — the most predictive fantasy features."""
    df = df.copy()

    if "rushing_attempts" in df.columns and "games" in df.columns:
        df["rush_att_per_game"] = df["rushing_attempts"] / df["games"].replace(0, np.nan)
        df["rush_att_per_game"] = df["rush_att_per_game"].fillna(0)

    if "targets" in df.columns and "games" in df.columns:
        df["targets_per_game"] = df["targets"] / df["games"].replace(0, np.nan)
        df["targets_per_game"] = df["targets_per_game"].fillna(0)

    if "receptions" in df.columns and "targets" in df.columns:
        df["catch_rate"] = df["receptions"] / df["targets"].replace(0, np.nan)
        df["catch_rate"] = df["catch_rate"].fillna(0)

    if "rushing_tds" in df.columns and "rushing_attempts" in df.columns:
        df["rush_td_rate"] = df["rushing_tds"] / df["rushing_attempts"].replace(0, np.nan)
        df["rush_td_rate"] = df["rush_td_rate"].fillna(0)

    if "receiving_tds" in df.columns and "targets" in df.columns:
        df["rec_td_rate"] = df["receiving_tds"] / df["targets"].replace(0, np.nan)
        df["rec_td_rate"] = df["rec_td_rate"].fillna(0)

    # === LEAKAGE PREVENTION: Lag current-season volume features ===
    # targets_per_game, catch_rate, rush_att_per_game use current-season stats.
    # The model should only see the PREVIOUS season's values.
    current_season_volume_cols = [
        "targets_per_game", "catch_rate", "rush_att_per_game",
        "rush_td_rate", "rec_td_rate",
    ]
    for c in current_season_volume_cols:
        if c in df.columns:
            df[f"{c}_lag1"] = df.groupby("player_id")[c].shift(1)
            df[f"{c}_lag1"] = df[f"{c}_lag1"].fillna(0)

    return df


def compute_regression_to_mean_features(df: pd.DataFrame) -> pd.DataFrame:
    """Regression to the mean features — critical for accuracy.

    Players coming off career years tend to regress. Players coming off
    down years tend to bounce back. This is the single biggest source of
    projection error that simple lag features miss.

    Features:
    - yoy_change: year-over-year change in fantasy points (positive = breakout)
    - yoy_pct_change: percentage change
    - is_breakout: >30% improvement over prior year
    - is_bust: >25% decline from prior year
    - regression_risk: how far above/below 2-year rolling average
    """
    df = df.copy().sort_values(["player_id", "season"])

    # Use fantasy_points if available, otherwise compute from stats
    pts_col = None
    for c in ["fantasy_points", "fantasy_points_half_ppr", "fantasy_points_ppr"]:
        if c in df.columns:
            pts_col = c
            break

    if pts_col is None:
        return df

    # Year-over-year change
    df["pts_lag1"] = df.groupby("player_id")[pts_col].shift(1)
    df["yoy_change"] = df[pts_col] - df["pts_lag1"]
    df["yoy_pct_change"] = df["yoy_change"] / df["pts_lag1"].replace(0, np.nan) * 100

    # Per-game production lag — normalizes for injury-shortened seasons
    # A player who scored 140 in 13 games (10.8/g) is better than one who
    # scored 140 in 17 games (8.2/g). This helps the model distinguish
    # injury-driven decline from talent-driven decline.
    if "games" in df.columns:
        df["fp_per_game"] = df[pts_col] / df["games"].replace(0, np.nan)
        df["fp_per_game_lag1"] = df.groupby("player_id")["fp_per_game"].shift(1)
        df["games_lag1"] = df.groupby("player_id")["games"].shift(1)
        # Injury-adjusted FP: what they'd score in a full 17-game season
        df["fp_adj_17games_lag1"] = df["fp_per_game_lag1"] * 17

    # 2-year rolling average for regression baseline
    df["pts_roll2"] = df.groupby("player_id")[pts_col].transform(
        lambda x: x.shift(1).rolling(2, min_periods=1).mean()
    )

    # Regression risk: how far is current season above/below recent average?
    df["regression_risk"] = (df[pts_col] - df["pts_roll2"]) / df["pts_roll2"].replace(0, np.nan) * 100

    # Breakout / bust flags
    df["is_breakout"] = (df["yoy_pct_change"] > 30).astype(int)
    df["is_bust"] = (df["yoy_pct_change"] < -25).astype(int)

    # Injury-adjusted regression: when YoY decline is driven by missed games,
    # the decline is likely temporary (players return to pre-injury form).
    # Key insight: a player who scored 140 in 13 games is NOT in decline —
    # they just got hurt. Their per-game production may still be elite.
    if "games" in df.columns:
        # Injury-driven decline: YoY decline AND current season had fewer games
        # (the decline IS this season — check current games, not lag1)
        injury_decline = (df["yoy_pct_change"] < -15) & (df["games"] < 14)
        # Per-game production held up despite fewer total points
        if "fp_per_game_lag1" not in df.columns:
            df["fp_per_game"] = df[pts_col] / df["games"].replace(0, np.nan)
            df["fp_per_game_lag1"] = df.groupby("player_id")["fp_per_game"].shift(1)
        fp_per_game_lag2 = df.groupby("player_id")["fp_per_game"].shift(2)
        # Per-game rate in current season vs 2 seasons ago (skip the injury season)
        # Use 65% threshold: even a 35% per-game decline can be injury-driven
        # (players play through minor injuries, reducing effectiveness)
        pg_held_up = df["fp_per_game"] >= fp_per_game_lag2 * 0.65

        # Injury-adjusted bust: only flag as bust if decline is NOT injury-driven
        df["is_bust_injury_adj"] = df["is_bust"].copy()
        df.loc[injury_decline & pg_held_up, "is_bust_injury_adj"] = 0

        # Injury-adjusted regression risk: reduce penalty for injury-driven decline
        # If per-game rate held up, the "regression risk" should be mild
        df["regression_risk_injury_adj"] = df["regression_risk"].copy()
        injury_adj_mask = injury_decline & pg_held_up
        # Dampen regression risk by 70% for injury-driven declines
        df.loc[injury_adj_mask, "regression_risk_injury_adj"] = df.loc[injury_adj_mask, "regression_risk"] * 0.3

        # Injury-adjusted YoY change: scale the decline by games_played/17
        # If a player missed 4 games, their YoY decline should be reduced by ~25%
        games_ratio = df["games"] / 17
        df["yoy_change_injury_adj"] = df["yoy_change"].copy()
        df.loc[injury_adj_mask, "yoy_change_injury_adj"] = df.loc[injury_adj_mask, "yoy_change"] * games_ratio[injury_adj_mask]
        df["yoy_pct_change_injury_adj"] = df["yoy_pct_change"].copy()
        df.loc[injury_adj_mask, "yoy_pct_change_injury_adj"] = df.loc[injury_adj_mask, "yoy_pct_change"] * games_ratio[injury_adj_mask]

        # Injury bounce-back flag: player was productive per-game but missed time
        # These players tend to return to form next season
        df["is_injury_bounce_back"] = (injury_decline & pg_held_up).astype(int)

    # TD regression: TD rate tends to regress heavily
    if "rushing_tds" in df.columns and "rushing_attempts" in df.columns:
        df["rush_td_rate_lag1"] = df.groupby("player_id")["rush_td_rate"].shift(1) if "rush_td_rate" in df.columns else np.nan
    if "receiving_tds" in df.columns and "targets" in df.columns:
        df["rec_td_rate_lag1"] = df.groupby("player_id")["rec_td_rate"].shift(1) if "rec_td_rate" in df.columns else np.nan

    # Cap extreme YoY pct changes and regression risk (from near-zero previous season)
    for c in ["yoy_pct_change", "yoy_pct_change_injury_adj", "regression_risk_injury_adj"]:
        if c in df.columns:
            df[c] = df[c].clip(-500, 500)

    # === LEAKAGE PREVENTION: Lag all current-season regression features ===
    # These features are derived from the current season's fantasy_points (the TARGET).
    # Using them directly would be data leakage — the model would know the answer.
    # Fix: shift by 1 season so the model only sees the PREVIOUS season's values.
    # e.g., for predicting 2025, the model sees 2024's regression_risk, not 2025's.
    current_season_regression_cols = [
        "yoy_change", "yoy_pct_change", "regression_risk",
        "is_breakout", "is_bust",
        "yoy_change_injury_adj", "yoy_pct_change_injury_adj",
        "regression_risk_injury_adj", "is_bust_injury_adj", "is_injury_bounce_back",
        "fp_per_game",
    ]
    for c in current_season_regression_cols:
        if c in df.columns:
            lag_col = f"{c}_lag1"
            df[lag_col] = df.groupby("player_id")[c].shift(1)

    # Fill NaN
    for c in ["yoy_change", "yoy_pct_change", "regression_risk", "is_breakout", "is_bust",
              "pts_roll2",
              "rush_td_rate_lag1", "rec_td_rate_lag1",
              "fp_per_game", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1",
              "is_bust_injury_adj", "regression_risk_injury_adj", "is_injury_bounce_back",
              "yoy_change_injury_adj", "yoy_pct_change_injury_adj",
              # Lagged versions (these are what the model should use)
              "yoy_change_lag1", "yoy_pct_change_lag1", "regression_risk_lag1",
              "is_breakout_lag1", "is_bust_lag1",
              "yoy_change_injury_adj_lag1", "yoy_pct_change_injury_adj_lag1",
              "regression_risk_injury_adj_lag1", "is_bust_injury_adj_lag1",
              "is_injury_bounce_back_lag1", "fp_per_game_lag1"]:
        if c in df.columns:
            df[c] = df[c].fillna(0)

    return df


def _merge_team_season_lag(
    df: pd.DataFrame,
    value_col: str,
    lag_col: Optional[str] = None,
    default: float = 0.0,
) -> pd.DataFrame:
    """Lag a team-level value once per season, then merge it to player rows.

    Calling ``groupby('team').shift(1)`` on a player-grain frame shifts by one
    player, not one season. This helper establishes a unique team-season grain
    before shifting so every player on a team receives the same prior value.
    """
    if value_col not in df.columns or not {"team", "season"}.issubset(df.columns):
        return df
    lag_col = lag_col or f"{value_col}_lag1"
    lookup = df[["team", "season", value_col]].copy()
    lookup[value_col] = pd.to_numeric(lookup[value_col], errors="coerce")
    lookup = (
        lookup.groupby(["team", "season"], as_index=False, dropna=False)[value_col]
        .median()
        .sort_values(["team", "season"])
    )
    lookup[lag_col] = lookup.groupby("team", dropna=False)[value_col].shift(1)
    fallback = lookup[lag_col].median()
    if pd.isna(fallback):
        fallback = lookup[value_col].median()
    if pd.isna(fallback):
        fallback = default
    lookup[lag_col] = lookup[lag_col].fillna(float(fallback))
    out = df.drop(columns=[lag_col], errors="ignore")
    return out.merge(
        lookup[["team", "season", lag_col]],
        on=["team", "season"],
        how="left",
        validate="many_to_one",
    )


def compute_sos_features(df: pd.DataFrame, team_df: Optional[pd.DataFrame] = None,
                         full_seasonal_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Strength of Schedule features — who you face matters.

    Features:
    - def_rank: overall defensive rank (lower = better defense = harder for offensive players)
    - pass_def_rank: pass defense rank
    - def_rank_lag1, pass_def_rank_lag1: lagged to prevent leakage
    """
    df = df.copy()

    if 'team' not in df.columns or 'season' not in df.columns:
        return df

    # === Derive defensive rankings ===
    # Priority: team_df opponent stats > full_seasonal_df (all players) > df (offensive only)

    computed = False

    # 1. Try team-level opponent stats (best source)
    if team_df is not None and not team_df.empty:
        def_cols = [c for c in team_df.columns if any(k in c.lower() for k in ['def', 'opp', 'allow', 'sack', 'int'])]
        if def_cols and 'team' in team_df.columns and 'season' in team_df.columns:
            if 'opp_score' in team_df.columns:
                def_strength = team_df.groupby(['team', 'season'])['opp_score'].mean().reset_index()
                def_strength = def_strength.rename(columns={'opp_score': 'def_pts_allowed'})
                def_strength['def_rank'] = def_strength.groupby('season')['def_pts_allowed'].rank(ascending=True)
                df = df.merge(def_strength[['team', 'season', 'def_pts_allowed', 'def_rank']],
                              on=['team', 'season'], how='left', suffixes=('', '_def'))
                for c in ['def_pts_allowed', 'def_rank']:
                    if c in df.columns:
                        df[c] = df[c].fillna(df[c].median() if c in df.columns else 16)
                computed = True

            if 'opp_pass_yds' in team_df.columns:
                pass_def = team_df.groupby(['team', 'season'])['opp_pass_yds'].mean().reset_index()
                pass_def = pass_def.rename(columns={'opp_pass_yds': 'def_pass_yds_allowed'})
                pass_def['pass_def_rank'] = pass_def.groupby('season')['def_pass_yds_allowed'].rank(ascending=True)
                df = df.merge(pass_def[['team', 'season', 'pass_def_rank']],
                              on=['team', 'season'], how='left', suffixes=('', '_pass'))
                if 'pass_def_rank' in df.columns:
                    df['pass_def_rank'] = df['pass_def_rank'].fillna(16)
                computed = True

    # 2. Use full seasonal data (includes defensive players) to compute team defensive rankings
    if not computed and full_seasonal_df is not None and not full_seasonal_df.empty:
        # Need team column in seasonal data
        seasonal = full_seasonal_df.copy()
        if 'team' not in seasonal.columns:
            # Try to get team from roster merge
            pass

        if 'team' in seasonal.columns and 'season' in seasonal.columns:
            # Aggregate defensive stats from ALL players (including defenders)
            def_agg_cols = {}
            for c in ['def_sacks', 'def_interceptions', 'def_pass_defended', 'def_tds',
                       'def_tackles_for_loss', 'def_qb_hits', 'def_fumbles_forced']:
                if c in seasonal.columns:
                    def_agg_cols[c] = 'sum'

            if def_agg_cols:
                team_def = seasonal.groupby(['team', 'season']).agg(def_agg_cols).reset_index()

                # Overall defensive rank: composite score
                # More sacks + INTs + TFLs + QB hits = better defense
                score_parts = []
                if 'def_sacks' in team_def.columns:
                    score_parts.append(team_def['def_sacks'] * 1.0)
                if 'def_interceptions' in team_def.columns:
                    score_parts.append(team_def['def_interceptions'] * 2.0)
                if 'def_tackles_for_loss' in team_def.columns:
                    score_parts.append(team_def['def_tackles_for_loss'] * 0.5)
                if 'def_qb_hits' in team_def.columns:
                    score_parts.append(team_def['def_qb_hits'] * 0.3)
                if 'def_fumbles_forced' in team_def.columns:
                    score_parts.append(team_def['def_fumbles_forced'] * 1.5)

                if score_parts:
                    team_def['def_score'] = sum(score_parts)
                    team_def['def_rank'] = team_def.groupby('season')['def_score'].rank(ascending=False)
                    df = df.merge(team_def[['team', 'season', 'def_rank']],
                                  on=['team', 'season'], how='left', suffixes=('', '_sos'))
                    if 'def_rank_sos' in df.columns:
                        if 'def_rank' in df.columns:
                            df['def_rank'] = df['def_rank_sos'].fillna(df['def_rank'])
                        else:
                            df['def_rank'] = df['def_rank_sos']
                        df = df.drop(columns=['def_rank_sos'], errors='ignore')
                    if 'def_rank' in df.columns:
                        df['def_rank'] = df['def_rank'].fillna(df['def_rank'].median())
                    computed = True

                # Pass defense rank: INTs + pass defended
                pass_parts = []
                if 'def_interceptions' in team_def.columns:
                    pass_parts.append(team_def['def_interceptions'] * 1.0)
                if 'def_pass_defended' in team_def.columns:
                    pass_parts.append(team_def['def_pass_defended'] * 0.5)

                if pass_parts:
                    team_def['pass_def_score'] = sum(pass_parts)
                    team_def['pass_def_rank'] = team_def.groupby('season')['pass_def_score'].rank(ascending=False)
                    df = df.merge(team_def[['team', 'season', 'pass_def_rank']],
                                  on=['team', 'season'], how='left', suffixes=('', '_sos'))
                    if 'pass_def_rank_sos' in df.columns:
                        if 'pass_def_rank' in df.columns:
                            df['pass_def_rank'] = df['pass_def_rank_sos'].fillna(df['pass_def_rank'])
                        else:
                            df['pass_def_rank'] = df['pass_def_rank_sos']
                        df = df.drop(columns=['pass_def_rank_sos'], errors='ignore')
                    if 'pass_def_rank' in df.columns:
                        df['pass_def_rank'] = df['pass_def_rank'].fillna(df['pass_def_rank'].median())
                    computed = True

    # === LEAKAGE FIX: Lag SOS features to use previous season's defensive stats ===
    # Current-season defensive stats include how opponents performed AGAINST this team
    # in the current season, which correlates with current-season player performance.
    for c in ['def_rank', 'pass_def_rank', 'def_pts_allowed']:
        if c in df.columns:
            df = _merge_team_season_lag(
                df,
                value_col=c,
                lag_col=f'{c}_lag1',
                default=16.0 if "rank" in c else 0.0,
            )

    return df


def _prior_defense_rank_lookup(full_seasonal_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Build prior-season defensive rank lookup for schedule-based SOS.

    A row for team-season 2025 becomes a lookup row for schedule season 2026,
    so projection rows only see defensive strength that was already known when
    the 2026 schedule was released.
    """
    if full_seasonal_df is None or full_seasonal_df.empty:
        return pd.DataFrame(columns=["team", "season", "opp_def_rank", "opp_pass_def_rank"])

    seasonal = full_seasonal_df.copy()
    if "team" not in seasonal.columns or "season" not in seasonal.columns:
        return pd.DataFrame(columns=["team", "season", "opp_def_rank", "opp_pass_def_rank"])

    from src.data.clean import normalize_teams
    seasonal = normalize_teams(seasonal, "team")

    agg_cols = {}
    for c in [
        "def_sacks", "def_interceptions", "def_pass_defended", "def_tds",
        "def_tackles_for_loss", "def_qb_hits", "def_fumbles_forced",
    ]:
        if c in seasonal.columns:
            agg_cols[c] = "sum"

    if not agg_cols:
        return pd.DataFrame(columns=["team", "season", "opp_def_rank", "opp_pass_def_rank"])

    team_def = seasonal.groupby(["team", "season"]).agg(agg_cols).reset_index()

    score_parts = []
    if "def_sacks" in team_def.columns:
        score_parts.append(team_def["def_sacks"] * 1.0)
    if "def_interceptions" in team_def.columns:
        score_parts.append(team_def["def_interceptions"] * 2.0)
    if "def_tackles_for_loss" in team_def.columns:
        score_parts.append(team_def["def_tackles_for_loss"] * 0.5)
    if "def_qb_hits" in team_def.columns:
        score_parts.append(team_def["def_qb_hits"] * 0.3)
    if "def_fumbles_forced" in team_def.columns:
        score_parts.append(team_def["def_fumbles_forced"] * 1.5)

    if score_parts:
        team_def["def_score"] = sum(score_parts)
        team_def["opp_def_rank"] = team_def.groupby("season")["def_score"].rank(ascending=False)
    else:
        team_def["opp_def_rank"] = 16.5

    pass_parts = []
    if "def_interceptions" in team_def.columns:
        pass_parts.append(team_def["def_interceptions"] * 1.0)
    if "def_pass_defended" in team_def.columns:
        pass_parts.append(team_def["def_pass_defended"] * 0.5)

    if pass_parts:
        team_def["pass_def_score"] = sum(pass_parts)
        team_def["opp_pass_def_rank"] = team_def.groupby("season")["pass_def_score"].rank(ascending=False)
    else:
        team_def["opp_pass_def_rank"] = team_def["opp_def_rank"]

    lookup = team_def[["team", "season", "opp_def_rank", "opp_pass_def_rank"]].copy()
    lookup["season"] = lookup["season"] + 1
    return lookup


def compute_schedule_sos_features(
    df: pd.DataFrame,
    schedule_df: Optional[pd.DataFrame] = None,
    full_seasonal_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Add schedule-derived strength-of-schedule features.

    Uses the released schedule plus each opponent's prior-season defensive
    rank. This is safe for walk-forward validation and projection because it
    avoids current-season results.
    """
    df = df.copy()
    if schedule_df is None or schedule_df.empty:
        return df
    if "team" not in df.columns or "season" not in df.columns:
        return df
    required = {"season", "home_team", "away_team"}
    if not required.issubset(schedule_df.columns):
        return df

    from src.data.clean import normalize_teams
    df["_schedule_sos_order"] = np.arange(len(df))

    sch = schedule_df.copy()
    if "game_type" in sch.columns:
        sch = sch[sch["game_type"] == "REG"].copy()
    if sch.empty:
        return df

    sch = normalize_teams(sch, "home_team")
    sch = normalize_teams(sch, "away_team")

    common_cols = ["season", "week"]
    for c in ["div_game", "roof", "home_rest", "away_rest"]:
        if c in sch.columns and c not in common_cols:
            common_cols.append(c)

    home = sch[common_cols + ["home_team", "away_team"]].rename(
        columns={"home_team": "team", "away_team": "opponent", "home_rest": "rest", "away_rest": "opp_rest"}
    )
    home["is_home"] = 1
    away = sch[common_cols + ["away_team", "home_team"]].rename(
        columns={"away_team": "team", "home_team": "opponent", "away_rest": "rest", "home_rest": "opp_rest"}
    )
    away["is_home"] = 0
    long = pd.concat([home, away], ignore_index=True)

    lookup = _prior_defense_rank_lookup(full_seasonal_df)
    if not lookup.empty:
        long = long.merge(
            lookup.rename(columns={"team": "opponent"}),
            on=["opponent", "season"],
            how="left",
        )
    else:
        long["opp_def_rank"] = 16.5
        long["opp_pass_def_rank"] = 16.5

    long["opp_def_rank"] = long["opp_def_rank"].fillna(16.5)
    long["opp_pass_def_rank"] = long["opp_pass_def_rank"].fillna(16.5)
    long["top8_def"] = (long["opp_def_rank"] <= 8).astype(int)
    long["bottom8_def"] = (long["opp_def_rank"] >= 25).astype(int)
    long["top8_pass_def"] = (long["opp_pass_def_rank"] <= 8).astype(int)
    long["bottom8_pass_def"] = (long["opp_pass_def_rank"] >= 25).astype(int)

    if "div_game" not in long.columns:
        long["div_game"] = 0
    long["div_game"] = pd.to_numeric(long["div_game"], errors="coerce").fillna(0)

    if "rest" in long.columns and "opp_rest" in long.columns:
        long["rest_advantage"] = (
            pd.to_numeric(long["rest"], errors="coerce").fillna(0)
            - pd.to_numeric(long["opp_rest"], errors="coerce").fillna(0)
        )
    else:
        long["rest_advantage"] = 0

    if "roof" in long.columns:
        roof = long["roof"].fillna("").astype(str).str.lower()
        long["is_dome_game"] = roof.isin(["dome", "closed"]).astype(int)
    else:
        long["is_dome_game"] = 0

    sched = long.groupby(["team", "season"]).agg(
        schedule_games=("opponent", "count"),
        schedule_opp_def_rank=("opp_def_rank", "mean"),
        schedule_opp_pass_def_rank=("opp_pass_def_rank", "mean"),
        schedule_top8_def_games=("top8_def", "sum"),
        schedule_bottom8_def_games=("bottom8_def", "sum"),
        schedule_top8_pass_def_games=("top8_pass_def", "sum"),
        schedule_bottom8_pass_def_games=("bottom8_pass_def", "sum"),
        schedule_home_games=("is_home", "sum"),
        schedule_division_games=("div_game", "sum"),
        schedule_rest_advantage=("rest_advantage", "mean"),
        schedule_dome_games=("is_dome_game", "sum"),
    ).reset_index()

    df = normalize_teams(df, "team")
    feature_cols = [c for c in sched.columns if c not in {"team", "season"}]
    df = df.drop(columns=[c for c in feature_cols if c in df.columns], errors="ignore")
    df = df.merge(sched, on=["team", "season"], how="left")

    rank_cols = ["schedule_opp_def_rank", "schedule_opp_pass_def_rank"]
    count_cols = [c for c in feature_cols if c not in rank_cols + ["schedule_rest_advantage"]]
    for c in rank_cols:
        if c in df.columns:
            df[c] = df[c].fillna(16.5)
    for c in count_cols:
        if c in df.columns:
            df[c] = df[c].fillna(0)
    if "schedule_rest_advantage" in df.columns:
        df["schedule_rest_advantage"] = df["schedule_rest_advantage"].fillna(0)

    df = df.sort_values("_schedule_sos_order").drop(columns=["_schedule_sos_order"])
    return df


def compute_rookie_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rookie/second-year player features — much higher uncertainty.

    Rookies have no NFL track record. Their projections should be
    treated with extra caution (wider confidence intervals).

    Uses draft_year relative to season for accurate classification.
    Falls back to years_of_experience or age-based heuristics.
    """
    df = df.copy()
    df['is_rookie'] = 0
    df['is_2nd_year'] = 0

    if 'draft_year' in df.columns and 'season' in df.columns:
        # Most accurate: draft_year relative to season
        yrs_since_draft = df['season'] - df['draft_year']
        df.loc[yrs_since_draft == 0, 'is_rookie'] = 1
        df.loc[yrs_since_draft == 1, 'is_2nd_year'] = 1
    elif 'entry_year' in df.columns and 'season' in df.columns:
        # entry_year from roster data (year player entered NFL)
        yrs_since_entry = df['season'] - df['entry_year']
        df.loc[yrs_since_entry == 0, 'is_rookie'] = 1
        df.loc[yrs_since_entry == 1, 'is_2nd_year'] = 1
    elif 'rookie_year' in df.columns and 'season' in df.columns:
        # rookie_year from roster data
        yrs_since_rookie = df['season'] - df['rookie_year']
        df.loc[yrs_since_rookie == 0, 'is_rookie'] = 1
        df.loc[yrs_since_rookie == 1, 'is_2nd_year'] = 1
    elif 'years_of_experience' in df.columns:
        # years_of_experience from player_info is current (not season-relative),
        # so we adjust: experience = current_exp - (max_season - season)
        if 'season' in df.columns:
            max_season = df['season'].max()
            adjusted_exp = df['years_of_experience'] - (max_season - df['season'])
            df.loc[adjusted_exp <= 1, 'is_rookie'] = 1
            df.loc[adjusted_exp == 2, 'is_2nd_year'] = 1
        else:
            df.loc[df['years_of_experience'] <= 1, 'is_rookie'] = 1
            df.loc[df['years_of_experience'] == 2, 'is_2nd_year'] = 1
    elif 'age' in df.columns and 'position' in df.columns:
        # Approximate: very young players likely rookies
        for pos in ['QB', 'RB', 'WR', 'TE']:
            typical_rookie_age = {'QB': 23, 'RB': 22, 'WR': 22, 'TE': 23}[pos]
            mask = (df['position'] == pos) & (df['age'] <= typical_rookie_age)
            df.loc[mask, 'is_rookie'] = 1
            mask2 = (df['position'] == pos) & (df['age'] == typical_rookie_age + 1)
            df.loc[mask2, 'is_2nd_year'] = 1

    return df


def compute_stacking_features(df: pd.DataFrame) -> pd.DataFrame:
    """Stacking features — QB + pass-catcher from same team.

    When a QB has a big game, his WRs/TEs tend to also have big games.
    This correlation is valuable for fantasy — it amplifies both upside
    and downside weeks.

    LEAKAGE FIX: Use PREVIOUS season's QB points, not current season.
    Current season QB points would leak the target variable.
    """
    df = df.copy()

    if 'team' not in df.columns or 'position' not in df.columns or 'season' not in df.columns:
        return df

    # Compute QB fantasy points per team per season
    qb_pts = (
        df[df['position'] == 'QB']
        .groupby(['team', 'season'], as_index=False)['fantasy_points']
        .mean()
        .sort_values(['team', 'season'])
    )
    qb_pts['team_qb_avg_pts'] = qb_pts.groupby('team')['fantasy_points'].shift(1)
    fallback = qb_pts['team_qb_avg_pts'].median()
    if pd.isna(fallback):
        fallback = qb_pts['fantasy_points'].median()
    if pd.isna(fallback):
        fallback = 0.0
    qb_pts['team_qb_avg_pts'] = qb_pts['team_qb_avg_pts'].fillna(float(fallback))

    df = df.drop(columns=['team_qb_avg_pts'], errors='ignore').merge(
        qb_pts[['team', 'season', 'team_qb_avg_pts']],
        on=['team', 'season'],
        how='left',
        validate='many_to_one',
    )
    df['team_qb_avg_pts'] = df['team_qb_avg_pts'].fillna(float(fallback))

    # Flag: is this player on the same team as a high-scoring QB?
    if 'team_qb_avg_pts' in df.columns:
        df['qb_stack_bonus'] = 0
        # WR/TE on same team as elite QB get a bonus
        pass_catchers = df['position'].isin(['WR', 'TE'])
        df.loc[pass_catchers, 'qb_stack_bonus'] = (
            df.loc[pass_catchers, 'team_qb_avg_pts'] > df.loc[pass_catchers, 'team_qb_avg_pts'].quantile(0.75)
        ).astype(int)

    return df


def compute_target_competition_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add target/carry competition features — captures how much volume is
    already claimed by OTHER pass-catchers/backs on the current roster.

    This is orthogonal to depth_rank: depth_rank tells us the *role*,
    target competition tells us *how much volume is available*.

    Uses current-season team assignments (who's on the roster now) combined
    with prior-season volume (what those teammates produced last year).
    No leakage: we never use current-season stats from teammates.

    Features:
      - teammate_targets_prev (WR/TE): sum of targets_lag1 from other WR/TE on
        the same team in the current season. High value → crowded pass offense.
      - teammate_carries_prev (RB): sum of rushing_attempts_lag1 from other RBs.
        High value → committee backfield / less work available.
      - teammate_rec_yards_prev (WR/TE): sum of receiving_yards_lag1 from other
        WR/TE on same team — captures quality of competition, not just volume.

    Why this is useful even with ADP/depth_rank:
      - ADP captures market consensus but lags real-time FA moves
      - Depth chart tells role but not volume (WR1 on low-pass team < WR2 on high-pass team)
      - Teammate_targets_prev directly measures the competition

    Rookies: teammates_prev uses veterans already on the team → values populate
    correctly; rookies just have 0 targets_lag1 themselves (already handled).
    """
    df = df.copy()

    if "team" not in df.columns or "season" not in df.columns or "position" not in df.columns:
        return df

    # WR/TE target competition
    if "targets_lag1" in df.columns:
        pass_mask = df["position"].isin(["WR", "TE"])
        df["teammate_targets_prev"] = 0.0
        if pass_mask.any():
            # Sum targets_lag1 across all WR+TE per (team, season), then subtract self
            wrte = df.loc[pass_mask, ["team", "season", "targets_lag1"]].copy()
            wrte["targets_lag1"] = wrte["targets_lag1"].fillna(0)
            team_totals = wrte.groupby(["team", "season"])["targets_lag1"].transform("sum")
            df.loc[pass_mask, "teammate_targets_prev"] = (team_totals - wrte["targets_lag1"]).values

    # WR/TE receiving-yards competition (quality signal, not just volume)
    if "receiving_yards_lag1" in df.columns:
        pass_mask = df["position"].isin(["WR", "TE"])
        df["teammate_rec_yards_prev"] = 0.0
        if pass_mask.any():
            wrte = df.loc[pass_mask, ["team", "season", "receiving_yards_lag1"]].copy()
            wrte["receiving_yards_lag1"] = wrte["receiving_yards_lag1"].fillna(0)
            team_totals = wrte.groupby(["team", "season"])["receiving_yards_lag1"].transform("sum")
            df.loc[pass_mask, "teammate_rec_yards_prev"] = (team_totals - wrte["receiving_yards_lag1"]).values

    # RB carry competition
    if "rushing_attempts_lag1" in df.columns:
        rb_mask = df["position"] == "RB"
        df["teammate_carries_prev"] = 0.0
        if rb_mask.any():
            rbs = df.loc[rb_mask, ["team", "season", "rushing_attempts_lag1"]].copy()
            rbs["rushing_attempts_lag1"] = rbs["rushing_attempts_lag1"].fillna(0)
            team_totals = rbs.groupby(["team", "season"])["rushing_attempts_lag1"].transform("sum")
            df.loc[rb_mask, "teammate_carries_prev"] = (team_totals - rbs["rushing_attempts_lag1"]).values

    # Fill any remaining NaN
    for c in ["teammate_targets_prev", "teammate_rec_yards_prev", "teammate_carries_prev"]:
        if c in df.columns:
            df[c] = df[c].fillna(0)

    return df


def compute_coaching_features(
    df: pd.DataFrame,
    coaches_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Add head-coaching-change features.

    A new HC usually brings scheme shifts that tend to lift young QBs
    (Geno/Waldron, Darnold/O'Connell, Goff/B.Johnson) and reshape RB/WR usage.
    We expose the raw signal plus interactions with age/experience to let
    the model learn position-specific effects.

    Features (team-level, lagged relative to the row's season):
      - `new_hc` (1 if HC differs from prior season, else 0)
      - `hc_tenure_years` (how many consecutive seasons under this HC, >=1)
      - `hc_year1` (1 when tenure == 1, redundant with new_hc but encodes "rookie HC year")

    Interactions:
      - `new_hc_x_young_qb` (new_hc * is_2nd_year, for QB)
      - `new_hc_x_rookie` (new_hc * is_rookie, all positions)

    No leakage: feature is known at draft time (coaches are set in Jan-March).
    For the projection season, callers can pass 2026 HCs via
    `fetch_coaches(..., extra_rows=...)` so `new_hc` computes correctly.

    Args:
        df: feature matrix with columns [season, team]
        coaches_df: optional DataFrame with columns [season, team, hc]

    Returns:
        df with coaching columns added (fills 0 where data is missing)
    """
    df = df.copy()

    # Default zeros so downstream code doesn't break when coaches data is absent
    df["new_hc"] = 0
    df["hc_tenure_years"] = 0
    df["hc_year1"] = 0
    df["new_hc_x_young_qb"] = 0
    df["new_hc_x_rookie"] = 0

    if coaches_df is None or coaches_df.empty:
        return df
    if "team" not in df.columns or "season" not in df.columns:
        return df

    hc = coaches_df[["season", "team", "hc"]].dropna().drop_duplicates()
    hc = hc.sort_values(["team", "season"])

    # Prior-season HC per team
    hc["prev_hc"] = hc.groupby("team")["hc"].shift(1)
    hc["new_hc_flag"] = (hc["hc"] != hc["prev_hc"]) & hc["prev_hc"].notna()
    hc["new_hc_flag"] = hc["new_hc_flag"].astype(int)

    # Tenure: consecutive seasons with same HC per team (resets when HC changes)
    # Build per-team running tenure by walking forward
    tenure_rows = []
    for team, g in hc.groupby("team"):
        t = 0
        prev = None
        for _, r in g.iterrows():
            if r["hc"] != prev:
                t = 1
            else:
                t += 1
            tenure_rows.append({"season": r["season"], "team": team, "hc_tenure_years": t})
            prev = r["hc"]
    tenure = pd.DataFrame(tenure_rows)

    merged = hc.merge(tenure, on=["season", "team"], how="left")
    feat = merged[["season", "team", "new_hc_flag", "hc_tenure_years"]].rename(
        columns={"new_hc_flag": "new_hc"}
    )

    # Merge into main df (drop placeholder cols first so we get the real values)
    df = df.drop(columns=["new_hc", "hc_tenure_years"])
    df = df.merge(feat, on=["season", "team"], how="left")
    df["new_hc"] = df["new_hc"].fillna(0).astype(int)
    df["hc_tenure_years"] = df["hc_tenure_years"].fillna(0).astype(int)
    df["hc_year1"] = (df["hc_tenure_years"] == 1).astype(int)

    # Interactions
    is_2nd = df["is_2nd_year"] if "is_2nd_year" in df.columns else 0
    is_rook = df["is_rookie"] if "is_rookie" in df.columns else 0
    is_qb = (df["position"] == "QB").astype(int) if "position" in df.columns else 0
    df["new_hc_x_young_qb"] = df["new_hc"] * is_2nd * is_qb
    df["new_hc_x_rookie"] = df["new_hc"] * is_rook

    return df


def compute_depth_chart_features(
    df: pd.DataFrame,
    depth_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Add pre-season depth chart rank feature.

    WR1 vs WR3 is a massive uncaptured signal. The depth chart (frozen at
    pre-season / Week 1) tells us the team's announced role, which is
    orthogonal to lagging stats — especially useful for role changes,
    trades, and rookies slotting in.

    Features:
      - depth_rank: 1=starter, 2=backup, 3=WR3/depth, 5+=not on active chart
      - is_starter: binary, depth_rank==1
      - is_backup: binary, depth_rank==2

    Leakage: depth_df should be the pre-Week-1 snapshot. `fetch_depth_charts`
    handles this (week=1 for old schema, Sep-5-closest for new schema).
    """
    df = df.copy()

    if depth_df is None or depth_df.empty:
        df["depth_rank"] = 5
        df["is_starter"] = 0
        df["is_backup"] = 0
        return df

    dc = depth_df.copy()
    # Rename gsis_id -> player_id to match feature matrix key
    if "player_id" not in dc.columns and "gsis_id" in dc.columns:
        dc = dc.rename(columns={"gsis_id": "player_id"})

    # Keep only what we need and ensure per (player_id, season) uniqueness
    keep = [c for c in ["season", "player_id", "position", "depth_rank"] if c in dc.columns]
    dc = dc[keep].dropna(subset=["player_id", "season"]).copy()
    dc["season"] = dc["season"].astype(int)
    # If multiple position entries per player (edge case), take best rank
    dc = dc.sort_values("depth_rank").drop_duplicates(subset=["season", "player_id"], keep="first")

    # Merge on player_id + season
    merge_cols = ["player_id", "season"]
    df = df.merge(dc[merge_cols + ["depth_rank"]], on=merge_cols, how="left")

    # Fill unmatched players (not on Week 1 depth chart) with 5 = "depth / not rostered"
    # Cap at 5: values >5 (IR/PS buckets from new schema) compress to a single "deep" signal
    df["depth_rank"] = df["depth_rank"].fillna(5).clip(upper=5).astype(int)
    df["is_starter"] = (df["depth_rank"] == 1).astype(int)
    df["is_backup"] = (df["depth_rank"] == 2).astype(int)

    return df


def compute_teammate_dependency_features(df: pd.DataFrame) -> pd.DataFrame:
    """Teammate dependency features — your production depends on who's around you.

    Justin Jefferson had a down 2024 because his QB was bad.
    Saquon Barkley exploded because Philly's OL + QB opened lanes.
    These cross-position dependencies are critical for accurate projections.

    Features:
    - qb_quality: How good is this player's QB? (affects WR/TE/RB)
    - wr_corps_quality: How good are this player's WRs? (affects QB)
    - ol_run_quality: How good is the run blocking? (affects RB)
    - box_stack_risk: Bad QB → defenses stack the box → RB suffers
    - target_concentration: Is one WR dominating targets? (good for that WR, bad for others)
    """
    df = df.copy()

    if 'team' not in df.columns or 'position' not in df.columns or 'season' not in df.columns:
        return df

    # --- QB QUALITY → affects WR, TE, RB ---
    # QB quality = their fantasy points per game (already computed in stacking)
    # But we need it as a continuous feature, not just binary
    qb_quality = df[df['position'] == 'QB'].groupby(['team', 'season']).agg(
        qb_fppg=('fantasy_points', lambda x: x.mean() if len(x) > 0 else 0),
        qb_pass_yds=('passing_yards', lambda x: x.mean() if len(x) > 0 else 0),
        qb_pass_tds=('passing_tds', lambda x: x.sum() if len(x) > 0 else 0),
        qb_ints=('interceptions', lambda x: x.sum() if len(x) > 0 else 0),
    ).reset_index()

    # Rank QB quality within season (1 = best QB, 32 = worst)
    if len(qb_quality):
        qb_quality['qb_quality_rank'] = qb_quality.groupby('season')['qb_fppg'].rank(ascending=False)
        # Tier: elite (1-8), average (9-20), bad (21+)
        qb_quality['qb_tier'] = pd.cut(qb_quality['qb_quality_rank'], bins=[0, 8, 20, 35],
                                        labels=[2, 1, 0]).astype(float)

        df = df.merge(qb_quality[['team', 'season', 'qb_fppg', 'qb_quality_rank', 'qb_tier']],
                      on=['team', 'season'], how='left', suffixes=('', '_qbdep'))

        # Fill for QBs themselves and missing
        for c in ['qb_fppg', 'qb_quality_rank', 'qb_tier']:
            if c in df.columns:
                df[c] = df[c].fillna(df[c].median())

        # Box-stack risk: bad QB → defenses stack the box → RB efficiency drops
        # Only meaningful for RBs
        if 'qb_tier' in df.columns:
            df['box_stack_risk'] = 0.0
            rb_mask = df['position'] == 'RB'
            # If QB is tier 0 (bad), RB faces more 8-man boxes
            df.loc[rb_mask & (df['qb_tier'] == 0), 'box_stack_risk'] = 1.0
            df.loc[rb_mask & (df['qb_tier'] == 1), 'box_stack_risk'] = 0.5

    # --- WR CORPS QUALITY → affects QB ---
    # Good WRs make QBs better. Compute team WR production.
    wr_quality = df[df['position'] == 'WR'].groupby(['team', 'season']).agg(
        wr_total_pts=('fantasy_points', 'sum'),
        wr_top_pts=('fantasy_points', 'max'),
        wr_count=('player_id', 'count'),
    ).reset_index()

    if len(wr_quality):
        wr_quality['wr_corps_rank'] = wr_quality.groupby('season')['wr_total_pts'].rank(ascending=False)
        df = df.merge(wr_quality[['team', 'season', 'wr_total_pts', 'wr_corps_rank']],
                      on=['team', 'season'], how='left', suffixes=('', '_wrdep'))
        for c in ['wr_total_pts', 'wr_corps_rank']:
            if c in df.columns:
                df[c] = df[c].fillna(df[c].median())

    # --- TARGET CONCENTRATION ---
    # Is one WR dominating targets? High concentration = that WR is safer
    if 'target_share' in df.columns:
        team_conc = df[df['position'].isin(['WR', 'TE'])].groupby(['team', 'season']).agg(
            target_concentration=('target_share', 'max'),  # Highest share on team
        ).reset_index()
        df = df.merge(team_conc, on=['team', 'season'], how='left')
        if 'target_concentration' in df.columns:
            df['target_concentration'] = df['target_concentration'].fillna(0)

    # --- LAG the dependency features (can't use current year to predict current year) ---
    dep_cols = ['qb_fppg', 'qb_quality_rank', 'qb_tier', 'box_stack_risk',
                'wr_total_pts', 'wr_corps_rank', 'target_concentration']
    for c in dep_cols:
        if c in df.columns and 'season' in df.columns and 'player_id' in df.columns:
            lag_col = f'{c}_lag1'
            # For teammate features, lag by team-position (not player)
            # The QB quality last year is what we know going into this year
            df[lag_col] = df.groupby(['team', 'position'])[c].shift(1)
            df[lag_col] = df[lag_col].fillna(df[c].median())

    return df


def compute_playmaker_features(df: pd.DataFrame) -> pd.DataFrame:
    """Individual playmaker ability features — how good is this player at creating value?

    Some players create their own value (YAC monsters, break tackles),
    while others are dependent (deep threats who need a good QB to throw it far).

    Features:
    - racr: Receiver Air Conversion Ratio — how efficient are they with their air yards?
    - yac_share: Yards After Catch share — playmakers create their own yards
    - domination_score: How much does this player dominate their team's passing game?
    - wopr: Weighted Opportunity Rating — combines target share + air yards share
    - efficiency: Points per opportunity (touches/targets)
    """
    df = df.copy()

    # These advanced metrics come from nfl_data_py seasonal data
    # They're already in the dataframe if the seasonal data included them

    # RACR (Receiver Air Conversion Ratio)
    # Higher = more efficient with air yards = less dependent on QB
    if 'racr' in df.columns:
        df['racr'] = pd.to_numeric(df['racr'], errors='coerce')
        df['racr'] = df['racr'].fillna(df['racr'].median())
    else:
        # Compute from available data
        if 'receiving_yards' in df.columns and 'receiving_air_yards' in df.columns:
            air = df['receiving_air_yards'].clip(lower=1)
            df['racr'] = (df['receiving_yards'] / air).fillna(0).clip(0, 2)

    # YAC share — playmakers create their own yards after the catch
    if 'yac_sh' in df.columns:
        df['yac_sh'] = pd.to_numeric(df['yac_sh'], errors='coerce')
        df['yac_sh'] = df['yac_sh'].fillna(df['yac_sh'].median())

    # Domination score — how much of team's receiving production comes from this player
    if 'dom' in df.columns:
        df['dom'] = pd.to_numeric(df['dom'], errors='coerce')
        df['dom'] = df['dom'].fillna(df['dom'].median())
    elif 'w8dom' in df.columns:
        df['dom'] = pd.to_numeric(df['w8dom'], errors='coerce')
        df['dom'] = df['dom'].fillna(df['dom'].median())

    # WOPR — weighted opportunity (target share + 0.5 * air yards share)
    if 'wopr_x' in df.columns:
        df['wopr'] = pd.to_numeric(df['wopr_x'], errors='coerce')
        df['wopr'] = df['wopr'].fillna(df['wopr'].median())

    # Efficiency: fantasy points per touch/target
    if 'fantasy_points' in df.columns:
        if 'rushing_attempts' in df.columns and 'targets' in df.columns:
            opportunities = df['rushing_attempts'].fillna(0) + df['targets'].fillna(0)
            df['pts_per_opportunity'] = (df['fantasy_points'] / opportunities.clip(lower=1)).fillna(0).clip(0, 3)

        # Points per target (for WR/TE)
        if 'targets' in df.columns:
            df['pts_per_target'] = (df['fantasy_points'] / df['targets'].clip(lower=1)).fillna(0).clip(0, 5)

        # Points per carry (for RB)
        if 'rushing_attempts' in df.columns:
            df['pts_per_carry'] = (df['fantasy_points'] / df['rushing_attempts'].clip(lower=1)).fillna(0).clip(0, 5)

    # Lag playmaker features (can't use current year to predict)
    play_cols = ['racr', 'yac_sh', 'dom', 'wopr', 'pts_per_opportunity', 'pts_per_target', 'pts_per_carry']
    for c in play_cols:
        if c in df.columns and 'player_id' in df.columns:
            lag_col = f'{c}_lag1'
            df[lag_col] = df.groupby('player_id')[c].shift(1)
            df[lag_col] = df[lag_col].fillna(df[c].median())

    return df


def compute_advanced_stat_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Lag nflverse advanced efficiency/usage stats.

    These source columns describe the current season, so the model should only
    receive prior-season values. Missing values are expected for rookies and
    players without prior qualifying usage.
    """
    df = df.copy()
    df["_advanced_lag_order"] = np.arange(len(df))
    df = df.sort_values(["player_id", "season"])

    advanced_cols = [
        "passing_epa", "passing_cpoe", "pacr", "passing_air_yards",
        "passing_yards_after_catch", "passing_first_downs",
        "rushing_epa", "rushing_first_downs",
        "receiving_epa", "receiving_air_yards", "receiving_yards_after_catch",
        "receiving_first_downs", "air_yards_share",
    ]

    for c in advanced_cols:
        if c in df.columns:
            lag_col = f"{c}_lag1"
            df[lag_col] = df.groupby("player_id")[c].shift(1)
            df[lag_col] = df[lag_col].fillna(0)

    df = df.sort_values("_advanced_lag_order").drop(columns=["_advanced_lag_order"])
    return df


def _weighted_average(group: pd.DataFrame, value_col: str, weight_col: str) -> float:
    values = pd.to_numeric(group[value_col], errors="coerce")
    weights = pd.to_numeric(group[weight_col], errors="coerce").fillna(0)
    valid = values.notna() & (weights > 0)
    if valid.any():
        return float(np.average(values[valid], weights=weights[valid]))
    if values.notna().any():
        return float(values.mean())
    return 0.0


def _aggregate_ngs_stat(stat_df: pd.DataFrame, stat_type: str) -> pd.DataFrame:
    """Aggregate weekly NGS rows to one player-season row."""
    if stat_df is None or stat_df.empty or "season" not in stat_df.columns:
        return pd.DataFrame()

    df = stat_df.copy()
    if "season_type" in df.columns:
        df = df[df["season_type"] == "REG"].copy()
    if df.empty:
        return pd.DataFrame()

    id_col = "player_gsis_id" if "player_gsis_id" in df.columns else None
    if id_col is None:
        return pd.DataFrame()

    group_cols = [id_col, "season"]
    if stat_type == "passing":
        weight_col = "attempts"
        features = [
            "avg_time_to_throw",
            "avg_completed_air_yards",
            "avg_intended_air_yards",
            "avg_air_yards_differential",
            "aggressiveness",
            "avg_air_yards_to_sticks",
            "completion_percentage_above_expectation",
        ]
    elif stat_type == "rushing":
        weight_col = "rush_attempts"
        features = [
            "efficiency",
            "percent_attempts_gte_eight_defenders",
            "avg_time_to_los",
            "expected_rush_yards",
            "rush_yards_over_expected",
            "rush_yards_over_expected_per_att",
            "rush_pct_over_expected",
        ]
    elif stat_type == "receiving":
        weight_col = "targets"
        features = [
            "avg_cushion",
            "avg_separation",
            "avg_intended_air_yards",
            "percent_share_of_intended_air_yards",
            "catch_percentage",
            "avg_yac",
            "avg_expected_yac",
            "avg_yac_above_expectation",
        ]
    else:
        return pd.DataFrame()

    features = [c for c in features if c in df.columns]
    if not features:
        return pd.DataFrame()
    if weight_col not in df.columns:
        df[weight_col] = 1

    rows = []
    for keys, group in df.groupby(group_cols, dropna=False):
        player_id, season = keys
        row = {"player_id": player_id, "season": season}
        for col in features:
            row[f"ngs_{stat_type}_{col}"] = _weighted_average(group, col, weight_col)
        rows.append(row)

    return pd.DataFrame(rows)


def compute_ngs_lag_features(
    df: pd.DataFrame,
    ngs_data: Optional[dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Merge prior-season Next Gen Stats aggregates.

    NGS rows are current-season weekly observations, so this function first
    aggregates each player-season, shifts the season by +1, and then merges.
    A 2025 NGS value can therefore feed 2026 projections, but 2025 validation
    never sees 2025 NGS.
    """
    if not ngs_data:
        return df
    out = df.copy()
    if "player_id" not in out.columns or "season" not in out.columns:
        return out

    merged = []
    for stat_type in ["passing", "rushing", "receiving"]:
        stat_df = ngs_data.get(stat_type)
        agg = _aggregate_ngs_stat(stat_df, stat_type)
        if agg.empty:
            continue
        feature_cols = [c for c in agg.columns if c not in {"player_id", "season"}]
        agg["season"] = agg["season"] + 1
        agg = agg.rename(columns={c: f"{c}_lag1" for c in feature_cols})
        merged.append(agg)

    for agg in merged:
        out = out.merge(agg, on=["player_id", "season"], how="left")

    ngs_cols = [c for c in out.columns if c.startswith("ngs_") and c.endswith("_lag1")]
    for col in ngs_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    return out


def compute_snap_lag_features(
    df: pd.DataFrame,
    snap_df: Optional[pd.DataFrame] = None,
    roster_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Merge prior-season offensive snap usage.

    Snap counts are current-season role data, so raw season snaps cannot be
    used to predict that same season. We aggregate regular-season snaps by
    player-season, shift the season by +1, and merge those lagged values.
    """
    if snap_df is None or snap_df.empty:
        return df
    out = df.copy()
    if "player_id" not in out.columns or "season" not in out.columns:
        return out

    snaps = snap_df.copy()
    if "game_type" in snaps.columns:
        snaps = snaps[snaps["game_type"] == "REG"].copy()
    if snaps.empty or "season" not in snaps.columns:
        return out

    if "player_id" not in snaps.columns:
        if "pfr_player_id" not in snaps.columns or roster_df is None or roster_df.empty:
            return out
        if "pfr_id" not in roster_df.columns or "player_id" not in roster_df.columns:
            return out
        roster_map_cols = ["pfr_id", "player_id"]
        if "season" in roster_df.columns:
            roster_map_cols.append("season")
        roster_map = (
            roster_df[roster_map_cols]
            .dropna(subset=["pfr_id", "player_id"])
            .drop_duplicates(roster_map_cols)
        )
        if "season" in roster_map.columns:
            snaps = snaps.merge(
                roster_map.rename(columns={"pfr_id": "pfr_player_id"}),
                on=["pfr_player_id", "season"],
                how="left",
            )
        else:
            snaps = snaps.merge(
                roster_map.rename(columns={"pfr_id": "pfr_player_id"}),
                on="pfr_player_id",
                how="left",
            )

    if "player_id" not in snaps.columns:
        return out

    for col in ["offense_snaps", "offense_pct"]:
        if col not in snaps.columns:
            snaps[col] = 0
        snaps[col] = pd.to_numeric(snaps[col], errors="coerce").fillna(0)

    snap_agg = (
        snaps.dropna(subset=["player_id"])
        .groupby(["player_id", "season"])
        .agg(
            snap_offense_snaps=("offense_snaps", "sum"),
            snap_offense_pct=("offense_pct", "mean"),
            snap_games=("week", "nunique") if "week" in snaps.columns else ("offense_snaps", "size"),
        )
        .reset_index()
    )
    if snap_agg.empty:
        return out

    snap_agg["snap_offense_snaps_per_game"] = (
        snap_agg["snap_offense_snaps"] / snap_agg["snap_games"].replace(0, np.nan)
    ).fillna(0)
    snap_feature_cols = [c for c in snap_agg.columns if c not in {"player_id", "season"}]
    snap_agg["season"] = snap_agg["season"] + 1
    snap_agg = snap_agg.rename(columns={c: f"{c}_lag1" for c in snap_feature_cols})

    out = out.merge(snap_agg, on=["player_id", "season"], how="left")
    for col in [c for c in out.columns if c.startswith("snap_") and c.endswith("_lag1")]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def compute_availability_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Prior-season games-played trend features.

    These use only completed prior seasons for each player. They help separate
    durable full-season roles from players whose one-year per-game production
    came on limited availability.
    """
    if "player_id" not in df.columns or "season" not in df.columns or "games" not in df.columns:
        return df

    out = df.copy()
    out["_availability_order"] = np.arange(len(out))
    out = out.sort_values(["player_id", "season"])
    games = pd.to_numeric(out["games"], errors="coerce").fillna(0)
    out["_games_numeric"] = games

    out["games_lag1"] = out.groupby("player_id")["_games_numeric"].shift(1).fillna(0)
    out["games_lag2"] = out.groupby("player_id")["_games_numeric"].shift(2).fillna(0)
    out["games_roll2"] = out.groupby("player_id")["_games_numeric"].transform(
        lambda x: x.shift(1).rolling(2, min_periods=1).mean()
    ).fillna(0)
    out["games_roll3"] = out.groupby("player_id")["_games_numeric"].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).mean()
    ).fillna(0)
    out["missed_games_lag1"] = (17 - out["games_lag1"]).clip(lower=0)
    out["missed_games_roll2"] = (17 - out["games_roll2"]).clip(lower=0)
    out["played_15plus_lag1"] = (out["games_lag1"] >= 15).astype(int)

    out = out.sort_values("_availability_order").drop(columns=["_availability_order", "_games_numeric"])
    return out


def compute_pfr_lag_features(
    df: pd.DataFrame,
    pfr_df: Optional[pd.DataFrame] = None,
    roster_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Merge prior-season Pro Football Reference advanced stats.

    PFR advanced rows are current-season player stats, so every feature is
    shifted to the following season before merging. The source is keyed by
    PFR id; roster data provides the PFR id to player_id bridge.
    """
    if pfr_df is None or pfr_df.empty:
        return df
    out = df.copy()
    if "player_id" not in out.columns or "season" not in out.columns:
        return out
    if "pfr_id" not in pfr_df.columns or "season" not in pfr_df.columns:
        return out
    if roster_df is None or roster_df.empty or "pfr_id" not in roster_df.columns or "player_id" not in roster_df.columns:
        return out

    roster_cols = ["pfr_id", "player_id"]
    if "season" in roster_df.columns:
        roster_cols.append("season")
    roster_map = (
        roster_df[roster_cols]
        .dropna(subset=["pfr_id", "player_id"])
        .drop_duplicates(roster_cols)
    )

    pfr = pfr_df.copy()
    if "pfr_stat_type" not in pfr.columns:
        pfr["pfr_stat_type"] = ""
    if "season" in roster_map.columns:
        pfr = pfr.merge(roster_map, on=["pfr_id", "season"], how="left")
    else:
        pfr = pfr.merge(roster_map, on="pfr_id", how="left")
    pfr = pfr.dropna(subset=["player_id"]).copy()
    if pfr.empty:
        return out

    stat_features = {
        "pass": [
            "pocket_time",
            "drop_pct",
            "bad_throw_pct",
            "pressure_pct",
            "on_tgt_pct",
            "intended_air_yards_per_pass_attempt",
            "completed_air_yards_per_pass_attempt",
            "pass_yards_after_catch_per_completion",
            "scramble_yards_per_attempt",
        ],
        "rush": ["gs", "x1d", "ybc_att", "yac_att", "brk_tkl", "att_br"],
        "rec": ["gs", "x1d", "ybc_r", "yac_r", "adot", "brk_tkl", "rec_br", "drop_percent", "rat"],
    }

    merged = []
    for stat_type, cols in stat_features.items():
        sub = pfr[pfr["pfr_stat_type"] == stat_type].copy()
        cols = [c for c in cols if c in sub.columns]
        if sub.empty or not cols:
            continue
        for col in cols:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
        agg = sub.groupby(["player_id", "season"])[cols].mean().reset_index()
        agg["season"] = agg["season"] + 1
        agg = agg.rename(columns={c: f"pfr_{stat_type}_{c}_lag1" for c in cols})
        merged.append(agg)

    for agg in merged:
        out = out.merge(agg, on=["player_id", "season"], how="left")

    pfr_cols = [c for c in out.columns if c.startswith("pfr_") and c.endswith("_lag1")]
    for col in pfr_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def compute_adp_features(df: pd.DataFrame, adp_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Add ADP (Average Draft Position) as a feature.

    ADP is the single best predictor of fantasy value — it aggregates
    thousands of real drafts. If our model disagrees strongly with ADP,
    that's a signal to investigate.

    Matching strategy (cascading from most to least specific):
    1. football_name + last_name + position + season (e.g., "A.J. Brown" not "Arthur Brown")
    2. first_name + last_name + position + season (legal name fallback)
    3. first_initial + last_name + position + team + season (disambiguates same-last-name-same-team)
    4. last_name + position + team + season
    5. last_name + position + season (no team; catches FAs and team changes)

    Features:
    - adp: current ADP rank (200 = undrafted/unmatched)
    - adp_tier: binned ADP (1-12, 13-24, 25-48, 49+)
    """
    if adp_df is None or adp_df.empty:
        return df

    df = df.copy()
    adp_df_full = adp_df.copy()

    # Normalize team abbreviations in both
    from src.data.clean import normalize_teams
    adp_df_full = normalize_teams(adp_df_full)
    if "team" in df.columns:
        df = normalize_teams(df)

    has_season = "season" in df.columns and "season" in adp_df_full.columns

    def _norm(s):
        """Normalize a name/token: lowercase, strip suffixes/single-letter tokens, remove special chars."""
        if isinstance(s, pd.Series):
            s = s.astype(str).str.lower().str.strip()
            # Strip trailing single-letter tokens (FantasyPros " O", " Q" injury flags)
            s = s.str.replace(r"\s+[a-z]$", "", regex=True)
            # Strip Jr/Sr/III suffixes
            s = s.str.replace(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", regex=True)
            s = s.str.replace("'", "", regex=False).str.replace("-", "", regex=False)
            s = s.str.replace(".", "", regex=False)
            return s
        s = str(s).lower().strip()
        import re as _re
        s = _re.sub(r"\s+[a-z]$", "", s)
        s = _re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", s)
        return s.replace("'", "").replace("-", "").replace(".", "")

    def _get_last(name):
        """Extract last meaningful name token (strip Jr/Sr/III)."""
        parts = str(name).split()
        suffixes = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}
        while parts and parts[-1].lower().rstrip(".") in suffixes:
            parts = parts[:-1]
        return _norm(parts[-1]) if parts else ""

    def _get_first_initial(name):
        """First letter of first name token."""
        parts = str(name).split()
        return _norm(parts[0])[:1] if parts else ""

    # Initialize ADP column; we'll fill via cascading strategies.
    # Use 999 as "not yet matched" sentinel so real ADP values >200 (FantasyPros
    # has ranks up to ~300 for deep leagues) aren't confused with "unmatched".
    if "adp" not in df.columns:
        df["adp"] = 999.0
    else:
        df["adp"] = df["adp"].fillna(999)

    adp_clean = adp_df_full.dropna(subset=["adp"]).copy()
    adp_clean["_full"] = _norm(adp_clean["player_name"])
    adp_clean["_last"] = adp_clean["player_name"].apply(_get_last)
    adp_clean["_first_init"] = adp_clean["player_name"].apply(_get_first_initial)

    # Precompute df keys
    df["_last"] = _norm(df["last_name"]) if "last_name" in df.columns else ""
    if "football_name" in df.columns and df["football_name"].notna().any():
        df["_full_football"] = _norm(df["football_name"].fillna("").str.strip() + " " + df["last_name"].fillna("").str.strip())
        df["_fi_football"] = _norm(df["football_name"].fillna("")).str[:1]
    else:
        df["_full_football"] = ""
        df["_fi_football"] = ""
    if "first_name" in df.columns:
        df["_full_legal"] = _norm(df["first_name"].fillna("").str.strip() + " " + df["last_name"].fillna("").str.strip())
        df["_fi_legal"] = _norm(df["first_name"].fillna("")).str[:1]
    else:
        df["_full_legal"] = ""
        df["_fi_legal"] = ""

    def _apply_strategy(df, adp_map, match_cols_df, match_cols_adp, label):
        """Merge ADP values into df where df[match_cols_df] == adp[match_cols_adp] and still unmatched (sentinel 999)."""
        mask_unmatched = df["adp"] >= 999
        if not mask_unmatched.any():
            return df, 0
        # Build lookup
        adp_sub = adp_map.rename(columns=dict(zip(match_cols_adp, match_cols_df)))
        adp_sub = adp_sub.drop_duplicates(subset=match_cols_df, keep="first")
        # Exclude empty keys
        for c in match_cols_df:
            adp_sub = adp_sub[adp_sub[c].astype(str).str.len() > 0]
        df = df.merge(adp_sub[match_cols_df + ["adp"]].rename(columns={"adp": f"_adp_{label}"}), on=match_cols_df, how="left")
        fill_mask = (df["adp"] >= 999) & df[f"_adp_{label}"].notna()
        filled = int(fill_mask.sum())
        df.loc[fill_mask, "adp"] = df.loc[fill_mask, f"_adp_{label}"]
        df = df.drop(columns=[f"_adp_{label}"])
        return df, filled

    total_filled = 0

    # Strategy 1: football_name full + position + season
    if "_full_football" in df.columns:
        cols_df = ["_full_football", "position"] + (["season"] if has_season else [])
        cols_adp = ["_full", "position"] + (["season"] if has_season else [])
        # Drop ambiguous football_name duplicates in ADP
        adp_map = adp_clean.copy()
        dup = adp_map.groupby(cols_adp).size()
        bad = set(dup[dup > 1].index)
        adp_map = adp_map[~adp_map.set_index(cols_adp).index.isin(bad)]
        df, n = _apply_strategy(df, adp_map, cols_df, cols_adp, "s1")
        total_filled += n

    # Strategy 2 (DISABLED): legal first_name + last_name full match.
    # Testing showed this adds noisy matches (players where roster first_name differs
    # from ADP but football_name already failed) that hurt WR walk-forward MAE.
    # Strategy 1 (football_name) alone gives the best walk-forward results.

    # Strategy 3 (DISABLED for now to isolate impact):
    # first_initial + last_name + position + team + season
    # Would resolve same-last-name same-team like A.J. Brown + Hollywood Brown on PHI.
    # Currently Strategy 1 handles A.J. via football_name, so this is redundant except for
    # edge cases. Testing showed TE regression when enabled.

    # Strategy 4 (DISABLED): last_name + position + team + season.
    # Walk-forward testing showed this over-matches; Strategies 1+2 (name-based)
    # give better model performance because they rely on exact name rather than
    # last-name + team heuristics that can mis-match in edge cases.

    # Strategy 5 (DISABLED): last_name + position + season without team was creating
    # false positives (wrong player matched to similar last-name). Prefer leaving
    # a player unmatched (adp=200) than assigning the wrong ADP. Top-ADP players
    # are already covered by strategies 1-4 which all require team match or exact name.

    # Cleanup helper cols
    df = df.drop(columns=[c for c in ["_last", "_full_football", "_full_legal", "_fi_football", "_fi_legal"] if c in df.columns], errors="ignore")

    # Finalize: unmatched sentinel 999 → fill 200 and clip at 200 (backward compatible
    # with existing models trained on adp<=200). We preserve the matching improvements
    # but compress real ADP ranks 200-300 back to 200 as "late / undrafted".
    df["adp"] = df["adp"].where(df["adp"] < 999, 200).clip(upper=200)
    df["adp_tier"] = pd.cut(
        df["adp"], bins=[0, 12, 24, 48, 100, 300],
        labels=[1, 2, 3, 4, 5],
    ).astype(float).fillna(5)

    # Market-shape features. These use only current draft price plus already
    # lagged production/age fields, so they are safe for preseason projection.
    df["adp_log"] = np.log1p(df["adp"])
    df["adp_inverse"] = 1 / df["adp"].clip(lower=1)
    df["is_top12_adp"] = (df["adp"] <= 12).astype(int)
    df["is_top24_adp"] = (df["adp"] <= 24).astype(int)
    df["is_top48_adp"] = (df["adp"] <= 48).astype(int)
    df["is_late_or_undrafted_adp"] = (df["adp"] >= 150).astype(int)

    pts_lag = pd.to_numeric(df["pts_lag1"], errors="coerce").fillna(0) if "pts_lag1" in df.columns else 0
    fp_pg_lag = pd.to_numeric(df["fp_per_game_lag1"], errors="coerce").fillna(0) if "fp_per_game_lag1" in df.columns else 0
    age = pd.to_numeric(df["age"], errors="coerce").fillna(0) if "age" in df.columns else 0
    df["adp_minus_pts_lag1"] = df["adp"] - pts_lag
    df["pts_lag1_per_adp"] = pts_lag / df["adp"].clip(lower=1)
    df["fp_per_game_lag1_per_adp"] = fp_pg_lag / df["adp"].clip(lower=1)
    df["age_x_adp"] = age * df["adp"]

    return df


def compute_injury_features(df: pd.DataFrame, injury_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Add injury history features — key for risk assessment.

    Features:
    - injury_count_prior: number of injuries in prior seasons
    - major_injury_flag: had a season-ending injury (IR, Out 4+ weeks)
    - games_lost_to_injury: estimated games missed
    """
    if injury_df is None or injury_df.empty:
        return df

    df = df.copy()

    # Aggregate injuries per player per season
    # Injury data uses gsis_id, roster uses player_id — they're the same namespace
    if "season" in injury_df.columns:
        # Normalize ID column to player_id
        inj_clean = injury_df.copy()
        if "player_id" not in inj_clean.columns and "gsis_id" in inj_clean.columns:
            inj_clean = inj_clean.rename(columns={"gsis_id": "player_id"})

        if "player_id" in inj_clean.columns:
            inj_agg = inj_clean.groupby(["player_id", "season"]).agg(
                injury_count=("report_primary_injury", "count"),
                games_missed=("report_status", lambda x: x.isin(["Out", "IR"]).sum()),
            ).reset_index()

            # Lag by 1 season (prior year injuries)
            inj_agg = inj_agg.sort_values(["player_id", "season"])
            inj_agg["injury_count_lag1"] = inj_agg.groupby("player_id")["injury_count"].shift(1)
            inj_agg["games_missed_lag1"] = inj_agg.groupby("player_id")["games_missed"].shift(1)

            # Rolling injury count
            inj_agg["injury_count_roll3"] = inj_agg.groupby("player_id")["injury_count"].transform(
                lambda x: x.shift(1).rolling(3, min_periods=1).sum()
            )

            inj_sub = inj_agg[["player_id", "season", "injury_count_lag1", "games_missed_lag1", "injury_count_roll3"]]

            if "season" in df.columns:
                df = df.merge(inj_sub, on=["player_id", "season"], how="left")
                for c in ["injury_count_lag1", "games_missed_lag1", "injury_count_roll3"]:
                    if c in df.columns:
                        df[c] = df[c].fillna(0)

    return df


def compute_career_arc_features(df: pd.DataFrame) -> pd.DataFrame:
    """Career arc features — model the rise/peak/decline pattern.

    Key insight: fantasy production follows a predictable arc by position.
    QBs peak late (27-33), RBs peak early and decline fast (23-27),
    WRs have a longer prime (24-29), TEs peak latest (25-30).
    """
    df = df.copy()

    if "age" not in df.columns or "position" not in df.columns:
        return df

    prime_ages = {"QB": 30, "RB": 25, "WR": 26, "TE": 27}

    def years_from_prime(row):
        pos = row.get("position", "")
        age = row.get("age", 0)
        peak = prime_ages.get(pos, 27)
        return age - peak  # negative = pre-prime, positive = post-prime

    df["years_from_prime"] = df.apply(years_from_prime, axis=1)
    df["years_from_prime_sq"] = df["years_from_prime"] ** 2

    # Career phase dummies
    df["is_pre_prime"] = (df["years_from_prime"] < -2).astype(int)
    df["is_prime_age"] = (df["years_from_prime"].between(-2, 2)).astype(int)
    df["is_post_prime"] = (df["years_from_prime"] > 2).astype(int)

    # RB cliff: RBs over 28 are historically much worse
    df["rb_age_risk"] = 0
    rb_mask = df["position"] == "RB"
    df.loc[rb_mask & (df["age"] >= 28), "rb_age_risk"] = 1
    df.loc[rb_mask & (df["age"] >= 30), "rb_age_risk"] = 2

    return df


def compute_lag_features(df: pd.DataFrame, stat_cols: list[str], lags: list[int] = [1, 2]) -> pd.DataFrame:
    """Year-over-year lag features: {stat}_lag1, {stat}_lag2."""
    df = df.copy().sort_values(["player_id", "season"])

    for col in stat_cols:
        if col not in df.columns:
            continue
        for lag in lags:
            df[f"{col}_lag{lag}"] = df.groupby("player_id")[col].shift(lag)

    return df


def compute_rolling_features(df: pd.DataFrame, stat_cols: list[str], windows: list[int] = [3]) -> pd.DataFrame:
    """Rolling averages over past seasons for specified stats."""
    df = df.copy().sort_values(["player_id", "season"])

    for col in stat_cols:
        if col not in df.columns:
            continue
        for w in windows:
            df[f"{col}_roll{w}"] = df.groupby("player_id")[col].transform(
                lambda x: x.shift(1).rolling(w, min_periods=1).mean()
            )

    return df


def build_feature_matrix(
    seasonal_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    team_df: pd.DataFrame,
    ol_df: pd.DataFrame,
    snap_df: Optional[pd.DataFrame] = None,
    schedule_df: Optional[pd.DataFrame] = None,
    ngs_data: Optional[dict[str, pd.DataFrame]] = None,
    pfr_df: Optional[pd.DataFrame] = None,
    lag_stats: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Build complete feature matrix from all data sources."""
    df = merge_player_context(seasonal_df, roster_df, team_df, ol_df)

    df = compute_ol_rb_features(df)
    df = compute_qb_wr_features(df)
    df = compute_age_experience_features(df)
    df = compute_volume_features(df)
    df = compute_career_arc_features(df)
    df = compute_rookie_features(df)
    df = compute_sos_features(df, team_df, full_seasonal_df=seasonal_df)
    df = compute_schedule_sos_features(df, schedule_df, full_seasonal_df=seasonal_df)
    df = compute_playmaker_features(df)
    df = compute_advanced_stat_lag_features(df)
    df = compute_ngs_lag_features(df, ngs_data)
    df = compute_snap_lag_features(df, snap_df, roster_df=roster_df)
    df = compute_availability_lag_features(df)
    df = compute_pfr_lag_features(df, pfr_df, roster_df=roster_df)

    if lag_stats is None:
        lag_stats = [
            "rushing_yards", "rushing_tds", "rushing_attempts",
            "receiving_yards", "receiving_tds",
            "passing_yards", "passing_tds", "targets", "receptions",
            "interceptions", "attempts", "completions",
        ]
    df = compute_lag_features(df, lag_stats)
    df = compute_rolling_features(df, lag_stats)

    # Regression features (computed after scoring if fantasy_points exists)
    # Otherwise called separately after scoring
    if any(c in df.columns for c in ["fantasy_points", "fantasy_points_half_ppr", "fantasy_points_ppr"]):
        df = compute_regression_to_mean_features(df)

    if "position" in df.columns:
        df = df[df["position"].notna()]

    return df.reset_index(drop=True)


def get_feature_columns(df: pd.DataFrame, exclude_cols: Optional[list[str]] = None) -> list[str]:
    """Return list of feature column names, excluding IDs, targets, and metadata."""
    default_exclude = {
        "player_id", "player_name", "team", "season", "position",
        "fantasy_points", "fantasy_points_per_game",
        "fantasy_points_standard", "fantasy_points_half_ppr", "fantasy_points_ppr",
        "player_display_name", "first_name", "last_name", "football_name",
    }
    if exclude_cols:
        default_exclude.update(exclude_cols)

    return [c for c in df.columns if c not in default_exclude and df[c].dtype in [np.float64, np.int64, float, int]]
