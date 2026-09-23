"""Per player-season and team-season opportunity features from nflverse play-by-play.

Expected-points ("xFP") lookups are fitted within each season only, so a lag-season
feature never uses information from a later season.
"""
import numpy as np
import pandas as pd
from pathlib import Path

D = Path(__file__).parent / "data"
COLS = ["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score", "away_score",
        "play_type", "yardline_100", "air_yards", "complete_pass", "pass_attempt", "rush_attempt",
        "passer_player_id", "receiver_player_id", "rusher_player_id", "receiving_yards", "rushing_yards",
        "pass_touchdown", "rush_touchdown", "epa", "qb_dropback", "two_point_attempt", "sack", "qb_scramble",
        "down", "wp", "xpass"]


def bins_air(a):
    return pd.cut(a.clip(-10, 60), [-11, -1, 2, 5, 9, 14, 19, 29, 61], labels=False)


def bins_yl(y):
    return pd.cut(y, [0, 2, 5, 10, 20, 40, 60, 80, 100], labels=False)


def season(year: int):
    p = pd.read_csv(D / f"pbp_{year}.csv.gz", usecols=COLS, low_memory=False)
    p = p[(p.season_type == "REG") & (p.two_point_attempt != 1)]
    # ---- targets
    t = p[(p.play_type == "pass") & p.receiver_player_id.notna() & p.air_yards.notna()].copy()
    t["ab"], t["yb"] = bins_air(t.air_yards), bins_yl(t.yardline_100)
    t["rec"] = t.complete_pass.fillna(0)
    t["std"] = 0.1 * t.receiving_yards.fillna(0) + 6 * t.pass_touchdown.fillna(0)
    grp = t.groupby(["ab", "yb"])
    t["x_rec"] = grp.rec.transform("mean")
    t["x_std"] = grp["std"].transform("mean")
    t["x_td"] = grp.pass_touchdown.transform("mean")
    t["rz"] = t.yardline_100 <= 20
    t["ez"] = t.air_yards >= t.yardline_100
    t["deep"] = t.air_yards >= 20
    rcv = t.groupby("receiver_player_id").agg(
        pbp_targets=("rec", "size"), xrec=("x_rec", "sum"), xstd_rec=("x_std", "sum"), xtd_rec=("x_td", "sum"),
        rz_targets=("rz", "sum"), ez_targets=("ez", "sum"), deep_targets=("deep", "sum"),
        adot=("air_yards", "mean"), rec_epa_pbp=("epa", "sum"))
    # ---- carries
    r = p[(p.play_type == "run") & p.rusher_player_id.notna() & (p.qb_scramble != 1)].copy()
    r["yb"] = pd.cut(r.yardline_100, [0, 1, 2, 3, 5, 10, 20, 40, 70, 100], labels=False)
    r["std"] = 0.1 * r.rushing_yards.fillna(0) + 6 * r.rush_touchdown.fillna(0)
    g = r.groupby("yb")
    r["x_std"] = g["std"].transform("mean")
    r["x_td"] = g.rush_touchdown.transform("mean")
    r["rz"], r["i10"], r["i5"] = r.yardline_100 <= 20, r.yardline_100 <= 10, r.yardline_100 <= 5
    rsh = r.groupby("rusher_player_id").agg(
        designed_carries=("std", "size"), xstd_rush=("x_std", "sum"), xtd_rush=("x_td", "sum"),
        rz_carries=("rz", "sum"), i10_carries=("i10", "sum"), i5_carries=("i5", "sum"))
    sc = p[(p.qb_scramble == 1) & p.rusher_player_id.notna()]
    scr = sc.groupby("rusher_player_id").agg(scrambles=("rushing_yards", "size"), scramble_yds=("rushing_yards", "sum"))
    gl = r[r.yardline_100 <= 5].groupby(["posteam", "rusher_player_id"]).size()
    gl_share = (gl / gl.groupby(level=0).transform("sum")).groupby(level=1).max().rename("gl_carry_share")
    rsh = rsh.join(scr, how="outer").join(gl_share, how="outer")
    # ---- passers
    q = p[(p.qb_dropback == 1) & p.passer_player_id.notna()]
    qb = q.groupby("passer_player_id").agg(dropbacks=("epa", "size"), qb_epa_db=("epa", "mean"),
                                           sack_rate=("sack", "mean"))
    player = rcv.join(rsh, how="outer").join(qb, how="outer")
    player.index.name = "player_id"
    player = player.reset_index()
    player["season"] = year
    # ---- team context
    off = p[p.play_type.isin(["pass", "run"]) & p.posteam.notna()]
    neutral = off[(off.wp.between(0.2, 0.8)) & (off.down <= 2)]
    team = off.groupby("posteam").agg(tm_plays=("epa", "size"), tm_epa_play=("epa", "mean"),
                                      tm_pass_rate=("qb_dropback", "mean"),
                                      tm_games=("game_id", "nunique"))
    team["tm_neutral_pass_rate"] = neutral.groupby("posteam").qb_dropback.mean()
    team["tm_proe"] = (neutral.qb_dropback - neutral.xpass).groupby(neutral.posteam).mean()
    team["tm_targets"] = t.groupby("posteam").size()
    team["tm_air_yards"] = t.groupby("posteam").air_yards.sum()
    team["tm_carries"] = r.groupby("posteam").size()
    team["tm_rz_plays"] = off[off.yardline_100 <= 20].groupby("posteam").size()
    games = p.drop_duplicates("game_id")
    pts = pd.concat([games[["home_team", "home_score"]].set_axis(["tm", "pts"], axis=1),
                     games[["away_team", "away_score"]].set_axis(["tm", "pts"], axis=1)])
    team["tm_pts_pg"] = pts.groupby("tm").pts.mean()
    team.index.name = "team"
    team = team.reset_index()
    team["tm_plays_pg"] = team.tm_plays / team.tm_games
    team["season"] = year
    return player, team


if __name__ == "__main__":
    P, T = zip(*(season(y) for y in range(2012, 2026)))
    pd.concat(P).to_pickle(Path(__file__).parent / "work/pbp_player.pkl")
    pd.concat(T).to_pickle(Path(__file__).parent / "work/pbp_team.pkl")
    print(pd.concat(P).shape, pd.concat(T).shape)
    print(pd.concat(T).groupby("season").team.nunique().to_dict())
