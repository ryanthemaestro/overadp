"""Private, no-echo CollegeFootballData API key entry. Stdlib only. The key is never printed."""
import getpass, json, os, sys, urllib.request, urllib.error
from pathlib import Path

KEY_FILE = Path(__file__).resolve().parent / ".secrets" / "cfbd_key"

def main() -> int:
    print("Paste your CollegeFootballData API key below, then press Enter.")
    print("Nothing will appear while you paste. The key is never printed.")
    key = getpass.getpass("CFBD API key (hidden): ").strip()
    if not key or " " in key or key.lower().startswith(("bearer", "export", "api_key")):
        print("That doesn't look like just the key. Copy only the key's value. Nothing was saved.")
        return 1
    req = urllib.request.Request("https://api.collegefootballdata.com/teams/fbs?year=2024",
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = r.status == 200 and len(json.load(r)) > 100
    except urllib.error.HTTPError as e:
        print(f"CollegeFootballData rejected the key (HTTP {e.code}). Nothing was saved.")
        return 1
    except Exception:
        print("Couldn't reach CollegeFootballData to check the key. Nothing was saved.")
        return 1
    if not ok:
        print("Unexpected response from CollegeFootballData. Nothing was saved.")
        return 1
    os.umask(0o077)
    KEY_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    KEY_FILE.write_text(key + "\n")
    KEY_FILE.chmod(0o600)
    (KEY_FILE.parent / ".gitignore").write_text("*\n")
    print("Key verified and saved privately. You can tell Claude it's done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
