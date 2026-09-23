# Public-data projection model v6 (research)

This is a research candidate for OverADP's preseason point projections. **It is not wired into the live site.** Pushing this branch changes nothing on overadp.com, because Netlify deploys only from `main`.

**What it predicts:** each QB/RB/WR/TE's regular-season fantasy points (standard, half-PPR and PPR), using only information available before week 1. That covers every player on a week-1 roster, including rookies, plus last season's free agents.

**Model:** a 5-seed bag of gradient-boosted trees (scikit-learn), averaged with a two-stage model (expected games × points per game). There is one pooled model per scoring format. Each projection comes with an empirically calibrated 80% range.

## Headline results

### vs. production CatBoost, 2023–2025, half-PPR, real-ADP cohort
The production numbers come from `nflmodel-nextgen-lab/artifacts/runs/cached-production-backtest-20260902-v1`. That run is a reconstruction of the production code, not the exact model fitted on Aug 29. The cohorts match closely: nearly identical player counts, and nearly identical ADP baselines (0.403 vs. 0.403).

| Mean of 12 season × position cells | Rank corr. | MAE |
|---|---:|---:|
| Production CatBoost (reconstruction) | 0.293 | 63.8 |
| ADP (calibrated) | 0.403 | 56.0–56.8 |
| **v6 model** | **0.414** | **55.7** |
| **v6 + ADP 50/50 blend** | **0.426** | **54.3** |

v6 beats production on rank correlation in 9 of 12 cells. Per-cell detail is in `out/production_comparison_2023_2025.csv`.

### vs. ADP (Fantasy Football Calculator, 2019–2025, all three formats)
- **The model alone is roughly even with ADP.** For half-PPR, rank correlation is 0.43 vs. 0.45.
- **The 50/50 model + ADP blend** beats ADP on MAE in **19 of 21** format-seasons and on rank correlation in **14 of 21**, and ties on draft value.
- **Defensible claim: "complements ADP," not "beats ADP."**

### vs. the TabPFN 3.5 screen, 2025, standard scoring, same cohort
MAE is **23.4** vs. 28.7 for TabPFN and 29.0 for the screen's CatBoost.

### Draft simulation (`draft_sim.py`, 2019–2025, half-PPR)
- **Setup:** paired 12-team, 14-round snake drafts: 7 seasons × 20 seeds × 12 seats.
  - Opponents draft by FFC ADP with noise.
  - The test seat drafts by value over replacement from each projection source.
  - Season score is the best-ball optimal weekly lineup, using actual weekly points.

| Test seat drafts by | Avg points | Avg finish (of 12) | Top-3 rate | Win rate |
|---|---:|---:|---:|---:|
| ADP order | 1,762 | 5.73 | 33.8% | 14.2% |
| ADP value (log-ADP points) | 1,734 | 6.12 | 29.0% | 9.0% |
| v6 model | 1,783 | 5.38 | 35.2% | 15.8% |
| **v6 + ADP 50/50 blend** | **1,840** | **4.15** | **51.7%** | **22.1%** |

- **Blend:** +77 points per team vs. ADP order (season-level SE 45), ahead in 5 of 7 seasons.
- **Model alone:** +21 points (SE 54), ahead in 3 of 7 seasons.
- Results swing a lot by season. With only 7 independent seasons, the blend is **promising, not proven** (about 1.7 SE).
- This is a simple best-ball simulator, not the lab's fair draft simulator. The lab version (`nflmodel-nextgen-lab`, `audit_cached_production_backtest.py`) should be rerun with a `public_v6_blend` board before promotion.

## Data and attribution

