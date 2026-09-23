"""Component model: predict each stat line, then score it. Plus p90 ceiling via quantile loss."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import build_features as BF, backtest as B, exp as E, exp4
X = exp4.X
COMP = ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receptions",
        "receiving_yards", "receiving_tds"]
ss = BF.season_stats()
ss["fum"] = ss.rushing_fumbles_lost + ss.receiving_fumbles_lost + ss.sack_fumbles_lost
ss["other_std"] = ss.fantasy_points - (ss.passing_yards * .04 + ss.passing_tds * 4 - ss.passing_interceptions * 2 +
                                       ss.rushing_yards * .1 + ss.rushing_tds * 6 + ss.receiving_yards * .1 + ss.receiving_tds * 6)
tg = ss.rename(columns={"season": "forecast_year"})[["forecast_year", "player_id"] + COMP + ["other_std"]]
X = X.merge(tg.rename(columns={c: "yc_" + c for c in COMP + ["other_std"]}), on=["forecast_year", "player_id"], how="left")
for c in COMP + ["other_std"]:
    X["yc_" + c] = X["yc_" + c].fillna(0)
feats = exp4.BASE + exp4.G["qb_"] + exp4.G["coach_"] + exp4.G["vegas_"]
kw = dict(min_samples_leaf=50, l2_regularization=10)
def score_line(p):
    std = (p.passing_yards * .04 + p.passing_tds * 4 - p.passing_interceptions * 2 + p.rushing_yards * .1 +
           p.rushing_tds * 6 + p.receiving_yards * .1 + p.receiving_tds * 6 + p.other_std)
    return std, std + 0.5 * p.receptions, std + p.receptions
if __name__ == "__main__":
    comp_out, direct, p90 = [], [], []
    for Y in E.YEARS + [2025]:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        p = pd.DataFrame(index=te.index)
        for c in COMP + ["other_std"]:
            p[c] = np.maximum(B.hgb(**kw).fit(tr[feats], tr["yc_" + c]).predict(te[feats]), 0) if c != "other_std" else \
                   B.hgb(**kw).fit(tr[feats], tr["yc_" + c]).predict(te[feats])
        comp_out.append(p)
        direct.append(pd.Series(np.maximum(B.hgb(**kw).fit(tr[feats], tr.y_half).predict(te[feats]), 0), index=te.index))
        p90.append(pd.Series(B.hgb(loss="quantile", quantile=0.9, **kw).fit(tr[feats], tr.y_half).predict(te[feats]), index=te.index))
        print("done", Y, flush=True)
    C = pd.concat(comp_out); D = pd.concat(direct); Q = pd.concat(p90)
    s, h, r = score_line(C)
    pd.to_pickle({"comp": C, "direct_half": D, "p90_half": Q}, "work/components_preds.pkl")
    yrs = E.YEARS
    idx = X[X.forecast_year.isin(yrs)].index
    B.X = X
    for name, pr in [("direct half", D), ("components half", h), ("avg(direct, comp)", (D + h) / 2)]:
        exp4.score(name, pr.loc[idx])
    # ceiling calibration
    d = X.loc[Q.index]
    rel = d.y_half.gt(50) | Q.gt(80)
    print("p90 coverage (actual <= p90): all %.3f  relevant %.3f" % ((d.y_half <= Q).mean(), (d.y_half <= Q)[rel].mean()))
