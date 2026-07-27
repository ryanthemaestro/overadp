# OverADP

Machine-learning fantasy football draft assistant with walk-forward validation, uncertainty ranges, and opportunity-cost guidance.

**Live site:** [overadp.com](https://overadp.com)

## Structure

- `/` — Landing page (SEO + conversion)
- `/app/` — Draft board application
- `/app/data/` — Pre-computed projections (JSON)

## Updating Data

### Daily draft-market refresh

Production refreshes current half-PPR ADP, teams, bye weeks, kicker depth
charts, the K/DEF Week 1-3 schedule model, and sleeper/bust labels every morning
during draft season:

```bash
python scripts/refresh_market_data.py
python scripts/validate_draft_data.py
```

The scheduled GitHub workflow runs the same commands and commits only after
all freshness, player-count, team/bye, duplicate, and source-join gates pass.
Daily market updates do not retrain or silently change the projection model,
and they do not invalidate a saved in-progress draft.

### Full projection refresh

From the full `nflmodel` working tree:

```bash
python -m src.api.export_static --seasons 5 --scoring half_ppr
cp src/api/static/data/*.json site/app/data/
python scripts/validate_draft_data.py
```

Run full model exports deliberately after meaningful preseason/roster changes,
then review accuracy, player coverage, and the browser rehearsal before
publishing.

See [`docs/DRAFT_DAY_RUNBOOK.md`](docs/DRAFT_DAY_RUNBOOK.md) for the release
and pre-draft checklist. See
[`docs/KDEF_STREAMING_MODEL.md`](docs/KDEF_STREAMING_MODEL.md) for the special
teams formulas, holdout evidence, and release gates.

## Deploy

Connected to GitHub → Netlify. Auto-deploys on push to `main`.
