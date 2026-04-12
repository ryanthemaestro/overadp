# OverADP

AI-powered fantasy football draft assistant. 4-model ML ensemble beats ADP by 58%.

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
