# OverADP Draft-Day Runbook

## What is automated

- Every day at 10:17 UTC, GitHub Actions fetches the latest 12-team half-PPR
  market from Fantasy Football Calculator and the current Sleeper NFL player
  feed.
- The job updates ADP, teams, bye weeks, K/DEF coverage, sleeper/bust labels,
  and `metadata.json`.
- The job stops without publishing if the source is stale, player volume
  drops, a top-24 market player is missing, join coverage falls, team/bye
  coverage breaks, IDs duplicate, or the two published data copies differ.
- A passing refresh commits to `main`, which triggers the Netlify production
  deploy.

## Model checkpoints

The daily job does not retrain projections. Run and review the full model
export at these higher-signal checkpoints:

1. After each preseason weekend if injuries or depth-chart changes materially
   alter roles.
2. Immediately after final 53-player roster cuts on August 30.
3. After the August 31 waiver-claim/practice-squad churn.
4. On the morning of any important home-league draft.

Keep the current guarded recommendation policy unless a replacement beats it
across the relevant league formats. The experimental scarcity policy is not a
draft-day release candidate.

## Fifteen minutes before a draft

1. Open `/app/` and confirm the ADP badge is green and dated today or yesterday.
2. Log in and confirm the paid season plan is visible.
3. Set league size, draft position, scoring, starters, FLEX, K/DEF, and bench.
   For a 2QB league, set QB to 2. True Superflex is not yet modeled as a
   separate slot.
4. Draft one player, mark one opponent pick, reload, and confirm both persist.
   Undo both test picks.
5. Use **EXPORT** to save a CSV backup of the current board.
6. Keep the app tab open. If an upstream service has an incident, the loaded
   board and local draft state continue working in that tab.

## Manual refresh and verification

```bash
python scripts/refresh_market_data.py
python scripts/validate_draft_data.py --max-age-hours 72
```

A healthy release reports:

- at least 800 skill projections;
- all 32 NFL teams and bye weeks;
- at least 98% current offensive ADP join coverage;
- all top-24 market players matched;
- at least 25 current K/DEF ADP matches;
- market metadata no older than 72 hours;
- identical `site/app/data` and `src/api/static/data` files.

## Incident behavior

- **Red or amber ADP badge:** use the exported CSV or last loaded board and
  investigate the scheduled workflow before trusting market timing.
- **Authentication waking up:** wait one minute and retry. The login endpoint
  returns HTTP 503 for a sleeping/unreachable auth service rather than blaming
  the password.
- **Refresh workflow failed:** do not bypass a player/top-24/join-coverage gate
  just to force a deploy. Inspect the source schema or name alias, fix it, and
  rerun validation.
