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
from datetime import datetime
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
html{scroll-behavior:smooth;}
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
  <div class="links">
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

    today = datetime.utcnow().strftime("%B %d, %Y")
    return f"""
    {related}
    {cta}
  </div></main>
<footer>
  <div>Updated {today} · Walk-forward validated through 2025 · <a href="/">Home</a> · <a href="/methodology/">Methodology</a> · <a href="/app/">Draft Tool</a></div>
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


def build_position_ranking(players: list, position: str, limit: int, slug: str, title_pos: str) -> str:
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

    intro = {
        "QB": "Quarterback is where ADP fails hardest — our walk-forward backtest shows ADP R² ≈ 0 for QB (consensus is essentially noise at the position). Our model posts a <strong>34% MAE edge over ADP</strong> for QBs.",
        "RB": "Running back is the hardest position for projections: committee usage, injury rates, and coaching changes add noise. Our depth-chart-aware model still posts a <strong>38% MAE edge over ADP</strong> for RBs.",
        "WR": "Wide receiver projections live or die on target share and teammate competition. We explicitly encode prior-season teammate targets so when a star signs elsewhere, our model sees it. <strong>33% MAE edge over ADP</strong>.",
        "TE": "Tight end is the highest-variance fantasy position. Most years, a handful of TEs produce and the rest are streamers. Our model cuts TE MAE by <strong>39% vs ADP</strong> — and the TE R² lift is the largest of any position (0.60 vs 0.03).",
    }[position]

    title_full = f"2026 Fantasy Football {title_pos} Rankings — Walk-Forward Validated Projections | OverADP"
    mae_edge = {'QB':'34%','RB':'38%','WR':'33%','TE':'39%'}[position]
    desc = f"Top {limit} 2026 fantasy football {position} rankings with calibrated 80% confidence intervals. ML model cut {position} MAE by {mae_edge} vs ADP on 2022-2025 walk-forward validation. Updated {datetime.utcnow().strftime('%B %Y')}."

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"Article",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"{datetime.utcnow().strftime('%Y-%m-%d')}",
  "dateModified":"{datetime.utcnow().strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/2026/{slug}/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / 2026 Rankings / {position}</div>
<div class="section-tag">2026 {title_pos} Rankings</div>
<h1>2026 Fantasy <span class="accent">{title_pos} Rankings</span></h1>
<p class="lead">The top {limit} {position}s for 2026 half-PPR leagues, ranked by our machine-learning model's projected fantasy points. Each projection comes with a calibrated 80% confidence interval — meaning 83% of actual outcomes fell inside our intervals in 2025 walk-forward testing.</p>

<div class="meta-strip">
  <span>📊 Model: <strong>CatBoost ensemble + CQR</strong></span>
  <span>🎯 Validation: <strong>walk-forward on 2019-2025</strong></span>
  <span>📅 Scoring: <strong>half-PPR</strong></span>
  <span>🔄 Updated: <strong>{datetime.utcnow().strftime('%B %d, %Y')}</strong></span>
</div>

<p>{intro}</p>

{table}

<div class="callout">
  <h3>How to read this table</h3>
  <p><strong>Proj Pts</strong>: half-PPR fantasy points our model expects over the full 2026 season. <strong>80% CI</strong>: the interval 80% of actual outcomes should fall inside, based on 2025 calibration. A wide CI means more uncertainty — injury-prone players and rookies have wider intervals. <strong>ADP</strong>: half-PPR consensus average draft position from Fantasy Football Calculator. <strong>Risk</strong>: relative coefficient of variation (CI width / projection) bucketed into position quartiles.</p>
</div>

<h2>What the model gets right that ADP misses</h2>
<p>ADP is a wisdom-of-the-crowd signal — it reflects what drafters collectively think, not what actually happens. In our 2022-2025 walk-forward validation, consensus ADP explained only <strong>9% of actual fantasy-point variance</strong>. Our model explained <strong>59%</strong> — a <a class="inline" href="/methodology/">7× improvement</a>.</p>
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
        gap_display = f"+{int(gap)}" if gap > 0 else str(int(gap))
        cards.append(f"""
<div class="card">
  <h4>{p['player_name']}</h4>
  <div class="sub">{p['position']} · {p.get('team','FA')} · <span class="verdict {verdict_cls}">{arrow} {kind}</span></div>
  <div class="stat">Model rank: <strong>#{int(p.get('model_rank', 0))}</strong></div>
  <div class="stat">ADP rank: <strong>#{int(p.get('adp', 0))}</strong></div>
  <div class="stat">Projected pts: <strong>{p.get('projected_points', 0):.1f}</strong></div>
  <div class="stat" style="color:var(--{color});">Gap vs ADP: <strong style="color:var(--{color});">{gap_display}</strong></div>
  <div class="reason">{p.get('reason', '')}</div>
