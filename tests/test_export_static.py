import pandas as pd

from src.api.export_static import apply_current_adp_to_projection_rows


def test_current_adp_override_only_changes_projection_season():
    rows = pd.DataFrame([
        {"season": 2025, "player_name": "Omar Cooper", "position": "WR", "adp": 88.0, "pts_lag1": 0},
        {"season": 2026, "player_name": "Omar Cooper", "position": "WR", "adp": 200.0, "pts_lag1": 0},
        {"season": 2026, "player_name": "Kenneth Gainwell", "position": "RB", "adp": 200.0, "pts_lag1": 100},
    ])
    current_adp = pd.DataFrame([
        {"season": 2026, "player_name": "Omar Cooper Jr.", "position": "WR", "adp": 136.1},
        {"season": 2026, "player_name": "Kenny Gainwell", "position": "RB", "adp": 109.4},
    ])

    result = apply_current_adp_to_projection_rows(rows, current_adp, 2026)

    assert result.loc[result["season"].eq(2025), "adp"].item() == 88.0
    current = result[result["season"].eq(2026)].set_index("player_name")
    assert current.loc["Omar Cooper", "adp"] == 136.1
    assert current.loc["Kenneth Gainwell", "adp"] == 109.4
