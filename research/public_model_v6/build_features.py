"""Preseason player-season feature table from public nflverse data.

One row = (forecast_year Y, player). Every feature uses only information available
before week 1 of Y: stats/pbp/snaps from seasons <= Y-1, bio/draft info, the week-1
roster and the pre-week-1 depth chart of Y. Targets are season-Y regular-season
fantasy points (standard, half-PPR, PPR) with non-appearance = 0.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
D = ROOT / "data"
POS = ["QB", "RB", "WR", "TE"]
FIRST_STATS, LAST = 2012, 2026
TEAM_MAP = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "LA", "STL": "LA", "LAR": "LA",
            "SD": "LAC", "OAK": "LV", "JAC": "JAX"}
SEASON_START = {2025: "2025-09-04", 2026: "2026-09-09"}  # depth-chart snapshots must predate kickoff
SUM = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
       "passing_air_yards", "passing_epa", "passing_first_downs", "carries", "rushing_yards", "rushing_tds",
       "rushing_first_downs", "rushing_epa", "receptions", "targets", "receiving_yards", "receiving_tds",
       "receiving_air_yards", "receiving_yards_after_catch", "receiving_first_downs", "receiving_epa",
       "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost", "fantasy_points", "fantasy_points_ppr"]
MEAN = ["target_share", "air_yards_share", "wopr", "passing_cpoe"]


def tm(s):
    return s.replace(TEAM_MAP)


def f(path):
    for cand in (D / path, D / (path + ".gz")):
        if cand.exists():
            return pd.read_csv(cand, low_memory=False)
    raise FileNotFoundError(path)


# ---------------------------------------------------------------- season aggregates
def season_stats():
    out = []
    for y in range(FIRST_STATS, LAST + 1):
        name = "spw_%d.csv.gz" % y if y < 2026 else "stats_player_week_2026.csv.gz"
        w = pd.read_csv(D / name, low_memory=False)
        w = w[(w.season_type == "REG") & w.position.isin(POS)]
        w["team"] = tm(w.team)
        g = w.groupby("player_id")
        a = g[SUM].sum()
        a[MEAN] = g[MEAN].mean()
        a["games"] = g.week.nunique()
        a["team"] = g.team.agg(lambda s: s.iloc[-1])
        a["n_teams"] = g.team.nunique()
        a["position"] = g.position.agg(lambda s: s.mode().iloc[0])
        # consistency / ceiling
        a["ppr_wk_std"] = g.fantasy_points_ppr.std()
        a["ppr_wk_max"] = g.fantasy_points_ppr.max()
        a["ppr_2nd_half"] = w[w.week > 9].groupby("player_id").fantasy_points_ppr.sum()
        a["games_2nd_half"] = w[w.week > 9].groupby("player_id").week.nunique()
        a["season"] = y
        out.append(a.reset_index())
    s = pd.concat(out, ignore_index=True)
    s["fantasy_points_half"] = (s.fantasy_points + s.fantasy_points_ppr) / 2
    return s


def snap_stats(players):
    pfr = players.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
    out = []
    for y in range(2013, 2026):
        s = f(f"snaps_{y}.csv")
        s = s[s.game_type == "REG"]
        s["player_id"] = s.pfr_player_id.map(pfr)
        s = s.dropna(subset=["player_id"])
        g = s.groupby("player_id")
        a = pd.DataFrame({"snap_pct": g.offense_pct.mean(), "off_snaps": g.offense_snaps.sum(),
                          "snap_games": g.offense_snaps.apply(lambda v: (v > 0).sum()),
                          "snap_games50": g.offense_pct.apply(lambda v: (v >= .5).sum()),
                          "snap_pct_last4": s[s.week >= s.week.max() - 3].groupby("player_id").offense_pct.mean()})
        a["season"] = y
        out.append(a.reset_index())
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- preseason context
def week1_roster(y):
    name = f"rw_{y}.csv" if y < 2026 else "roster_weekly_2026.csv.gz"
    r = f(name) if y < 2026 else pd.read_csv(D / name, low_memory=False)
    if "game_type" in r:
        r = r[r.game_type == "REG"]
    r = r[r.week == r.week.min()].copy()
    r["team"] = tm(r.team)
    r = r[r.status.isin(["ACT", "INA", "RES", "PUP", "SUS", "DEV", "NON", "EXE"]) & r.gsis_id.notna()]
    prio = {"ACT": 0, "INA": 1, "RES": 2, "PUP": 3, "SUS": 4, "NON": 5, "EXE": 6, "DEV": 7}
    r["p"] = r.status.map(prio)
    r = r.sort_values("p").drop_duplicates("gsis_id")
    return r[["gsis_id", "team", "position", "status", "years_exp"]].rename(columns={"gsis_id": "player_id"})


def depth_chart(y):
    """Best (lowest) depth rank at the player's offensive skill position before week 1."""
    if y <= 2024:
        d = f(f"dc_{y}.csv")
        d = d[(d.game_type == "REG") & (d.formation == "Offense") & d.position.isin(POS)]
        d = d[d.week == d.week.min()]
        d = d.rename(columns={"depth_team": "rank"})
    else:
        d = f(f"dc_{y}.csv") if y == 2025 else pd.read_csv(D / "depth_charts_2026.csv.gz", low_memory=False)
        d = d[d.pos_abb.isin(POS + ["WR1", "WR2", "WR3"]) | d.pos_abb.str.match(r"^(QB|RB|WR|TE)")]
        d = d[d.dt < SEASON_START[y]]
        d = d[d.dt == d.dt.max()]
        d = d.rename(columns={"pos_rank": "rank"})
    d = d.dropna(subset=["gsis_id"])
    d["rank"] = pd.to_numeric(d["rank"], errors="coerce")
    return d.groupby("gsis_id")["rank"].min().rename("dc_rank").rename_axis("player_id").reset_index()


