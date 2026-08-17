#!/usr/bin/env python3
"""Historical fantasy-football league simulation for OverADP.

The simulation compares an ADP-first drafter with OverADP's guarded
"Target Intel" policy in paired 12-team leagues.  Every automated manager
uses the same point-in-time lineup and waiver logic.  Real weekly half-PPR
results supply injuries, absences, breakouts, and schedule variance.

This is a retrospective strategy backtest, not an untouched clinical trial:
the guarded policy was designed after these seasons were observable.  The
2025 market ordering is also an ESPN preseason-rank proxy, not true ADP.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


POSITIONS = ("QB", "RB", "WR", "TE")
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
FLEX_SLOTS = 2
ROUNDS = 15
MAX_BY_POSITION = {"QB": 2, "RB": 6, "WR": 7, "TE": 2}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}


@dataclass(frozen=True)
class SeasonInputs:
    season: int
    board: pd.DataFrame
    points: np.ndarray
    preseason_weekly: np.ndarray
    source_label: str
    true_adp: bool


def snake_order(teams: int = 12, rounds: int = ROUNDS) -> list[int]:
    order: list[int] = []
    for round_idx in range(rounds):
        row = list(range(teams))
        if round_idx % 2:
            row.reverse()
        order.extend(row)
    return order


def position_counts(roster: list[int], positions: np.ndarray) -> dict[str, int]:
    counts = {p: 0 for p in POSITIONS}
    for idx in roster:
        pos = str(positions[idx])
        if pos in counts:
            counts[pos] += 1
    return counts


def roster_needs(roster: list[int], positions: np.ndarray) -> dict[str, float]:
    counts = position_counts(roster, positions)
    needs = {p: float(max(0, STARTERS[p] - counts[p])) for p in POSITIONS}
    flex_have = sum(max(0, counts[p] - STARTERS[p]) for p in FLEX_ELIGIBLE)
    needs["FLEX"] = float(max(0, FLEX_SLOTS - flex_have))
    return needs


def legal_candidates(
    available: np.ndarray,
    roster: list[int],
    positions: np.ndarray,
    adp: np.ndarray,
    round_num: int,
    limit: int = 70,
) -> np.ndarray:
    counts = position_counts(roster, positions)
    queue = np.argsort(adp, kind="stable")
    choices = []
    for i in queue:
        pos = str(positions[i])
        if not available[i] or counts[pos] >= MAX_BY_POSITION[pos]:
            continue
        # A realistic one-QB home league rarely spends early capital on a
        # second QB or TE. Apply the same rule to every automated manager.
        if round_num < 10 and pos in {"QB", "TE"} and counts[pos] >= STARTERS[pos]:
            continue
        choices.append(int(i))
        if len(choices) >= limit:
            break
    return np.asarray(choices[:limit], dtype=int)


def market_pick(
    candidates: np.ndarray,
    roster: list[int],
    positions: np.ndarray,
    adp: np.ndarray,
    rng: np.random.Generator,
    noise: float,
) -> int:
    needs = roster_needs(roster, positions)
    pos = positions[candidates]
    need_bonus = np.asarray(
        [22.0 * needs[str(p)] + (8.0 * needs["FLEX"] if p in FLEX_ELIGIBLE else 0.0) for p in pos]
    )
    random_term = np.zeros(len(candidates)) if noise == 0 else rng.normal(0.0, noise, len(candidates))
    score = -adp[candidates] + need_bonus + random_term
    return int(candidates[int(np.argmax(score))])


def next_pick_number(order: list[int], current_pick: int, team_idx: int) -> int:
    for offset in range(current_pick, len(order)):
        if order[offset] == team_idx:
            return offset + 1
    return len(order) + 1


def target_intel_pick(
    candidates: np.ndarray,
    roster: list[int],
    positions: np.ndarray,
    adp: np.ndarray,
    projections: np.ndarray,
    vbd: np.ndarray,
    pick_number: int,
    next_pick: int,
    teams: int,
) -> int:
    """ADP anchor plus roster value and probability a target makes it back."""
    needs = roster_needs(roster, positions)
    counts = position_counts(roster, positions)
    pos = positions[candidates]
    cand_adp = adp[candidates]
    cand_proj = projections[candidates]
    cand_vbd = vbd[candidates]
    pick_gap = max(1, next_pick - pick_number)
    round_num = ((pick_number - 1) // teams) + 1

    starter_need = np.asarray([needs[str(p)] for p in pos])
    flex_need = np.asarray([needs["FLEX"] if p in FLEX_ELIGIBLE else 0.0 for p in pos])
    pos_count = np.asarray([counts[str(p)] for p in pos])
    late_need = ((round_num >= 8) & (starter_need > 0)).astype(float)
    rb_bias = (pos == "RB").astype(float)

    gone_scale = max(6.0, min(16.0, pick_gap / 2.5))
    p_gone = 1.0 / (1.0 + np.exp(-np.clip((next_pick - cand_adp) / gone_scale, -30, 30)))
    p_available = 1.0 - p_gone
    wait_same = np.zeros(len(candidates), dtype=float)
    for player_pos in POSITIONS:
        mask = pos == player_pos
        local = cand_vbd[mask] * p_available[mask]
        if len(local) < 2:
            continue
        ranked = np.argsort(-local)
        best, second = local[ranked[0]], local[ranked[1]]
        wait_same[mask] = np.where(np.arange(len(local)) == ranked[0], second, best)

    urgency = p_gone * np.maximum(0.0, cand_vbd - wait_same)
    adp_value = np.clip(pick_number - cand_adp, 0.0, 45.0)
    reach = np.clip(cand_adp - pick_number - pick_gap * 0.65, 0.0, 90.0)
    need_bonus = 24.0 * starter_need + 9.0 * flex_need + 10.0 * late_need
    depth_penalty = np.maximum(0.0, pos_count - starter_need - flex_need - 1.0) * 3.0

    score = (
        -cand_adp
        + 0.10 * cand_proj
        + 0.34 * cand_vbd
        + need_bonus
        + 1.25 * urgency
        + 0.45 * adp_value
        - 0.85 * reach
        - depth_penalty
        + 2.5 * rb_bias
    )
    return int(candidates[int(np.argmax(score))])


def model_pick(
    candidates: np.ndarray,
    roster: list[int],
    positions: np.ndarray,
    projections: np.ndarray,
    vbd: np.ndarray,
) -> int:
    needs = roster_needs(roster, positions)
    pos = positions[candidates]
    need_bonus = np.asarray(
        [22.0 * needs[str(p)] + (8.0 * needs["FLEX"] if p in FLEX_ELIGIBLE else 0.0) for p in pos]
    )
    return int(candidates[int(np.argmax(projections[candidates] + 0.25 * vbd[candidates] + need_bonus))])


def run_draft(inputs: SeasonInputs, strategy: str, seed: int, draft_slot: int) -> list[list[int]]:
    board = inputs.board
    positions = board["position"].to_numpy(dtype=str)
    adp = board["adp"].to_numpy(dtype=float)
    projections = board["projected_points"].to_numpy(dtype=float)
    vbd = board["vbd"].to_numpy(dtype=float)
    order = snake_order()
    rosters: list[list[int]] = [[] for _ in range(12)]
    available = np.ones(len(board), dtype=bool)
    controlled_team = draft_slot - 1
    rng = np.random.default_rng(seed)

    for pick_number, team_idx in enumerate(order, start=1):
        round_num = ((pick_number - 1) // 12) + 1
        choices = legal_candidates(available, rosters[team_idx], positions, adp, round_num)
        if not len(choices):
            raise RuntimeError("Draft board ran out of legal players")
        if team_idx != controlled_team:
            chosen = market_pick(choices, rosters[team_idx], positions, adp, rng, noise=8.0)
        elif strategy == "adp":
            chosen = market_pick(choices, rosters[team_idx], positions, adp, rng, noise=0.0)
        elif strategy == "target_intel":
            chosen = target_intel_pick(
                choices,
                rosters[team_idx],
                positions,
                adp,
                projections,
                vbd,
                pick_number,
                next_pick_number(order, pick_number, controlled_team),
                12,
            )
        elif strategy == "model_only":
            chosen = model_pick(choices, rosters[team_idx], positions, projections, vbd)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
        rosters[team_idx].append(chosen)
        available[chosen] = False
    return rosters


def choose_lineup(roster: list[int], positions: np.ndarray, expected: np.ndarray) -> list[int]:
    chosen: list[int] = []
    remaining = set(roster)
    for pos, count in STARTERS.items():
        candidates = [i for i in remaining if positions[i] == pos]
        starters = sorted(candidates, key=lambda i: expected[i], reverse=True)[:count]
        chosen.extend(starters)
        remaining.difference_update(starters)
    flex = [i for i in remaining if positions[i] in FLEX_ELIGIBLE]
    chosen.extend(sorted(flex, key=lambda i: expected[i], reverse=True)[:FLEX_SLOTS])
    return chosen


def expected_points(inputs: SeasonInputs, week_index: int) -> np.ndarray:
    """Weekly forecast using preseason expectation plus only prior observed weeks."""
    if week_index == 0:
        return inputs.preseason_weekly.copy()
    start = max(0, week_index - 3)
    recent = inputs.points[:, start:week_index]
    games = recent.shape[1]
    return (2.0 * inputs.preseason_weekly + recent.sum(axis=1)) / (2.0 + games)


def run_waivers(
    rosters: list[list[int]],
    free_agents: set[int],
    positions: np.ndarray,
    expected: np.ndarray,
    cumulative_points: np.ndarray,
) -> None:
    """One conservative same-position transaction per team per week."""
    for team_idx in np.argsort(cumulative_points):
        if not free_agents:
            break
        roster = rosters[int(team_idx)]
        lineup = set(choose_lineup(roster, positions, expected))
        bench = [i for i in roster if i not in lineup]
        best_move: tuple[float, int, int] | None = None
        for incoming in sorted(free_agents, key=lambda i: expected[i], reverse=True)[:80]:
            same_pos = [i for i in bench if positions[i] == positions[incoming]]
            if not same_pos:
                continue
            outgoing = min(same_pos, key=lambda i: expected[i])
            gain = float(expected[incoming] - expected[outgoing])
            if gain >= 1.5 and (best_move is None or gain > best_move[0]):
                best_move = (gain, incoming, outgoing)
        if best_move is None:
            continue
        _, incoming, outgoing = best_move
        roster.remove(outgoing)
        roster.append(incoming)
        free_agents.remove(incoming)
        free_agents.add(outgoing)


def weekly_lineup_scores(inputs: SeasonInputs, drafted: list[list[int]]) -> tuple[np.ndarray, np.ndarray]:
    positions = inputs.board["position"].to_numpy(dtype=str)
    rosters = [list(r) for r in drafted]
    free_agents = set(range(len(inputs.board))) - {i for roster in rosters for i in roster}
    managed = np.zeros((12, 17), dtype=float)
    optimal = np.zeros((12, 17), dtype=float)
    cumulative = np.zeros(12, dtype=float)

    for week_idx in range(17):
        expected = expected_points(inputs, week_idx)
        if week_idx > 0:
            run_waivers(rosters, free_agents, positions, expected, cumulative)
        for team_idx, roster in enumerate(rosters):
            lineup = choose_lineup(roster, positions, expected)
            oracle_lineup = choose_lineup(roster, positions, inputs.points[:, week_idx])
            managed[team_idx, week_idx] = inputs.points[lineup, week_idx].sum()
            optimal[team_idx, week_idx] = inputs.points[oracle_lineup, week_idx].sum()
        cumulative += managed[:, week_idx]
    return managed, optimal


def round_robin_schedule(teams: int = 12, weeks: int = 14) -> list[list[tuple[int, int]]]:
    rotation = list(range(teams))
    rounds: list[list[tuple[int, int]]] = []
    for _ in range(teams - 1):
        rounds.append([(rotation[i], rotation[-1 - i]) for i in range(teams // 2)])
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return [rounds[i % len(rounds)] for i in range(weeks)]


def standings(scores: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    wins = np.zeros(12, dtype=float)
    for week_idx, games in enumerate(round_robin_schedule()):
        for left, right in games:
            if scores[left, week_idx] > scores[right, week_idx]:
                wins[left] += 1
            elif scores[right, week_idx] > scores[left, week_idx]:
                wins[right] += 1
            else:
                wins[left] += 0.5
                wins[right] += 0.5
    points = scores[:, :14].sum(axis=1)
    order = np.lexsort((-points, -wins))
    ranks = np.empty(12, dtype=int)
    ranks[order] = np.arange(1, 13)
    return order, ranks, wins


def playoff_champion(scores: np.ndarray, regular_order: np.ndarray) -> int:
    seeds = list(map(int, regular_order[:6]))

    def winner(left: int, right: int, week_idx: int) -> int:
        if scores[left, week_idx] == scores[right, week_idx]:
            return left if seeds.index(left) < seeds.index(right) else right
        return left if scores[left, week_idx] > scores[right, week_idx] else right

    qf_a = winner(seeds[2], seeds[5], 14)
    qf_b = winner(seeds[3], seeds[4], 14)
    advancing = sorted([qf_a, qf_b], key=seeds.index)
    sf_a = winner(seeds[0], advancing[-1], 15)
    sf_b = winner(seeds[1], advancing[0], 15)
    return winner(sf_a, sf_b, 16)


def load_inputs(board_path: Path, weekly_path: Path, seasons: list[int]) -> dict[int, SeasonInputs]:
    boards = pd.read_parquet(board_path)
    weekly = pd.read_parquet(weekly_path)
    weekly = weekly[(weekly["season_type"] == "REG") & weekly["position"].isin(POSITIONS)].copy()
    weekly["half_ppr"] = (
        pd.to_numeric(weekly["fantasy_points"], errors="coerce").fillna(0.0)
        + pd.to_numeric(weekly["fantasy_points_ppr"], errors="coerce").fillna(0.0)
    ) / 2.0

    output: dict[int, SeasonInputs] = {}
    for season in seasons:
        board = boards[boards["season"] == season].copy().reset_index(drop=True)
        if board.empty:
            raise ValueError(f"No cached point-in-time board for {season}")
        board = board[board["position"].isin(POSITIONS)].copy().reset_index(drop=True)
        by_player_week = (
            weekly[weekly["season"] == season]
            .pivot_table(index="player_id", columns="week", values="half_ppr", aggfunc="sum", fill_value=0.0)
            .reindex(columns=range(1, 18), fill_value=0.0)
        )
        points = by_player_week.reindex(board["player_id"]).fillna(0.0).to_numpy(dtype=float)
        preseason = np.clip(board["projected_points"].to_numpy(dtype=float) / 17.0, 0.0, None)
        true_adp = season in (2023, 2024)
        output[season] = SeasonInputs(
            season=season,
            board=board,
            points=points,
            preseason_weekly=preseason,
            source_label="Fantasy Football Calculator ADP" if true_adp else "ESPN preseason-rank proxy",
            true_adp=true_adp,
        )
    return output


def simulate(inputs: dict[int, SeasonInputs], episodes: int, seed: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    strategies = ("adp", "target_intel", "model_only")
    for season, season_inputs in sorted(inputs.items()):
        for episode in range(episodes):
            draft_slot = 1 + (episode % 12)
            episode_seed = seed * 1_000_000 + season * 10_000 + episode
            for strategy in strategies:
                rosters = run_draft(season_inputs, strategy, episode_seed, draft_slot)
                managed, optimal = weekly_lineup_scores(season_inputs, rosters)
                regular_order, ranks, wins = standings(managed)
                champion = playoff_champion(managed, regular_order)
                controlled = draft_slot - 1
                rows.append(
                    {
                        "season": season,
                        "adp_source": season_inputs.source_label,
                        "true_adp": season_inputs.true_adp,
                        "episode": episode,
                        "seed": episode_seed,
                        "draft_slot": draft_slot,
                        "strategy": strategy,
                        "regular_rank": int(ranks[controlled]),
                        "regular_wins": float(wins[controlled]),
                        "managed_points": float(managed[controlled, :14].sum()),
                        "oracle_lineup_points": float(optimal[controlled, :14].sum()),
                        "made_playoffs": bool(ranks[controlled] <= 6),
                        "champion": bool(champion == controlled),
                    }
                )
    return pd.DataFrame(rows)


def summarize(raw: pd.DataFrame) -> pd.DataFrame:
    return (
        raw.groupby(["season", "adp_source", "true_adp", "strategy"], sort=True)
        .agg(
            simulations=("episode", "size"),
            avg_regular_rank=("regular_rank", "mean"),
            first_place_rate=("regular_rank", lambda s: float((s == 1).mean())),
            top3_rate=("regular_rank", lambda s: float((s <= 3).mean())),
            playoff_rate=("made_playoffs", "mean"),
            championship_rate=("champion", "mean"),
            managed_points=("managed_points", "mean"),
            oracle_lineup_points=("oracle_lineup_points", "mean"),
        )
        .reset_index()
    )


def paired_summary(raw: pd.DataFrame) -> pd.DataFrame:
    baseline = raw[raw["strategy"] == "adp"].set_index(["season", "episode"])
    rows: list[dict[str, object]] = []
    for strategy in ("target_intel", "model_only"):
        challenger = raw[raw["strategy"] == strategy].set_index(["season", "episode"])
        joined = challenger.join(baseline, lsuffix="_challenger", rsuffix="_adp")
        for season, group in joined.groupby(level="season"):
            rank_delta = group["regular_rank_adp"] - group["regular_rank_challenger"]
            points_delta = group["managed_points_challenger"] - group["managed_points_adp"]
            rows.append(
                {
                    "season": int(season),
                    "strategy": strategy,
                    "paired_simulations": int(len(group)),
                    "avg_rank_improvement_vs_adp": float(rank_delta.mean()),
                    "avg_points_delta_vs_adp": float(points_delta.mean()),
                    "beat_adp_rank_rate": float((rank_delta > 0).mean()),
                    "tied_adp_rank_rate": float((rank_delta == 0).mean()),
                    "points_delta_p05": float(points_delta.quantile(0.05)),
                    "points_delta_p95": float(points_delta.quantile(0.95)),
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
    inputs = load_inputs(args.board, args.weekly, args.seasons)
    raw = simulate(inputs, args.episodes, args.seed)
    summary = summarize(raw)
    paired = paired_summary(raw)

    raw.to_csv(args.output_dir / "simulation_raw.csv", index=False)
    summary.to_csv(args.output_dir / "simulation_summary.csv", index=False)
    paired.to_csv(args.output_dir / "paired_summary.csv", index=False)
    metadata = {
        "league": "12 teams; 1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX, 7 bench; half-PPR",
        "regular_season": "Weeks 1-14; head-to-head; points tiebreaker",
        "playoffs": "Top 6; Weeks 15-17; top two seeds receive byes",
        "management": "Trailing-three-week plus preseason lineups; one conservative same-position waiver per team/week",
        "draft_guardrails": "No backup QB or TE before Round 10; identical positional caps for every manager",
        "strategies": ["adp", "target_intel", "model_only"],
        "seasons": args.seasons,
        "episodes_per_strategy_season": args.episodes,
        "seed": args.seed,
        "limitations": [
            "Retrospective exploratory backtest; the strategy was not frozen before these seasons.",
            "2025 uses an ESPN preseason-rank proxy instead of true market ADP.",
            "No trades, defenses, kickers, FAAB bids, or explicit injury designations.",
            "Injuries and absences enter through actual weekly fantasy points.",
            "Opponent behavior is a noisy ADP-and-roster-need approximation, not observed league drafts.",
        ],
    }
    (args.output_dir / "simulation_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(summary.to_string(index=False))
    print("\nPaired comparisons\n", paired.to_string(index=False))


if __name__ == "__main__":
    main()
