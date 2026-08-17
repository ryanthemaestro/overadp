import importlib.util
from pathlib import Path
import sys

import numpy as np


MODULE_PATH = Path(__file__).with_name("run_management_decomposition.py")
SPEC = importlib.util.spec_from_file_location("management_decomposition", MODULE_PATH)
decomp = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = decomp
SPEC.loader.exec_module(decomp)


def test_management_modes_score_same_draft_and_expected_shape():
    inputs = decomp.sim.load_inputs(
        Path("/home/nar/Documents/nflmodel-experiments/snake_draft_boards.parquet"),
        Path("/home/nar/Documents/nflmodel/data/weekly_stats.parquet"),
        [2023],
    )[2023]
    drafted = decomp.sim.run_draft(inputs, "target_intel", seed=731, draft_slot=6)
    scores = decomp.score_management_modes(inputs, drafted)
    assert set(scores) == set(decomp.MODES)
    assert all(value.shape == (12, 17) for value in scores.values())
    assert all(np.isfinite(value).all() for value in scores.values())


def test_decomposition_has_complete_paired_cells():
    inputs = decomp.sim.load_inputs(
        Path("/home/nar/Documents/nflmodel-experiments/snake_draft_boards.parquet"),
        Path("/home/nar/Documents/nflmodel/data/weekly_stats.parquet"),
        [2023],
    )
    raw = decomp.simulate_decomposition(inputs, episodes=2, seed=73)
    assert len(raw) == 2 * 3 * 3
    assert raw.groupby(["season", "episode"])[["seed", "draft_slot"]].nunique().eq(1).all().all()
    assert raw.groupby(["season", "episode", "strategy"]).size().eq(3).all()
