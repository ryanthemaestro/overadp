"""How often does the calibrated model pick the right player in a start/sit?

For every decision week w (2-14) in 2019-2025, compare pairs of same-position,
fantasy-relevant players who both played in week w. The model (fit without the
held-out season) "starts" the one with the higher projected points per game.
Accuracy is reported by the size of the projected gap, which is what the page
shows next to each call.
Run: python3 research/ros_calibration/start_sit.py DATA_DIR
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.argv = sys.argv[:2]
import calibrate as c  # noqa: E402

GAPS = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 99)]
# Roughly the players a 10-12 team league actually starts or benches, per position.
RELEVANT = {'QB': 24, 'RB': 48, 'WR': 60, 'TE': 24}


def main():
    weekly, pre, _ = c.load()
    rows = c.build_rows(weekly, pre)
    out, rng = [], np.random.default_rng(7)
    for pos in c.POSITIONS:
        data = rows[rows.position == pos]
        for held in c.SEASONS:
            model = ('regression', c.fit_regression(data[data.season != held]))
            test = data[data.season == held].copy()
            test['pred'] = c.predict(test, model)
            test['season_avg'] = np.where(test.g > 0, np.nan_to_num(test.obs_pg), test.pre_pg)
            games = weekly[(weekly.season == held) & (weekly.position == pos)][['week', 'player_id', 'half']]
            for w, snap in test.groupby('week'):
                snap = snap.merge(games[games.week == w], on='player_id')
                snap = snap.nlargest(RELEVANT[pos], 'pred')
                if len(snap) < 2:
                    continue
                i, j = np.triu_indices(len(snap), 1)
                a, b = snap.iloc[i].reset_index(drop=True), snap.iloc[j].reset_index(drop=True)
                keep = a.half.values != b.half.values
                for name, col in [('calibrated', 'pred'), ('preseason', 'pre_pg'), ('season average', 'season_avg')]:
                    pick_a = a[col].values >= b[col].values
                    right = np.where(pick_a, a.half.values > b.half.values, b.half.values > a.half.values)
                    gap = np.abs(a.pred.values - b.pred.values)  # binned by the calibrated gap the page shows
                    out.append(pd.DataFrame({'position': pos, 'model': name, 'gap': gap[keep], 'right': right[keep]}))
    df = pd.concat(out, ignore_index=True)
    overall = df.groupby(['model']).right.mean().round(3)
    df['bucket'] = pd.cut(df.gap, [g[0] for g in GAPS] + [99], right=False, labels=[f'{a}-{b}' for a, b in GAPS])
    by_gap = df[df.model == 'calibrated'].groupby(['position', 'bucket'], observed=True).right.agg(['mean', 'size']).round(3)
    print('overall pick accuracy by model:\n', overall.to_string())
    print(by_gap.to_string())
    table = {pos: {str(b): round(float(r['mean']), 3) for b, r in by_gap.loc[pos].iterrows()} for pos in c.POSITIONS}
    (c.OUT / 'start_sit_accuracy.json').write_text(json.dumps({'overall': overall.to_dict(), 'by_gap': table}, indent=2))
    site = json.loads((Path(__file__).parents[2] / 'site/yahoo/ros-model.json').read_text())
    site['start_sit'] = {'gaps': [list(g) for g in GAPS], 'accuracy': table}
    (Path(__file__).parents[2] / 'site/yahoo/ros-model.json').write_text(json.dumps(site, separators=(',', ':')))


if __name__ == '__main__':
    main()
