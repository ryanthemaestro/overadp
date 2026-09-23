"""Optional override: use the public-data v6 projections (research/public_model_v6) in the static export.

Off by default. Enabled with `export_static.py --projection-source public_v6` (model only) or
`--projection-source public_v6_blend` (50/50 v6 + ADP-implied points for players with real ADP).
Players missing from the v6 file keep their CatBoost projection (`projection_source` records which).

Walk-forward evidence (2023-2025, half-PPR, real-ADP cohort): v6 rank corr .414 / MAE 55.7 vs the
cached production CatBoost reconstruction .293 / 63.8; 50/50 blend .426 / 54.3; ADP .403 / ~56.
See research/public_model_v6/README.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

V6_DIR = Path(__file__).resolve().parents[2] / "research" / "public_model_v6"
SCORING_COL = {"half_ppr": "proj_half", "ppr": "proj_ppr", "standard": "proj_std"}
CURVE_FMT = {"half_ppr": "half", "ppr": "ppr", "standard": "std"}
NO_ADP = 200  # export_static fills missing ADP with 200


def adp_implied_points(adp: pd.Series, position: pd.Series, scoring: str, curve: dict) -> pd.Series:
    """ADP -> expected season points via per-position log(ADP) fit (research/public_model_v6/adp_curve.json)."""
    coefs = curve[CURVE_FMT[scoring]]
    a = position.map(lambda p: coefs.get(p, {}).get("intercept", np.nan))
    b = position.map(lambda p: coefs.get(p, {}).get("slope_log_adp", np.nan))
    adp = pd.to_numeric(adp, errors="coerce")
    pts = a + b * np.log(adp.clip(lower=1))
    return pts.where(adp.lt(NO_ADP)).clip(lower=0)


def apply_public_v6(out: pd.DataFrame, scoring: str = "half_ppr", blend: bool = False,
                    projections_csv: str | Path | None = None, curve_json: str | Path | None = None) -> pd.DataFrame:
    """Return a copy of `out` with projected_points / ci_low / ci_high / rel_width / risk replaced by v6."""
    path = Path(projections_csv) if projections_csv else None
    if path is None:
        cands = sorted((V6_DIR / "out").glob("projections_*.csv"))
        if not cands:
            raise FileNotFoundError(f"No v6 projections found in {V6_DIR / 'out'}; run research/public_model_v6/run_all.sh")
        path = cands[-1]
    v6 = pd.read_csv(path)
    col = SCORING_COL[scoring]
    v6 = v6.dropna(subset=[col]).drop_duplicates("player_id").set_index("player_id")

    res = out.copy()
    res["projection_source"] = "catboost"
    pid = res["player_id"].astype(str)
    mask = pid.isin(v6.index)
    if not mask.any():
        print("  Warning: no players matched the v6 projections; export unchanged")
        return res

    new = pid[mask].map(v6[col]).astype(float).clip(lower=0)
    # 80% range: v6 empirical half-PPR range, scaled to this scoring format by the projection ratio.
    ratio = new / pid[mask].map(v6["proj_half"]).astype(float).where(lambda s: s > 0)
    lo = pid[mask].map(v6["p10_half"]).astype(float) * ratio
    hi = pid[mask].map(v6["p90_half"]).astype(float) * ratio
    old_mid = pd.to_numeric(res.loc[mask, "projected_points"], errors="coerce").fillna(0)
    old_half = ((pd.to_numeric(res.loc[mask, "ci_high"], errors="coerce").fillna(old_mid)
                 - pd.to_numeric(res.loc[mask, "ci_low"], errors="coerce").fillna(old_mid)) / 2).clip(lower=0)
    lo = lo.where(lo.notna(), new - old_half)
    hi = hi.where(hi.notna(), new + old_half)
    source = "public_v6"

    if blend:
        curve = json.loads(Path(curve_json or V6_DIR / "adp_curve.json").read_text())
        adp_pts = adp_implied_points(res.loc[mask, "adp"], res.loc[mask, "position"], scoring, curve)
        has = adp_pts.notna()
        shift = (adp_pts - new).where(has, 0) / 2
        new, lo, hi = new + shift, lo + shift, hi + shift
        source = np.where(has, "public_v6_adp_blend", "public_v6")

    res.loc[mask, "projected_points"] = new.round(1)
    res.loc[mask, "ci_low"] = lo.clip(lower=0).round(1)
    res.loc[mask, "ci_high"] = hi.clip(lower=0).round(1)
    res.loc[mask, "rel_width"] = np.where(new > 0, (hi - lo.clip(lower=0)) / new, 99.0).round(3)
    res.loc[mask, "interval_source"] = "v6_empirical"
    res.loc[mask, "model_used"] = "public_v6"
    res.loc[mask, "projection_source"] = source

    res["risk"] = "medium"
    for pos, min_proj in {"QB": 50, "RB": 30, "WR": 30, "TE": 20}.items():
        m = res["position"].eq(pos) & res["projected_points"].ge(min_proj)
        if m.sum() >= 4:
            q25, q75 = res.loc[m, "rel_width"].quantile([0.25, 0.75])
            res.loc[m & res["rel_width"].le(q25), "risk"] = "low"
            res.loc[m & res["rel_width"].ge(q75), "risk"] = "high"
        res.loc[res["position"].eq(pos) & res["projected_points"].lt(min_proj), "risk"] = "high"
    print(f"  Public v6 projections applied to {int(mask.sum())}/{len(res)} players "
          f"({'with' if blend else 'without'} ADP blend) from {path.name}")
    return res
