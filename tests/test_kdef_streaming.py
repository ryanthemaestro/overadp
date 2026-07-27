import unittest

from scripts.refresh_market_data import (
    VALID_TEAMS,
    apply_opening_streaming_model,
    current_kicker_rows,
    defense_expected_points,
    kicker_expected_points,
    opening_schedule_contexts,
)


class KDefStreamingTests(unittest.TestCase):
    def synthetic_schedule(self):
        teams = sorted(VALID_TEAMS)
        rows = []
        for week in (1, 2, 3):
            for game_index in range(16):
                away = teams[game_index]
                home = teams[-game_index - 1]
                rows.append({
                    "season": "2026",
                    "game_type": "REG",
                    "week": str(week),
                    "away_team": away,
                    "home_team": home,
                    "spread_line": str((game_index % 7) - 3),
                    "total_line": str(40 + (game_index % 9)),
                    "roof": "dome" if game_index % 4 == 0 else "outdoors",
                })
        return rows

    def test_expected_points_move_in_the_intended_direction(self):
        self.assertGreater(
            kicker_expected_points(28, 1.0, True),
            kicker_expected_points(20, 0.0, False),
        )
        self.assertGreater(
            defense_expected_points(17),
            defense_expected_points(28),
        )

    def test_opening_schedule_and_stream_ranks_cover_every_team(self):
        contexts = opening_schedule_contexts(self.synthetic_schedule())
        board = []
        for team in sorted(VALID_TEAMS):
            board.extend([
                {
                    "player_id": f"K_{team}",
                    "player_name": f"{team} Kicker",
                    "position": "K",
                    "team": team,
                    "adp": 200,
                },
                {
                    "player_id": f"DEF_{team}",
                    "player_name": f"{team} Defense",
                    "position": "DEF",
                    "team": team,
                    "adp": 200,
                },
            ])
        apply_opening_streaming_model(board, contexts)
        for position in ("K", "DEF"):
            rows = [row for row in board if row["position"] == position]
            self.assertEqual(
                sorted(row["stream_rank"] for row in rows),
                list(range(1, 33)),
            )
            self.assertTrue(all(len(row["opening_schedule"]) == 3 for row in rows))
            self.assertTrue(all(row["opening_schedule"][0]["week"] == 1 for row in rows))

    def test_sleeper_depth_chart_rebuilds_one_current_kicker_per_team(self):
        sleeper = {}
        for index, team in enumerate(sorted(VALID_TEAMS), start=1):
            sleeper[str(index)] = {
                "position": "K",
                "team": team,
                "active": True,
                "status": "Active",
                "depth_chart_order": 1,
                "full_name": f"{team} Current Kicker",
            }
        previous = [{
            "player_id": "K_PRIOR",
            "player_name": "Prior Kicker",
            "position": "K",
            "team": "ARI",
            "projected_points": 100,
            "ci_low": 75,
            "ci_high": 125,
            "uncertainty": 0.5,
            "risk": "high",
            "adp": 200,
            "pts_lag1": 0,
            "model_used": "test",
            "bye": 10,
            "vbd": 0,
            "projected_receptions": 0,
        }]
        rebuilt = current_kicker_rows(sleeper, previous)
        self.assertEqual(len(rebuilt), 32)
        self.assertEqual({row["team"] for row in rebuilt}, VALID_TEAMS)
        self.assertTrue(all(row["depth_chart_order"] == 1 for row in rebuilt))
        self.assertTrue(all(row["role_confidence"] == "HIGH" for row in rebuilt))


if __name__ == "__main__":
    unittest.main()
