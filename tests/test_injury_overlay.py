import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.refresh_market_data import (
    apply_espn_injury_fields,
    apply_nflverse_injury_fields,
    apply_preseason_injury_note,
    expected_games_missed_from_return_date,
    fetch_optional_csv,
    flatten_espn_injuries,
    load_preseason_injury_file,
    PRESEASON_INJURY_FILE,
)


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

    def test_espn_suspension_is_normalized_with_games_and_return(self):
        payload = {
            "injuries": [{
                "injuries": [{
                    "status": "Suspension",
                    "date": "2026-08-29T12:00:00Z",
                    "shortComment": "Unavailable for the first four games.",
                    "athlete": {
                        "id": "1234",
                        "displayName": "Example Receiver",
                        "position": {"abbreviation": "WR"},
                        "team": {"abbreviation": "DAL"},
                        "links": [{"rel": ["news"], "href": "https://example.com/news"}],
                    },
                    "type": {"description": "Suspension"},
                    "details": {
                        "type": "Suspension",
                        "returnDate": "2026-10-11",
                    },
                }],
            }],
        }

        rows = flatten_espn_injuries(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expected_games_missed"], 4.0)
        self.assertEqual(rows[0]["suspension_games"], 4.0)

        player = {"player_name": "Example Receiver", "position": "WR"}
        status = apply_espn_injury_fields(
            player,
            rows[0],
            "2026-08-29T13:00:00Z",
        )
        self.assertEqual(status, "Suspension")
        self.assertEqual(player["suspension_games"], 4.0)
        self.assertEqual(player["expected_return_date"], "2026-10-11")

    def test_return_date_counts_games_before_eligible_sunday(self):
        self.assertEqual(expected_games_missed_from_return_date("2026-09-13"), 0.0)
        self.assertEqual(expected_games_missed_from_return_date("2026-09-20"), 1.0)
        self.assertEqual(expected_games_missed_from_return_date("2026-10-11"), 4.0)

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

    def test_current_preseason_reserve_codes_are_exposed(self):
        cases = {
            "R34": "Injured Reserve",
            "R36": "Injured Reserve",
            "R37": "PUP",
            "R41": "PUP",
            "R46": "NFI",
        }

        for roster_code, expected in cases.items():
            with self.subTest(roster_code=roster_code):
                player = {"player_name": "Preseason Reserve Player"}
                status = apply_nflverse_injury_fields(
                    player,
                    None,
                    {"status": "RES", "status_description_abbr": roster_code},
                    "2026-08-20T12:00:00Z",
                )

                self.assertEqual(status, expected)
                self.assertEqual(player["injury_status"], expected)

    def test_practice_report_without_game_designation_is_informational(self):
        player = {"player_name": "Camp Injury Player"}

        status = apply_nflverse_injury_fields(
            player,
            {
                "report_status": "",
                "practice_primary_injury": "Hamstring",
                "practice_status": "Did Not Participate in Practice",
            },
            {"status": "ACT"},
            "2026-09-08T12:00:00Z",
        )

        self.assertEqual(status, "INJ")
        self.assertEqual(player["injury_status"], "INJ")
        self.assertEqual(player["injury_body_part"], "Hamstring")

    def test_reviewed_preseason_note_is_informational_and_expires(self):
        note = {
            "injury_body_part": "Calf",
            "injury_notes": "Held out as a precaution.",
            "season_outlook": "expected_week_1",
            "expected_games_missed": 0,
            "outlook_confidence": "reported",
            "source_label": "NFL.com player news",
            "source_url": "https://example.com/player",
            "source_updated_at": "2026-08-20T14:52:00Z",
            "expires_on": "2026-08-26",
        }
        player = {"player_name": "Camp Injury Player"}

        status = apply_preseason_injury_note(
            player,
            note,
            "2026-08-20T16:00:00Z",
        )

        self.assertEqual(status, "INJ")
        self.assertEqual(player["injury_status"], "INJ")
        self.assertEqual(player["injury_source_label"], "NFL.com player news")
        self.assertEqual(player["season_outlook"], "expected_week_1")
        self.assertEqual(player["expected_games_missed"], 0)
        self.assertIsNone(
            apply_preseason_injury_note(
                {},
                note,
                "2026-08-27T12:00:00Z",
            )
        )

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
            "season_outlook": "expected_absence",
            "expected_games_missed": 3,
            "expected_return_date": "2026-09-27",
            "outlook_confidence": "estimated",
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
        self.assertNotIn("season_outlook", player)
        self.assertNotIn("expected_games_missed", player)
        self.assertNotIn("expected_return_date", player)
        self.assertNotIn("outlook_confidence", player)

    def test_reviewed_preseason_file_has_structured_draft_outlooks(self):
        rows = load_preseason_injury_file(PRESEASON_INJURY_FILE)

        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all("season_outlook" in row for row in rows))
        self.assertTrue(all("expected_games_missed" in row for row in rows))
        self.assertTrue(any(row["season_outlook"] == "season_out" for row in rows))
        self.assertTrue(any(float(row["expected_games_missed"]) > 0 for row in rows))


if __name__ == "__main__":
    unittest.main()
