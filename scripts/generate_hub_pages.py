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
.answer-block{padding:22px 24px;margin:28px 0;background:linear-gradient(160deg,rgba(0,255,106,.075),var(--bg3));border:1px solid rgba(0,255,106,.25);border-left:4px solid var(--green);border-radius:3px;max-width:900px;}
.answer-block .answer-label{display:block;margin-bottom:8px;color:var(--green);font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:2px;text-transform:uppercase;}
.answer-block p{margin:0;color:var(--fg);font-size:17px;}
.byline{display:flex;flex-wrap:wrap;gap:8px 18px;margin:18px 0 28px;color:var(--fg3);font-family:var(--mono);font-size:11px;}
.compare-tool{margin:34px 0;padding:28px;background:var(--bg3);border:1px solid rgba(0,255,106,.22);border-radius:4px;}
.compare-selects{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:end;}
.compare-selects label{display:block;color:var(--fg2);font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;}
.compare-selects select{width:100%;min-height:48px;margin-top:7px;padding:0 12px;background:var(--bg);border:1px solid var(--fg3);border-radius:3px;color:var(--fg);font:14px var(--body);}
.compare-vs{padding-bottom:14px;color:var(--green);font:700 12px var(--mono);}
.compare-result{display:none;margin-top:24px;padding-top:24px;border-top:1px solid rgba(255,255,255,.08);}
.compare-result.active{display:block;}
.verdict-line{font-family:var(--display);font-size:clamp(24px,4vw,38px);font-weight:700;line-height:1.15;color:var(--fg);}
.verdict-line span{color:var(--green);}
.comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:20px;}
.player-panel{padding:20px;background:var(--bg);border:1px solid rgba(255,255,255,.08);border-radius:3px;}
.player-panel.winner{border-color:var(--green);box-shadow:0 0 24px rgba(0,255,106,.08);}
.player-panel h3{margin:0 0 4px;}
.player-meta{color:var(--fg3);font:11px var(--mono);}
.metric-row{display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.06);color:var(--fg2);font-size:14px;}
.metric-row strong{font-family:var(--mono);}
.evidence-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:28px 0;}
.evidence-card{padding:24px;background:var(--bg3);border:1px solid rgba(255,255,255,.07);border-radius:3px;}
.evidence-card.primary{border-color:rgba(0,255,106,.35);background:linear-gradient(160deg,rgba(0,255,106,.07),var(--bg3));}
.evidence-number{color:var(--green);font:700 clamp(30px,4vw,46px) var(--display);line-height:1;}
.evidence-label{margin-top:10px;color:var(--fg2);font-size:14px;line-height:1.45;}
.bar-compare{margin:30px 0;padding:24px;background:var(--bg3);border:1px solid rgba(255,255,255,.07);}
.bar-row{display:grid;grid-template-columns:130px 1fr 58px;gap:12px;align-items:center;margin:16px 0;}
.bar-label{color:var(--fg2);font:12px var(--mono);}
.bar-track{height:18px;background:var(--bg);border-radius:999px;overflow:hidden;}
.bar-fill{display:block;height:100%;background:#66737d;border-radius:inherit;}
.bar-fill.green{background:var(--green);}
.bar-value{font:700 14px var(--mono);text-align:right;}
.research-table{width:100%;border-collapse:collapse;margin:26px 0;font-size:14px;}
.research-table th,.research-table td{padding:13px 12px;border-bottom:1px solid rgba(255,255,255,.07);text-align:left;}
.research-table th{color:var(--fg3);font:10px var(--mono);letter-spacing:1px;text-transform:uppercase;background:var(--bg3);}
.research-table td{color:var(--fg2);}
.research-table td strong{color:var(--green);}
.fine-print{color:var(--fg3);font-size:12px;line-height:1.6;}
.faq-list details{padding:18px 0;border-top:1px solid rgba(255,255,255,.08);}
.faq-list details:last-child{border-bottom:1px solid rgba(255,255,255,.08);}
.faq-list summary{cursor:pointer;color:var(--fg);font-weight:600;}
.faq-list details p{margin:10px 0 0;}
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
  .compare-selects{grid-template-columns:1fr;}.compare-vs{padding:0;text-align:center;}.comparison-grid,.evidence-grid{grid-template-columns:1fr;}.compare-tool{padding:20px 16px;}.bar-row{grid-template-columns:92px 1fr 48px;gap:8px;}
  .research-table{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;}
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
    <a href="/2026/who-should-i-draft/">Who to Draft</a>
    <a href="/2026/adp-vs-model/">ADP Study</a>
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
      <p style="max-width:560px;margin:0 auto 24px;">Every projection, 80%-target range, risk tier, and sleeper/bust call, live, in a single-page draft command center. Free to browse. Unlock one complete draft for $6.99 with no subscription.</p>
      <a href="/app/" class="btn btn-primary">ENTER THE WAR ROOM →</a>
    </div>
    """

    today = datetime.now(UTC).strftime("%B %d, %Y")
    return f"""
    {related}
    {cta}
  </div></main>
<footer>
  <div>Updated {today} · Walk-forward validated through 2025 · <a href="/">Home</a> · <a href="/2026/who-should-i-draft/">Who Should I Draft?</a> · <a href="/2026/adp-vs-model/">ADP Study</a> · <a href="/methodology/">Methodology</a> · <a href="/app/">Draft Tool</a> · <a href="/support/">Support</a> · <a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a> · <a href="/refunds/">Refunds</a> · <a href="mailto:overadp@gmail.com">overadp@gmail.com</a></div>
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
    """Filter to players likely relevant for 2026 drafts: non-zero projection and valid ADP or top projection."""
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
    # Need model rank to determine sleeper/bust; we approximate using projected_points rank later
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
        return "-"
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
            # compute approx model overall rank vs adp overall rank (crude): use pts percentile
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

    title_full = f"2026 Fantasy Football {title_pos} Rankings: Walk-Forward Validated Projections | OverADP"
    desc = f"Top {limit} 2026 fantasy football {position} rankings with 80% ranges. Held-out 2024-2025 MAE: {mae:.2f}; R²: {r2:.2f}. Updated {datetime.now(UTC).strftime('%B %Y')}."

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"Article",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"2026-07-20",
  "dateModified":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/2026/{slug}/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 Rankings / {position}</div>
<div class="section-tag">2026 {title_pos} Rankings</div>
<h1>2026 Fantasy <span class="accent">{title_pos} Rankings</span></h1>
<p class="lead">The top {limit} {position}s for 2026 half-PPR leagues, ranked by projected fantasy points. Each projection includes an 80% range built from how far past projections missed. A target range is not a guarantee for an individual player.</p>
<div class="answer-block"><span class="answer-label">Quick answer</span><p>These rankings order 2026 {position}s by OverADP's projection (model blended with ADP), then show current ADP and uncertainty beside every player. Use the projection as an independent estimate, the range as risk context, and ADP as market price, not as three interchangeable rankings.</p></div>
<div class="byline"><span>By OverADP Research</span><span>Updated {datetime.now(UTC).strftime('%B %d, %Y')}</span><span>Half-PPR</span></div>

<div class="meta-strip">
  <span>📊 Model: <strong>v6 + ADP blend</strong></span>
  <span>🎯 Point-model tests: <strong>2024 and 2025</strong></span>
  <span>📅 Scoring: <strong>half-PPR</strong></span>
  <span>🔄 Updated: <strong>{datetime.now(UTC).strftime('%B %d, %Y')}</strong></span>
</div>

<p>{intro}</p>

{table}

<div class="callout">
  <h3>How to read this table</h3>
  <p><strong>Proj Pts</strong>: half-PPR fantasy points the point model estimates over the full 2026 season. <strong>80% CI</strong>: the range that past projections at this level hit about 80% of the time. A wide range means more uncertainty. <strong>ADP</strong>: current half-PPR average draft position. <strong>Risk</strong>: relative interval width bucketed within position.</p>
</div>

<h2>How the results were measured</h2>
<p>The point model was trained only on earlier seasons and evaluated on the next season. The published metrics aggregate every eligible player row from the 2024 and 2025 test folds. Projections blend the model 50/50 with ADP-implied points, the combination that tested best on 2019 to 2025, and are shown next to current ADP.</p>
<p>The biggest gaps between model and ADP are surfaced on our <a class="inline" href="/2026/top-sleepers/">Top Sleepers</a> and <a class="inline" href="/2026/top-busts/">Top Busts</a> pages. The <a class="inline" href="/app/">full War Room</a> shows every player with filtering, VBD, scarcity, and draft-tracking.</p>
"""

    related = [
        ("/2026/qb-rankings/", "QB Rankings") if position != "QB" else None,
        ("/2026/rb-rankings/", "RB Rankings") if position != "RB" else None,
        ("/2026/wr-rankings/", "WR Rankings") if position != "WR" else None,
        ("/2026/te-rankings/", "TE Rankings") if position != "TE" else None,
        ("/2026/top-sleepers/", "Top Sleepers"),
        ("/2026/top-busts/", "Top Busts"),
        ("/2026/who-should-i-draft/", "Who Should I Draft?"),
        ("/2026/adp-vs-model/", "ADP vs Model Study"),
        ("/methodology/", "Methodology"),
    ]
    related = [r for r in related if r]

    return html_head(title_full, desc, f"/2026/{slug}/", schema) + body + html_foot(related)


def gap_text(reason: str) -> str:
    """Describe a rank gap neutrally instead of asserting a player is under/overvalued."""
    import re
    reason = re.sub(r"\(undervalued by (\d+) spots\)", r"(model ranks him \1 spots higher)", reason)
    return re.sub(r"\(overvalued by (\d+) spots\)", r"(model ranks him \1 spots lower)", reason)


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
  <div class="reason">{gap_text(p.get('reason', ''))}</div>
</div>""")

    if is_sleeper:
        title_full = "2026 Fantasy Football Sleepers: Model vs ADP Price Gaps | OverADP"
        desc = "Top 2026 fantasy football sleeper candidates: players whose current model rank is meaningfully higher than current half-PPR ADP. Updated from the live projection board."
        intro_lead = "The 2026 players our model ranks <strong>above current ADP</strong>. These are model-vs-market disagreements to investigate, not promises that a player will outperform."
        proof_hed = "What this signal means"
        proof_body = """A sleeper label measures a current rank gap: the point model values the player more highly than the draft market does. It can surface changing roles, prior production, depth-chart movement, or a cheap price. It does not estimate a hit probability, and the model can be wrong. Use the projection range, roster fit, and current news alongside the label."""
        slug = "top-sleepers"
    else:
        title_full = "2026 Fantasy Football Busts: Model vs ADP Price Gaps | OverADP"
        desc = "Top 2026 fantasy football bust candidates: players whose current model rank is meaningfully lower than current half-PPR ADP. Updated from the live projection board."
        intro_lead = "The 2026 players our model ranks <strong>below current ADP</strong>. These are prices to question, not declarations that a player will fail."
        proof_hed = "What this signal means"
        proof_body = """A bust label measures a current rank gap: the market price is richer than the model's production rank. That can reflect role competition, prior volume, age, depth context, or simply an aggressive draft price. It is not an injury forecast or a certainty. Use the projection range and current team news before making a pick."""
        slug = "top-busts"

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"Article",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"2026-07-20",
  "dateModified":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/2026/{slug}/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 / {'Top Sleepers' if is_sleeper else 'Top Busts'}</div>
