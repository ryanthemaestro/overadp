#!/usr/bin/env python3
"""
Generate SEO hub-and-spoke pages from players.json + sleepers_busts.json.

Produces:
  site/2026/top-sleepers/index.html
  site/2026/top-busts/index.html
  site/2026/qb-rankings/index.html
  site/2026/rb-rankings/index.html
  site/2026/wr-rankings/index.html
  site/2026/te-rankings/index.html
  site/methodology/index.html
  site/sitemap.xml
  site/robots.txt

Run: python3 scripts/generate_hub_pages.py
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "app" / "data"
OUT = SITE / "2026"

GA_TAG = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-8GM0JH1DM4"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-8GM0JH1DM4');
</script>"""

BASE_CSS = """
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;}
:root{
  --bg:#05080a;--bg2:#0a0f13;--bg3:#0f1519;--bg4:#141c22;
  --fg:#eef1f5;--fg2:#b8c4d0;--fg3:#98a8b8;
  --green:#00ff6a;--green2:#00cc55;--red:#ff3344;--amber:#ffaa00;--blue:#3388ff;
  --mono:'IBM Plex Mono',monospace;--display:'Chakra Petch',sans-serif;--body:'Outfit',sans-serif;
  --grid:rgba(0,255,106,0.04);
}
html{scroll-behavior:smooth;overflow-x:hidden;}
body{background:var(--bg);color:var(--fg);font-family:var(--body);line-height:1.6;-webkit-font-smoothing:antialiased;}
body::before{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:60px 60px;}
.wrap{position:relative;z-index:1;max-width:1100px;margin:0 auto;padding:0 32px;}
nav{position:sticky;top:0;z-index:100;background:rgba(5,8,10,0.85);backdrop-filter:blur(12px);border-bottom:1px solid rgba(0,255,106,0.1);padding:16px 0;}
nav .wrap{display:flex;justify-content:space-between;align-items:center;}
nav a.logo{font-family:var(--display);font-weight:700;font-size:18px;letter-spacing:2px;color:var(--fg);text-decoration:none;}
nav a.logo span{color:var(--green);}
nav .links{display:flex;gap:24px;font-family:var(--mono);font-size:12px;}
nav .links a{color:var(--fg2);text-decoration:none;transition:color 0.2s;}
nav .links a:hover{color:var(--green);}
.nav-toggle{display:none;min-width:64px;min-height:44px;align-items:center;justify-content:center;padding:0 12px;background:var(--bg3);border:1px solid var(--fg3);border-radius:4px;color:var(--fg);font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;cursor:pointer;touch-action:manipulation;}
.nav-toggle:hover{border-color:var(--green);color:var(--green);}
.nav-toggle:focus-visible,nav a:focus-visible{outline:2px solid var(--green);outline-offset:3px;}
.btn{display:inline-block;padding:12px 24px;font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:1px;text-decoration:none;border-radius:3px;transition:all 0.2s;cursor:pointer;border:1px solid transparent;}
.btn-primary{background:var(--green);color:var(--bg);}
.btn-primary:hover{background:var(--green2);transform:translateY(-1px);}
.btn-ghost{background:transparent;border-color:var(--fg3);color:var(--fg);}
.btn-ghost:hover{border-color:var(--green);color:var(--green);}
main{padding:48px 0 96px;min-height:70vh;}
.section-tag{display:inline-block;font-family:var(--mono);font-size:10px;letter-spacing:3px;color:var(--green);text-transform:uppercase;margin-bottom:16px;padding:4px 12px;border:1px solid rgba(0,255,106,0.3);border-radius:2px;}
h1{font-family:var(--display);font-weight:700;font-size:clamp(32px,5vw,56px);line-height:1.1;letter-spacing:0.5px;margin-bottom:20px;}
h1 span.accent{color:var(--green);}
h2{font-family:var(--display);font-weight:600;font-size:clamp(22px,3vw,32px);margin:48px 0 20px;color:var(--fg);}
h3{font-family:var(--display);font-weight:600;font-size:20px;margin:24px 0 12px;color:var(--fg);}
.lead{color:var(--fg2);font-size:17px;line-height:1.7;margin-bottom:32px;max-width:780px;}
p{color:var(--fg2);margin-bottom:16px;line-height:1.7;}
a.inline{color:var(--green);text-decoration:underline;text-decoration-color:rgba(0,255,106,0.3);text-underline-offset:3px;}
a.inline:hover{text-decoration-color:var(--green);}
strong{color:var(--fg);}
.meta-strip{display:flex;flex-wrap:wrap;gap:16px;margin:24px 0;padding:12px 16px;background:var(--bg3);border:1px solid rgba(255,255,255,0.05);border-radius:3px;font-family:var(--mono);font-size:11px;color:var(--fg3);}
.meta-strip strong{color:var(--green);}
table.rank{width:100%;border-collapse:collapse;margin:24px 0;font-family:var(--mono);font-size:13px;}
table.rank th{text-align:left;padding:12px 10px;background:var(--bg3);color:var(--fg3);font-size:10px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid rgba(0,255,106,0.15);}
table.rank td{padding:12px 10px;border-bottom:1px solid rgba(255,255,255,0.05);color:var(--fg2);}
table.rank tr:hover td{background:rgba(0,255,106,0.02);}
table.rank td.rank{color:var(--green);font-weight:600;}
table.rank td.name{color:var(--fg);font-weight:500;}
table.rank td.positive{color:var(--green);}
table.rank td.negative{color:var(--red);}
table.rank td.warn{color:var(--amber);}
.verdict{display:inline-block;padding:2px 8px;font-size:10px;letter-spacing:1px;border-radius:2px;}
.verdict.sleeper{background:rgba(0,255,106,0.1);color:var(--green);border:1px solid rgba(0,255,106,0.3);}
.verdict.bust{background:rgba(255,51,68,0.1);color:var(--red);border:1px solid rgba(255,51,68,0.3);}
.verdict.risky{background:rgba(255,170,0,0.1);color:var(--amber);border:1px solid rgba(255,170,0,0.3);}
.verdict.safe{background:rgba(0,255,106,0.08);color:var(--green);border:1px solid rgba(0,255,106,0.25);}
.verdict.medium{background:rgba(184,196,208,0.06);color:var(--fg2);border:1px solid rgba(184,196,208,0.2);}
.callout{padding:20px 24px;background:linear-gradient(170deg,rgba(0,255,106,0.04),var(--bg3));border:1px solid rgba(0,255,106,0.15);border-radius:3px;margin:32px 0;}
.callout h3{margin-top:0;color:var(--green);}
.cta-block{margin:48px 0;padding:32px;background:linear-gradient(170deg,rgba(0,255,106,0.06),var(--bg3));border:1px solid rgba(0,255,106,0.2);border-radius:3px;text-align:center;}
.cta-block h2{margin-top:0;}
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin:24px 0;}
.card{padding:20px;background:var(--bg3);border:1px solid rgba(255,255,255,0.06);border-radius:3px;}
.card h4{font-family:var(--display);font-size:16px;color:var(--fg);margin-bottom:4px;}
.card .sub{font-family:var(--mono);font-size:10px;color:var(--fg3);margin-bottom:12px;letter-spacing:1px;}
.card .stat{font-family:var(--mono);font-size:12px;color:var(--fg2);margin:4px 0;}
.card .stat strong{color:var(--green);}
.card .reason{font-size:13px;color:var(--fg2);margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.05);line-height:1.5;}
.crumbs{font-family:var(--mono);font-size:11px;color:var(--fg3);margin-bottom:24px;}
.crumbs a{color:var(--fg3);text-decoration:none;}
.crumbs a:hover{color:var(--green);}
.related-hubs{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px;}
.related-hubs a{display:inline-block;padding:8px 14px;background:var(--bg3);border:1px solid rgba(255,255,255,0.08);border-radius:3px;font-family:var(--mono);font-size:11px;color:var(--fg2);text-decoration:none;transition:all 0.2s;}
.related-hubs a:hover{border-color:var(--green);color:var(--green);}
footer{padding:40px 0;border-top:1px solid rgba(255,255,255,0.05);font-family:var(--mono);font-size:11px;color:var(--fg3);text-align:center;}
footer a{color:var(--fg3);text-decoration:none;margin:0 8px;}
footer a:hover{color:var(--green);}
@media(max-width:760px){
  .wrap{padding-right:max(16px,env(safe-area-inset-right));padding-left:max(16px,env(safe-area-inset-left));}
  nav{padding:6px 0;}
  nav .wrap{min-height:44px;flex-wrap:wrap;}
  .nav-toggle{display:inline-flex;}
  nav .links{display:none;flex:0 0 100%;width:100%;padding-top:6px;flex-direction:column;gap:0;}
  nav .links.open{display:flex;}
  nav .links a{display:flex;align-items:center;min-height:44px;padding:0 2px;border-top:1px solid rgba(0,255,106,0.08);}
  nav .links a:last-child{color:var(--green);}
  main{padding-top:36px;}
  table.rank{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;overscroll-behavior-inline:contain;}
}
"""


