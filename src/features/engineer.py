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
    if "player_id" in roster_df.columns and "player_id" in df.columns:
        roster_cols = ["player_id", "position", "age", "team"]
        for c in ["player_name", "football_name", "first_name", "last_name"]:
            if c in roster_df.columns and c not in roster_cols:
                roster_cols.append(c)
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

    if "team_rush_td_rate" in df.columns and "rushing_tds" in df.columns:
        team_rush_tds = df.groupby(["team", "season"])["rushing_tds"].transform("sum")
        df["rb_share_of_team_rush_td"] = df["rushing_tds"] / team_rush_tds.replace(0, np.nan)
        df["rb_share_of_team_rush_td"] = df["rb_share_of_team_rush_td"].fillna(0)

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

    # Fill NaN
    for c in ["yoy_change", "yoy_pct_change", "regression_risk", "is_breakout", "is_bust",
              "pts_roll2", "rush_td_rate_lag1", "rec_td_rate_lag1",
              "fp_per_game", "fp_per_game_lag1", "games_lag1", "fp_adj_17games_lag1",
              "is_bust_injury_adj", "regression_risk_injury_adj", "is_injury_bounce_back",
              "yoy_change_injury_adj", "yoy_pct_change_injury_adj"]:
        if c in df.columns:
            df[c] = df[c].fillna(0)

    return df