<div class="section-tag">{arrow} 2026 {'Sleepers' if is_sleeper else 'Busts'}</div>
<h1>2026 Fantasy <span class="accent">{'Sleepers' if is_sleeper else 'Busts'}</span>: Model vs ADP</h1>
<p class="lead">{intro_lead}</p>
<div class="answer-block"><span class="answer-label">Quick answer</span><p>{'A 2026 sleeper is a player the current OverADP model ranks materially above the draft market. The gap can reveal an inexpensive path to production, but it is a research signal, not a hit guarantee. Check the player range, current news, roster fit, and the cost of waiting.' if is_sleeper else 'A 2026 bust candidate is a player whose current ADP is materially earlier than the OverADP model rank. That means the market price looks aggressive relative to the projection; it does not mean the player is certain to fail or should never be drafted.'}</p></div>
<div class="byline"><span>By OverADP Research</span><span>Updated {datetime.now(UTC).strftime('%B %d, %Y')}</span><span>Half-PPR</span></div>

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
<p>Methodology is public: season-by-season tests, 80% ranges, and current depth-chart context. Read the full <a class="inline" href="/methodology/">model methodology</a> or open the <a class="inline" href="/app/">free draft board</a>.</p>

<div class="callout">
  <h3>How "sleeper" and "bust" are defined here</h3>
  <p>A <strong>sleeper</strong> is a player whose model rank is meaningfully higher than ADP rank: they're being drafted later than we think they should be. A <strong>bust</strong> is the opposite: drafted earlier than the model thinks is justified. We rank by the absolute size of the gap. Players with no ADP (undrafted) are excluded.</p>
