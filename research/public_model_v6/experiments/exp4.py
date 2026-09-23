import warnings, sys; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import backtest as B, exp as E
X4 = pd.read_pickle("work/features_v4.pkl")
B.X = X4; E.X = X4; X = X4
BASE = [c for c in B.FULL]  # v2 feature list
G = {p: [c for c in X.columns if c.startswith(p)] for p in ["qb_", "coach_", "vegas_", "ngs_"]}
kw = dict(min_samples_leaf=50, l2_regularization=10)
def score(name, pr):
    m = B.metrics(pr, "half", E.YEARS)
    s = m[["mae_rel", "rho_rel", "hit12", "capture"]].mean(); q = m[m.pos == "QB"][["mae_rel", "rho_rel"]].mean()
    print(f"{name:26s} " + " ".join(f"{k}={v:.3f}" for k, v in s.items()) + f" | QB mae={q.mae_rel:.1f} rho={q.rho_rel:.3f}", flush=True)
    return pr
if __name__ == "__main__":
    P = {}
    P["base"] = score("base (v2)", E.run(BASE, **kw))
    for g in ["qb_", "coach_", "vegas_"]:
        P[g] = score("+" + g, E.run(BASE + G[g], **kw))
    comm = BASE + G["qb_"] + G["coach_"] + G["vegas_"]
    P["comm"] = score("+qb+coach+vegas", E.run(comm, **kw))
    P["ngs"] = score("+all +ngs (research)", E.run(comm + G["ngs_"], **kw))
    pd.to_pickle(P, "work/exp4_preds.pkl")
