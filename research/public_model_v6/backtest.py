"""Walk-forward backtest: for each forecast year Y, train on forecast years < Y only."""
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
X = pd.read_pickle("work/features.pkl")
POS = ["QB", "RB", "WR", "TE"]
FMT = {"std": "fantasy_points", "half": "fantasy_points_half", "ppr": "fantasy_points_ppr"}
TOPN = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
NONFEAT = {"player_id", "team", "position", "status", "forecast_year", "bio_pos", "y_std", "y_ppr", "y_half",
           "y_games", "y_rec", "draft_year", "draft_round", "draft_pick", "rookie_season"}
FULL = [c for c in X.columns if c not in NONFEAT and X[c].dtype != object]
SCREEN = [f"l{L}_{s}" for L in (1, 2) for s in ("games", "fantasy_points")] + [
    f"l1_{s}" for s in ("attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries",
                        "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards",
                        "receiving_tds")]


def hgb(loss="squared_error", **kw):
    p = dict(max_iter=400, learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1.0,
             max_features=0.5, random_state=0)
    p.update(kw)
    return HistGradientBoostingRegressor(loss=loss, **p)


def fit_predict(kind, tr, te, fmt, feats):
    y = tr[f"y_{fmt}"].to_numpy(float)
    if kind == "prior":
        return te[f"l1_{FMT[fmt]}"].fillna(0).to_numpy()
    if kind == "marcel":
        pg = te[f"marcel_ppr_pg" if fmt == "ppr" else "marcel_pg"].fillna(0)
        if fmt == "half":
            pg = (te.marcel_pg.fillna(0) + te.marcel_ppr_pg.fillna(0)) / 2
        g = te[["l1_games", "l2_games", "l3_games"]].fillna(0).mean(axis=1).clip(upper=16)
        return (pg * (0.5 * g + 0.5 * 14)).to_numpy()
    if kind == "ridge":
        m = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                          RidgeCV(alphas=np.logspace(-1, 4, 20)))
        m.fit(tr[feats], y)
        return m.predict(te[feats])
    if kind.startswith("hgb"):
        loss = "poisson" if "pois" in kind else "squared_error"
        m = hgb(loss)
        m.fit(tr[feats], np.maximum(y, 0) if loss == "poisson" else y)
        return m.predict(te[feats])
    raise ValueError(kind)


def run_model(kind, feats, fmt, years, per_position=True):
    out = []
    for Y in years:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        if per_position:
            for p in POS:
                a, b = tr[tr.position == p], te[te.position == p]
                out.append(pd.DataFrame({"idx": b.index, "pred": fit_predict(kind, a, b, fmt, feats)}))
        else:
            out.append(pd.DataFrame({"idx": te.index, "pred": fit_predict(kind, tr, te, fmt, feats)}))
    o = pd.concat(out).set_index("idx").pred
    return np.maximum(o, 0)


def metrics(pred, fmt, years):
    rows = []
    for Y in years:
        for p in POS:
            d = X[(X.forecast_year == Y) & (X.position == p)]
            a, pr = d[f"y_{fmt}"], pred.loc[d.index]
            base = d[f"l1_{FMT[fmt]}"].fillna(0)
            n = TOPN[p]
            rel = set(a.nlargest(n).index) | set(base.nlargest(n).index)
            R = list(rel)
            top_a12, top_p12 = set(a.nlargest(12).index), set(pr.nlargest(12).index)
            top_an, top_pn = a.nlargest(n), pr.nlargest(n)
            rows.append(dict(year=Y, pos=p, mae_all=np.mean(np.abs(a - pr)), mae_rel=np.mean(np.abs(a[R] - pr[R])),
                             rho_rel=spearmanr(a[R], pr[R]).statistic, hit12=len(top_a12 & top_p12),
                             hitN=len(set(top_an.index) & set(top_pn.index)),
                             capture=a[top_pn.index].sum() / top_an.sum()))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    years = list(range(2019, 2025))
    configs = [("prior", SCREEN, True), ("marcel", SCREEN, True), ("hgb", SCREEN, True),
               ("ridge", FULL, True), ("hgb", FULL, True), ("hgb_pois", FULL, True), ("hgb", FULL, False),
               ("hgb_pois", FULL, False)]
    res, preds = [], {}
    for fmt in ["half"]:
        for kind, feats, pp in configs:
            name = f"{kind}|{'screen' if feats is SCREEN else 'full'}|{'pos' if pp else 'pooled'}"
            pr = run_model(kind, feats, fmt, years, pp)
            preds[(name, fmt)] = pr
            m = metrics(pr, fmt, years).assign(model=name, fmt=fmt)
            res.append(m)
            s = m[["mae_all", "mae_rel", "rho_rel", "hit12", "hitN", "capture"]].mean()
            print(f"{name:28s} {fmt}", " ".join(f"{k}={v:.3f}" for k, v in s.items()), flush=True)
    R = pd.concat(res)
    R.to_pickle("work/bt_v1.pkl")
    pd.to_pickle(preds, "work/bt_v1_preds.pkl")
    print(R.groupby(["model", "pos"])[["mae_rel", "rho_rel", "capture"]].mean().unstack().round(3).to_string())
