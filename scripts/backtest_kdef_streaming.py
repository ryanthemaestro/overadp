#!/usr/bin/env python3
"""Reproduce the K/DEF opening-matchup holdout check.

This optional research script uses the nflmodel parquet files and pandas. It is
kept separate from the dependency-free daily production refresh.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from refresh_market_data import (
    defense_expected_points,
    expected_indoor_share,
    kicker_expected_points,
    normalize_team,
)


def points_allowed_score(points: float) -> int:
    if points == 0:
        return 10
    if points <= 6:
        return 7
    if points <= 13:
        return 4
    if points <= 20:
        return 1
    if points <= 27:
        return 0
    if points <= 34:
        return -1
    return -4


def schedule_context(schedules: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for game in schedules.itertuples(index=False):
        home_team = normalize_team(game.home_team)
        away_team = normalize_team(game.away_team)
        indoor = expected_indoor_share(game.roof, home_team)
        home_implied = game.total_line / 2 + game.spread_line / 2
        away_implied = game.total_line / 2 - game.spread_line / 2
        rows.extend([
            {
                "season": game.season,
                "week": game.week,
                "team": home_team,
                "own_implied": home_implied,
                "opponent_implied": away_implied,
                "home": True,
                "indoor": indoor,
                "points_allowed": game.away_score,
            },
            {
                "season": game.season,
                "week": game.week,
                "team": away_team,
                "own_implied": away_implied,
                "opponent_implied": home_implied,
                "home": False,
                "indoor": indoor,
                "points_allowed": game.home_score,
            },
        ])
    return pd.DataFrame(rows)


def summarize(frame: pd.DataFrame) -> dict[str, float | int]:
    ranked = frame.copy()
    ranked["rank"] = ranked.groupby(["season", "week"])["predicted"].rank(
        method="first",
        ascending=False,
    )
    top = ranked[ranked["rank"] <= 8]["actual"].mean()
    rest = ranked[ranked["rank"] > 8]["actual"].mean()
    return {
        "observations": int(len(ranked)),
        "top_8_points_per_game": round(float(top), 2),
        "other_points_per_game": round(float(rest), 2),
        "top_8_lift_points_per_game": round(float(top - rest), 2),
        "prediction_correlation": round(
            float(ranked["predicted"].corr(ranked["actual"])),
            3,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weekly-stats", type=Path, required=True)
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--weeks", type=int, nargs="+", default=[1, 2, 3])
    args = parser.parse_args()

    weekly = pd.read_parquet(args.weekly_stats)
    weekly = weekly[
        (weekly["season_type"] == "REG")
        & (weekly["season"] == args.season)
        & (weekly["week"].isin(args.weeks))
    ].copy()
    schedules = pd.read_parquet(args.schedules)
    schedules = schedules[
        (schedules["game_type"] == "REG")
        & (schedules["season"] == args.season)
        & (schedules["week"].isin(args.weeks))
    ].dropna(subset=["spread_line", "total_line"]).copy()
    context = schedule_context(schedules)

    kickers = weekly[weekly["position"] == "K"].copy()
    kickers["actual"] = (
        3 * (
            kickers["fg_made_0_19"].fillna(0)
            + kickers["fg_made_20_29"].fillna(0)
            + kickers["fg_made_30_39"].fillna(0)
        )
        + 4 * kickers["fg_made_40_49"].fillna(0)
        + 5 * kickers["fg_made_50_59"].fillna(0)
        + 6 * kickers["fg_made_60_"].fillna(0)
        + kickers["pat_made"].fillna(0)
    )
    kickers["attempts"] = (
        kickers["fg_att"].fillna(0) + kickers["pat_att"].fillna(0)
    )
    kickers = (
        kickers.sort_values(
            ["season", "week", "team", "attempts", "actual"],
            ascending=[True, True, True, False, False],
        )
        .drop_duplicates(["season", "week", "team"])
        .merge(context, on=["season", "week", "team"], how="inner")
    )
    kickers["predicted"] = kickers.apply(
        lambda row: kicker_expected_points(
            row["own_implied"],
            row["indoor"],
            bool(row["home"]),
        ),
        axis=1,
    )

    defense_columns = [
        "def_sacks",
        "def_interceptions",
        "fumble_recovery_opp",
        "def_safeties",
        "def_tds",
        "special_teams_tds",
    ]
    weekly[defense_columns] = weekly[defense_columns].fillna(0)
    defenses = (
        weekly.groupby(["season", "week", "team"], as_index=False)[defense_columns]
        .sum()
        .merge(context, on=["season", "week", "team"], how="inner")
    )
    defenses["actual"] = (
        defenses["def_sacks"]
        + 2 * defenses["def_interceptions"]
        + 2 * defenses["fumble_recovery_opp"]
        + 2 * defenses["def_safeties"]
        + 6 * (defenses["def_tds"] + defenses["special_teams_tds"])
        + defenses["points_allowed"].map(points_allowed_score)
    )
    defenses["predicted"] = defenses["opponent_implied"].map(
        defense_expected_points
    )

    result = {
        "season": args.season,
        "weeks": args.weeks,
        "scoring": {
            "kicker": "3/4/5/6 by distance plus PAT",
            "defense": "1 sack, 2 turnover/safety, 6 TD, standard points allowed",
        },
        "kicker": summarize(kickers),
        "defense": summarize(defenses),
    }
    print(json.dumps(result, indent=2))
    if (
        result["kicker"]["top_8_lift_points_per_game"] < 0.5
        or result["defense"]["top_8_lift_points_per_game"] < 1.5
    ):
        raise SystemExit("K/DEF opening model failed the minimum holdout lift")


if __name__ == "__main__":
    main()
