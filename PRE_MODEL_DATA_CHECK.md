# Pre-Model Data Quality Report

Generated: 2026-04-14 | Pipeline: nflverse → clean → features → model

---

## 1. Raw Data Sources

| Source | File | Rows | Seasons | Key Cols |
|--------|------|------|---------|----------|
| Seasonal Stats | `seasonal_stats.parquet` | 13,860 | 2019-2025 | player_id, season, team, games, passing/rushing/receiving stats |
| Roster Info | `roster_info.parquet` | 21,711 | 2019-2025 | player_id, season, team, position, age, entry_year, rookie_year |
| Team Stats | `team_stats.parquet` | 224 | 2019-2025 | team, season, offensive/defensive metrics |
| OL Metrics | `ol_metrics.parquet` | 224 | 2019-2025 | team, season, rush_ypa, sack_rate, rush_td_rate |
| ADP Data | `adp_data.parquet` | 1,269 | 2020-2025 | player_name, position, team, adp, season |
| Injury Data | `injury_data.parquet` | 40,204 | 2019-2025 | gsis_id, season, team, injury, status |
| Draft Picks | `draft_picks.parquet` | 1,803 | 2019-2025 | pfr_player_id, round, pick, college stats |
| Combine Data | `combine_data.parquet` | 2,076 | 2000-2025 | pfr_id, forty, bench, vertical, broad, shuttle |
| Player Info | `player_info.parquet` | 24,376 | — | gsis_id, pfr_id, draft_year, college_conference |

---

## 2. Cleaning Pipeline

### `clean_seasonal_stats`
- Combines REG + POST into one row per player-season
- Renames columns to match nfl_data_py format (`recent_team` → `team`, etc.)
- Fills numeric NaN with 0
- **Team normalization**: `normalize_teams()` — maps LAR→LA, OAK→LV, JAC→JAX, WSH→WAS, GNB→GB, etc.
- Filters to `games >= 3`
- **Result**: 13,860 → 9,284 rows

### `clean_roster_info`
- Standardizes positions (FB→RB, HB→RB)
- Team normalization
- Deduplicates on player_id (keep last)
- **Result**: 21,711 → 7,124 rows

### `clean_team_stats`, `clean_ol_metrics`
- Team normalization applied
- 32 teams per season ✓

---

## 3. Feature Engineering Pipeline (Order Matters!)

```
1. build_feature_matrix()     — merge seasonal + roster + team + OL
2. add_fantasy_points_to_df() — compute half-PPR scoring
3. compute_regression_to_mean_features() — YoY change, breakout/bust, TD rate lags
4. compute_stacking_features() — team_qb_avg_pts, qb_stack_bonus (lagged)
5. compute_teammate_dependency_features() — qb_quality, wr_corps_quality, etc.
6. compute_adp_features() — 3-strategy name matching (full→last+team→last only)
7. compute_injury_features() — aggregated injury counts, games missed (lagged)
8. compute_rookie_features() — is_rookie, is_2nd_year (via entry_year > rookie_year > draft_year > age heuristic)
9. compute_sos_features() — defensive strength rankings (lagged)
10. compute_college_features() — draft capital, athletic_score, college_dominance, combine metrics, interactions
```

**Critical ordering**: Step 8 (rookie) runs BEFORE step 10 (college) so `is_rookie`/`is_2nd_year` flags exist when college interaction features are created.

---

## 4. Data Quality Checks

### 4a. Team Abbreviations

All sources normalized to 32 nflverse standard abbreviations via `TEAM_MAP`:

```
ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND
JAX KC LA LAC LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS
```

| Mapping | From | To |
|---------|------|----|
| Rams | LAR, STL | LA |
| Raiders | LVR, OAK | LV |
| Chargers | SD | LAC |
| Washington | WSH, WFT | WAS |
| Jaguars | JAC | JAX |
| PFR variants | GNB, KAN, NWE, NOR, SFO, TAM | GB, KC, NE, NO, SF, TB |

