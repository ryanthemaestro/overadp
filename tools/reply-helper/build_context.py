#!/usr/bin/env python3
"""Build players_compact.json from site/app/data/players.json for the extension.

Ships top 400 players with rich historical context so the LLM can cite real
numbers (last year's points, YoY delta, bye, rookie/2nd-year flag, VBD, injuries)
instead of hallucinating.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # overadp/
DATA = ROOT / "site" / "app" / "data"
OUT = Path(__file__).resolve().parent / "players_compact.json"

players = json.loads((DATA / "players.json").read_text())

# Load sleepers/busts so drafts can reference them
try:
    sb = json.loads((DATA / "sleepers_busts.json").read_text())
    label_by_id = {}
    if isinstance(sb, list):
        for x in sb:
            if "player_id" in x and "label" in x:
                label_by_id[x["player_id"]] = x["label"]
    else:
        for x in sb.get("sleepers", []):
            label_by_id[x.get("player_id")] = "SLEEPER"
        for x in sb.get("busts", []):
            label_by_id[x.get("player_id")] = "BUST"
except Exception:
    label_by_id = {}

# Rank by projected_points desc
players = [p for p in players if p.get("projected_points")]
players.sort(key=lambda p: p.get("projected_points", 0), reverse=True)
players = players[:400]

# Add rank within position
by_pos = {}
for p in sorted(players, key=lambda p: p.get("projected_points", 0), reverse=True):
    pos = p.get("position", "?")
    by_pos.setdefault(pos, 0)
    by_pos[pos] += 1
    p["_pos_rank"] = by_pos[pos]


def _round(v, d=1):
    if v is None:
        return None
    try:
        return round(float(v), d)
    except (TypeError, ValueError):
        return None


def _int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


out = []
for p in players:
    pos = p.get("position", "?")
    proj = _round(p.get("projected_points"), 1)
    last = _round(p.get("pts_lag1"), 1)
    yoy = None
    if proj is not None and last is not None and last > 0:
        yoy = round((proj - last) / last * 100)  # percent change

    ci_low = _round(p.get("ci_low"), 1)
    ci_high = _round(p.get("ci_high"), 1)
    ci = None
    if ci_low is not None and ci_high is not None:
        ci = round((ci_high - ci_low) / 2, 1)

    # Role flag
    if p.get("is_2nd_year"):
        role = "2nd-year"
    elif last == 0 or last is None:
        role = "rookie"
    else:
        role = None

    entry = {
        "name": p.get("player_name", ""),
        "pos": pos,
        "team": p.get("team", ""),
        "proj": proj,
        "last": last,  # last season actual fantasy points
        "yoy": yoy,    # percent change proj vs last
        "adp": p.get("adp") if (p.get("adp") is not None and p.get("adp") < 200) else None,
        "rank": f"{pos}{p['_pos_rank']}",
        "ci": ci if ci is not None else 0,
        "risk": p.get("risk", "medium"),
        "vbd": _round(p.get("vbd"), 1),
        "bye": _int(p.get("bye")),
        "role": role,   # rookie / 2nd-year / None (veteran)
        "gm_miss": _int(p.get("games_missed_lag1")),
        "inj3": _int(p.get("injury_count_roll3")),
        "label": label_by_id.get(p.get("player_id")),
    }
    # Drop None keys to save tokens
    entry = {k: v for k, v in entry.items() if v is not None and v != 0 or k in ("proj", "rank", "pos", "name", "team")}
    out.append(entry)

OUT.write_text(json.dumps(out, separators=(",", ":")))
print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(out)} players)")

# ----- board.json : scarcity, roster, accuracy -----
BOARD_OUT = Path(__file__).resolve().parent / "board.json"
board = {}
for fname in ("scarcity.json", "roster_config.json", "accuracy.json"):
    path = DATA / fname
    if path.exists():
        try:
            board[fname.replace(".json", "")] = json.loads(path.read_text())
        except Exception:
            pass

BOARD_OUT.write_text(json.dumps(board, separators=(",", ":")))
print(f"Wrote {BOARD_OUT} ({BOARD_OUT.stat().st_size} bytes)")

# Report data freshness
import datetime as _dt
players_mtime = (DATA / "players.json").stat().st_mtime
age_days = (_dt.datetime.now().timestamp() - players_mtime) / 86400
print(f"\nSource data age: {age_days:.1f} days old (last regenerated {_dt.datetime.fromtimestamp(players_mtime):%Y-%m-%d %H:%M})")
if age_days > 7:
    print(f"  WARNING: data is {age_days:.0f} days old. Rerun the full export pipeline to refresh rosters/ADP/trades.")

# Refresh team assignments from Sleeper (catches trades since last export)
print("\nRefreshing team assignments from Sleeper API...")
import subprocess as _sp
_sp.run(
    ["python", str(Path(__file__).resolve().parent / "refresh_teams.py")],
    check=False,
)
