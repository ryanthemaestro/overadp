import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.refresh_market_data import apply_nflverse_injury_fields, fetch_optional_csv


class InjuryOverlayTests(unittest.TestCase):
    @patch("scripts.refresh_market_data.fetch_csv")
    def test_not_yet_published_season_report_is_optional(self, fetch_csv):
        fetch_csv.side_effect = HTTPError(
            "https://example.invalid/injuries_2026.csv",
            404,
            "Not Found",
            None,
            None,
        )

        self.assertEqual(fetch_optional_csv("https://example.invalid"), [])

    def test_current_injury_details_are_exported(self):
        player = {"player_name": "Example Player", "injury_status": "Out"}
        status = apply_nflverse_injury_fields(
            player,
            {
                "report_status": "Questionable",
                "report_primary_injury": "Knee",
                "practice_primary_injury": "Knee",
                "practice_status": "Limited Participation in Practice",
            },
            {"status": "ACT"},
            "2026-09-10T12:00:00Z",
        )

        self.assertEqual(status, "Questionable")
        self.assertEqual(player["injury_status"], "Questionable")
        self.assertEqual(player["injury_body_part"], "Knee")
        self.assertEqual(
            player["practice_description"],
            "Limited Participation in Practice",
        )
        self.assertEqual(player["injury_source_updated_at"], "2026-09-10T12:00:00Z")

    def test_documented_injury_reserve_code_is_exposed(self):
        player = {"player_name": "Injured Reserve Player"}

        status = apply_nflverse_injury_fields(
            player,
            None,
            {"status": "RES", "status_description_abbr": "R01"},
            "2026-08-20T12:00:00Z",
        )

        self.assertEqual(status, "Injured Reserve")
        self.assertEqual(player["injury_status"], "Injured Reserve")
        self.assertEqual(player["roster_status"], "RES")
        self.assertNotIn("injury_body_part", player)

    def test_unknown_reserve_code_does_not_invent_an_injury(self):
        player = {"player_name": "Unsigned Draft Choice"}

        status = apply_nflverse_injury_fields(
            player,
            None,
            {"status": "RES", "status_description_abbr": "R09"},
            "2026-08-20T12:00:00Z",
        )

        self.assertIsNone(status)
        self.assertNotIn("injury_status", player)

    def test_old_injury_fields_are_removed_when_status_clears(self):
        player = {
            "player_name": "Healthy Player",
            "injury_status": "Questionable",
            "injury_body_part": "Hamstring",
            "injury_notes": "Strain",
            "injury_news_updated": 1787000000000,
        }

        status = apply_nflverse_injury_fields(
            player,
            None,
            {"status": "ACT"},
            "2026-08-20T12:00:00Z",
        )

        self.assertIsNone(status)
        self.assertNotIn("injury_status", player)
        self.assertNotIn("injury_body_part", player)
        self.assertNotIn("injury_notes", player)
        self.assertNotIn("injury_news_updated", player)


if __name__ == "__main__":
    unittest.main()