| Source | Use | License / terms |
|---|---|---|
| nflverse: stats, pbp, rosters, depth charts, snaps, draft, combine, players | core features | CC BY 4.0. *Data from nflverse-data; modified by OverADP* |
| nflverse participation | route-participation features | CC BY-SA 4.0. *NFL NextGenStats via nflverse* (≤2022); *FTN Data via nflverse* (2023+). Don't redistribute derived route tables except under CC BY-SA |
| CollegeFootballData | college-production features | Free API key. Commercial derived predictions are allowed; raw data may not be redistributed. *Data provided by CollegeFootballData.com* |
| Fantasy Football Calculator ADP | evaluation baseline and blend | Free for personal and commercial use; attribution requested. *ADP data courtesy of FantasyFootballCalculator.com* |

Keys and raw third-party data are never committed; `.gitignore` covers `data/`, `work/`, `adp/`, `cfbd_raw/`, `cfbd_derived/` and `.secrets/`.

## Rebuild

This takes about 10 minutes on 2 CPUs. It needs Python 3.11+ and `requirements.txt`.

```
./cfbd_login.sh              # once: store your CFBD API key privately (no-echo)
python3 cfbd_fetch.py        # ~105 calls, free tier
python3 cfbd_derive.py       # compact derived college tables
python3 fetch_adp.py         # optional: FFC ADP for the comparison (21 calls)
./run_all.sh                 # nflverse fetch -> features -> v6 -> walk-forward -> 2026 projections -> metrics
```

A clean rebuild reproduces `out/projections_2026.csv` exactly.

## Files
- **Pipeline:** `draft_sim.py` (simulation), `adp_curve.json` (ADP→points), `pbp_extract.py`, `build_features.py`, `college.py`, `routes.py`, `add_routes.py`, `final.py`, `intervals.py`, `evaluate.py`, `adp_eval.py`, `backtest.py`
- **`experiments/`:** tried and not adopted — injury/availability, QB, coaching, Vegas, NGS, component model, stacked ADP combination. See the results below.
- **`out/`:** metrics, comparisons, walk-forward predictions for 2019–2025, and 2026 projections.

## Tried, not adopted

These are all measured with the same walk-forward setup.

| Idea | Result |
|---|---|
| Injury/availability features, 32 of them | No gain. Stars returning from injury remain under-projected by about 19 points on average. ADP handles them better. |
| QB rushing style, starter security, supporting cast | No gain. ADP ranks drafted QBs better (0.43 vs. 0.26–0.30). |
| Coaching changes; week-1 Vegas totals | Within noise. |
| NGS separation, RYOE, CPOE | Small gain, but rights review is required. |
| Stat-component model, then score | Worse. |
| Learned model + ADP combination | Not better than the simple 50/50 blend; only 2–6 ADP seasons to learn from. |

## Using it in the site export (off by default)
`src/api/export_static.py --projection-source {catboost|public_v6|public_v6_blend}`
- `catboost` is the default and changes nothing.
- `public_v6` replaces projections and 80% ranges for matched players (by gsis id).
- `public_v6_blend` averages v6 with ADP-implied points (`adp_curve.json`) for players with real ADP (< 200).
- Unmatched players keep CatBoost. Unmatched means Sleeper-stub rookies or players not on a week-1 roster. The `projection_source` field records which applied.
- Tests are in `tests/test_public_v6.py`.
- Before using it, regenerate `out/projections_<season>.csv` with `run_all.sh` once week-1 rosters and depth charts exist. For a true preseason board, use the latest depth-chart snapshot at draft time.

## Before production
1. Rerun the lab's fair draft simulator with the `public_v6_blend` board.
2. **Add a preseason mode.** `build_features.py` currently takes the cohort, team and depth chart from the *week-1* roster and depth chart. At draft time in late August those don't exist yet. Use the nflverse season roster and the latest daily depth-chart snapshot as of the draft date instead.
3. The data-source registry was updated in `nflmodel-nextgen-lab/config/data_sources.yaml`. Participation is now commercial with attribution under CC BY-SA, FFC's API terms are recorded, and CFBD is noted as used.
4. Keep site copy to "complements ADP" unless a future prospective test shows more.
