#!/usr/bin/env python3
"""Run CatBoost-only feature group experiments with walk-forward validation.

The goal is fast, repeatable feature testing:
  - Build the same clean feature matrix used by export_static.py
  - Mutate POSITION_FEATURES in memory for each candidate group
  - Validate CatBoost only on the same walk-forward folds
  - Write per-experiment deltas so changes are kept only when evidence supports it

Leakage rules for groups in this script:
  - Advanced player stats are *_lag1 only.
  - Schedule SOS uses released schedules plus opponents' prior-season defense.
  - NGS features are weekly player data aggregated to season and shifted +1.
  - Snap count features are regular-season player usage aggregated to season and shifted +1.
  - Availability features are prior-season games played and rolling prior-season games.
  - ADP-derived features use draft-market price plus already-lagged player data only.
  - PFR advanced stats are player-season rows shifted +1 before use.
  - No current-season game outcomes are used as model features.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data.clean import clean_ol_metrics, clean_roster_info, clean_seasonal_stats, clean_team_stats
from src.data.fetch import fetch_adp_data, fetch_contracts, fetch_depth_charts, fetch_injury_data, fetch_ngs_data, load_all_data
from src.features.college import compute_college_features
from src.features.contracts import CONTRACT_ALL, CONTRACT_STATUS, CONTRACT_VALUE, compute_contract_features
from src.features.engineer import (
    build_feature_matrix,
    compute_adp_features,
    compute_depth_chart_features,
    compute_injury_features,
    compute_regression_to_mean_features,
    compute_rookie_features,
    compute_sos_features,
    compute_stacking_features,
    compute_target_competition_features,
    compute_teammate_dependency_features,
)
from src.models import pipeline as pipeline_mod
from src.models.catboost_model import CatBoostModel
from src.models.pipeline import PositionPipeline
from src.scoring.calculator import add_fantasy_points_to_df


SEASONS = list(range(2021, 2026))
MAX_STATS = 2025
POSITIONS = ["QB", "RB", "WR", "TE"]

QB_ADVANCED = [
    "passing_epa_lag1",
    "passing_cpoe_lag1",
    "pacr_lag1",
    "passing_air_yards_lag1",
    "passing_first_downs_lag1",
]

RB_ADVANCED = [
    "rushing_epa_lag1",
    "rushing_first_downs_lag1",
]

RECEIVING_ADVANCED = [
    "receiving_epa_lag1",
    "receiving_air_yards_lag1",
    "receiving_yards_after_catch_lag1",
    "receiving_first_downs_lag1",
    "air_yards_share_lag1",
    "wopr_lag1",
    "racr_lag1",
    "pts_per_target_lag1",
]

SCHEDULE_QB = [
    "schedule_opp_def_rank",
    "schedule_opp_pass_def_rank",
    "schedule_top8_def_games",
    "schedule_bottom8_def_games",
    "schedule_top8_pass_def_games",
    "schedule_bottom8_pass_def_games",
    "schedule_division_games",
    "schedule_rest_advantage",
    "schedule_dome_games",
]

SCHEDULE_RB = [
    "schedule_opp_def_rank",
    "schedule_top8_def_games",
    "schedule_bottom8_def_games",
    "schedule_division_games",
    "schedule_rest_advantage",
]

SCHEDULE_RECEIVING = [
    "schedule_opp_pass_def_rank",
    "schedule_top8_pass_def_games",
    "schedule_bottom8_pass_def_games",
    "schedule_division_games",
    "schedule_rest_advantage",
    "schedule_dome_games",
]

NGS_QB = [
    "ngs_passing_avg_time_to_throw_lag1",
    "ngs_passing_avg_completed_air_yards_lag1",
    "ngs_passing_avg_intended_air_yards_lag1",
    "ngs_passing_avg_air_yards_differential_lag1",
    "ngs_passing_aggressiveness_lag1",
    "ngs_passing_avg_air_yards_to_sticks_lag1",
    "ngs_passing_completion_percentage_above_expectation_lag1",
]

NGS_RB = [
    "ngs_rushing_efficiency_lag1",
    "ngs_rushing_percent_attempts_gte_eight_defenders_lag1",
    "ngs_rushing_avg_time_to_los_lag1",
    "ngs_rushing_expected_rush_yards_lag1",
    "ngs_rushing_rush_yards_over_expected_lag1",
    "ngs_rushing_rush_yards_over_expected_per_att_lag1",
    "ngs_rushing_rush_pct_over_expected_lag1",
]

NGS_RECEIVING = [
    "ngs_receiving_avg_cushion_lag1",
    "ngs_receiving_avg_separation_lag1",
    "ngs_receiving_avg_intended_air_yards_lag1",
    "ngs_receiving_percent_share_of_intended_air_yards_lag1",
    "ngs_receiving_catch_percentage_lag1",
    "ngs_receiving_avg_yac_lag1",
    "ngs_receiving_avg_expected_yac_lag1",
    "ngs_receiving_avg_yac_above_expectation_lag1",
]

NGS_RECEIVING_SEPARATION = [
    "ngs_receiving_avg_cushion_lag1",
    "ngs_receiving_avg_separation_lag1",
]

NGS_RECEIVING_AIR = [
    "ngs_receiving_avg_intended_air_yards_lag1",
    "ngs_receiving_percent_share_of_intended_air_yards_lag1",
]

NGS_RECEIVING_CATCH = [
    "ngs_receiving_catch_percentage_lag1",
]

NGS_RECEIVING_YAC = [
    "ngs_receiving_avg_yac_lag1",
    "ngs_receiving_avg_expected_yac_lag1",
    "ngs_receiving_avg_yac_above_expectation_lag1",
]

SNAP_USAGE = [
    "snap_offense_snaps_lag1",
    "snap_offense_pct_lag1",
    "snap_games_lag1",
    "snap_offense_snaps_per_game_lag1",
]

AVAILABILITY = [
    "games_lag2",
    "games_roll2",
    "games_roll3",
    "missed_games_lag1",
    "missed_games_roll2",
    "played_15plus_lag1",
]

AVAILABILITY_GAMES = [
    "games_lag2",
    "games_roll2",
    "games_roll3",
]

AVAILABILITY_MISSED = [
    "missed_games_lag1",
    "missed_games_roll2",
]

AVAILABILITY_DURABLE = [
    "played_15plus_lag1",
]

ADP_SHAPE = [
    "adp_log",
    "adp_inverse",
    "is_top12_adp",
    "is_top24_adp",
    "is_top48_adp",
    "is_late_or_undrafted_adp",
]

ADP_VALUE = [
    "adp_minus_pts_lag1",
    "pts_lag1_per_adp",
    "fp_per_game_lag1_per_adp",
]

ADP_INTERACTION = [
    "age_x_adp",
]

DRAFT_VALUE_CORE = [
    "draft_value_log_otc",
    "draft_value_pff",
]

DRAFT_VALUE_ALL = [
    "draft_value_stuart",
    "draft_value_johnson",
    "draft_value_hill",
    "draft_value_otc",
    "draft_value_pff",
    "draft_value_log_otc",
]

DRAFT_VALUE_ROOKIE = [
    "draft_value_otc_x_rookie",
    "draft_value_pff_x_rookie",
]

PFR_PASS = [
    "pfr_pass_pocket_time_lag1",
    "pfr_pass_drop_pct_lag1",
    "pfr_pass_bad_throw_pct_lag1",
    "pfr_pass_pressure_pct_lag1",
    "pfr_pass_on_tgt_pct_lag1",
    "pfr_pass_intended_air_yards_per_pass_attempt_lag1",
    "pfr_pass_completed_air_yards_per_pass_attempt_lag1",
    "pfr_pass_pass_yards_after_catch_per_completion_lag1",
    "pfr_pass_scramble_yards_per_attempt_lag1",
]

PFR_RUSH = [
    "pfr_rush_gs_lag1",
    "pfr_rush_x1d_lag1",
    "pfr_rush_ybc_att_lag1",
    "pfr_rush_yac_att_lag1",
    "pfr_rush_brk_tkl_lag1",
    "pfr_rush_att_br_lag1",
]

PFR_REC = [
    "pfr_rec_gs_lag1",
    "pfr_rec_x1d_lag1",
    "pfr_rec_ybc_r_lag1",
    "pfr_rec_yac_r_lag1",
    "pfr_rec_adot_lag1",
    "pfr_rec_brk_tkl_lag1",
    "pfr_rec_rec_br_lag1",
    "pfr_rec_drop_percent_lag1",
    "pfr_rec_rat_lag1",
]


EXPERIMENTS: dict[str, dict[str, Any]] = {
    "current": {"add": {}},
    "clean_base": {
        "remove": {
            "QB": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
            "RB": SCHEDULE_RB + ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
            "WR": SCHEDULE_RECEIVING + NGS_RECEIVING + AVAILABILITY + ADP_VALUE,
            "TE": RECEIVING_ADVANCED + ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
        }
    },
    "baseline_no_te_advanced": {"remove": {"TE": RECEIVING_ADVANCED}},
    "te_advanced_clean": {
        "remove": {
            "RB": SCHEDULE_RB,
            "WR": SCHEDULE_RECEIVING,
        }
    },
    "schedule_rb_clean": {
        "remove": {
            "WR": SCHEDULE_RECEIVING,
            "TE": RECEIVING_ADVANCED,
        },
        "add": {"RB": SCHEDULE_RB},
    },
    "schedule_wr_clean": {
        "remove": {
            "RB": SCHEDULE_RB,
            "TE": RECEIVING_ADVANCED,
        },
        "add": {"WR": SCHEDULE_RECEIVING},
    },
    "schedule_rb_wr_clean": {
        "remove": {"TE": RECEIVING_ADVANCED},
        "add": {
            "RB": SCHEDULE_RB,
            "WR": SCHEDULE_RECEIVING,
        },
    },
    "qb_advanced": {"add": {"QB": QB_ADVANCED}},
    "rb_advanced": {"add": {"RB": RB_ADVANCED}},
    "wr_advanced": {"add": {"WR": RECEIVING_ADVANCED}},
    "te_advanced": {"add": {"TE": RECEIVING_ADVANCED}},
    "schedule_qb": {"add": {"QB": SCHEDULE_QB}},
    "schedule_rb": {"add": {"RB": SCHEDULE_RB}},
    "schedule_wr": {"add": {"WR": SCHEDULE_RECEIVING}},
    "schedule_te": {"add": {"TE": SCHEDULE_RECEIVING}},
    "schedule_all": {
        "add": {
            "QB": SCHEDULE_QB,
            "RB": SCHEDULE_RB,
            "WR": SCHEDULE_RECEIVING,
            "TE": SCHEDULE_RECEIVING,
        }
    },
    "advanced_all": {
        "add": {
            "QB": QB_ADVANCED,
            "RB": RB_ADVANCED,
            "WR": RECEIVING_ADVANCED,
            "TE": RECEIVING_ADVANCED,
        }
    },
    "advanced_schedule_all": {
        "add": {
            "QB": QB_ADVANCED + SCHEDULE_QB,
            "RB": RB_ADVANCED + SCHEDULE_RB,
            "WR": RECEIVING_ADVANCED + SCHEDULE_RECEIVING,
            "TE": RECEIVING_ADVANCED + SCHEDULE_RECEIVING,
        }
    },
    "ngs_qb": {"add": {"QB": NGS_QB}},
    "ngs_rb": {"add": {"RB": NGS_RB}},
    "ngs_wr": {"add": {"WR": NGS_RECEIVING}},
    "ngs_wr_separation": {"remove": {"WR": NGS_RECEIVING}, "add": {"WR": NGS_RECEIVING_SEPARATION}},
    "ngs_wr_air": {"remove": {"WR": NGS_RECEIVING}, "add": {"WR": NGS_RECEIVING_AIR}},
    "ngs_wr_catch": {"remove": {"WR": NGS_RECEIVING}, "add": {"WR": NGS_RECEIVING_CATCH}},
    "ngs_wr_yac": {"remove": {"WR": NGS_RECEIVING}, "add": {"WR": NGS_RECEIVING_YAC}},
    "ngs_wr_air_yac": {"remove": {"WR": NGS_RECEIVING}, "add": {"WR": NGS_RECEIVING_AIR + NGS_RECEIVING_YAC}},
    "ngs_wr_no_catch": {
        "remove": {"WR": NGS_RECEIVING_CATCH},
        "add": {"WR": NGS_RECEIVING_SEPARATION + NGS_RECEIVING_AIR + NGS_RECEIVING_YAC},
    },
    "ngs_te": {"add": {"TE": NGS_RECEIVING}},
    "ngs_all": {
        "add": {
            "QB": NGS_QB,
            "RB": NGS_RB,
            "WR": NGS_RECEIVING,
            "TE": NGS_RECEIVING,
        }
    },
    "current_plus_ngs": {
        "add": {
            "QB": NGS_QB,
            "RB": NGS_RB,
            "WR": NGS_RECEIVING,
            "TE": NGS_RECEIVING,
        }
    },
    "snap_qb": {"add": {"QB": SNAP_USAGE}},
    "snap_rb": {"add": {"RB": SNAP_USAGE}},
    "snap_wr": {"add": {"WR": SNAP_USAGE}},
    "snap_te": {"add": {"TE": SNAP_USAGE}},
    "snap_all": {
        "add": {
            "QB": SNAP_USAGE,
            "RB": SNAP_USAGE,
            "WR": SNAP_USAGE,
            "TE": SNAP_USAGE,
        }
    },
    "qb_snap_availability": {
        "add": {"QB": SNAP_USAGE + AVAILABILITY},
    },
    "availability_qb": {"add": {"QB": AVAILABILITY}},
    "availability_rb": {"add": {"RB": AVAILABILITY}},
    "availability_wr": {"add": {"WR": AVAILABILITY}},
    "availability_wr_games": {"remove": {"WR": AVAILABILITY}, "add": {"WR": AVAILABILITY_GAMES}},
    "availability_wr_missed": {"remove": {"WR": AVAILABILITY}, "add": {"WR": AVAILABILITY_MISSED}},
    "availability_wr_durable": {"remove": {"WR": AVAILABILITY}, "add": {"WR": AVAILABILITY_DURABLE}},
    "availability_wr_games_durable": {
        "remove": {"WR": AVAILABILITY},
        "add": {"WR": AVAILABILITY_GAMES + AVAILABILITY_DURABLE},
    },
    "availability_te": {"add": {"TE": AVAILABILITY}},
    "availability_all": {
        "add": {
            "QB": AVAILABILITY,
            "RB": AVAILABILITY,
            "WR": AVAILABILITY,
            "TE": AVAILABILITY,
        }
    },
    "adp_shape_qb": {"add": {"QB": ADP_SHAPE}},
    "adp_shape_rb": {"add": {"RB": ADP_SHAPE}},
    "adp_shape_wr": {"add": {"WR": ADP_SHAPE}},
    "adp_shape_te": {"add": {"TE": ADP_SHAPE}},
    "adp_value_qb": {"add": {"QB": ADP_VALUE}},
    "adp_value_rb": {"add": {"RB": ADP_VALUE}},
    "adp_value_wr": {"add": {"WR": ADP_VALUE}},
    "adp_value_te": {"add": {"TE": ADP_VALUE}},
    "adp_interaction_qb": {"add": {"QB": ADP_INTERACTION}},
    "adp_interaction_rb": {"add": {"RB": ADP_INTERACTION}},
    "adp_interaction_wr": {"add": {"WR": ADP_INTERACTION}},
    "adp_interaction_te": {"add": {"TE": ADP_INTERACTION}},
    "adp_qb_shape_value": {"add": {"QB": ADP_SHAPE + ADP_VALUE}},
    "adp_qb_shape_interaction": {"add": {"QB": ADP_SHAPE + ADP_INTERACTION}},
    "adp_qb_value_interaction": {"add": {"QB": ADP_VALUE + ADP_INTERACTION}},
    "adp_qb_all": {"add": {"QB": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION}},
    "adp_rb_shape_value": {"add": {"RB": ADP_SHAPE + ADP_VALUE}},
    "adp_rb_shape_interaction": {"add": {"RB": ADP_SHAPE + ADP_INTERACTION}},
    "adp_rb_value_interaction": {"add": {"RB": ADP_VALUE + ADP_INTERACTION}},
    "adp_rb_all": {"add": {"RB": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION}},
    "adp_wr_shape_value": {"add": {"WR": ADP_SHAPE + ADP_VALUE}},
    "adp_wr_value_interaction": {"add": {"WR": ADP_VALUE + ADP_INTERACTION}},
    "adp_wr_all": {"add": {"WR": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION}},
    "adp_te_value_interaction": {"add": {"TE": ADP_VALUE + ADP_INTERACTION}},
    "adp_te_all": {"add": {"TE": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION}},
    "adp_all": {
        "add": {
            "QB": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
            "RB": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
            "WR": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
            "TE": ADP_SHAPE + ADP_VALUE + ADP_INTERACTION,
        }
    },
    "draft_value_core_all": {
        "add": {
            "QB": DRAFT_VALUE_CORE,
            "RB": DRAFT_VALUE_CORE,
            "WR": DRAFT_VALUE_CORE,
            "TE": DRAFT_VALUE_CORE,
        }
    },
    "draft_value_rookie_all": {
        "add": {
            "QB": DRAFT_VALUE_ROOKIE,
            "RB": DRAFT_VALUE_ROOKIE,
            "WR": DRAFT_VALUE_ROOKIE,
            "TE": DRAFT_VALUE_ROOKIE,
        }
    },
    "draft_value_rookie_rb_wr": {
        "add": {
            "RB": DRAFT_VALUE_ROOKIE,
            "WR": DRAFT_VALUE_ROOKIE,
        }
    },
    "draft_value_all": {
        "add": {
            "QB": DRAFT_VALUE_ALL + DRAFT_VALUE_ROOKIE,
            "RB": DRAFT_VALUE_ALL + DRAFT_VALUE_ROOKIE,
            "WR": DRAFT_VALUE_ALL + DRAFT_VALUE_ROOKIE,
            "TE": DRAFT_VALUE_ALL + DRAFT_VALUE_ROOKIE,
        }
    },
    "wr_cached_best": {
        "add": {"WR": DRAFT_VALUE_ROOKIE + SNAP_USAGE + PFR_REC + SCHEDULE_RECEIVING},
    },
    "nflverse_keep_candidates": {
        "add": {
            "QB": SNAP_USAGE + AVAILABILITY,
            "RB": DRAFT_VALUE_ROOKIE,
            "WR": DRAFT_VALUE_ROOKIE + SNAP_USAGE + PFR_REC + SCHEDULE_RECEIVING,
        }
    },
    "contract_value_qb": {"add": {"QB": CONTRACT_VALUE}},
    "contract_value_rb": {"add": {"RB": CONTRACT_VALUE}},
    "contract_value_wr": {"add": {"WR": CONTRACT_VALUE}},
    "contract_value_te": {"add": {"TE": CONTRACT_VALUE}},
    "contract_status_qb": {"add": {"QB": CONTRACT_STATUS}},
    "contract_status_rb": {"add": {"RB": CONTRACT_STATUS}},
    "contract_status_wr": {"add": {"WR": CONTRACT_STATUS}},
    "contract_status_te": {"add": {"TE": CONTRACT_STATUS}},
    "contract_all_qb": {"add": {"QB": CONTRACT_ALL}},
    "contract_all_rb": {"add": {"RB": CONTRACT_ALL}},
    "contract_all_wr": {"add": {"WR": CONTRACT_ALL}},
    "contract_all_te": {"add": {"TE": CONTRACT_ALL}},
    "contract_value_skill": {"add": {"RB": CONTRACT_VALUE, "WR": CONTRACT_VALUE, "TE": CONTRACT_VALUE}},
    "contract_status_skill": {"add": {"RB": CONTRACT_STATUS, "WR": CONTRACT_STATUS, "TE": CONTRACT_STATUS}},
    "contract_all_skill": {"add": {"RB": CONTRACT_ALL, "WR": CONTRACT_ALL, "TE": CONTRACT_ALL}},
    "contract_te_all_wr_status": {"add": {"WR": CONTRACT_STATUS, "TE": CONTRACT_ALL}},
    "contract_all": {
        "add": {
            "QB": CONTRACT_ALL,
            "RB": CONTRACT_ALL,
            "WR": CONTRACT_ALL,
            "TE": CONTRACT_ALL,
        }
    },
    "pfr_pass_qb": {"add": {"QB": PFR_PASS}},
    "pfr_rush_rb": {"add": {"RB": PFR_RUSH}},
    "pfr_rec_wr": {"add": {"WR": PFR_REC}},
    "pfr_rec_te": {"add": {"TE": PFR_REC}},
    "pfr_all": {
        "add": {
            "QB": PFR_PASS,
            "RB": PFR_RUSH,
            "WR": PFR_REC,
            "TE": PFR_REC,
        }
    },
}


def add_unique(base: list[str], extra: list[str]) -> list[str]:
    out = list(base)
    for item in extra:
        if item not in out:
            out.append(item)
    return out


def apply_experiment_features(base_features: dict[str, list[str]], spec: dict[str, Any]) -> dict[str, list[str]]:
    features = copy.deepcopy(base_features)

    for pos, remove_cols in spec.get("remove", {}).items():
        features[pos] = [c for c in features[pos] if c not in set(remove_cols)]

    for pos, add_cols in spec.get("add", {}).items():
        features[pos] = add_unique(features[pos], add_cols)

    return features


def build_frame() -> pd.DataFrame:
    print(f"Loading {SEASONS}...")
    data = load_all_data(SEASONS)
    seasonal = clean_seasonal_stats(data["seasonal"], min_games=3)
    roster = clean_roster_info(data["roster"])
    team = clean_team_stats(data["team"])
    ol = clean_ol_metrics(data["ol"])

    ngs_data = {}
    for stat_type in ["passing", "rushing", "receiving"]:
        try:
            ngs_data[stat_type] = fetch_ngs_data(stat_type, SEASONS)
        except Exception as exc:
            print(f"  Warning: NGS {stat_type} skipped: {exc}")

    df = build_feature_matrix(
        seasonal,
        roster,
        team,
        ol,
        snap_df=data.get("snap_counts"),
        schedule_df=data.get("schedules"),
        ngs_data=ngs_data,
        pfr_df=data.get("pfr"),
    )
    df = add_fantasy_points_to_df(df, format="half_ppr")
    df = compute_regression_to_mean_features(df)
    df = compute_stacking_features(df)

    adp = fetch_adp_data(seasons=SEASONS)
    df = compute_adp_features(df, adp)

    try:
        injury = fetch_injury_data([s for s in SEASONS if s <= MAX_STATS])
        df = compute_injury_features(df, injury)
    except Exception as exc:
        print(f"  Warning: injury skipped: {exc}")

    df = compute_sos_features(df)
    df = compute_rookie_features(df)
    df = compute_teammate_dependency_features(df)
    df = compute_college_features(
        df,
        draft_df=data.get("draft"),
        combine_df=data.get("combine"),
        player_info_df=data.get("player_info"),
        draft_values_df=data.get("draft_values"),
    )
    try:
        contracts = fetch_contracts()
        df = compute_contract_features(df, contracts)
    except Exception as exc:
        print(f"  Warning: contracts skipped: {exc}")
        df = compute_contract_features(df, pd.DataFrame())
    depth = fetch_depth_charts(SEASONS)
    df = compute_depth_chart_features(df, depth)
    df = compute_target_competition_features(df)
    return df


def validate_catboost(df: pd.DataFrame, features: dict[str, list[str]]) -> pd.DataFrame:
    original = copy.deepcopy(pipeline_mod.POSITION_FEATURES)
    try:
        pipeline_mod.POSITION_FEATURES.clear()
        pipeline_mod.POSITION_FEATURES.update(copy.deepcopy(features))

        pipe = PositionPipeline(models=[CatBoostModel()])
        results = pipe.validate_all(df, min_train_seasons=3)
        if results is None or results.empty:
            return pd.DataFrame()
        return results
    finally:
        pipeline_mod.POSITION_FEATURES.clear()
        pipeline_mod.POSITION_FEATURES.update(original)


def summarize(results_by_exp: dict[str, pd.DataFrame], reference: str) -> pd.DataFrame:
    rows = []
    ref = results_by_exp[reference].groupby("position").agg(ref_mae=("mae", "mean"), ref_r2=("r2", "mean"))

    for exp, results in results_by_exp.items():
        agg = results.groupby("position").agg(mae=("mae", "mean"), r2=("r2", "mean"), n=("n_players", "sum"))
        for pos, row in agg.iterrows():
            ref_row = ref.loc[pos]
            rows.append({
                "experiment": exp,
                "position": pos,
                "mae": row["mae"],
                "r2": row["r2"],
                "n_players": int(row["n"]),
                "ref_mae": ref_row["ref_mae"],
                "mae_delta": row["mae"] - ref_row["ref_mae"],
                "r2_delta": row["r2"] - ref_row["ref_r2"],
            })

    summary = pd.DataFrame(rows)
    pos_order = {p: i for i, p in enumerate(POSITIONS)}
    summary["_pos_order"] = summary["position"].map(pos_order)
    return summary.sort_values(["experiment", "_pos_order"]).drop(columns=["_pos_order"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments", nargs="+", default=["all"], help="Experiment names, or 'all'")
    parser.add_argument("--reference", default="clean_base")
    parser.add_argument("--out", default="feature_experiment_results.csv")
    parser.add_argument("--raw-out", default="feature_experiment_raw.csv")
    args = parser.parse_args()

    selected = list(EXPERIMENTS) if args.experiments == ["all"] else args.experiments
    unknown = [e for e in selected if e not in EXPERIMENTS]
    if unknown:
        raise SystemExit(f"Unknown experiments: {unknown}. Valid: {sorted(EXPERIMENTS)}")
    if args.reference not in selected:
        selected = [args.reference] + selected

    df = build_frame()
    base_features = copy.deepcopy(pipeline_mod.POSITION_FEATURES)

    results_by_exp: dict[str, pd.DataFrame] = {}
    raw_rows = []
    for exp in selected:
        print(f"\n### Experiment: {exp}")
        features = apply_experiment_features(base_features, EXPERIMENTS[exp])
        results = validate_catboost(df, features)
        results_by_exp[exp] = results
        tmp = results.copy()
        tmp["experiment"] = exp
        raw_rows.append(tmp)

    summary = summarize(results_by_exp, args.reference)
    raw = pd.concat(raw_rows, ignore_index=True)

    summary_path = REPO / args.out
    raw_path = REPO / args.raw_out
    summary.to_csv(summary_path, index=False)
    raw.to_csv(raw_path, index=False)

    print("\n=== Summary vs reference:", args.reference, "===")
    print(summary.round(4).to_string(index=False))
    print(f"\nWrote {summary_path}")
    print(f"Wrote {raw_path}")

    notes = {
        "reference": args.reference,
        "leakage_rules": [
            "Advanced stats are lagged by player before use.",
            "Schedule SOS uses released schedules and prior-season opponent defense.",
            "NGS stats are aggregated to player-season and shifted to the following season.",
            "Snap counts are aggregated to player-season and shifted to the following season.",
            "Availability features are lagged games played and rolling prior-season games.",
            "ADP-derived features use draft-market price and lagged player data only.",
            "Draft value features are static pick-value chart data known at draft time.",
            "Contract experiment features use only contracts signed before the modeled season.",
            "PFR advanced stats are shifted to the following season before use.",
            "Validation is walk-forward by season.",
        ],
    }
    print("\n" + json.dumps(notes, indent=2))


if __name__ == "__main__":
    main()
