import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import backtest as B, exp as E
X, FULL = B.X, B.FULL
AV = [c for c in FULL if c.startswith("av_")]
BASE = [c for c in FULL if c not in AV]
def elite(pr):
    d = X.loc[pr.index]; sl = np.where(d.forecast_year >= 2022, 17, 16)
    m = (sl - d.l1_games >= 6) & (d.car_best_ppr_pg >= 20) & (d.position != "QB")
    return (d.y_half[m] - pr[m]).mean(), m.sum()
kw = dict(min_samples_leaf=50, l2_regularization=10)
res = {}
for name, feats in [("v2 (no availability)", BASE), ("v3 (+availability)", FULL)]:
    pr = E.run(feats, **kw); res[name] = pr
    E.score(name, pr); print("   elite-injured mean err: %.1f (n=%d)" % elite(pr))
pr = E.run(FULL, min_samples_leaf=20, l2_regularization=10); E.score("v3 msl20", pr); print("   elite-injured: %.1f (n=%d)" % elite(pr))
pd.to_pickle(res, "work/av_preds.pkl")
