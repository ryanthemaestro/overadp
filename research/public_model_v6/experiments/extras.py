"""Extra preseason feature groups on top of work/features_v2.pkl -> work/features_v4.pkl

qb_*     QB rushing style, starter security, supporting cast            (nflverse pbp/rosters, CC BY 4.0)
coach_*  head-coach change / tenure / coach's previous pass rate & pace  (nflverse schedules, CC BY 4.0)
vegas_*  week-1 implied team total & spread (set before kickoff)         (nflverse schedules)
ngs_*    Next Gen Stats season summaries  -- RESEARCH ONLY (rights review required), kept separate
"""
import numpy as np
import pandas as pd
import build_features as BF

X = pd.read_pickle("work/features_v2.pkl")
pp = pd.read_pickle("work/pbp_player.pkl")
tm = pd.read_pickle("work/pbp_team.pkl")
tm["team"] = BF.tm(tm.team)
names = pd.read_csv("data/players.csv.gz", low_memory=False)

# ---------------- QB rushing style (lag 1 and 2)
for L in (1, 2):
    lag = pp.assign(forecast_year=pp.season + L)[["forecast_year", "player_id", "scrambles", "scramble_yds",
                                                   "designed_carries", "gl_carry_share", "i5_carries"]]
    lag = lag.rename(columns={c: f"qb_l{L}_{c}" for c in lag.columns[2:]})
    X = X.merge(lag, on=["forecast_year", "player_id"], how="left")
g = X.l1_games.where(X.l1_games > 0)
X["qb_l1_designed_pg"] = X.qb_l1_designed_carries / g
X["qb_l1_scramble_pg"] = X.qb_l1_scrambles / g
X["qb_l1_rush_share_of_fp"] = (X.l1_rushing_yards.fillna(0) * .1 + X.l1_rushing_tds.fillna(0) * 6) / \
    X.l1_fantasy_points.where(X.l1_fantasy_points > 0)

# ---------------- starter security & supporting cast (season-Y roster)
rows = []
for Y, c in X.groupby("forecast_year"):
    c = c.copy()
    qbs = c[c.position == "QB"]
    qpy = qbs.l1_passing_yards / qbs.l1_games.where(qbs.l1_games >= 4)
    q = qbs.assign(pypg=qpy.fillna(0))
    for i, r in q.iterrows():
        others = q[(q.team == r.team) & (q.player_id != r.player_id)]
        c.loc[i, "qb_backup_best_pypg"] = others.pypg.max() if len(others) else 0
        c.loc[i, "qb_backup_best_draft"] = others.draft_pick_f.min() if len(others) else 300
        c.loc[i, "qb_rookie_threat"] = int(((others.draft_year == Y) & (others.draft_pick <= 64)).any())
        c.loc[i, "qb_n_on_roster"] = len(others) + 1
    skill = c[c.position.isin(["WR", "TE", "RB"])]
    cast = skill.groupby("team").l1_fantasy_points_ppr.apply(lambda v: v.fillna(0).nlargest(4).sum())
    top_rook = skill[(skill.draft_year == Y) & (skill.draft_pick <= 64)].groupby("team").size()
    c["qb_cast_top4_ppr"] = c.team.map(cast)
    c["qb_cast_new_top_rookies"] = c.team.map(top_rook).fillna(0)
    rows.append(c)
X = pd.concat(rows)
X["qb_gap_to_backup"] = X.l1_passing_yards / X.l1_games.where(X.l1_games >= 4) - X.qb_backup_best_pypg
qbcols = [c for c in X.columns if c.startswith("qb_")]
X.loc[X.position != "QB", [c for c in qbcols if c.startswith(("qb_backup", "qb_rookie", "qb_n_", "qb_gap"))]] = np.nan

# ---------------- coaching & Vegas from schedules
gm = pd.read_csv("data/games.csv.gz")
gm = gm[gm.game_type == "REG"]
side = pd.concat([
    gm[["season", "week", "home_team", "home_coach", "spread_line", "total_line"]].set_axis(
        ["season", "week", "team", "coach", "spread", "total"], axis=1).assign(home=1),
    gm[["season", "week", "away_team", "away_coach", "spread_line", "total_line"]].set_axis(
        ["season", "week", "team", "coach", "spread", "total"], axis=1).assign(home=0)])
