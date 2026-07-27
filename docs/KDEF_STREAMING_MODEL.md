# Kicker and Defense Streaming Model

## Product policy

Kickers and defenses are low-scarcity positions. OverADP therefore keeps them
out of early Target Intel recommendations, recommends a top defense only in the
final two rounds, and waits until the final round for a kicker. It never assigns
VBD to either position.

The K and DEF position filters rank current options for the opening three
weeks:

- Week 1: 55%
- Week 2: 30%
- Week 3: 15%

This favors immediate usefulness while retaining some value for avoiding an
instant waiver move.

## Inputs and formulas

The daily refresh gets active kicker starters and depth-chart order from
Sleeper, current K/DEF ADP from Fantasy Football Calculator, and the opening
schedule, market spread, market total, and venue from nflverse.

The formulas were fit on 2021-2024 regular-season games:

```text
K expected points =
  4.7215
  + 0.1446 × team implied points
  + 0.6755 × expected indoor share
  + 0.1218 × home indicator

DEF expected points =
  15.2133
  - 0.4041 × opponent implied points
```

Known fixed-roof venues receive full indoor credit. Retractable-roof venues
receive partial credit before game-week roof status is known. Kicker fantasy
scoring is 3/4/5/6 points by field-goal distance plus one point per PAT.
Defense scoring is one point per sack, two per turnover or safety, six per
touchdown, plus standard points-allowed tiers.

The board displays a separate rank for K and DEF, expected opening points per
game, matchup grades for Weeks 1-3, and the recommended draft window. ADP is
shown as market context but does not override the late-round policy.

## Holdout result

On the untouched 2025 opening three weeks, selecting the top eight options each
week produced:

| Position | Top eight | Other options | Lift |
|---|---:|---:|---:|
| K | 9.96 points/game | 8.75 | +1.21 |
| DEF | 7.92 points/game | 5.11 | +2.81 |

This is a ranking model, not a guarantee of exact weekly points. Kicker and
defensive touchdowns remain volatile, which is why the product still recommends
streaming instead of spending meaningful draft capital.

Reproduce the holdout check from a full nflmodel checkout:

```bash
python scripts/backtest_kdef_streaming.py \
  --weekly-stats ../nflmodel/data/weekly_stats.parquet \
  --schedules ../nflmodel/data/schedules.parquet
```

## Release gates

The daily refresh fails instead of publishing when:

- nflverse lacks all 48 games across Weeks 1-3 or a spread/total;
- the schedule does not cover all 32 teams exactly once each week;
- Sleeper does not identify one current starting kicker for every team;
- either K or DEF does not produce a complete, unique 1-32 streaming rank.
