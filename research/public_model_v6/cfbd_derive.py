"""Stdlib-only: turn cfbd_raw/ into compact derived tables for drafted QB/RB/WR/TE only.
Output: cfbd_derived/{draft,player_seasons,recruits}.csv (derived, per-player aggregates)."""
import csv, json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW, OUT = HERE / "cfbd_raw", HERE / "cfbd_derived"
OUT.mkdir(exist_ok=True)
POS = {"QB", "RB", "WR", "TE", "FB", "HB"}

draft = []
for f in sorted(RAW.glob("draft_*.json")):
    for d in json.load(open(f)):
        if (d.get("position") or "").upper() in POS or (d.get("position") or "") in ("Running Back", "Wide Receiver", "Tight End", "Quarterback"):
            draft.append({k: d.get(k) for k in ("year", "overall", "round", "pick", "name", "position", "collegeAthleteId",
                                                "nflAthleteId", "collegeTeam", "collegeConference", "preDraftRanking",
                                                "preDraftPositionRanking", "preDraftGrade", "height", "weight")})
ids = {str(d["collegeAthleteId"]) for d in draft if d["collegeAthleteId"] is not None}

team = defaultdict(dict)
for f in sorted(RAW.glob("team_*.json")):
    for r in json.load(open(f)):
        team[(r["season"], r["team"])][r["statName"]] = r["statValue"]

ps = defaultdict(dict)
for f in sorted(RAW.glob("player_*_*.json")):
    for r in json.load(open(f)):
        pid = str(r["playerId"])
        if pid not in ids:
            continue
        k = (pid, r["season"], r["team"])
        ps[k].update({"name": r["player"], "conference": r.get("conference"), "cfb_pos": r.get("position")})
        try:
            ps[k][f'{r["category"]}_{r["statType"]}'] = float(r["stat"])
        except (TypeError, ValueError):
            pass
cols = ["playerId", "season", "team", "name", "conference", "cfb_pos", "receiving_REC", "receiving_YDS", "receiving_TD",
        "rushing_CAR", "rushing_YDS", "rushing_TD", "passing_ATT", "passing_COMPLETIONS", "passing_YDS", "passing_TD",
        "passing_INT", "tm_games", "tm_passAttempts", "tm_netPassingYards", "tm_passingTDs", "tm_rushingAttempts",
        "tm_rushingYards", "tm_rushingTDs", "tm_totalYards"]
with open(OUT / "player_seasons.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
    for (pid, season, tm), v in ps.items():
        t = team.get((season, tm), {})
        row = {"playerId": pid, "season": season, "team": tm, **v,
               **{f"tm_{s}": t.get(s) for s in ("games", "passAttempts", "netPassingYards", "passingTDs",
                                               "rushingAttempts", "rushingYards", "rushingTDs", "totalYards")}}
        w.writerow({c: row.get(c) for c in cols})
with open(OUT / "draft.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(draft[0].keys())); w.writeheader(); w.writerows(draft)
with open(OUT / "recruits.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["athleteId", "year", "stars", "rating", "ranking", "position"])
    for f in sorted(RAW.glob("recruits_*.json")):
        for r in json.load(open(f)):
            if str(r.get("athleteId")) in ids:
                w.writerow([r.get("athleteId"), r.get("year"), r.get("stars"), r.get("rating"), r.get("ranking"), r.get("position")])
print("draft rows", len(draft), "| player-season rows", len(ps), "| ids", len(ids))
