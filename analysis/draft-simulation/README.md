# Historical managed-league simulation

This experiment compares three draft policies in paired 12-team half-PPR leagues:

- `adp`: market ADP plus roster-need guardrails
- `target_intel`: ADP anchored, with selective overrides for model projection, VBD, roster need, and probability a player survives to the next pick
- `model_only`: projection-first diagnostic; not the recommended product strategy

Real weekly fantasy results drive Weeks 1–17. All teams use the same point-in-time lineup logic and conservative waiver automation. Injuries and absences appear through actual weekly points; the simulation does not use explicit injury designations, trades, FAAB, kickers, or defenses.

## Run

```bash
python3 run_historical_league_sim.py \
  --board /home/nar/Documents/nflmodel-experiments/snake_draft_boards.parquet \
  --weekly /home/nar/Documents/nflmodel/data/weekly_stats.parquet \
  --output-dir results \
  --seasons 2023 2024 2025 \
  --episodes 500 \
  --seed 73

python3 validate_results.py
python3 build_report_artifact.py

python3 run_management_decomposition.py \
  --board /home/nar/Documents/nflmodel-experiments/snake_draft_boards.parquet \
  --weekly /home/nar/Documents/nflmodel/data/weekly_stats.parquet \
  --output-dir results \
  --seasons 2023 2024 2025 \
  --episodes 500 \
  --seed 73

python3 validate_management_decomposition.py
python3 build_management_report_artifact.py
```

The management decomposition scores every paired draft three ways: a frozen Week-1 lineup, weekly start/sit decisions without transactions, and weekly lineups plus one conservative waiver move per team/week.

The primary comparison is limited to 2023–2024, which have true Fantasy Football Calculator ADP. The 2025 market ordering is an ESPN preseason-rank proxy and must remain labeled as sensitivity evidence.

This is a retrospective exploratory backtest. It is useful for product and messaging decisions, but it is not an untouched holdout or a guarantee of fantasy-league results.
