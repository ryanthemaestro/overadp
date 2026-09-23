"""Final model: pooled HGB (5-seed bag) averaged with a games x points-per-game two-stage model.

Outputs
  work/walkforward.pkl  - out-of-sample predictions 2019-2025 (each year trained on earlier years only)
  out/projections_2026.csv - 2026 preseason projections (std / half / ppr + p10/p90 for half)
"""
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
import backtest as B

warnings.filterwarnings("ignore")
X, FULL = B.X, B.FULL
KW = dict(min_samples_leaf=50, l2_regularization=10)
FMTS = ["std", "half", "ppr"]
OUT = Path("out"); OUT.mkdir(exist_ok=True)


def ensemble(tr, te, fmt):
    y = tr[f"y_{fmt}"]
    bag = np.mean([B.hgb(random_state=s, **KW).fit(tr[FULL], y).predict(te[FULL]) for s in range(5)], axis=0)
    g = B.hgb(**KW).fit(tr[FULL], tr.y_games).predict(te[FULL])
    pl = tr[tr.y_games >= 1]
    ppg = B.hgb(**KW).fit(pl[FULL], pl[f"y_{fmt}"] / pl.y_games, sample_weight=pl.y_games).predict(te[FULL])
    two = np.clip(g, 0, 17) * np.maximum(ppg, 0)
    return np.maximum((bag + two) / 2, 0)


def quantiles(tr, te, fmt="half"):
    q = {}
    for a in (0.1, 0.9):
        m = B.hgb(loss="quantile", quantile=a, **KW).fit(tr[FULL], tr[f"y_{fmt}"])
        q[a] = np.maximum(m.predict(te[FULL]), 0)
    return q


def walkforward(years=range(2019, 2026)):
    parts = []
    for Y in years:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        d = te[["forecast_year", "player_id", "position", "team", "is_rookie", "l1_games"] +
               [f"y_{f}" for f in FMTS] + [f"l1_{B.FMT[f]}" for f in FMTS]].copy()
        for f in FMTS:
            d[f"pred_{f}"] = ensemble(tr, te, f)
        q = quantiles(tr, te)
        d["p10_half"], d["p90_half"] = q[0.1], q[0.9]
        # comparator: same learner on the TabPFN-screen feature set
        d["screen_hgb_std"] = np.maximum(B.hgb(**KW).fit(tr[B.SCREEN], tr.y_std).predict(te[B.SCREEN]), 0)
        parts.append(d)
        print("done", Y, flush=True)
    return pd.concat(parts)


def project(Y=2026):
    tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
    players = pd.read_csv("data/players.csv.gz", low_memory=False).set_index("gsis_id").display_name
    d = te[["player_id", "position", "team", "status", "age", "exp", "dc_rank", "room_order",
            "l1_fantasy_points_half"]].copy()
    d.insert(1, "name", d.player_id.map(players))
    for f in FMTS:
        d[f"proj_{f}"] = ensemble(tr, te, f)
    q = quantiles(tr, te)
    d["p10_half"], d["p90_half"] = q[0.1], q[0.9]
    d["pos_rank_half"] = d.groupby("position").proj_half.rank(ascending=False, method="first").astype(int)
    d = d.sort_values("proj_half", ascending=False)
    return d.round(1)


if __name__ == "__main__":
    wf = walkforward()
    wf.to_pickle("work/walkforward.pkl")
    pr = project()
    pr.to_csv(OUT / "projections_2026.csv", index=False)
    print(pr.head(30).to_string())
