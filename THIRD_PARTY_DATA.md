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
only the availability fields used by the application. In preseason, reserve
codes are shown as IR/PUP/NFI and can affect recommendations; practice-only
reports are shown as informational `INJ` notes. Q/D/O labels are used only when
the official weekly report release is available.

## Reviewed preseason notes

`preseason_injuries.json` contains a small, repository-reviewed overlay for
fantasy-relevant camp injuries that are absent from official weekly reports.
Each entry links to its public source, records the source timestamp, expires
automatically, and separates the reported facts from a labeled return outlook.
Expected games missed reduce Target Intel value using the same projection/VBD
score weights as the draft model; players reported ready for Week 1 receive no
deduction, and season-ending reports are removed from recommendations. These
outlooks are draft estimates, not medical diagnoses. The overlay is ignored
once nflverse's official weekly report is available.
