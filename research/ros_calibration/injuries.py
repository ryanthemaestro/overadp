"""How long do injured fantasy players actually miss? (Team Hub availability)

The Team Hub had assumed: Yahoo "Out" misses only this week; IR misses four
weeks then 80% available; Questionable plays 75% of the time, Doubtful 25%.
This measures the real rates from public NFL injury reports and weekly roster
statuses, 2018-2025, for fantasy-relevant QB/RB/WR/TE (5+ half-PPR pts/game):

  Out: consecutive team games missed from the first "Out" report, by injury
       group, as a survival curve (Kaplan-Meier, censored at season end)
  IR:  consecutive team games spent on reserve (roster status RES)
  Questionable / Doubtful: share who played that week

Scored leave-one-season-out with the Brier score on "plays the game j games
from now" (j = 1..8), against the page's previous assumptions.
Run: python3 research/ros_calibration/injuries.py DATA_DIR
     (inj_YYYY.csv, roster_YYYY.csv, stats_YYYY.csv, games.csv)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1])
OUT = Path(__file__).parent / 'out'
SEASONS = range(2018, 2026)
POSITIONS = ['QB', 'RB', 'WR', 'TE']
HORIZON = 17  # longest absence tracked, in team games
GROUPS = ['Knee', 'Ankle', 'Hamstring', 'Concussion', 'Foot', 'Shoulder', 'Calf', 'Groin', 'Back', 'Hip', 'Illness']
MIN_GROUP = 40  # tested: 40 scored best held-out (0.1782 vs 0.1814 at 150)


def group(injury):
    text = str(injury or '').lower()
    for g in GROUPS:
        if g.lower() in text:
            return g
    return 'Other'


def load():
    stats, inj, ros = [], [], []
    for s in SEASONS:
        st = pd.read_csv(DATA / f'stats_{s}.csv', low_memory=False)
        st = st[(st.season_type == 'REG') & st.position.isin(POSITIONS) & (st.week <= 18)]
        stats.append(st.assign(half=st.fantasy_points + 0.5 * st.receptions.fillna(0))[['season', 'week', 'player_id', 'team', 'half']])
        i = pd.read_csv(DATA / f'inj_{s}.csv', low_memory=False)
        inj.append(i[(i.game_type == 'REG') & i.position.isin(POSITIONS)][['season', 'week', 'gsis_id', 'team', 'report_status', 'report_primary_injury']])
        r = pd.read_csv(DATA / f'roster_{s}.csv', low_memory=False, usecols=['season', 'week', 'gsis_id', 'team', 'position', 'status', 'game_type'])
        ros.append(r[(r.game_type == 'REG') & r.position.isin(POSITIONS)])
    games = pd.read_csv(DATA / 'games.csv', low_memory=False)
    games = games[(games.game_type == 'REG') & games.season.isin(SEASONS)]
    team_weeks = pd.concat([games[['season', 'week', 'home_team']].rename(columns={'home_team': 'team'}),
                            games[['season', 'week', 'away_team']].rename(columns={'away_team': 'team'})])
    return pd.concat(stats), pd.concat(inj), pd.concat(ros), team_weeks


def episodes(stats, inj, ros, team_weeks):
    """Absence episodes: (season, kind, group, length, censored)."""
    played = set(zip(stats.season, stats.week, stats.player_id))
    avg = stats.groupby(['season', 'player_id']).half.mean()
    relevant = set(avg[avg >= 5].index)
    tw = {k: sorted(v.week) for k, v in team_weeks.groupby(['season', 'team'])}
    rows, qd = [], []

    def run_length(season, pid, team, week):
        weeks = [w for w in tw.get((season, team), []) if w >= week]
        n = 0
        for w in weeks:
            if (season, w, pid) in played:
                return n, False
            n += 1
        return n, True  # still out when the season ended

    out = inj[inj.report_status == 'Out']
    seen = set()
    for r in out.sort_values(['season', 'week']).itertuples():
        key = (r.season, r.gsis_id)
        if (r.season, r.gsis_id) not in relevant or (r.season, r.week, r.gsis_id) in played:
            continue
        prev = [w for w in tw.get((r.season, r.team), []) if w < r.week]
        if prev and (r.season, prev[-1], r.gsis_id) not in played and key in seen:
            continue  # the same absence, already counted from its first week
        seen.add(key)
        n, cens = run_length(r.season, r.gsis_id, r.team, r.week)
        if n:
            rows.append({'season': r.season, 'kind': 'Out', 'group': group(r.report_primary_injury), 'length': n, 'censored': cens})
    res = ros[ros.status == 'RES'].sort_values(['season', 'week'])
    res_seen = set()
    for r in res.itertuples():
        key = (r.season, r.gsis_id)
        if key not in relevant or key in res_seen:
            continue
        res_seen.add(key)
        n, cens = run_length(r.season, r.gsis_id, r.team, r.week)
        if n:
            rows.append({'season': r.season, 'kind': 'IR', 'group': 'IR', 'length': n, 'censored': cens})
    for r in inj[inj.report_status.isin(['Questionable', 'Doubtful'])].itertuples():
        if (r.season, r.gsis_id) in relevant:
            qd.append({'season': r.season, 'status': r.report_status, 'played': (r.season, r.week, r.gsis_id) in played})
    return pd.DataFrame(rows), pd.DataFrame(qd)


def km(df):
    """S[k] = P(misses at least k games), k = 0..HORIZON, Kaplan-Meier with censoring."""
    s, surv = 1.0, [1.0]
    for k in range(1, HORIZON + 1):
        at_risk = (df.length >= k).sum()
        # Episodes that ended (player returned) after exactly k-1 missed games.
        ended = ((df.length == k - 1) & ~df.censored).sum()
        base = (df.length >= k - 1).sum()
        s *= 1 - (ended / base if base else 0)
        surv.append(round(float(s), 4) if at_risk or base else round(float(s), 4))
    return surv


def curves(ep):
    out = {}
    for kind in ['Out', 'IR']:
        part = ep[ep.kind == kind]
        out[kind] = {'all': km(part), 'n': int(len(part))}
        if kind == 'Out':
            for g, gp in part.groupby('group'):
                if len(gp) >= MIN_GROUP:
                    out[kind][g] = km(gp)
    return out


def play_prob(curve, missed, j):
    """P(plays the game j after the current one | already missing the current game after `missed` earlier misses)."""
    now = curve[min(missed + 1, HORIZON)]
    later = curve[min(missed + 1 + j, HORIZON)]
    return 1 - later / now if now > 0 else 1.0


def brier(ep, fit_curves, baseline):
    """Leave-one-season-out Brier on 'plays j games later', calibrated vs baseline."""
    scores = {'calibrated': [], 'previous page': []}
    for held in SEASONS:
        train, test = ep[ep.season != held], ep[ep.season == held]
        cur = curves(train)
        for r in test.itertuples():
            curve = cur[r.kind].get(r.group, cur[r.kind]['all']) if r.kind == 'Out' else cur['IR']['all']
            for j in range(1, 9):
                # Observed: plays game j (0-indexed from the first missed game) iff length <= j.
                if r.censored and r.length <= j:
                    continue
                y = 1.0 if r.length <= j else 0.0
                scores['calibrated'].append((play_prob(curve, 0, j) - y) ** 2)
                scores['previous page'].append((baseline(r.kind, j) - y) ** 2)
    return {k: round(float(np.mean(v)), 4) for k, v in scores.items()}


def previous(kind, j):
    return 1.0 if kind == 'Out' else (0.0 if j < 4 else 0.8)


def main():
    OUT.mkdir(exist_ok=True)
    stats, inj, ros, tw = load()
    ep, qd = episodes(stats, inj, ros, tw)
    cur = curves(ep)
    b = brier(ep, curves, previous)
    qrate = qd.groupby('status').played.mean().round(3).to_dict()
    med = {kind: float(ep[ep.kind == kind].length.median()) for kind in ['Out', 'IR']}
    print(f"episodes: {len(ep)} ({(ep.kind == 'Out').sum()} Out, {(ep.kind == 'IR').sum()} IR); Q/D reports: {len(qd)}")
    print('median games missed:', med)
    print('played when listed:', qrate)
    print('Brier (plays j games later, lower is better):', b)
    for g in ['all'] + [k for k in cur['Out'] if k not in ('all', 'n')]:
        c = cur['Out'][g]
        print(f"  Out/{g:11} P(miss >=2)={c[2]:.2f} >=3={c[3]:.2f} >=5={c[5]:.2f}")
    c = cur['IR']['all']; print(f"  IR           P(miss >=4)={c[4]:.2f} >=6={c[6]:.2f} >=9={c[9]:.2f}")
    result = {'curves': cur, 'played_when_listed': qrate, 'brier': b, 'median_games_missed': med}
    (OUT / 'injuries.json').write_text(json.dumps(result, indent=2))
    site_path = Path(__file__).parents[2] / 'site/yahoo/ros-model.json'
    site = json.loads(site_path.read_text())
    site['availability'] = {'horizon': HORIZON, 'out': {k: v for k, v in cur['Out'].items() if k != 'n'}, 'ir': cur['IR']['all'],
                            'questionable': qrate.get('Questionable'), 'doubtful': qrate.get('Doubtful'), 'groups': GROUPS, 'held_out_brier': b}
    site_path.write_text(json.dumps(site, separators=(',', ':')))


if __name__ == '__main__':
    main()
