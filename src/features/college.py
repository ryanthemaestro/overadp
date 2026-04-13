"""College/draft feature engineering — critical for rookie projections.

Rookies have zero NFL lag features. College production and draft capital
are the strongest available signals for how they'll translate to the NFL.
"""
import pandas as pd
import numpy as np
from typing import Optional


def compute_college_features(
    df: pd.DataFrame,
    draft_df: Optional[pd.DataFrame] = None,
    combine_df: Optional[pd.DataFrame] = None,
    player_info_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Add college/draft features for rookie and young player projections.

    Features created:
    - draft_round: 1-7 (0 = undrafted)
    - draft_pick: overall pick number (0 = undrafted)
    - draft_capital: composite score (1st round = ~7, UDFA = 0)
    - combine_forty, combine_bench, combine_vertical, combine_broad, combine_shuttle
    - athletic_score: position-weighted composite of combine z-scores
    - college_pass_yds_per_game, college_pass_td_per_game (QB)
    - college_rush_yds_per_game, college_rush_td_per_game (RB)
    - college_rec_yds_per_game, college_rec_td_per_game (WR/TE)
    - college_dominance: position-weighted college production z-score
    - early_declare: left college before senior season (1/0)
    - p5_conference: played in Power 5 conference (1/0)
    """
    if draft_df is None and combine_df is None and player_info_df is None:
        return df

    df = df.copy()

    # --- Player info: draft position, college, experience ---
    if player_info_df is not None and not player_info_df.empty:
        pi = player_info_df.copy()
        pi.columns = [c.lower() for c in pi.columns]

        id_col = "gsis_id" if "gsis_id" in pi.columns else "player_id"
        if id_col not in pi.columns:
            return df

        pi_cols = [id_col]
        for c in ["draft_year", "draft_round", "draft_pick", "college_name",
                   "college_conference", "years_of_experience", "height", "weight"]:
            if c in pi.columns:
                pi_cols.append(c)
        pi = pi[pi_cols].drop_duplicates(subset=[id_col])

        if id_col == "gsis_id" and "player_id" in df.columns:
            pi = pi.rename(columns={"gsis_id": "player_id"})

        if "player_id" in pi.columns and "player_id" in df.columns:
            new_cols = [c for c in pi.columns if c not in df.columns or c == "player_id"]
            if len(new_cols) > 1:
                df = df.merge(pi[new_cols], on="player_id", how="left")

    # --- Draft picks: college stats + draft capital ---
    if draft_df is not None and not draft_df.empty:
        dp = draft_df.copy()
        dp.columns = [c.lower() for c in dp.columns]

        id_col = "gsis_id" if "gsis_id" in dp.columns else "player_id"
        if id_col in dp.columns:
            if id_col == "gsis_id" and "player_id" in df.columns:
                dp = dp.rename(columns={"gsis_id": "player_id"})

            # Take most recent draft entry per player
            if "season" in dp.columns:
                dp = dp.sort_values("season").groupby("player_id").last().reset_index()
            else:
                dp = dp.drop_duplicates(subset=["player_id"])

            # Draft capital features
            if "round" in dp.columns:
                dp["draft_round"] = dp["round"].fillna(0).astype(int)
            if "pick" in dp.columns:
                dp["draft_pick"] = dp["pick"].fillna(0).astype(int)

            # Draft capital composite: higher = better prospect
            # 1st round pick 1 = ~7.99, 7th round = ~1.03, UDFA = 0
            if "draft_round" in dp.columns and "draft_pick" in dp.columns:
                dp["draft_capital"] = np.where(
                    dp["draft_round"] > 0,
                    8 - dp["draft_round"] + (1 - dp["draft_pick"] / 260),
                    0,
                )

            # College production per game (estimate ~13 games/season)
            college_games = 13
            stat_map = {
                "pass_yards": "college_pass_yds_per_game",
                "pass_tds": "college_pass_td_per_game",
                "rush_yards": "college_rush_yds_per_game",
                "rush_tds": "college_rush_td_per_game",
                "rec_yards": "college_rec_yds_per_game",
                "rec_tds": "college_rec_td_per_game",
                "receptions": "college_rec_per_game",
                "rush_atts": "college_rush_att_per_game",
            }
            for src, dst in stat_map.items():
                if src in dp.columns:
                    dp[dst] = dp[src].fillna(0) / college_games

            # Early declare: drafted young (age <= 21)
            if "age" in dp.columns:
                dp["early_declare"] = (dp["age"].fillna(99) <= 21).astype(int)

            # Merge draft features
            merge_cols = ["player_id"]
            for c in ["draft_round", "draft_pick", "draft_capital",
                       "college_pass_yds_per_game", "college_pass_td_per_game",
                       "college_rush_yds_per_game", "college_rush_td_per_game",
                       "college_rec_yds_per_game", "college_rec_td_per_game",
                       "college_rec_per_game", "college_rush_att_per_game",
                       "early_declare"]:
                if c in dp.columns:
                    merge_cols.append(c)

            if len(merge_cols) > 1 and "player_id" in df.columns:
                existing = [c for c in merge_cols if c not in df.columns or c == "player_id"]
                if len(existing) > 1:
                    df = df.merge(dp[existing], on="player_id", how="left")

    # --- Combine data: athletic metrics ---
    if combine_df is not None and not combine_df.empty:
        cb = combine_df.copy()
        cb.columns = [c.lower() for c in cb.columns]

        # Try matching via pfr_id through player_info gsis_id→pfr_id mapping
        # The feature matrix has player_id (=gsis_id), combine has pfr_id
        # We need player_info to bridge them
        merge_on = None
        if "pfr_id" in cb.columns and "player_id" in df.columns:
            # Build gsis_id → pfr_id mapping from player_info
            if player_info_df is not None and not player_info_df.empty:
                pi_for_merge = player_info_df.copy()
                pi_for_merge.columns = [c.lower() for c in pi_for_merge.columns]
                if "gsis_id" in pi_for_merge.columns and "pfr_id" in pi_for_merge.columns:
                    id_map = pi_for_merge[["gsis_id", "pfr_id"]].dropna(subset=["pfr_id"]).drop_duplicates("gsis_id")
                    id_map = id_map.rename(columns={"gsis_id": "player_id", "pfr_id": "pfr_id"})
                    # Add pfr_id to df via player_id
                    df = df.merge(id_map, on="player_id", how="left")
            if "pfr_id" in df.columns:
                cb = cb.drop_duplicates(subset=["pfr_id"])
                merge_on = "pfr_id"

        # Fallback: name matching (less reliable but better than nothing)
        if merge_on is None and "player_name" in cb.columns and "player_name" in df.columns:
            # Use last_name matching since df has abbreviated names (L.Jackson)
            # and combine has full names (Lamar Jackson)
            cb["_merge_last"] = cb["player_name"].str.split().str[-1].str.lower().str.strip()
            df["_merge_last"] = df["player_name"].str.split(".").str[-1].str.lower().str.strip()
            cb = cb.drop_duplicates(subset=["_merge_last"])
            merge_on = "_merge_last"

        if merge_on:
            combine_cols = [merge_on]
            for c in ["forty", "bench", "vertical", "broad_jump", "shuttle", "cone", "ht", "wt"]:
                if c in cb.columns:
                    combine_cols.append(c)

            if len(combine_cols) > 1:
                cb_sub = cb[combine_cols].drop_duplicates(subset=[merge_on])
                rename_map = {
                    "forty": "combine_forty",
                    "bench": "combine_bench",
                    "vertical": "combine_vertical",
                    "broad_jump": "combine_broad",
                    "shuttle": "combine_shuttle",
                    "cone": "combine_cone",
                    "ht": "combine_ht",
                    "wt": "combine_wt",
                }
                cb_sub = cb_sub.rename(columns={k: v for k, v in rename_map.items() if k in cb_sub.columns})
                df = df.merge(cb_sub, on=merge_on, how="left")
                if "_merge_name" in df.columns:
                    df = df.drop(columns=["_merge_name"])

    # --- Derived features ---
    # P5 conference flag
    # nfl_data_py uses full conference names, not abbreviations
    p5_names = {
        "southeastern conference", "sec",
        "big ten conference", "big ten",
        "atlantic coast conference", "acc",
        "big twelve conference", "big 12", "big xii",
        "pacific twelve conference", "pac-12", "pac 12", "pacific ten conference",
    }
    if "college_conference" in df.columns:
        df["p5_conference"] = df["college_conference"].str.lower().str.strip().isin(p5_names).astype(int)
    elif "college_name" in df.columns:
        # Heuristic: major programs are P5
        df["p5_conference"] = 0

    # Athletic score: position-weighted composite of combine z-scores
    combine_metrics = ["combine_forty", "combine_bench", "combine_vertical",
                        "combine_broad", "combine_shuttle"]
    has_combine = any(c in df.columns for c in combine_metrics)

    if has_combine and "position" in df.columns:
        # Position-specific weights for combine drills
        # Higher weight = more important for that position
        pos_weights = {
            "QB":  {"combine_forty": 0.25, "combine_shuttle": 0.25, "combine_vertical": 0.2, "combine_broad": 0.2, "combine_bench": 0.1},
            "RB":  {"combine_forty": 0.40, "combine_shuttle": 0.20, "combine_vertical": 0.15, "combine_broad": 0.15, "combine_bench": 0.1},
            "WR":  {"combine_forty": 0.35, "combine_shuttle": 0.20, "combine_vertical": 0.15, "combine_broad": 0.20, "combine_bench": 0.1},
            "TE":  {"combine_forty": 0.25, "combine_shuttle": 0.15, "combine_vertical": 0.20, "combine_broad": 0.25, "combine_bench": 0.15},
        }

        # Compute z-scores within position
        for metric in combine_metrics:
            if metric in df.columns:
                vals = df[metric].copy()
                # Lower is better for forty and shuttle → negate
                if metric in ["combine_forty", "combine_shuttle"]:
                    vals = -vals
                grp = df.groupby("position")[metric]
                mean = grp.transform("mean")
                std = grp.transform("std")
                df[f"{metric}_z"] = (vals - mean) / std.replace(0, np.nan)

        # Weighted athletic score per position
        # Only compute for players who have at least one combine metric
        df["athletic_score"] = np.nan
        for pos, weights in pos_weights.items():
            pos_mask = df["position"] == pos
            if pos_mask.sum() == 0:
                continue
            score = pd.Series(0.0, index=df.index)
            weight_applied = pd.Series(0.0, index=df.index)
            for metric, weight in weights.items():
                z_col = f"{metric}_z"
                if z_col in df.columns:
                    has_val = df[z_col].notna()
                    score += df[z_col].fillna(0) * weight
                    weight_applied += has_val.astype(float) * weight
            # Only assign score where at least one metric was available
            valid = weight_applied > 0
            df.loc[pos_mask & valid, "athletic_score"] = (score / weight_applied).loc[pos_mask & valid]

    # College dominance: position-weighted college production z-score
    college_stat_cols = {
        "QB": ["college_pass_yds_per_game", "college_pass_td_per_game", "college_rush_yds_per_game"],
        "RB": ["college_rush_yds_per_game", "college_rush_td_per_game", "college_rec_per_game"],
        "WR": ["college_rec_yds_per_game", "college_rec_td_per_game", "college_rush_yds_per_game"],
        "TE": ["college_rec_yds_per_game", "college_rec_td_per_game"],
    }

    df["college_dominance"] = 0.0
    for pos, stats in college_stat_cols.items():
        pos_mask = df["position"] == pos
        if pos_mask.sum() < 5:
            continue
        available = [s for s in stats if s in df.columns]
        if not available:
            continue
        # Z-score each stat within position, then average
        z_scores = []
        for stat in available:
            vals = df.loc[pos_mask, stat]
            mean = vals.mean()
            std = vals.std()
            if std > 0:
                z_scores.append((vals - mean) / std)
        if z_scores:
            combined_z = pd.concat(z_scores, axis=1).mean(axis=1)
            df.loc[pos_mask, "college_dominance"] = combined_z

    # --- Interaction features: college supplements missing lag data ---
    # When a player has no NFL history (rookie) or only 1 year (2nd-year),
    # their lag features are zero/uninformative. These interaction features
    # tell the model "use college data AS the prior for this player."
    if "is_rookie" in df.columns:
        df["college_x_rookie"] = df["college_dominance"] * df["is_rookie"]
        df["draft_cap_x_rookie"] = df["draft_capital"] * df["is_rookie"]
        df["athletic_x_rookie"] = df["athletic_score"] * df["is_rookie"]
    if "is_2nd_year" in df.columns:
        df["college_x_2nd_year"] = df["college_dominance"] * df["is_2nd_year"]
        df["draft_cap_x_2nd_year"] = df["draft_capital"] * df["is_2nd_year"]

    # Fill NaN for all new columns
    new_cols = ["draft_round", "draft_pick", "draft_capital",
                "athletic_score", "college_dominance",
                "early_declare", "p5_conference",
                "combine_forty", "combine_bench", "combine_vertical",
                "combine_broad", "combine_shuttle", "combine_cone",
                "college_pass_yds_per_game", "college_pass_td_per_game",
                "college_rush_yds_per_game", "college_rush_td_per_game",
                "college_rec_yds_per_game", "college_rec_td_per_game",
                "college_rec_per_game", "college_rush_att_per_game",
                "college_x_rookie", "draft_cap_x_rookie", "athletic_x_rookie",
                "college_x_2nd_year", "draft_cap_x_2nd_year"]
    for c in new_cols:
        if c in df.columns:
            if c in ["early_declare", "p5_conference", "draft_round"]:
                df[c] = df[c].fillna(0).astype(int)
            else:
                df[c] = df[c].fillna(0)

    # Clean up z-score columns (used internally, not as model features)
    z_cols = [c for c in df.columns if c.endswith("_z") and c.startswith("combine_")]
    df = df.drop(columns=z_cols, errors="ignore")

    return df
