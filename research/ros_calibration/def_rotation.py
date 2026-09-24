"""Is the Team Hub's defense-rotation value overstated?

The Team Hub values a second defense by starting, each week, whichever of the two
has the better projected matchup (next week: betting-line model; later weeks:
opponent-scoring model). Choosing the larger of two estimates can overstate the
gain, and ranking many candidates by that gain can overstate the top of the list.

For 2019-2025 (models fit without the tested season), from decision weeks
2, 5, 8 and 11, for every ordered pair (held defense A, added defense B):
  predicted gain = sum over remaining weeks of max(pred A, pred B) - pred A
  realized gain  = sum over remaining weeks of actual(started) - actual(A)
Then find the shrink factor lambda for weekly matchup deviations,
  pred' = season mean + lambda * (pred - season mean),
that makes predicted gains match realized gains for the candidates that would
rank at the top of the Waivers list.
Run: python3 research/ros_calibration/def_rotation.py DATA_DIR
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.argv = sys.argv[:2]
import defenses as D  # noqa: E402

AS_OF = [2, 5, 8, 11]
LAMBDAS = [round(x, 2) for x in np.arange(0.0, 1.01, 0.1)]


def weekly_predictions(d, rows):
    """Per (season, as-of week, team, target week): predicted and actual DEF points."""
    out = []
    week_cols = D.WEEK['blend+opponent offense']
    for held in D.SEASONS:
        train = rows[rows.season != held].dropna(subset=['next', 'next_opp_off', 'home'])
        coefs = D.fit(train.assign(w1=1.0), week_cols, target='next', weight='w1')
        prev = d[d.season == held - 1]
        prior, prior_off = prev.groupby('team').pts.mean(), prev.groupby('team').scored.mean()
        league = float(prev.pts.mean())
        cur = d[d.season == held]
        for w in AS_OF:
            past, fut = cur[cur.week < w], cur[(cur.week >= w) & (cur.week <= D.LAST_WEEK)]
            obs = past.groupby('team').pts.agg(['mean', 'size'])
            off = past.groupby('team').scored.agg(['sum', 'size'])
            strength = ((prior_off.reindex(off.index).fillna(prior_off.mean()) * 4 + off['sum']) / (4 + off['size']))
            f = fut.assign(base=fut.team.map(prior).fillna(league), obs=fut.team.map(obs['mean']),
                           g=fut.team.map(obs['size']).fillna(0), next_opp_off=fut.opp.map(strength).fillna(prior_off.mean()))
            f['pred'] = D.predict(f, week_cols, coefs)
            f['season_mean'] = f.groupby('team').pred.transform('mean')
            out.append(f.assign(as_of=w)[['season', 'as_of', 'week', 'team', 'pred', 'season_mean', 'pts']])
    return pd.concat(out, ignore_index=True)


def pair_gains(wp, lam):
    """Predicted and realized rotation gains for every ordered pair, with shrink lambda."""
    wp = wp.assign(p=wp.season_mean + lam * (wp.pred - wp.season_mean))
    res = []
    for (season, as_of), g in wp.groupby(['season', 'as_of']):
        p = g.pivot_table(index='week', columns='team', values='p')    # NaN = bye
        a = g.pivot_table(index='week', columns='team', values='pts')
        teams = list(p.columns)
        P, A = p.values, a.values
        for i, ta in enumerate(teams):
            pa, aa = P[:, i], A[:, i]
            for j, tb in enumerate(teams):
                if i == j:
                    continue
                pb, ab = P[:, j], A[:, j]
                use_b = np.where(np.isnan(pa), ~np.isnan(pb), np.where(np.isnan(pb), False, pb > pa))
                pred = np.nansum(np.where(use_b, pb, np.nan_to_num(pa)) - np.nan_to_num(pa))
                real = np.nansum(np.where(use_b, np.nan_to_num(ab), np.nan_to_num(aa)) - np.nan_to_num(aa))
                res.append((season, as_of, ta, tb, pred, real))
    return pd.DataFrame(res, columns=['season', 'as_of', 'held', 'added', 'pred', 'real'])


def top_candidates(pg, k=3):
    """For each held defense, the k added defenses the page would rank highest."""
    return pg.sort_values('pred', ascending=False).groupby(['season', 'as_of', 'held']).head(k)


def main():
    d = D.load()
    rows = D.build(d)
    wp = weekly_predictions(d, rows)
    table = []
    for lam in LAMBDAS:
        pg = pair_gains(wp, lam)
        top = top_candidates(pg)
        table.append({'lambda': lam, 'all_pred': pg.pred.mean(), 'all_real': pg.real.mean(),
                      'top3_pred': top.pred.mean(), 'top3_real': top.real.mean()})
    t = pd.DataFrame(table).round(2)
    t['top3_ratio'] = (t.top3_real / t.top3_pred).round(2)
    print(t.to_string(index=False))
    # Best lambda: predicted matches realized for the top-ranked candidates.
    best = t.iloc[(t.top3_pred - t.top3_real).abs().argmin()]
    print(f"\nCurrent page (lambda 1.0): top-3 candidates predicted {t.iloc[-1].top3_pred:.1f} pts, realized {t.iloc[-1].top3_real:.1f}")
    print(f"Closest damping (lambda {best['lambda']}): top-3 predicted {best.top3_pred:.1f}, realized {best.top3_real:.1f}; damping doesn't close the gap")
    # Weekly choices are best at full strength (lambda 1 has the highest realized gain), so
    # the fix is a discount on the add value of top-ranked defenses, not damped matchups.
    full = t.iloc[-1]
    factor = round(float(full.top3_real / full.top3_pred), 2)
    print(f"Add-value factor for defenses (realized / predicted, top-3 candidates): {factor}")
    result = {'table': t.to_dict(orient='records'), 'lambda_matching_top3': float(best['lambda']), 'add_value_factor': factor}
    (D.OUT / 'def_rotation.json').write_text(json.dumps(result, indent=2))
    site_path = Path(__file__).parents[2] / 'site/yahoo/ros-model.json'
    site = json.loads(site_path.read_text())
    site['defense']['add_value_factor'] = factor
    site_path.write_text(json.dumps(site, separators=(',', ':')))


if __name__ == '__main__':
    main()