def html_head(title: str, desc: str, path: str, schema_json: str = "") -> str:
    canonical = f"https://overadp.com{path}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{GA_TAG}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{canonical}">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>{BASE_CSS}</style>
{schema_json}
</head>
<body>
<nav><div class="wrap">
  <a href="/" class="logo">OVER<span>ADP</span></a>
  <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="hub-nav-links" onclick="toggleHubNav(this)">Menu</button>
  <div class="links" id="hub-nav-links">
    <a href="/2026/top-sleepers/">Sleepers</a>
    <a href="/2026/top-busts/">Busts</a>
    <a href="/2026/qb-rankings/">QB</a>
    <a href="/2026/rb-rankings/">RB</a>
    <a href="/2026/wr-rankings/">WR</a>
    <a href="/2026/te-rankings/">TE</a>
    <a href="/methodology/">Methodology</a>
    <a href="/app/" style="color:var(--green);">War Room →</a>
  </div>
</div></nav>
<script>
function toggleHubNav(button){{
  const links = document.getElementById('hub-nav-links');
  const isOpen = links.classList.toggle('open');
  button.setAttribute('aria-expanded', String(isOpen));
}}
</script>
<main><div class="wrap">
"""


def html_foot(related_pairs: list[tuple[str, str]] | None = None) -> str:
    related = ""
    if related_pairs:
        items = "".join(f'<a href="{h}">{t}</a>' for h, t in related_pairs)
        related = f"""<h3 style="margin-top:48px;">Related Rankings</h3><div class="related-hubs">{items}</div>"""

    cta = """
    <div class="cta-block">
      <div class="section-tag">The Draft Tool</div>
      <h2>Get the Full Model in Your Draft Room</h2>
      <p style="max-width:560px;margin:0 auto 24px;">Every projection, 80% confidence interval, risk tier, and sleeper/bust call — live, in a single-page draft command center. Free to browse. $6.99 for a single draft, $24.99 for the full season.</p>
      <a href="/app/" class="btn btn-primary">ENTER THE WAR ROOM →</a>
    </div>
    """

    today = datetime.now(UTC).strftime("%B %d, %Y")
    return f"""
    {related}
    {cta}
  </div></main>
