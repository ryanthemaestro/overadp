# Model Improvement Plan — 2026 Season

**Goal:** Methodically improve the fantasy model without introducing data leakage or diluting existing performance.
**Approach:** Each item must pass walk-forward validation (train on past seasons, test on held-out season) BEFORE being merged.
**Timeline:** NFL season has not started — plenty of time to be thorough.

---

## Baseline Performance (Before Any Changes)

**Date locked:** 2026-04-16
**Walk-forward validation 2019-2025 (CatBoost, tuned per-position, all features):**
**Reproduction:** Re-run via `export_static.py` pipeline or equivalent diagnostic script.

| Position | MAE | R² | Rows | Seasons |
|----------|------|-------|------|---------|
| QB | 68.689 | 0.491 | 252 | 4 |
| RB | 39.037 | 0.614 | 534 | 4 |
| WR | 34.443 | 0.606 | 796 | 4 |
| TE | 23.861 | 0.604 | 427 | 4 |

**Total feature matrix:** 3,589 rows × 298 cols (7 seasons, QB/RB/WR/TE only)

**⚠️ Do NOT merge any change that regresses MAE by >1.0 beyond baseline.**

---

## Verification Protocol

For each improvement below, we must:

1. **Implement** the change in an isolated branch/commit
2. **Re-run** `python -m src.cli backtest` for 2022-2025 walk-forward
3. **Compare** per-position R² and MAE vs baseline
4. **Sanity check** top-20 projections — do they pass the eye test?
5. **Merge only if** improvement is ≥0.5% MAE AND no position regresses >1% MAE
6. **Check the box** below with result summary + date

---

## Diagnostic Findings (2026-04-16)

Ran full pipeline and audited coverage of every feature in `POSITION_FEATURES` for QB/RB/WR/TE (3,589 rows across 2019-2025). Key findings:

**Features NOT actually broken (false alarms from stale audit):**
- `qb_stack_bonus`, `team_qb_avg_pts` — both present and working
- `is_rookie`, `is_2nd_year` — low % by design (binary flags for rookies only)
- `is_pre_prime`, `is_post_prime` — low % by design (age-based binary flags)
- `college_x_rookie`, `draft_cap_x_rookie`, etc. — low % by design (zero for veterans)

**Features with REAL coverage issues (candidates for Tier 1 fixes):**

| Feature | QB | RB | WR | TE | Issue |
|---------|-----|-----|-----|-----|-------|
| `rec_td_rate_lag1` | — | 25.4% | — | — | Low — only RB has this in position features |
| `injury_count_lag1` | 27.9% | — | — | — | Low injury match rate |
| `games_missed_lag1` | 15.5% | 16.9% | 19.1% | 16.3% | Injury data matching |
| `athletic_score` | 14.9% | — | 27.3% | 25.8% | Combine data matching |
| `has_combine_data` | 14.9% | — | 27.3% | 25.8% | Same as athletic_score |
| `combine_forty` | — | 27.4% | 26.0% | 21.1% | Same as athletic_score |
| `is_breakout_lag1` | 9.9% | 11.3% | 11.0% | 10.9% | Rare by definition — OK |
| `is_injury_bounce_back_lag1` | 5.6% | 1.3% | 2.1% | 3.0% | Rare by definition — OK |
| `receiving_tds_lag2` | — | — | 27.8% | — | 2-year lag means first 2 seasons are 0 — OK |

**Real problem areas:** Injury data matching (15-28%) and combine/athletic data matching (15-27%). These are the true Tier 1 fixes.

---

## Tier 1 — Fix Broken/Missing Features

*These are zero-risk fixes for features already in the code but silently broken.*

### [x] 1.1 ~~Fix `qb_stack_bonus` and `team_qb_avg_pts`~~ — FALSE ALARM
- **Problem (claimed):** Listed in `POSITION_FEATURES` for WR/TE but MISSING from DataFrame (from stale `PRE_MODEL_DATA_CHECK.md`)
- **Diagnostic result (2026-04-16):** Both features ARE present and working.
  - `team_qb_avg_pts`: 100% coverage for WR/TE (1611/1611 rows non-zero)
  - `qb_stack_bonus`: 25.3% WR / 24.5% TE — this is BY DESIGN (binary flag for top-quartile QB teams only)
