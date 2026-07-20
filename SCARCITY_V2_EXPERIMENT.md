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
8. In the follow-up experiment, replace the shared availability spread with
   format-specific FFC standard deviation and soft earliest/latest-pick tails.

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

## Historical ADP distribution follow-up

The FFC distributions now join to the historical boards by normalized player
name and position. Same-season preseason values are used when available;
otherwise the fallback is the median of the 25 closest prior-season players at
the same position and ADP. Future seasons are explicitly excluded.

- 2023/2024 one-QB exact coverage is 100% of priced players.
- 2023/2024 two-QB exact coverage is 89.2% and 98.1% of priced players.
- The 2025 archive is unavailable, so all 2025 dispersion values are prior-only
  imputations. No board rows are left without a fallback.

Paired starter-point results below use 240 drafts per case and 20,000 bootstrap
resamples. Positive values favor the distribution-based policy.

| Evaluation | Versus guarded ADP | 95% CI | Versus generic Scarcity | 95% CI |
|---|---:|---:|---:|---:|
| 2024 fixed one-QB | +0.1 | [-23.1, +22.9] | -11.6 | [-21.4, -2.5] |
| 2024 fixed two-QB | +108.1 | [+76.8, +138.9] | -30.1 | [-47.8, -12.6] |
| 2025 seed 73 fixed one-QB | +14.3 | [-0.4, +29.0] | -1.1 | [-10.9, +8.5] |
| 2025 seed 141 fixed one-QB | +8.3 | [-5.8, +22.9] | -1.1 | [-9.4, +7.4] |
| 2025 seed 73 fixed two-QB | +68.3 | [+47.3, +89.2] | +27.1 | [+11.4, +43.3] |
| 2025 seed 141 fixed two-QB | +66.2 | [+46.4, +86.1] | +7.7 | [-6.6, +21.6] |
| 2025 seed 73 mixed | +29.3 | [+13.6, +44.9] | +15.9 | [+5.7, +26.4] |
| 2025 seed 141 mixed | +12.9 | [-1.7, +27.3] | +2.7 | [-6.6, +12.2] |

The two-QB advantage over guarded ADP is stable and large, but the historical
distribution does not consistently improve the already experimental generic
Scarcity policy. One-QB confidence intervals still cross zero, and the 2024
observed-distribution test significantly regresses versus generic Scarcity.
This follow-up therefore remains a **no-go for production**. It is kept behind
the experiment script while the live board continues using the guarded policy.

## Checks completed

- Exact synthetic FLEX allocation and per-position cutoffs.
- Superflex allocation with additional quarterbacks.
- Signed VBD below replacement.
- Conditional next-turn probability bounds and ordering.
- Player-specific ADP standard deviation and asymmetric soft-tail behavior.
- Exact same-season joins and prior-only imputation with a future-leakage test.
- VONA comparison against expected same-position next-turn value.
- Fixed and randomized roster simulations.
- Paired bootstrap confidence intervals with 20,000 resamples.
- Two simulator seeds plus a 2024 observed-distribution walk-forward check.

## Remaining analytical risks

- Only three historical draft boards are available, with one final holdout
  season.
- FFC supplies aggregate ADP standard deviation and extrema, not complete pick
  sequences. That cannot identify correlated position runs or roster context.
- Scripted opponent behavior may not reproduce real position runs or home-
  league tendencies. The opponents also do not draw directly from the imported
  human distributions, so this simulator is not a pure disappearance-label
  validation.
- Season-total starter points do not model weekly injuries, byes, waiver
  replacement, or head-to-head playoff probability.
- Coefficient searches were unstable across simulator seeds, so further tuning
  on the same seasons risks overfitting.

## Promotion gates

Before changing production rankings:

1. The FFC replacement is implemented and evaluated. Before promotion, add
   exact Sleeper draft sequences or another roster-context source and at least
   one more point-in-time outcome season.
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

Pass `--adp-distribution-cache data/ffc_adp_distributions.parquet` to enable the
historical distribution and `--fixed-qb-slots 2` for the fixed two-QB family.
Use `scripts/summarize_scarcity_distribution_validation.py` to verify exact
episode pairing and regenerate
`experiments/scarcity_distribution_holdout_summary.csv` and
`experiments/scarcity_distribution_paired_comparisons.csv`.
