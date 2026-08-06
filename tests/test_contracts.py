import pandas as pd

from src.features.contracts import CONTRACT_ALL, compute_contract_features


def test_contract_signed_during_season_is_not_visible_until_next_season():
    player_seasons = pd.DataFrame([
        {"player_id": "p1", "season": 2025},
        {"player_id": "p1", "season": 2026},
    ])
    contracts = pd.DataFrame([{
        "gsis_id": "p1",
        "year_signed": 2025,
        "years": 3,
        "value": 60_000_000,
        "apy": 20_000_000,
        "guaranteed": 30_000_000,
        "apy_cap_pct": 0.08,
    }])

    result = compute_contract_features(player_seasons, contracts).set_index("season")

    assert result.loc[2025, CONTRACT_ALL].sum() == 0
    assert result.loc[2026, "contract_is_active_prev"] == 1
    assert result.loc[2026, "contract_years_remaining_prev"] == 2
