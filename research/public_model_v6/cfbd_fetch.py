"""One-time pull of CollegeFootballData inputs for rookie features. Stdlib only; run on your machine.
Uses the key saved by cfbd_login.sh (never printed). ~110 API calls total; skips files already downloaded.
Raw API data stays private in cfbd_raw/ (CFBD terms: no redistribution of raw data)."""
import json, sys, time, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY = (HERE / ".secrets" / "cfbd_key").read_text().strip()
OUT = HERE / "cfbd_raw"; OUT.mkdir(exist_ok=True)
(OUT / ".gitignore").write_text("*\n")
JOBS = []
for y in range(2008, 2026):
    for cat in ("receiving", "rushing", "passing"):
        JOBS.append((f"player_{cat}_{y}", f"/stats/player/season?year={y}&category={cat}"))
    JOBS.append((f"team_{y}", f"/stats/season?year={y}"))
    JOBS.append((f"recruits_{y}", f"/recruiting/players?year={y}&classification=HighSchool"))
for y in range(2012, 2027):
    JOBS.append((f"draft_{y}", f"/draft/picks?year={y}"))

done = calls = 0
for name, path in JOBS:
    f = OUT / f"{name}.json"
    if f.exists() and f.stat().st_size > 2:
        done += 1; continue
    req = urllib.request.Request("https://api.collegefootballdata.com" + path,
                                 headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"{name}: HTTP {e.code} -- stopping (rerun later to resume)"); sys.exit(1)
    f.write_text(json.dumps(data))
    calls += 1; done += 1
    print(f"[{done}/{len(JOBS)}] {name}: {len(data)} rows", flush=True)
    time.sleep(0.6)
print(f"Finished. {calls} API calls this run. Tell Claude it's done.")
