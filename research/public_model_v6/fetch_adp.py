"""Fetch Fantasy Football Calculator ADP (12-team; std/half/PPR) for 2019-2025 -> adp/ffc_adp_2019_2025.csv.
FFC ADP REST API: free for personal and commercial use; attribution requested ("ADP data courtesy of
FantasyFootballCalculator.com"). 21 calls; please don't call more than needed (data updates daily)."""
import csv, json, time, urllib.request
from pathlib import Path
Path("adp").mkdir(exist_ok=True)
F = {"half-ppr": "half", "ppr": "ppr", "standard": "std"}
rows = []
for fmt, short in F.items():
    for y in range(2019, 2026):
        with urllib.request.urlopen(f"https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams=12&year={y}", timeout=60) as r:
            j = json.load(r)
        for p in j.get("players", []):
            if p["position"] in ("QB", "RB", "WR", "TE"):
                rows.append([short, y, p["player_id"], p["name"], p["position"], p["team"], p["adp"], p["stdev"], p["times_drafted"]])
        time.sleep(0.5)
with open("adp/ffc_adp_2019_2025.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["fmt", "season", "ffc_id", "name", "position", "team", "adp", "adp_stdev", "times_drafted"]); w.writerows(rows)
print(len(rows), "rows")