**Status**: ✅ All 32 teams consistent across all sources after normalization

### 4b. Player-Season Integrity

| Check | Value | Status |
|-------|-------|--------|
| Player-season duplicates (cleaned) | 0 | ✅ |
| Null player_id (cleaned) | 0 | ✅ |
| Null team in feature matrix | 0 | ✅ |
| Null position in feature matrix | 0 | ✅ |
| 951 raw rows with no team/name | Dropped by roster merge | ✅ |
| `NAN`/`NONE` as team strings | Converted to NaN, filtered | ✅ |

### 4c. Fantasy Points

| Check | Value | Status |
|-------|-------|--------|
| Negative FP | 25 rows (mostly backup QBs with fumbles) | ✅ Expected |
| Zero FP | 284 rows (199 K, 85 skill) | ✅ K filtered, skill trained on fp>0 |
| FP range | -3.2 to 479.5 | ✅ |
| Trainable rows (fp>0, skill positions) | 3,479 | ✅ |

### 4d. Games Played

| Check | Value | Status |
|-------|-------|--------|
| Min games (after clean) | 3 | ✅ |
| Max games | 21 (17 reg + 4 playoff) | ✅ Expected |
| Games > 17 | 742 rows (playoff contributors) | ✅ |

---

## 5. Feature Completeness

### Per-Position Feature Counts

| Position | Features Defined | Features Available | Missing |
|----------|-----------------|-------------------|---------|
| QB | 52 | 52 | 0 |
| RB | 56 | 56 | 0 |
| WR | 57 | 57 | 0 |
| TE | 55 | 55 | 0 |

### NaN Rates (Lag Features — Expected)

Lag features are naturally NaN for first-season players (no prior year data). Filled with 0 before training.

| Feature | QB NaN | RB NaN | WR NaN | TE NaN |
|---------|--------|--------|--------|--------|
| *_lag1 | 131 (31%) | 312 (33%) | 445 (32%) | 234 (32%) |
| *_lag2 | 223 (53%) | 539 (57%) | 765 (56%) | 410 (55%) |

**Status**: ✅ Expected — first/second-year players have no lag data

### High-Zero Features (>80% zeros)

These are sparse by design (binary flags, rare events, or limited-coverage data):

| Feature | Why >80% zeros | Impact |
|---------|---------------|--------|
| `is_rookie` | Only ~15% of players are rookies | ✅ Binary flag, tree models handle well |
| `is_2nd_year` | Only ~14% are 2nd-year | ✅ Same |
| `is_breakout_lag1` | Only ~15% break out | ✅ Same |
| `is_bust_injury_adj_lag1` | Only ~12% bust | ✅ Same |
| `is_injury_bounce_back_lag1` | Only ~5% | ✅ Same |
| `games_missed_lag1` | Most players don't miss games | ✅ Same |
| `early_declare` | Only ~13% left college early | ✅ Same |
| `college_x_rookie` | Product of college × rookie flag | ✅ Zero for non-rookies |
| `athletic_x_rookie` | Product of athletic × rookie | ✅ Zero for non-rookies |
| `college_x_2nd_year` | Product of college × 2nd-year | ✅ Zero for non-2nd-year |
| `athletic_score` | 36% have combine data | ⚠️ 64% get 0 (no data) |
| `combine_forty` | 36% have combine data | ⚠️ Same |
| `has_combine_data` | 36% have combine data | ✅ Flag helps model distinguish |
| `is_pre_prime` | Only ~5% are pre-prime age | ✅ Binary |

**Key insight**: The `has_combine_data` flag (added this audit) lets the model know when `athletic_score=0` means "no data" vs "average athlete". Without this flag, the model couldn't distinguish.

---

## 6. Feature Correlations with Target (fantasy_points)

No leakage detected — max correlation is 0.755 (TE receiving_yards_roll3).

### Top Predictors by Position