<footer>
  <div>Updated {today} · Walk-forward validated through 2025 · <a href="/">Home</a> · <a href="/methodology/">Methodology</a> · <a href="/app/">Draft Tool</a> · <a href="/support/">Support</a> · <a href="mailto:overadp@gmail.com">overadp@gmail.com</a></div>
</footer>
</body>
</html>
"""


def load_data():
    players = json.load(open(DATA / "players.json"))
    sleepers_busts = json.load(open(DATA / "sleepers_busts.json"))
    try:
        accuracy = json.load(open(DATA / "accuracy.json"))
    except Exception:
        accuracy = {}
    return players, sleepers_busts, accuracy


def filter_active(players: list, min_proj: float = 20.0) -> list:
    """Filter to players likely relevant for 2026 drafts — non-zero projection and valid ADP or top projection."""
    out = []
    for p in players:
        proj = p.get("projected_points", 0) or 0
        adp = p.get("adp", 999) or 999
        if proj < min_proj:
            continue
        # Keep if either has ADP or is a top-projection player
        out.append(p)
    return out


def tier_verdict(p: dict) -> tuple[str, str]:
    """Return (verdict_class, verdict_text) based on model vs ADP + risk."""
    adp = p.get("adp", 999) or 999
    risk = (p.get("risk") or "medium").lower()
    # Need model rank to determine sleeper/bust — we approximate using projected_points rank later
    if risk == "low":
        return "safe", "LOW RISK"
    if risk == "high":
        return "risky", "HIGH RISK"
    return "", ""


def fmt_proj(p: dict) -> str:
    return f"{p.get('projected_points', 0):.1f}"


def fmt_adp(p: dict) -> str:
    adp = p.get("adp", 0) or 0
    if adp >= 200:
        return "—"
    return f"{adp:.0f}"


def fmt_ci(p: dict) -> str:
    lo = p.get("ci_low", 0) or 0
    hi = p.get("ci_high", 0) or 0
    return f"{lo:.0f}–{hi:.0f}"


def risk_badge(p: dict) -> str:
    r = (p.get("risk") or "medium").lower()
    cls = {"low": "safe", "medium": "medium", "high": "risky"}.get(r, "medium")
    label = {"low": "LOW", "medium": "MED", "high": "HIGH"}.get(r, "MED")
    return f'<span class="verdict {cls}">{label}</span>'


# =====================================================================
# Page builders
# =====================================================================


def build_position_ranking(
    players: list,
    accuracy: dict,
    position: str,
    limit: int,
    slug: str,
    title_pos: str,
) -> str:
    pos_players = [p for p in players if p.get("position") == position]
    pos_players.sort(key=lambda p: p.get("projected_points", 0) or 0, reverse=True)
    top = pos_players[:limit]

    # Build content
    rows = []
    for i, p in enumerate(top, 1):
        adp = p.get("adp", 999) or 999
        model_rank = i  # rank within position
        # Determine if model disagrees with ADP (rough)
        verdict = ""
        if adp < 200:
            # compute approx model overall rank vs adp overall rank — crude: use pts percentile
            pass
        adp_display = fmt_adp(p)
        proj = fmt_proj(p)
        ci = fmt_ci(p)
        rb = risk_badge(p)
        rows.append(f"""
