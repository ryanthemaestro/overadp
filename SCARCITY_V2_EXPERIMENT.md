# Scarcity 2.0 validation

## Decision

**Needs revision — do not publish to the production board yet.**

The allocation method fixes real correctness problems and the 2025 point
estimates are directionally better than the current guarded policy, but the
paired confidence intervals include meaningful losses. The live site should
remain unchanged until the gain is stable across seeds and league formats.

## Question

Can league-aware replacement values plus conditional value-over-next-available
(VONA) build better fantasy starting lineups than ADP, static VBD, and the
current ADP-guarded policy?

## Data and grain

- Historical draft boards: 2023, 2024, and 2025 player-seasons.
- Draft-day inputs: point-in-time CatBoost projections, ADP, positions, and
  roster settings.
- Outcome: realized season fantasy points in the best legal QB/RB/WR/TE/FLEX
  starting lineup.
- Training/tuning seasons: 2023-2024 only.
- Final holdout: 2025.
- Opponents: noisy ADP/model/VBD scripted drafters with roster-need constraints.
- Holdout sample: 240 fixed-format drafts and 240 randomized-format drafts per
  strategy. Randomized formats cover 10/12/14 teams, 1/2 QB, 1-3 RB, 2-3 WR,
  0-3 FLEX, and 5-10 bench slots.

## Method changes

1. Fill exclusive league-wide starter slots first.
2. Fill FLEX and Superflex with the highest projected remaining eligible
   players.
3. Set each position's replacement baseline to its final allocated starter.
4. Keep signed VBD instead of collapsing every below-replacement player to 0.
5. Estimate next-turn availability conditional on the player still being
   available at the current pick.
6. Use expected best next-turn VBD to calculate VONA.
7. Remove the automatic RB bonus from Scarcity 2.0.

## 2025 holdout results

| Format | Policy | Starter points | Average rank | Win rate | Top-3 rate |
|---|---:|---:|---:|---:|---:|
| Fixed 12-team | Scarcity 2.0 | 1,613.3 | 4.43 | 18.8% | 47.5% |
| Fixed 12-team | Current guarded | 1,608.5 | 4.58 | 17.1% | 46.7% |
| Fixed 12-team | ADP | 1,593.9 | 5.00 | 11.3% | 40.0% |
| Mixed formats | Scarcity 2.0 | 1,710.0 | 4.57 | 17.1% | 43.3% |
| Mixed formats | Current guarded | 1,708.8 | 4.75 | 17.9% | 45.4% |
| Mixed formats | ADP | 1,680.1 | 5.40 | 12.1% | 33.3% |

Paired Scarcity 2.0 minus guarded starter-point estimates:

- Fixed: **+4.9 points**, bootstrap 95% CI **[-7.3, +17.1]**.
- Mixed: **+1.1 points**, bootstrap 95% CI **[-15.8, +18.1]**.

The point estimates improve, but neither interval excludes zero. Mixed-format
win and top-three rates also trail the current guarded policy despite a better
average rank. That is not a production-quality win.

## Checks completed

- Exact synthetic FLEX allocation and per-position cutoffs.
- Superflex allocation with additional quarterbacks.
- Signed VBD below replacement.
- Conditional next-turn probability bounds and ordering.
- VONA comparison against expected same-position next-turn value.
- Fixed and randomized roster simulations.
- Paired bootstrap confidence intervals with 20,000 resamples.

## Remaining analytical risks

- Only three historical draft boards are available, with one final holdout
  season.
- ADP uncertainty is approximated because the board stores a mean ADP rather
  than the full draft-position distribution.
- Scripted opponent behavior may not reproduce real position runs or home-
  league tendencies.
- Season-total starter points do not model weekly injuries, byes, waiver
  replacement, or head-to-head playoff probability.
- Coefficient searches were unstable across simulator seeds, so further tuning
  on the same seasons risks overfitting.

## Promotion gates

Before changing production rankings:

1. Replace the fixed ADP spread with the validated FFC historical distributions,
   then add exact Sleeper draft sequences or another roster-context source and
   at least one more point-in-time season.
2. Evaluate at least 200 drafts per important format family, not sparse random
   one-off formats.
3. Require the paired starter-point confidence interval versus guarded to have
   a non-negative lower bound.
4. Require no material regression in win rate, top-three rate, or the common
   10-team/12-team one-QB formats.
5. Validate the browser implementation against Python fixtures so replacement,
   VBD, availability, and VONA match exactly.

## Reproduction

Use `scripts/run_snake_draft_rl_experiment.py` with the cached historical frame
and boards. The `scarcity_v2` strategy is available in `--strategies`, and
`--scarcity-weights` accepts a JSON object for auditable experiments. Summary
results are saved in `experiments/scarcity_v2_holdout_summary.csv`.