def depth_chart_end(y):
    """Best depth rank at the final regular-season week of season y (known before y+1)."""
    if y <= 2024:
        d = f(f"dc_{y}.csv")
        d = d[(d.game_type == "REG") & (d.formation == "Offense") & d.position.isin(POS)]
        d = d[d.week == d.week.max()].rename(columns={"depth_team": "rank"})
    else:
        d = f(f"dc_{y}.csv")
        d = d[d.pos_abb.isin(POS)]
        d = d[d.dt < f"{y + 1}-01-06"]
        d = d[d.dt == d.dt.max()].rename(columns={"pos_rank": "rank"})
    d = d.dropna(subset=["gsis_id"])
    d["rank"] = pd.to_numeric(d["rank"], errors="coerce")
    return d.groupby("gsis_id")["rank"].min().rename("dc_rank_prev_end").rename_axis("player_id").reset_index()


def bio(players):
    b = players[["gsis_id", "birth_date", "height", "weight", "rookie_season", "draft_year", "draft_round",
                 "draft_pick", "pfr_id", "position"]].rename(columns={"gsis_id": "player_id", "position": "bio_pos"})
    c = f("combine.csv").dropna(subset=["pfr_id"]).drop_duplicates("pfr_id")
    b = b.merge(c[["pfr_id", "forty", "vertical", "broad_jump", "cone", "shuttle", "bench"]], on="pfr_id", how="left")
    b["birth_date"] = pd.to_datetime(b.birth_date, errors="coerce")
    return b.drop(columns="pfr_id")


# ---------------------------------------------------------------- assemble
LAG_COLS = ["games", "fantasy_points", "fantasy_points_ppr", "fantasy_points_half", "attempts", "passing_yards",
            "passing_tds", "passing_interceptions", "passing_epa", "passing_cpoe", "carries", "rushing_yards",
            "rushing_tds", "rushing_epa", "targets", "receptions", "receiving_yards", "receiving_tds",
            "receiving_air_yards", "receiving_yards_after_catch", "receiving_epa", "target_share",
            "air_yards_share", "wopr", "ppr_wk_std", "ppr_wk_max", "ppr_2nd_half", "games_2nd_half", "n_teams",
            # snaps
            "snap_pct", "off_snaps", "snap_games", "snap_games50", "snap_pct_last4",
            # pbp
            "pbp_targets", "xrec", "xstd_rec", "xtd_rec", "rz_targets", "ez_targets", "deep_targets", "adot",
            "designed_carries", "xstd_rush", "xtd_rush", "rz_carries", "i10_carries", "i5_carries",
            "dropbacks", "qb_epa_db", "sack_rate"]
