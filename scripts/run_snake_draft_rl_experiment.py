#!/usr/bin/env python3
"""Train/evaluate a Puffer-compatible snake-draft RL policy.

This experiment asks a different question than point-projection modeling:
can a learned draft policy build a better roster than ADP/VBD/CatBoost
heuristics when opponents draft realistically?

MVP scope:
  - Skill positions only: QB/RB/WR/TE
  - 10/12/14-team snake draft support
  - Fixed or randomized roster formats
  - Opponents are scripted ADP drafters with noise and roster-need bonuses
  - Reward is actual held-out starter/flex fantasy points
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.run_catboost_feature_experiments import build_frame
from src.models.catboost_model import CatBoostModel, POSITION_CATBOOST_PARAMS, POSITION_TEMPORAL_WEIGHTS
from src.models.pipeline import OFFENSIVE_POSITIONS, _numeric_feature_cols, get_position_features
from src.optimizer.draft_strategy import (
    compute_vbd,
    conditional_probability_gone,
    expected_best_available_value,
)
from src.utils.config import get_roster_config


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
STARTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}
DEFAULT_MAX_BY_POS = {"QB": 2, "RB": 6, "WR": 7, "TE": 2}
POSITION_ORDER = {p: i for i, p in enumerate(SKILL_POSITIONS)}
DEFAULT_FLEX_ELIGIBLE = ("RB", "WR", "TE")


def _mae_safe(values: Iterable[float]) -> float:
    arr = np.asarray(list(values), dtype=float)
    return float(np.mean(arr)) if len(arr) else 0.0


@dataclass
class DraftResult:
    season: int
    strategy: str
    seed: int
    draft_slot: int
    roster_format: str
    num_teams: int
    rounds: int
    qb_slots: int
    rb_slots: int
    wr_slots: int
    te_slots: int
    flex_slots: int
    bench_slots: int
    starter_points: float
    total_points: float
    league_rank: int
    field_avg_starter_points: float
    picks: str


@dataclass(frozen=True)
class RosterFormat:
    name: str
    num_teams: int
    starter_slots: dict[str, int]
    flex_eligible: tuple[str, ...] = DEFAULT_FLEX_ELIGIBLE
    bench: int = 7

    @property
    def flex_slots(self) -> int:
        return int(self.starter_slots.get("FLEX", 0))

    @property
    def skill_starter_slots(self) -> int:
        return int(sum(self.starter_slots.get(p, 0) for p in SKILL_POSITIONS))

    @property
    def rounds(self) -> int:
        return max(1, self.skill_starter_slots + self.flex_slots + int(self.bench))

    @property
    def max_by_pos(self) -> dict[str, int]:
        bench = int(self.bench)
        starters = self.starter_slots
        flex = self.flex_slots
        return {
            "QB": max(starters.get("QB", 1) + 1, 2),
            "RB": max(starters.get("RB", 2) + flex + math.ceil(bench * 0.45), starters.get("RB", 2) + flex),
            "WR": max(starters.get("WR", 2) + flex + math.ceil(bench * 0.50), starters.get("WR", 2) + flex),
            "TE": max(starters.get("TE", 1) + 1, 2),
        }

    def to_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "num_teams": self.num_teams,
                "starter_slots": self.starter_slots,
                "flex_eligible": self.flex_eligible,
                "bench": self.bench,
                "rounds": self.rounds,
                "max_by_pos": self.max_by_pos,
            },
            sort_keys=True,
        )


@dataclass(frozen=True)
class ScarcityV2Weights:
    """Auditable coefficients for the ADP-anchored VONA policy."""

    adp: float = 1.0
    projected: float = 0.10
    vbd: float = 0.34
    starter_need: float = 18.0
    flex_need: float = 9.0
    late_need: float = 10.0
    vona: float = 0.75
    adp_value: float = 0.45
    reach: float = 1.10
    depth: float = 3.0


DEFAULT_SCARCITY_V2_WEIGHTS = ScarcityV2Weights()


@dataclass
class SimBoard:
    df: pd.DataFrame
    season: int
    player_names: np.ndarray
    positions: np.ndarray
    pos_codes: np.ndarray
    fantasy_points: np.ndarray
    projected_points: np.ndarray
    vbd: np.ndarray
    adp: np.ndarray
    pts_lag1: np.ndarray
    fp_per_game_lag1: np.ndarray
    is_rookie: np.ndarray
    is_2nd_year: np.ndarray
    queue_order: np.ndarray


def get_sim_board(board: pd.DataFrame) -> SimBoard:
    cached = board.attrs.get("_sim_board")
    if cached is not None:
        return cached

    df = board.reset_index(drop=True)
    positions = df["position"].fillna("").astype(str).to_numpy()
    pos_codes = np.asarray([POSITION_ORDER.get(p, -1) for p in positions], dtype=np.int16)

    def col(name: str, default: float = 0.0) -> np.ndarray:
        if name in df.columns:
            arr = pd.to_numeric(df[name], errors="coerce").fillna(default).to_numpy(dtype=np.float32)
        else:
            arr = np.full(len(df), default, dtype=np.float32)
        return np.nan_to_num(arr, nan=default, posinf=default, neginf=default)

    projected = col("projected_points")
    vbd = col("vbd")
    adp = np.clip(col("adp", 200.0), 1.0, 250.0)
    queue_score = -adp + 0.20 * projected + 0.45 * vbd
    sim = SimBoard(
        df=df,
        season=int(df["season"].iloc[0]),
        player_names=df["player_name"].fillna(df["player_id"]).astype(str).to_numpy(),
        positions=positions,
        pos_codes=pos_codes,
        fantasy_points=np.clip(col("fantasy_points"), 0.0, None),
        projected_points=np.clip(projected, 0.0, None),
        vbd=np.clip(vbd, 0.0, None),
        adp=adp,
        pts_lag1=col("pts_lag1"),
        fp_per_game_lag1=col("fp_per_game_lag1"),
        is_rookie=col("is_rookie"),
        is_2nd_year=col("is_2nd_year"),
        queue_order=np.argsort(-queue_score),
    )
    board.attrs["_sim_board"] = sim
    return sim


class SnakeDraftEnv:
    """Minimal Gymnasium env for PufferLib wrapper compatibility checks."""

    metadata = {"render_modes": []}

    def __init__(self, board: pd.DataFrame, shortlist_size: int = 32, seed: int = 42):
        try:
            import gymnasium as gym
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("gymnasium is required for Puffer smoke check") from exc

        self.board = board.reset_index(drop=True)
        self.shortlist_size = shortlist_size
        self.rng = np.random.default_rng(seed)
        self.observation_space = gym.spaces.Box(
            low=-10,
            high=10,
            shape=(shortlist_size, 12),
            dtype=np.float32,
        )
        self.action_space = gym.spaces.Discrete(shortlist_size)
        self._available = np.ones(len(self.board), dtype=bool)

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self._available[:] = True
        return self._obs(), {}

    def step(self, action: int):
        candidates = np.flatnonzero(self._available)[: self.shortlist_size]
        if len(candidates):
            idx = candidates[min(int(action), len(candidates) - 1)]
            self._available[idx] = False
        return self._obs(), 0.0, False, False, {}

    def _obs(self) -> np.ndarray:
        avail = self.board[self._available].head(self.shortlist_size)
        obs = np.zeros(self.observation_space.shape, dtype=np.float32)
        for i, (_, row) in enumerate(avail.iterrows()):
            pos = row["position"]
            obs[i, 0] = float(row.get("projected_points", 0)) / 300.0
            obs[i, 1] = float(row.get("vbd", 0)) / 150.0
            obs[i, 2] = min(float(row.get("adp", 200)), 250.0) / 250.0
            for p, j in POSITION_ORDER.items():
                obs[i, 3 + j] = 1.0 if pos == p else 0.0
        return obs


def puffer_smoke_check(board: pd.DataFrame, shortlist_size: int) -> str:
    try:
        import pufferlib.emulation
    except Exception as exc:
        return f"pufferlib unavailable: {exc}"

    try:
        env = SnakeDraftEnv(board, shortlist_size=shortlist_size)
        wrapped = pufferlib.emulation.GymnasiumPufferEnv(env)
        obs, _ = wrapped.reset()
        action = wrapped.action_space.sample()
        wrapped.step(action)
        return f"wrapped snake env observation shape {tuple(np.asarray(obs).shape)}"
    except Exception as exc:
        return f"pufferlib import ok, wrapper failed: {exc}"


def load_or_build_frame(cache_path: Optional[Path], refresh_cache: bool) -> pd.DataFrame:
    if cache_path and cache_path.exists() and not refresh_cache:
        print(f"Loading cached frame: {cache_path}")
        return pd.read_parquet(cache_path)

    df = build_frame()
    if cache_path:
        df.to_parquet(cache_path, index=False)
        print(f"Wrote cached frame: {cache_path}")
    return df


def clean_feature_matrix(X: pd.DataFrame) -> pd.DataFrame:
    return X.replace([np.inf, -np.inf], np.nan).fillna(0)


def train_catboost_predictions(df: pd.DataFrame, target_season: int) -> pd.DataFrame:
    """Create draft-day projected points for one target season.

    Models train on seasons strictly before target_season, then predict players
    in target_season. Actual target-season points are retained only for scoring.
    """
    parts = []
    for pos in SKILL_POSITIONS:
        pos_df = df[df["position"] == pos].copy()
        feat_cols = get_position_features(pos, list(df.columns))
        feat_cols = _numeric_feature_cols(pos_df, feat_cols)
        if not feat_cols:
            continue

        train = pos_df[pos_df["season"] < target_season].copy()
        test = pos_df[pos_df["season"] == target_season].copy()
        valid = train["fantasy_points"].notna() & np.isfinite(train["fantasy_points"])
        train = train[valid]
        if train.empty or test.empty:
            continue

        model = CatBoostModel(**POSITION_CATBOOST_PARAMS.get(pos, {}))
        X_train = clean_feature_matrix(train[feat_cols])
        y_train = train["fantasy_points"]
        tw = POSITION_TEMPORAL_WEIGHTS.get(pos, 0.0)
        sample_weight = None
        if tw > 0:
            years_ago = train["season"].max() - train["season"]
            sample_weight = np.exp(-tw * years_ago)
        model.fit(X_train, y_train, sample_weight=sample_weight)
        preds = model.predict(clean_feature_matrix(test[feat_cols]))

        out = test.copy()
        out["projected_points"] = np.clip(preds, 0, None)
        parts.append(out)

    if not parts:
        return pd.DataFrame()

    board = pd.concat(parts, ignore_index=True)
    keep_cols = [
        "player_id",
        "player_name",
        "position",
        "team",
        "season",
        "fantasy_points",
        "projected_points",
        "adp",
        "pts_lag1",
        "fp_per_game_lag1",
        "games_lag1",
        "age",
        "is_rookie",
        "is_2nd_year",
    ]
    keep_cols = [c for c in keep_cols if c in board.columns]
    board = board[keep_cols].copy()
    board["adp"] = pd.to_numeric(board.get("adp", 200), errors="coerce").fillna(200).clip(1, 250)
    board["fantasy_points"] = pd.to_numeric(board["fantasy_points"], errors="coerce").fillna(0).clip(lower=0)
    board["projected_points"] = pd.to_numeric(board["projected_points"], errors="coerce").fillna(0).clip(lower=0)
    board = board[board["projected_points"].notna()]
    board = board[board["position"].isin(SKILL_POSITIONS)].copy()
    board = board.sort_values(["adp", "projected_points"], ascending=[True, False]).drop_duplicates("player_id")
    board = board.reset_index(drop=True)

    vbd_input = board.rename(columns={"projected_points": "_projected_points"}).copy()
    vbd_input["projected_points"] = vbd_input["_projected_points"]
    vbd = compute_vbd(vbd_input, num_teams=12, roster_config=get_roster_config())
    board["vbd"] = pd.to_numeric(vbd["vbd"], errors="coerce").fillna(0).to_numpy()
    board["model_rank"] = board["projected_points"].rank(ascending=False, method="first")
    board["adp_rank"] = board["adp"].rank(ascending=True, method="first")
    return board


def load_or_build_boards(df: pd.DataFrame, seasons: list[int], cache_path: Optional[Path], refresh: bool) -> dict[int, pd.DataFrame]:
    boards = {}
    cached_seasons: set[int] = set()
    if cache_path and cache_path.exists() and not refresh:
        print(f"Loading cached draft boards: {cache_path}")
        raw = pd.read_parquet(cache_path)
        boards = {int(s): g.reset_index(drop=True) for s, g in raw.groupby("season")}
        cached_seasons = set(boards)

    for season in [s for s in seasons if s not in boards]:
        print(f"Building draft board for {season}...")
        board = train_catboost_predictions(df, season)
        if not board.empty:
            boards[season] = board

    if cache_path and boards and (refresh or any(s not in cached_seasons for s in seasons)):
        out = pd.concat([boards[s] for s in sorted(boards)], ignore_index=True)
        out.to_parquet(cache_path, index=False)
        print(f"Wrote cached draft boards: {cache_path}")
    return boards


def snake_pick_order(num_teams: int, rounds: int) -> list[int]:
    order = []
    for r in range(rounds):
        teams = list(range(num_teams))
        if r % 2 == 1:
            teams.reverse()
        order.extend(teams)
    return order


def count_positions(roster: list[int], board: pd.DataFrame) -> dict[str, int]:
    counts = {p: 0 for p in SKILL_POSITIONS}
    if not roster:
        return counts
    sim = get_sim_board(board)
    for code in sim.pos_codes[np.asarray(roster, dtype=int)]:
        if code >= 0:
            pos = SKILL_POSITIONS[int(code)]
            counts[pos] = counts.get(pos, 0) + 1
    return counts


def can_pick_position(pos: str, roster: list[int], board: pd.DataFrame, max_by_pos: dict[str, int]) -> bool:
    counts = count_positions(roster, board)
    return counts.get(pos, 0) < max_by_pos.get(pos, 99)


def legal_available_indices(
    board: pd.DataFrame,
    available: np.ndarray,
    roster: list[int],
    roster_format: RosterFormat,
) -> np.ndarray:
    sim = get_sim_board(board)
    idxs = np.flatnonzero(available)
    if not len(idxs):
        return idxs
    counts = count_positions(roster, board)
    max_by_pos = roster_format.max_by_pos
    keep = []
    for i in idxs:
        code = int(sim.pos_codes[i])
        if code < 0:
            continue
        pos = SKILL_POSITIONS[code]
        if counts.get(pos, 0) < max_by_pos.get(pos, 99):
            keep.append(i)
    return np.asarray(keep if keep else idxs, dtype=int)


def roster_needs_for_format(roster: list[int], board: pd.DataFrame, roster_format: RosterFormat) -> dict[str, float]:
    counts = count_positions(roster, board)
    starters = roster_format.starter_slots
    needs = {
        "QB": max(0, starters.get("QB", 0) - counts["QB"]),
        "RB": max(0, starters.get("RB", 0) - counts["RB"]),
        "WR": max(0, starters.get("WR", 0) - counts["WR"]),
        "TE": max(0, starters.get("TE", 0) - counts["TE"]),
    }
    flex_have = sum(
        max(0, counts[pos] - starters.get(pos, 0))
        for pos in roster_format.flex_eligible
        if pos in counts
    )
    needs["FLEX"] = max(0, roster_format.flex_slots - flex_have)
    return needs


def candidate_indices(
    board: pd.DataFrame,
    available: np.ndarray,
    roster: list[int],
    roster_format: RosterFormat,
    shortlist_size: int,
) -> np.ndarray:
    sim = get_sim_board(board)
    counts = count_positions(roster, board)
    max_by_pos = roster_format.max_by_pos
    out = []
    for idx in sim.queue_order:
        if not available[idx]:
            continue
        code = int(sim.pos_codes[idx])
        if code < 0:
            continue
        pos = SKILL_POSITIONS[code]
        if counts.get(pos, 0) >= max_by_pos.get(pos, 99):
            continue
        out.append(int(idx))
        if len(out) >= shortlist_size:
            break
    if out:
        return np.asarray(out, dtype=int)
    return legal_available_indices(board, available, roster, roster_format)


def score_roster(roster: list[int], board: pd.DataFrame, roster_format: RosterFormat) -> tuple[float, float]:
    if not roster:
        return 0.0, 0.0
    sim = get_sim_board(board)
    roster_arr = np.asarray(roster, dtype=int)
    total = float(sim.fantasy_points[roster_arr].sum())
    used: set[int] = set()
    starter_points = 0.0

    for pos in SKILL_POSITIONS:
        n = int(roster_format.starter_slots.get(pos, 0))
        if n <= 0:
            continue
        code = POSITION_ORDER[pos]
        pos_idxs = roster_arr[sim.pos_codes[roster_arr] == code]
        if len(pos_idxs):
            chosen = pos_idxs[np.argsort(-sim.fantasy_points[pos_idxs])[:n]]
            used.update(int(i) for i in chosen)
            starter_points += float(sim.fantasy_points[chosen].sum())

    flex_idxs = [
        int(i)
        for i in roster_arr
        if int(i) not in used and sim.positions[int(i)] in roster_format.flex_eligible
    ]
    if flex_idxs and roster_format.flex_slots > 0:
        flex_arr = np.asarray(flex_idxs, dtype=int)
        chosen = flex_arr[np.argsort(-sim.fantasy_points[flex_arr])[: roster_format.flex_slots]]
        starter_points += float(sim.fantasy_points[chosen].sum())
    return starter_points, total


def action_features(
    board: pd.DataFrame,
    idxs: np.ndarray,
    roster: list[int],
    pick_number: int,
    total_picks: int,
    roster_format: RosterFormat,
) -> np.ndarray:
    sim = get_sim_board(board)
    counts = count_positions(roster, board)
    needs = roster_needs_for_format(roster, board, roster_format)
    max_by_pos = roster_format.max_by_pos
    rows = []
    for idx in idxs:
        code = int(sim.pos_codes[idx])
        pos = SKILL_POSITIONS[code]
        adp = float(sim.adp[idx])
        projected = float(sim.projected_points[idx])
        vbd = float(sim.vbd[idx])
        pos_count = counts.get(pos, 0)
        pos_need = needs.get(pos, 0)
        flex_need = needs.get("FLEX", 0) if pos in roster_format.flex_eligible else 0
        feats = [
            1.0,
            projected / 300.0,
            vbd / 150.0,
            min(adp, 250.0) / 250.0,
            math.log1p(max(adp, 1.0)) / math.log(251.0),
            float(pos_need),
            float(flex_need),
            float(pos_count) / 7.0,
            pick_number / max(total_picks, 1),
            float(sim.pts_lag1[idx]) / 300.0,
            float(sim.fp_per_game_lag1[idx]) / 25.0,
            float(sim.is_rookie[idx]),
            float(sim.is_2nd_year[idx]),
            roster_format.starter_slots.get(pos, 0) / 3.0,
            roster_format.flex_slots / 3.0 if pos in roster_format.flex_eligible else 0.0,
            max_by_pos.get(pos, 99) / 10.0,
            roster_format.num_teams / 14.0,
        ]
        feats.extend(1.0 if pos == p else 0.0 for p in SKILL_POSITIONS)
        rows.append(feats)
    return np.asarray(rows, dtype=np.float32)


def pick_by_strategy(
    strategy: str,
    board: pd.DataFrame,
    available: np.ndarray,
    roster: list[int],
    roster_format: RosterFormat,
    shortlist_size: int,
    pick_number: int,
    total_picks: int,
    rng: np.random.Generator,
) -> int:
    sim = get_sim_board(board)
    idxs = candidate_indices(board, available, roster, roster_format, shortlist_size)
    if not len(idxs):
        raise RuntimeError("No available players")
    needs = roster_needs_for_format(roster, board, roster_format)
    pos_arr = sim.positions[idxs]
    need_bonus = np.asarray([
        25.0 * needs.get(p, 0) + (10.0 * needs.get("FLEX", 0) if p in roster_format.flex_eligible else 0.0)
        for p in pos_arr
    ])

    if strategy == "random":
        return int(rng.choice(idxs))
    if strategy == "adp":
        score = -sim.adp[idxs] + need_bonus + rng.normal(0, 4.0, len(idxs))
    elif strategy == "catboost":
        score = sim.projected_points[idxs] + need_bonus + rng.normal(0, 2.0, len(idxs))
    elif strategy == "vbd":
        score = sim.vbd[idxs] + need_bonus + rng.normal(0, 2.0, len(idxs))
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    return int(idxs[int(np.argmax(score))])


def next_pick_for_team(order: list[int], current_pick_number: int, team_idx: int) -> int:
    for i in range(current_pick_number, len(order)):
        if order[i] == team_idx:
            return i + 1
    return len(order) + 1


def sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def pick_by_adp_guarded(
    board: pd.DataFrame,
    available: np.ndarray,
    roster: list[int],
    roster_format: RosterFormat,
    shortlist_size: int,
    pick_number: int,
    total_picks: int,
    next_pick_number: int,
) -> int:
    """ADP anchor with selective overrides for urgency and roster value.

    The policy should only fight market price when a player creates enough
    roster value and is unlikely to survive until the controlled team's next
    pick. This directly targets the practical draft question: can I wait?
    """
    sim = get_sim_board(board)
    idxs = candidate_indices(board, available, roster, roster_format, shortlist_size)
    if not len(idxs):
        raise RuntimeError("No available players")

    needs = roster_needs_for_format(roster, board, roster_format)
    counts = count_positions(roster, board)
    pos_arr = sim.positions[idxs]
    adp = sim.adp[idxs].astype(np.float32)
    projected = sim.projected_points[idxs].astype(np.float32)
    vbd = sim.vbd[idxs].astype(np.float32)
    pick_gap = max(1, next_pick_number - pick_number)
    round_num = ((pick_number - 1) // roster_format.num_teams) + 1

    starter_need = np.asarray([needs.get(p, 0.0) for p in pos_arr], dtype=np.float32)
    flex_need = np.asarray(
        [needs.get("FLEX", 0.0) if p in roster_format.flex_eligible else 0.0 for p in pos_arr],
        dtype=np.float32,
    )
    pos_count = np.asarray([counts.get(p, 0.0) for p in pos_arr], dtype=np.float32)
    late_need = np.asarray(
        [1.0 if round_num >= 8 and needs.get(p, 0.0) > 0 else 0.0 for p in pos_arr],
        dtype=np.float32,
    )
    rb_bias = np.asarray([1.0 if p == "RB" else 0.0 for p in pos_arr], dtype=np.float32)

    # Market availability estimate. If ADP is before the next turn, the player
    # is increasingly likely to be gone. Wider turn gaps increase uncertainty.
    gone_scale = max(6.0, min(16.0, pick_gap / 2.5))
    p_gone = sigmoid((next_pick_number - adp) / gone_scale).astype(np.float32)
    p_available = 1.0 - p_gone

    # Estimate the best same-position value we can wait for. This is computed
    # over the current shortlist for speed; candidate_indices already includes
    # the players most relevant to the next several picks.
    wait_same = np.zeros(len(idxs), dtype=np.float32)
    for pos in SKILL_POSITIONS:
        mask = pos_arr == pos
        if not np.any(mask):
            continue
        wait_value = vbd[mask] * p_available[mask]
        if len(wait_value) == 1:
            wait_same[mask] = 0.0
            continue
        order = np.argsort(-wait_value)
        best = wait_value[order[0]]
        second = wait_value[order[1]]
        local = np.where(np.arange(len(wait_value)) == order[0], second, best)
        wait_same[mask] = local.astype(np.float32)

    urgency = p_gone * np.maximum(0.0, vbd - wait_same)
    adp_value = np.clip(pick_number - adp, 0.0, 45.0)
    reach = np.clip(adp - pick_number - pick_gap * 0.65, 0.0, 90.0)
    need_bonus = 24.0 * starter_need + 9.0 * flex_need + 10.0 * late_need
    depth_penalty = np.maximum(0.0, pos_count - starter_need - flex_need - 1.0) * 3.0

    score = (
        -adp
        + 0.10 * projected
        + 0.34 * vbd
        + need_bonus
        + 1.25 * urgency
        + 0.45 * adp_value
        - 0.85 * reach
        - depth_penalty
        + 2.5 * rb_bias
    )
    return int(idxs[int(np.argmax(score))])


def roster_config_for_format(roster_format: RosterFormat) -> dict:
    """Translate a simulator format to the canonical scarcity config."""
    slots = {
        pos.lower(): int(roster_format.starter_slots.get(pos, 0))
        for pos in SKILL_POSITIONS
    }
    slots["flex"] = int(roster_format.flex_slots)
    slots["bench"] = int(roster_format.bench)
    return {
        "roster_slots": slots,
        "flex_eligible": [p.lower() for p in roster_format.flex_eligible],
    }


def format_vbd_values(board: pd.DataFrame, roster_format: RosterFormat) -> np.ndarray:
    """Return signed, format-specific VBD aligned to a simulation board."""
    cache = board.attrs.setdefault("_format_vbd", {})
    key = roster_format.to_json()
    if key not in cache:
        valued = compute_vbd(
            board[["position", "projected_points"]],
            num_teams=roster_format.num_teams,
            roster_config=roster_config_for_format(roster_format),
        )
        cache[key] = valued["vbd"].to_numpy(dtype=np.float32)
    return cache[key]


def pick_by_scarcity_v2(
    board: pd.DataFrame,
    available: np.ndarray,
    roster: list[int],
    roster_format: RosterFormat,
    shortlist_size: int,
    pick_number: int,
    next_pick_number: int,
    weights: ScarcityV2Weights = DEFAULT_SCARCITY_V2_WEIGHTS,
) -> int:
    """ADP-anchored VONA using true FLEX VBD and conditional availability."""
    sim = get_sim_board(board)
    candidates = candidate_indices(
        board, available, roster, roster_format, shortlist_size
    )
    if not len(candidates):
        raise RuntimeError("No available players")

    signed_vbd = format_vbd_values(board, roster_format)
    needs = roster_needs_for_format(roster, board, roster_format)
    counts = count_positions(roster, board)
    pos_arr = sim.positions[candidates]
    adp = sim.adp[candidates].astype(np.float32)
    projected = sim.projected_points[candidates].astype(np.float32)
    vbd = signed_vbd[candidates].astype(np.float32)
    pick_gap = max(1, next_pick_number - pick_number)
    round_num = ((pick_number - 1) // roster_format.num_teams) + 1

    starter_need = np.asarray([needs.get(p, 0.0) for p in pos_arr], dtype=np.float32)
    flex_need = np.asarray([
        needs.get("FLEX", 0.0) if p in roster_format.flex_eligible else 0.0
        for p in pos_arr
    ], dtype=np.float32)
    pos_count = np.asarray([counts.get(p, 0.0) for p in pos_arr], dtype=np.float32)
    late_need = np.asarray([
        1.0 if round_num >= 8 and needs.get(p, 0.0) > 0 else 0.0
        for p in pos_arr
    ], dtype=np.float32)

    p_gone = conditional_probability_gone(
        adp, pick_number, next_pick_number
    )
    p_available = 1.0 - p_gone

    expected_next_same = np.zeros(len(candidates), dtype=np.float32)
    for pos in SKILL_POSITIONS:
        local = np.flatnonzero(pos_arr == pos)
        if not len(local):
            continue
        local_values = np.maximum(vbd[local], 0.0)
        local_probs = p_available[local]
        for local_i, candidate_i in enumerate(local):
            expected_next_same[candidate_i] = expected_best_available_value(
                local_values, local_probs, exclude_index=local_i
            )

    # VONA is already availability-adjusted: likely survivors retain more of
    # their value in expected_next_same and therefore create less urgency now.
    vona = np.maximum(0.0, vbd - expected_next_same)
    adp_value = np.clip(pick_number - adp, 0.0, 45.0)
    reach = np.clip(adp - pick_number - pick_gap * 0.65, 0.0, 90.0)
    depth_penalty = np.maximum(
        0.0, pos_count - starter_need - flex_need - 1.0
    )

    score = (
        -weights.adp * adp
        + weights.projected * projected
        + weights.vbd * vbd
        + weights.starter_need * starter_need
        + weights.flex_need * flex_need
        + weights.late_need * late_need
        + weights.vona * vona
        + weights.adp_value * adp_value
        - weights.reach * reach
        - weights.depth * depth_penalty
    )
    return int(candidates[int(np.argmax(score))])


class LinearDraftPolicy:
    def __init__(
        self,
        n_features: int,
        learning_rate: float = 0.03,
        temperature: float = 0.8,
        anchor_reg: float = 0.02,
        seed: int = 42,
    ):
        self.rng = np.random.default_rng(seed)
        self.weights = self.rng.normal(0.0, 0.03, size=n_features).astype(np.float32)
        # ADP is the strongest held-out baseline in this simulator, so the RL
        # policy starts as an ADP-aware value drafter and learns small corrections.
        self.weights[1] += 0.35   # projected points
        self.weights[2] += 0.45   # VBD
        self.weights[3] -= 2.80   # ADP rank, lower is better
        self.weights[4] -= 0.90   # log ADP rank
        self.weights[5] += 0.65   # open starter slot
        self.weights[6] += 0.25   # open flex slot
        self.weights[7] -= 0.15   # already drafted at position
        self.weights[11] -= 0.15  # rookie uncertainty
        self.anchor_weights = self.weights.copy()
        self.learning_rate = learning_rate
        self.temperature = temperature
        self.anchor_reg = anchor_reg

    def choose(self, feats: np.ndarray, train: bool) -> tuple[int, np.ndarray]:
        logits = feats @ self.weights / max(self.temperature, 1e-6)
        logits -= logits.max()
        probs = np.exp(logits)
        probs /= max(float(probs.sum()), 1e-8)
        if train:
            action = int(self.rng.choice(len(feats), p=probs))
        else:
            action = int(np.argmax(probs))
        return action, probs

    def update(self, grads: list[np.ndarray], advantage: float) -> None:
        if not grads or advantage <= 0:
            return
        grad = np.sum(grads, axis=0)
        grad = np.clip(grad, -5.0, 5.0)
        self.weights += self.learning_rate * float(advantage) * grad.astype(np.float32)
        self.weights = (1.0 - self.anchor_reg) * self.weights + self.anchor_reg * self.anchor_weights
        self.weights = np.clip(self.weights, -5.0, 5.0)


def simulate_draft(
    board: pd.DataFrame,
    strategy: str,
    seed: int,
    draft_slot: int,
    shortlist_size: int,
    roster_format: RosterFormat,
    opponent_noise: float,
    policy: Optional[LinearDraftPolicy] = None,
    scarcity_weights: ScarcityV2Weights = DEFAULT_SCARCITY_V2_WEIGHTS,
    train: bool = False,
) -> tuple[DraftResult, list[np.ndarray], list[float]]:
    sim = get_sim_board(board)
    rng = np.random.default_rng(seed)
    num_teams = roster_format.num_teams
    team_idx = draft_slot - 1
    order = snake_pick_order(num_teams, roster_format.rounds)
    total_picks = len(order)
    rosters: list[list[int]] = [[] for _ in range(num_teams)]
    available = np.ones(len(board), dtype=bool)
    policy_grads: list[np.ndarray] = []

    for pick_no, picker in enumerate(order, start=1):
        roster = rosters[picker]
        if picker == team_idx:
            if strategy == "rl":
                if policy is None:
                    raise ValueError("RL strategy requires a policy")
                idxs = candidate_indices(board, available, roster, roster_format, shortlist_size)
                feats = action_features(board, idxs, roster, pick_no, total_picks, roster_format)
                action, probs = policy.choose(feats, train=train)
                chosen = int(idxs[action])
                if train:
                    expected = probs @ feats
                    policy_grads.append((feats[action] - expected) / max(policy.temperature, 1e-6))
            elif strategy == "scarcity_v2":
                next_pick = next_pick_for_team(order, pick_no, team_idx)
                chosen = pick_by_scarcity_v2(
                    board,
                    available,
                    roster,
                    roster_format,
                    shortlist_size,
                    pick_no,
                    next_pick,
                    scarcity_weights,
                )
            elif strategy == "adp_guarded":
                next_pick = next_pick_for_team(order, pick_no, team_idx)
                chosen = pick_by_adp_guarded(
                    board,
                    available,
                    roster,
                    roster_format,
                    shortlist_size,
                    pick_no,
                    total_picks,
                    next_pick,
                )
            else:
                chosen = pick_by_strategy(
                    strategy,
                    board,
                    available,
                    roster,
                    roster_format,
                    shortlist_size,
                    pick_no,
                    total_picks,
                    rng,
                )
        else:
            chosen = opponent_pick(
                board,
                available,
                roster,
                roster_format,
                shortlist_size,
                pick_no,
                total_picks,
                rng,
                opponent_noise,
            )
        available[chosen] = False
        rosters[picker].append(chosen)

    team_scores = [score_roster(r, board, roster_format) for r in rosters]
    starter_scores = [s for s, _ in team_scores]
    total_scores = [t for _, t in team_scores]
    my_starter, my_total = team_scores[team_idx]
    rank = 1 + sum(s > my_starter for s in starter_scores)
    picks = [
        {"player_name": str(sim.player_names[i]), "position": str(sim.positions[i])}
        for i in rosters[team_idx]
    ]
    result = DraftResult(
        season=sim.season,
        strategy=strategy,
        seed=seed,
        draft_slot=draft_slot,
        roster_format=roster_format.name,
        num_teams=roster_format.num_teams,
        rounds=roster_format.rounds,
        qb_slots=roster_format.starter_slots.get("QB", 0),
        rb_slots=roster_format.starter_slots.get("RB", 0),
        wr_slots=roster_format.starter_slots.get("WR", 0),
        te_slots=roster_format.starter_slots.get("TE", 0),
        flex_slots=roster_format.flex_slots,
        bench_slots=roster_format.bench,
        starter_points=round(float(my_starter), 3),
        total_points=round(float(my_total), 3),
        league_rank=int(rank),
        field_avg_starter_points=round(float(np.mean(starter_scores)), 3),
        picks=json.dumps(picks),
    )
    return result, policy_grads, starter_scores


def opponent_pick(
    board: pd.DataFrame,
    available: np.ndarray,
    roster: list[int],
    roster_format: RosterFormat,
    shortlist_size: int,
    pick_number: int,
    total_picks: int,
    rng: np.random.Generator,
    opponent_noise: float,
) -> int:
    sim = get_sim_board(board)
    idxs = candidate_indices(board, available, roster, roster_format, shortlist_size)
    if not len(idxs):
        raise RuntimeError("No available players")
    needs = roster_needs_for_format(roster, board, roster_format)
    pos_arr = sim.positions[idxs]
    need_bonus = np.asarray([
        22.0 * needs.get(p, 0) + (8.0 * needs.get("FLEX", 0) if p in roster_format.flex_eligible else 0.0)
        for p in pos_arr
    ])
    round_num = ((pick_number - 1) // roster_format.num_teams) + 1
    qb_te_late = np.asarray([
        12.0 if round_num >= 8 and p in ("QB", "TE") and needs.get(p, 0) > 0 else 0.0
        for p in pos_arr
    ])
    score = (
        -sim.adp[idxs]
        + 0.15 * sim.projected_points[idxs]
        + 0.25 * sim.vbd[idxs]
        + need_bonus
        + qb_te_late
        + rng.normal(0, opponent_noise, len(idxs))
    )
    return int(idxs[int(np.argmax(score))])


def default_roster_format(num_teams: int, rounds: int) -> RosterFormat:
    starter_slots = dict(STARTER_SLOTS)
    skill_starters = sum(starter_slots[p] for p in SKILL_POSITIONS) + starter_slots.get("FLEX", 0)
    bench = max(0, int(rounds) - skill_starters)
    return RosterFormat(
        name=f"standard_{num_teams}tm_{rounds}rnd",
        num_teams=int(num_teams),
        starter_slots=starter_slots,
        bench=bench,
    )


def sample_roster_format(rng: np.random.Generator, mode: str, num_teams: int, rounds: int) -> RosterFormat:
    if mode == "fixed":
        return default_roster_format(num_teams, rounds)

    teams = int(rng.choice([10, 12, 14], p=[0.25, 0.55, 0.20]))
    qb = int(rng.choice([1, 2], p=[0.88, 0.12]))
    rb = int(rng.choice([1, 2, 3], p=[0.12, 0.76, 0.12]))
    wr = int(rng.choice([2, 3], p=[0.65, 0.35]))
    te = 1
    flex = int(rng.choice([0, 1, 2, 3], p=[0.18, 0.58, 0.20, 0.04]))
    bench = int(rng.choice([5, 6, 7, 8, 9, 10], p=[0.12, 0.25, 0.28, 0.20, 0.10, 0.05]))
    starters = {"QB": qb, "RB": rb, "WR": wr, "TE": te, "FLEX": flex}
    name = f"{teams}tm_qb{qb}_rb{rb}_wr{wr}_te{te}_flex{flex}_bn{bench}"
    return RosterFormat(name=name, num_teams=teams, starter_slots=starters, bench=bench)


def train_policy(
    boards: dict[int, pd.DataFrame],
    train_seasons: list[int],
    episodes: int,
    shortlist_size: int,
    roster_mode: str,
    num_teams: int,
    rounds: int,
    opponent_noise: float,
    learning_rate: float,
    temperature: float,
    anchor_reg: float,
    seed: int,
) -> LinearDraftPolicy:
    sample_board = next(iter(boards.values()))
    sample_idxs = np.arange(min(shortlist_size, len(sample_board)))
    sample_format = default_roster_format(num_teams, rounds)
    n_features = action_features(
        sample_board,
        sample_idxs,
        [],
        1,
        sample_format.num_teams * sample_format.rounds,
        sample_format,
    ).shape[1]
    policy = LinearDraftPolicy(
        n_features,
        learning_rate=learning_rate,
        temperature=temperature,
        anchor_reg=anchor_reg,
        seed=seed,
    )
    rng = np.random.default_rng(seed)
    baseline = None

    for ep in range(1, episodes + 1):
        season = int(rng.choice(train_seasons))
        roster_format = sample_roster_format(rng, roster_mode, num_teams, rounds)
        draft_slot = int(rng.integers(1, roster_format.num_teams + 1))
        result, grads, _ = simulate_draft(
            boards[season],
            "rl",
            seed=seed * 100_000 + ep,
            draft_slot=draft_slot,
            shortlist_size=shortlist_size,
            roster_format=roster_format,
            opponent_noise=opponent_noise,
            policy=policy,
            train=True,
        )
        reward = result.starter_points - result.field_avg_starter_points
        baseline = reward if baseline is None else 0.98 * baseline + 0.02 * reward
        advantage = (reward - baseline) / 100.0
        policy.update(grads, advantage)
        if ep % max(episodes // 5, 1) == 0:
            print(f"  train episode {ep:>5}/{episodes}: reward_vs_field={reward:7.2f}, rank={result.league_rank}")

    return policy


def evaluate_strategy(
    boards: dict[int, pd.DataFrame],
    seasons: list[int],
    strategy: str,
    episodes_per_season: int,
    shortlist_size: int,
    roster_mode: str,
    num_teams: int,
    rounds: int,
    opponent_noise: float,
    seed: int,
    policy: Optional[LinearDraftPolicy] = None,
    scarcity_weights: ScarcityV2Weights = DEFAULT_SCARCITY_V2_WEIGHTS,
) -> pd.DataFrame:
    rows = []
    ep = 0
    rng = np.random.default_rng(seed)
    for season in seasons:
        reps = max(int(episodes_per_season), 1)
        for rep in range(reps):
            ep += 1
            roster_format = sample_roster_format(rng, roster_mode, num_teams, rounds)
            if roster_mode == "fixed":
                draft_slot = 1 + (rep % roster_format.num_teams)
            else:
                draft_slot = int(rng.integers(1, roster_format.num_teams + 1))
            result, _, _ = simulate_draft(
                boards[season],
                strategy,
                seed=seed * 1_000_000 + season * 1000 + ep,
                draft_slot=draft_slot,
                shortlist_size=shortlist_size,
                roster_format=roster_format,
                opponent_noise=opponent_noise,
                policy=policy,
                scarcity_weights=scarcity_weights,
                train=False,
            )
            rows.append(result.__dict__)
    return pd.DataFrame(rows)


def summarize_results(raw: pd.DataFrame) -> pd.DataFrame:
    return (
        raw.groupby("strategy")
        .agg(
            starter_points=("starter_points", "mean"),
            total_points=("total_points", "mean"),
            avg_rank=("league_rank", "mean"),
            win_rate=("league_rank", lambda s: float((s == 1).mean())),
            top3_rate=("league_rank", lambda s: float((s <= 3).mean())),
            field_avg=("field_avg_starter_points", "mean"),
            episodes=("starter_points", "size"),
        )
        .reset_index()
        .sort_values(["starter_points", "top3_rate"], ascending=False)
    )


def summarize_by_format(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or "roster_format" not in raw.columns:
        return pd.DataFrame()
    return (
        raw.groupby(["roster_format", "strategy"])
        .agg(
            starter_points=("starter_points", "mean"),
            avg_rank=("league_rank", "mean"),
            win_rate=("league_rank", lambda s: float((s == 1).mean())),
            top3_rate=("league_rank", lambda s: float((s <= 3).mean())),
            episodes=("starter_points", "size"),
        )
        .reset_index()
        .sort_values(["roster_format", "starter_points"], ascending=[True, False])
    )


def summarize_by_archetype(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    keys = ["num_teams", "qb_slots", "rb_slots", "wr_slots", "flex_slots"]
    return (
        raw.groupby(keys + ["strategy"])
        .agg(
            starter_points=("starter_points", "mean"),
            avg_rank=("league_rank", "mean"),
            win_rate=("league_rank", lambda s: float((s == 1).mean())),
            top3_rate=("league_rank", lambda s: float((s <= 3).mean())),
            episodes=("starter_points", "size"),
        )
        .reset_index()
        .sort_values(keys + ["starter_points"], ascending=[True, True, True, True, True, False])
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame-cache", default="puffer_rl_frame.parquet")
    parser.add_argument("--board-cache", default="snake_draft_boards.parquet")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--train-seasons", nargs="+", type=int, default=[2023, 2024])
    parser.add_argument("--eval-seasons", nargs="+", type=int, default=[2025])
    parser.add_argument("--train-episodes", type=int, default=600)
    parser.add_argument("--eval-episodes-per-season", type=int, default=120)
    parser.add_argument("--shortlist-size", type=int, default=24)
    parser.add_argument("--rounds", type=int, default=14)
    parser.add_argument("--num-teams", type=int, default=12)
    parser.add_argument("--roster-mode", choices=["fixed", "mixed"], default="fixed")
    parser.add_argument("--opponent-noise", type=float, default=18.0)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--temperature", type=float, default=0.55)
    parser.add_argument("--anchor-reg", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--scarcity-weights",
        help="JSON object overriding ScarcityV2Weights for reproducible tuning",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=["adp", "adp_guarded", "scarcity_v2", "catboost", "vbd", "random", "rl"],
        choices=["adp", "adp_guarded", "scarcity_v2", "catboost", "vbd", "random", "rl"],
    )
    parser.add_argument("--out", default="snake_draft_rl_results.csv")
    parser.add_argument("--raw-out", default="snake_draft_rl_raw.csv")
    parser.add_argument("--format-out", default="snake_draft_rl_by_format.csv")
    parser.add_argument("--archetype-out", default="snake_draft_rl_by_archetype.csv")
    args = parser.parse_args()
    scarcity_weights = DEFAULT_SCARCITY_V2_WEIGHTS
    if args.scarcity_weights:
        scarcity_weights = ScarcityV2Weights(**json.loads(args.scarcity_weights))

    seasons = sorted(set(args.train_seasons + args.eval_seasons))
    frame_cache = REPO / args.frame_cache if args.frame_cache else None
    board_cache = REPO / args.board_cache if args.board_cache else None
    df = load_or_build_frame(frame_cache, args.refresh_cache)
    boards = load_or_build_boards(df, seasons, board_cache, args.refresh_cache)
    missing = sorted(set(seasons) - set(boards))
    if missing:
        raise SystemExit(f"Missing boards for seasons: {missing}")

    print(f"Puffer wrapper: {puffer_smoke_check(next(iter(boards.values())), args.shortlist_size)}")

    policy = None
    if "rl" in args.strategies:
        print("\nTraining RL draft policy...")
        policy = train_policy(
            boards,
            args.train_seasons,
            episodes=args.train_episodes,
            shortlist_size=args.shortlist_size,
            roster_mode=args.roster_mode,
            num_teams=args.num_teams,
            rounds=args.rounds,
            opponent_noise=args.opponent_noise,
            learning_rate=args.learning_rate,
            temperature=args.temperature,
            anchor_reg=args.anchor_reg,
            seed=args.seed,
        )

    raw_parts = []
    for strategy in args.strategies:
        print(f"\nEvaluating {strategy}...")
        raw_parts.append(
            evaluate_strategy(
                boards,
                args.eval_seasons,
                strategy,
                episodes_per_season=args.eval_episodes_per_season,
                shortlist_size=args.shortlist_size,
                roster_mode=args.roster_mode,
                num_teams=args.num_teams,
                rounds=args.rounds,
                opponent_noise=args.opponent_noise,
                seed=args.seed,
                policy=policy if strategy == "rl" else None,
                scarcity_weights=scarcity_weights,
            )
        )

    raw = pd.concat(raw_parts, ignore_index=True)
    summary = summarize_results(raw)
    by_format = summarize_by_format(raw)
    by_archetype = summarize_by_archetype(raw)
    raw_path = REPO / args.raw_out
    out_path = REPO / args.out
    format_path = REPO / args.format_out
    archetype_path = REPO / args.archetype_out
    raw.to_csv(raw_path, index=False)
    summary.to_csv(out_path, index=False)
    if not by_format.empty:
        by_format.to_csv(format_path, index=False)
    if not by_archetype.empty:
        by_archetype.to_csv(archetype_path, index=False)

    print("\n=== Snake Draft RL Experiment ===")
    print(summary.round(4).to_string(index=False))
    if not by_format.empty:
        print("\n=== By Roster Format ===")
        print(by_format.round(4).head(40).to_string(index=False))
    if not by_archetype.empty:
        print("\n=== By Roster Archetype ===")
        print(by_archetype.round(4).head(60).to_string(index=False))
    print(f"\nWrote {out_path}")
    print(f"Wrote {raw_path}")
    if not by_format.empty:
        print(f"Wrote {format_path}")
    if not by_archetype.empty:
        print(f"Wrote {archetype_path}")
    print(
        "\n"
        + json.dumps(
            {
                "train_seasons": args.train_seasons,
                "eval_seasons": args.eval_seasons,
                "scoring": "actual held-out QB/RB/WR/TE starter+flex fantasy points",
                "roster_mode": args.roster_mode,
                "fixed_roster_format": default_roster_format(args.num_teams, args.rounds).to_json(),
                "opponents": "ADP/model/VBD scripted drafters with Gaussian noise and roster-need bonuses",
                "rl_policy": "linear softmax over top-N legal available player/action features",
                "scarcity_v2_weights": asdict(scarcity_weights),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
