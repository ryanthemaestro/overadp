import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import backtest as B, exp as E
from exp_av import elite, AV, BASE
X, FULL = B.X, B.FULL
kw = dict(min_samples_leaf=50, l2_regularization=10)
def two(feats):
    out=[]
    for Y in E.YEARS:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        g = B.hgb(**kw).fit(tr[feats], tr.y_games).predict(te[feats])
        pl = tr[tr.y_games >= 1]
        p = B.hgb(**kw).fit(pl[feats], pl.y_half/pl.y_games, sample_weight=pl.y_games).predict(te[feats])
        out.append(pd.Series(np.clip(g,0,17)*np.maximum(p,0), index=te.index))
    return pd.concat(out)
for name, f in [("two-stage v2", BASE), ("two-stage v3", FULL)]:
    pr = two(f); E.score(name, pr); print("   elite-injured: %.1f (n=%d)" % elite(pr))
# significance of the original pattern
W = pd.read_pickle("work/walkforward.pkl"); d = W.merge(X[["forecast_year","player_id","car_best_ppr_pg"]], on=["forecast_year","player_id"])
sl = np.where(d.forecast_year>=2022,17,16); m=(sl-d.l1_games>=6)&(d.car_best_ppr_pg>=20)&(d.position!="QB")
e=(d.y_half-d.pred_half)[m]; print("final model elite-injured: mean %.1f, sd %.1f, n %d, se %.1f"%(e.mean(),e.std(),len(e),e.std()/np.sqrt(len(e))))