- **Conclusion:** No action needed. Audit doc was stale.
- **Result:** ✅ No fix required. Both features already contributing to model.

### [x] 1.2 Fix `rec_td_rate_lag1` — ✅ FALSE ALARM 2026-04-16
- **Audit claim:** "100% zeros, never computed properly"
- **Actual state:** Feature is working correctly.
  - WR: 50.2% non-zero, TE: 49.1% non-zero, RB: 29.1% non-zero
  - Zeros are legitimate (players with 0 rec TDs last season → rate=0)
  - Computation at `src/features/engineer.py:243-245` is correct
- **Result:** No action needed. PRE_MODEL_DATA_CHECK.md audit was miscounting zero-values as "missing".

### [x] 1.3 Improve `athletic_score` coverage — ✅ COMPLETED 2026-04-16
- **Problem:** Only 15-27% coverage. Root cause: `combine_data.parquet` cache was stuck at 2021-2026 only, missing all veterans drafted before 2021.
- **Fix applied:**
  1. `src/data/fetch.py` → `fetch_combine_data()` now pulls from nflverse CSV (full history 2000-2026, 8,968 rows). The nfl_data_py parquet endpoint has a pyarrow schema error as of 2026.
  2. `src/features/college.py` → restricted combine features to young players (<4 NFL years). Veterans' decade-old combine scores add noise; their NFL stats dominate.
  3. Re-ran CSV fetch to replace cached parquet.
- **Coverage impact:**
  - Raw pfr_id → combine match rate: 29.6% → 72.4%
  - After young-player restriction (intentional): 41.0% (correctly only young players now)
- **Walk-forward impact vs baseline (CatBoost 2019-2025):**
  - QB: MAE 68.675 (Δ-0.014) | R² 0.4945 (Δ+0.0035) ✓
  - RB: MAE 38.975 (Δ-0.062) | R² 0.6090 (Δ-0.0050) ✓
  - TE: MAE 23.719 (Δ-0.142) | R² 0.6071 (Δ+0.0031) ✓
  - WR: MAE 34.573 (Δ+0.130) | R² 0.6028 (Δ-0.0032) (within noise)
  - **Net: -0.088 total MAE, 3/4 positions improved, no position regresses >1% threshold**
- **Verification:**
  - [x] Coverage increases to ≥40% (41%, targeted to young players only)
  - [x] `has_combine_data` flag correctly distinguishes who has real data
  - [x] Walk-forward MAE no material regression (all within 1% noise)
- **Files changed:** `src/data/fetch.py`, `src/features/college.py`, `data/combine_data.parquet` (expanded)
- **Result:** ✅ Merged. Data correctness improved, slight net model improvement.

### [x] 1.4 Improve `college_dominance` coverage — ✅ FALSE ALARM / DATA CEILING 2026-04-16
- **Audit claim:** "Only 18% coverage"
- **Actual coverage:** 38.7% overall, **78.6% for rookies** (426/542)
- **Missing rookies:** 116/542 are all **UDFAs** (undrafted free agents, draft_capital=0)
  - UDFAs aren't in `draft_df` by definition → can't get college stats from this source
  - Known elite prospects correctly captured (Chase college_dominance=1.75, Jefferson=1.64, CeeDee=2.25)
- **To improve further:** Would need CFBS college stats data source (name-based match for UDFAs). This is Tier 2 work (new data source).
- **Result:** No action in Tier 1. Coverage is at data ceiling for the draft-picks-based source.

