"""Team defense (DEF) projections for the Yahoo Team Hub: backtest and calibration.

Yahoo default DEF scoring, rebuilt from public nflverse team stats and final
scores: sack 1, interception 2, fumble recovery 2, defensive or return TD 6,
safety 2, blocked kick 2, and points allowed (0: 10, 1-6: 7, 7-13: 4, 14-20: 1,
21-27: 0, 28-34: -1, 35+: -4). Points allowed is the opponent's final score,
which also counts any points the defense's own offense gave up; that is the
approximation public data allows.

Leave-one-season-out on 2019-2025:
  rest of season (weeks w..17) DEF points per game, for waivers and drops
  next week's points, for start/sit, including the betting line's implied
  total for the opponent (the classic "stream against weak offenses" signal)
Run: python3 research/ros_calibration/defenses.py DATA_DIR  (team_YYYY.csv, games.csv)
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
GAPS = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 99)]
TIERS = [(0, 0, 10), (1, 6, 7), (7, 13, 4), (14, 20, 1), (21, 27, 0), (28, 34, -1), (35, 999, -4)]


def points_allowed_score(pa):
    return np.select([(pa >= lo) & (pa <= hi) for lo, hi, _ in TIERS], [v for *_, v in TIERS])


def load():
    frames = []
    for season in range(2018, 2026):
        t = pd.read_csv(DATA / f'team_{season}.csv', low_memory=False)
        frames.append(t[(t.season_type == 'REG') & (t.week <= LAST_WEEK)])
    teams = pd.concat(frames, ignore_index=True)
    games = pd.read_csv(DATA / 'games.csv', low_memory=False)
    games = games[(games.game_type == 'REG') & games.season.between(2018, 2025) & (games.week <= LAST_WEEK)]
    rows = []
    for _, g in games.iterrows():
        for team, opp, allowed, scored, home in [(g.home_team, g.away_team, g.away_score, g.home_score, 1), (g.away_team, g.home_team, g.home_score, g.away_score, 0)]:
            opp_implied = (g.total_line - g.spread_line) / 2 if home else (g.total_line + g.spread_line) / 2
            rows.append({'season': g.season, 'week': g.week, 'team': team, 'opp': opp, 'allowed': allowed, 'scored': scored,
                         'home': home, 'opp_implied': opp_implied})
    sched = pd.DataFrame(rows)
    f = lambda c: teams[c].fillna(0)
    teams = teams.assign(stat_pts=f('def_sacks') + 2 * f('def_interceptions') + 2 * f('fumble_recovery_opp') + 6 * (f('def_tds') + f('special_teams_tds'))
                         + 2 * f('def_safeties') + 2 * (f('def_punt_blocks') + f('def_fg_blocks') + f('def_pat_blocks')))
    d = sched.merge(teams[['season', 'week', 'team', 'stat_pts']], on=['season', 'week', 'team'], how='inner')
    d['pts'] = d.stat_pts + points_allowed_score(d.allowed.values)
    return d


def build(d):
    rows = []
    for season in SEASONS:
        prev = d[d.season == season - 1]
        prior = prev.groupby('team').pts.mean()
        prior_off = prev.groupby('team').scored.mean()
        league = float(prev.pts.mean())
        cur = d[d.season == season]
        for w in AS_OF:
            past, fut = cur[cur.week < w], cur[cur.week >= w]
            obs = past.groupby('team').pts.agg(['mean', 'size'])
            # Offense strength so far, shrunk toward last season (4 games of weight).
            off = past.groupby('team').scored.agg(['sum', 'size'])
            off_str = ((prior_off.reindex(off.index).fillna(prior_off.mean()) * 4 + off['sum']) / (4 + off['size'])).reindex(prior_off.index).fillna(prior_off)
            agg = fut.groupby('team').agg(ros=('pts', 'mean'), ros_g=('pts', 'size'))
            agg['opp_off'] = fut.assign(o=fut.opp.map(off_str)).groupby('team').o.mean()
            nxt = fut[fut.week == w].set_index('team')
            df = agg[agg.ros_g >= 2].join(obs.rename(columns={'mean': 'obs', 'size': 'g'})).reset_index()
            df['g'] = df.g.fillna(0)
            df['base'] = df.team.map(prior).fillna(league)
            df['next'] = df.team.map(nxt.pts)
            df['opp_implied'] = df.team.map(nxt.opp_implied)
            # Renamed teams (e.g. OAK -> LV) can lack a prior value; fall back to the league mean.
            df['next_opp_off'] = df.team.map(nxt.opp.map(off_str) if len(nxt) else pd.Series(dtype=float))
            df.loc[df.opp_implied.notna(), 'next_opp_off'] = df.loc[df.opp_implied.notna(), 'next_opp_off'].fillna(float(prior_off.mean()))
            df['home'] = df.team.map(nxt.home)
            df['season'], df['week'] = season, w
            rows.append(df)
    return pd.concat(rows, ignore_index=True)


def bucket(g):
    return next(f'{lo}-{hi}' for lo, hi in BUCKETS if lo <= g <= hi)


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


def pick_accuracy(df, pred):
    right, gaps = [], []
    for _, wk in df.assign(p=pred).dropna(subset=['next']).groupby(['season', 'week']):
        i, j = np.triu_indices(len(wk), 1)
        a, b = wk.iloc[i], wk.iloc[j]
        keep = a.next.values != b.next.values
        r = np.where(a.p.values >= b.p.values, a.next.values > b.next.values, b.next.values > a.next.values)
        right.append(r[keep]); gaps.append(np.abs(a.p.values - b.p.values)[keep])
    return np.concatenate(right), np.concatenate(gaps)


ROS = {'blend': ['base', 'obs0'], 'blend+schedule': ['base', 'obs0', 'opp_off']}
WEEK = {'blend+opponent offense': ['base', 'obs0', 'next_opp_off', 'home'],
        'blend+betting line': ['base', 'obs0', 'opp_implied', 'home']}


def main():
    OUT.mkdir(exist_ok=True)
    rows = build(load())
    ros, nxt, picks = [], [], {}
    for held in SEASONS:
        train, test = rows[rows.season != held], rows[rows.season == held]
        preds = {'last season only': test.base.values, 'this season only': np.where(test.g > 0, np.nan_to_num(test.obs.values), test.base.values)}
        for name, cols in ROS.items():
            preds[name] = predict(test, cols, fit(train, cols))
        for name, p in preds.items():
            ros.append({'model': name, 'mae': float(np.average(np.abs(test.ros - p), weights=test.ros_g)), 'w': float(test.ros_g.sum())})
        tn, sn = train.dropna(subset=['next', 'opp_implied']), test.dropna(subset=['next', 'opp_implied'])
        week_preds = {name: predict(sn, cols, fit(tn.assign(w1=1.0), cols, target='next', weight='w1')) for name, cols in WEEK.items()}
        week_preds.update({k: v[test.index.get_indexer(sn.index)] for k, v in preds.items()})
        for name, p in week_preds.items():
            nxt.append({'model': name, 'mae': float(np.mean(np.abs(sn.next.values - p))), 'n': len(sn)})
            picks.setdefault(name, []).append(pick_accuracy(sn, p)[0])
    ros, nxt = pd.DataFrame(ros), pd.DataFrame(nxt)
    ros_s = (ros.assign(x=ros.mae * ros.w).groupby('model').x.sum() / ros.groupby('model').w.sum()).round(3).sort_values()
    nxt_s = (nxt.assign(x=nxt.mae * nxt.n).groupby('model').x.sum() / nxt.groupby('model').n.sum()).round(3).sort_values()
    pick_s = pd.Series({k: float(np.mean(np.concatenate(v))) for k, v in picks.items()}).round(3).sort_values(ascending=False)
    print('Rest-of-season MAE (pts/game):\n' + ros_s.to_string())
    print('\nNext-week MAE (pts):\n' + nxt_s.to_string())
    print('\nStart/sit pick accuracy:\n' + pick_s.to_string())
    best_ros, best_week = ros_s.index[0], next(m for m in pick_s.index if m in WEEK)
    parts = []
    for held in SEASONS:
        tn = rows[rows.season != held].dropna(subset=['next', 'opp_implied'])
        sn = rows[rows.season == held].dropna(subset=['next', 'opp_implied'])
        parts.append(sn.assign(p=predict(sn, WEEK[best_week], fit(tn.assign(w1=1.0), WEEK[best_week], target='next', weight='w1'))))
    allp = pd.concat(parts)
    r, g = pick_accuracy(allp, allp.p.values)
    by_gap = {f'{lo}-{hi}': {'accuracy': round(float(r[(g >= lo) & (g < hi)].mean()), 3), 'pairs': int(((g >= lo) & (g < hi)).sum())}
              for lo, hi in GAPS if ((g >= lo) & (g < hi)).sum() >= 200}
    print(f'\nShipped: rest of season = {best_ros}; next week = {best_week}')
    print('Next-week pick accuracy by projected gap:', by_gap)
    tn = rows.dropna(subset=['next', 'opp_implied'])
    result = {'rest_of_season_mae': ros_s.to_dict(), 'next_week_mae': nxt_s.to_dict(), 'pick_accuracy': pick_s.to_dict(),
              'next_week_pick_accuracy_by_gap': by_gap,
              'rest_of_season_model': {'name': best_ros, 'features': ['intercept'] + ROS.get(best_ros, []), 'buckets': [list(b) for b in BUCKETS],
                                       'by_bucket': fit(rows, ROS[best_ros]) if best_ros in ROS else None},
              'next_week_model': {'name': best_week, 'features': ['intercept'] + WEEK[best_week], 'buckets': [list(b) for b in BUCKETS],
                                  'by_bucket': fit(tn.assign(w1=1.0), WEEK[best_week], target='next', weight='w1')},
              'fallback_base': round(float(rows[rows.season == max(SEASONS)].ros.mean()), 3)}
    (OUT / 'defenses.json').write_text(json.dumps(result, indent=2))
    site_path = Path(__file__).parents[2] / 'site/yahoo/ros-model.json'
    site = json.loads(site_path.read_text())
    site['defense'] = {'scoring': 'Yahoo default: sack 1, INT 2, fumble rec 2, TD 6, safety 2, blocked kick 2, points-allowed tiers',
                       'fallback_base': result['fallback_base'], 'rest_of_season': result['rest_of_season_model'], 'next_week': result['next_week_model'],
                       'held_out': {'rest_of_season_mae': ros_s.to_dict(), 'next_week_pick_accuracy': pick_s.to_dict()}}
    site['start_sit']['accuracy']['DEF'] = {k: v['accuracy'] for k, v in by_gap.items()}
    site_path.write_text(json.dumps(site, separators=(',', ':')))


if __name__ == '__main__':
    main()
