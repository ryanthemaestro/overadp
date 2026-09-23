import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import exp4, backtest as B, exp as E, adp_eval as AE
X = exp4.X; P = pd.read_pickle("work/exp4_preds.pkl")
A = pd.read_csv("adp/ffc_adp_2019_2025.csv"); A = A[A.fmt == "half"]
names = pd.read_csv("data/players.csv.gz", low_memory=False).set_index("gsis_id").display_name
X["key"] = X.player_id.map(names).map(AE.norm); A["key"] = A.name.map(AE.norm)
def qb_pool_rho(pr, label):
    d = X.loc[pr.index].assign(pred=pr)
    m = d.merge(A[["season", "key", "position", "adp"]], left_on=["forecast_year", "key", "position"], right_on=["season", "key", "position"])
    m = m[m.position == "QB"]
    r = m.groupby("forecast_year").apply(lambda e: pd.Series({"model": AE.rho(e.pred, e.y_half), "adp": AE.rho(-e.adp, e.y_half), "n": len(e)}))
    print(f"{label:22s} model={r.model.mean():.3f} adp={r.adp.mean():.3f} n/yr={r.n.mean():.0f}")
for k in ["base", "qb_", "comm", "ngs"]: qb_pool_rho(P[k], k)
# QB-only model
kw = dict(min_samples_leaf=20, l2_regularization=10)
feats = exp4.BASE + exp4.G["qb_"] + exp4.G["coach_"] + exp4.G["vegas_"]
out = []
for Y in E.YEARS:
    tr, te = X[(X.forecast_year < Y) & (X.position == "QB")], X[(X.forecast_year == Y) & (X.position == "QB")]
    out.append(pd.Series(B.hgb(**kw).fit(tr[feats], tr.y_half).predict(te[feats]), index=te.index))
qb_pool_rho(pd.concat(out), "QB-only model")