| Rank | QB | RB | WR | TE |
|------|----|----|----|----|
| 1 | pts_lag1 (0.670) | pts_lag1 (0.662) | rec_yds_lag1 (0.710) | rec_yds_roll3 (0.755) |
| 2 | pass_tds_lag1 (0.623) | rush_yds_roll3 (0.654) | pts_lag1 (0.709) | rec_yds_lag1 (0.752) |
| 3 | pass_yds_roll3 (0.622) | rush_yds_lag1 (0.646) | rec_yds_roll3 (0.704) | pts_lag1 (0.739) |
| 4 | pass_yds_lag1 (0.617) | adp (-0.629) | rec_lag1 (0.693) | tgt_lag1 (0.731) |
| 5 | adp (-0.613) | adp_tier (-0.613) | tgt_lag1 (0.692) | rec_lag1 (0.722) |

**Status**: ✅ No feature has >0.9 correlation with target. ADP is negatively correlated (lower ADP = higher points).

---

## 7. Coverage Summary

| Feature | Coverage | Method | Status |
|---------|----------|--------|--------|
| `adp` (real, <200) | 30% | 3-strategy name matching | ⚠️ 70% get ADP=200 |
| `athletic_score` | 36% | pfr_id bridge via player_info | ✅ + has_combine_data flag |
| `college_dominance` | 18% | draft_picks college stats | ⚠️ Structural limit |
| `combine_forty` | 36% | pfr_id bridge | ✅ |
| `injury_count_lag1` | 45% | gsis_id matching | ✅ |
| `entry_year` (roster) | 99.8% | roster merge | ✅ |
| `is_rookie` (via entry_year) | — | season - entry_year == 0 | ✅ 80-89/season detected |
| `qb_stack_bonus` | 25% of WR/TE | top-quartile QB teammates | ✅ Binary flag |
| `team_qb_avg_pts` | 100% | lagged QB avg per team | ✅ |

---

## 8. Model vs Baselines (Walk-Forward 2022-2025)

| Position | Mean R² | ADP-only R² | Model R² | Model vs ADP |
|----------|---------|-------------|----------|-------------|
| QB | — | 0.224 | **0.440** | **+24% MAE** |
| RB | — | 0.448 | **0.585** | **+3% MAE** |
| WR | — | 0.408 | **0.604** | **+25% MAE** |
| TE | — | 0.250 | **0.588** | **+38% MAE** |

Best model: **CatBoost** for all 4 positions.

Also beats "repeat last year's points" by 13-20% across all positions.

---

## 9. Known Limitations

1. **ADP coverage**: Only 30% of players have real ADP. The rest get ADP=200 (placeholder). The model still works because lag features and other signals compensate, but ADP is the strongest single predictor.

2. **College data**: Only 18% of players have college production stats. This is a structural limit — only drafted players with college stats in the draft_picks dataset are covered. Undrafted/older players have no college data.

3. **2019-2020 data quality**: ~951 player-seasons from 2019-2020 are missing team/name data in nflverse. These are dropped during the roster merge. We lose some training data but avoid garbage rows.

4. **Playoff games**: Games > 17 include playoff stats. This inflates season totals for playoff contributors. Currently accepted as-is.

5. **Negative fantasy points**: 25 rows have fp < 0 (fumbles/missed FGs by backup QBs). These are valid and included in training.

---

## 10. Verification Commands

```bash
# Quick data quality check
python3 -c "
from src.data.clean import clean_seasonal_stats, clean_roster_info
import pandas as pd; from pathlib import Path
s = clean_seasonal_stats(pd.read_parquet(Path('data')/'seasonal_stats.parquet'))
r = clean_roster_info(pd.read_parquet(Path('data')/'roster_info.parquet'))
print(f'Seasonal: {len(s)} rows, {s[\"team\"].nunique()} teams')
print(f'Roster: {len(r)} rows, {r[\"team\"].nunique()} teams')
print(f'Teams match: {set(s[\"team\"].dropna()) == set(r[\"team\"].dropna())}')
"

# Walk-forward validation
python -m src.models.compare --seasons 5
```