def compute_sos_features(df: pd.DataFrame, team_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Strength of Schedule features — who you face matters.

    Features:
    - sos_defensive_rank: how good the opposing defenses are (lower = harder schedule)
    - sos_pass_def: pass defense quality faced
    - sos_rush_def: rush defense quality faced
    """
    if team_df is None or team_df.empty:
        return df

    df = df.copy()

    # Use team defensive stats if available
    def_cols = [c for c in team_df.columns if any(k in c.lower() for k in ['def', 'opp', 'allow', 'sack', 'int'])]
    if not def_cols or 'team' not in team_df.columns:
        return df

    # Compute defensive strength per team
    # Lower points allowed = better defense = harder for our players
    if 'opp_score' in team_df.columns and 'season' in team_df.columns:
        # Average points allowed by each team's defense
        def_strength = team_df.groupby(['team', 'season'])['opp_score'].mean().reset_index()
        def_strength = def_strength.rename(columns={'opp_score': 'def_pts_allowed'})
        # Rank: lower pts allowed = better defense = rank 1
        def_strength['def_rank'] = def_strength.groupby('season')['def_pts_allowed'].rank(ascending=True)

        if 'season' in df.columns:
            df = df.merge(def_strength[['team', 'season', 'def_pts_allowed', 'def_rank']],
                          on=['team', 'season'], how='left', suffixes=('', '_def'))
            for c in ['def_pts_allowed', 'def_rank']:
                if c in df.columns:
                    df[c] = df[c].fillna(df[c].median() if c in df.columns else 16)

    # Pass/rush defense splits if available
    if 'opp_pass_yds' in team_df.columns and 'season' in team_df.columns:
        pass_def = team_df.groupby(['team', 'season'])['opp_pass_yds'].mean().reset_index()
        pass_def = pass_def.rename(columns={'opp_pass_yds': 'def_pass_yds_allowed'})
        pass_def['pass_def_rank'] = pass_def.groupby('season')['def_pass_yds_allowed'].rank(ascending=True)
        if 'season' in df.columns:
            df = df.merge(pass_def[['team', 'season', 'pass_def_rank']],
                          on=['team', 'season'], how='left', suffixes=('', '_pass'))
            if 'pass_def_rank' in df.columns:
                df['pass_def_rank'] = df['pass_def_rank'].fillna(16)

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
    """
    df = df.copy()

    if 'team' not in df.columns or 'position' not in df.columns or 'season' not in df.columns:
        return df

    # Compute QB fantasy points per team per season
    qb_pts = df[df['position'] == 'QB'].groupby(['team', 'season'])['fantasy_points'].mean().reset_index()
    qb_pts = qb_pts.rename(columns={'fantasy_points': 'team_qb_avg_pts'})

    df = df.merge(qb_pts, on=['team', 'season'], how='left')

    # Flag: is this player on the same team as a high-scoring QB?
    if 'team_qb_avg_pts' in df.columns:
        df['team_qb_avg_pts'] = df['team_qb_avg_pts'].fillna(0)
        df['qb_stack_bonus'] = 0
        # WR/TE on same team as elite QB get a bonus
        pass_catchers = df['position'].isin(['WR', 'TE'])
        df.loc[pass_catchers, 'qb_stack_bonus'] = (
            df.loc[pass_catchers, 'team_qb_avg_pts'] > df.loc[pass_catchers, 'team_qb_avg_pts'].quantile(0.75)
        ).astype(int)

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


def compute_adp_features(df: pd.DataFrame, adp_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Add ADP (Average Draft Position) as a feature.

    ADP is the single best predictor of fantasy value — it aggregates
    thousands of real drafts. If our model disagrees strongly with ADP,
    that's a signal to investigate.

    Features:
    - adp: current ADP rank
    - adp_tier: binned ADP (1-12, 13-24, 25-48, 49+)
    - model_vs_adp: how far our projection rank differs from ADP
    """
    if adp_df is None or adp_df.empty:
        return df

    df = df.copy()
    adp_clean = adp_df.dropna(subset=["adp"]).copy()

    # Strategy 1: Match on full name (first_name + last_name from roster)
    # ADP uses full names like "Ja'Marr Chase", seasonal uses abbreviated "J.Chase"
    # but the roster has first_name and last_name columns
    matched = False
    if "first_name" in df.columns and "last_name" in df.columns:
        # Normalize names for matching: strip suffixes, remove apostrophes/hyphens
        def _norm_name(s):
            """Normalize a name string for fuzzy matching."""
            s = s.str.lower().str.strip()
            # Strip common suffixes
            s = s.str.replace(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", regex=True)
            # Remove apostrophes and hyphens (De'Von -> Devon, A.J. -> AJ)
            s = s.str.replace("'", "", regex=False).str.replace("-", "", regex=False)
            # Remove periods from initials (A.J. -> AJ)
            s = s.str.replace(".", "", regex=False)
            return s

        df["_full_name"] = _norm_name(df["first_name"].str.strip() + " " + df["last_name"].str.strip())
        adp_clean["_full_name"] = _norm_name(adp_clean["player_name"])

        adp_key = adp_clean[["_full_name", "adp"]].drop_duplicates("_full_name")
        adp_key = adp_key.rename(columns={"adp": "adp_matched"})

        df = df.merge(adp_key, on="_full_name", how="left")
        match_count = df["adp_matched"].notna().sum()
        if match_count > 20:
            matched = True
            if "adp" in df.columns:
                df["adp"] = df["adp_matched"].fillna(df["adp"])
            else:
                df["adp"] = df["adp_matched"]
            # Fill unmatched with 200 so Strategy 2 can detect them
            df["adp"] = df["adp"].fillna(200)
        df = df.drop(columns=["_full_name", "adp_matched"], errors="ignore")

    # Strategy 2: Supplement — match remaining unmatched on last_name + position + team
    # This catches players where ADP uses nicknames (CeeDee, Dak, DK) that differ
    # from roster legal names (Cedarian, Rayne, DeKaylin)
    if "adp" not in df.columns or df["adp"].isna().all() or (df["adp"] == 200).sum() > 0:
        adp_clean2 = adp_df.dropna(subset=["adp"]).copy()
        # Normalize: strip suffixes from ADP last names too
        adp_clean2["_last"] = adp_clean2["player_name"].str.split().str[-1].str.lower().str.strip()
        # Remove suffixes like Jr, III from last token
        adp_clean2["_last"] = adp_clean2["_last"].str.replace(r"\.(jr|sr|ii|iii|iv|v)$", "", regex=True)

        if "last_name" in df.columns:
            df["_last"] = df["last_name"].str.lower().str.strip()
        elif "player_name" in df.columns:
            df["_last"] = df["player_name"].str.extract(r"\.([A-Za-z'-]+)")[0].str.lower().str.strip()

        if "_last" in df.columns and "position" in df.columns:
            match_cols = ["_last", "position"]
            if "team" in df.columns and "team" in adp_clean2.columns:
                match_cols.append("team")

            adp_key = adp_clean2[match_cols + ["adp"]].drop_duplicates(subset=match_cols)
            # Skip ambiguous matches where ADP has multiple entries for same key
            adp_dup = adp_clean2.groupby(match_cols).size()
            adp_dup_keys = set(adp_dup[adp_dup > 1].index)
            adp_key = adp_key[~adp_key.set_index(match_cols).index.isin(adp_dup_keys)]
            adp_key = adp_key.rename(columns={"adp": "adp_supp"})

            df = df.merge(adp_key, on=match_cols, how="left")
            if "adp_supp" in df.columns:
                if "adp" in df.columns:
                    # Only fill in players that still have default ADP (200) AND have a real match
                    mask = (df["adp"] == 200) & df["adp_supp"].notna()
                    df.loc[mask, "adp"] = df.loc[mask, "adp_supp"]
                else:
                    df["adp"] = df["adp_supp"].fillna(200)
                df = df.drop(columns=["adp_supp"], errors="ignore")
            if "_last" in df.columns:
                df = df.drop(columns=["_last"], errors="ignore")

    # Strategy 3: Match remaining unmatched on last_name + position only (no team)
    # This catches FA players (team="FA" in ADP, different team in roster)
    # and players whose ADP team doesn't match roster team yet
    # IMPORTANT: Skip ambiguous matches where multiple players share last+position
    # (e.g. B.Robinson RB — Brian Robinson vs Bijan Robinson)
    if "adp" in df.columns and (df["adp"] == 200).sum() > 0:
        adp_clean3 = adp_df.dropna(subset=["adp"]).copy()
        # Get the last meaningful name token (strip suffixes)
        def _get_last(name):
            parts = str(name).split()
            # Remove suffix tokens
            suffixes = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}
            while parts and parts[-1].lower().rstrip(".") in suffixes:
                parts = parts[:-1]
            return parts[-1].lower().strip().replace("'", "").replace(".", "").replace("-", "") if parts else ""

        adp_clean3["_last"] = adp_clean3["player_name"].apply(_get_last)

        if "last_name" in df.columns:
            df["_last"] = df["last_name"].str.lower().str.strip().str.replace("'", "", regex=False).str.replace(".", "", regex=False).str.replace("-", "", regex=False)

        if "_last" in df.columns and "position" in df.columns:
            # Find ambiguous last+position combos (multiple players in df with same key)
            dup_keys = df.groupby(["_last", "position"]).size()
            dup_keys = set(dup_keys[dup_keys > 1].index)

            # Only match on last + position (no team constraint)
            # But skip ADP keys that are ambiguous in our dataframe
            adp_key3 = adp_clean3[["_last", "position", "adp"]].drop_duplicates(subset=["_last", "position"])
            # Also skip ADP entries that are ambiguous in ADP itself
            adp_dup = adp_clean3.groupby(["_last", "position"]).size()
            adp_dup_keys = set(adp_dup[adp_dup > 1].index)
            adp_key3 = adp_key3[~adp_key3.set_index(["_last", "position"]).index.isin(adp_dup_keys)]
            # Skip keys that are ambiguous in our dataframe too
            adp_key3 = adp_key3[~adp_key3.set_index(["_last", "position"]).index.isin(dup_keys)]
            adp_key3 = adp_key3.rename(columns={"adp": "adp_fa"})

            df = df.merge(adp_key3, on=["_last", "position"], how="left")
            if "adp_fa" in df.columns:
                # Only fill players still at default ADP
                mask = df["adp"] == 200
                df.loc[mask, "adp"] = df.loc[mask, "adp_fa"]
                df = df.drop(columns=["adp_fa"], errors="ignore")
            if "_last" in df.columns:
                df = df.drop(columns=["_last"], errors="ignore")

    if "adp" in df.columns:
        df["adp"] = df["adp"].fillna(200)  # Undrafted = late ADP
        df["adp_tier"] = pd.cut(
            df["adp"], bins=[0, 12, 24, 48, 100, 300],
            labels=[1, 2, 3, 4, 5],
        ).astype(float).fillna(5)

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
    lag_stats: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Build complete feature matrix from all data sources."""
    df = merge_player_context(seasonal_df, roster_df, team_df, ol_df, snap_df)

    df = compute_ol_rb_features(df)
    df = compute_qb_wr_features(df)
    df = compute_age_experience_features(df)
    df = compute_volume_features(df)
    df = compute_career_arc_features(df)
    df = compute_rookie_features(df)
    df = compute_sos_features(df, team_df)
    df = compute_playmaker_features(df)

    if lag_stats is None:
        lag_stats = [
            "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds",
            "passing_yards", "passing_tds", "targets", "receptions", "rushing_attempts",
        ]
    df = compute_lag_features(df, lag_stats)
    df = compute_rolling_features(df, lag_stats[:5])

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