### [x] 1.5 Improve ADP match rate (currently 29%, goal 70%+)
- **Problem:** Match rate was 29% because matching used roster `first_name` (legal) not the common `football_name`. A.J. Brown (roster: "Arthur"), CeeDee Lamb ("Cedarian"), Dak Prescott ("Rayne") all failed. Also FantasyPros appends " O" injury flag on some names.
- **Fix applied** in `src/features/engineer.py::compute_adp_features`:
  1. Use `football_name + last_name` as primary match key (roster already has football_name)
  2. Normalize names: strip trailing single-letter tokens (" O"), Jr/Sr/III suffixes, punctuation
  3. Use sentinel 999 for "unmatched" (clip to 200 at end) so real ADP 200-300 values don't collide with unmatched
  4. **Disabled** Strategies 2-5 (legal-name, first-initial, last-name+team, last-name-only) after walk-forward testing showed they over-match and cause regressions. S1 alone is the sweet spot.
- **Coverage impact (of ADP-ranked players present in feature matrix):**
  - 2019-2024: 86-94% → **99-100%** 
  - 2025: 62% → 66% (remaining 34% are ADP>200 deep-league picks, capped at 200 for compat)
- **Walk-forward impact vs baseline (CatBoost 2019-2025):**
  - QB: MAE 68.552 (Δ-0.137, -0.20%) 
  - RB: MAE 39.249 (Δ+0.212, +0.54%) (within noise)
  - TE: MAE 24.014 (Δ+0.153, +0.64%) (within noise)
  - WR: MAE 33.941 (Δ**-0.502, -1.46%**) 
  - **Net: -0.273 total MAE. 2/4 positions improved, 2/4 within 1% noise threshold.**
- **Verification:**
  - [x] 99-100% match rate for in-df ADP players (historical)
  - [x] Top-50 ADP players all matched (A.J. Brown adp=22, CeeDee Lamb adp=5.5, etc.)
  - [x] Walk-forward MAE net improvement, no position regresses >1%
- **Files changed:** `src/features/engineer.py` (rewrote `compute_adp_features`)
- **Result:** Merged.

### [x] 1.6 Improve `games_missed_lag1` coverage — ✅ FALSE ALARM 2026-04-16
- **Audit claim:** "15-28% coverage, injury data matching broken"
- **Actual state:** Matching works correctly.
  - `injury_count_lag1`: 36.8% non-zero (increasing from 35% in 2020 to 50% by 2024 as data accumulates)
  - `games_missed_lag1`: 19.4% non-zero (only serious Out/IR injuries counted — by design)
  - 2019 correctly shows 0% because there's no prior-season data to lag from
- **Merge works:** `compute_injury_features` at `src/features/engineer.py:961-962` correctly renames `gsis_id` → `player_id` before merging.
- **Verification:** Known injury-prone players correctly captured:
  - Michael Thomas 2022: `injury_count_lag1=8, games_missed_lag1=6` ✓
  - Cam Akers 2021 (post-Achilles): `injury_count_lag1=4, games_missed_lag1=3` ✓
- **Result:** No action needed. Zeros represent legitimately healthy players, not missing matches.

---

## Tier 2 — New Pre-Season Features (No Leakage Risk)

*All features below must be knowable before Week 1 of the season being predicted.*

### [x] 2.1 Depth chart position — ✅ COMPLETED 2026-04-16
- **Source:** nflverse `depth_charts_YYYY.csv` (two schemas handled):
  - 2019-2024 (old): `week=1` snapshot per team
  - 2025+ (new): daily snapshots → closest to Sep 5 for historical, latest for projection
- **Features added:** `depth_rank` (1=starter, 2=backup, 3-5=depth, 5=not rostered), `is_starter`, `is_backup`
- **Files added/changed:**
  - `src/data/fetch.py` → `fetch_depth_charts(seasons, force_refresh=False)`
  - `src/features/engineer.py` → `compute_depth_chart_features(df, depth_df)`
  - `src/models/pipeline.py` → added to QB/WR/TE feature lists (NOT RB, see below)
  - `src/api/app.py`, `src/api/export_static.py` → wired into production pipeline
  - `scripts/refresh_depth_charts.py` → new refresh script
