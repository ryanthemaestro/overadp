"""Availability / injury feature group (all from seasons < forecast year).

Sources (nflverse, CC BY 4.0): weekly injury reports, weekly rosters (IR = status RES), weekly player stats.
Adds to work/features.pkl (previous version kept as work/features_v2.pkl).
"""
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import build_features as BF

ROOT = Path(__file__).parent
D = ROOT / "data"
SOFT = {"hamstring", "groin", "calf", "quadricep", "quad", "thigh", "hip flexor", "pectoral", "oblique", "abdomen"}
CATS = {"knee": {"knee", "acl", "mcl", "meniscus", "patella"}, "achilles": {"achilles"}, "soft": SOFT,
        "ankle_foot": {"ankle", "foot", "toe", "heel", "high ankle", "plantar fascia"},
        "concussion": {"concussion", "head"}, "upper": {"shoulder", "elbow", "wrist", "hand", "thumb", "finger",
                                                          "clavicle", "collarbone", "ribs", "chest", "back", "neck"}}


def season_len(y):
    return 16 if y <= 2020 else 17


def injury_season(y):
    d = pd.read_csv(D / f"injuries_{y}.csv", low_memory=False)
    d = d[(d.game_type == "REG") & d.gsis_id.notna()].copy()
    inj = d.report_primary_injury.fillna("").str.lower().str.replace(r"^(left|right) ", "", regex=True).str.strip()
    out = d.report_status.isin(["Out", "Doubtful"])
    d["out"] = out.astype(int)
    d["q"] = d.report_status.eq("Questionable").astype(int)
    for k, words in CATS.items():
        d[f"inj_{k}"] = (out & inj.isin(words)).astype(int)
    g = d.groupby("gsis_id")
    a = g[["out", "q"] + [f"inj_{k}" for k in CATS]].sum().rename(columns={"out": "inj_out_wks", "q": "inj_q_wks"})
    a["inj_last_out_week"] = d[out].groupby("gsis_id").week.max()
    a["season"] = y
    return a.rename_axis("player_id").reset_index()


def ir_season(y):
    r = BF.f(f"rw_{y}.csv") if y < 2026 else None
    r = r[(r.game_type == "REG")] if "game_type" in r else r
    last = r.week.max()
    res = r[r.status.isin(["RES", "PUP", "NON"])]
    a = res.groupby("gsis_id").week.nunique().rename("ir_wks").to_frame()
    a["ended_on_ir"] = res[res.week == last].groupby("gsis_id").size().gt(0).astype(int)
    a["season"] = y
    return a.rename_axis("player_id").reset_index()


def per_season():
    ss = BF.season_stats()[["player_id", "season", "games", "fantasy_points", "fantasy_points_half",
                            "fantasy_points_ppr"]]
    inj = pd.concat([injury_season(y) for y in range(2012, 2026)])
    ir = pd.concat([ir_season(y) for y in range(2012, 2026)])
    s = ss.merge(inj, on=["player_id", "season"], how="outer").merge(ir, on=["player_id", "season"], how="outer")
    s["games"] = s.games.fillna(0)
    s["missed"] = s.season.map(season_len) - s.games
    return s


def build(X):
    s = per_season()
    rows = []
    for Y in sorted(X.forecast_year.unique()):
        ids = X.loc[X.forecast_year == Y, "player_id"]
        h = s[(s.season < Y) & (s.season >= Y - 3) & s.player_id.isin(ids)].copy()
        h["lag"] = Y - h.season
        f = pd.DataFrame(index=pd.Index(ids.unique(), name="player_id"))
        for L in (1, 2):
            e = h[h.lag == L].set_index("player_id")
            for c in ["missed", "inj_out_wks", "inj_q_wks", "ir_wks", "ended_on_ir", "inj_last_out_week",
                      "inj_knee", "inj_soft", "inj_achilles", "inj_ankle_foot", "inj_concussion", "inj_upper"]:
                f[f"av_l{L}_{c}"] = e[c] if L == 1 or c in ("missed", "inj_out_wks", "ir_wks") else np.nan
        f = f.dropna(axis=1, how="all")
        g = h.groupby("player_id")
        f["av_3y_out_wks"] = g.inj_out_wks.sum()
        f["av_3y_ir_wks"] = g.ir_wks.sum()
        f["av_3y_soft"] = g.inj_soft.sum()
        f["av_3y_knee"] = g.inj_knee.sum()
        f["av_3y_seasons_short"] = g.missed.apply(lambda m: (m >= 5).sum())
        # availability rate over seasons with any NFL footprint (stats, report or roster reserve)
        f["av_3y_rate"] = g.games.sum() / g.season.apply(lambda v: sum(season_len(x) for x in v))
        # healthy per-game production: seasons with >= 6 games, weighted by recency and games
        hh = h[h.games >= 6].copy()
        hh["w"] = hh.games * hh.lag.map({1: 5, 2: 3, 3: 2})
        for col, nm in [("fantasy_points", "std"), ("fantasy_points_half", "half"), ("fantasy_points_ppr", "ppr")]:
            hh["pg"] = hh[col] / hh.games
            gg = hh.groupby("player_id")
            f[f"av_healthy_pg_{nm}"] = (hh.pg * hh.w).groupby(hh.player_id).sum() / gg.w.sum()
            f[f"av_peak_pg_{nm}"] = gg.pg.max()
            f[f"av_full_season_{nm}"] = f[f"av_healthy_pg_{nm}"] * 17
        rows.append(f.reset_index().assign(forecast_year=Y))
    A = pd.concat(rows, ignore_index=True)
    X = X.merge(A, on=["forecast_year", "player_id"], how="left")
    X["av_l1_injury_shortened"] = ((X.av_l1_missed >= 5) &
                                   ((X.av_l1_ir_wks.fillna(0) + X.av_l1_inj_out_wks.fillna(0)) >= 3)).astype(int)
    X["av_l1_pg_vs_healthy"] = X.l1_fantasy_points_ppr_pg / X.av_healthy_pg_ppr
    return X


if __name__ == "__main__":
    base = ROOT / "work/features_v2.pkl"
    if not base.exists():
        shutil.copy(ROOT / "work/features.pkl", base)
    X = build(pd.read_pickle(base))
    X.to_pickle(ROOT / "work/features.pkl")
    new = [c for c in X.columns if c.startswith("av_")]
    print(X.shape, len(new))
    print(X.groupby("forecast_year")[["av_l1_missed", "av_l1_inj_out_wks", "av_l1_ir_wks", "av_healthy_pg_ppr"]]
          .apply(lambda d: d.notna().mean()).round(2).to_string())
    names = pd.read_csv(D / "players.csv.gz", low_memory=False).set_index("gsis_id").display_name
    c = X[(X.forecast_year == 2025) & (X.player_id == "00-0033280")]
    print(names.get("00-0033280"), c[[x for x in new if "l1" in x or "healthy_pg_ppr" in x or "3y" in x]].T)
