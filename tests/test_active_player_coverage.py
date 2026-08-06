import unittest

from scripts.refresh_market_data import active_depth_projection_coverage


class ActivePlayerCoverageTests(unittest.TestCase):
    def test_sleeper_id_covers_public_name_change(self):
        players = [{
            "player_id": "00-0036919",
            "sleeper_id": "7567.0",
            "player_name": "Kenneth Gainwell",
            "position": "RB",
        }]
        sleeper = {
            "7567": {
                "full_name": "Kenny Gainwell",
                "position": "RB",
                "team": "TB",
                "status": "Active",
                "depth_chart_order": 2,
            },
        }

        coverage = active_depth_projection_coverage(players, sleeper)

        self.assertEqual(coverage["expected_active_depth_players"], 1)
        self.assertEqual(coverage["matched_active_depth_players"], 1)
        self.assertEqual(coverage["missing_active_depth_players"], [])

    def test_missing_active_depth_player_is_reported(self):
        coverage = active_depth_projection_coverage([], {
            "2449": {
                "full_name": "Stefon Diggs",
                "position": "WR",
                "team": "WAS",
                "status": "Active",
                "depth_chart_order": 2,
            },
        })

        self.assertEqual(
            coverage["missing_active_depth_players"],
            ["Stefon Diggs|WR"],
        )


if __name__ == "__main__":
    unittest.main()