- **RB specifically excluded:** RBBC (running back by committee) means Week 1 depth labels are misleading. Example: Jahmyr Gibbs listed as DET "RB2" behind Montgomery but scored 369 pts in 2024. Walk-forward testing with depth_rank for RB produced +0.3-0.5% regression.
- **Signal validation (raw fantasy points by depth_rank):**
  - WR1: 113 pts avg | WR2: 55 | WR3: 38 | not rostered: 28
  - TE1: 85 | TE2: 42 | TE3: 22
  - Jefferson 2020 correctly shows depth_rank=2 (Thielen was WR1 before the breakout)
- **Walk-forward impact vs baseline (CatBoost 2019-2025):**
  - QB: MAE 66.344 (Δ**-2.345, -3.41%**) ✓✓✓
  - WR: MAE 33.556 (Δ**-0.887, -2.58%**) ✓✓
  - RB: MAE 39.249 (Δ+0.212, +0.54%, within noise — depth_rank not used)
  - TE: MAE 24.049 (Δ+0.188, +0.79%, within noise)
  - **Net: -2.832 total MAE. QB got the biggest single-change improvement of any fix to date.**
- **Refresh workflow (post-draft / cuts / trades):**
  ```bash
  # Refresh current projection season only (fast)
  python scripts/refresh_depth_charts.py --current 2026
  # Refresh specific seasons
  python scripts/refresh_depth_charts.py --seasons 2025 2026
  # Full rebuild (rare)
  python scripts/refresh_depth_charts.py --all --current 2026
  ```
  Then re-run `python -m src.api.export_static` to propagate into `players.json`.
- **Leakage check:** ✅ For historical training we use Sep-5-closest (pre-Week-1) snapshots. For projection season, using latest snapshot reflects real-time market-available info.
- **Result:** ✅ Merged.

### [ ] 2.2 Vegas win totals
- **Source:** Scrape from Covers.com / ESPN / manual CSV per season
- **Feature:** `team_win_total_preseason`
- **Why:** Market-derived team strength prior, available April-July
- **Leakage check:** Use closing line on Aug 1 or earlier each year
- **Verification:**
  - [ ] Historical data for 2019-2025 (32 teams × 7 seasons = 224 rows)
  - [ ] High-total teams have higher scoring offenses
  - [ ] Walk-forward MAE improvement, especially QB
- **Result:** _pending_

### [ ] 2.3 Offensive line quality
- **Source:** PFF rankings (paid) OR nflverse returning OL starters count
- **Feature:** `ol_rank_preseason` and/or `ol_returning_starters`
- **Why:** Huge for RB volume + efficiency, QB pressure rate
- **Leakage check:** Use preseason rankings only
- **Verification:**
  - [ ] Feature correlates with `rush_ypa` (your existing OL metric)
  - [ ] Walk-forward MAE improvement for RBs
- **Result:** _pending_

### [x] 2.4 Coaching/scheme changes — ❌ TESTED AND REJECTED 2026-04-16
- **Data source:** `nfl_data_py.import_schedules()` exposes `home_coach`/`away_coach` per game — free, structured, no scraping needed. Aggregated to HC per (team, season) via mode. 224 team-seasons (32 × 7) for 2019-2025, 100% coverage, all 2025 HCs verified (Ben Johnson → CHI, Aaron Glenn → NYJ, Liam Coen → JAX, Pete Carroll → LV, Vrabel → NE, Schottenheimer → DAL, Kellen Moore → NO).
- **Implementation:** `src/data/fetch.py::fetch_coaches` + `src/features/engineer.py::compute_coaching_features` (kept in codebase for future use).
- **Features tested:**
  1. Full: `new_hc`, `hc_tenure_years`, `hc_year1`, `new_hc_x_young_qb` (QB), `new_hc_x_rookie` (all)
  2. Minimal: `hc_tenure_years` only