side["team"] = BF.tm(side.team)
# nflverse spread_line = home margin expected; team implied = total/2 + margin/2
side["margin"] = np.where(side.home == 1, side.spread, -side.spread)
side["implied"] = side.total / 2 + side.margin / 2
wk1 = side.sort_values("week").groupby(["season", "team"]).first()
last = side.sort_values("week").groupby(["season", "team"]).last()
X = X.join(wk1[["implied", "margin", "total"]].rename(columns=lambda c: f"vegas_wk1_{c}"),
           on=["forecast_year", "team"])
# coach history
coach_team = last.reset_index()[["season", "team", "coach"]]
coach_team = coach_team.merge(tm[["season", "team", "tm_neutral_pass_rate", "tm_plays_pg", "tm_epa_play", "tm_proe"]],
                              on=["season", "team"], how="left")
hc = wk1.reset_index()[["season", "team", "coach"]].rename(columns={"season": "forecast_year", "coach": "coach_now"})
prev_hc = last.reset_index()[["season", "team", "coach"]].assign(forecast_year=lambda d: d.season + 1)
hc = hc.merge(prev_hc[["forecast_year", "team", "coach"]].rename(columns={"coach": "coach_prev"}),
              on=["forecast_year", "team"], how="left")
hc["coach_new_hc"] = (hc.coach_now != hc.coach_prev).astype(int)
ten = []
for _, r in hc.iterrows():
    h = coach_team[(coach_team.coach == r.coach_now) & (coach_team.season < r.forecast_year)]
    lastrow = h.sort_values("season").iloc[-1] if len(h) else None
    ten.append(dict(coach_hc_years=len(h),
                    coach_prev_pass_rate=None if lastrow is None else lastrow.tm_neutral_pass_rate,
                    coach_prev_pace=None if lastrow is None else lastrow.tm_plays_pg,
                    coach_prev_epa=None if lastrow is None else lastrow.tm_epa_play,
                    coach_prev_proe=None if lastrow is None else lastrow.tm_proe))
hc = pd.concat([hc.reset_index(drop=True), pd.DataFrame(ten)], axis=1)
X = X.merge(hc.drop(columns=["coach_now", "coach_prev"]), on=["forecast_year", "team"], how="left")

# ---------------- NGS (research-only)
def ngs(kind, cols):
    n = pd.read_csv(f"data/ngs_{kind}.csv.gz")
    n = n[(n.season_type == "REG") & (n.week == 0)]  # week 0 = season summary
    n = n[["season", "player_gsis_id"] + cols].rename(columns={"player_gsis_id": "player_id"})
    n["forecast_year"] = n.season + 1
    return n.drop(columns="season").rename(columns={c: f"ngs_l1_{c}" for c in cols})
for kind, cols in [("receiving", ["avg_cushion", "avg_separation", "avg_intended_air_yards",
                                  "avg_yac_above_expectation", "catch_percentage"]),
                   ("rushing", ["efficiency", "percent_attempts_gte_eight_defenders", "avg_time_to_los",
                                "rush_yards_over_expected_per_att", "rush_pct_over_expected"]),
                   ("passing", ["avg_time_to_throw", "aggressiveness", "completion_percentage_above_expectation",
                                "avg_air_yards_to_sticks"])]:
    try:
        X = X.merge(ngs(kind, cols), on=["forecast_year", "player_id"], how="left")
    except KeyError as e:
        print("ngs", kind, "missing col", e)

X = X.reset_index(drop=True)
X.to_pickle("work/features_v4.pkl")
for p in ["qb_", "coach_", "vegas_", "ngs_"]:
    cols = [c for c in X.columns if c.startswith(p)]
    print(p, len(cols), X[X.forecast_year >= 2016][cols].notna().mean().round(2).to_dict())
