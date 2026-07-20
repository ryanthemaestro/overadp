#!/usr/bin/env python3
"""Run a small Puffer-compatible RL experiment against the CatBoost baseline.

This is a contextual-bandit formulation of the projection problem:
  - observation: the same numeric player features CatBoost sees
  - action: choose one discretized fantasy-points bin
  - reward: negative absolute prediction error

It is not a full draft simulator. The point is to answer the first practical
question quickly: does an RL-style policy learn better point projections than
the current CatBoost walk-forward baseline on the same data?
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.run_catboost_feature_experiments import build_frame
from src.models.base import FantasyModel
from src.models.catboost_model import CatBoostModel, POSITION_CATBOOST_PARAMS, POSITION_TEMPORAL_WEIGHTS
from src.models.compare import walk_forward_validate
from src.models.pipeline import OFFENSIVE_POSITIONS, _numeric_feature_cols, get_position_features


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


@dataclass
class PufferSmokeResult:
    available: bool
    wrapped: bool
    detail: str


class FantasyBanditEnv:
    """Minimal Gymnasium env that PufferLib can wrap.

    Training below uses a vectorized PyTorch objective for speed, but this env
    keeps the experiment honest: the same observation/action/reward interface is
    compatible with PufferLib's Gymnasium wrapper when pufferlib is installed.
    """

    metadata = {"render_modes": []}

    def __init__(self, X: np.ndarray, y: np.ndarray, bin_centers: np.ndarray, seed: int = 42):
        try:
            import gymnasium as gym
        except ImportError as exc:  # pragma: no cover - only hit without optional dep
            raise RuntimeError("gymnasium is required for the Puffer smoke check") from exc

        self.X = X.astype(np.float32)
        self.y = y.astype(np.float32)
        self.bin_centers = bin_centers.astype(np.float32)
        self.rng = np.random.default_rng(seed)
        self.observation_space = gym.spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self.X.shape[1],),
            dtype=np.float32,
        )
        self.action_space = gym.spaces.Discrete(len(self.bin_centers))
        self._idx = 0

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self._idx = int(self.rng.integers(0, len(self.X)))
        return self.X[self._idx], {}

    def step(self, action: int):
        pred = self.bin_centers[int(action)]
        reward = -abs(float(pred) - float(self.y[self._idx])) / 100.0
        obs, _ = self.reset()
        return obs, reward, True, False, {}


def puffer_smoke_check(X: np.ndarray, y: np.ndarray, bin_centers: np.ndarray) -> PufferSmokeResult:
    try:
        import pufferlib.emulation
    except Exception as exc:
        return PufferSmokeResult(False, False, f"pufferlib unavailable: {exc}")

    try:
        env = FantasyBanditEnv(X[: min(len(X), 32)], y[: min(len(y), 32)], bin_centers)
        wrapped = pufferlib.emulation.GymnasiumPufferEnv(env)
        obs, _ = wrapped.reset()
        action = wrapped.action_space.sample()
        wrapped.step(action)
        return PufferSmokeResult(True, True, f"wrapped observation shape {tuple(np.asarray(obs).shape)}")
    except Exception as exc:
        return PufferSmokeResult(True, False, f"pufferlib import ok, wrapper failed: {exc}")


class PufferBanditRegressor(FantasyModel):
    """Discrete-action policy trained to maximize negative absolute-error reward."""

    name = "puffer_bandit_rl"

    def __init__(
        self,
        bins: int = 24,
        hidden_size: int = 128,
        epochs: int = 700,
        batch_size: int = 128,
        learning_rate: float = 3e-3,
        entropy_coef: float = 0.002,
        seed: int = 42,
    ):
        self.bins = bins
        self.hidden_size = hidden_size
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.entropy_coef = entropy_coef
        self.seed = seed
        self.feature_names_: list[str] = []
        self.mean_: Optional[np.ndarray] = None
        self.scale_: Optional[np.ndarray] = None
        self.bin_centers_: Optional[np.ndarray] = None
        self.random_weights_: Optional[np.ndarray] = None
        self.random_bias_: Optional[np.ndarray] = None
        self.policy_weights_: Optional[np.ndarray] = None
        self.policy_bias_: Optional[np.ndarray] = None
        self.model = None
        self.smoke_result: Optional[PufferSmokeResult] = None

    def _augment(self, X_np: np.ndarray) -> np.ndarray:
        if self.random_weights_ is None or self.random_bias_ is None:
            raise RuntimeError("Random feature map is not initialized")
        hidden = X_np @ self.random_weights_ + self.random_bias_
        hidden = np.maximum(hidden, 0.0)
        return np.concatenate([X_np, hidden], axis=1).astype(np.float32)

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weight: Optional[np.ndarray] = None,
        **kwargs,
    ) -> "PufferBanditRegressor":
        self.validate_inputs(X, y)
        rng = np.random.default_rng(self.seed)

        X_np = X.to_numpy(dtype=np.float32, copy=True)
        y_np = pd.to_numeric(y, errors="coerce").to_numpy(dtype=np.float32)
        valid = np.isfinite(y_np)
        X_np = X_np[valid]
        y_np = y_np[valid]
        if sample_weight is not None:
            sw_np = np.asarray(sample_weight, dtype=np.float32)[valid]
        else:
            sw_np = np.ones(len(y_np), dtype=np.float32)

        self.feature_names_ = list(X.columns)
        self.mean_ = X_np.mean(axis=0)
        self.scale_ = X_np.std(axis=0)
        self.scale_[self.scale_ < 1e-6] = 1.0
        X_np = (X_np - self.mean_) / self.scale_

        q = np.linspace(0, 1, self.bins + 1)
        edges = np.unique(np.quantile(y_np, q))
        if len(edges) <= 2:
            lo, hi = float(y_np.min()), float(y_np.max())
            edges = np.linspace(lo, hi if hi > lo else lo + 1.0, self.bins + 1)
        centers = (edges[:-1] + edges[1:]) / 2.0
        self.bin_centers_ = centers.astype(np.float32)
        n_actions = len(self.bin_centers_)

        # Keep a Puffer compatibility signal on the first fit; it is not in the
        # hot path because Puffer's full trainer is overkill for this bandit.
        if self.smoke_result is None:
            self.smoke_result = puffer_smoke_check(X_np, y_np, self.bin_centers_)

        in_dim = X_np.shape[1]
        self.random_weights_ = (
            rng.normal(0.0, 1.0 / math.sqrt(max(in_dim, 1)), size=(in_dim, self.hidden_size))
            .astype(np.float32)
        )
        self.random_bias_ = rng.normal(0.0, 0.25, size=self.hidden_size).astype(np.float32)
        Z = self._augment(X_np)
        z_scale = np.maximum(Z.std(axis=0), 1e-6)
        Z = Z / z_scale
        self.random_bias_ = self.random_bias_  # keep attrs explicit for deepcopy clarity

        self.policy_weights_ = rng.normal(0.0, 0.01, size=(Z.shape[1], n_actions)).astype(np.float32)
        self.policy_bias_ = np.zeros(n_actions, dtype=np.float32)
        sw_np = sw_np / max(float(sw_np.mean()), 1e-6)
        reward_scale = max(float(np.nanstd(y_np)), 1.0)
        batch_size = min(self.batch_size, len(X_np))
        l2 = 1e-4

        for _ in range(self.epochs):
            idx_np = rng.choice(len(X_np), size=batch_size, replace=len(X_np) < batch_size)
            Zb = Z[idx_np]
            yb = y_np[idx_np]
            wb = sw_np[idx_np]

            logits = Zb @ self.policy_weights_ + self.policy_bias_
            logits -= logits.max(axis=1, keepdims=True)
            exp_logits = np.exp(logits)
            probs = exp_logits / np.maximum(exp_logits.sum(axis=1, keepdims=True), 1e-8)
            rewards = -np.abs(self.bin_centers_[None, :] - yb[:, None]) / reward_scale
            expected_reward = (probs * rewards).sum(axis=1, keepdims=True)

            grad_logits = probs * (expected_reward - rewards)
            grad_logits *= wb[:, None] / batch_size
            grad_w = Zb.T @ grad_logits + l2 * self.policy_weights_
            grad_b = grad_logits.sum(axis=0)
            grad_norm = np.linalg.norm(grad_w)
            if grad_norm > 5.0:
                grad_w *= 5.0 / grad_norm
            self.policy_weights_ -= self.learning_rate * grad_w.astype(np.float32)
            self.policy_bias_ -= self.learning_rate * grad_b.astype(np.float32)

        self.model = "numpy_softmax_policy"
        self._z_scale = z_scale.astype(np.float32)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if (
            self.model is None
            or self.mean_ is None
            or self.scale_ is None
            or self.bin_centers_ is None
            or self.policy_weights_ is None
            or self.policy_bias_ is None
        ):
            raise RuntimeError("Model not fitted yet")

        X_np = X.to_numpy(dtype=np.float32, copy=True)
        X_np = (X_np - self.mean_) / self.scale_
        Z = self._augment(X_np) / self._z_scale
        logits = Z @ self.policy_weights_ + self.policy_bias_
        logits -= logits.max(axis=1, keepdims=True)
        exp_logits = np.exp(logits)
        probs = exp_logits / np.maximum(exp_logits.sum(axis=1, keepdims=True), 1e-8)
        preds = probs @ self.bin_centers_
        return np.clip(preds, 0.0, None)

    def get_feature_importance(self) -> Optional[pd.Series]:
        return None


def load_or_build_frame(cache_path: Optional[Path], refresh_cache: bool) -> pd.DataFrame:
    if cache_path and cache_path.exists() and not refresh_cache:
        print(f"Loading cached frame: {cache_path}")
        return pd.read_parquet(cache_path)

    df = build_frame()
    if cache_path:
        df.to_parquet(cache_path, index=False)
        print(f"Wrote cached frame: {cache_path}")
    return df


def validate_position_models(
    df: pd.DataFrame,
    position: str,
    rl_args: argparse.Namespace,
) -> pd.DataFrame:
    pos_df = df[df["position"] == position].copy()
    feature_cols = get_position_features(position, list(df.columns))
    feature_cols = _numeric_feature_cols(pos_df, feature_cols)
    if not feature_cols:
        return pd.DataFrame()

    print(f"\n=== {position}: {len(pos_df)} rows, {len(feature_cols)} features ===")
    smoke_df = pos_df[pos_df["fantasy_points"].notna() & np.isfinite(pos_df["fantasy_points"])].copy()
    if not smoke_df.empty:
        smoke_X = smoke_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy(dtype=np.float32)
        smoke_y = smoke_df["fantasy_points"].to_numpy(dtype=np.float32)
        q = np.linspace(0, 1, min(rl_args.bins, max(len(smoke_y) - 1, 2)) + 1)
        smoke_edges = np.unique(np.quantile(smoke_y, q))
        smoke_centers = ((smoke_edges[:-1] + smoke_edges[1:]) / 2.0).astype(np.float32)
        smoke = puffer_smoke_check(smoke_X, smoke_y, smoke_centers)
        print(f"  Puffer wrapper: {smoke.detail}")

    models: list[FantasyModel] = [
        CatBoostModel(**POSITION_CATBOOST_PARAMS.get(position, {})),
        PufferBanditRegressor(
            bins=rl_args.bins,
            hidden_size=rl_args.hidden_size,
            epochs=rl_args.epochs,
            batch_size=rl_args.batch_size,
            learning_rate=rl_args.learning_rate,
            entropy_coef=rl_args.entropy_coef,
            seed=rl_args.seed,
        ),
    ]

    rows = []
    for model in models:
        temporal_weight = POSITION_TEMPORAL_WEIGHTS.get(position, 0.0) if model.name == "catboost" else 0.0
        print(f"  Validating {model.name}...")
        res = walk_forward_validate(
            model,
            pos_df,
            feature_cols,
            "fantasy_points",
            season_col="season",
            position_col=None,
            min_train_seasons=rl_args.min_train_seasons,
            temporal_weight=temporal_weight,
        )
        if not res.empty:
            res["position"] = position
            rows.append(res)

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def summarize(raw: pd.DataFrame) -> pd.DataFrame:
    summary = raw.groupby(["position", "model"]).agg(
        mae=("mae", "mean"),
        rmse=("rmse", "mean"),
        r2=("r2", "mean"),
        n_players=("n_players", "sum"),
        n_seasons=("season", "nunique"),
    ).reset_index()

    cat = summary[summary["model"] == "catboost"][["position", "mae", "r2"]].rename(
        columns={"mae": "catboost_mae", "r2": "catboost_r2"}
    )
    out = summary.merge(cat, on="position", how="left")
    out["mae_delta_vs_catboost"] = out["mae"] - out["catboost_mae"]
    out["r2_delta_vs_catboost"] = out["r2"] - out["catboost_r2"]
    pos_order = {p: i for i, p in enumerate(OFFENSIVE_POSITIONS)}
    model_order = {"catboost": 0, "puffer_bandit_rl": 1}
    out["_pos_order"] = out["position"].map(pos_order)
    out["_model_order"] = out["model"].map(model_order).fillna(99)
    return out.sort_values(["_pos_order", "_model_order"]).drop(columns=["_pos_order", "_model_order"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", nargs="+", default=OFFENSIVE_POSITIONS)
    parser.add_argument("--min-train-seasons", type=int, default=3)
    parser.add_argument("--bins", type=int, default=24)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=700)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-3)
    parser.add_argument("--entropy-coef", type=float, default=0.002)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--frame-cache", default="puffer_rl_frame.parquet")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--out", default="puffer_rl_results.csv")
    parser.add_argument("--raw-out", default="puffer_rl_raw.csv")
    args = parser.parse_args()

    unknown = sorted(set(args.positions) - set(OFFENSIVE_POSITIONS))
    if unknown:
        raise SystemExit(f"Unknown positions: {unknown}. Valid: {OFFENSIVE_POSITIONS}")

    cache = REPO / args.frame_cache if args.frame_cache else None
    df = load_or_build_frame(cache, args.refresh_cache)

    raw_parts = []
    for pos in args.positions:
        res = validate_position_models(df, pos, args)
        if not res.empty:
            raw_parts.append(res)

    if not raw_parts:
        raise SystemExit("No validation results produced")

    raw = pd.concat(raw_parts, ignore_index=True)
    summary = summarize(raw)

    raw_path = REPO / args.raw_out
    summary_path = REPO / args.out
    raw.to_csv(raw_path, index=False)
    summary.to_csv(summary_path, index=False)

    print("\n=== Puffer-compatible RL vs CatBoost ===")
    print(summary.round(4).to_string(index=False))
    print(f"\nWrote {summary_path}")
    print(f"Wrote {raw_path}")
    print(
        "\n"
        + json.dumps(
            {
                "experiment_type": "contextual bandit over discretized fantasy-point bins",
                "reward": "-abs(predicted_points - actual_points)",
                "comparison": "same position features, same walk-forward folds as CatBoost",
                "caveat": "not a full snake-draft RL simulator",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
