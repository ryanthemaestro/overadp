# Third-party data attribution

## nflverse availability data

OverADP uses selected fields from the `nflverse/nflverse-data` GitHub releases:

- `weekly_rosters/roster_weekly_2026.csv` for current roster availability;
- `injuries/injuries_2026.csv` for official weekly game and practice reports
  when that season file is available.

Source: https://github.com/nflverse/nflverse-data

License: Creative Commons Attribution 4.0 International (CC BY 4.0):
https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md

OverADP modifies the source data by selecting current-season/current-week
records, joining them to its fantasy-player board, mapping only documented
injury/PUP/NFI roster codes, normalizing weekly report labels, and publishing
only the availability fields used by the application.