</div>
"""

    related = [
        ("/2026/top-sleepers/", "Top Sleepers") if not is_sleeper else ("/2026/top-busts/", "Top Busts"),
        ("/2026/qb-rankings/", "QB Rankings"),
        ("/2026/rb-rankings/", "RB Rankings"),
        ("/2026/wr-rankings/", "WR Rankings"),
        ("/2026/te-rankings/", "TE Rankings"),
        ("/2026/who-should-i-draft/", "Who Should I Draft?"),
        ("/2026/adp-vs-model/", "ADP vs Model Study"),
        ("/methodology/", "Methodology"),
    ]

    return html_head(title_full, desc, f"/2026/{slug}/", schema) + body + html_foot(related)


def comparison_score(player: dict) -> float:
    """Roster-neutral comparison score. Target Intel adds live roster context in the app."""
    risk_penalty = {"low": 0.0, "medium": 7.0, "high": 14.0}.get((player.get("risk") or "medium").lower(), 7.0)
    adp = float(player.get("adp") or 200)
    return float(player.get("vbd") or 0) + 0.08 * float(player.get("projected_points") or 0) + 0.12 * max(0, 80 - adp) - risk_penalty


def build_who_should_i_draft(players: list) -> str:
    eligible = [
        p for p in players
        if p.get("position") in {"QB", "RB", "WR", "TE"}
        and float(p.get("adp") or 999) < 200
        and float(p.get("projected_points") or 0) > 0
    ]
    eligible.sort(key=lambda p: (float(p.get("adp") or 999), p.get("player_name", "")))

    compact = [
        {
            "name": p.get("player_name"),
            "position": p.get("position"),
            "team": p.get("team") or "FA",
            "projection": round(float(p.get("projected_points") or 0), 1),
            "low": round(float(p.get("ci_low") or 0), 1),
            "high": round(float(p.get("ci_high") or 0), 1),
            "adp": round(float(p.get("adp") or 200), 1),
            "vbd": round(float(p.get("vbd") or 0), 1),
            "risk": (p.get("risk") or "medium").lower(),
            "bye": p.get("bye") or "-",
        }
        for p in eligible
    ]
    player_json = json.dumps(compact, separators=(",", ":")).replace("</", "<\\/")
    options = "".join(
        f'<option value="{i}">{p["name"]} ({p["position"]}, {p["team"]})</option>'
        for i, p in enumerate(compact)
    )

    index_by_name = {p["name"]: i for i, p in enumerate(compact)}
    popular_pairs = [
        ("Jahmyr Gibbs", "Bijan Robinson"),
        ("Puka Nacua", "Ja'Marr Chase"),
        ("Jonathan Taylor", "Christian McCaffrey"),
        ("Drake London", "De'Von Achane"),
    ]
    popular_cards = []
    for left_name, right_name in popular_pairs:
        if left_name not in index_by_name or right_name not in index_by_name:
            continue
        left = eligible[index_by_name[left_name]]
        right = eligible[index_by_name[right_name]]
        winner = left if comparison_score(left) >= comparison_score(right) else right
        popular_cards.append(
            f'<article class="card"><h4>{left_name} vs {right_name}</h4>'
            f'<div class="sub">CURRENT 2026 MODEL LEAN</div>'
            f'<p class="reason"><strong>{winner["player_name"]}</strong> has the stronger roster-neutral value signal today. '
            'Your live roster and the chance each player returns can change the pick.</p></article>'
        )

    title = "Who Should I Draft in 2026? Fantasy Player Comparison | OverADP"
    desc = "Compare two 2026 fantasy football players by projection, value above replacement, ADP, risk range and bye week, then get a roster-aware live recommendation."
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    display_date = datetime.now(UTC).strftime("%B %d, %Y")
    schema = f"""<script type="application/ld+json">
