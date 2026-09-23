import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import backtest as B, exp as E
X = pd.read_pickle("work/features.pkl")  # v5 (college), current champion
R = pd.read_pickle("work/routes_player.pkl")
for L in (1, 2):
    r = R.assign(forecast_year=R.season + L).drop(columns="season")
    cols = ["rt_routes", "rt_share", "rt_tprr", "rt_yprr"] if L == 1 else ["rt_share", "rt_tprr", "rt_yprr"]
    X = X.merge(r[["forecast_year", "player_id"] + cols].rename(columns={c: f"l{L}_{c}" for c in cols}),
                on=["forecast_year", "player_id"], how="left")
X["l1_rt_routes_pg"] = X.l1_rt_routes / X.l1_games.where(X.l1_games > 0)
B.X = X; E.X = X
BASE = list(B.FULL); RT = [c for c in X.columns if "_rt_" in c]
kw = dict(min_samples_leaf=50, l2_regularization=10)
def run(feats, years):
    out = []
    for Y in years:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        out.append(pd.Series(np.maximum(B.hgb(**kw).fit(tr[feats], tr.y_half).predict(te[feats]), 0), index=te.index))
    return pd.concat(out)
for name, f in [("v5 (current)", BASE), ("v5 + route data", BASE + RT)]:
    pr = run(f, E.YEARS + [2025])
    for lab, yrs in [("2019-24", E.YEARS), ("2025", [2025])]:
        m = B.metrics(pr.loc[X[X.forecast_year.isin(yrs)].index], "half", yrs)
        s = m[["mae_rel", "rho_rel", "capture"]].mean(); wr = m[m.pos.isin(["WR", "TE", "RB"])][["mae_rel", "rho_rel"]].mean()
        print(f"{name:18s} {lab}: mae_rel={s.mae_rel:.2f} rho={s.rho_rel:.3f} capture={s.capture:.3f} | RB/WR/TE mae={wr.mae_rel:.2f} rho={wr.rho_rel:.3f}", flush=True)
