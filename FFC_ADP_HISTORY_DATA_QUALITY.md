# Historical ADP distribution import

## Decision

**Approved for Scarcity 2.0 availability research with documented limits.**

The imported fields are trustworthy for estimating player-specific draft
position dispersion in 12-team formats. They are not exact pick-by-pick draft
logs, and the 12-team archive must not be relabeled as observed 10- or 14-team
behavior.

## Dataset and grain

- Source: [Fantasy Football Calculator ADP API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api).
- Grain: one player by season, scoring format, and team count.
- Seasons: 2019-2024.
- Formats: standard, half-PPR, PPR, and 2-QB.
- League size: 12 teams.
- Coverage: 24 snapshots, 4,704 player rows, including 4,081 QB/RB/WR/TE rows.
- Provider evidence: the snapshot-level draft counts sum to 44,971. This is a
  measure of source volume across snapshots, not a claim of 44,971 unique
  people or mutually exclusive drafts.
- Fields retained: mean ADP, ADP standard deviation, earliest/latest pick,
  times drafted, source draft count and window, source player ID, URL, and
  fetch timestamp.

| Season | Snapshots | Player rows | Sum of snapshot draft counts |
|---:|---:|---:|---:|
| 2019 | 4 | 760 | 5,026 |
| 2020 | 4 | 846 | 7,045 |
| 2021 | 4 | 864 | 10,019 |
| 2022 | 4 | 673 | 6,551 |
| 2023 | 4 | 786 | 9,731 |
| 2024 | 4 | 775 | 6,599 |

## Quality checks

Every accepted snapshot passed these automated checks:

- Requested season equals the provider's source-period year.
- Requested team count equals returned metadata.
- Requested scoring format equals returned metadata, with `Non-PPR` accepted
  as the provider's label for standard scoring.
- At least 40 player rows and a positive provider draft count.
- No duplicate source player IDs within a snapshot.
- Required IDs, names, and positions are populated.
- ADP is positive, standard deviation is non-negative, and the mean lies
  between the reported earliest and latest picks.

The full profile is in `experiments/ffc_adp_history_profile.csv`.

## Findings and risks

### Medium: historical league-size coverage

The provider's historical endpoint can silently return 12-team metadata for a
non-12-team request. The importer rejects any such mismatch. Use these observed
distributions directly for 12-team leagues; adapting them to 10 or 14 teams is
a model assumption that must be validated separately.

### Medium: no exact draft sequence or roster context

The API publishes aggregate distributions, not complete human pick sequences.
It can replace the fixed, identical availability spread currently assigned to
every player, but it cannot by itself learn correlations such as positional
runs or how a drafter's existing roster changes the next selection.

### Medium: uneven tail coverage

Snapshot player counts vary from 124 to 226. The 2022 half-PPR archive is the
smallest at 124 players, so late-round availability estimates for that partition
will be less complete. Core early- and middle-round players remain covered.

### Low: one inconsistent provider count

The 2021 PPR snapshot reports Gus Edwards as drafted 1,951 times while the
snapshot metadata reports 1,709 total drafts. All ADP, standard-deviation, and
pick-bound fields pass. Preserve the raw value for auditability, but do not use
that row's `times_drafted / total_drafts` ratio as a probability or reliability
weight.

## Safe downstream use

1. Fit player availability from `adp` and `adp_sd`, bounded by the observed
   earliest and latest picks.
2. Use walk-forward evaluation: train on prior seasons and score the next one.
3. Keep format-specific distributions; never pool 2-QB with one-QB formats.
4. Treat 10- and 14-team transforms, positional-run behavior, and missing 2025
   dispersion as explicit uncertainties.
5. Retain the current guarded board until the distribution-based policy passes
   the production gates in `SCARCITY_V2_EXPERIMENT.md`.

## Reproduction

```bash
python scripts/import_ffc_adp_history.py \
  --seasons 2019 2020 2021 2022 2023 2024 \
  --scoring standard half-ppr ppr 2qb \
  --teams 12
```

Normalized data, raw source responses, the request manifest, and the complete
quality profile are written under the gitignored `data/` directory. The
importer requests attribution to Fantasy Football Calculator when the data is
used in the product.