<tr>
  <td class="rank">{title_pos}{i}</td>
  <td class="name">{p['player_name']}</td>
  <td>{p.get('team','')}</td>
  <td>{proj}</td>
  <td style="color:var(--fg3);">{ci}</td>
  <td>{adp_display}</td>
  <td>{rb}</td>
</tr>""")

    table = f"""
<table class="rank">
  <thead>
    <tr>
      <th>Rank</th>
      <th>Player</th>
      <th>Team</th>
      <th>Proj Pts</th>
      <th>80% CI</th>
      <th>ADP</th>
      <th>Risk</th>
    </tr>
  </thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""

    metric = accuracy.get(position, {})
    mae = float(metric.get("mae", 0))
    r2 = float(metric.get("r2", 0))
    n_players = int(metric.get("n_players", 0))
    intro = {
        "QB": "Quarterback scoring has a wider absolute error scale than the other positions, so the model is trained and reported separately.",
        "RB": "Running-back projections account for committee usage, prior workload, current depth context, injury history, and teammate competition.",
        "WR": "Wide-receiver projections use prior target volume, teammate competition, current depth context, and player-level career signals.",
        "TE": "Tight-end production is sparse and role-sensitive, so TE uses its own feature set and error profile.",
    }[position]
    intro += f" Across the 2024-2025 test folds, {position} posted <strong>{mae:.2f} MAE</strong> and <strong>{r2:.2f} R²</strong> over {n_players:,} player-season predictions."

    title_full = f"2026 Fantasy Football {title_pos} Rankings — Walk-Forward Validated Projections | OverADP"
    desc = f"Top {limit} 2026 fantasy football {position} rankings with 80%-target split-conformal ranges. Held-out 2024-2025 MAE: {mae:.2f}; R²: {r2:.2f}. Updated {datetime.now(UTC).strftime('%B %Y')}."

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"Article",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "dateModified":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/2026/{slug}/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 Rankings / {position}</div>
<div class="section-tag">2026 {title_pos} Rankings</div>
<h1>2026 Fantasy <span class="accent">{title_pos} Rankings</span></h1>
<p class="lead">The top {limit} {position}s for 2026 half-PPR leagues, ranked by projected fantasy points. Each projection includes a split-conformal range targeting 80% marginal coverage, calibrated on held-out 2025 rows. A target range is not a guarantee for an individual player.</p>

<div class="meta-strip">
  <span>📊 Model: <strong>position-specific CatBoost + split CQR</strong></span>
  <span>🎯 Point-model tests: <strong>2024 and 2025</strong></span>
  <span>📅 Scoring: <strong>half-PPR</strong></span>
  <span>🔄 Updated: <strong>{datetime.now(UTC).strftime('%B %d, %Y')}</strong></span>
</div>

<p>{intro}</p>

{table}

<div class="callout">
  <h3>How to read this table</h3>
  <p><strong>Proj Pts</strong>: half-PPR fantasy points the point model estimates over the full 2026 season. <strong>80% CI</strong>: a split-conformal range with an 80% marginal-coverage target, calibrated on 2025 rows. A wide range means more uncertainty. <strong>ADP</strong>: current half-PPR average draft position. <strong>Risk</strong>: relative interval width bucketed within position.</p>