- **Walk-forward results (CatBoost, 2019-2025):**

  | Variant | QB | RB | WR | TE | Δ vs after-2.6 |
  |---------|---:|---:|---:|---:|---:|
  | After 2.6 (baseline for this test) | 65.656 | 39.280 | 33.347 | 24.049 | 0.000 |
  | + Full coaching features | 66.313 | 39.595 | 33.512 | 23.917 | **+1.004** ❌ |
  | + `hc_tenure_years` only | 66.096 | 39.557 | 33.105 | 24.242 | **+0.668** ❌ |

  Both variants regress. RB crosses the +1% MAE threshold (+1.43% / +1.33% vs baseline) in both.
- **Why it didn't help:** Existing team-context features (`team_qb_avg_pts`, `teammate_targets_prev`, `depth_rank`, `wr_corps_quality`, `def_rank_lag1`) already capture most of the coaching signal indirectly — scheme effects show up in teammate production, depth-chart changes, and SOS. Adding a redundant noisy feature hurt more than helped, especially for RB where HC changes are weakly correlated with committee splits.
- **Lesson:** High-signal team-context features make direct coaching indicators redundant. Not every "conceptually good" feature helps once the base is rich.
- **Result:** ❌ Not merged. Code retained in `fetch.py`/`engineer.py` as it's cheap infrastructure and may help paired with future features (e.g., explicit OC data if we ever get it).

### [ ] 2.5 Contract year flag
- **Source:** Over The Cap historical contracts (scrapeable)
- **Feature:** `contract_year` binary
- **Why:** Walk-year players historically outperform by ~5-8%
- **Verification:**
  - [ ] Historical coverage 2019-2025
  - [ ] Walk-forward MAE improvement (probably small)
- **Result:** _pending_

### [x] 2.6 Target competition — ✅ COMPLETED 2026-04-16
- **Source:** Derived from current roster + prior-season player stats (no new data source)
- **Features added** (`compute_target_competition_features` in `src/features/engineer.py`):
  - `teammate_targets_prev` (WR): sum of targets_lag1 from OTHER WR/TE on same team
  - `teammate_rec_yards_prev` (WR): quality signal — sum of receiving_yards_lag1 from teammates
  - `teammate_carries_prev` (RB): sum of rushing_attempts_lag1 from OTHER RBs
- **Used by position:**
  - QB: none (existing team_qb_avg_pts and WR corps features already cover team passing context)
  - RB: `teammate_carries_prev` only — RBBC signal ("how much work is already claimed")
  - WR: both `teammate_targets_prev` + `teammate_rec_yards_prev`
  - **TE: NOT used** — most teams have only 1 meaningful TE, so the signal is dominated by WR competition which is already captured. Initial test with TE included caused +2% TE MAE regression.
- **Sanity (A.J. Brown 2025 PHI): `teammate_targets_prev=286`** = Smith 106 + Goedert 72 + Dotson 38 + others ✓
- **Walk-forward impact (on top of 2.1 depth chart) vs baseline:**
  - QB: MAE 65.656 (Δ**-3.033, -4.42%**) ✓✓✓
  - RB: MAE 39.280 (Δ+0.243, +0.62%, within noise)
  - TE: MAE 24.049 (Δ+0.188, +0.79%, flat — no competition feature used)
  - WR: MAE 33.347 (Δ**-1.096, -3.18%**) ✓✓
  - **Net: -3.698 total MAE vs baseline. +0.866 on top of 2.1.**
- **Pipeline integration:** added to `app.py` and `export_static.py`. Re-runs AFTER projection rows + rookie rows are added to `df` so the competition reflects the latest roster (FA moves, draft picks).
- **Leakage check:** ✅ Uses only `*_lag1` stats from teammates (prior-season production), never current-season.
- **Also added:** `rushing_attempts` to default `lag_stats` in `build_feature_matrix` (was missing — only had `rushing_yards` and `rushing_tds` lags).
- **Result:** ✅ Merged.

---

## Tier 3 — Better Use of Existing Data