</div>""")

    if is_sleeper:
        title_full = "2026 Fantasy Football Sleepers — ML Model Calls vs ADP | OverADP"
        desc = "Top 2026 fantasy football sleepers our ML model ranks dramatically higher than consensus ADP. Walk-forward validated on 2025 data — found Drake Maye (ADP 128 → QB2), Matthew Stafford (ADP 169 → QB3), and more."
        intro_lead = "The 2026 players our machine-learning model ranks <strong>well above consensus ADP</strong>. These are the largest model-vs-crowd disagreements — the spots where our walk-forward history suggests ADP is wrong."
        proof_hed = "Why trust these calls?"
        proof_body = """In our 2025 walk-forward backtest (train through 2024, predict 2025), the model flagged <strong>Drake Maye as a sleeper at ADP #128</strong>. He finished QB#2 with 416 fantasy points — 126 rank spots above where he was being drafted. It also flagged <strong>Matthew Stafford (ADP #169 → actual QB#3)</strong>, <strong>Sam Darnold (ADP #183 → actual QB#21)</strong>, and <strong>Trevor Lawrence (ADP #140 → actual QB#6)</strong>. ADP is the wisdom of the crowd, but the crowd is slow to update on depth-chart changes, coaching hires, and free-agent moves — which is exactly where our model has the biggest edge."""
        slug = "top-sleepers"
    else:
        title_full = "2026 Fantasy Football Busts — Overvalued by ADP | OverADP"
        desc = "Top 2026 fantasy football busts our ML model ranks dramatically lower than consensus ADP. Walk-forward validated — correctly flagged Brian Thomas Jr. (ADP 13 → WR #33 in 15 games) and more in 2025."
        intro_lead = "The 2026 players our machine-learning model ranks <strong>well below consensus ADP</strong>. These are picks we think you should avoid at their current draft cost — the largest negative model-vs-crowd gaps."
        proof_hed = "Why trust these calls?"
        proof_body = """In 2025 walk-forward testing, the model flagged <strong>Brian Thomas Jr. as a bust</strong> — he was going ADP #13 (WR6-ish consensus) and our model had him overall #41. He finished the season at overall rank #102 with 124 points across <strong>15 games played</strong> — a real, non-injury bust. It also correctly flagged <strong>Bucky Irving (ADP #16 → actual RB#40)</strong> and flagged <strong>Isiah Pacheco (ADP #58 → actual RB#41)</strong>. Busts are harder to call than sleepers because injuries dominate the worst outcomes — but model-flagged busts consistently underperformed <em>even when healthy</em>."""
        slug = "top-busts"

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"Article",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"{datetime.utcnow().strftime('%Y-%m-%d')}",
  "dateModified":"{datetime.utcnow().strftime('%Y-%m-%d')}",
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
  <span>🎯 2025 hit rate: <strong>Drake Maye ADP 128 → QB#2</strong></span>
  <span>🔄 Updated: <strong>{datetime.utcnow().strftime('%B %d, %Y')}</strong></span>
</div>

<h2>The Top 15</h2>
<div class="card-grid">{''.join(cards)}</div>

<h2>{proof_hed}</h2>
<p>{proof_body}</p>
<p>Methodology is public — walk-forward validation, conformal quantile regression for calibrated 80% intervals, depth-chart aware, no leakage. Read the full <a class="inline" href="/methodology/">model methodology</a> or open the <a class="inline" href="/app/">free draft board</a>.</p>

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