</div>

<h2>How the results were measured</h2>
<p>The point model was trained only on earlier seasons and evaluated on the next season. The published metrics aggregate every eligible player row from the 2024 and 2025 test folds. An exact-cohort ADP-only check is directionally positive, but we withhold a market-beating percentage because the 2025 input is a preseason-rank proxy rather than true ADP.</p>
<p>The biggest gaps between model and ADP are surfaced on our <a class="inline" href="/2026/top-sleepers/">Top Sleepers</a> and <a class="inline" href="/2026/top-busts/">Top Busts</a> pages. The <a class="inline" href="/app/">full War Room</a> shows every player with filtering, VBD, scarcity, and draft-tracking.</p>
"""

    related = [
        ("/2026/qb-rankings/", "QB Rankings") if position != "QB" else None,
        ("/2026/rb-rankings/", "RB Rankings") if position != "RB" else None,
        ("/2026/wr-rankings/", "WR Rankings") if position != "WR" else None,
        ("/2026/te-rankings/", "TE Rankings") if position != "TE" else None,
        ("/2026/top-sleepers/", "Top Sleepers"),
        ("/2026/top-busts/", "Top Busts"),
        ("/methodology/", "Methodology"),
    ]
    related = [r for r in related if r]

    return html_head(title_full, desc, f"/2026/{slug}/", schema) + body + html_foot(related)


def build_sleepers_or_busts(sleepers_busts: list, kind: str) -> str:
    assert kind in ("SLEEPER", "BUST")
    filtered = [x for x in sleepers_busts if x.get("label") == kind]
    filtered.sort(key=lambda x: abs(x.get("adp_gap", 0) or 0), reverse=True)
    top = filtered[:15]

    is_sleeper = kind == "SLEEPER"
    verdict_cls = "sleeper" if is_sleeper else "bust"
    arrow = "▲" if is_sleeper else "▼"
    color = "green" if is_sleeper else "red"

    cards = []
    for p in top:
        gap = p.get("adp_gap", 0) or 0
        gap_display = f"+{int(abs(gap))} spots" if gap > 0 else f"−{int(abs(gap))} spots"
        pos = p.get("position", "")
        # Use positional rank if available (new format), fall back to overall rank
        if p.get("model_pos_rank"):
            rank_line = f"Model rank: <strong>{pos}{int(p['model_pos_rank'])}</strong>"
            adp_line  = f"ADP rank: <strong>{pos}{int(p['adp_pos_rank'])}</strong>"
        else:
            rank_line = f"Model rank: <strong>#{int(p.get('model_rank', 0))}</strong>"
            adp_line  = f"ADP rank: <strong>#{int(p.get('adp', 0))}</strong>"
        cards.append(f"""
<div class="card">
  <h4>{p['player_name']}</h4>
  <div class="sub">{pos} · {p.get('team','FA')} · <span class="verdict {verdict_cls}">{arrow} {kind}</span></div>
  <div class="stat">{rank_line}</div>
  <div class="stat">{adp_line}</div>
  <div class="stat">Projected pts: <strong>{p.get('projected_points', 0):.1f}</strong></div>
  <div class="stat" style="color:var(--{color});">Gap vs ADP: <strong style="color:var(--{color});">{gap_display}</strong></div>
  <div class="reason">{p.get('reason', '')}</div>
</div>""")

    if is_sleeper:
        title_full = "2026 Fantasy Football Sleepers — ML Model Calls vs ADP | OverADP"
        desc = "Top 2026 fantasy football sleeper candidates: players whose current model rank is meaningfully higher than current half-PPR ADP. Updated from the live projection board."
        intro_lead = "The 2026 players our model ranks <strong>above current ADP</strong>. These are model-vs-market disagreements to investigate, not promises that a player will outperform."
        proof_hed = "What this signal means"
        proof_body = """A sleeper label measures a current rank gap: the point model values the player more highly than the draft market does. It can surface changing roles, prior production, depth-chart movement, or a cheap price. It does not estimate a hit probability, and the model can be wrong — use the projection range, roster fit, and current news alongside the label."""
        slug = "top-sleepers"
    else:
        title_full = "2026 Fantasy Football Busts — Overvalued by ADP | OverADP"
        desc = "Top 2026 fantasy football bust candidates: players whose current model rank is meaningfully lower than current half-PPR ADP. Updated from the live projection board."
        intro_lead = "The 2026 players our model ranks <strong>below current ADP</strong>. These are prices to question, not declarations that a player will fail."
        proof_hed = "What this signal means"
        proof_body = """A bust label measures a current rank gap: the market price is richer than the model's production rank. That can reflect role competition, prior volume, age, depth context, or simply an aggressive draft price. It is not an injury forecast or a certainty — use the projection range and current team news before making a pick."""
        slug = "top-busts"

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"Article",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "dateModified":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/2026/{slug}/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 / {'Top Sleepers' if is_sleeper else 'Top Busts'}</div>
<div class="section-tag">{arrow} 2026 {'Sleepers' if is_sleeper else 'Busts'}</div>
<h1>2026 Fantasy <span class="accent">{'Sleepers' if is_sleeper else 'Busts'}</span> — Model vs ADP</h1>
<p class="lead">{intro_lead}</p>