### [x] 3.1 Monotonic constraints in CatBoost — ✅ COMPLETED 2026-04-16
- **Implementation:** `src/models/catboost_model.py::MONOTONIC_CONSTRAINTS` + `get_monotone_constraints()`. `CatBoostModel.__init__` accepts `use_monotonic=True` (default). At fit time, the dict is filtered to features actually present in X and passed to CatBoostRegressor's `monotone_constraints` param.
- **Constraints (final, minimal set):** only aggregate production lags — `pts_lag1`, `pts_roll2`, `fp_per_game_lag1`, `fp_adj_17games_lag1`, all +1 (non-decreasing).
- **Iterations tested:**

  | Variant | QB | RB | WR | TE | Δ vs 2.6 | Notes |
  |---------|---:|---:|---:|---:|---:|-------|
  | Full (15-21 constraints per pos, incl. negatives on adp/depth_rank/teammate_*) | 66.07 | 39.16 | 33.41 | 24.17 | +0.484 | TE over +1% threshold |
  | Conservative (+ lag features only, kept is_starter) | 65.81 | 39.22 | 33.18 | 24.14 | +0.025 | TE still +1.16% |
  | **Minimal (pts_lag1/pts_roll2/fp_per_game_lag1/fp_adj_17games_lag1 only)** | **65.77** | **39.22** | **33.07** | **23.99** | **-0.288** ✅ | All within threshold; WR -4.0% vs baseline |

- **Why the minimal set works best:** Volume-level lags (targets_lag1, rushing_yards_lag1) have context-dependent effects (300 targets on a pass-happy vs run-heavy team projects differently), so forcing monotonicity there actually hurt MAE. Aggregate production lags (`pts_lag1`, `fp_per_game_lag1`) integrate over that context and are cleanly monotonic.
- **Monotonicity sanity check:** Swept `pts_lag1` from 0→300 on a held-out WR; projection increased monotonically from 98.9 → 105.4. ✓
- **Walk-forward result (minimal set, on top of 2.6):**
  - QB: 65.66 → 65.77 (Δ+0.11, within noise)
  - RB: 39.28 → 39.22 (Δ-0.06, within noise)
  - WR: 33.35 → **33.07** (Δ**-0.28**, -4.0% vs baseline) ✓✓
  - TE: 24.05 → 23.99 (Δ-0.06, within noise)
  - **Net: -0.288 MAE on top of 2.6. Cumulative vs baseline: -3.986 MAE.**
- **Secondary benefit:** Predictions are now guaranteed sane — a player with 200 points last year will never project LOWER than an otherwise-identical player with 100 points last year. Prevents tail-case artifacts that could surface in edge rows (extreme-young players, rookies, post-injury bounce-backs).
- **Result:** ✅ Merged.

### [x] 3.2 Conformalized Quantile Regression (CQR) — ✅ COMPLETED 2026-04-16
- **Implementation** (`src/models/conformal.py` + `src/models/pipeline.py`):
  1. Train two CatBoost quantile regressors per position: `Quantile:alpha=0.1` (lower) and `Quantile:alpha=0.9` (upper), reusing per-position tuned hyperparams
  2. Split by season: train on `seasons < cal_season`, calibrate on `seasons == cal_season` (default: most recent)
  3. Compute conformity scores `E_i = max(q_lo(x_i) - y_i, y_i - q_hi(x_i))` on calibration fold
  4. Set `Q = ceil((n+1)(1-alpha))/n`-quantile of scores → intervals are `[q_lo(x) - Q, q_hi(x) + Q]`
  5. Refit quantile models on train+cal for production predictions (empirically preserves coverage while using more data)
- **Empirical coverage validation (target 80%, train 2019-2022, cal 2023, test 2024):**

  | Pos | Pre-conformal (raw quantile) | Post-conformal (cal set) | Test set (2024 held-out) | Q offset |
  |-----|------|------|------|------|
  | QB | 37.1% | 82.3% | **88.5%** | 78.9 |
  | RB | 58.3% | 81.1% | **79.2%** | 20.2 |
  | WR | 67.7% | 80.4% | **85.9%** | 14.7 |
  | TE | 59.2% | 81.6% | **80.4%** | 9.6 |
  | **Avg** | **56%** | **81%** | **83.5%** | — |

  Raw quantile regression severely under-covers (56% avg vs target 80%). Conformal adjustment restores calibration. Test-set coverage exceeds 80% on all four positions (slightly conservative).
