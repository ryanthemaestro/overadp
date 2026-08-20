import unittest

from scripts.refresh_market_data import apply_sleeper_injury_fields


class InjuryOverlayTests(unittest.TestCase):
    def test_current_injury_details_are_exported(self):
        player = {"player_name": "Example Player", "injury_status": "Out"}
        status = apply_sleeper_injury_fields(
            player,
            {
                "injury_status": "Questionable",
                "injury_body_part": "Knee",
                "injury_notes": " Limited   workload ",
                "practice_participation": "Limited",
                "practice_description": "Limited Practice",
                "injury_start_date": "2026-08-18",
                "news_updated": "1787000000000",
                "status": "Active",
            },
        )

        self.assertEqual(status, "Questionable")
        self.assertEqual(player["injury_status"], "Questionable")
        self.assertEqual(player["injury_body_part"], "Knee")
        self.assertEqual(player["injury_notes"], "Limited workload")
        self.assertEqual(player["practice_description"], "Limited Practice")
        self.assertEqual(player["injury_news_updated"], 1787000000000)

    def test_old_injury_fields_are_removed_when_status_clears(self):
        player = {
            "player_name": "Healthy Player",
            "injury_status": "Questionable",
            "injury_body_part": "Hamstring",
            "injury_notes": "Strain",
            "injury_news_updated": 1787000000000,
        }

        status = apply_sleeper_injury_fields(player, {"injury_status": None})

        self.assertIsNone(status)
        self.assertNotIn("injury_status", player)
        self.assertNotIn("injury_body_part", player)
        self.assertNotIn("injury_notes", player)
        self.assertNotIn("injury_news_updated", player)


if __name__ == "__main__":
    unittest.main()
