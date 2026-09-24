"""Kicker projections for the Yahoo Team Hub: backtest and calibration.

The Team Hub currently projects a kicker by blending last season's points per
game with this season's (this season's weight = min(0.5, games/4)). This script
asks whether anything does better, leave-one-season-out on 2019-2025:

  rest of season (weeks w..17) points per game, for waiver/drop decisions
  next week's points, for start/sit, including the pregame implied team total

Candidate inputs: last season, this season, the kicker's team scoring (so far
and last season), and the share of remaining games played indoors. A factor is
kept only if it lowers held-out error. Kicker scoring is Yahoo's default
(FG 0-39: 3, 40-49: 4, 50+: 5, PAT: 1, no miss penalties).
Run: python3 research/ros_calibration/kickers.py DATA_DIR  (needs stats_2018.csv too)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1])
OUT = Path(__file__).parent / 'out'
SEASONS = range(2019, 2026)
AS_OF = range(2, 15)
LAST_WEEK = 17
BUCKETS = [(0, 0), (1, 2), (3, 5), (6, 16)]
GAPS = [(0, 1), (1, 2), (2, 3), (3, 99)]
INDOOR = {'dome', 'closed'}


def bucket(g):
    return next(f'{lo}-{hi}' for lo, hi in BUCKETS if lo <= g <= hi)


def kicker_points(s):
    f = lambda c: s[c].fillna(0)
    return 3 * (f('fg_made_0_19') + f('fg_made_20_29') + f('fg_made_30_39')) + 4 * f('fg_made_40_49') + \
        5 * (f('fg_made_50_59') + f('fg_made_60_')) + f('pat_made')


def load():
    frames = []
    for season in range(2018, 2026):
        s = pd.read_csv(DATA / f'stats_{season}.csv', low_memory=False)
        s = s[(s.season_type == 'REG') & (s.position == 'K') & (s.week <= LAST_WEEK)]
        frames.append(s.assign(pts=kicker_points(s))[['season', 'week', 'player_id', 'team', 'pts']])
    kicks = pd.concat(frames, ignore_index=True)
    games = pd.read_csv(DATA / 'games.csv', low_memory=False)
    games = games[(games.game_type == 'REG') & games.season.between(2018, 2025) & (games.week <= LAST_WEEK)]
    rows = []
    for _, g in games.iterrows():
        indoor = g.roof in INDOOR
        for team, opp, scored, home in [(g.home_team, g.away_team, g.home_score, True), (g.away_team, g.home_team, g.away_score, False)]:
            implied = (g.total_line + g.spread_line) / 2 if home else (g.total_line - g.spread_line) / 2
            rows.append({'season': g.season, 'week': g.week, 'team': team, 'scored': scored, 'indoor': indoor, 'implied': implied})
    team_games = pd.DataFrame(rows)
    return kicks, team_games


def build(kicks, tg):
    rows = []
    for season in SEASONS:
        prev = kicks[kicks.season == season - 1].groupby('player_id').pts.agg(['mean', 'size'])
        prior = prev['mean'].where(prev['size'] >= 4)
        league_prior = float(kicks[kicks.season == season - 1].pts.mean())
        tprev = tg[tg.season == season - 1].groupby('team').scored.mean()
        cur, tcur = kicks[kicks.season == season], tg[tg.season == season]
        for w in AS_OF:
            past = cur[cur.week < w].groupby('player_id').agg(g=('pts', 'size'), obs=('pts', 'mean'))
            fut = cur[cur.week >= w].groupby('player_id').agg(ros_g=('pts', 'size'), ros=('pts', 'mean'), team=('team', 'last'))
            nxt = cur[cur.week == w].set_index('player_id').pts.rename('next')
            df = fut[fut.ros_g >= 2].join(past).join(nxt).reset_index()
            df['g'] = df.g.fillna(0)
            df['prior'] = df.player_id.map(prior)
            df['base'] = df.prior.fillna(league_prior)
            tpast = tcur[tcur.week < w].groupby('team').scored.mean()
            df['team_ppg'] = df.team.map(tpast).fillna(df.team.map(tprev)).fillna(tprev.mean())
            df['team_prior'] = df.team.map(tprev).fillna(tprev.mean())
            rem = tcur[tcur.week >= w].groupby('team').indoor.mean()
            df['indoor_share'] = df.team.map(rem).fillna(0)
            wk = tcur[tcur.week == w].set_index('team')
            df['implied'] = df.team.map(wk.implied)
            df['indoor_next'] = df.team.map(wk.indoor).astype(float)
            df['season'], df['week'] = season, w
            rows.append(df)
    return pd.concat(rows, ignore_index=True)


def page_method(df):
    obs, prior, g = df.obs.values, df.prior.values, df.g.values
    wt = np.minimum(0.5, g / 4)
    out = np.where(~np.isnan(prior) & ~np.isnan(obs), (1 - wt) * prior + wt * np.nan_to_num(obs),
                   np.where(~np.isnan(prior), prior, obs))
    return np.where(np.isnan(out), df.base.values, out)


FEATURES = {'blend': ['base', 'obs0'], 'blend+indoor': ['base', 'obs0', 'indoor_share'], 'blend+team': ['base', 'obs0', 'team_ppg', 'team_prior'],
            'blend+team+indoor': ['base', 'obs0', 'team_ppg', 'team_prior', 'indoor_share']}


def design(df, cols):
    d = df.assign(obs0=np.nan_to_num(df.obs.values))
    return np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])


def fit(train, cols, target='ros', weight='ros_g', ridge=1.0):
    coefs = {}
    for b in {bucket(g) for g in train.g}:
        part = train[train.g.map(bucket) == b]
        X, y, w = design(part, cols), part[target].values, part[weight].values
        W = np.sqrt(w)[:, None]
        A = (X * W).T @ (X * W) + ridge * np.eye(X.shape[1]) * np.r_[0, np.ones(X.shape[1] - 1)]
        coefs[b] = np.linalg.solve(A, (X * W).T @ (y * np.sqrt(w))).tolist()
    return coefs


def predict(df, cols, coefs):
    X = design(df, cols)
    return np.array([X[i] @ np.array(coefs[bucket(g)]) if bucket(g) in coefs else df.base.values[i] for i, g in enumerate(df.g.values)])


def wmae(y, p, w):
    return float(np.sum(w * np.abs(y - p)) / np.sum(w))


def pick_accuracy(df, pred):
    """Pairs of kickers in the same week; share where the higher projection scored more."""
    right, gaps = [], []
    for (_, _), wk in df.assign(p=pred).dropna(subset=['next']).groupby(['season', 'week']):
        wk = wk.nlargest(32, 'p')
        i, j = np.triu_indices(len(wk), 1)
        a, b = wk.iloc[i], wk.iloc[j]
        keep = a.next.values != b.next.values
        pick_a = a.p.values >= b.p.values
        r = np.where(pick_a, a.next.values > b.next.values, b.next.values > a.next.values)
        right.append(r[keep]); gaps.append(np.abs(a.p.values - b.p.values)[keep])
    return np.concatenate(right), np.concatenate(gaps)


def main():
    OUT.mkdir(exist_ok=True)
    kicks, tg = load()
    rows = build(kicks, tg)
    ros, nxt, picks = [], [], {}
    for held in SEASONS:
        train, test = rows[rows.season != held], rows[rows.season == held]
        preds = {'page (current)': page_method(test), 'last season only': test.base.values,
                 'this season only': np.where(test.g > 0, np.nan_to_num(test.obs.values), test.base.values)}
        for name, cols in FEATURES.items():
            preds[name] = predict(test, cols, fit(train, cols))
        # Next week only: add the pregame implied team total and roof to the best ROS inputs.
        tn, sn = train.dropna(subset=['next', 'implied']), test.dropna(subset=['next', 'implied'])
        wk_cols = FEATURES['blend+team'] + ['implied', 'indoor_next']
        wk_coefs = fit(tn.assign(w1=1.0), wk_cols, target='next', weight='w1')
        for name, p in preds.items():
            ros.append({'model': name, 'held': held, 'mae': wmae(test.ros.values, p, test.ros_g.values), 'w': float(test.ros_g.sum())})
            m = test.next.notna().values
            nxt.append({'model': name, 'held': held, 'mae': float(np.mean(np.abs(test.next.values[m] - p[m]))), 'n': int(m.sum())})
            r, _ = pick_accuracy(test, p)
            picks.setdefault(name, []).append(r)
        p = predict(sn, wk_cols, wk_coefs)
        nxt.append({'model': 'blend+team + implied total + roof', 'held': held, 'mae': float(np.mean(np.abs(sn.next.values - p))), 'n': len(sn)})
        r, _ = pick_accuracy(sn, p)
        picks.setdefault('blend+team + implied total + roof', []).append(r)
    ros = pd.DataFrame(ros); nxt = pd.DataFrame(nxt)
    ros_s = (ros.assign(x=ros.mae * ros.w).groupby('model').x.sum() / ros.groupby('model').w.sum()).round(3).sort_values()
    nxt_s = (nxt.assign(x=nxt.mae * nxt.n).groupby('model').x.sum() / nxt.groupby('model').n.sum()).round(3).sort_values()
    pick_s = pd.Series({k: float(np.mean(np.concatenate(v))) for k, v in picks.items()}).round(3).sort_values(ascending=False)
    print('Rest-of-season MAE (pts/game):\n' + ros_s.to_string())
    print('\nNext-week MAE (pts):\n' + nxt_s.to_string())
    print('\nStart/sit pick accuracy:\n' + pick_s.to_string())
    best = ros_s.index[0]
    final_cols = FEATURES[best]
    # Start/sit accuracy by projected gap for the next-week model (with the betting line).
    wk_cols = FEATURES['blend+team'] + ['implied', 'indoor_next']
    parts = []
    for held in SEASONS:
        tn = rows[(rows.season != held)].dropna(subset=['next', 'implied'])
        sn = rows[(rows.season == held)].dropna(subset=['next', 'implied'])
        parts.append(sn.assign(p=predict(sn, wk_cols, fit(tn.assign(w1=1.0), wk_cols, target='next', weight='w1'))))
    allp = pd.concat(parts)
    r, g = pick_accuracy(allp, allp.p.values)
    by_gap = {f'{lo}-{hi}': {'accuracy': round(float(r[(g >= lo) & (g < hi)].mean()), 3), 'pairs': int(((g >= lo) & (g < hi)).sum())}
              for lo, hi in GAPS if ((g >= lo) & (g < hi)).sum() >= 200}
    print('\nNext-week pick accuracy by projected gap:', by_gap)
    tn = rows.dropna(subset=['next', 'implied'])
    result = {'rest_of_season_mae': ros_s.to_dict(), 'next_week_mae': nxt_s.to_dict(), 'pick_accuracy': pick_s.to_dict(),
              'best_rest_of_season': best, 'next_week_pick_accuracy_by_gap': by_gap,
              'rest_of_season_model': {'features': ['intercept'] + final_cols, 'buckets': [list(b) for b in BUCKETS], 'by_bucket': fit(rows, final_cols)},
              'next_week_model': {'features': ['intercept'] + wk_cols, 'buckets': [list(b) for b in BUCKETS],
                                  'by_bucket': fit(tn.assign(w1=1.0), wk_cols, target='next', weight='w1')}}
    (OUT / 'kickers.json').write_text(json.dumps(result, indent=2))
    # Browser model: both kicker models, the fallback for kickers with no prior season,
    # and start/sit accuracy (bands above 3 pts share the 3+ rate).
    site_path = Path(__file__).parents[2] / 'site/yahoo/ros-model.json'
    site = json.loads(site_path.read_text())
    site['kicker'] = {'scoring': 'Yahoo default: FG 0-39 3, 40-49 4, 50+ 5, PAT 1',
                      'fallback_base': round(float(kicks[kicks.season == max(SEASONS)].pts.mean()), 3),
                      'rest_of_season': result['rest_of_season_model'], 'next_week': result['next_week_model'],
                      'held_out': {'rest_of_season_mae': ros_s.to_dict(), 'next_week_pick_accuracy': pick_s.to_dict()}}
    three = by_gap.get('3-99', by_gap.get('2-3'))['accuracy']
    site['start_sit']['accuracy']['K'] = {'0-1': by_gap['0-1']['accuracy'], '1-2': by_gap['1-2']['accuracy'],
                                          '2-3': by_gap['2-3']['accuracy'], '3-5': three, '5-99': three}
    site_path.write_text(json.dumps(site, separators=(',', ':')))


if __name__ == '__main__':
    main()
