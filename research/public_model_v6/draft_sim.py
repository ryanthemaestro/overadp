"""Paired snake-draft simulation, half-PPR, 2019-2025.

12 teams x 15 rounds. Lineup QB, 2RB, 3WR, TE, FLEX (RB/WR/TE); season score = best-ball optimal weekly lineup,
weeks 1-17, using ACTUAL weekly fantasy points (nflverse). Pool = players with FFC ADP in any format that season (half-PPR ADP preferred); 14 rounds.
Opponents draft by ADP with noise (ADP + N(0, FFC stdev)). The test seat drafts by value over replacement from one of:
  ADP     - ADP-implied points (log-ADP curve fit leaving the season out)
  Model   - v6 walk-forward projection (trained only on earlier seasons)
  Blend   - 50/50 of the two
Everything else (seat, opponent noise, roster rules) is identical across arms (paired seeds).
"""
import numpy as np, pandas as pd
import adp_eval as AE

CAPS = {"QB": 2, "RB": 6, "WR": 7, "TE": 2}
NEED = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
REPL = {"QB": 13, "RB": 30, "WR": 40, "TE": 13}
TEAMS, ROUNDS, SEEDS = 12, 14, 20


def weekly_points(season):
    w = pd.read_csv(f"data/spw_{season}.csv.gz", usecols=["player_id", "season_type", "week", "fantasy_points",
                                                          "fantasy_points_ppr"], low_memory=False)
    w = w[(w.season_type == "REG") & (w.week <= 17)]
    w["pts"] = (w.fantasy_points + w.fantasy_points_ppr) / 2
    return w.pivot_table(index="player_id", columns="week", values="pts", aggfunc="sum").fillna(0)


def bestball(ids, pos, W):
    if not ids:
        return 0.0
    m = W.reindex(ids).fillna(0).to_numpy()  # players x weeks
    p = np.array([pos[i] for i in ids])
    total = 0.0
    for wk in range(m.shape[1]):
        col = m[:, wk]
        used = np.zeros(len(ids), bool)
        s = 0.0
        for P, k in (("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1)):
            idx = np.where((p == P) & ~used)[0]
            top = idx[np.argsort(-col[idx])][:k]
            s += col[top].sum(); used[top] = True
        idx = np.where(np.isin(p, ["RB", "WR", "TE"]) & ~used)[0]
        if len(idx):
            s += col[idx].max()
        total += s
    return total


def value_board(d, col):
    v = pd.Series(0.0, index=d.index)
    for P, r in REPL.items():
        e = d[d.position == P][col]
        if len(e):
            v[e.index] = e - e.nlargest(min(r, len(e))).iloc[-1]
    return v


def pick(avail, order_vals, roster_pos, rounds_left):
    counts = {P: roster_pos.count(P) for P in CAPS}
    missing = {P: max(NEED[P] - counts[P], 0) for P in NEED}
    must = sum(missing.values()) >= rounds_left  # must fill starters now
    for i in order_vals:
        P = avail[i]
        if counts[P] >= CAPS[P]:
            continue
        if must and missing[P] == 0:
            continue
        return i
    return None


def simulate(M, season):
    import json
    A = pd.read_csv("adp/ffc_adp_2019_2025.csv"); A = A[A.season == season].copy()
    A["key"] = A.name.map(AE.norm)
    half = A[A.fmt == "half"].drop_duplicates("key").set_index("key")
    anyf = A.groupby("key").agg(adp=("adp", "mean"), adp_stdev=("adp_stdev", "mean"), position=("position", "first"))
    anyf.loc[half.index, ["adp", "adp_stdev"]] = half[["adp", "adp_stdev"]].values  # prefer half-PPR market
    wf = pd.read_csv("out/walkforward_predictions_2019_2025.csv")
    wf = wf[wf.forecast_year == season].copy(); wf["key"] = wf.name.map(AE.norm)
    d = wf.merge(anyf.reset_index(), on=["key", "position"], how="inner").drop_duplicates("player_id").set_index("player_id")
    d = d.rename(columns={"pred_half": "model"})
    loso = M[(M.fmt == "half") & (M.season == season)].drop_duplicates("player_id").set_index("player_id").adp_pts
    cur = json.load(open("adp_curve.json"))["half"]
    curve = d.apply(lambda r: max(cur[r.position]["intercept"] + cur[r.position]["slope_log_adp"] * np.log(r.adp), 0), axis=1)
    d["adp_pts"] = loso.reindex(d.index).fillna(curve)
    d["blend"] = (d.model + d.adp_pts) / 2
    d = d[d.position.isin(list(CAPS))]
    W = weekly_points(season)
    pos = d.position.to_dict()
    boards = {"ADP order": -d.adp, "ADP value": value_board(d, "adp_pts"), "Model": value_board(d, "model"),
              "Blend": value_board(d, "blend")}
    rows = []
    for seed in range(SEEDS):
        rng = np.random.default_rng(1000 * season + seed)
        noisy = (d.adp + rng.normal(0, d.adp_stdev.fillna(5).clip(lower=1))).sort_values()
        opp_order = list(noisy.index)
        for seat in range(TEAMS):
            for arm, val in boards.items():
                my_order = list(val.sort_values(ascending=False).index)
                avail = dict(pos); rosters = [[] for _ in range(TEAMS)]
                for rnd in range(ROUNDS):
                    order = range(TEAMS) if rnd % 2 == 0 else range(TEAMS - 1, -1, -1)
                    for t in order:
                        pref = my_order if t == seat else opp_order
                        cand = [i for i in pref if i in avail]
                        rp = [pos[i] for i in rosters[t]]
                        i = pick(avail, cand, rp, ROUNDS - rnd)
                        if i is None:
                            continue
                        rosters[t].append(i); avail.pop(i)
                scores = [bestball(r, pos, W) for r in rosters]
                mine = scores[seat]
                rank = 1 + sum(s > mine for s in scores)
                rows.append(dict(season=season, seed=seed, seat=seat, arm=arm, points=mine, rank=rank,
                                 top3=int(rank <= 3), win=int(rank == 1), field_avg=np.mean(scores)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    M = AE.load()
    R = pd.concat([simulate(M, y) for y in range(2019, 2026)])
    R.to_csv("out/draft_sim_2019_2025.csv", index=False)
    s = R.groupby("arm")[["points", "rank", "top3", "win"]].mean()
    print("Paired snake drafts, half-PPR best-ball, 12 teams, 2019-2025 (7 seasons x 20 seeds x 12 seats):")
    print(s.round(3).to_string())
    by = R.pivot_table(index="season", columns="arm", values="top3").round(3)
    print("\ntop-3 rate by season:\n", by.to_string())
    P = R.pivot_table(index=["season", "seed", "seat"], columns="arm", values="points")
    for a in ["ADP value", "Model", "Blend"]:
        diff = P[a] - P["ADP order"]
        se = diff.groupby(level="season").mean().std() / np.sqrt(7)
        print(f"{a} - ADP-order points per team: {diff.mean():+.1f} (season-level SE {se:.1f}); "
              f"seasons ahead: {(diff.groupby(level='season').mean() > 0).sum()}/7")
