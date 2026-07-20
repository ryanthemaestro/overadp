"""Tests for paired Scarcity 2.0 validation summaries."""

import numpy as np
import pandas as pd
import pytest

from scripts.summarize_scarcity_distribution_validation import (
    _paired_delta,
    paired_bootstrap_interval,
)


def _results(points):
    return pd.DataFrame(
        {
            "season": [2025] * len(points),
            "seed": range(len(points)),
            "draft_slot": [1] * len(points),
            "roster_format": ["standard"] * len(points),
            "starter_points": points,
        }
    )


def test_paired_delta_matches_simulation_keys_not_row_order():
    left = _results([110.0, 120.0, 130.0])
    right = _results([100.0, 115.0, 140.0]).iloc[::-1]

    delta = _paired_delta(left, right, left_label="left", right_label="right")

    np.testing.assert_allclose(delta.to_numpy(), [10.0, 5.0, -10.0])


def test_paired_delta_rejects_nonmatching_simulations():
    left = _results([110.0, 120.0])
    right = _results([100.0, 115.0])
    right.loc[1, "seed"] = 9

    with pytest.raises(ValueError, match="do not pair exactly"):
        _paired_delta(left, right, left_label="left", right_label="right")


def test_bootstrap_interval_is_deterministic_and_directional():
    delta = np.asarray([2.0, 3.0, 4.0, 5.0])

    first = paired_bootstrap_interval(delta, resamples=2_000, seed=7)
    second = paired_bootstrap_interval(delta, resamples=2_000, seed=7)

    assert first == second
    assert first[0] > 0
