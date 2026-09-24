"""Calibrate rest-of-season (ROS) projections for the Yahoo Team Hub.

Question: at week w, what is the best estimate of a player's half-PPR points per
game for weeks w..17 (through the usual fantasy playoffs)? Candidates blend the
walk-forward v6 preseason projection with what the player has done so far.

Everything is evaluated leave-one-season-out on 2019-2025: fit on six seasons,
score the seventh, so reported errors are out of sample.

Then, at the game level, test team-context factors against the chosen model's
residuals: opponent strength, home field, and late-season teams with nothing
to play for. A factor is kept only if it improves held-out error.

Inputs (public): nflverse weekly player stats and schedules, and the v6
walk-forward preseason predictions (research/public-model-v6 branch).
Run: python3 research/ros_calibration/calibrate.py DATA_DIR
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1])
OUT = Path(__file__).parent / 'out'
SEASONS = range(2019, 2026)
POSITIONS = ['QB', 'RB', 'WR', 'TE']
LAST_WEEK = 17            # fantasy playoffs end here in most leagues
AS_OF = range(2, 15)      # decision weeks: weeks 1..w-1 are known
BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 16)]


def bucket(g):
    for lo, hi in BUCKETS:
        if lo <= g <= hi:
            return f'{lo}-{hi}'
    return None


def load():
    frames = []
    for season in SEASONS:
        s = pd.read_csv(DATA / f'stats_{season}.csv', low_memory=False)
        s = s[(s.season_type == 'REG') & s.position.isin(POSITIONS) & (s.week <= LAST_WEEK)]
        s = s.assign(half=s.fantasy_points + 0.5 * s.receptions.fillna(0))
        frames.append(s[['season', 'week', 'player_id', 'position', 'team', 'opponent_team',
                         'half', 'targets', 'carries', 'attempts', 'receptions']])
    weekly = pd.concat(frames, ignore_index=True).fillna({'targets': 0, 'carries': 0, 'attempts': 0})
    pre = pd.read_csv(DATA / 'preseason.csv')
    pre = pre.rename(columns={'forecast_year': 'season'})
    games_in_season = np.where(pre.season <= 2020, 16, 17)
    pre = pre.assign(pre_pg=pre.pred_half / games_in_season)[['season', 'player_id', 'pre_pg', 'is_rookie']]
    games = pd.read_csv(DATA / 'games.csv', low_memory=False)
    games = games[(games.game_type == 'REG') & games.season.isin(SEASONS)]
    return weekly, pre, games


def build_rows(weekly, pre):
    """One row per (season, as-of week, player) with a ROS target of >= 2 games."""
    rows = []
    for season in SEASONS:
        w_season = weekly[weekly.season == season]
        p_season = pre[pre.season == season].set_index('player_id')
        for w in AS_OF:
            past = w_season[w_season.week < w].groupby('player_id').agg(
                g=('half', 'size'), obs_pg=('half', 'mean'), tgt_pg=('targets', 'mean'),
                car_pg=('carries', 'mean'), att_pg=('attempts', 'mean'))
            future = w_season[w_season.week >= w].groupby('player_id').agg(
                ros_g=('half', 'size'), ros_pg=('half', 'mean'), position=('position', 'last'))
            future = future[future.ros_g >= 2]
            df = future.join(past, how='left').join(p_season[['pre_pg', 'is_rookie']], how='inner')
            df = df.fillna({'g': 0}).reset_index()
            df['season'], df['week'] = season, w
            rows.append(df)
    return pd.concat(rows, ignore_index=True)


def wmae(y, yhat, w):
    return float(np.sum(w * np.abs(y - yhat)) / np.sum(w))


def fit_k(train):
    """Shrinkage weight k in (k*pre + g*obs)/(k+g), chosen to minimize weighted MAE."""
    best = None
    for k in np.arange(0.5, 30.01, 0.5):
        g = train.g.values
        obs = np.nan_to_num(train.obs_pg.values)
        pred = (k * train.pre_pg.values + g * obs) / (k + g)
        err = wmae(train.ros_pg.values, pred, train.ros_g.values)
        if best is None or err < best[1]:
            best = (float(k), err)
    return best[0]


def design(df):
    """Features for the regression model: preseason, results so far, and usage."""
    obs = np.nan_to_num(df.obs_pg.values)
    return np.column_stack([np.ones(len(df)), df.pre_pg.values, obs,
                            np.nan_to_num(df.tgt_pg.values), np.nan_to_num(df.car_pg.values),
                            np.nan_to_num(df.att_pg.values)])


def fit_regression(train, ridge=1.0):
    """Weighted ridge per games-played bucket; bucket 0 (no games) uses preseason only."""
    coefs = {}
    for b in {bucket(g) for g in train.g if g >= 1}:
        part = train[train.g.map(bucket) == b]
        X, y, w = design(part), part.ros_pg.values, part.ros_g.values
        W = np.sqrt(w)[:, None]
        A = (X * W).T @ (X * W) + ridge * np.diag([0, 1, 1, 1, 1, 1])
        coefs[b] = np.linalg.solve(A, (X * W).T @ (y * np.sqrt(w))).tolist()
    return coefs


def predict(df, model):
    kind, params = model
    obs = np.nan_to_num(df.obs_pg.values)
    g = df.g.values
    if kind == 'preseason':
        return df.pre_pg.values
    if kind == 'observed':
        return np.where(g > 0, obs, df.pre_pg.values)
    if kind == 'shrink':
        return (params * df.pre_pg.values + g * obs) / (params + g)
    out = df.pre_pg.values.copy()
    X = design(df)
    for i, gi in enumerate(g):
        b = bucket(gi)
        if b in params:
            out[i] = X[i] @ np.array(params[b])
    return np.maximum(out, 0)


def evaluate(rows):
    """Leave-one-season-out comparison per position."""
    results, final = [], {}
    for pos in POSITIONS:
        data = rows[rows.position == pos]
        for held in SEASONS:
            train, test = data[data.season != held], data[data.season == held]
            models = {'preseason': ('preseason', None), 'observed': ('observed', None),
                      'shrink': ('shrink', fit_k(train)), 'shrink+usage': ('regression', fit_regression(train))}
            for name, model in models.items():
                pred = predict(test, model)
                for early, part in [('weeks 2-5', test.week <= 5), ('weeks 6-14', test.week >= 6)]:
                    t = test[part]
                    results.append({'position': pos, 'held_out': held, 'model': name, 'phase': early,
                                    'mae': wmae(t.ros_pg.values, pred[part.values], t.ros_g.values),
                                    'weight': float(t.ros_g.sum())})
        final[pos] = {'k': fit_k(data), 'regression': fit_regression(data)}
    res = pd.DataFrame(results)
    summary = (res.assign(wm=res.mae * res.weight).groupby(['position', 'model', 'phase'])
               .agg(wm=('wm', 'sum'), w=('weight', 'sum')))
    summary = (summary.wm / summary.w).unstack('phase').round(3)
    return summary, final


def team_context(weekly, rows, games, final):
    """Game-level residual tests for opponent strength, home field and late-season motivation."""
    records = []
    for season in SEASONS:
        g_season = games[games.season == season]
        w_season = weekly[weekly.season == season]
        for w in AS_OF:
            known = w_season[w_season.week < w]
            # Fantasy points allowed per game to each position, by defense, through week w-1.
            allowed = known.groupby(['opponent_team', 'position', 'week']).half.sum().groupby(['opponent_team', 'position']).mean()
            league = allowed.groupby('position').mean()
            done = g_season[g_season.week < w].dropna(subset=['result'])
            wins = pd.concat([done.assign(team=done.home_team, win=(done.result > 0) + 0.5 * (done.result == 0)),
                              done.assign(team=done.away_team, win=(done.result < 0) + 0.5 * (done.result == 0))])
            win_pct = wins.groupby('team').win.mean()
            snap = rows[(rows.season == season) & (rows.week == w)]
            if snap.empty:
                continue
            for pos in POSITIONS:
                part = snap[snap.position == pos]
                if part.empty:
                    continue
                base = pd.Series(predict(part, ('regression', final[pos]['regression'])), index=part.player_id)
                fut = w_season[(w_season.week >= w) & w_season.player_id.isin(base.index) & (w_season.position == pos)]
                fut = fut.merge(g_season[['week', 'home_team', 'away_team']], on='week')
                fut = fut[(fut.team == fut.home_team) | (fut.team == fut.away_team)]
                fut = fut[(fut.opponent_team == fut.home_team) | (fut.opponent_team == fut.away_team)]
                opp = fut.opponent_team.map(lambda t: allowed.get((t, pos), np.nan)) / league.get(pos, np.nan)
                records.append(pd.DataFrame({
                    'season': season, 'as_of': w, 'week': fut.week.values, 'position': pos,
                    'actual': fut.half.values, 'base': base.reindex(fut.player_id).values,
                    'opp_index': opp.values, 'home': (fut.team == fut.home_team).astype(int).values,
                    'team_win_pct': fut.team.map(win_pct).values,
                    'weeks_ahead': fut.week.values - w}))
    games_df = pd.concat(records, ignore_index=True).dropna(subset=['base'])
    games_df = games_df[games_df.base > 1]
    games_df['ratio'] = games_df.actual / games_df.base
    return games_df


def factor_tests(gdf):
    """Held-out check: does scaling by each factor reduce per-game error?"""
    out = {}
    def held_out(apply):
        errs = []
        for held in SEASONS:
            train, test = gdf[gdf.season != held], gdf[gdf.season == held]
            pred = apply(train, test)
            errs.append((np.abs(test.actual - pred).sum(), len(test)))
        return sum(e for e, _ in errs) / sum(n for _, n in errs)
    base_err = held_out(lambda tr, te: te.base)
    out['baseline_game_mae'] = round(base_err, 3)

    # Opponent strength: multiplier = 1 + b*(opp_index-1), shrunk by how far ahead the game is.
    def opp(tr, te):
        m = tr.dropna(subset=['opp_index'])
        m = m[m.as_of >= 4]
        x = (m.opp_index - 1).clip(-0.6, 0.6)
        b = float(np.sum(x * (m.ratio - 1)) / np.sum(x * x))
        xi = (te.opp_index.fillna(1) - 1).clip(-0.6, 0.6).where(te.as_of >= 4, 0)
        return te.base * (1 + b * xi)
    out['opponent_strength_game_mae'] = round(held_out(opp), 3)

    def home(tr, te):
        h = float(tr[tr.home == 1].ratio.median() / tr[tr.home == 0].ratio.median())
        return te.base * np.where(te.home == 1, np.sqrt(h), 1 / np.sqrt(h))
    out['home_field_game_mae'] = round(held_out(home), 3)

    # Late season (weeks 15-17) on teams at or below .300 when the decision is made.
    late = gdf[(gdf.week >= 15)]
    losing = late[late.team_win_pct <= 0.3]
    other = late[late.team_win_pct > 0.3]
    out['late_season_losing_team_ratio_median'] = round(float(losing.ratio.median()), 3)
    out['late_season_other_team_ratio_median'] = round(float(other.ratio.median()), 3)
    out['late_season_losing_team_games'] = int(len(losing))
    def motivation(tr, te):
        lt = tr[tr.week >= 15]
        f = float(lt[lt.team_win_pct <= 0.3].ratio.median() / lt[lt.team_win_pct > 0.3].ratio.median())
        return te.base * np.where((te.week >= 15) & (te.team_win_pct <= 0.3), f, 1)
    out['late_season_motivation_game_mae'] = round(held_out(motivation), 3)
    # Effect sizes fit on all seasons, for the report.
    m = gdf.dropna(subset=['opp_index'])
    m = m[m.as_of >= 4]
    x = (m.opp_index - 1).clip(-0.6, 0.6)
    out['opponent_strength_slope'] = round(float(np.sum(x * (m.ratio - 1)) / np.sum(x * x)), 3)
    out['home_vs_away_ratio'] = round(float(gdf[gdf.home == 1].ratio.median() / gdf[gdf.home == 0].ratio.median()), 3)
    return out


def main():
    OUT.mkdir(exist_ok=True)
    weekly, pre, games = load()
    rows = build_rows(weekly, pre)
    summary, final = evaluate(rows)
    gdf = team_context(weekly, rows, games, final)
    factors = factor_tests(gdf)
    summary.to_csv(OUT / 'ros_model_comparison.csv')
    (OUT / 'factor_tests.json').write_text(json.dumps(factors, indent=2))
    (OUT / 'fitted.json').write_text(json.dumps(final, indent=2))
    # The browser model: per position, ridge coefficients by games-played bucket.
    site = {'version': 1, 'target': 'half-PPR points per game, weeks w..17',
            'trained_on': [min(SEASONS), max(SEASONS)], 'features': ['intercept', 'preseason_pg', 'observed_pg', 'targets_pg', 'carries_pg', 'attempts_pg'],
            'buckets': [list(b) for b in BUCKETS],
            'positions': {pos: final[pos]['regression'] for pos in POSITIONS},
            'held_out_mae': {pos: {phase: float(summary.loc[(pos, 'shrink+usage'), phase]) for phase in summary.columns} for pos in POSITIONS},
            'preseason_only_mae': {pos: {phase: float(summary.loc[(pos, 'preseason'), phase]) for phase in summary.columns} for pos in POSITIONS}}
    (Path(__file__).parents[2] / 'site/yahoo/ros-model.json').write_text(json.dumps(site, separators=(',', ':')))
    print(f'rows: {len(rows):,}  player-games for factor tests: {len(gdf):,}')
    print(summary.to_string())
    print(json.dumps(factors, indent=2))


if __name__ == '__main__':
    main()
