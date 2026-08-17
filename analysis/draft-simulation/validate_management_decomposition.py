#!/usr/bin/env python3
"""Validate completeness and pairing for management-layer attribution."""
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
raw = pd.read_csv(ROOT / "results" / "management_decomposition_raw.csv")
saved_summary = pd.read_csv(ROOT / "results" / "management_decomposition_summary.csv")

assert len(raw) == 3 * 3 * 3 * 500, f"unexpected row count: {len(raw)}"
assert not raw.duplicated(["season", "episode", "strategy", "management_mode"]).any()
assert set(raw["season"]) == {2023, 2024, 2025}
assert set(raw["strategy"]) == {"adp", "target_intel", "model_only"}
assert set(raw["management_mode"]) == {
    "frozen_lineup",
    "weekly_lineups",
    "lineups_plus_waivers",
}
assert raw.groupby(["season", "strategy", "management_mode"]).size().eq(500).all()
assert raw["regular_rank"].between(1, 12).all()
assert raw["regular_wins"].between(0, 14).all()
assert np.isfinite(raw[["regular_wins", "points"]]).all().all()

pairing = raw.groupby(["season", "episode"])[["seed", "draft_slot"]].nunique()
assert pairing.eq(1).all().all()
mode_completeness = raw.groupby(["season", "episode", "strategy"])["management_mode"].nunique()
assert mode_completeness.eq(3).all()

# The two primary seasons and proxy sensitivity must never be pooled silently.
assert raw.loc[raw["season"].isin([2023, 2024]), "true_adp"].all()
assert not raw.loc[raw["season"] == 2025, "true_adp"].any()

# Independently recompute the highest-impact aggregate fields from raw rows.
recomputed = (
    raw.groupby(["season", "management_mode", "strategy"])
    .agg(
        avg_regular_rank=("regular_rank", "mean"),
        top3_rate=("regular_rank", lambda s: float((s <= 3).mean())),
        playoff_rate=("made_playoffs", "mean"),
        points=("points", "mean"),
    )
    .reset_index()
)
check = saved_summary.merge(
    recomputed,
    on=["season", "management_mode", "strategy"],
    suffixes=("_saved", "_recomputed"),
    validate="one_to_one",
)
for field in ("avg_regular_rank", "top3_rate", "playoff_rate", "points"):
    assert np.allclose(check[f"{field}_saved"], check[f"{field}_recomputed"], atol=1e-12)

print("Management decomposition validation passed")
print(raw.groupby(["season", "management_mode", "strategy"]).size().to_string())