[
  {{"@context":"https://schema.org","@type":"WebApplication","name":"OverADP Who Should I Draft?","url":"https://overadp.com/2026/who-should-i-draft/","applicationCategory":"SportsApplication","operatingSystem":"Web","description":"{desc}","dateModified":"{today}","offers":{{"@type":"Offer","price":"0","priceCurrency":"USD"}}}},
  {{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
    {{"@type":"Question","name":"Who should I draft in fantasy football?","acceptedAnswer":{{"@type":"Answer","text":"Compare players by value above replacement, projection, draft cost, uncertainty and roster fit. OverADP uses ADP as market price, then adds model projections and live roster context to identify who helps now and who may be safe to wait on."}}}},
    {{"@type":"Question","name":"Should I draft the highest projected player?","acceptedAnswer":{{"@type":"Answer","text":"Not automatically. Raw projected points are not directly comparable across positions. Value above replacement, roster needs, positional scarcity, ADP cost and next-turn availability can make a lower raw projection the better pick."}}}},
    {{"@type":"Question","name":"Is ADP the same as a fantasy football ranking?","acceptedAnswer":{{"@type":"Answer","text":"No. ADP describes where players are being selected by the market. A projection estimates production. OverADP treats ADP as price and combines it with model value and roster context rather than treating it as the answer."}}}}
  ]}}
]
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 / Who Should I Draft?</div>
<div class="section-tag">Free 2026 Player Comparison</div>
<h1>Who Should I <span class="accent">Draft?</span></h1>
<p class="lead">Compare any two current 2026 players by projection, value above replacement, ADP, uncertainty and risk. Then bring the decision into the War Room for the roster-aware answer.</p>
<div class="answer-block"><span class="answer-label">The short answer</span><p>Draft the player who gives your roster the most value at the current pick, not simply the first name on ADP or the highest raw projection. Start with value above replacement, check the uncertainty range and market cost, then account for roster needs and whether the alternative is likely to survive until your next turn.</p></div>
<div class="byline"><span>By OverADP Research</span><span>Updated {display_date}</span><span>Current half-PPR board</span></div>

<section class="compare-tool" aria-labelledby="compare-heading">
  <h2 id="compare-heading" style="margin-top:0;">Compare two players</h2>
  <div class="compare-selects">
    <label>Player one<select id="player-one">{options}</select></label>
    <div class="compare-vs">VS</div>
    <label>Player two<select id="player-two">{options}</select></label>
  </div>
  <div id="compare-result" class="compare-result" aria-live="polite"></div>
</section>

<div class="callout">
  <h3>This is a roster-neutral comparison</h3>
  <p>The free comparator weighs position-adjusted value, projection, draft urgency and range risk. It cannot see the roster you are building. <a class="inline" href="/app/?utm_source=who_should_i_draft&utm_medium=organic&utm_campaign=2026_tools">Target Intel in the War Room</a> recalculates after every pick using starter holes, flex paths, scarcity and the chance a player returns.</p>
</div>

<h2>Popular 2026 draft comparisons</h2>
<div class="card-grid">{''.join(popular_cards)}</div>

<h2>What matters when choosing between two players?</h2>
<div class="card-grid">
  <article class="card"><h4>Value above replacement</h4><div class="sub">COMPARE ACROSS POSITIONS</div><p class="reason">VBD estimates how many points a player adds over a usable option at the same position. It is more useful than raw points when comparing an RB to a WR or TE.</p></article>
  <article class="card"><h4>ADP as price</h4><div class="sub">DON'T CONFUSE COST WITH VALUE</div><p class="reason">An early ADP means the room usually pays more. It does not prove the player will score more or fit your roster better.</p></article>
  <article class="card"><h4>Range and risk</h4><div class="sub">AVOID FAKE CERTAINTY</div><p class="reason">Two players can have similar point estimates but very different outcome ranges. The wider range deserves more caution when your roster already carries volatility.</p></article>
  <article class="card"><h4>Next-turn availability</h4><div class="sub">WHO CAN WAIT?</div><p class="reason">The best value can still be the wrong current pick if the player is likely to return and the alternative is about to disappear.</p></article>
