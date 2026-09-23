"""Replace p10/p90 in out/projections_2026.csv with empirical 80% ranges from 2019-2024 walk-forward residuals
(by position x projection bucket). Run after final.py. 2025 holdout coverage: 77.7%."""
import numpy as np
import pandas as pd

W = pd.read_pickle("work/walkforward.pkl")
BINS = [30, 80, 130, 180, 1000]
v = W[(W.forecast_year < 2025) & (W.pred_half >= 30)].copy()
v["b"] = pd.cut(v.pred_half, BINS, labels=False)
q = (v.y_half - v.pred_half).groupby([v.position, v.b]).quantile([.1, .9]).unstack()
P = pd.read_csv("out/projections_2026.csv")
P["b"] = pd.cut(P.proj_half.clip(lower=30.01), BINS, labels=False)
P = P.join(q, on=["position", "b"])
P["p10_half"] = np.maximum(P.proj_half + P[0.1], 0).round(1)
P["p90_half"] = (P.proj_half + P[0.9]).round(1)
P.loc[P.proj_half < 30, ["p10_half", "p90_half"]] = np.nan
P.drop(columns=["b", 0.1, 0.9]).to_csv("out/projections_2026.csv", index=False)
