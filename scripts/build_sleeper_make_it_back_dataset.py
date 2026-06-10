#!/usr/bin/env python3
"""Build supervised next-pick availability examples from Sleeper draft logs."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def norm_name(name: str) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", s)
    s = re.sub(r"[^a-z\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        df.to_csv(path, index=False)
    else:
        df.to_parquet(path, index=False)


def snake_next_pick(pick_no: int, draft_slot: int, teams: int, total_picks: int) -> int:
    for p in range(pick_no + 1, total_picks + 1):
        rnd = (p - 1) // teams + 1
        slot = ((p - 1) % teams) + 1
        if rnd % 2 == 0:
            slot = teams - slot + 1
        if slot == draft_slot:
            return p
    return total_picks + 1


def prepare_board(board_path: Path | None) -> pd.DataFrame:
    if not board_path:
        return pd.DataFrame()
    board = read_table(board_path)
    if board.empty:
        return board
    board = board.copy()
    board = board[board["position"].isin(SKILL_POSITIONS)]
    board["player_key"] = board["player_name"].map(norm_name) + "|" + board["position"].astype(str)
    if "adp" not in board.columns:
        board["adp"] = np.nan
    sort_cols = ["season", "adp"]
    ascending = [True, True]
    if "projected_points" in board.columns:
        sort_cols.append("projected_points")
        ascending.append(False)
    board = board.sort_values(sort_cols, ascending=ascending, na_position="last")
    return board.drop_duplicates(["season", "player_key"], keep="first").reset_index(drop=True)


def candidate_pool_for_draft(draft: pd.DataFrame, season_board: pd.DataFrame, total_picks: int) -> pd.DataFrame:
    picked = draft[["player_id", "player_name", "position", "pick_no"]].drop_duplicates("player_id").copy()
    picked = picked[picked["position"].isin(SKILL_POSITIONS)]
    picked["player_key"] = picked["player_name"].map(norm_name) + "|" + picked["position"].astype(str)
    pick_map = dict(zip(picked["player_key"], picked["pick_no"]))

    if season_board.empty:
        pool = picked.copy()
        pool["candidate_adp"] = np.nan
        pool["candidate_projected_points"] = np.nan
        pool["candidate_vbd"] = np.nan
        pool["candidate_model_rank"] = np.nan
        pool["candidate_adp_rank"] = np.nan
    else:
        cols = [
            "player_name",
            "position",
            "player_key",
            "adp",
            "projected_points",
            "vbd",
            "model_rank",
            "adp_rank",
        ]
        cols = [c for c in cols if c in season_board.columns]
        pool = season_board[cols].copy()
        pool = pool.rename(
            columns={
                "adp": "candidate_adp",
                "projected_points": "candidate_projected_points",
                "vbd": "candidate_vbd",
                "model_rank": "candidate_model_rank",
                "adp_rank": "candidate_adp_rank",
            }
        )
        pool["player_id"] = ""

    pool["actual_pick"] = pool["player_key"].map(pick_map).fillna(total_picks + 999).astype(int)
    return pool


def build_examples(picks: pd.DataFrame, max_candidates: int, draft_board: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = []
    required = {"draft_id", "pick_no", "draft_slot", "player_id", "position", "teams"}
    missing = required - set(picks.columns)
    if missing:
        raise ValueError(f"Missing required pick columns: {sorted(missing)}")

    picks = picks.copy()
    picks["pick_no"] = pd.to_numeric(picks["pick_no"], errors="coerce").fillna(0).astype(int)
    picks["draft_slot"] = pd.to_numeric(picks["draft_slot"], errors="coerce").fillna(0).astype(int)
    picks["teams"] = pd.to_numeric(picks["teams"], errors="coerce").fillna(0).astype(int)
    picks = picks[picks["pick_no"] > 0].sort_values(["draft_id", "pick_no"])

    for draft_id, draft in picks.groupby("draft_id", sort=False):
        draft = draft.sort_values("pick_no").reset_index(drop=True)
        teams = int(draft["teams"].iloc[0] or draft["draft_slot"].max())
        if teams <= 1:
            continue
        total_picks = int(draft["pick_no"].max())
        season = int(draft["season"].iloc[0] or 0)
        season_board = pd.DataFrame()
        if draft_board is not None and not draft_board.empty and "season" in draft_board.columns:
            season_board = draft_board[draft_board["season"].eq(season)].copy()
        pool = candidate_pool_for_draft(draft, season_board, total_picks)
        if pool.empty:
            continue

        for _, pick in draft.iterrows():
            pick_no = int(pick["pick_no"])
            draft_slot = int(pick["draft_slot"])
            if draft_slot <= 0:
                continue
            next_pick = snake_next_pick(pick_no, draft_slot, teams, total_picks)
            if next_pick <= pick_no + 1:
                continue
            available = pool[pool["actual_pick"] > pick_no].head(max_candidates)
            if available.empty:
                continue
            for _, cand in available.iterrows():
                actual_pick = int(cand["actual_pick"])
                rows.append(
                    {
                        "draft_id": draft_id,
                        "season": int(pick.get("season") or 0),
                        "scoring_type": pick.get("scoring_type"),
                        "teams": teams,
                        "rounds": int(pick.get("rounds") or 0),
                        "slots_qb": int(pick.get("slots_qb") or 0),
                        "slots_rb": int(pick.get("slots_rb") or 0),
                        "slots_wr": int(pick.get("slots_wr") or 0),
                        "slots_te": int(pick.get("slots_te") or 0),
                        "slots_flex": int(pick.get("slots_flex") or 0),
                        "slots_super_flex": int(pick.get("slots_super_flex") or 0),
                        "slots_bn": int(pick.get("slots_bn") or 0),
                        "current_pick": pick_no,
                        "draft_slot": draft_slot,
                        "next_pick": next_pick,
                        "picks_until_next": next_pick - pick_no,
                        "candidate_player_id": cand.get("player_id", ""),
                        "candidate_player_name": cand.get("player_name", ""),
                        "candidate_position": cand.get("position", ""),
                        "candidate_actual_pick": actual_pick if actual_pick <= total_picks else np.nan,
                        "candidate_rank_available": int(len(rows) + 1),
                        "candidate_adp": cand.get("candidate_adp", np.nan),
                        "candidate_projected_points": cand.get("candidate_projected_points", np.nan),
                        "candidate_vbd": cand.get("candidate_vbd", np.nan),
                        "candidate_model_rank": cand.get("candidate_model_rank", np.nan),
                        "candidate_adp_rank": cand.get("candidate_adp_rank", np.nan),
                        "will_be_gone": int(pick_no < actual_pick < next_pick),
                        "will_make_it_back": int(actual_pick >= next_pick),
                    }
                )
    return pd.DataFrame(rows)


def enrich_with_board(examples: pd.DataFrame, board_path: Path) -> pd.DataFrame:
    if examples.empty:
        return examples
    board = read_table(board_path)
    if board.empty:
        return examples
    keep = [
        "season",
        "player_name",
        "position",
        "adp",
        "projected_points",
        "vbd",
        "model_rank",
        "adp_rank",
    ]
    keep = [c for c in keep if c in board.columns]
    board = board[keep].copy()
    board["player_key"] = board["player_name"].map(norm_name) + "|" + board["position"].astype(str)
    board = board.sort_values(["season", "adp"], na_position="last").drop_duplicates(["season", "player_key"])
    board = board.rename(
        columns={
            "adp": "candidate_adp",
            "projected_points": "candidate_projected_points",
            "vbd": "candidate_vbd",
            "model_rank": "candidate_model_rank",
            "adp_rank": "candidate_adp_rank",
        }
    )
    examples = examples.copy()
    examples["player_key"] = examples["candidate_player_name"].map(norm_name) + "|" + examples["candidate_position"].astype(str)
    out = examples.merge(
        board.drop(columns=[c for c in ["player_name", "position"] if c in board.columns]),
        on=["season", "player_key"],
        how="left",
    )
    out = out.drop(columns=["player_key"])
    if "candidate_adp" in out.columns:
        out["adp_to_pick"] = pd.to_numeric(out["candidate_adp"], errors="coerce") - out["current_pick"]
        out["adp_to_next_pick"] = pd.to_numeric(out["candidate_adp"], errors="coerce") - out["next_pick"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--picks", type=Path, default=DATA_DIR / "sleeper_draft_picks.parquet")
    parser.add_argument("--out", type=Path, default=DATA_DIR / "sleeper_make_it_back.parquet")
    parser.add_argument("--board", type=Path, help="Optional season draft board with ADP/projection/VBD features")
    parser.add_argument("--max-candidates", type=int, default=72)
    args = parser.parse_args()

    picks = read_table(args.picks)
    draft_board = prepare_board(args.board)
    examples = build_examples(picks, args.max_candidates, draft_board)
    if not examples.empty:
        # Rank must reset within each draft state, not across the entire dataset.
        examples["candidate_rank_available"] = (
            examples.groupby(["draft_id", "current_pick"]).cumcount() + 1
        )
    if args.board and "candidate_adp" not in examples.columns:
        examples = enrich_with_board(examples, args.board)
    elif "candidate_adp" in examples.columns:
        examples["adp_to_pick"] = pd.to_numeric(examples["candidate_adp"], errors="coerce") - examples["current_pick"]
        examples["adp_to_next_pick"] = pd.to_numeric(examples["candidate_adp"], errors="coerce") - examples["next_pick"]
    write_table(examples, args.out)
    print(f"Wrote {len(examples):,} examples -> {args.out}")
    if not examples.empty:
        print(
            examples.groupby(["candidate_position"])
            .agg(
                examples=("will_be_gone", "size"),
                gone_rate=("will_be_gone", "mean"),
                avg_picks_until_next=("picks_until_next", "mean"),
            )
            .reset_index()
            .round(4)
            .to_string(index=False)
        )


if __name__ == "__main__":
    main()