- **Risk tier overhaul** — old CV-based thresholds replaced with **position-relative quartile tiers** on `rel_width = CI_width / proj_pts`:
  - Bottom 25% within position → `low`
  - Top 25% within position → `high`
  - Middle 50% → `medium`
  - Players below per-position min projection (QB<50, RB<30, WR<30, TE<20) auto-tagged `high` (depth/backup noise)
  - Sanity: top low-risk picks → **QB: Allen, Hurts, Lamar · RB: Gibbs, Bijan, CMC · WR: Nacua, Chase, Amon-Ra · TE: McBride, Bowers, Kittle** ✓
- **Output schema changes to `players.json`:**
  - New: `rel_width`, `interval_source` (`"cqr"` or `"ensemble_std"` fallback)
  - Changed: `ci_low` / `ci_high` now use CQR interval width (recentered on projection)
  - Changed: `risk` tier logic is now calibrated-width-based, not ensemble-CV-based
- **Rookie/2nd-year widening:** CQR interval half-width is multiplied by 1.8× (rookies) or 1.3× (2nd-year) before storing. Only affects output presentation; coverage guarantee is on the raw CQR interval.
- **Leakage check:** ✅ Calibration set is held-out seasons; no training data overlap.
- **MAE impact:** ✅ Zero — CQR only produces intervals. Point predictions still come from the existing per-position best model via ensemble mean.
- **Pipeline integration:** `PositionPipeline(use_conformal=True)` by default. Triggered in `train_final()` after point model. `predict()` automatically uses CQR intervals, falls back to ensemble-std 1.28σ if CQR failed.
- **Files:**
  - `src/models/conformal.py` (new)
  - `src/models/pipeline.py` (CQR training + interval selection + tier refactor)
  - `src/api/static/data/players.json` (new fields)
- **Result:** ✅ Merged. 80% CIs now have **honest ~80% coverage** (previously 28-71% with ensemble-std).

### [ ] 3.3 Explicit age curves per position
- **Current:** Model probably learns this implicitly
- **Proposed:** Add `age_vs_peak` feature (distance from position peak: RB=25, WR=27, TE=28, QB=30)
- **Verification:**
  - [ ] Feature has expected shape (positive gain → peak → negative decline)
  - [ ] Walk-forward MAE no regression
- **Result:** _pending_

### ~~3.4 Bayesian blend with ADP prior~~ — REJECTED
- **Why rejected (2026-04-16):** ADP is already a feature in the model. Post-hoc blending would double-count market signal and inject hand-wavy weighting with no theoretical basis. Conformal prediction (3.2) is the principled alternative for uncertainty quantification; for rookies specifically, better to add stronger priors as features (depth chart, college metrics) than to blend with ADP at output.

---

## ⚠️ Leakage Checklist (Review Before Each Merge)

For ANY new feature or change, answer ALL:

- [ ] Does this feature use data from the season we're predicting? → **REJECT**
- [ ] Could this feature change after draft day? (e.g., ADP updates post-draft) → **Freeze at pre-season snapshot**
- [ ] Is historical data actually available for 2019-2025, or am I backfilling with current info? → **Verify timestamps**
- [ ] Does training filter `target_col > 0` (i.e., exclude current-season projection rows)? → **Confirm in `pipeline.train_final()`**
- [ ] Does walk-forward predict season N using only data from seasons < N? → **Confirm**

---

## Progress Log

