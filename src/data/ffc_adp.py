"""Fantasy Football Calculator ADP-distribution ingestion.

The existing model uses mean ADP. Scarcity and next-turn availability also
need the observed dispersion around that mean: standard deviation, earliest
pick, latest pick, and the number of human selections behind the estimate.

Source documentation:
https://help.fantasyfootballcalculator.com/article/42-adp-rest-api
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse
import urllib.request

import pandas as pd


API_ROOT = "https://fantasyfootballcalculator.com/api/v1/adp"
SOURCE = "fantasy_football_calculator"
SCHEMA_VERSION = 1
SUPPORTED_SCORING = ("standard", "half-ppr", "ppr", "2qb")
SCORING_META_TOKENS = {
    "standard": {"standard", "nonppr"},
    "half-ppr": {"halfppr"},
    "ppr": {"ppr"},
    "2qb": {"2qb"},
}
POSITION_ALIASES = {"PK": "K", "DST": "DEF"}

SNAPSHOT_COLUMNS = [
    "schema_version",
    "source",
    "source_player_id",
    "player_name",
    "position",
    "source_position",
    "nfl_team",
    "bye_week",
    "season",
    "scoring",
    "teams",
    "rounds",
    "total_drafts",
    "adp",
    "adp_formatted",
    "adp_sd",
    "earliest_pick",
    "latest_pick",
    "times_drafted",
    "source_start_date",
    "source_end_date",
    "source_url",
    "fetched_at",
]


class SnapshotUnavailable(RuntimeError):
    """The provider has no archive for a requested snapshot."""


@dataclass(frozen=True, order=True)
class SnapshotKey:
    season: int
    scoring: str = "ppr"
    teams: int = 12

    def __post_init__(self) -> None:
        if self.scoring not in SUPPORTED_SCORING:
            raise ValueError(
                f"Unsupported scoring {self.scoring!r}; choose from {SUPPORTED_SCORING}"
            )
        if self.season < 2007:
            raise ValueError("FFC historical ADP begins in 2007")
        if self.teams < 4 or self.teams > 32:
            raise ValueError("teams must be between 4 and 32")

    @property
    def url(self) -> str:
        query = urllib.parse.urlencode({"teams": self.teams, "year": self.season})
        return f"{API_ROOT}/{self.scoring}?{query}"

    @property
    def slug(self) -> str:
        return f"{self.season}_{self.scoring}_{self.teams}tm"


def fetch_payload(key: SnapshotKey, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch one provider response without relabeling or fallback behavior."""
    request = urllib.request.Request(
        key.url,
        headers={"User-Agent": "OverADP historical ADP research importer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _number(value: Any, *, integer: bool = False) -> float | int | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return int(parsed) if integer else float(parsed)


def validate_payload(
    key: SnapshotKey,
    payload: dict[str, Any],
    *,
    min_players: int = 40,
) -> None:
    """Reject missing or silently relabeled provider responses."""
    if _token(payload.get("status")) != "success":
        message = payload.get("errors") or payload.get("error") or "no data"
        raise SnapshotUnavailable(f"{key.slug}: {message}")

    meta = payload.get("meta") or {}
    players = payload.get("players") or []
    actual_teams = _number(meta.get("teams"), integer=True)
    if actual_teams != key.teams:
        raise ValueError(
            f"{key.slug}: provider returned {actual_teams}-team data for a "
            f"{key.teams}-team request"
        )

    actual_scoring = _token(meta.get("type"))
    if actual_scoring not in SCORING_META_TOKENS[key.scoring]:
        raise ValueError(
            f"{key.slug}: provider returned scoring type {meta.get('type')!r}"
        )

    period_end = pd.to_datetime(meta.get("end_date"), errors="coerce")
    if pd.isna(period_end) or int(period_end.year) != key.season:
        raise ValueError(
            f"{key.slug}: source period {meta.get('end_date')!r} does not match season"
        )

    total_drafts = _number(meta.get("total_drafts"), integer=True)
    rounds = _number(meta.get("rounds"), integer=True)
    if total_drafts is None or total_drafts <= 0:
        raise ValueError(f"{key.slug}: invalid total_drafts")
    if rounds is None or rounds <= 0:
        raise ValueError(f"{key.slug}: invalid rounds")
    if len(players) < min_players:
        raise ValueError(
            f"{key.slug}: only {len(players)} player rows; expected at least {min_players}"
        )


def normalize_snapshot(
    key: SnapshotKey,
    payload: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
    min_players: int = 40,
) -> pd.DataFrame:
    """Normalize and validate one season/format/team-size snapshot."""
    validate_payload(key, payload, min_players=min_players)
    meta = payload["meta"]
    timestamp = fetched_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    rows = []
    for player in payload["players"]:
        source_position = str(player.get("position") or "").upper().strip()
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE,
                "source_player_id": str(player.get("player_id") or ""),
                "player_name": str(player.get("name") or "").strip(),
                "position": POSITION_ALIASES.get(source_position, source_position),
                "source_position": source_position,
                "nfl_team": str(player.get("team") or "").upper().strip(),
                "bye_week": _number(player.get("bye"), integer=True),
                "season": key.season,
                "scoring": key.scoring,
                "teams": key.teams,
                "rounds": int(meta["rounds"]),
                "total_drafts": int(meta["total_drafts"]),
                "adp": _number(player.get("adp")),
                "adp_formatted": str(player.get("adp_formatted") or ""),
                "adp_sd": _number(player.get("stdev")),
                "earliest_pick": _number(player.get("high"), integer=True),
                "latest_pick": _number(player.get("low"), integer=True),
                "times_drafted": _number(player.get("times_drafted"), integer=True),
                "source_start_date": meta.get("start_date"),
                "source_end_date": meta.get("end_date"),
                "source_url": key.url,
                "fetched_at": timestamp.astimezone(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)


def profile_snapshots(frame: pd.DataFrame) -> pd.DataFrame:
    """Return high-signal quality metrics at the intended snapshot grain."""
    columns = [
        "season",
        "scoring",
        "teams",
        "rows",
        "total_drafts",
        "source_start_date",
        "source_end_date",
        "duplicate_player_ids",
        "missing_key_rows",
        "invalid_adp_rows",
        "invalid_sd_rows",
        "invalid_bounds_rows",
        "invalid_draft_count_rows",
        "core_position_rows",
        "quality_status",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    required = set(SNAPSHOT_COLUMNS)
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Snapshot data is missing columns: {missing_columns}")

    profiles = []
    group_cols = ["season", "scoring", "teams"]
    for key, group in frame.groupby(group_cols, dropna=False, sort=True):
        adp = pd.to_numeric(group["adp"], errors="coerce")
        sd = pd.to_numeric(group["adp_sd"], errors="coerce")
        earliest = pd.to_numeric(group["earliest_pick"], errors="coerce")
        latest = pd.to_numeric(group["latest_pick"], errors="coerce")
        times = pd.to_numeric(group["times_drafted"], errors="coerce")
        total = pd.to_numeric(group["total_drafts"], errors="coerce")
        missing_keys = group[["source_player_id", "player_name", "position"]].apply(
            lambda column: column.astype(str).str.strip().eq("") | column.isna()
        ).any(axis=1)
        duplicate_ids = group.duplicated("source_player_id", keep=False)
        invalid_adp = adp.isna() | adp.le(0)
        invalid_sd = sd.isna() | sd.lt(0)
        invalid_bounds = (
            earliest.isna()
            | latest.isna()
            | earliest.le(0)
            | latest.lt(earliest)
            | adp.lt(earliest)
            | adp.gt(latest)
        )
        invalid_counts = times.isna() | times.le(0) | total.isna() | times.gt(total)
        hard_failures = (
            int(duplicate_ids.sum())
            + int(missing_keys.sum())
            + int(invalid_adp.sum())
            + int(invalid_sd.sum())
            + int(invalid_bounds.sum())
        )
        warnings = int(invalid_counts.sum())
        status = "reject" if hard_failures else "warn" if warnings else "pass"
        profiles.append(
            {
                "season": key[0],
                "scoring": key[1],
                "teams": key[2],
                "rows": len(group),
                "total_drafts": int(total.max()),
                "source_start_date": group["source_start_date"].iloc[0],
                "source_end_date": group["source_end_date"].iloc[0],
                "duplicate_player_ids": int(duplicate_ids.sum()),
                "missing_key_rows": int(missing_keys.sum()),
                "invalid_adp_rows": int(invalid_adp.sum()),
                "invalid_sd_rows": int(invalid_sd.sum()),
                "invalid_bounds_rows": int(invalid_bounds.sum()),
                "invalid_draft_count_rows": int(invalid_counts.sum()),
                "core_position_rows": int(
                    group["position"].isin(["QB", "RB", "WR", "TE"]).sum()
                ),
                "quality_status": status,
            }
        )
    return pd.DataFrame(profiles, columns=columns)


def replace_snapshots(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Atomically replace complete snapshot partitions, then deduplicate rows."""
    if incoming.empty:
        return existing.copy()
    if existing.empty:
        combined = incoming.copy()
    else:
        keys = set(
            incoming[["season", "scoring", "teams"]]
            .itertuples(index=False, name=None)
        )
        existing_keys = existing[["season", "scoring", "teams"]].apply(tuple, axis=1)
        combined = pd.concat(
            [existing.loc[~existing_keys.isin(keys)], incoming], ignore_index=True
        )
    return (
        combined.drop_duplicates(
            ["season", "scoring", "teams", "source_player_id"], keep="last"
        )
        .sort_values(["season", "scoring", "teams", "adp", "source_player_id"])
        .reset_index(drop=True)
    )


def enrich_board_with_adp_distribution(
    board: pd.DataFrame,
    distributions: pd.DataFrame,
    *,
    scoring: str,
    source_teams: int = 12,
    suffix: str | None = None,
    nearest_neighbors: int = 25,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach point-in-time or prior-season ADP dispersion to a draft board.

    Exact same-season matches use the observed preseason snapshot. Unmatched
    players use only earlier seasons, matched by position and nearby mean ADP.
    Pick bounds are stored as offsets and recentered on the board's own ADP so
    mixing two market sources does not silently replace the board's mean rank.
    """
    if board.empty:
        return board.copy(), {
            "season": None,
            "scoring": scoring,
            "source_teams": source_teams,
            "rows": 0,
            "priced_rows": 0,
            "observed_rows": 0,
            "observed_priced_rows": 0,
            "imputed_rows": 0,
            "missing_rows": 0,
        }
    if scoring not in SUPPORTED_SCORING:
        raise ValueError(f"Unsupported scoring {scoring!r}")
    required_board = {"season", "player_name", "position", "adp"}
    missing_board = sorted(required_board - set(board.columns))
    if missing_board:
        raise ValueError(f"Board is missing columns: {missing_board}")
    seasons = pd.to_numeric(board["season"], errors="coerce").dropna().unique()
    if len(seasons) != 1:
        raise ValueError("Board enrichment requires exactly one season")
    target_season = int(seasons[0])

    required_market = {
        "season",
        "scoring",
        "teams",
        "player_name",
        "position",
        "adp",
        "adp_sd",
        "earliest_pick",
        "latest_pick",
    }
    missing_market = sorted(required_market - set(distributions.columns))
    if missing_market:
        raise ValueError(f"ADP distributions are missing columns: {missing_market}")

    # Reuse the project's accent/suffix/first-name normalization so joins agree
    # with the live ADP overlay and Sleeper entity resolution.
    from src.data.sleeper_rosters import _normalize_name

    market = distributions[
        distributions["scoring"].eq(scoring)
        & pd.to_numeric(distributions["teams"], errors="coerce").eq(source_teams)
    ].copy()
    market["_key"] = (
        market["player_name"].map(_normalize_name)
        + "|"
        + market["position"].astype(str).str.upper()
    )
    market["_early_offset"] = (
        pd.to_numeric(market["earliest_pick"], errors="coerce")
        - pd.to_numeric(market["adp"], errors="coerce")
    )
    market["_late_offset"] = (
        pd.to_numeric(market["latest_pick"], errors="coerce")
        - pd.to_numeric(market["adp"], errors="coerce")
    )

    current = market[market["season"].eq(target_season)].copy()
    if current["_key"].duplicated().any():
        duplicates = current.loc[current["_key"].duplicated(False), "_key"].unique()
        raise ValueError(
            f"Duplicate market keys for {target_season}/{scoring}: {duplicates[:5]}"
        )
    current = current.set_index("_key")

    label = suffix or scoring.replace("-", "_")
    sd_col = f"market_adp_sd_{label}"
    early_col = f"market_earliest_pick_{label}"
    late_col = f"market_latest_pick_{label}"
    source_col = f"market_distribution_source_{label}"

    result = board.copy()
    result["_market_key"] = (
        result["player_name"].map(_normalize_name)
        + "|"
        + result["position"].astype(str).str.upper()
    )
    board_adp = pd.to_numeric(result["adp"], errors="coerce")
    result[sd_col] = pd.to_numeric(
        result["_market_key"].map(current["adp_sd"]), errors="coerce"
    )
    early_offset = pd.to_numeric(
        result["_market_key"].map(current["_early_offset"]), errors="coerce"
    )
    late_offset = pd.to_numeric(
        result["_market_key"].map(current["_late_offset"]), errors="coerce"
    )
    observed = result[sd_col].notna()
    result[source_col] = "missing"
    result.loc[observed, source_col] = "observed"

    history = market[market["season"].lt(target_season)].copy()
    history["adp"] = pd.to_numeric(history["adp"], errors="coerce")
    history["adp_sd"] = pd.to_numeric(history["adp_sd"], errors="coerce")
    history = history.dropna(
        subset=["position", "adp", "adp_sd", "_early_offset", "_late_offset"]
    )
    missing_indices = result.index[~observed]
    for row_index in missing_indices:
        pos = str(result.at[row_index, "position"]).upper()
        mean_adp = board_adp.at[row_index]
        pool = history[history["position"].astype(str).str.upper().eq(pos)]
        if pool.empty or pd.isna(mean_adp):
            continue
        nearest = pool.assign(_distance=(pool["adp"] - mean_adp).abs()).nsmallest(
            max(1, int(nearest_neighbors)), "_distance"
        )
        if nearest.empty:
            continue
        result.at[row_index, sd_col] = float(nearest["adp_sd"].median())
        early_offset.at[row_index] = float(nearest["_early_offset"].median())
        late_offset.at[row_index] = float(nearest["_late_offset"].median())
        result.at[row_index, source_col] = "imputed_prior"

    result[sd_col] = pd.to_numeric(result[sd_col], errors="coerce").clip(0.5, 40.0)
    result[early_col] = board_adp + early_offset
    result[late_col] = board_adp + late_offset
    result[early_col] = pd.concat([result[early_col], board_adp], axis=1).min(axis=1)
    result[late_col] = pd.concat([result[late_col], board_adp], axis=1).max(axis=1)
    result = result.drop(columns="_market_key")
    result.attrs.clear()

    priced = board_adp.lt(200)
    source = result[source_col]
    coverage = {
        "season": target_season,
        "scoring": scoring,
        "source_teams": int(source_teams),
        "rows": len(result),
        "priced_rows": int(priced.sum()),
        "observed_rows": int(source.eq("observed").sum()),
        "observed_priced_rows": int((source.eq("observed") & priced).sum()),
        "imputed_rows": int(source.eq("imputed_prior").sum()),
        "missing_rows": int(source.eq("missing").sum()),
    }
    return result, coverage


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype={"source_player_id": "string"})
    return pd.read_parquet(path)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