</div>

<h2>Frequently asked questions</h2>
<div class="faq-list">
  <details><summary>Who should I draft in fantasy football?</summary><p>Use value above replacement to compare positions, then consider projection, uncertainty, roster construction and draft cost. A live recommendation should also estimate whether each player can survive until your next selection.</p></details>
  <details><summary>Should I draft the highest projected player?</summary><p>Not automatically. Quarterbacks often score more raw points than other positions, but that does not make every quarterback the best early pick. Compare each player with the replacement level at his position and with what your roster still needs.</p></details>
  <details><summary>Is ADP the same as a ranking?</summary><p>No. ADP measures market behavior. A model ranking estimates value. OverADP uses both: ADP describes the price and urgency, while the model and roster state help decide whether that price is worth paying.</p></details>
</div>

<script>
const comparisonPlayers={player_json};
const riskPenalty={{low:0,medium:7,high:14}};
function valueScore(p){{return p.vbd+(p.projection*.08)+(Math.max(0,80-p.adp)*.12)-(riskPenalty[p.risk]??7);}}
function metric(label,value){{return `<div class="metric-row"><span>${{label}}</span><strong>${{value}}</strong></div>`;}}
function panel(p,winner){{return `<article class="player-panel ${{winner?'winner':''}}"><h3>${{p.name}}</h3><div class="player-meta">${{p.position}} · ${{p.team}} · BYE ${{p.bye}}</div>${{metric('Projection',p.projection+' pts')}}${{metric('80% target range',p.low+'–'+p.high)}}${{metric('Value above replacement',p.vbd)}}${{metric('Current ADP',p.adp)}}${{metric('Range risk',p.risk.toUpperCase())}}</article>`;}}
function renderComparison(){{
  const one=comparisonPlayers[Number(document.getElementById('player-one').value)];
  const two=comparisonPlayers[Number(document.getElementById('player-two').value)];
  if(!one||!two)return;
  const scoreOne=valueScore(one),scoreTwo=valueScore(two);
  const winner=scoreOne>=scoreTwo?one:two;
  const close=Math.abs(scoreOne-scoreTwo)<8;
  const reason=winner.vbd===Math.max(one.vbd,two.vbd)?'stronger position-adjusted value':'better balance of value, projection, cost and range risk';
  const result=document.getElementById('compare-result');
  result.className='compare-result active';
  result.innerHTML=`<div class="verdict-line">${{close?'Slight model lean:':'Roster-neutral lean:'}} <span>${{winner.name}}</span></div><p>${{winner.name}} has the ${{reason}} on the current board. This can change with your roster and live draft state.</p><div class="comparison-grid">${{panel(one,winner===one)}}${{panel(two,winner===two)}}</div><p class="fine-print">This quick comparison is a decision aid, not a guarantee or a substitute for current injury and depth-chart news.</p>`;
}}
document.getElementById('player-one').value=String({index_by_name.get('Jahmyr Gibbs', 0)});
document.getElementById('player-two').value=String({index_by_name.get('Bijan Robinson', 1)});
document.getElementById('player-one').addEventListener('change',renderComparison);
document.getElementById('player-two').addEventListener('change',renderComparison);
renderComparison();
</script>
"""
    related = [
        ("/2026/adp-vs-model/", "ADP vs Model Study"),
        ("/2026/top-sleepers/", "Top Sleepers"),
        ("/2026/top-busts/", "Top Busts"),
        ("/methodology/", "Methodology"),
    ]
    return html_head(title, desc, "/2026/who-should-i-draft/", schema) + body + html_foot(related)


def build_adp_vs_model() -> str:
    title = "ADP vs Model: Our Draft Tests, Including the Re-run | OverADP"
    desc = "What OverADP's tests found: the new model now powering the board, a September re-run where the previous model did not beat ADP, and the original August study. Methods and limits."
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    display_date = datetime.now(UTC).strftime("%B %d, %Y")
    schema = f"""<script type="application/ld+json">
