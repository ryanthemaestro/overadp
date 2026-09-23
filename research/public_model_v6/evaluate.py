import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
W = pd.read_pickle("work/walkforward.pkl")
POS = ["QB", "RB", "WR", "TE"]
TOPN = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
REPL = {"QB": 12, "RB": 30, "WR": 36, "TE": 12}  # 12-team, 1QB/2RB/3WR/1TE/1FLEX-ish replacement ranks
FMT = {"std": "fantasy_points", "half": "fantasy_points_half", "ppr": "fantasy_points_ppr"}


def pos_metrics(d, pred, fmt):
    rows = []
    for p in POS:
        e = d[d.position == p]
        a, pr, base = e[f"y_{fmt}"], e[pred], e[f"l1_{FMT[fmt]}"].fillna(0)
        n = TOPN[p]
        R = list(set(a.nlargest(n).index) | set(base.nlargest(n).index))
        ta, tp = a.nlargest(n), pr.nlargest(n)
        rows.append(dict(pos=p, mae_rel=np.mean(np.abs(a[R] - pr[R])), rho_rel=spearmanr(a[R], pr[R]).statistic,
                         hit12=len(set(a.nlargest(12).index) & set(pr.nlargest(12).index)),
                         capture=a[tp.index].sum() / ta.sum()))
    return pd.DataFrame(rows)


def vor(d, col):
    v = pd.Series(index=d.index, dtype=float)
    for p in POS:
        e = d[d.position == p][col]
        v[e.index] = e - e.nlargest(REPL[p]).iloc[-1]
    return v


def draft_value(d, pred, fmt, picks=120):
    """Take the top-`picks` overall by predicted VOR; sum their realised VOR (above realised replacement)."""
    av = vor(d, f"y_{fmt}")
    pv = vor(d, pred)
    chosen = pv.nlargest(picks).index
    ideal = av.nlargest(picks)
    return av[chosen].clip(lower=-50).sum() / ideal.sum(), spearmanr(av[chosen], pv[chosen]).statistic


def report(years, label):
    out = []
    for fmt in ["std", "half", "ppr"]:
        W[f"prior_{fmt}"] = W[f"l1_{FMT[fmt]}"].fillna(0)
        preds = {"model": f"pred_{fmt}", "prior season": f"prior_{fmt}"}
        if fmt == "std":
            preds["screen-feature HGB"] = "screen_hgb_std"
        for name, col in preds.items():
            for Y in years:
                d = W[W.forecast_year == Y]
                m = pos_metrics(d, col, fmt).assign(year=Y, model=name, fmt=fmt)
                dv, _ = draft_value(d, col, fmt)
                m["draft_value"] = dv
                out.append(m)
    R = pd.concat(out)
    print(f"\n==== {label} ====")
    print(R.groupby(["fmt", "model"])[["mae_rel", "rho_rel", "hit12", "capture", "draft_value"]].mean().round(3)
          .to_string())
    return R


if __name__ == "__main__":
    val = report(range(2019, 2025), "walk-forward 2019-2024 (model-selection years)")
    test = report([2025], "2025 final holdout")
    print("\n2025 half-PPR by position:")
    print(test[test.fmt == "half"].pivot_table(index="model", columns="pos", values=["mae_rel", "capture"]).round(3)
          .to_string())
    # comparison with the TabPFN screen cohort: 2025, players with a prior season, standard scoring, all players
    d = W[(W.forecast_year == 2025) & W.l1_games.notna()]
    screen = {"QB": (54.83, 56.95), "RB": (35.72, 34.42), "WR": (22.35, 22.39), "TE": (17.06, 16.06)}
    print("\n2025 standard, prior-season cohort (TabPFN-screen definition): MAE")
    rows = []
    for p in POS:
        e = d[d.position == p]
        rows.append(dict(pos=p, n=len(e), new_model=np.mean(np.abs(e.y_std - e.pred_std)),
                         screen_feat_hgb=np.mean(np.abs(e.y_std - e.screen_hgb_std)),
                         screen_catboost=screen[p][0], screen_tabpfn=screen[p][1]))
    t = pd.DataFrame(rows)
    tot = t.n.sum()
    t.loc[len(t)] = dict(pos="ALL", n=tot, **{c: (t[c] * t.n).sum() / tot for c in
                                               ["new_model", "screen_feat_hgb", "screen_catboost", "screen_tabpfn"]})
    print(t.round(2).to_string(index=False))
    val.to_csv("out/metrics_walkforward.csv", index=False)
    test.to_csv("out/metrics_2025.csv", index=False)
    t.to_csv("out/screen_comparison_2025.csv", index=False)
