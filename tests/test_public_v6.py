import json
import pandas as pd
from src.api.public_v6 import apply_public_v6, adp_implied_points


def _fixture(tmp_path):
    v6 = pd.DataFrame({"player_id": ["a", "b"], "position": ["RB", "WR"], "proj_std": [150.0, 100.0],
                       "proj_half": [170.0, 120.0], "proj_ppr": [190.0, 140.0],
                       "p10_half": [90.0, 60.0], "p90_half": [260.0, 180.0]})
    p = tmp_path / "projections_2026.csv"; v6.to_csv(p, index=False)
    curve = {"half": {"RB": {"intercept": 300.0, "slope_log_adp": -40.0}, "WR": {"intercept": 300.0, "slope_log_adp": -40.0}}}
    c = tmp_path / "curve.json"; c.write_text(json.dumps(curve))
    out = pd.DataFrame({"player_id": ["a", "b", "c"], "position": ["RB", "WR", "TE"], "projected_points": [100.0, 100.0, 80.0],
                        "ci_low": [50.0, 50.0, 40.0], "ci_high": [150.0, 150.0, 120.0], "adp": [10.0, 200.0, 50.0],
                        "rel_width": [1.0, 1.0, 1.0], "risk": ["medium"] * 3, "model_used": ["catboost"] * 3,
                        "interval_source": ["cqr"] * 3})
    return out, p, c


def test_model_only_override(tmp_path):
    out, p, c = _fixture(tmp_path)
    r = apply_public_v6(out, "half_ppr", blend=False, projections_csv=p)
    assert r.projected_points.tolist() == [170.0, 120.0, 80.0]      # c not in v6 -> unchanged
    assert r.projection_source.tolist() == ["public_v6", "public_v6", "catboost"]
    assert (r.ci_low <= r.projected_points).all() and (r.ci_high >= r.projected_points).all()


def test_blend_only_with_real_adp(tmp_path):
    out, p, c = _fixture(tmp_path)
    r = apply_public_v6(out, "half_ppr", blend=True, projections_csv=p, curve_json=c)
    adp_pts = 300 - 40 * __import__("math").log(10)
    assert abs(r.projected_points[0] - round((170 + adp_pts) / 2, 1)) < 0.11
    assert r.projected_points[1] == 120.0                             # ADP 200 = undrafted -> model only
    assert r.projection_source.tolist() == ["public_v6_adp_blend", "public_v6", "catboost"]


def test_adp_curve_ignores_undrafted():
    s = adp_implied_points(pd.Series([1.0, 200.0]), pd.Series(["RB", "RB"]), "half_ppr",
                           {"half": {"RB": {"intercept": 300.0, "slope_log_adp": -40.0}}})
    assert s[0] == 300.0 and pd.isna(s[1])
