import sys, warnings
import numpy as np, pandas as pd
import backtest as B
warnings.filterwarnings("ignore")
X, FULL = B.X, B.FULL
YEARS = list(range(2019, 2025))

G = {
    "dc": ["dc_rank"],
    "bio": [c for c in FULL if c in ("age", "exp", "is_rookie", "drafted", "draft_pick_f", "draft_round_f", "bmi",
                                     "height", "weight", "forty", "vertical", "broad_jump", "cone", "shuttle",
                                     "bench")],
    "team": [c for c in FULL if c.startswith(("nt_", "vac_", "open_", "ret_", "pos_room", "pos_comp", "rookie_comp",
                                                "team_qb", "team_rookie")) or c == "changed_team"],
    "pbp": [c for c in FULL if any(k in c for k in ("xfp", "xrec", "xstd", "xtd", "rz_", "ez_", "deep", "adot", "i10",
                                                     "i5_", "tdoe", "fpoe", "designed", "dropbacks", "qb_epa",
                                                     "sack_rate", "pbp_targets"))],
    "snap": [c for c in FULL if "snap" in c],
    "status": ["status_code", "on_roster"],
}


def run(feats, fmt="half", weight=None, pooled=True, **kw):
    out = []
    for Y in YEARS:
        tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
        w = None if weight is None else weight(tr, Y)
        m = B.hgb(kw.pop("loss", "squared_error") if False else kw.get("loss", "squared_error"),
                  **{k: v for k, v in kw.items() if k != "loss"})
        m.fit(tr[feats], tr[f"y_{fmt}"], sample_weight=w)
        out.append(pd.Series(m.predict(te[feats]), index=te.index))
    return np.maximum(pd.concat(out), 0)


def score(name, pr, fmt="half"):
    m = B.metrics(pr, fmt, YEARS)
    s = m[["mae_all", "mae_rel", "rho_rel", "hit12", "hitN", "capture"]].mean()
    print(f"{name:34s}", " ".join(f"{k}={v:.3f}" for k, v in s.items()), flush=True)
    return s


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "ablate":
        score("full", run(FULL))
        for g, cols in G.items():
            score(f"-{g} ({len(cols)})", run([c for c in FULL if c not in cols]))
    if which == "params":
        for kw in [dict(max_iter=800, learning_rate=0.015), dict(max_leaf_nodes=31, min_samples_leaf=40),
                   dict(max_leaf_nodes=7), dict(min_samples_leaf=50), dict(max_features=0.25),
                   dict(max_features=1.0), dict(l2_regularization=10), dict(max_iter=250, learning_rate=0.05)]:
            score(str(kw), run(FULL, **kw))
    if which == "weights":
        score("recency 0.9^age", run(FULL, weight=lambda tr, Y: 0.9 ** (Y - tr.forecast_year)))
        score("recency 0.8^age", run(FULL, weight=lambda tr, Y: 0.8 ** (Y - tr.forecast_year)))
        score("drop DEV/FA-noprior", run(FULL, weight=lambda tr, Y: np.where(
            tr.status.isin(["DEV"]) & tr.l1_games.isna(), 0.2, 1.0)))
    if which == "v2":
        base = run(FULL, min_samples_leaf=50, l2_regularization=10)
        score("full+room (msl50,l2=10)", base)
        old = [c for c in FULL if c not in ("dc_rank_prev_end", "dc_rank_change", "room_order", "room_size",
                                            "room_n_starters")]
        score("without new room feats", run(old, min_samples_leaf=50, l2_regularization=10))
        # seed bagging
        bag = sum(run(FULL, min_samples_leaf=50, l2_regularization=10, random_state=s) for s in range(5)) / 5
        score("bag5", bag)
        # two-stage: games x per-game
        out = []
        for Y in YEARS:
            tr, te = X[X.forecast_year < Y], X[X.forecast_year == Y]
            mg = B.hgb(min_samples_leaf=50, l2_regularization=10).fit(tr[FULL], tr.y_games)
            played = tr[tr.y_games >= 1]
            mp = B.hgb(min_samples_leaf=50, l2_regularization=10).fit(
                played[FULL], played.y_half / played.y_games, sample_weight=played.y_games)
            out.append(pd.Series(np.clip(mg.predict(te[FULL]), 0, 17) * np.maximum(mp.predict(te[FULL]), 0),
                                 index=te.index))
        two = pd.concat(out)
        score("two-stage games x ppg", two)
        score("avg(bag5, two-stage)", (bag + two) / 2)
        pd.to_pickle({"bag": bag, "two": two}, "work/v2_preds.pkl")