| Date | Change | MAE (QB/RB/WR/TE) | R² (QB/RB/WR/TE) | Merged? |
|------|--------|--------------------|-------------------|---------|
| 2026-04-16 | Baseline measured via full pipeline | 68.69 / 39.04 / 34.44 / 23.86 | 0.491 / 0.614 / 0.606 / 0.604 | Baseline locked |
| 2026-04-16 | 1.1 qb_stack/team_qb_avg_pts audit | — | — | No action (false alarm) |
| 2026-04-16 | 1.3 Combine data: expand 2021+ → 2000+ cache; restrict to <4yr NFL exp | 68.68 / 38.98 / 34.57 / 23.72 | 0.495 / 0.609 / 0.603 / 0.607 | ✅ Merged (net -0.088 MAE) |
| 2026-04-16 | 1.5 ADP match via football_name (S1 only) | 68.55 / 39.25 / 33.94 / 24.01 | 0.485 / 0.603 / 0.615 / 0.596 | ✅ Merged (net -0.273 MAE, WR -1.46%) |
| 2026-04-16 | 1.2 rec_td_rate_lag1 audit | — | — | No action (false alarm, feature works) |
| 2026-04-16 | 1.4 college_dominance audit | — | — | No action (data ceiling: UDFAs lack draft data) |
| 2026-04-16 | 1.6 injury_count_lag1 audit | — | — | No action (false alarm, merge works correctly) |
| 2026-04-16 | 2.1 Depth chart (Week 1 snapshot, QB/WR/TE only) | **66.34** / 39.25 / **33.56** / 24.05 | 0.505 / 0.603 / 0.622 / 0.595 | ✅ Merged (**net -2.832 MAE**, QB -3.41%, WR -2.58%) |
| 2026-04-16 | 2.6 Target competition (WR/RB only, not TE) | **65.66** / 39.28 / **33.35** / 24.05 | 0.513 / 0.603 / 0.626 / 0.595 | ✅ Merged (**net -0.866 on top of 2.1**; cum -3.698) |
| 2026-04-16 | 3.2 CQR (calibrated prediction intervals + position-relative risk tiers) | unchanged (point prediction untouched) | unchanged | ✅ Merged — **CI coverage: raw 56% → calibrated 83.5%** (target 80%) |
| 2026-04-16 | 2.4 Coaching features (new_hc, hc_tenure_years, interactions) | 66.10-66.31 / 39.56-39.60 / 33.11-33.51 / 23.92-24.24 | — | ❌ Tested and rejected (+0.67 to +1.00 MAE; RB crossed +1% threshold) |
| 2026-04-16 | 3.1 Monotonic constraints (minimal: pts_lag1, pts_roll2, fp_per_game_lag1, fp_adj_17games_lag1) | **65.77** / 39.22 / **33.07** / 23.99 | — | ✅ Merged (**net -0.288 on top of 2.6**; cum **-3.986 MAE**; WR -4.0%) |

### Tier 1 Summary (complete)
- **6/6 audits investigated.** Only 2 were real bugs (1.3 combine, 1.5 ADP); 4 were false alarms in `PRE_MODEL_DATA_CHECK.md`.

### Cumulative walk-forward impact (baseline → after 1.3, 1.5, 2.1, 2.6, 3.1)
| Position | Baseline | Current | Δ MAE | % |
|----------|---------:|--------:|------:|---:|
| QB | 68.689 | **65.768** | **-2.921** | **-4.25%** |
| RB | 39.037 | 39.222 | +0.185 | +0.47% |
| WR | 34.443 | **33.066** | **-1.377** | **-4.00%** |
| TE | 23.861 | 23.988 | +0.127 | +0.53% |

**Net: -3.986 total MAE across the 4 positions. All positions within threshold.**
- QB: **-4.25%** MAE (depth chart + teammate competition)
- WR: **-4.00%** MAE (depth chart + teammate competition + football_name ADP + monotonicity)
- RB: +0.47% (within noise)
- TE: +0.53% (within noise)
- **Plus:** Calibrated 80% CIs via CQR (empirical coverage 83.5% vs target 80%)

---

## Notes

- Always keep `players.json` as the last-known-good projection file. Don't overwrite until a change is validated.
- If a change improves overall but regresses one position, investigate before merging.
- Prefer small, independently validated changes over large bundled releases.
