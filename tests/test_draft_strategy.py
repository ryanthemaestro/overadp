"""Tests for league-aware replacement value and next-turn scarcity."""
import numpy as np
import pandas as pd

from src.optimizer.draft_strategy import (
    compute_league_slot_allocation,
    compute_next_pick_values,
    compute_vbd,
    conditional_probability_gone,
)


def _standard_two_team_config():
    return {
        "roster_slots": {"rb": 1, "wr": 1, "te": 1, "flex": 1, "bench": 2},
        "flex_eligible": ["rb", "wr", "te"],
    }


def _players():
    rows = []
    for pos, points in {
        "RB": [100, 90, 80, 70],
        "WR": [110, 95, 85, 75],
        "TE": [105, 60, 50, 40],
    }.items():
        rows.extend(
            {
                "player_id": f"{pos}_{i}",
                "player_name": f"{pos} {i}",
                "position": pos,
                "projected_points": points_value,
                "adp": 1 + i * 12,
            }
            for i, points_value in enumerate(points)
        )
    return pd.DataFrame(rows)


def test_flex_is_allocated_from_best_remaining_players():
    allocation = compute_league_slot_allocation(
        _players(), num_teams=2, roster_config=_standard_two_team_config()
    )

    assert allocation["flex_replacement"]["FLEX"] == 80
    assert allocation["flex_allocations"]["FLEX"] == {"RB": 1, "WR": 1, "TE": 0}
    assert allocation["selected_counts"] == {"RB": 3, "TE": 2, "WR": 3}
    assert allocation["effective_replacement"] == {"RB": 80, "TE": 60, "WR": 85}


def test_vbd_uses_final_position_cutoff_and_keeps_negative_values():
    valued = compute_vbd(_players(), 2, _standard_two_team_config()).set_index("player_id")

    assert valued.loc["RB_0", "vbd"] == 20
    assert valued.loc["WR_0", "vbd"] == 25
    assert valued.loc["TE_0", "vbd"] == 45
    assert valued.loc["RB_3", "vbd"] == -10
    assert valued.loc["RB_3", "vbd_positive"] == 0


def test_superflex_can_allocate_additional_quarterbacks():
    players = pd.DataFrame(
        [
            *(
                {"player_id": f"QB_{i}", "position": "QB", "projected_points": p}
                for i, p in enumerate([300, 290, 280, 270])
            ),
            *(
                {"player_id": f"RB_{i}", "position": "RB", "projected_points": p}
                for i, p in enumerate([200, 190, 180, 170])
            ),
        ]
    )
    config = {
        "roster_slots": {"qb": 1, "rb": 1, "superflex": 1},
        "superflex_eligible": ["qb", "rb", "wr", "te"],
    }

    allocation = compute_league_slot_allocation(players, 2, config)

    assert allocation["flex_replacement"]["SUPERFLEX"] == 270
    assert allocation["flex_allocations"]["SUPERFLEX"]["QB"] == 2
    assert allocation["selected_counts"]["QB"] == 4
    assert allocation["effective_replacement"]["QB"] == 270


def test_next_turn_risk_is_conditional_on_player_being_available_now():
    risk = conditional_probability_gone(
        np.asarray([18.0, 30.0, 60.0]), current_pick=20, next_pick=35, scale=6
    )

    assert 0 <= risk.min() <= risk.max() <= 1
    assert risk[0] > risk[1] > risk[2]
    # An ADP 18 player who has already fallen to pick 20 is not treated as if
    # the earlier draft outcomes can still happen.
    assert risk[0] < 1


def test_observed_adp_dispersion_changes_next_turn_risk_by_player():
    narrow = conditional_probability_gone(
        np.asarray([30.0]),
        current_pick=20,
        next_pick=35,
        adp_sd=np.asarray([2.0]),
        earliest_pick=np.asarray([25.0]),
        latest_pick=np.asarray([35.0]),
    )
    wide = conditional_probability_gone(
        np.asarray([30.0]),
        current_pick=20,
        next_pick=35,
        adp_sd=np.asarray([10.0]),
        earliest_pick=np.asarray([1.0]),
        latest_pick=np.asarray([80.0]),
    )

    assert narrow[0] > wide[0]
    assert 0 <= wide[0] <= narrow[0] <= 1


def test_observed_pick_range_softens_an_unusually_long_tail():
    short_tail = conditional_probability_gone(
        np.asarray([30.0]),
        current_pick=20,
        next_pick=40,
        adp_sd=np.asarray([2.0]),
        latest_pick=np.asarray([32.0]),
    )
    long_tail = conditional_probability_gone(
        np.asarray([30.0]),
        current_pick=20,
        next_pick=40,
        adp_sd=np.asarray([2.0]),
        latest_pick=np.asarray([60.0]),
    )

    assert long_tail[0] < short_tail[0]


def test_missing_dispersion_uses_the_generic_fallback():
    fallback = conditional_probability_gone(
        np.asarray([30.0]), current_pick=20, next_pick=35
    )
    missing = conditional_probability_gone(
        np.asarray([30.0]),
        current_pick=20,
        next_pick=35,
        adp_sd=np.asarray([np.nan]),
    )

    np.testing.assert_allclose(missing, fallback)


def test_vona_compares_player_to_expected_same_position_option_next_turn():
    valued = compute_next_pick_values(
        _players(),
        current_pick=1,
        next_pick=15,
        num_teams=2,
        roster_config=_standard_two_team_config(),
    )
    rb = valued[valued["position"] == "RB"].sort_values("projected_points", ascending=False)

    assert (valued["p_gone_next"].between(0, 1)).all()
    assert rb.iloc[0]["expected_next_vbd"] > 0
    assert rb.iloc[0]["vona"] < rb.iloc[0]["vbd"]


def test_next_pick_values_handle_players_without_adp():
    valued = compute_next_pick_values(
        _players().drop(columns="adp"),
        current_pick=1,
        next_pick=15,
        num_teams=2,
        roster_config=_standard_two_team_config(),
    )

    assert valued["p_gone_next"].isna().sum() == 0
    assert valued["vona"].isna().sum() == 0
