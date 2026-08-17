#!/usr/bin/env python3
"""Build the canonical analytics report artifact from simulation outputs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def rate(frame: pd.DataFrame, strategy: str, column: str) -> float:
    return float(frame.loc[frame["strategy"] == strategy, column].iloc[0])


def main() -> None:
    raw = pd.read_csv(RESULTS / "simulation_raw.csv")
    summary = pd.read_csv(RESULTS / "simulation_summary.csv")
    primary_raw = raw[raw["true_adp"]].copy()
    primary = (
        primary_raw.groupby("strategy")
        .agg(
            simulations=("episode", "size"),
            avg_rank=("regular_rank", "mean"),
            first_place_rate=("regular_rank", lambda s: float((s == 1).mean())),
            top3_rate=("regular_rank", lambda s: float((s <= 3).mean())),
            playoff_rate=("made_playoffs", "mean"),
            championship_rate=("champion", "mean"),
            managed_points=("managed_points", "mean"),
        )
        .reset_index()
    )

    avg_rank_lift = rate(primary, "adp", "avg_rank") - rate(primary, "target_intel", "avg_rank")
    top3_lift = rate(primary, "target_intel", "top3_rate") - rate(primary, "adp", "top3_rate")
    playoff_lift = rate(primary, "target_intel", "playoff_rate") - rate(primary, "adp", "playoff_rate")
    title_lift = rate(primary, "target_intel", "championship_rate") - rate(primary, "adp", "championship_rate")
    points_lift = rate(primary, "target_intel", "managed_points") - rate(primary, "adp", "managed_points")

    wide = primary_raw.pivot(index=["season", "episode"], columns="strategy", values="managed_points")
    deltas = (wide["target_intel"] - wide["adp"]).to_numpy()
    rng = np.random.default_rng(20260816)
    samples = deltas[rng.integers(0, len(deltas), size=(5000, len(deltas)))].mean(axis=1)
    points_ci = np.quantile(samples, [0.025, 0.975])

    chart_rows = []
    for row in summary.itertuples(index=False):
        chart_rows.append(
            {
                "season": f"{row.season}{'' if row.true_adp else ' proxy'}",
                "strategy": str(row.strategy).replace("_", " ").title(),
                "top3_rate": float(row.top3_rate),
                "first_place_rate": float(row.first_place_rate),
                "playoff_rate": float(row.playoff_rate),
                "simulations": int(row.simulations),
                "adp_source": str(row.adp_source),
            }
        )

    table_rows = []
    for row in summary.itertuples(index=False):
        table_rows.append(
            {
                "season": int(row.season),
                "evidence": "Primary" if row.true_adp else "Proxy sensitivity",
                "strategy": str(row.strategy).replace("_", " ").title(),
                "average_rank": round(float(row.avg_regular_rank), 2),
                "top3_rate": float(row.top3_rate),
                "playoff_rate": float(row.playoff_rate),
                "championship_rate": float(row.championship_rate),
                "managed_points": round(float(row.managed_points), 1),
                "simulations": int(row.simulations),
            }
        )

    source = {
        "id": "historical-simulation",
        "label": "OverADP historical managed-league simulation",
        "path": "analysis/draft-simulation/results/simulation_raw.csv",
        "query": {
            "description": "Paired historical 12-team snake-draft simulations scored with real weekly half-PPR outcomes.",
            "engine": "DuckDB",
            "language": "sql",
            "sql": (
                "WITH raw AS (SELECT * FROM read_csv_auto('analysis/draft-simulation/results/simulation_raw.csv')), "
                "by_strategy AS (SELECT season, adp_source, true_adp, strategy, COUNT(*) AS simulations, "
                "AVG(regular_rank) AS avg_regular_rank, AVG(CASE WHEN regular_rank = 1 THEN 1 ELSE 0 END) AS first_place_rate, "
                "AVG(CASE WHEN regular_rank <= 3 THEN 1 ELSE 0 END) AS top3_rate, AVG(CAST(made_playoffs AS INTEGER)) AS playoff_rate, "
                "AVG(CAST(champion AS INTEGER)) AS championship_rate, AVG(managed_points) AS managed_points "
                "FROM raw GROUP BY ALL) SELECT * FROM by_strategy ORDER BY season, strategy"
            ),
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "tables_used": [
                "snake_draft_boards.parquet",
                "weekly_stats.parquet",
                "simulation_raw.csv",
            ],
            "filters": [
                "Primary claim set: 2023 and 2024 true-ADP seasons",
                "Sensitivity only: 2025 ESPN preseason-rank proxy",
                "12 teams, 15 rounds, half-PPR, weeks 1-17",
                "500 paired leagues per strategy-season",
            ],
            "metric_definitions": [
                "Top-three rate: share of simulated teams ranked 1-3 after weeks 1-14 by head-to-head wins, with points as tiebreaker.",
                "Championship rate: share winning a six-team playoff in weeks 15-17.",
                "Managed points: half-PPR points from lineups selected using preseason projection and only prior weekly results.",
            ],
        },
    }
    generated = datetime.now(timezone.utc).isoformat()
    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Can OverADP Draft a Top-Finishing Team?",
            "description": "A retrospective managed-league simulation against an ADP-first control.",
            "generatedAt": generated,
            "sources": [source],
            "cards": [
                {
                    "id": "rank-lift",
                    "description": "Lower average regular-season rank is better; positive lift favors Target Intel.",
                    "dataset": "headline",
                    "sourceId": "historical-simulation",
                    "metrics": [{"label": "Average rank improvement", "field": "avg_rank_lift", "format": "number"}],
                },
                {
                    "id": "top3-lift",
                    "description": "Percentage-point difference from ADP across the true-ADP seasons.",
                    "dataset": "headline",
                    "sourceId": "historical-simulation",
                    "metrics": [{"label": "Top-three lift (pp)", "field": "top3_lift_pp", "format": "number", "signed": True}],
                },
                {
                    "id": "playoff-lift",
                    "description": "Percentage-point difference in making the six-team playoff.",
                    "dataset": "headline",
                    "sourceId": "historical-simulation",
                    "metrics": [{"label": "Playoff lift (pp)", "field": "playoff_lift_pp", "format": "number", "signed": True}],
                },
                {
                    "id": "points-lift",
                    "description": "Average managed half-PPR point difference; bootstrap interval is in the findings.",
                    "dataset": "headline",
                    "sourceId": "historical-simulation",
                    "metrics": [{"label": "Managed points vs ADP", "field": "points_lift", "format": "number", "signed": True}],
                },
            ],
            "charts": [
                {
                    "id": "top3-by-season",
                    "title": "Top-three finish rate by season and strategy",
                    "subtitle": "2025 is separated and labeled because its market ordering is a proxy.",
                    "type": "bar",
                    "intent": "comparison",
                    "question": "How often did each strategy finish in the top three in each historical season?",
                    "rationale": "Grouped bars compare strategies within seasons while keeping the proxy season visible.",
                    "combinationRationale": "Color groups the three drafting strategies within each season.",
                    "dataset": "by-season",
                    "sourceId": "historical-simulation",
                    "encodings": {
                        "x": {"field": "season", "type": "ordinal", "label": "Season"},
                        "y": {"field": "top3_rate", "type": "quantitative", "format": "percent", "label": "Top-three rate"},
                        "color": {"field": "strategy", "type": "nominal", "label": "Strategy"},
                        "tooltip": [
                            {"field": "top3_rate", "format": "percent", "label": "Top-three rate"},
                            {"field": "simulations", "format": "number", "label": "Simulations"},
                            {"field": "adp_source", "type": "text", "label": "Market source"},
                        ],
                    },
                    "valueFormat": "percent",
                    "layout": "full",
                    "legend": {"position": "bottom", "title": "Strategy"},
                }
            ],
            "tables": [
                {
                    "id": "season-results",
                    "title": "Simulation results by season and strategy",
                    "subtitle": "Primary and proxy evidence are intentionally labeled separately.",
                    "dataset": "table-results",
                    "sourceId": "historical-simulation",
                    "defaultSort": {"field": "season", "direction": "asc"},
                    "density": "dense",
                    "layout": "full",
                    "columns": [
                        {"field": "season", "label": "Season", "format": "number"},
                        {"field": "evidence", "label": "Evidence", "type": "text"},
                        {"field": "strategy", "label": "Strategy", "type": "text"},
                        {"field": "average_rank", "label": "Avg rank", "format": "number"},
                        {"field": "top3_rate", "label": "Top 3", "format": "percent"},
                        {"field": "playoff_rate", "label": "Playoffs", "format": "percent"},
                        {"field": "championship_rate", "label": "Champion", "format": "percent"},
                        {"field": "managed_points", "label": "Managed pts", "format": "number"},
                        {"field": "simulations", "label": "N", "format": "number"},
                    ],
                }
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "body": "# Can OverADP Draft a Top-Finishing Team?\n\nA retrospective managed-league simulation against an ADP-first control."},
                {
                    "id": "answer",
                    "type": "markdown",
                    "sourceId": "historical-simulation",
                    "body": (
                        "## Answer\n\n"
                        f"Across the 2023–2024 true-ADP simulations, Target Intel improved average regular-season rank by **{avg_rank_lift:.2f} places** and added **{top3_lift * 100:.1f} percentage points** to the top-three rate versus ADP-first drafting. "
                        "That is encouraging evidence for the combined decision system—not for model rankings in isolation—and it is not a guarantee of a top finish."
                    ),
                },
                {"id": "headline-metrics", "type": "metric-strip", "cardIds": ["rank-lift", "top3-lift", "playoff-lift", "points-lift"]},
                {
                    "id": "what-won",
                    "type": "markdown",
                    "sourceId": "historical-simulation",
                    "body": (
                        "## What actually won\n\n"
                        "The strongest policy did not blindly draft the model's highest projection. It anchored to market ADP, then overrode the market when projected value, roster need, positional scarcity, and the chance a player would disappear before the next pick aligned. "
                        f"It averaged **{points_lift:.1f} more managed half-PPR points** than ADP (paired bootstrap 95% interval **{points_ci[0]:.1f} to {points_ci[1]:.1f}**)."
                    ),
                },
                {"id": "chart-block", "type": "chart", "chartId": "top3-by-season", "layout": "full"},
                {
                    "id": "why-it-matters",
                    "type": "markdown",
                    "sourceId": "historical-simulation",
                    "body": (
                        "## Product implication\n\n"
                        "The simple benefit is: **ADP tells you who the room is drafting; OverADP helps decide who your roster should draft now and who can wait.** "
                        "The simulation supports explaining OverADP as a decision layer on top of ADP. It does not support saying the raw model alone beats ADP or guarantees championships."
                    ),
                },
                {"id": "table-block", "type": "table", "tableId": "season-results", "layout": "full"},
                {
                    "id": "method",
                    "type": "markdown",
                    "sourceId": "historical-simulation",
                    "body": (
                        "## Method\n\n"
                        "Each strategy entered 500 paired 12-team, 15-round snake drafts per season. Opponents used noisy ADP plus roster need, never OverADP projections. All teams then used the same trailing-information lineup logic and one conservative same-position waiver move per week. Weeks 1–14 determined standings; a six-team playoff ran in Weeks 15–17. Real weekly half-PPR results carried injuries, missed games, and breakouts into scoring."
                    ),
                },
                {
                    "id": "caveats",
                    "type": "markdown",
                    "body": (
                        "## Caveats\n\n"
                        "This is a retrospective exploratory backtest, so the strategy was not frozen before the evaluated seasons. The opponent field approximates home leagues rather than replaying observed drafts. The simulation omits trades, kickers, defenses, FAAB bidding, and explicit injury designations. The 2025 result is sensitivity evidence only because it uses an ESPN preseason-rank proxy instead of true ADP. These limits make the work useful for product direction and copy discipline, but not sufficient for a causal or guaranteed-performance advertising claim."
                    ),
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated,
            "status": "ready",
            "datasets": {
                "headline": [
                    {
                        "avg_rank_lift": round(avg_rank_lift, 2),
                        "top3_lift_pp": round(top3_lift * 100, 1),
                        "playoff_lift_pp": round(playoff_lift * 100, 1),
                        "title_lift_pp": round(title_lift * 100, 1),
                        "points_lift": round(points_lift, 1),
                    }
                ],
                "by-season": chart_rows,
                "table-results": table_rows,
            },
        },
        "sources": [source],
    }
    (ROOT / "artifact.json").write_text(json.dumps(artifact, indent=2) + "\n")
    print(ROOT / "artifact.json")


if __name__ == "__main__":
    main()
