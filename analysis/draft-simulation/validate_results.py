#!/usr/bin/env python3
"""Independent result-contract checks for the historical simulation."""
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
raw = pd.read_csv(ROOT / "results" / "simulation_raw.csv")

assert len(raw) == 3 * 3 * 500, f"unexpected row count: {len(raw)}"
assert raw[["season", "episode", "strategy"]].duplicated().sum() == 0
assert set(raw["season"]) == {2023, 2024, 2025}
assert set(raw["strategy"]) == {"adp", "target_intel", "model_only"}
assert raw.groupby(["season", "strategy"]).size().eq(500).all()
assert raw["regular_rank"].between(1, 12).all()
assert raw["regular_wins"].between(0, 14).all()
assert np.isfinite(raw[["regular_wins", "managed_points", "oracle_lineup_points"]]).all().all()
assert (raw["oracle_lineup_points"] >= raw["managed_points"] - 1e-9).all()

# Paired runs must use the same slot and seed for each strategy.
pairing = raw.groupby(["season", "episode"])[["seed", "draft_slot"]].nunique()
assert pairing.eq(1).all().all()

# Source labeling is part of the claim boundary.
assert raw.loc[raw["season"].isin([2023, 2024]), "true_adp"].all()
assert not raw.loc[raw["season"] == 2025, "true_adp"].any()

print("Result validation passed")
print(raw.groupby(["season", "strategy"]).size().to_string())
