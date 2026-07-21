#!/usr/bin/env python3
"""Summarize paired holdout tests for historical ADP dispersion.

Each distribution run contains ADP, guarded ADP, and Scarcity 2.0 policies.
The matching generic run contains Scarcity 2.0 with the old fixed spread. The
script refuses incomplete or non-pairable inputs so confidence intervals cannot
quietly compare different simulated drafts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PAIR_KEYS = ["season", "seed", "draft_slot", "roster_format"]
REQUIRED_COLUMNS = [
    *PAIR_KEYS,
    "strategy",
    "starter_points",
    "total_points",
    "league_rank",
    "field_avg_starter_points",
]


def _read_raw(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    return frame


def _policy_summary(frame: pd.DataFrame, *, case: str, policy: str) -> dict:
    return {
        "case": case,
        "policy": policy,
        "episodes": len(frame),
        "starter_points_mean": frame["starter_points"].mean(),
        "total_points_mean": frame["total_points"].mean(),
        "league_rank_mean": frame["league_rank"].mean(),
        "win_rate": frame["league_rank"].eq(1).mean(),
        "top3_rate": frame["league_rank"].le(3).mean(),
        "field_starter_points_mean": frame["field_avg_starter_points"].mean(),
    }


def paired_bootstrap_interval(
    delta: np.ndarray,
    *,
    resamples: int = 20_000,
    seed: int = 20_260_720,
    chunk_size: int = 1_000,
) -> tuple[float, float]:
    """Return a deterministic percentile CI for a paired mean difference."""
    values = np.asarray(delta, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("paired deltas must be a non-empty finite vector")
    if resamples < 2:
        raise ValueError("resamples must be at least 2")

    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    for start in range(0, resamples, chunk_size):
        stop = min(start + chunk_size, resamples)
        indices = rng.integers(0, len(values), size=(stop - start, len(values)))
        means[start:stop] = values[indices].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


def _paired_delta(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_label: str,
    right_label: str,
) -> pd.Series:
    for label, frame in [(left_label, left), (right_label, right)]:
        if frame.duplicated(PAIR_KEYS).any():
            raise ValueError(f"{label} has duplicate simulation keys")

    left_values = left.set_index(PAIR_KEYS)["starter_points"].sort_index()
    right_values = right.set_index(PAIR_KEYS)["starter_points"].sort_index()
    if not left_values.index.equals(right_values.index):
        only_left = len(left_values.index.difference(right_values.index))
        only_right = len(right_values.index.difference(left_values.index))
        raise ValueError(
            f"{left_label} and {right_label} do not pair exactly "
            f"({only_left} left-only, {only_right} right-only)"
        )
    return left_values - right_values


def summarize_case(
    case: str,
    distribution_path: Path,
    generic_path: Path,
    *,
    expected_episodes: int,
    resamples: int,
) -> tuple[list[dict], list[dict]]:
    distribution = _read_raw(distribution_path)
    generic = _read_raw(generic_path)
    expected_distribution = {"adp", "adp_guarded", "scarcity_v2"}
    if set(distribution["strategy"].unique()) != expected_distribution:
        raise ValueError(
            f"{distribution_path} must contain exactly {sorted(expected_distribution)}"
        )
    if set(generic["strategy"].unique()) != {"scarcity_v2"}:
        raise ValueError(f"{generic_path} must contain only scarcity_v2")

    policies = {
        "adp": distribution[distribution["strategy"].eq("adp")],
        "adp_guarded": distribution[distribution["strategy"].eq("adp_guarded")],
        "scarcity_distribution": distribution[
            distribution["strategy"].eq("scarcity_v2")
        ],
        "scarcity_generic": generic,
    }
    for policy, frame in policies.items():
        if len(frame) != expected_episodes:
            raise ValueError(
                f"{case}/{policy} has {len(frame)} episodes; "
                f"expected {expected_episodes}"
            )

    summaries = [
        _policy_summary(frame, case=case, policy=policy)
        for policy, frame in policies.items()
    ]
    comparisons = []
    for comparator in ["adp_guarded", "scarcity_generic"]:
        delta = _paired_delta(
            policies["scarcity_distribution"],
            policies[comparator],
            left_label=f"{case}/scarcity_distribution",
            right_label=f"{case}/{comparator}",
        )
        low, high = paired_bootstrap_interval(
            delta.to_numpy(), resamples=resamples
        )
        comparisons.append(
            {
                "case": case,
                "comparison": f"scarcity_distribution-minus-{comparator}",
                "episodes": len(delta),
                "mean_starter_points_delta": delta.mean(),
                "median_starter_points_delta": delta.median(),
                "ci95_low": low,
                "ci95_high": high,
                "positive_share": delta.gt(0).mean(),
                "tie_share": delta.eq(0).mean(),
            }
        )
    return summaries, comparisons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        action="append",
        nargs=3,
        metavar=("LABEL", "DISTRIBUTION_RAW", "GENERIC_RAW"),
        required=True,
        help="A label and the paired raw CSVs; repeat for additional cases.",
    )
    parser.add_argument("--expected-episodes", type=int, default=240)
    parser.add_argument("--resamples", type=int, default=20_000)
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=Path("experiments/scarcity_distribution_holdout_summary.csv"),
    )
    parser.add_argument(
        "--comparisons-out",
        type=Path,
        default=Path("experiments/scarcity_distribution_paired_comparisons.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summaries: list[dict] = []
    comparisons: list[dict] = []
    for label, distribution_path, generic_path in args.case:
        case_summaries, case_comparisons = summarize_case(
            label,
            Path(distribution_path),
            Path(generic_path),
            expected_episodes=args.expected_episodes,
            resamples=args.resamples,
        )
        summaries.extend(case_summaries)
        comparisons.extend(case_comparisons)

    summary = pd.DataFrame(summaries)
    comparison = pd.DataFrame(comparisons)
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.comparisons_out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_out, index=False, float_format="%.6f")
    comparison.to_csv(args.comparisons_out, index=False, float_format="%.6f")
    print(summary.to_string(index=False))
    print()
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
