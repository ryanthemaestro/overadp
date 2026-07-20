#!/usr/bin/env python3
"""Fetch Sleeper draft settings and pick logs for policy training.

Sleeper does not expose a global draft index. Seed this script with draft IDs,
league IDs, or usernames/user IDs, and it will normalize complete NFL snake
drafts into two local tables:

  - data/sleeper_drafts.parquet
  - data/sleeper_draft_picks.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


API = "https://api.sleeper.app/v1"
REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"


@dataclass(frozen=True)
class DraftSeed:
    kind: str
    value: str


def api_get(path: str, sleep: float = 0.12) -> Any:
    url = f"{API}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "OverADP research draft importer"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if sleep:
        time.sleep(sleep)
    return data


def read_seed_file(path: Path) -> list[DraftSeed]:
    seeds: list[DraftSeed] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            kind, value = [x.strip() for x in line.split(",", 1)]
        elif ":" in line:
            kind, value = [x.strip() for x in line.split(":", 1)]
        else:
            kind, value = "draft_id", line
        seeds.append(DraftSeed(kind.lower().replace("-", "_"), value))
    return seeds


def sleeper_user_id(username_or_id: str) -> str | None:
    # Numeric user IDs work directly in draft endpoints. Usernames need lookup.
    if username_or_id.isdigit():
        return username_or_id
    user = api_get(f"/user/{urllib.parse.quote(username_or_id)}")
    if not user:
        return None
    return str(user.get("user_id") or "")


def discover_draft_ids(seeds: list[DraftSeed], seasons: list[int]) -> set[str]:
    draft_ids: set[str] = set()
    for seed in seeds:
        if seed.kind in {"draft", "draft_id"}:
            draft_ids.add(seed.value)
        elif seed.kind in {"league", "league_id"}:
            drafts = api_get(f"/league/{seed.value}/drafts") or []
            draft_ids.update(str(d.get("draft_id")) for d in drafts if d.get("draft_id"))
        elif seed.kind in {"username", "user", "user_id"}:
            uid = sleeper_user_id(seed.value)
            if not uid:
                print(f"WARN: no Sleeper user found for {seed.value}", file=sys.stderr)
                continue
            for season in seasons:
                drafts = api_get(f"/user/{uid}/drafts/nfl/{season}") or []
                draft_ids.update(str(d.get("draft_id")) for d in drafts if d.get("draft_id"))
        else:
            print(f"WARN: unsupported seed type {seed.kind!r}", file=sys.stderr)
    return draft_ids


def setting(settings: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(settings.get(key, default) or 0)
    except Exception:
        return default


def normalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    settings = draft.get("settings") or {}
    metadata = draft.get("metadata") or {}
    draft_id = str(draft.get("draft_id") or "")
    return {
        "draft_id": draft_id,
        "league_id": str(draft.get("league_id") or ""),
        "season": int(draft.get("season") or 0),
        "season_type": draft.get("season_type"),
        "type": draft.get("type"),
        "status": draft.get("status"),
        "scoring_type": metadata.get("scoring_type"),
        "teams": setting(settings, "teams"),
        "rounds": setting(settings, "rounds"),
        "slots_qb": setting(settings, "slots_qb"),
        "slots_rb": setting(settings, "slots_rb"),
        "slots_wr": setting(settings, "slots_wr"),
        "slots_te": setting(settings, "slots_te"),
        "slots_flex": setting(settings, "slots_flex"),
        "slots_super_flex": setting(settings, "slots_super_flex"),
        "slots_k": setting(settings, "slots_k"),
        "slots_def": setting(settings, "slots_def"),
        "slots_bn": setting(settings, "slots_bn"),
        "pick_timer": setting(settings, "pick_timer"),
        "start_time": draft.get("start_time"),
        "created": draft.get("created"),
        "draft_order": json.dumps(draft.get("draft_order") or {}, sort_keys=True),
        "slot_to_roster_id": json.dumps(draft.get("slot_to_roster_id") or {}, sort_keys=True),
    }


def normalize_pick(pick: dict[str, Any], draft_row: dict[str, Any]) -> dict[str, Any]:
    metadata = pick.get("metadata") or {}
    player_id = str(pick.get("player_id") or metadata.get("player_id") or "")
    first = metadata.get("first_name") or ""
    last = metadata.get("last_name") or ""
    player_name = (f"{first} {last}").strip() or metadata.get("full_name") or ""
    return {
        "draft_id": draft_row["draft_id"],
        "league_id": draft_row["league_id"],
        "season": draft_row["season"],
        "scoring_type": draft_row["scoring_type"],
        "teams": draft_row["teams"],
        "rounds": draft_row["rounds"],
        "slots_qb": draft_row["slots_qb"],
        "slots_rb": draft_row["slots_rb"],
        "slots_wr": draft_row["slots_wr"],
        "slots_te": draft_row["slots_te"],
        "slots_flex": draft_row["slots_flex"],
        "slots_super_flex": draft_row["slots_super_flex"],
        "slots_bn": draft_row["slots_bn"],
        "pick_no": int(pick.get("pick_no") or 0),
        "round": int(pick.get("round") or 0),
        "draft_slot": int(pick.get("draft_slot") or 0),
        "roster_id": str(pick.get("roster_id") or ""),
        "picked_by": str(pick.get("picked_by") or ""),
        "player_id": player_id,
        "player_name": player_name,
        "position": metadata.get("position"),
        "team": metadata.get("team"),
        "is_keeper": pick.get("is_keeper"),
    }


def load_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        df.to_csv(path, index=False)
    else:
        df.to_parquet(path, index=False)


def append_dedup(new_df: pd.DataFrame, path: Path, subset: list[str]) -> pd.DataFrame:
    old = load_existing(path)
    if old.empty:
        out = new_df
    elif new_df.empty:
        out = old
    else:
        out = pd.concat([old, new_df], ignore_index=True)
    if not out.empty:
        out = out.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)
    write_table(out, path)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft-id", action="append", default=[])
    parser.add_argument("--league-id", action="append", default=[])
    parser.add_argument("--username", action="append", default=[])
    parser.add_argument("--user-id", action="append", default=[])
    parser.add_argument("--seed-file", type=Path)
    parser.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024, 2025])
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--csv", action="store_true", help="Write CSV instead of parquet")
    parser.add_argument("--include-incomplete", action="store_true")
    parser.add_argument("--max-drafts", type=int, default=0)
    args = parser.parse_args()

    seeds: list[DraftSeed] = []
    seeds.extend(DraftSeed("draft_id", x) for x in args.draft_id)
    seeds.extend(DraftSeed("league_id", x) for x in args.league_id)
    seeds.extend(DraftSeed("username", x) for x in args.username)
    seeds.extend(DraftSeed("user_id", x) for x in args.user_id)
    if args.seed_file:
        seeds.extend(read_seed_file(args.seed_file))
    if not seeds:
        raise SystemExit("Provide at least one --draft-id, --league-id, --username, --user-id, or --seed-file")

    draft_ids = sorted(discover_draft_ids(seeds, args.seasons))
    if args.max_drafts:
        draft_ids = draft_ids[: args.max_drafts]
    print(f"Discovered {len(draft_ids)} draft IDs")

    draft_rows: list[dict[str, Any]] = []
    pick_rows: list[dict[str, Any]] = []
    for i, draft_id in enumerate(draft_ids, start=1):
        draft = api_get(f"/draft/{draft_id}")
        if not draft:
            print(f"WARN: draft not found {draft_id}", file=sys.stderr)
            continue
        if draft.get("sport") != "nfl":
            continue
        if draft.get("type") != "snake":
            continue
        if not args.include_incomplete and draft.get("status") != "complete":
            continue
        row = normalize_draft(draft)
        picks = api_get(f"/draft/{draft_id}/picks") or []
        if not picks:
            continue
        draft_rows.append(row)
        pick_rows.extend(normalize_pick(p, row) for p in picks)
        if i % 25 == 0:
            print(f"Fetched {i}/{len(draft_ids)} drafts")

    suffix = ".csv" if args.csv else ".parquet"
    drafts_path = args.out_dir / f"sleeper_drafts{suffix}"
    picks_path = args.out_dir / f"sleeper_draft_picks{suffix}"
    drafts_df = append_dedup(pd.DataFrame(draft_rows), drafts_path, ["draft_id"])
    picks_df = append_dedup(pd.DataFrame(pick_rows), picks_path, ["draft_id", "pick_no", "player_id"])

    print(f"Wrote {len(drafts_df):,} drafts -> {drafts_path}")
    print(f"Wrote {len(picks_df):,} picks -> {picks_path}")
    if pick_rows:
        new = pd.DataFrame(pick_rows)
        print(
            new.groupby(["season", "teams", "slots_qb", "slots_rb", "slots_wr", "slots_flex"])
            .size()
            .reset_index(name="picks")
            .sort_values("picks", ascending=False)
            .head(20)
            .to_string(index=False)
        )


if __name__ == "__main__":
    main()