<div class="meta-strip">
  <span>📊 Source: <strong>walk-forward ML projections</strong></span>
  <span>📅 Scoring: <strong>half-PPR</strong></span>
  <span>🎯 Signal: <strong>current model rank vs current ADP</strong></span>
  <span>🔄 Updated: <strong>{datetime.now(UTC).strftime('%B %d, %Y')}</strong></span>
</div>

<h2>The Top 15</h2>
<div class="card-grid">{''.join(cards)}</div>

<h2>{proof_hed}</h2>
<p>{proof_body}</p>
<p>Methodology is public — chronological point-model tests, split-conformal 80%-target ranges, and current depth-chart context. Read the full <a class="inline" href="/methodology/">model methodology</a> or open the <a class="inline" href="/app/">free draft board</a>.</p>

<div class="callout">
  <h3>How "sleeper" and "bust" are defined here</h3>
  <p>A <strong>sleeper</strong> is a player whose model rank is meaningfully higher than ADP rank — they're being drafted later than we think they should be. A <strong>bust</strong> is the opposite: drafted earlier than the model thinks is justified. We rank by the absolute size of the gap. Players with no ADP (undrafted) are excluded.</p>
</div>
"""

    related = [
        ("/2026/top-sleepers/", "Top Sleepers") if not is_sleeper else ("/2026/top-busts/", "Top Busts"),
        ("/2026/qb-rankings/", "QB Rankings"),
        ("/2026/rb-rankings/", "RB Rankings"),
        ("/2026/wr-rankings/", "WR Rankings"),
        ("/2026/te-rankings/", "TE Rankings"),
        ("/methodology/", "Methodology"),
    ]

    return html_head(title_full, desc, f"/2026/{slug}/", schema) + body + html_foot(related)


def build_methodology(accuracy: dict) -> str:
    title_full = "Methodology — How OverADP's Walk-Forward Fantasy Football Model Works | OverADP"
    desc = "How OverADP projects fantasy football: chronological walk-forward testing, position-specific CatBoost models, split-conformal 80%-target ranges, current depth-chart context, and published limitations."

    metric_rows = []
    total_n = 0
    weighted_mae = 0.0
    weighted_rmse_sq = 0.0
    weighted_r2 = 0.0
    test_seasons = set()
    for pos in ("QB", "RB", "WR", "TE"):
        metric = accuracy.get(pos, {})
        n = int(metric.get("n_players", 0))
        mae = float(metric.get("mae", 0))
        rmse = float(metric.get("rmse", 0))
        r2 = float(metric.get("r2", 0))
        total_n += n
        weighted_mae += mae * n
        weighted_rmse_sq += rmse * rmse * n
        weighted_r2 += r2 * n
        test_seasons.update(metric.get("test_seasons", []))
        metric_rows.append(
            f'<tr><td>{pos}</td><td class="positive">{mae:.2f}</td>'
            f'<td>{rmse:.2f}</td><td class="positive">{r2:.2f}</td><td>{n:,}</td></tr>'
        )
    if total_n:
        weighted_mae /= total_n
        weighted_rmse = (weighted_rmse_sq / total_n) ** 0.5
        weighted_r2 /= total_n
    else:
        weighted_rmse = 0.0
    metric_rows.append(
        f'<tr><td><strong>Player-weighted summary</strong></td>'
        f'<td class="positive">{weighted_mae:.2f}</td><td>{weighted_rmse:.2f}</td>'
        f'<td class="positive">{weighted_r2:.2f}</td><td>{total_n:,}</td></tr>'
    )
    metric_table_rows = "".join(metric_rows)
    test_season_label = ", ".join(str(s) for s in sorted(test_seasons))

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"TechArticle",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "dateModified":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/methodology/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / Methodology</div>
<div class="section-tag">Transparency</div>
<h1>How the <span class="accent">Model</span> Works</h1>
<p class="lead">A full technical breakdown of OverADP's machine-learning pipeline — how we project fantasy points, how we quantify uncertainty, and how we validate without leaking future information into the past.</p>

<h2>The one-sentence version</h2>
<p>We train one CatBoost point model per position on completed NFL seasons, test it chronologically on the next season, and pair the point estimate with a separate split-conformal quantile range targeting 80% marginal coverage.</p>

<h2>1. Walk-forward validation (not random splits)</h2>
<p>Fantasy football data is temporal: player stats in 2023 are <em>not</em> independent of stats in 2022. A standard 80/20 random train-test split would leak future information — the model would see a player's 2024 season during training and then be "tested" on his 2025 season, but it already knows the player's career trajectory.</p>
<p>Walk-forward validation prevents this. The published point-model results use two folds: train through 2023 and test on 2024, then train through 2024 and test on 2025. The aggregate includes every eligible QB/RB/WR/TE row in those folds.</p>

<h2>2. One CatBoost model per position</h2>
<p>QB, RB, WR, and TE are trained separately because their production scales and useful features differ. The production point model is CatBoost for all four positions, with position-specific feature lists and temporal sample weighting so newer training seasons matter more.</p>

<h2>3. Conformal quantile regression (CQR) for honest 80% intervals</h2>
<p>Point predictions alone are dangerous in fantasy — every projection is wrong, the question is <em>by how much</em>. We train separate quantile CatBoost models at the 10th and 90th percentiles, then calibrate on the most recent held-out season using split-conformal CQR.</p>
<p>The final adjustment is learned from 2025 calibration rows and targets <strong>80% marginal coverage</strong>. Because that same season is used for final calibration, its post-adjustment coverage is a calibration diagnostic, not an independent test-set guarantee. Coverage for an individual player is never guaranteed.</p>

<h2>4. Depth-chart awareness (Week 1 snapshot)</h2>
<p>One of our biggest 2026 feature additions. We pull pre-season depth charts from nflverse (Week 1 snapshot for 2019-2024; nearest-to-September-5 snapshot for 2025+) and encode each player's depth rank (1=starter, 2=backup, 3+=depth), plus binary is_starter and is_backup flags.</p>
<p>Used for QB, WR, and TE projections. Excluded from RB because RBBC (running-back-by-committee) makes a nominal depth rank less reliable than actual prior workload and teammate carry competition.</p>

<h2>5. Target-competition features (prevent phantom breakouts)</h2>
<p>Using prior-season teammate targets, we compute each WR's teammate_targets_prev and teammate_rec_yards_prev on their <em>current</em> team (so if Chase Claypool signs with the Jaguars, his projections reflect BTJ's 200+ targets ahead of him). We also compute teammate_carries_prev for RBs.</p>
<p>The feature uses prior-season teammate production on the current roster, never the target season's outcomes. This re-runs after free-agent and draft changes are reflected in the projection-season roster.</p>

<h2>6. Conservative monotonic constraints</h2>
<p>Aggregate production lags (prior-season fantasy points, targets, receptions, carries) should never have a <em>negative</em> marginal effect on projections. We encode positive monotonic constraints on exactly these features and leave everything else unconstrained. This adds sanity guardrails without overfitting — MAE stays within noise, but the model can't produce pathological projections where scoring more the prior year makes you project lower.</p>

<h2>7. College + draft capital features for rookies</h2>
<p>For rookies and second-year players, we merge draft picks, combine metrics, college production, and interaction features (college_x_rookie, draft_cap_x_rookie, athletic_x_rookie). Athletic score is a position-weighted composite of combine z-scores. These features give the model signal before an NFL stat line exists.</p>

<h2>The {test_season_label} walk-forward results</h2>
<p>All numbers below are aggregated from the exported validation results and weighted by the number of player-season predictions in each fold. The exact-cohort market check uses true FFC ADP in 2024 but an explicitly labeled ESPN preseason-rank proxy in 2025, so no ADP improvement percentage is published here.</p>
<table class="rank">
  <thead><tr><th>Position</th><th>MAE</th><th>RMSE</th><th>R²</th><th>Held-Out N</th></tr></thead>
  <tbody>{metric_table_rows}</tbody>
</table>

<h2>What the model doesn't do</h2>
<p>Honest limitations:</p>
<p><strong>It can't predict injuries.</strong> Malik Nabers finishing 2025 with 4 games played wasn't a model call — it was a bone bruise. We DO model injury rates from prior-season games-missed features, but week-to-week injuries are noise.</p>
<p><strong>It's only as good as the data.</strong> UDFAs and late-round rookies with missing college data get wider intervals and lower confidence. Coaching-change features were tested and rejected after walk-forward validation showed them adding noise rather than signal.</p>
<p><strong>Fantasy football is high-variance.</strong> Even a strong aggregate model misses individual players. The interval pipeline targets 80% marginal coverage after calibration, but that target is not a player-level promise and still needs monitoring on future untouched seasons.</p>

<h2>What's next</h2>
<p>Roster, depth-chart, ADP, and rookie inputs continue to change through training camp. We refresh the board as those sources stabilize and will report interval coverage again only after a future season remains untouched through evaluation.</p>
<p>See the current results in <a class="inline" href="/app/">the free War Room</a>, or dive into the <a class="inline" href="/2026/top-sleepers/">top sleepers</a> and <a class="inline" href="/2026/top-busts/">top busts</a>.</p>
"""

    related = [
        ("/2026/top-sleepers/", "Top Sleepers"),
        ("/2026/top-busts/", "Top Busts"),
        ("/2026/qb-rankings/", "QB Rankings"),
        ("/2026/rb-rankings/", "RB Rankings"),
        ("/2026/wr-rankings/", "WR Rankings"),
        ("/2026/te-rankings/", "TE Rankings"),
    ]

    return html_head(title_full, desc, "/methodology/", schema) + body + html_foot(related)


