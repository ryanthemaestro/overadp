# OverADP Reply Helper

A Vivaldi/Chrome extension that adds a **Δ Draft** button next to every tweet on
x.com. Click it and an LLM drafts 3 reply options grounded in your OverADP
model data (top-250 projections, sleeper/bust labels, CI ranges).

You still post manually — the extension never sends anything to X, so it stays
within X's ToS.

## Install (one-time, ~2 min)

1. Open `vivaldi://extensions` (or `chrome://extensions`)
2. Toggle **Developer mode** (top right)
3. Click **Load unpacked**
4. Select this folder: `/home/nar/Documents/overadp/tools/reply-helper`
5. Pin the extension (puzzle icon → pin Δ)
6. Click the Δ icon → paste your API key:
   - **Anthropic** (recommended): get at https://console.anthropic.com/settings/keys — starts with `sk-ant-...`
   - **OpenAI**: get at https://platform.openai.com/api-keys — starts with `sk-...`
7. Save. Done.

## Use

1. Go to x.com (or your fantasy-football list)
2. Scroll — every tweet now has a **Δ Draft** button next to Like
3. Click it → overlay shows 3 draft replies (~3 sec)
4. Click **Copy** on the best one
5. Click X's native **Reply** button, paste, post

### Tips

- Change **Tone** (analyst / casual / mix) per-tweet in the overlay, or set default in the popup
- If a tweet mentions a player in the top-250, the extension injects that player's stats into the prompt automatically — drafts will cite real projections
- Hit **Generate** again to get 3 new drafts with different angles

## Refresh player context

Whenever `site/app/data/players.json` changes (weekly during the season):

```bash
python build_context.py
```

Then reload the extension from `vivaldi://extensions` (no re-install needed).

## Cost

- Anthropic Haiku 4.6: ~$0.01 per draft call (3 replies)
- OpenAI GPT-4o-mini: ~$0.001 per call
- Expect $2-5/month at normal use

## Files

- `manifest.json` — extension config
- `content.js` / `content.css` — injects Draft button + overlay on x.com
- `background.js` — service worker, makes LLM API calls
- `popup.html` / `popup.js` / `popup.css` — settings UI (API key, tone)
- `players_compact.json` — top-250 player context (regenerate with `build_context.py`)
- `icons/` — extension icons

## Troubleshooting

- **Button doesn't appear:** Reload the x.com tab after installing
- **"No API key set":** Open extension popup, paste key, click Save
- **"Anthropic 401":** Wrong key or expired. Create a new one.
- **"Anthropic 529":** API overloaded — hit Generate again
- **Drafts are too long:** Change tone to "casual" — they tend to be shorter
- **Drafts don't cite stats:** Player wasn't in top-250. That's expected for deep/fringe guys.
