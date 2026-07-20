#!/usr/bin/env python3
"""Import historical human-mock ADP distributions from FFC.

Historical archives are stored locally under data/ (gitignored). A request
manifest and quality profile make unavailable or silently mismatched snapshots
visible instead of substituting another season or league size.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data.ffc_adp import (  # noqa: E402
    SUPPORTED_SCORING,
    SnapshotKey,
    SnapshotUnavailable,
    fetch_payload,
    normalize_snapshot,
    profile_snapshots,
    read_table,
    replace_snapshots,
    write_table,
)


def main() -> None:
    current_year = datetime.now(timezone.utc).year
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=list(range(max(2007, current_year - 5), current_year + 1)),
    )
    parser.add_argument(
        "--scoring",
        nargs="+",
        choices=SUPPORTED_SCORING,
        default=list(SUPPORTED_SCORING),
    )
    parser.add_argument("--teams", nargs="+", type=int, default=[12])
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "data" / "ffc_adp_distributions.parquet",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=REPO / "data" / "ffc_adp_import_manifest.csv",
    )
    parser.add_argument(
        "--profile-out",
        type=Path,
        default=REPO / "data" / "ffc_adp_quality_profile.csv",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=REPO / "data" / "ffc_adp_raw",
    )
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any requested snapshot is unavailable or rejected",
    )
    args = parser.parse_args()

    fetched_at = datetime.now(timezone.utc)
    import_run_id = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    frames: list[pd.DataFrame] = []
    manifest_rows = []
    args.raw_dir.mkdir(parents=True, exist_ok=True)

    keys = sorted(
        SnapshotKey(season, scoring, teams)
        for season in set(args.seasons)
        for scoring in set(args.scoring)
        for teams in set(args.teams)
    )
    for index, key in enumerate(keys, start=1):
        status = "imported"
        error = ""
        rows = 0
        total_drafts = 0
        source_start_date = ""
        source_end_date = ""
        try:
            payload = fetch_payload(key)
            raw_path = args.raw_dir / f"{key.slug}.json"
            raw_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
            frame = normalize_snapshot(key, payload, fetched_at=fetched_at)
            profile = profile_snapshots(frame).iloc[0]
            if profile["quality_status"] == "reject":
                raise ValueError(f"normalized snapshot failed quality checks: {profile.to_dict()}")
            if profile["quality_status"] == "warn":
                status = "imported_with_warnings"
            frames.append(frame)
            rows = len(frame)
            total_drafts = int(profile["total_drafts"])
            source_start_date = profile["source_start_date"]
            source_end_date = profile["source_end_date"]
        except SnapshotUnavailable as exc:
            status = "unavailable"
            error = str(exc)
        except Exception as exc:
            status = "rejected"
            error = str(exc)

        manifest_rows.append(
            {
                "import_run_id": import_run_id,
                "requested_season": key.season,
                "requested_scoring": key.scoring,
                "requested_teams": key.teams,
                "status": status,
                "rows": rows,
                "total_drafts": total_drafts,
                "source_start_date": source_start_date,
                "source_end_date": source_end_date,
                "source_url": key.url,
                "fetched_at": fetched_at.isoformat(),
                "error": error,
            }
        )
        print(
            f"[{index:>2}/{len(keys)}] {key.slug}: {status} "
            f"({rows:,} players; {total_drafts:,} drafts)"
        )
        if args.request_delay and index < len(keys):
            time.sleep(max(0.0, args.request_delay))

    incoming = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not incoming.empty:
        complete = replace_snapshots(read_table(args.out), incoming)
        write_table(complete, args.out)
        profile = profile_snapshots(complete)
    else:
        complete = read_table(args.out)
        profile = profile_snapshots(complete)

    manifest = pd.DataFrame(manifest_rows)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    if args.manifest_out.exists():
        prior_manifest = pd.read_csv(args.manifest_out)
        if "import_run_id" not in prior_manifest:
            prior_manifest.insert(0, "import_run_id", "legacy")
        stored_manifest = pd.concat([prior_manifest, manifest], ignore_index=True)
    else:
        stored_manifest = manifest
    stored_manifest.to_csv(args.manifest_out, index=False)
    profile.to_csv(args.profile_out, index=False)

    accepted = manifest[manifest["status"].str.startswith("imported")]
    unavailable = manifest[manifest["status"].eq("unavailable")]
    rejected = manifest[manifest["status"].eq("rejected")]
    print(f"\nStored {len(complete):,} player distributions -> {args.out}")
    print(f"Imported {len(accepted)}/{len(manifest)} requested snapshots")
    print(f"Unavailable: {len(unavailable)}; rejected by quality gates: {len(rejected)}")
    print("Attribution: Fantasy Football Calculator (fantasyfootballcalculator.com)")

    if not len(accepted) and len(rejected) == len(manifest):
        raise SystemExit(2)
    if args.strict and (len(unavailable) or len(rejected)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
