#!/usr/bin/env python3
"""Decompose OverADP results into draft, lineup, and waiver layers."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
SIM_PATH = HERE / "run_historical_league_sim.py"
SPEC = importlib.util.spec_from_file_location("historical_league_sim", SIM_PATH)
sim = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = sim
SPEC.loader.exec_module(sim)

MODES = ("frozen_lineup", "weekly_lineups", "lineups_plus_waivers")


def score_management_modes(inputs, drafted: list[list[int]]) -> dict[str, np.ndarray]:
    """Score the same drafted teams under three increasingly active managers."""
    positions = inputs.board["position"].to_numpy(dtype=str)
    frozen_lineups = [sim.choose_lineup(roster, positions, inputs.preseason_weekly) for roster in drafted]
    frozen = np.zeros((12, 17), dtype=float)
    lineup_only = np.zeros((12, 17), dtype=float)
    full = np.zeros((12, 17), dtype=float)

    waiver_rosters = [list(roster) for roster in drafted]
    free_agents = set(range(len(inputs.board))) - {i for roster in waiver_rosters for i in roster}
    cumulative_full = np.zeros(12, dtype=float)

    for week_idx in range(17):
        expected = sim.expected_points(inputs, week_idx)
        if week_idx > 0:
            sim.run_waivers(waiver_rosters, free_agents, positions, expected, cumulative_full)
        for team_idx in range(12):
            frozen[team_idx, week_idx] = inputs.points[frozen_lineups[team_idx], week_idx].sum()
            lineup = sim.choose_lineup(drafted[team_idx], positions, expected)
            lineup_only[team_idx, week_idx] = inputs.points[lineup, week_idx].sum()
            full_lineup = sim.choose_lineup(waiver_rosters[team_idx], positions, expected)
            full[team_idx, week_idx] = inputs.points[full_lineup, week_idx].sum()
        cumulative_full += full[:, week_idx]

    return {
        "frozen_lineup": frozen,
        "weekly_lineups": lineup_only,
        "lineups_plus_waivers": full,
    }


def simulate_decomposition(inputs: dict[int, object], episodes: int, seed: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season, season_inputs in sorted(inputs.items()):
        for episode in range(episodes):
            draft_slot = 1 + (episode % 12)
            episode_seed = seed * 1_000_000 + season * 10_000 + episode
            controlled = draft_slot - 1
            for strategy in ("adp", "target_intel", "model_only"):
                drafted = sim.run_draft(season_inputs, strategy, episode_seed, draft_slot)
                mode_scores = score_management_modes(season_inputs, drafted)
                for mode, scores in mode_scores.items():
                    regular_order, ranks, wins = sim.standings(scores)
                    champion = sim.playoff_champion(scores, regular_order)
                    rows.append(
                        {
                            "season": season,
                            "adp_source": season_inputs.source_label,
                            "true_adp": season_inputs.true_adp,
                            "episode": episode,
                            "seed": episode_seed,
                            "draft_slot": draft_slot,
                            "strategy": strategy,
                            "management_mode": mode,
                            "regular_rank": int(ranks[controlled]),
                            "regular_wins": float(wins[controlled]),
                            "points": float(scores[controlled, :14].sum()),
                            "made_playoffs": bool(ranks[controlled] <= 6),
                            "champion": bool(champion == controlled),
                        }
                    )
    return pd.DataFrame(rows)


def summarize(raw: pd.DataFrame) -> pd.DataFrame:
    return (
        raw.groupby(
            ["season", "adp_source", "true_adp", "management_mode", "strategy"],
            sort=True,
        )
        .agg(
            simulations=("episode", "size"),
            avg_regular_rank=("regular_rank", "mean"),
            first_place_rate=("regular_rank", lambda s: float((s == 1).mean())),
            top3_rate=("regular_rank", lambda s: float((s <= 3).mean())),
            playoff_rate=("made_playoffs", "mean"),
            championship_rate=("champion", "mean"),
            points=("points", "mean"),
        )
        .reset_index()
    )


def paired_strategy_lift(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (season, mode), frame in raw.groupby(["season", "management_mode"]):
        wide = frame.pivot(index="episode", columns="strategy", values=["regular_rank", "points"])
        for challenger in ("target_intel", "model_only"):
            rank_delta = wide["regular_rank"]["adp"] - wide["regular_rank"][challenger]
            point_delta = wide["points"][challenger] - wide["points"]["adp"]
            rows.append(
                {
                    "season": int(season),
                    "management_mode": mode,
                    "strategy": challenger,
                    "paired_simulations": int(len(wide)),
                    "avg_rank_improvement_vs_adp": float(rank_delta.mean()),
                    "avg_points_delta_vs_adp": float(point_delta.mean()),
                    "beat_adp_rank_rate": float((rank_delta > 0).mean()),
                }
            )
    return pd.DataFrame(rows)


def management_lift(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (season, strategy), frame in raw.groupby(["season", "strategy"]):
        wide = frame.pivot(index="episode", columns="management_mode", values=["regular_rank", "points"])
        for mode in ("weekly_lineups", "lineups_plus_waivers"):
            rows.append(
                {
                    "season": int(season),
                    "strategy": strategy,
                    "management_mode": mode,
                    "paired_simulations": int(len(wide)),
                    "rank_improvement_vs_frozen": float(
                        (wide["regular_rank"]["frozen_lineup"] - wide["regular_rank"][mode]).mean()
                    ),
                    "points_added_vs_frozen": float(
                        (wide["points"][mode] - wide["points"]["frozen_lineup"]).mean()
                    ),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--weekly", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024, 2025])
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--seed", type=int, default=73)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    inputs = sim.load_inputs(args.board, args.weekly, args.seasons)
    raw = simulate_decomposition(inputs, args.episodes, args.seed)
    summary = summarize(raw)
    strategy_lift = paired_strategy_lift(raw)
    manager_lift = management_lift(raw)

    raw.to_csv(args.output_dir / "management_decomposition_raw.csv", index=False)
    summary.to_csv(args.output_dir / "management_decomposition_summary.csv", index=False)
    strategy_lift.to_csv(args.output_dir / "management_strategy_lift.csv", index=False)
    manager_lift.to_csv(args.output_dir / "management_incremental_lift.csv", index=False)
    metadata = {
        "modes": {
            "frozen_lineup": "Week-1 lineup selected from preseason projections and never changed; no waivers.",
            "weekly_lineups": "Weekly start/sit decisions use preseason plus only prior observed results; no waivers.",
            "lineups_plus_waivers": "Weekly start/sit decisions plus one conservative same-position waiver move per team/week.",
        },
        "pairing": "Identical season, seed, and draft slot across strategies and management modes.",
        "primary_evidence": "2023-2024 true Fantasy Football Calculator ADP.",
        "sensitivity_only": "2025 ESPN preseason-rank proxy.",
        "episodes_per_strategy_season": args.episodes,
        "seed": args.seed,
    }
    (args.output_dir / "management_decomposition_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
