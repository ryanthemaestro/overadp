import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import backtest as B, exp as E, adp_eval as AE
X5 = pd.read_pickle("work/features_v5.pkl"); B.X = X5; E.X = X5; X = X5
BASE = list(B.FULL); COL = [c for c in X.columns if c.startswith("col_")]
NOPD = [c for c in COL if "predraft" not in c]
kw = dict(min_samples_leaf=50, l2_regularization=10)
A = pd.read_csv("adp/ffc_adp_2019_2025.csv"); A = A[A.fmt == "half"]
names = pd.read_csv("data/players.csv.gz", low_memory=False).set_index("gsis_id").display_name
X["key"] = X.player_id.map(names).map(AE.norm); A["key"] = A.name.map(AE.norm)
def rookie_stats(pr, yrs):
    d = X.loc[pr.index].assign(pred=pr); r = d[(d.is_rookie == 1) & (d.draft_pick <= 150) & d.forecast_year.isin(yrs)]
    rho = np.mean([AE.rho(e.pred, e.y_half) for _, e in r.groupby(["forecast_year", "position"]) if len(e) > 4])
    m = d[d.forecast_year.isin(yrs)].merge(A[["season", "key", "position", "adp"]], left_on=["forecast_year", "key", "position"],
                                           right_on=["season", "key", "position"])
    m = m[m.is_rookie == 1]
    mr = np.mean([AE.rho(e.pred, e.y_half) for _, e in m.groupby("forecast_year")])
    ar = np.mean([AE.rho(-e.adp, e.y_half) for _, e in m.groupby("forecast_year")])
    return np.mean(np.abs(r.pred - r.y_half)), rho, mr, ar
def run(feats, years):
    out = []
    for Y in years:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        out.append(pd.Series(np.maximum(B.hgb(**kw).fit(tr[feats], tr.y_half).predict(te[feats]), 0), index=te.index))
    return pd.concat(out)
P = {}
for name, f in [("base v2", BASE), ("+college (no predraft rank)", BASE + NOPD), ("+college +predraft rank", BASE + COL)]:
    pr = run(f, E.YEARS + [2025]); P[name] = pr
    for lab, yrs in [("2019-24", E.YEARS), ("2025", [2025])]:
        m = B.metrics(pr.loc[X[X.forecast_year.isin(yrs)].index], "half", yrs)[["mae_rel", "rho_rel", "capture"]].mean()
        mae_r, rho_r, adp_model, adp_adp = rookie_stats(pr, yrs)
        print(f"{name:28s} {lab}: mae_rel={m.mae_rel:.2f} rho={m.rho_rel:.3f} capture={m.capture:.3f} | rookies(pick<=150): mae={mae_r:.1f} rho={rho_r:.3f} | drafted-rookie rho model={adp_model:.3f} vs ADP={adp_adp:.3f}", flush=True)
pd.to_pickle(P, "work/col_preds.pkl")
