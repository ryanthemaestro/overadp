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

## Start/sit accuracy (`start_sit.py`)

Pairs of same-position, fantasy-relevant players who both played the following week, 2019–2025, scored with a model fit without that season. The page shows the rate for the projected gap between the two players.

| Picked by | Right |
|---|---|
| **Calibrated model** | **63.6%** |
| v6 preseason projection | 61.0% |
| Season average so far | 61.4% |

| Projected gap | QB | RB | WR | TE |
|---|---|---|---|---|
| under 1 pt | 52% | 53% | 52% | 54% |
| 1–2 | 57% | 57% | 57% | 57% |
| 2–3 | 59% | 63% | 61% | 61% |
| 3–5 | 65% | 68% | 67% | 68% |
| 5+ | 69% | 79% | 75% | 74% |

Under one point the page calls it a toss-up. When the two players play different positions (a FLEX decision), it uses the lower of the two rates.

## Kickers (`kickers.py`)

Yahoo default kicker scoring, leave-one-season-out on 2019–2025.

| Kicker projection | Rest-of-season MAE (pts/game) | Next-week start/sit right |
|---|---|---|
| Page's previous method (last season blended with this season, this season up to 50%) | 1.75 | 52.8% |
| Last season only | 1.66 | 50.7% |
| This season only | 2.28 | 52.6% |
| Calibrated blend | 1.39 | 52.5% |
| **Blend + share of remaining games indoors (shipped, rest of season)** | **1.37** | 53.2% |
| Blend + team scoring + indoors | 1.37 | 53.2% |
| **Blend + team scoring + betting-line implied team total + roof (shipped, next week)** | — | **55.3%** |

Rest-of-season kicker scoring is close to a constant (~6.4 pts/game) plus an indoor-schedule bonus; a kicker's own history carries little forward, which is why trusting it (the previous method) did worst. Next-week pick accuracy by projected gap: 52% under 1 pt, 58% at 1–2, 63% at 2+. Team scoring alone added noise to the rest-of-season model and was dropped there.

## Team defenses (`defenses.py`)

Yahoo default DEF scoring rebuilt from nflverse team stats plus final scores (points allowed = the opponent's final score, which also counts points the defense's own offense gave up; the approximation public data allows). Leave-one-season-out on 2019–2025.

| Defense projection | Rest-of-season MAE (pts/game) | Next-week start/sit right |
|---|---|---|
| Last season only | 2.02 | 53.1% |
| This season only | 2.86 | 53.5% |
| Calibrated blend | 1.68 | 54.0% |
| **Blend + remaining opponents' scoring (shipped, rest of season)** | **1.67** | 54.0% |
| Blend + next opponent's scoring so far | — | 57.7% |
| **Blend + betting-line implied points for the opponent (shipped, next week)** | — | **60.8%** |

Defenses are the most matchup-driven position: next-week pick accuracy by projected gap is 53% under 1 pt, 60% at 1–2, 65% at 2–3, 70% at 3–5 and 77% at 5+. The next-week model is roughly 15.7 − 0.41 × the opponent's implied points.
