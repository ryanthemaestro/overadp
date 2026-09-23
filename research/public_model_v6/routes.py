"""Route-participation features from nflverse participation (RESEARCH ONLY: NGS through 2022 / FTN 2023+, CC BY-SA).
routes ~= skill player on the field for a dropback. Output: work/routes_player.pkl (player-season)."""
import os, subprocess
import numpy as np, pandas as pd

B = "https://github.com/nflverse/nflverse-data/releases/download/pbp_participation"
out = []
for y in range(2016, 2026):
    f = f"data/part_{y}.csv"
    if not os.path.exists(f):
        subprocess.run(["curl", "-sSL", "-o", f, f"{B}/pbp_participation_{y}.csv"], check=True)
    pa = pd.read_csv(f, usecols=["nflverse_game_id", "play_id", "offense_players"], low_memory=False)
    pb = pd.read_csv(f"data/pbp_{y}.csv.gz", usecols=["game_id", "play_id", "season_type", "qb_dropback", "posteam",
                                                       "receiver_player_id", "receiving_yards", "complete_pass",
                                                       "two_point_attempt"], low_memory=False)
    pb = pb[(pb.season_type == "REG") & (pb.qb_dropback == 1) & (pb.two_point_attempt != 1)]
    m = pb.merge(pa.rename(columns={"nflverse_game_id": "game_id"}), on=["game_id", "play_id"], how="inner")
    m = m.dropna(subset=["offense_players"])
    team_db = m.groupby(["game_id", "posteam"]).size().rename("team_db")
    e = m[["game_id", "posteam", "play_id", "offense_players", "receiver_player_id", "receiving_yards"]].copy()
    e["pid"] = e.offense_players.str.split(";")
    e = e.explode("pid")
    e["tgt"] = (e.pid == e.receiver_player_id).astype(int)
    e["yds"] = np.where(e.tgt == 1, e.receiving_yards.fillna(0), 0)
    g = e.groupby(["pid", "game_id", "posteam"]).agg(routes=("play_id", "size"), tgt=("tgt", "sum"), yds=("yds", "sum"))
    g = g.join(team_db, on=["game_id", "posteam"]).reset_index()
    s = g.groupby("pid").agg(rt_routes=("routes", "sum"), rt_tgt=("tgt", "sum"), rt_yds=("yds", "sum"),
                             rt_team_db=("team_db", "sum"), rt_games=("game_id", "nunique"))
    s["rt_share"] = s.rt_routes / s.rt_team_db
    s["rt_tprr"] = s.rt_tgt / s.rt_routes.where(s.rt_routes >= 50)
    s["rt_yprr"] = s.rt_yds / s.rt_routes.where(s.rt_routes >= 50)
    s["season"] = y
    out.append(s.rename_axis("player_id").reset_index())
    os.remove(f)
    print(y, len(m), "dropbacks matched", flush=True)
R = pd.concat(out)
R.to_pickle("work/routes_player.pkl")
print(R.groupby("season").rt_routes.describe()[["count", "max"]])