TEAM_COLS = ["tm_plays_pg", "tm_epa_play", "tm_pass_rate", "tm_neutral_pass_rate", "tm_proe", "tm_targets",
             "tm_air_yards", "tm_carries", "tm_rz_plays", "tm_pts_pg"]


def build():
    players = pd.read_csv(D / "players.csv.gz", low_memory=False)
    ss = season_stats()
    ss = ss.merge(snap_stats(players), on=["player_id", "season"], how="outer")
    pp = pd.read_pickle(ROOT / "work/pbp_player.pkl")
    ss = ss.merge(pp, on=["player_id", "season"], how="outer")
    tmx = pd.read_pickle(ROOT / "work/pbp_team.pkl")
    tmx["team"] = tm(tmx.team)
    # derived per-season rates
    ss["xfp_std"] = ss.xstd_rec.fillna(0) + ss.xstd_rush.fillna(0)
    ss["xfp_ppr"] = ss.xfp_std + ss.xrec.fillna(0)
    for c in ["fantasy_points", "fantasy_points_ppr", "fantasy_points_half", "xfp_std", "xfp_ppr", "targets",
              "carries", "attempts", "receptions", "rz_targets", "rz_carries"]:
        ss[c + "_pg"] = ss[c] / ss.games.where(ss.games > 0)
    ss["fpoe_ppr"] = ss.fantasy_points_ppr - ss.xfp_ppr  # finishing over expected (skill vs luck)
    ss["td_total"] = ss.rushing_tds.fillna(0) + ss.receiving_tds.fillna(0)
    ss["xtd_total"] = ss.xtd_rec.fillna(0) + ss.xtd_rush.fillna(0)
    ss["tdoe"] = ss.td_total - ss.xtd_total
    ss["yprr_proxy"] = ss.receiving_yards / ss.off_snaps.where(ss.off_snaps > 0)
    ss["ypc"] = ss.rushing_yards / ss.carries.where(ss.carries > 0)
    ss["ypa"] = ss.passing_yards / ss.attempts.where(ss.attempts > 0)
    ss["team_tgt_share_season"] = ss.targets / ss.merge(tmx, on=["team", "season"], how="left").tm_targets.values
    ss["team_car_share_season"] = ss.carries / ss.merge(tmx, on=["team", "season"], how="left").tm_carries.values
    lagc = LAG_COLS + [c for c in ss.columns if c.endswith("_pg")] + ["fpoe_ppr", "td_total", "tdoe", "xfp_std",
                                                                       "xfp_ppr", "yprr_proxy", "ypc", "ypa",
                                                                       "team_tgt_share_season",
                                                                       "team_car_share_season"]
    lagc = list(dict.fromkeys(lagc))
    b = bio(players)
    rows = []
    for Y in range(2014, LAST + 1):
        ros = week1_roster(Y)
        prev = ss[ss.season == Y - 1]
        cohort = ros[ros.position.isin(POS)][["player_id", "team", "position", "status"]]
        fa = prev[prev.position.isin(POS) & ~prev.player_id.isin(ros.player_id)][["player_id", "position"]]
        fa = fa.assign(team=np.nan, status="FA")
        c = pd.concat([cohort, fa], ignore_index=True).drop_duplicates("player_id")
        c["forecast_year"] = Y
        for L in (1, 2, 3):
            lag = ss[ss.season == Y - L].set_index("player_id")
            cols = lagc if L == 1 else ["games", "fantasy_points", "fantasy_points_ppr", "fantasy_points_pg",
                                        "fantasy_points_ppr_pg", "xfp_ppr_pg", "targets_pg", "carries_pg",
                                        "attempts_pg", "snap_pct", "target_share", "fpoe_ppr", "td_total"]
            c = c.join(lag[cols].add_prefix(f"l{L}_"), on="player_id")
        c = c.join(ss[ss.season == Y - 1].set_index("player_id")[["team"]].rename(columns={"team": "l1_team"}),
                   on="player_id")
        # career to date
        hist = ss[ss.season < Y].groupby("player_id").agg(car_seasons=("season", "nunique"),
                                                         car_games=("games", "sum"),
                                                         car_ppr=("fantasy_points_ppr", "sum"),
                                                         car_best_ppr_pg=("fantasy_points_ppr_pg", "max"))
        c = c.join(hist, on="player_id")
        c["car_ppr_pg"] = c.car_ppr / c.car_games.where(c.car_games > 0)
        # bio / draft
        c = c.merge(b, on="player_id", how="left")
        c["age"] = (pd.Timestamp(f"{Y}-09-01") - c.birth_date).dt.days / 365.25
        c["exp"] = Y - c.rookie_season
        c["is_rookie"] = (c.exp <= 0).astype(int)
        c["drafted"] = c.draft_pick.notna().astype(int)
        c["draft_pick_f"] = c.draft_pick.fillna(300)
        c["draft_round_f"] = c.draft_round.fillna(8)
        c["bmi"] = c.weight / c.height.clip(lower=60) ** 2 * 703
        c = c.merge(depth_chart(Y), on="player_id", how="left")
        c = c.merge(depth_chart_end(Y - 1), on="player_id", how="left")
        c["dc_rank_change"] = c.dc_rank - c.dc_rank_prev_end
        # ordinal within team position room: depth rank, then prior production, then draft capital
        c["_k1"] = c.dc_rank.fillna(9)
        c["_k2"] = -c.l1_fantasy_points_ppr_pg.fillna(0)
        c["_k3"] = c.draft_pick.fillna(300)
        c = c.sort_values(["_k1", "_k2", "_k3"])
        c["room_order"] = c.groupby(["team", "position"]).cumcount() + 1
        c.loc[c.team.isna(), "room_order"] = np.nan
        c["room_size"] = c.groupby(["team", "position"]).player_id.transform("size")
        c["room_n_starters"] = c.groupby(["team", "position"]).dc_rank.transform(lambda v: (v == 1).sum())
        c = c.drop(columns=["_k1", "_k2", "_k3"]).sort_index()
        c["changed_team"] = ((c.team != c.l1_team) & c.l1_team.notna() & c.team.notna()).astype(int)
        # team context for the season-Y team, measured in Y-1
        tprev = tmx[tmx.season == Y - 1].set_index("team")[TEAM_COLS]
        c = c.join(tprev.add_prefix("nt_"), on="team")
        # vacated / competing opportunity on the Y team
        p1 = prev.set_index("player_id")
        allr = ros[["player_id", "team", "position"]].join(
            p1[["targets", "carries", "fantasy_points_ppr", "fantasy_points_ppr_pg", "passing_yards", "games",
                "qb_epa_db", "attempts"]], on="player_id")
        rookies = allr.merge(b[["player_id", "draft_pick", "draft_year"]], on="player_id", how="left")
        rookies = rookies[(rookies.draft_year == Y) & (rookies.draft_pick <= 100)]
        tsum = allr.groupby("team")[["targets", "carries"]].sum()
        c = c.join(tsum.rename(columns={"targets": "ret_tgt_team", "carries": "ret_car_team"}), on="team")
        own_t, own_c = c.l1_targets.fillna(0), c.l1_carries.fillna(0)
        c["ret_tgt_others"] = c.ret_tgt_team - own_t.where(c.team.notna(), 0)
        c["ret_car_others"] = c.ret_car_team - own_c.where(c.team.notna(), 0)
        c["vac_tgt"] = c.nt_tm_targets - c.ret_tgt_team
        c["vac_car"] = c.nt_tm_carries - c.ret_car_team
        c["open_tgt_share"] = 1 - c.ret_tgt_others / c.nt_tm_targets
        c["open_car_share"] = 1 - c.ret_car_others / c.nt_tm_carries
        pos_t = allr.groupby(["team", "position"]).fantasy_points_ppr.agg(["sum", "max"])
        c = c.join(pos_t.rename(columns={"sum": "pos_room_ppr", "max": "pos_room_max_ppr"}), on=["team", "position"])
        c["pos_comp_ppr"] = c.pos_room_ppr.fillna(0) - c.l1_fantasy_points_ppr.fillna(0).where(c.team.notna(), 0)
        rk = rookies.groupby(["team", "position"]).draft_pick.agg(["min", "size"])
        c = c.join(rk.rename(columns={"min": "rookie_comp_best_pick", "size": "rookie_comp_n"}),
                   on=["team", "position"])
        own_rookie = (c.draft_year == Y) & (c.draft_pick <= 100)
        c.loc[own_rookie, "rookie_comp_n"] -= 1
        c["rookie_comp_n"] = c.rookie_comp_n.fillna(0)
        # QB quality of Y team: best prior-year passer on the week-1 roster (by pass yards/g, min 4 games)
        qbs = allr[(allr.position == "QB")].copy()
        qbs["pypg"] = qbs.passing_yards / qbs.games.where(qbs.games >= 4)
        qb = qbs.sort_values("pypg", ascending=False).drop_duplicates("team").set_index("team")
        c = c.join(qb[["pypg", "qb_epa_db"]].rename(columns={"pypg": "team_qb_pypg", "qb_epa_db": "team_qb_epa"}),
                   on="team")
        # rookie QB drafted high on team
        c["team_rookie_qb_r1"] = c.team.isin(rookies[(rookies.position == "QB") & (rookies.draft_pick <= 32)].team)
        # ---- targets (season Y)
        cur = ss[ss.season == Y].set_index("player_id")
        for k, col in [("y_std", "fantasy_points"), ("y_ppr", "fantasy_points_ppr"),
                       ("y_half", "fantasy_points_half"), ("y_games", "games"), ("y_rec", "receptions")]:
            c[k] = c.player_id.map(cur[col]).fillna(0) if Y < LAST else np.nan
        rows.append(c)
    X = pd.concat(rows, ignore_index=True).copy()
    X["team_rookie_qb_r1"] = X.team_rookie_qb_r1.astype(int)
    X["on_roster"] = X.team.notna().astype(int)
    X["status_code"] = X.status.map({"ACT": 0, "INA": 1, "RES": 2, "PUP": 2, "SUS": 3, "NON": 2, "EXE": 3,
                                     "DEV": 4, "FA": 5}).fillna(5)
    X["pos_code"] = X.position.map({p: i for i, p in enumerate(POS)})
    # weighted recent production (classic Marcel-style)
    for fmt in ["", "_ppr"]:
        pg = [X[f"l{L}_fantasy_points{fmt}_pg"] for L in (1, 2, 3)]
        gm = [X[f"l{L}_games"].fillna(0) for L in (1, 2, 3)]
        w = [5, 3, 2]
        num = sum(wi * gi * p.fillna(0) for wi, gi, p in zip(w, gm, pg))
        den = sum(wi * gi for wi, gi in zip(w, gm))
        X[f"marcel{fmt}_pg"] = num / den.where(den > 0)
    X = X.drop(columns=["birth_date", "l1_team"])
    return X


if __name__ == "__main__":
    X = build()
    X.to_pickle(ROOT / "work/features.pkl")
    print(X.shape)
    print(X.groupby(["forecast_year", "position"]).size().unstack())
    print(X[X.forecast_year == 2025].sort_values("y_ppr", ascending=False)[
        ["player_id", "position", "team", "status", "age", "dc_rank", "l1_fantasy_points_ppr", "y_ppr"]].head(8))