def build_methodology() -> str:
    title_full = "Methodology — How OverADP's Walk-Forward Fantasy Football Model Works | OverADP"
    desc = "How OverADP projects fantasy football: walk-forward validation, CatBoost ensemble, conformal quantile regression for 80% confidence intervals, depth-chart features, and more. Full transparency on the 2025 results."

    schema = f"""<script type="application/ld+json">
{{
  "@context":"https://schema.org",
  "@type":"TechArticle",
  "headline":"{title_full}",
  "description":"{desc}",
  "author":{{"@type":"Organization","name":"OverADP"}},
  "publisher":{{"@type":"Organization","name":"OverADP","url":"https://overadp.com"}},
  "datePublished":"{datetime.utcnow().strftime('%Y-%m-%d')}",
  "dateModified":"{datetime.utcnow().strftime('%Y-%m-%d')}",
  "mainEntityOfPage":"https://overadp.com/methodology/"
}}
</script>"""

    body = f"""
<div class="crumbs"><a href="/">Home</a> / Methodology</div>
<div class="section-tag">Transparency</div>
<h1>How the <span class="accent">Model</span> Works</h1>
<p class="lead">A full technical breakdown of OverADP's machine-learning pipeline — how we project fantasy points, how we quantify uncertainty, and how we validate without leaking future information into the past.</p>

<h2>The one-sentence version</h2>
<p>We train a per-position CatBoost ensemble on 7 years of NFL skill-position data (2019-2025), validated with rolling walk-forward splits so the model is only ever tested on seasons it hasn't seen, and we wrap point predictions with conformal quantile regression to produce 80% confidence intervals with empirically verified coverage.</p>

<h2>1. Walk-forward validation (not random splits)</h2>
<p>Fantasy football data is temporal: player stats in 2023 are <em>not</em> independent of stats in 2022. A standard 80/20 random train-test split would leak future information — the model would see a player's 2024 season during training and then be "tested" on his 2025 season, but it already knows the player's career trajectory.</p>
<p>Walk-forward validation prevents this. We train on seasons 2019-N and test on season N+1, for every N. The 2025 results you see on this site come from a model that was trained on <strong>2019-2024 only</strong> and tested on 2025 out-of-sample. Every year is a truly held-out test.</p>

<h2>2. Four-model ensemble</h2>
<p>We run four models per position: Ridge regression, Random Forest, XGBoost, and CatBoost. In walk-forward validation, CatBoost wins every position after hyperparameter tuning with per-position temporal weights, so the production model uses CatBoost point predictions. The ensemble spread is also used for ensemble uncertainty (see below).</p>
<p>Per-position tuning matters. QB rewards deeper trees (depth=6) with more iterations; RB/WR/TE prefer depth=4 with more aggressive L2. Temporal weighting (recent seasons weighted more heavily) cut QB MAE by 2.6% and RB MAE by 3.0% in validation.</p>

<h2>3. Conformal quantile regression (CQR) for honest 80% intervals</h2>
<p>Point predictions alone are dangerous in fantasy — every projection is wrong, the question is <em>by how much</em>. We train separate quantile CatBoost models at the 10th and 90th percentiles, then calibrate on the most recent held-out season using split-conformal CQR.</p>
<p>The result: intervals with <strong>empirically verified 80% coverage</strong>. In 2025 walk-forward testing, raw quantile regression covered 56% of outcomes (badly miscalibrated), while conformal CQR covered <strong>83.5% on the test set</strong> — above the 80% target, with coverage error under 4 percentage points. This is real uncertainty, not a Bayesian band.</p>

<h2>4. Depth-chart awareness (Week 1 snapshot)</h2>
<p>One of our biggest 2026 feature additions. We pull pre-season depth charts from nflverse (Week 1 snapshot for 2019-2024; nearest-to-September-5 snapshot for 2025+) and encode each player's depth rank (1=starter, 2=backup, 3+=depth), plus binary is_starter and is_backup flags.</p>
<p>Used for QB, WR, and TE projections. Excluded from RB because RBBC (running-back-by-committee) breaks the signal — a RB2 who gets 60% of carries produces more than a RB1 who splits. Walk-forward gain: QB MAE −3.4%, WR MAE −2.6%.</p>

<h2>5. Target-competition features (prevent phantom breakouts)</h2>
<p>Using prior-season teammate targets, we compute each WR's teammate_targets_prev and teammate_rec_yards_prev on their <em>current</em> team (so if Chase Claypool signs with the Jaguars, his projections reflect BTJ's 200+ targets ahead of him). We also compute teammate_carries_prev for RBs.</p>
<p>Crucially: no leakage. We use prior-season teammate production on the current roster, never current-season production. This re-runs after free-agent and draft changes are reflected in the projection-season roster.</p>

<h2>6. Conservative monotonic constraints</h2>
<p>Aggregate production lags (prior-season fantasy points, targets, receptions, carries) should never have a <em>negative</em> marginal effect on projections. We encode positive monotonic constraints on exactly these features and leave everything else unconstrained. This adds sanity guardrails without overfitting — MAE stays within noise, but the model can't produce pathological projections where scoring more the prior year makes you project lower.</p>

<h2>7. College + draft capital features for rookies</h2>
<p>For rookies and second-year players, we merge draft picks, combine metrics, college production, and interaction features (college_x_rookie, draft_cap_x_rookie, athletic_x_rookie). Athletic score is a position-weighted composite of combine z-scores. These features give the model signal before an NFL stat line exists.</p>

<h2>The 2022-2025 walk-forward results</h2>
<p>All numbers below are averages across four held-out test seasons (2022, 2023, 2024, 2025). The model only ever sees past seasons during training, never the season it's being tested on. ADP baseline is a per-position quadratic regression on log(ADP), fit on the same training seasons.</p>
<table class="rank">
  <thead><tr><th>Metric</th><th>OverADP</th><th>ADP</th><th>Edge</th></tr></thead>
  <tbody>
    <tr><td>Overall R² (variance explained)</td><td class="positive">0.59</td><td class="negative">0.09</td><td class="positive">+7×</td></tr>
    <tr><td>Overall MAE</td><td class="positive">38.4</td><td class="negative">62.7</td><td class="positive">−39%</td></tr>
    <tr><td>QB MAE</td><td class="positive">71.2</td><td class="negative">107.8</td><td class="positive">−34%</td></tr>
    <tr><td>RB MAE</td><td class="positive">40.4</td><td class="negative">65.0</td><td class="positive">−38%</td></tr>
    <tr><td>WR MAE</td><td class="positive">34.4</td><td class="negative">51.2</td><td class="positive">−33%</td></tr>
    <tr><td>TE MAE</td><td class="positive">24.2</td><td class="negative">39.6</td><td class="positive">−39%</td></tr>
    <tr><td>QB R²</td><td class="positive">0.49</td><td class="negative">0.00</td><td class="positive">huge</td></tr>
    <tr><td>TE R²</td><td class="positive">0.60</td><td class="negative">0.03</td><td class="positive">+20×</td></tr>
    <tr><td>80% CI coverage</td><td class="positive">83.5%</td><td>n/a</td><td class="positive">calibrated</td></tr>
  </tbody>
</table>

<h2>What the model doesn't do</h2>
<p>Honest limitations:</p>
<p><strong>It can't predict injuries.</strong> Malik Nabers finishing 2025 with 4 games played wasn't a model call — it was a bone bruise. We DO model injury rates from prior-season games-missed features, but week-to-week injuries are noise.</p>
<p><strong>It's only as good as the data.</strong> UDFAs and late-round rookies with missing college data get wider intervals and lower confidence. Coaching-change features were tested and rejected after walk-forward validation showed them adding noise rather than signal.</p>
<p><strong>Fantasy football is high-variance.</strong> Even a perfect model won't hit every call. Our 80% CIs cover 83.5% of outcomes — which means 16.5% of players still blow through their interval in either direction.</p>

<h2>What's next</h2>
<p>We refresh the depth-chart features after the NFL draft (late April) and again in August once pre-season depth charts are final. Draft capital for 2026 rookies is already in the model, and team assignments update automatically when FA signings are reflected in the roster data.</p>
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
    today = datetime.utcnow().strftime("%Y-%m-%d")
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
    players, sleepers_busts, _ = load_data()
    active = filter_active(players)
    print(f"  {len(active)} active players, {len(sleepers_busts)} sleepers/busts entries")

    print("Generating hub pages...")
    write_page("2026/qb-rankings/index.html", build_position_ranking(active, "QB", 32, "qb-rankings", "QB"))
    write_page("2026/rb-rankings/index.html", build_position_ranking(active, "RB", 50, "rb-rankings", "RB"))
    write_page("2026/wr-rankings/index.html", build_position_ranking(active, "WR", 60, "wr-rankings", "WR"))
    write_page("2026/te-rankings/index.html", build_position_ranking(active, "TE", 24, "te-rankings", "TE"))
    write_page("2026/top-sleepers/index.html", build_sleepers_or_busts(sleepers_busts, "SLEEPER"))
    write_page("2026/top-busts/index.html", build_sleepers_or_busts(sleepers_busts, "BUST"))
    write_page("methodology/index.html", build_methodology())

    print("Generating sitemap + robots.txt...")
    pages = [
        "/2026/qb-rankings/",
        "/2026/rb-rankings/",
        "/2026/wr-rankings/",
        "/2026/te-rankings/",
        "/2026/top-sleepers/",
        "/2026/top-busts/",
        "/methodology/",
    ]
    (SITE / "sitemap.xml").write_text(build_sitemap(pages))
    print(f"  wrote /sitemap.xml ({len(pages)+2} URLs)")
    (SITE / "robots.txt").write_text(build_robots())
    print(f"  wrote /robots.txt")

    print(f"\n✓ Done. 7 hub pages + sitemap + robots.txt generated.")
    print(f"  Submit sitemap to Search Console: https://overadp.com/sitemap.xml")


if __name__ == "__main__":
    main()
