import pandas as pd

from src.features.contracts import compute_contract_features


def test_contract_features_only_use_prior_year_signings():
    rows = pd.DataFrame([
        {"player_id": "p1", "season": 2025},
        {"player_id": "p1", "season": 2026},
    ])
    contracts = pd.DataFrame([
        {
            "gsis_id": "p1",
            "year_signed": 2025,
            "years": 3,
            "value": 30_000_000,
            "apy": 10_000_000,
            "guaranteed": 15_000_000,
            "apy_cap_pct": 0.04,
        },
    ])

    result = compute_contract_features(rows, contracts).set_index("season")

    assert result.loc[2025, "contract_is_active_prev"] == 0
    assert result.loc[2026, "contract_is_active_prev"] == 1
    assert result.loc[2026, "contract_years_remaining_prev"] == 2
    assert result.loc[2026, "contract_guaranteed_pct_prev"] == 0.5
