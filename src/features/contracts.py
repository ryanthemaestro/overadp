"""Contract feature engineering with conservative as-of-season timing."""
from __future__ import annotations

import numpy as np
import pandas as pd


CONTRACT_VALUE = [
    "contract_apy_cap_pct_prev",
    "contract_apy_log_prev",
    "contract_guaranteed_log_prev",
    "contract_guaranteed_pct_prev",
]

CONTRACT_STATUS = [
    "contract_years_prev",
    "contract_years_elapsed_prev",
    "contract_years_remaining_prev",
    "contract_is_active_prev",
    "contract_year_flag_prev",
]

CONTRACT_ALL = CONTRACT_VALUE + CONTRACT_STATUS


def compute_contract_features(df: pd.DataFrame, contracts: pd.DataFrame | None) -> pd.DataFrame:
    """Add leak-safe prior-year contract features.

    The nflverse historical contracts table includes ``year_signed``, but not
    a precise transaction date. To avoid leaking in-season extensions, a
    player-season only sees contracts signed in years strictly before that
    season.
    """
    out = df.copy()
    feature_cols = CONTRACT_ALL
    out = out.drop(columns=[col for col in feature_cols if col in out.columns], errors="ignore")
    if contracts is None or contracts.empty or "player_id" not in out.columns or "season" not in out.columns:
        for col in feature_cols:
            out[col] = 0.0
        return out

    c = contracts.copy()
    c.columns = [str(col).lower() for col in c.columns]
    if "gsis_id" not in c.columns or "year_signed" not in c.columns:
        for col in feature_cols:
            out[col] = 0.0
        return out

    c = c.rename(columns={"gsis_id": "player_id"})
    keep = [
        "player_id", "position", "year_signed", "years", "value", "apy",
        "guaranteed", "apy_cap_pct", "inflated_value", "inflated_apy",
        "inflated_guaranteed",
    ]
    c = c[[col for col in keep if col in c.columns]].copy()
    c["player_id"] = c["player_id"].replace({"None": None, "": None})
    c = c.dropna(subset=["player_id", "year_signed"])
    if c.empty:
        for col in feature_cols:
            out[col] = 0.0
        return out

    numeric_cols = [col for col in c.columns if col not in {"player_id", "position"}]
    for col in numeric_cols:
        c[col] = pd.to_numeric(c[col], errors="coerce")

    rows = []
    for season in sorted(out["season"].dropna().astype(int).unique()):
        eligible = c[c["year_signed"] < season].copy()
        if eligible.empty:
            continue
        eligible = eligible.sort_values(["player_id", "year_signed", "apy"], ascending=[True, False, False])
        latest = eligible.drop_duplicates("player_id", keep="first").copy()
        latest["season"] = season

        value = latest.get("value", pd.Series(0, index=latest.index)).fillna(0)
        guaranteed = latest.get("guaranteed", pd.Series(0, index=latest.index)).fillna(0)
        apy = latest.get("apy", pd.Series(0, index=latest.index)).fillna(0)
        years = latest.get("years", pd.Series(0, index=latest.index)).fillna(0)
        year_signed = latest["year_signed"].fillna(season)
        contract_end = year_signed + years
        remaining = (contract_end - season).clip(lower=0)

        latest["contract_years_prev"] = years
        latest["contract_years_elapsed_prev"] = (season - year_signed).clip(lower=0)
        latest["contract_years_remaining_prev"] = remaining
        latest["contract_is_active_prev"] = (remaining > 0).astype(float)
        latest["contract_year_flag_prev"] = ((remaining > 0) & (remaining <= 1)).astype(float)
        latest["contract_apy_cap_pct_prev"] = latest.get("apy_cap_pct", pd.Series(0, index=latest.index)).fillna(0)
        latest["contract_apy_log_prev"] = np.log1p(apy.clip(lower=0))
        latest["contract_guaranteed_log_prev"] = np.log1p(guaranteed.clip(lower=0))
        latest["contract_guaranteed_pct_prev"] = (
            guaranteed / value.replace(0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(0)

        rows.append(latest[["player_id", "season"] + feature_cols])

    if not rows:
        for col in feature_cols:
            out[col] = 0.0
        return out

    features = pd.concat(rows, ignore_index=True)
    out = out.merge(features, on=["player_id", "season"], how="left")
    for col in feature_cols:
        out[col] = out[col].fillna(0.0)
    return out
