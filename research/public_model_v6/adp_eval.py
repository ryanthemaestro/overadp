"""Model vs Fantasy Football Calculator ADP (end-of-preseason snapshots, 12-team), 2019-2025.

ADP data: Fantasy Football Calculator ADP REST API (free for personal & commercial use, attribution requested).
Comparison pool = players with ADP in that season/format (QB/RB/WR/TE); both rankings choose from the same pool.
ADP-implied points: per position/format, regress actual points on log(ADP) fitted leave-one-season-out
(slightly favourable to ADP).
"""
import re
import numpy as np
import pandas as pd

POS = ["QB", "RB", "WR", "TE"]
REPL = {"QB": 12, "RB": 30, "WR": 36, "TE": 12}
ALIAS = {"gabrieldavis": "gabedavis", "williamfullerv": "willfuller", "williamfuller": "willfuller",
         "robbyanderson": "robbieanderson", "chigoziemokonkwo": "chigokonkwo", "hollywoodbrown": "marquisebrown"}


def norm(s):
    s = str(s).lower().replace("'", "")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return ALIAS.get(re.sub(r"[^a-z]", "", s), re.sub(r"[^a-z]", "", s))


def rho(a, b):
    return pd.Series(np.asarray(a)).rank().corr(pd.Series(np.asarray(b)).rank())


def load():
    W = pd.read_csv("out/walkforward_predictions_2019_2025.csv").rename(columns={"forecast_year": "season"})
    A = pd.read_csv("adp/ffc_adp_2019_2025.csv")
    A["key"], W["key"] = A.name.map(norm), W.name.map(norm)
    M = A.merge(W.drop(columns=["name"]), on=["season", "key", "position"], how="inner")
    M["actual"] = np.select([M.fmt == "std", M.fmt == "half"], [M.y_std, M.y_half], M.y_ppr)
    M["model"] = np.select([M.fmt == "std", M.fmt == "half"], [M.pred_std, M.pred_half], M.pred_ppr)
    M["logadp"] = np.log(M.adp)
    M["adp_pts"] = np.nan
    for (fmt, p), g in M.groupby(["fmt", "position"]):
        for Y in g.season.unique():
            tr = g[g.season != Y]
            b = np.polyfit(tr.logadp, tr.actual, 1)
            idx = g[g.season == Y].index
            M.loc[idx, "adp_pts"] = np.polyval(b, M.loc[idx, "logadp"])
    M["blend"] = (M.model + M.adp_pts) / 2
    return M


def draft_value(d, col, picks=120):
    av, pv = pd.Series(0.0, index=d.index), pd.Series(0.0, index=d.index)
    for p in POS:
        e = d[d.position == p]
        av[e.index] = e.actual - e.actual.nlargest(REPL[p]).iloc[-1]
        pv[e.index] = e[col] - e[col].nlargest(REPL[p]).iloc[-1]
    picks = min(picks, len(d))
    return av[pv.nlargest(picks).index].clip(lower=-50).sum() / av.nlargest(picks).clip(lower=-50).sum()


def evaluate(M):
    rows = []
    for (fmt, Y), d in M.groupby(["fmt", "season"]):
        for name, col in [("ADP", "adp_pts"), ("Model", "model"), ("Blend 50/50", "blend")]:
            r = dict(fmt=fmt, season=Y, ranker=name, draft_value=draft_value(d, col))
            for p in POS:
                e = d[d.position == p]
                r[f"rho_{p}"] = rho(e[col], e.actual)
                r[f"hit12_{p}"] = len(set(e.actual.nlargest(12).index) & set(e[col].nlargest(12).index))
            r["mae"] = np.mean(np.abs(d[col] - d.actual))
            rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    M = load()
    R = evaluate(M)
    R["rho_avg"] = R[[f"rho_{p}" for p in POS]].mean(axis=1)
    R["hit12_avg"] = R[[f"hit12_{p}" for p in POS]].mean(axis=1)
    cols = ["mae", "rho_avg", "rho_QB", "rho_RB", "rho_WR", "rho_TE", "hit12_avg", "draft_value"]
    print(R.groupby(["fmt", "ranker"])[cols].mean().round(3).to_string())
    piv = R.pivot_table(index=["fmt", "season"], columns="ranker", values=["rho_avg", "draft_value", "mae"])
    print("\nseasons where model beats ADP (of 7):")
    for m in ["rho_avg", "draft_value"]:
        print(m, (piv[(m, "Model")] > piv[(m, "ADP")]).groupby("fmt").sum().to_dict())
    print("mae", (piv[("mae", "Model")] < piv[("mae", "ADP")]).groupby("fmt").sum().to_dict())
    print("\nhalf-PPR by season:")
    print(piv.loc["half"].round(3).to_string())
    print("\nmatched rows:", len(M))
    R.to_csv("out/adp_comparison_by_season.csv", index=False)
    R.groupby(["fmt", "ranker"])[cols].mean().round(3).to_csv("out/adp_comparison_summary.csv")
