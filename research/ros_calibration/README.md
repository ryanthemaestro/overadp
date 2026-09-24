# Rest-of-season calibration for the Yahoo Team Hub

**Question.** At week *w*, what's the best estimate of a player's half-PPR points per game for weeks *w*–17 (through the usual fantasy playoffs)?

**Data.** Public only: nflverse weekly player stats and schedules for 2019–2025, and the v6 model's walk-forward preseason predictions (`research/public-model-v6` branch, `out/walkforward_predictions_2019_2025.csv`). 43,049 player/week decision points; target players had at least two games left.

**Method.** Every model is scored leave-one-season-out: fit on six seasons, score the seventh. Error is the average miss in points per game over the rest of the season, weighted by games remaining.

## Results (held-out MAE, pts/game)

| Position | Decision weeks | v6 preseason only | Results so far only | Shrinkage blend | **Blend + usage (shipped)** |
|---|---|---|---|---|---|
| QB | 2–5 | 4.96 | 5.26 | 4.31 | **3.74** |
| QB | 6–14 | 5.44 | 4.52 | 4.27 | **3.92** |
| RB | 2–5 | 3.04 | 3.55 | 2.78 | **2.61** |
| RB | 6–14 | 3.31 | 2.87 | 2.64 | **2.65** |
| WR | 2–5 | 2.45 | 3.12 | 2.22 | **2.13** |
| WR | 6–14 | 2.72 | 2.53 | 2.29 | **2.27** |
| TE | 2–5 | 1.90 | 2.44 | 1.77 | **1.58** |
| TE | 6–14 | 2.13 | 2.01 | 1.78 | **1.73** |

"Blend + usage" is a ridge regression per position and games-played bucket (1, 2, 3, 4–5, 6–8, 9+) on the preseason projection, points per game so far, and targets, carries and pass attempts per game. With no games played it falls back to the preseason projection. Coefficients: `site/yahoo/ros-model.json`.

## Team-context factors (tested, not used)

Each factor was applied to the shipped model's per-game estimates and scored on held-out seasons (baseline game-level MAE 4.402):

| Factor | Held-out MAE | Verdict |
|---|---|---|
| Opponent strength (points allowed to the position so far) | 4.399 | Effect real but tiny (a defense allowing 20% more ≈ +3%); not worth the noise |
| Home field | 4.402 | No improvement |
| Late season (weeks 15–17), team at or below .300 | 4.411 | Worse: those players scored *above* projection (1.10× vs 0.98× for mid teams) |

Resting starters shows up only in the season's final week (strong teams 0.98× vs mid teams 1.13×, n = 116, 2019–2020). Since 2021 that's Week 18, after typical fantasy playoffs. None of these factors are used.

## Caveats

- Calibrated on the pure v6 preseason model; production uses v6 blended 50/50 with ADP, which the historical file doesn't include.
- Half-PPR target. The page converts to a league's own scoring using each player's own scoring ratio.
- Points per game *when playing*. Availability (injury status, byes) is handled separately on the page.

Run: `python3 research/ros_calibration/calibrate.py DATA_DIR` (DATA_DIR holds `stats_YYYY.csv`, `games.csv`, `preseason.csv`).