def build_sitemap(pages: list[str]) -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    urls = []
    urls.append(f"""  <url><loc>https://overadp.com/</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>""")
    urls.append(f"""  <url><loc>https://overadp.com/app/</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.9</priority></url>""")
    for p in pages:
        urls.append(f"""  <url><loc>https://overadp.com{p}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.8</priority></url>""")
    joined = "\n".join(urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{joined}
</urlset>
"""


def build_robots() -> str:
    return """User-agent: *
Allow: /
Disallow: /app/data/
Disallow: /.netlify/

Sitemap: https://overadp.com/sitemap.xml
"""


def write_page(relpath: str, html: str):
    out = SITE / relpath.lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"  wrote {relpath}  ({len(html):,} bytes)")


def main():
    print("Loading data...")
    players, sleepers_busts, accuracy = load_data()
    active = filter_active(players)
    print(f"  {len(active)} active players, {len(sleepers_busts)} sleepers/busts entries")

    print("Generating hub pages...")
    write_page("2026/qb-rankings/index.html", build_position_ranking(active, accuracy, "QB", 32, "qb-rankings", "QB"))
    write_page("2026/rb-rankings/index.html", build_position_ranking(active, accuracy, "RB", 50, "rb-rankings", "RB"))
    write_page("2026/wr-rankings/index.html", build_position_ranking(active, accuracy, "WR", 60, "wr-rankings", "WR"))
    write_page("2026/te-rankings/index.html", build_position_ranking(active, accuracy, "TE", 24, "te-rankings", "TE"))
    write_page("2026/top-sleepers/index.html", build_sleepers_or_busts(sleepers_busts, "SLEEPER"))
    write_page("2026/top-busts/index.html", build_sleepers_or_busts(sleepers_busts, "BUST"))
    write_page("methodology/index.html", build_methodology(accuracy))

    print("Generating sitemap + robots.txt...")
    pages = [
        "/2026/qb-rankings/",
        "/2026/rb-rankings/",
        "/2026/wr-rankings/",
        "/2026/te-rankings/",
        "/2026/top-sleepers/",
        "/2026/top-busts/",
        "/methodology/",
        "/support/",
        "/draft-assistant/",
    ]
    (SITE / "sitemap.xml").write_text(build_sitemap(pages))
    print(f"  wrote /sitemap.xml ({len(pages)+2} URLs)")
    (SITE / "robots.txt").write_text(build_robots())
    print(f"  wrote /robots.txt")

    print(f"\n✓ Done. 7 hub pages + sitemap + robots.txt generated.")
    print(f"  Submit sitemap to Search Console: https://overadp.com/sitemap.xml")


if __name__ == "__main__":
    main()