[
  {{"@context":"https://schema.org","@type":"Article","headline":"ADP vs Model: Our Draft Tests, Including the Re-run","description":"{desc}","author":{{"@type":"Organization","name":"OverADP Research"}},"publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},"datePublished":"2026-08-17","dateModified":"{today}","mainEntityOfPage":"https://overadp.com/2026/adp-vs-model/"}},
  {{"@context":"https://schema.org","@type":"Dataset","name":"OverADP August 2026 paired fantasy draft simulation summary (2023-2024)","description":"Summary outcomes from the original August 2026 study: 1,000 paired 12-team half-PPR draft simulations comparing Target Intel with ADP-first drafting under a frozen Week-1 lineup. A September 2026 re-run did not reproduce this result.","creator":{{"@type":"Organization","name":"OverADP"}},"temporalCoverage":"2023/2024","distribution":{{"@type":"DataDownload","encodingFormat":"text/csv","contentUrl":"https://overadp.com/2026/adp-vs-model/simulation-summary.csv"}}}},
  {{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
    {{"@type":"Question","name":"Does OverADP beat ADP?","acceptedAnswer":{{"@type":"Answer","text":"Not proven. The previous model did not beat ADP in a September 2026 re-run. The board now blends a new model with ADP; in tests on 2019 to 2025 that blend had lower error than ADP alone in 19 of 21 season-format checks and ranked players better in 14 of 21. It has not yet been tested through a live season."}}}},
    {{"@type":"Question","name":"What model powers the board now?","acceptedAnswer":{{"@type":"Answer","text":"Since September 2026 the board uses a new public-data projection model blended 50/50 with ADP-implied points. On its own the model roughly matches ADP; the blend tested better than either."}}}},
    {{"@type":"Question","name":"Does OverADP guarantee a top-three fantasy finish?","acceptedAnswer":{{"@type":"Answer","text":"No. These are retrospective simulations, not promises. Real leagues include injuries, waivers, trades, lineup choices and opponents that simulations only approximate."}}}}
  ]}}
]
</script>"""
    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 Research / ADP vs Model</div>
<div class="section-tag">Original OverADP Research</div>
<h1>ADP vs Model: <span class="accent">What Held Up</span> and What Didn't</h1>
<p class="lead">We test whether OverADP helps build better fantasy rosters than drafting from ADP. Here is every result we have, including the one that did not reproduce.</p>
<div class="answer-block"><span class="answer-label">Answer</span><p><strong>The board now blends a new model with ADP, the combination that tested best.</strong> The previous model did not beat ADP in a September 2026 re-run. The new model roughly matches ADP on its own; blended 50/50 with ADP it had lower error than ADP alone in 19 of 21 season-format tests. That is historical testing, not a guarantee, and it has not yet been tested through a live season.</p></div>
<div class="byline"><span>By OverADP Research</span><span>Published August 17, 2026</span><span>Updated {display_date}</span><span>Half-PPR</span></div>

<h2 id="september-rerun">September 2026 re-run: the previous model did not beat ADP</h2>
<p>Our lab re-ran the draft test with a rebuilt copy of the production model and the live Target Intel policy: 144 paired drafts across the 2023, 2024 and 2025 seasons and several league sizes and flex settings, using true preseason ADP.</p>
<table class="research-table">
  <thead><tr><th>Draft strategy (2023–2025)</th><th>Top-three rate vs ADP-first</th><th>95% interval</th></tr></thead>
  <tbody>
    <tr><td>Previous app policy</td><td>−17 percentage points (11.8% vs 29.2%)</td><td>−25 to −10</td></tr>
    <tr><td>August 17 study policy, as archived</td><td>−15 percentage points</td><td>−22 to −6</td></tr>
    <tr><td>Reconstruction of the original study recipe</td><td>+10 percentage points</td><td>+1 to +20</td></tr>
  </tbody>
</table>
<p>We also compared the projections themselves with ADP on the same players. On true 2023–2025 ADP, the previous point model ranked players less accurately than ADP (rank correlation 0.29 vs 0.40; average error 63.8 vs about 56 points). That result is why we rebuilt the model and now blend it with ADP.</p>
<p class="fine-print">The re-run is a provisional reconstruction of the production code, not the exact model fitted on August 29, and it uses synthetic opponents. It is still the most complete test we have, so we report it.</p>

<h2 id="model-2027">The new model, now live</h2>
<p>We built a new projection model from public NFL data, college production and route participation. Since September 2026 it powers the board, blended with ADP. Each season below was predicted using only earlier seasons.</p>
<table class="research-table">
  <thead><tr><th>2023–2025, true-ADP players</th><th>Rank correlation</th><th>Average error (pts)</th></tr></thead>
  <tbody>
    <tr><td>Previous model</td><td>0.29</td><td>63.8</td></tr>
    <tr><td>ADP</td><td>0.40</td><td>about 56</td></tr>
    <tr><td>New model</td><td>0.41</td><td>55.7</td></tr>
    <tr><td><strong>New model + ADP, 50/50 (the live board)</strong></td><td><strong>0.43</strong></td><td><strong>54.3</strong></td></tr>
  </tbody>
</table>
<p>Across 2019–2025 and three scoring formats, the 50/50 blend had lower error than ADP in 19 of 21 season-format tests and ranked players better in 14 of 21. In a simple best-ball draft simulation (12 teams, 2019–2025), blend-guided teams finished top three 51.7% of the time versus 33.8% for ADP-order drafting, ahead in 5 of 7 seasons. With only seven seasons, that is promising, not proven. We will also run it through our full draft simulator and report the result here.</p>

<h2>The original August 2026 study</h2>
<p>For the record, the original study found that across 1,000 paired 12-team simulations using true 2023 and 2024 Fantasy Football Calculator ADP, Target Intel produced a 50.6% top-three regular-season rate versus 25.7% for ADP-first drafting with Week-1 lineups frozen. The September re-run above did not reproduce this with the previous model.</p>
<table class="research-table">
  <thead><tr><th>Season</th><th>Strategy</th><th>Simulations</th><th>Avg. rank</th><th>Top-three rate</th><th>Frozen-lineup points</th></tr></thead>
  <tbody>
    <tr><td>2023</td><td>ADP first</td><td>500</td><td>6.63</td><td>26.4%</td><td>1,102.5</td></tr>
    <tr><td>2023</td><td>Target Intel</td><td>500</td><td>4.26</td><td>48.8%</td><td>1,223.0</td></tr>
    <tr><td>2024</td><td>ADP first</td><td>500</td><td>6.72</td><td>25.0%</td><td>1,129.0</td></tr>
    <tr><td>2024</td><td>Target Intel</td><td>500</td><td>4.04</td><td>52.4%</td><td>1,250.4</td></tr>
  </tbody>
</table>
<p class="fine-print">Original August 2026 study, kept for transparency. <a class="inline" href="/2026/adp-vs-model/simulation-summary.csv">Download the summary CSV</a>.</p>

<h2>How to use ADP and OverADP together</h2>
<div class="card-grid">
  <article class="card"><h4>Keep ADP on the screen</h4><div class="sub">PRICE SIGNAL</div><p class="reason">ADP is a strong signal of player value and predicts which players may reach your next turn. Our tests say to respect it.</p></article>
  <article class="card"><h4>Treat disagreements as research</h4><div class="sub">SECOND OPINION</div><p class="reason">When the model and ADP disagree, check the range, depth chart and news before acting. A gap is a question, not an answer.</p></article>
  <article class="card"><h4>Draft for this roster</h4><div class="sub">LIVE CONTEXT</div><p class="reason">Starter holes, flex paths and positional cliffs can change the best selection after every pick.</p></article>
</div>

<h2>Frequently asked questions</h2>
<div class="faq-list">
  <details><summary>Does OverADP beat ADP?</summary><p>Not proven. The previous model did not. The new board blends the model with ADP, and in historical tests that blend beat ADP alone on projection error in 19 of 21 season-format checks. It has not yet been tested through a live season.</p></details>
  <details><summary>Why publish a result that went against you?</summary><p>Because you are trusting these numbers in your draft. A test that only reports wins is not a test.</p></details>
  <details><summary>Is the new model live?</summary><p>Yes, since September 2026, blended with ADP. We will keep testing it and update this page either way.</p></details>
</div>
"""
    related = [
        ("/2026/who-should-i-draft/", "Who Should I Draft?"),
        ("/draft-assistant/", "Fantasy Draft Assistant"),
        ("/2026/top-sleepers/", "Top Sleepers"),
        ("/methodology/", "Full Methodology"),
    ]
    return html_head(title, desc, "/2026/adp-vs-model/", schema) + body + html_foot(related)


def build_methodology(accuracy: dict) -> str:
    title_full = "Methodology: How OverADP's Walk-Forward Fantasy Football Model Works | OverADP"
    desc = "How OverADP projects fantasy football: season-by-season walk-forward testing, a gradient-boosted model blended with ADP, empirical 80% ranges, depth-chart and college context, and published limitations."

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
  "datePublished":"2026-07-20",
  "dateModified":"{datetime.now(UTC).strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/methodology/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / Methodology</div>
<div class="section-tag">Transparency</div>
<h1>How the <span class="accent">Model</span> Works</h1>
<p class="lead">A full technical breakdown of OverADP's machine-learning pipeline: how we project fantasy points, how we quantify uncertainty, and how we validate without leaking future information into the past.</p>
<div class="byline"><span>By OverADP Research</span><span>Updated {datetime.now(UTC).strftime('%B %d, %Y')}</span><span>Methods and limitations</span></div>

<h2>The one-sentence version</h2>
<p>We train one gradient-boosted model on completed NFL seasons (2014 onward), test it season by season on years it never saw, then blend each projection 50/50 with the points implied by current ADP, because that combination tested better than either the model or ADP alone.</p>

<h2>1. Walk-forward validation (not random splits)</h2>
<p>Fantasy football data is temporal: player stats in 2023 are <em>not</em> independent of stats in 2022. A standard random train-test split would leak future information. The model would see a player's 2024 season during training and then be "tested" on his 2025 season, but it already knows the player's career trajectory.</p>
<p>Walk-forward validation prevents this. Every test season is predicted by a model trained only on earlier seasons. We tested seven seasons this way (2019 to 2025) and chose the design using 2019 to 2024 before looking at 2025.</p>

<h2>2. One model, three scoring formats</h2>
<p>The point model is a bag of gradient-boosted trees averaged with a two-stage version that predicts games played and points per game separately, so a season shortened by injury is not automatically read as lost talent. One model is trained across QB, RB, WR and TE with position as an input, which tested better than separate position models, especially at TE. Standard, half-PPR and PPR are each trained directly.</p>

<h2>3. What goes into it</h2>
<p><strong>Production and usage:</strong> three seasons of stats, per-game rates, target share, air-yards share, snap share and route participation (routes run, targets and yards per route).</p>
<p><strong>Opportunity quality:</strong> expected fantasy points from play-by-play, red-zone and goal-line work, deep and end-zone targets, and touchdowns over expected to catch regression.</p>
<p><strong>Role:</strong> the preseason depth chart, last season's closing depth chart and each player's order in his position room. The depth chart is the strongest single signal after past production.</p>
<p><strong>Rookies:</strong> draft capital, combine results, age and college production (share of team receiving yards and touchdowns, breakout age, yards per team pass attempt, recruiting rating).</p>
<p><strong>Team context:</strong> the new team's pace, pass rate and scoring, vacated targets and carries, returning competition at the position and the quality of the team's quarterback.</p>

<h2>4. Blending with ADP</h2>
<p>ADP carries information public stats do not, such as camp news and injury recovery timelines. We convert each player's ADP into implied points (a log-ADP curve fitted by position on past seasons) and average it with the model. On 2019 to 2025, across three scoring formats, the blend had lower error than ADP alone in 19 of 21 season-format tests and ranked players better in 14 of 21. Players without real ADP use the model alone.</p>

<h2>5. 80% ranges</h2>
<p>Every projection is wrong; the question is <em>by how much</em>. Each range comes from how far past projections at the same position and projection level missed, measured only on earlier seasons. In 2024 and 2025 about 77% of outcomes landed inside the 80% range (lower at TE and QB), so treat the ranges as a guide, not a guarantee.</p>

<h2>6. What we tested and left out</h2>
<p>Injury-report features, coaching changes, week-1 betting lines, a model that predicts yards and touchdowns separately, and a learned (rather than 50/50) ADP combination were all tested season by season. None beat the current design by more than noise, so none were added.</p>

<h2>The {test_season_label} walk-forward results</h2>
<p>These are the live board's numbers (model blended with ADP, half-PPR) for players with a prior NFL season or a top-150 draft pick, each season predicted using only earlier seasons. Because the player pool differs from the previous model's published table, the error values are not directly comparable to older versions of this page. On the same true-ADP players in 2023 to 2025, the previous model had a rank correlation of 0.29 and the new blend 0.43.</p>
<table class="rank">
  <thead><tr><th>Position</th><th>MAE</th><th>RMSE</th><th>R²</th><th>Held-Out N</th></tr></thead>
  <tbody>{metric_table_rows}</tbody>
</table>

<h2>What the model doesn't do</h2>
<p>Honest limitations:</p>
<p><strong>It can't predict injuries.</strong> Malik Nabers finishing 2025 with 4 games played wasn't a model call. It was a bone bruise. The model does learn from games played in past seasons, but week-to-week injuries are noise.</p>
<p><strong>It's only as good as the data.</strong> Undrafted and late-round rookies with thin college data carry more uncertainty. Players not in the model's roster snapshot keep the previous model's projection.</p>
<p><strong>Fantasy football is high-variance.</strong> Even a strong aggregate model misses individual players. Stars coming back from injury are the biggest known blind spot for public stats, which is one reason the board leans on ADP too.</p>

<h2>What's next</h2>
<p>For 2027 we plan to rebuild the board from draft-day rosters and depth charts through training camp and to re-test the full draft simulator before August. This page will be updated with the results.</p>
<p>See the current results in <a class="inline" href="/app/">the free War Room</a>, or dive into the <a class="inline" href="/2026/top-sleepers/">top sleepers</a> and <a class="inline" href="/2026/top-busts/">top busts</a>.</p>
<h2 id="draft-simulation">Draft simulations</h2>
<p>We also test full drafts against ADP-first drafting. All results, including a re-run that did not reproduce an earlier study, are on the <a class="inline" href="/2026/adp-vs-model/">ADP vs Model page</a>.</p>
<p>For a fast two-player check, use the <a class="inline" href="/2026/who-should-i-draft/">Who Should I Draft comparator</a>.</p>
"""

    related = [
        ("/2026/top-sleepers/", "Top Sleepers"),
        ("/2026/top-busts/", "Top Busts"),
        ("/2026/qb-rankings/", "QB Rankings"),
        ("/2026/rb-rankings/", "RB Rankings"),
        ("/2026/wr-rankings/", "WR Rankings"),
        ("/2026/te-rankings/", "TE Rankings"),
        ("/2026/who-should-i-draft/", "Who Should I Draft?"),
        ("/2026/adp-vs-model/", "ADP vs Model Study"),
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
    write_page("2026/who-should-i-draft/index.html", build_who_should_i_draft(active))
    write_page("2026/adp-vs-model/index.html", build_adp_vs_model())
    write_page("2026/adp-vs-model/simulation-summary.csv", """season,strategy,simulations,average_rank,top_three_rate,frozen_lineup_points
2023,ADP first,500,6.632,0.264,1102.49636
2023,Target Intel,500,4.264,0.488,1222.96284
2024,ADP first,500,6.720,0.250,1129.00068
2024,Target Intel,500,4.038,0.524,1250.36204
""")
    write_page("methodology/index.html", build_methodology(accuracy))

    print("Generating sitemap + robots.txt...")
    pages = [
        "/2026/qb-rankings/",
        "/2026/rb-rankings/",
        "/2026/wr-rankings/",
        "/2026/te-rankings/",
        "/2026/top-sleepers/",
        "/2026/top-busts/",
        "/2026/who-should-i-draft/",
        "/2026/adp-vs-model/",
        "/methodology/",
        "/support/",
        "/draft-assistant/",
        "/privacy/",
        "/terms/",
        "/refunds/",
    ]
    (SITE / "sitemap.xml").write_text(build_sitemap(pages))
    print(f"  wrote /sitemap.xml ({len(pages)+2} URLs)")
    (SITE / "robots.txt").write_text(build_robots())
    print(f"  wrote /robots.txt")

    print(f"\n✓ Done. 9 hub pages + research CSV + sitemap + robots.txt generated.")
    print(f"  Submit sitemap to Search Console: https://overadp.com/sitemap.xml")


if __name__ == "__main__":
    main()
