# OverADP

Machine-learning fantasy football draft assistant with walk-forward validation, uncertainty ranges, and opportunity-cost guidance.

**Live site:** [overadp.com](https://overadp.com)

## Structure

- `/` — Landing page (SEO + conversion)
- `/app/` — Draft board application
- `/app/data/` — Pre-computed projections (JSON)

## Updating Data

From the main `nflmodel` repo:

```bash
python -m src.api.export_static --seasons 5 --scoring half_ppr
cp src/api/static/data/*.json site/app/data/
```

Then commit and push — Netlify auto-deploys.

## Deploy

Connected to GitHub → Netlify. Auto-deploys on push to `main`.
