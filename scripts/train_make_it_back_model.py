#!/usr/bin/env python3
"""Train/evaluate a will-make-it-back model from Sleeper draft examples."""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"


NUMERIC_FEATURES = [
    "teams",
    "rounds",
    "slots_qb",
    "slots_rb",
    "slots_wr",
    "slots_te",
    "slots_flex",
    "slots_super_flex",
    "slots_bn",
    "current_pick",
    "draft_slot",
    "next_pick",
    "picks_until_next",
    "candidate_rank_available",
    "candidate_adp",
    "candidate_adp_rank",
    "candidate_projected_points",
    "candidate_vbd",
    "candidate_model_rank",
    "adp_to_pick",
    "adp_to_next_pick",
]
CATEGORICAL_FEATURES = ["scoring_type", "candidate_position"]


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def available_features(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric = [c for c in NUMERIC_FEATURES if c in df.columns]
    categorical = [c for c in CATEGORICAL_FEATURES if c in df.columns]
    return numeric, categorical


def make_model(numeric: list[str], categorical: list[str]) -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), numeric),
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )
    clf = HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.04,
        max_leaf_nodes=31,
        l2_regularization=0.03,
        random_state=42,
    )
    return Pipeline([("pre", pre), ("model", clf)])


def evaluate(name: str, y: pd.Series, p: np.ndarray) -> dict[str, float | str | int]:
    out: dict[str, float | str | int] = {"split": name, "rows": int(len(y))}
    if y.nunique() > 1:
        out["auc"] = float(roc_auc_score(y, p))
        out["log_loss"] = float(log_loss(y, np.clip(p, 1e-5, 1 - 1e-5)))
    else:
        out["auc"] = float("nan")
        out["log_loss"] = float("nan")
    out["brier"] = float(brier_score_loss(y, p))
    out["base_rate"] = float(y.mean())
    out["avg_pred"] = float(np.mean(p))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA_DIR / "sleeper_make_it_back.parquet")
    parser.add_argument("--target", choices=["will_make_it_back", "will_be_gone"], default="will_be_gone")
    parser.add_argument("--holdout-season", type=int, default=2025)
    parser.add_argument("--model-out", type=Path, default=DATA_DIR / "make_it_back_model.pkl")
    parser.add_argument("--metrics-out", type=Path, default=DATA_DIR / "make_it_back_metrics.csv")
    args = parser.parse_args()

    df = read_table(args.data)
    if df.empty:
        raise SystemExit(f"No rows found in {args.data}")
    if args.target not in df.columns:
        raise SystemExit(f"Missing target column {args.target}")

    df = df[df[args.target].notna()].copy()
    if "candidate_adp" in df.columns:
        # The deployable model should learn from live board features; rows with
        # no board match are useful for coverage reporting but not for training.
        matched = df["candidate_adp"].notna().mean()
        print(f"Board feature match rate: {matched:.1%}")
        df = df[df["candidate_adp"].notna()].copy()
    numeric, categorical = available_features(df)
    if not numeric and not categorical:
        raise SystemExit("No usable feature columns found")

    train = df[df["season"] != args.holdout_season].copy()
    test = df[df["season"] == args.holdout_season].copy()
    if train.empty or test.empty:
        # Fall back to draft-level random split when only one season is present.
        rng = np.random.default_rng(42)
        draft_ids = np.asarray(sorted(df["draft_id"].unique()))
        rng.shuffle(draft_ids)
        cutoff = max(1, int(len(draft_ids) * 0.8))
        train_ids = set(draft_ids[:cutoff])
        train = df[df["draft_id"].isin(train_ids)].copy()
        test = df[~df["draft_id"].isin(train_ids)].copy()
        print("Using draft-level random holdout because requested season split was unavailable")

    model = make_model(numeric, categorical)
    X_train = train[numeric + categorical]
    y_train = train[args.target].astype(int)
    X_test = test[numeric + categorical]
    y_test = test[args.target].astype(int)
    model.fit(X_train, y_train)

    metrics = [
        evaluate("train", y_train, model.predict_proba(X_train)[:, 1]),
        evaluate("test", y_test, model.predict_proba(X_test)[:, 1]),
    ]
    metrics_df = pd.DataFrame(metrics)
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_df.to_csv(args.metrics_out, index=False)
    with args.model_out.open("wb") as f:
        pickle.dump({"model": model, "numeric": numeric, "categorical": categorical, "target": args.target}, f)

    print(metrics_df.round(4).to_string(index=False))
    print(f"Wrote model -> {args.model_out}")
    print(f"Wrote metrics -> {args.metrics_out}")


if __name__ == "__main__":
    main()
