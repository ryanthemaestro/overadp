"""College-production features (CollegeFootballData, derived tables only) -> work/features_v5.pkl

Linked to NFL players via (draft year, overall pick) between CFBD draft picks and nflverse draft picks.
Static per player, built only from college seasons before the draft; attached to every forecast year.
Data provided by CollegeFootballData.com.
"""
import numpy as np
import pandas as pd

U = "cfbd_derived/"  # produced locally by cfbd_derive.py
dr = pd.read_csv(U + "draft.csv")
ps = pd.read_csv(U + "player_seasons.csv")
rc = pd.read_csv(U + "recruits.csv")
nfl = pd.read_csv("data/draft_picks.csv.gz", low_memory=False)[["season", "pick", "gsis_id"]].dropna()
players = pd.read_csv("data/players.csv.gz", low_memory=False)[["gsis_id", "birth_date"]]
players["birth_date"] = pd.to_datetime(players.birth_date, errors="coerce")

link = dr.merge(nfl, left_on=["year", "overall"], right_on=["season", "pick"], how="inner")
link = link.rename(columns={"gsis_id": "player_id"})[["player_id", "collegeAthleteId", "year", "collegeConference",
                                                        "preDraftRanking", "preDraftPositionRanking", "preDraftGrade"]]
link = link.merge(players.rename(columns={"gsis_id": "player_id"}), on="player_id", how="left")

s = ps.rename(columns={"playerId": "collegeAthleteId"})
num = [c for c in s.columns if c.startswith(("receiving_", "rushing_", "passing_", "tm_"))]
s = s.groupby(["collegeAthleteId", "season"])[num].sum(min_count=1).reset_index()
s = s.merge(link[["collegeAthleteId", "year", "birth_date"]], on="collegeAthleteId")
s = s[s.season < s.year]
f0 = lambda c: s[c].fillna(0)
s["rec_yds_share"] = f0("receiving_YDS") / s.tm_netPassingYards.where(s.tm_netPassingYards > 0)
s["rec_td_share"] = f0("receiving_TD") / s.tm_passingTDs.where(s.tm_passingTDs > 0)
s["dominator"] = s[["rec_yds_share", "rec_td_share"]].mean(axis=1)
s["scrim_share"] = (f0("receiving_YDS") + f0("rushing_YDS")) / s.tm_totalYards.where(s.tm_totalYards > 0)
s["rush_share"] = f0("rushing_YDS") / s.tm_rushingYards.where(s.tm_rushingYards > 0)
s["ryptpa"] = f0("receiving_YDS") / s.tm_passAttempts.where(s.tm_passAttempts > 0)
s["age_season"] = (pd.to_datetime(s.season.astype(str) + "-09-01") - s.birth_date).dt.days / 365.25
s = s.sort_values(["collegeAthleteId", "season"])

g = s.groupby("collegeAthleteId")
last = g.tail(1).set_index("collegeAthleteId")
F = pd.DataFrame(index=last.index)
F["col_seasons"] = g.size()
for c, n in [("receiving_REC", "rec"), ("receiving_YDS", "rec_yds"), ("receiving_TD", "rec_td"), ("rushing_CAR", "car"),
             ("rushing_YDS", "rush_yds"), ("rushing_TD", "rush_td"), ("passing_ATT", "pass_att"),
             ("passing_YDS", "pass_yds"), ("passing_TD", "pass_td"), ("passing_INT", "pass_int")]:
    F[f"col_final_{n}"] = last[c]
for c in ["rec_yds_share", "rec_td_share", "dominator", "scrim_share", "rush_share", "ryptpa", "age_season"]:
    F[f"col_final_{c}"] = last[c]
F["col_best_dominator"] = g.dominator.max()
F["col_best_scrim_share"] = g.scrim_share.max()
F["col_best_ryptpa"] = g.ryptpa.max()
F["col_final_ypa"] = last.passing_YDS / last.passing_ATT.where(last.passing_ATT > 0)
F["col_final_td_rate"] = last.passing_TD / last.passing_ATT.where(last.passing_ATT > 0)
F["col_final_int_rate"] = last.passing_INT / last.passing_ATT.where(last.passing_ATT > 0)
bo_rec = s[s.dominator >= 0.20].groupby("collegeAthleteId").age_season.min()
bo_rb = s[s.scrim_share >= 0.20].groupby("collegeAthleteId").age_season.min()
F["col_breakout_age_rec"] = bo_rec.reindex(F.index).fillna(25)
F["col_breakout_age_scrim"] = bo_rb.reindex(F.index).fillna(25)
F = F.reset_index()

L = link.merge(F, on="collegeAthleteId", how="left")
rc = rc.sort_values("rating", ascending=False).drop_duplicates("athleteId")
L = L.merge(rc[["athleteId", "stars", "rating"]].rename(columns={"athleteId": "collegeAthleteId", "stars": "col_recruit_stars",
                                                                  "rating": "col_recruit_rating"}), on="collegeAthleteId", how="left")
L["col_power_conf"] = L.collegeConference.isin(["SEC", "Big Ten", "Big 12", "ACC", "Pac-12", "Pac-10"]).astype(int)
L = L.rename(columns={"preDraftRanking": "col_predraft_rank", "preDraftPositionRanking": "col_predraft_pos_rank",
                      "preDraftGrade": "col_predraft_grade"})
keep = ["player_id"] + [c for c in L.columns if c.startswith("col_")]
L = L[keep].drop_duplicates("player_id")

X = pd.read_pickle("work/features_v2.pkl").merge(L, on="player_id", how="left")
X.to_pickle("work/features_v5.pkl")
cols = [c for c in X.columns if c.startswith("col_")]
r = X[(X.is_rookie == 1) & X.drafted.eq(1)]
print("linked players:", L.player_id.nunique(), "| college features:", len(cols))
print("coverage among drafted rookies by year:")
print(r.groupby("forecast_year")[["col_final_rec_yds", "col_best_dominator", "col_recruit_rating", "col_predraft_grade"]]
      .apply(lambda d: d.notna().mean()).round(2).to_string())
