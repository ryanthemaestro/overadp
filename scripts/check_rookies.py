"""Quick check: are 2026 NFL draft rookies in the model data yet?"""
import pandas as pd
from pathlib import Path

DATA = Path("data")

print("=== Draft picks parquet ===")
try:
    draft = pd.read_parquet(DATA / "draft_picks.parquet")
    print(f"Total rows: {len(draft)}")
    if "season" in draft.columns:
        print(f"Seasons present: {sorted(draft['season'].unique())}")
        d26 = draft[draft["season"] == 2026]
        print(f"2026 picks: {len(d26)}")
        if len(d26) > 0:
            cols = [c for c in ["pfr_player_name", "player_name", "pick", "round", "team", "position", "college"] if c in d26.columns]
            print(d26[cols].head(15).to_string(index=False))
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== Roster parquet (2026) ===")
try:
    roster = pd.read_parquet(DATA / "roster.parquet")
    if "season" in roster.columns:
        r26 = roster[roster["season"] == 2026]
        print(f"2026 rows: {len(r26)}")
        # Look for Cam Ward / Travis Hunter
        for nm in ["Cam Ward", "Travis Hunter", "Cameron Ward"]:
            for col in ["football_name", "player_name", "first_name"]:
                if col in r26.columns:
                    m = r26[r26[col].astype(str).str.contains(nm, case=False, na=False)]
                    if len(m) > 0:
                        print(f"\nFound '{nm}' via {col}:")
                        showcols = [c for c in ["football_name", "first_name", "last_name", "position", "team", "season", "rookie_year", "draft_number", "draft_round"] if c in m.columns]
                        print(m[showcols].head(3).to_string(index=False))
                        break
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== Exported players.json (rookies on real teams) ===")
try:
    import json
    with open("src/api/static/data/players.json") as f:
        players = json.load(f)
    print(f"Total players in export: {len(players)}")
    rookies = [p for p in players if p.get("is_rookie")]
    print(f"Tagged is_rookie: {len(rookies)}")
    for p in rookies[:15]:
        nm = p.get("display_name") or p.get("name") or "?"
        print(f"  {nm:<28} {p.get('position'):<3} {p.get('team'):<4} proj={p.get('projection', p.get('proj', 'NA'))}")
    # Search by name
    print("\n--- Specific players ---")
    for nm in ["Cam Ward", "Cameron Ward", "Travis Hunter", "Abdul Carter", "Ashton Jeanty", "Tetairoa McMillan"]:
        for p in players:
            disp = (p.get("display_name") or p.get("name") or "")
            if nm.lower() in disp.lower():
                print(f"  {disp:<28} {p.get('position'):<3} {p.get('team'):<4} rookie={p.get('is_rookie')} proj={p.get('projection', p.get('proj', 'NA'))}")
                break
        else:
            print(f"  {nm}: NOT FOUND")
except Exception as e:
    print(f"  ERROR: {e}")
