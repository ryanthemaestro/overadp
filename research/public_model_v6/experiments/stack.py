"""ADP-informed model: learn how to combine the stats model with ADP, walk-forward.

For each forecast year Y (2021-2025), fit on ADP-pool seasons 2019..Y-1, predict Y.
Inputs: stats-model projection, log(ADP), ADP stdev, times drafted, + a few context fields.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.ensemble import HistGradientBoostingRegressor
import adp_eval as AE

M = AE.load()
X = pd.read_pickle("work/features.pkl")[["forecast_year", "player_id", "age", "dc_rank", "changed_team",
                                          "l1_fantasy_points_ppr_pg", "car_best_ppr_pg"]]
M = M.merge(X.rename(columns={"forecast_year": "season"}), on=["season", "player_id"], how="left")
M["log_adp"] = np.log(M.adp)
M["adp_cv"] = M.adp_stdev / M.adp
M["pos_rank_adp"] = M.groupby(["fmt", "season", "position"]).adp.rank()
M["pos_rank_model"] = M.groupby(["fmt", "season", "position"]).model.rank(ascending=False)
M["rank_gap"] = M.pos_rank_adp - M.pos_rank_model   # >0: model likes him more than the market
M["l1_short"] = (M.l1_games.fillna(0) <= 10).astype(int)
POS = ["QB", "RB", "WR", "TE"]
LIN = ["model", "log_adp"]
GB = ["model", "log_adp", "adp_cv", "rank_gap", "is_rookie", "age", "dc_rank", "l1_short", "changed_team",
      "car_best_ppr_pg", "pos_code"]
M["pos_code"] = M.position.map({p: i for i, p in enumerate(POS)})

out = []
for fmt in ["std", "half", "ppr"]:
    F = M[M.fmt == fmt]
    for Y in range(2021, 2026):
        tr, te = F[F.season < Y], F[F.season == Y].copy()
        te["stack_lin"] = np.nan
        for p in POS:
            a, b = tr[tr.position == p], te[te.position == p]
            m = RidgeCV(alphas=np.logspace(-2, 3, 12)).fit(a[LIN], a.actual)
            te.loc[b.index, "stack_lin"] = m.predict(b[LIN])
        g = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=30,
                                          l2_regularization=10, random_state=0).fit(tr[GB], tr.actual)
        te["stack_gb"] = g.predict(te[GB])
        te["stack"] = (te.stack_lin + te.stack_gb) / 2
        out.append(te)
S = pd.concat(out)
S["stack_lin"] = S.stack_lin.clip(lower=0); S["stack"] = S["stack"].clip(lower=0)

rows = []
for (fmt, Y), d in S.groupby(["fmt", "season"]):
    for name, col in [("ADP", "adp_pts"), ("Model", "model"), ("Blend 50/50", "blend"),
                      ("Stack linear", "stack_lin"), ("Stack GB", "stack_gb"), ("Stack avg", "stack")]:
        r = dict(fmt=fmt, season=Y, ranker=name, draft_value=AE.draft_value(d, col), mae=np.mean(np.abs(d[col] - d.actual)))
        for p in POS:
            e = d[d.position == p]
            r[f"rho_{p}"] = AE.rho(e[col], e.actual)
        r["rho_avg"] = np.mean([r[f"rho_{p}"] for p in POS])
        rows.append(r)
R = pd.DataFrame(rows)
cols = ["mae", "rho_avg", "rho_QB", "rho_RB", "rho_WR", "rho_TE", "draft_value"]
print("walk-forward 2021-2025 (stack trained only on earlier ADP seasons)")
print(R.groupby(["fmt", "ranker"])[cols].mean().round(3).to_string())
piv = R.pivot_table(index=["fmt", "season"], columns="ranker", values=["rho_avg", "mae", "draft_value"])
for m in ["rho_avg", "draft_value"]:
    print(m, "Stack avg beats ADP in", (piv[(m, "Stack avg")] > piv[(m, "ADP")]).groupby("fmt").sum().to_dict(), "of 5")
print("mae Stack avg beats ADP in", (piv[("mae", "Stack avg")] < piv[("mae", "ADP")]).groupby("fmt").sum().to_dict(), "of 5")
R.to_csv("out/stack_comparison_by_season.csv", index=False)
S.to_pickle("work/stack_preds.pkl")
