"""Tests for historical FFC ADP distribution ingestion and quality gates."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.data.ffc_adp import (
    SnapshotKey,
    enrich_board_with_adp_distribution,
    normalize_snapshot,
    profile_snapshots,
    replace_snapshots,
    validate_payload,
)


def _payload(*, teams=12, season=2024, scoring="PPR", players=50):
    return {
        "status": "Success",
        "meta": {
            "type": scoring,
            "teams": teams,
            "rounds": 15,
            "total_drafts": 900,
            "start_date": f"{season}-08-20",
            "end_date": f"{season}-09-01",
        },
        "players": [
            {
                "player_id": index,
                "name": (
                    f"Player {chr(65 + (index - 1) // 26)}"
                    f"{chr(65 + (index - 1) % 26)}"
                ),
                "position": "PK" if index == players else "WR",
                "team": "NYJ",
                "adp": float(index),
                "adp_formatted": f"1.{index:02}",
                "times_drafted": 100,
                "high": max(1, index - 1),
                "low": index + 2,
                "stdev": 1.5,
                "bye": 12,
            }
            for index in range(1, players + 1)
        ],
    }


def test_snapshot_preserves_distribution_and_provenance_fields():
    fetched_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    frame = normalize_snapshot(
        SnapshotKey(2024, "ppr", 12), _payload(), fetched_at=fetched_at
    )

    assert len(frame) == 50
    assert frame.iloc[0]["adp_sd"] == 1.5
    assert frame.iloc[0]["earliest_pick"] == 1
    assert frame.iloc[0]["latest_pick"] == 3
    assert frame.iloc[0]["times_drafted"] == 100
    assert frame.iloc[-1]["position"] == "K"
    assert frame["source_end_date"].unique().tolist() == ["2024-09-01"]
    assert frame["fetched_at"].unique().tolist() == ["2026-07-20T00:00:00+00:00"]


def test_payload_rejects_silent_team_size_substitution():
    with pytest.raises(ValueError, match="returned 12-team data"):
        validate_payload(SnapshotKey(2024, "ppr", 10), _payload(teams=12))


def test_payload_rejects_wrong_season_period():
    with pytest.raises(ValueError, match="does not match season"):
        validate_payload(SnapshotKey(2023, "ppr", 12), _payload(season=2024))


def test_standard_accepts_provider_non_ppr_label():
    validate_payload(
        SnapshotKey(2024, "standard", 12),
        _payload(scoring="Non-PPR"),
    )


def test_quality_profile_rejects_duplicate_and_impossible_distribution():
    frame = normalize_snapshot(SnapshotKey(2024, "ppr", 12), _payload())
    broken = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    broken.loc[0, "earliest_pick"] = 10

    profile = profile_snapshots(broken).iloc[0]

    assert profile["duplicate_player_ids"] == 2
    assert profile["invalid_bounds_rows"] == 1
    assert profile["quality_status"] == "reject"


def test_quality_profile_warns_on_inconsistent_provider_draft_count():
    frame = normalize_snapshot(SnapshotKey(2024, "ppr", 12), _payload())
    frame.loc[0, "times_drafted"] = frame.loc[0, "total_drafts"] + 1

    profile = profile_snapshots(frame).iloc[0]

    assert profile["invalid_draft_count_rows"] == 1
    assert profile["quality_status"] == "warn"


def test_replace_snapshots_removes_stale_rows_from_whole_partition():
    old = normalize_snapshot(SnapshotKey(2024, "ppr", 12), _payload(players=50))
    new = normalize_snapshot(SnapshotKey(2024, "ppr", 12), _payload(players=49))
    other = normalize_snapshot(
        SnapshotKey(2023, "ppr", 12), _payload(season=2023, players=50)
    )

    combined = replace_snapshots(pd.concat([old, other]), new)

    assert len(combined[combined["season"].eq(2024)]) == 49
    assert len(combined[combined["season"].eq(2023)]) == 50


def test_board_enrichment_uses_current_snapshot_then_prior_only_imputation():
    current = normalize_snapshot(
        SnapshotKey(2024, "ppr", 12), _payload(season=2024)
    )
    history = normalize_snapshot(
        SnapshotKey(2023, "ppr", 12), _payload(season=2023)
    )
    future = normalize_snapshot(
        SnapshotKey(2025, "ppr", 12), _payload(season=2025)
    )
    future["adp_sd"] = 39.0
    board = pd.DataFrame(
        [
            {"season": 2024, "player_name": "Player AA", "position": "WR", "adp": 10.0},
            {"season": 2024, "player_name": "New Player", "position": "WR", "adp": 20.0},
        ]
    )

    enriched, coverage = enrich_board_with_adp_distribution(
        board,
        pd.concat([history, current, future], ignore_index=True),
        scoring="ppr",
        suffix="1qb",
    )

    assert enriched.loc[0, "market_distribution_source_1qb"] == "observed"
    assert enriched.loc[0, "market_adp_sd_1qb"] == 1.5
    assert enriched.loc[1, "market_distribution_source_1qb"] == "imputed_prior"
    assert enriched.loc[1, "market_adp_sd_1qb"] == 1.5
    assert enriched.loc[1, "market_adp_sd_1qb"] != 39.0
    assert coverage["observed_rows"] == 1
    assert coverage["imputed_rows"] == 1
    assert coverage["missing_rows"] == 0
