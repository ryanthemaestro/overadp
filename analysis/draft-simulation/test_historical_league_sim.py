import importlib.util
from pathlib import Path
import sys

import numpy as np


MODULE_PATH = Path(__file__).with_name("run_historical_league_sim.py")
SPEC = importlib.util.spec_from_file_location("historical_league_sim", MODULE_PATH)
sim = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = sim
SPEC.loader.exec_module(sim)


def test_snake_order_has_every_team_once_per_round():
    order = sim.snake_order(12, 15)
    assert len(order) == 180
    for start in range(0, len(order), 12):
        assert sorted(order[start : start + 12]) == list(range(12))


def test_schedule_has_one_game_per_team_per_week():
    schedule = sim.round_robin_schedule(12, 14)
    assert len(schedule) == 14
    for games in schedule:
        teams = [team for game in games for team in game]
        assert sorted(teams) == list(range(12))


def test_standings_rank_all_teams_once():
    scores = np.arange(12 * 17, dtype=float).reshape(12, 17)
    order, ranks, wins = sim.standings(scores)
    assert sorted(order.tolist()) == list(range(12))
    assert sorted(ranks.tolist()) == list(range(1, 13))
    assert wins.sum() == 14 * 6


def test_half_ppr_inputs_have_expected_shape():
    inputs = sim.load_inputs(
        Path("/home/nar/Documents/nflmodel-experiments/snake_draft_boards.parquet"),
        Path("/home/nar/Documents/nflmodel/data/weekly_stats.parquet"),
        [2023],
    )[2023]
    assert inputs.points.shape == (len(inputs.board), 17)
    assert np.isfinite(inputs.points).all()
    assert (inputs.points >= -5).all()


def test_draft_has_unique_players_and_legal_roster_sizes():
    inputs = sim.load_inputs(
        Path("/home/nar/Documents/nflmodel-experiments/snake_draft_boards.parquet"),
        Path("/home/nar/Documents/nflmodel/data/weekly_stats.parquet"),
        [2023],
    )[2023]
    rosters = sim.run_draft(inputs, "target_intel", seed=731, draft_slot=6)
    all_players = [player for roster in rosters for player in roster]
    assert all(len(roster) == 15 for roster in rosters)
    assert len(all_players) == len(set(all_players)) == 180
    positions = inputs.board["position"].to_numpy(dtype=str)
    for roster in rosters:
        counts = sim.position_counts(roster, positions)
        assert all(counts[pos] <= sim.MAX_BY_POSITION[pos] for pos in sim.POSITIONS)
