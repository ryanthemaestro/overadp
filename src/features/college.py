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
            draft_feat_cols = ["draft_round", "draft_pick", "draft_capital",
                               "college_pass_yds_per_game", "college_pass_td_per_game",
                               "college_rush_yds_per_game", "college_rush_td_per_game",
                               "college_rec_yds_per_game", "college_rec_td_per_game",
                               "college_rec_per_game", "college_rush_att_per_game",
                               "early_declare"]
            available_draft_cols = [c for c in draft_feat_cols if c in dp.columns]

            # A row "needs draft data" if its draft_capital is NaN OR is zero and
            # it's a rookie (Sleeper stubs template-zero all numeric columns, so a
            # zero draft_capital on a rookie is indistinguishable from "never
            # matched" without this check).
            def _needs_draft(d: pd.DataFrame) -> "pd.Series[bool]":
                is_rook = d.get("is_rookie", pd.Series(0, index=d.index)).astype(float).eq(1)
                if "draft_capital" in d.columns:
                    return d["draft_capital"].isna() | (d["draft_capital"].eq(0) & is_rook)
                return pd.Series(True, index=d.index)

            # Pass 1: merge by player_id / gsis_id (exact — covers veterans and
            # rookies already in nflverse with a gsis_id assigned)
            if available_draft_cols and "player_id" in df.columns:
                dp_p1 = dp[["player_id"] + available_draft_cols].drop_duplicates("player_id")
                df = df.merge(dp_p1, on="player_id", how="left", suffixes=("", "_dp1"))
                for c in available_draft_cols:
                    dp_col = f"{c}_dp1"
                    if dp_col in df.columns:
                        if c not in df.columns:
                            df[c] = df[dp_col]
                        else:
                            # Overwrite where the existing value needs updating
                            needs = _needs_draft(df) & df[dp_col].notna()
                            df.loc[needs, c] = df.loc[needs, dp_col]
                        df = df.drop(columns=[dp_col])

            # Pass 2: name-based fallback for rows still missing draft_capital.
            # Covers (a) Sleeper stubs whose player_id is "SL-<id>" with no
            # gsis_id match, and (b) picks where nflverse hasn't assigned a
            # gsis_id yet (typically ~10% of picks in the first few weeks after
            # the draft).  We match on last name within the same projection
            # season — low collision risk since we only touch rookie rows.
            if "player_name" in df.columns:
                unmatched_mask = _needs_draft(df)
                if unmatched_mask.any():
                    name_col = "pfr_player_name" if "pfr_player_name" in dp.columns else None
                    if name_col:
                        dp["_dp_last"] = dp[name_col].astype(str).str.split().str[-1].str.lower().str.strip()
                        df.loc[unmatched_mask, "_df_last"] = (
                            df.loc[unmatched_mask, "player_name"]
                            .astype(str).str.split().str[-1].str.lower().str.strip()
                        )
                        # Only use draft picks from the target projection season
                        # to avoid veteran/rookie last-name collisions
                        if "season" in df.columns and "season" in dp.columns:
                            proj_season = df.loc[unmatched_mask, "season"].max()
                            dp_cur = dp[dp["season"] == proj_season].copy()
                        else:
                            dp_cur = dp.copy()

                        dp_cur = dp_cur.drop_duplicates(subset=["_dp_last"])
                        fallback_cols = ["_dp_last"] + [c for c in available_draft_cols if c in dp_cur.columns]
                        if len(fallback_cols) > 1:
                            dp_fb = dp_cur[fallback_cols].rename(
                                columns={c: f"_fb_{c}" for c in fallback_cols if c != "_dp_last"}
                            )
                            df = df.merge(dp_fb, left_on="_df_last", right_on="_dp_last", how="left")
                            n_before = unmatched_mask.sum()
                            for c in available_draft_cols:
                                fb_col = f"_fb_{c}"
                                if fb_col in df.columns:
                                    if c not in df.columns:
                                        df[c] = np.nan
                                    still_needs = _needs_draft(df) & df[fb_col].notna()
                                    df.loc[still_needs, c] = df.loc[still_needs, fb_col]
                                    df = df.drop(columns=[fb_col])
                            n_filled = n_before - _needs_draft(df).sum()
                            if n_filled > 0:
                                print(f"  draft_capital name-fallback: filled {n_filled} rows "
                                      f"(Sleeper stubs / no gsis_id)")
                        df = df.drop(columns=["_df_last", "_dp_last"], errors="ignore")

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
            df["_merge_last"] = df["player_name"].str.split().str[-1].str.lower().str.strip()
            # Don't dedupe here - let pandas handle the merge, then we'll dedupe on df later
            # Aggressive dedupe on last name alone drops the wrong rows (veteran vs rookie with same last name)
            merge_on = "_merge_last"

        # Log merge stats for debugging
        if merge_on:
            before_len = len(df)
            matched = df["_merge_last"].isin(cb["_merge_last"]).sum() if "_merge_last" in df.columns else 0
            print(f"  College features: combine merge via {merge_on}, matched {matched}/{len(df)} rows")
            # Show which last names matched
            if "_merge_last" in df.columns and "_merge_last" in cb.columns:
                matched_lasts = set(df[df["_merge_last"].isin(cb["_merge_last"])]["_merge_last"].dropna().unique())
                print(f"    Matched last names: {sorted(matched_lasts)[:20]}")

        if merge_on:
            combine_cols = [merge_on]
            for c in ["forty", "bench", "vertical", "broad_jump", "shuttle", "cone", "ht", "wt"]:
                if c in cb.columns:
                    combine_cols.append(c)

            if len(combine_cols) > 1:
                cb_sub = cb[combine_cols].drop_duplicates(subset=[merge_on])
                # Parse height from "6-5" format to inches
                if "ht" in cb_sub.columns:
                    def parse_ht(h):
                        if pd.isna(h):
                            return None
                        s = str(h).strip()
                        if "-" in s:
                            try:
                                feet, inches = s.split("-")
                                return float(feet) * 12 + float(inches)
                            except (ValueError, TypeError):
                                return None
                        try:
                            return float(s)
                        except (ValueError, TypeError):
                            return None
                    cb_sub["ht"] = cb_sub["ht"].apply(parse_ht)
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
                # Merge left, then only fill NaN values (don't clobber existing from Sleeper)
                df_before = df.copy()
                df = df.merge(cb_sub, on=merge_on, how="left", suffixes=("", "_new"))
                # For each combine column, use existing if non-null, else use new value
                for col in ["combine_forty", "combine_bench", "combine_vertical", "combine_broad", "combine_shuttle", "combine_cone", "combine_ht", "combine_wt"]:
                    if f"{col}_new" in df.columns:
                        df[col] = df[col].fillna(df[f"{col}_new"])
                        df = df.drop(columns=[f"{col}_new"])
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
        if "athletic_score" in df.columns:
            df["athletic_x_rookie"] = df["athletic_score"] * df["is_rookie"]
        else:
            df["athletic_x_rookie"] = 0.0
    if "is_2nd_year" in df.columns:
        df["college_x_2nd_year"] = df["college_dominance"] * df["is_2nd_year"]
        df["draft_cap_x_2nd_year"] = df["draft_capital"] * df["is_2nd_year"]

    # Add has_combine_data flag before filling NaN
    combine_metric_cols = ["combine_forty", "combine_bench", "combine_vertical",
                           "combine_broad", "combine_shuttle", "combine_cone"]
    if any(c in df.columns for c in combine_metric_cols):
        df["has_combine_data"] = df[combine_metric_cols].notna().any(axis=1).astype(int)
    else:
        df["has_combine_data"] = 0

    # Restrict combine features to young players (<4 NFL years).
    # Veteran combine scores from a decade ago add noise; their NFL stats dominate.
    # Walk-forward testing showed this cutoff gives the best overall improvement.
    if "draft_year" in df.columns and "season" in df.columns:
        years_exp = df["season"] - df["draft_year"].fillna(df["season"])
        veteran_mask = years_exp >= 4
        combine_and_athletic = combine_metric_cols + ["athletic_score", "has_combine_data"]
        for col in combine_and_athletic:
            if col in df.columns:
                df.loc[veteran_mask, col] = 0

    # Fill NaN for all new columns
    new_cols = ["draft_round", "draft_pick", "draft_capital",
                "athletic_score", "college_dominance",
                "early_declare", "p5_conference", "has_combine_data",
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
            if c in ["early_declare", "p5_conference", "draft_round", "has_combine_data"]:
                df[c] = df[c].fillna(0).astype(int)
            else:
                df[c] = df[c].fillna(0)

    # Clean up z-score columns (used internally, not as model features)
    z_cols = [c for c in df.columns if c.endswith("_z") and c.startswith("combine_")]
    df = df.drop(columns=z_cols, errors="ignore")

    return df
