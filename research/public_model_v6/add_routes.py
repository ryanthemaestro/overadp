"""v5 (college) -> v6: drop CFBD pre-draft rank columns, add route-participation lags. Writes work/features.pkl."""
import pandas as pd
X = pd.read_pickle("work/features_v5.pkl")
X = X.drop(columns=[c for c in X.columns if "predraft" in c])
R = pd.read_pickle("work/routes_player.pkl")
for L in (1, 2):
    r = R.assign(forecast_year=R.season + L).drop(columns="season")
    cols = ["rt_routes", "rt_share", "rt_tprr", "rt_yprr"] if L == 1 else ["rt_share", "rt_tprr", "rt_yprr"]
    X = X.merge(r[["forecast_year", "player_id"] + cols].rename(columns={c: f"l{L}_{c}" for c in cols}),
                on=["forecast_year", "player_id"], how="left")
X["l1_rt_routes_pg"] = X.l1_rt_routes / X.l1_games.where(X.l1_games > 0)
X.to_pickle("work/features.pkl")
print("v6 feature table:", X.shape)
