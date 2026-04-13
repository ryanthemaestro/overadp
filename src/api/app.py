"""FastAPI backend for the fantasy draft assistant GUI.

Endpoints:
- GET  /api/players       — available player pool with projections
- GET  /api/my-team       — your current roster
- GET  /api/drafted       — players drafted by opponents
- POST /api/draft         — draft a player (yours or opponent's)
- DELETE /api/draft/{pid} — undo a pick
- GET  /api/recommend     — optimizer recommendation for next picks
- POST /api/load-data     — fetch NFL data and train models
"""
import os
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.utils.config import get_roster_config, get_scoring_rules
from src.data.fetch import load_all_data, fetch_adp_data, fetch_injury_data
from src.data.clean import clean_seasonal_stats, clean_roster_info, clean_team_stats, clean_ol_metrics
from src.features.engineer import build_feature_matrix, compute_regression_to_mean_features, compute_adp_features, compute_injury_features, compute_sos_features, compute_rookie_features, compute_stacking_features, compute_teammate_dependency_features, compute_playmaker_features
from src.features.college import compute_college_features
from src.scoring.calculator import add_fantasy_points_to_df
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel
from src.models.catboost_model import CatBoostModel
from src.models.pipeline import PositionPipeline
from src.optimizer.roster_optimizer import optimize_roster, greedy_roster
from src.optimizer.draft_strategy import compute_vbd, compute_positional_scarcity, get_pick_recommendation, compute_bye_weeks, check_bye_conflicts, detect_sleepers_and_busts, detect_position_runs, find_handcuffs

app = FastAPI(title="NFL Fantasy Draft Assistant")

# --- State ---
STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "draft_state.json"


class DraftState:
    """Manages draft state: player pool, my team, opponent picks."""

    def __init__(self):
        self.player_pool: list[dict] = []
        self.my_team: list[str] = []       # player_ids
        self.opponent_picks: list[str] = []  # player_ids
        self.scoring_format: str = "half_ppr"
        self.pipeline: Optional[PositionPipeline] = None
        self.models_trained: bool = False
        self.roster_config: dict = get_roster_config()
        self.bye_weeks: dict = {}  # team → [bye_weeks]

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "my_team": self.my_team,
            "opponent_picks": self.opponent_picks,
            "scoring_format": self.scoring_format,
            "models_trained": self.models_trained,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)

    def load(self):
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                data = json.load(f)
            self.my_team = data.get("my_team", [])
            self.opponent_picks = data.get("opponent_picks", [])
            self.scoring_format = data.get("scoring_format", "half_ppr")
            self.models_trained = data.get("models_trained", False)

    def get_available(self) -> list[dict]:
        drafted = set(self.my_team + self.opponent_picks)
        return [p for p in self.player_pool if p["player_id"] not in drafted]


state = DraftState()


# --- Request models ---
class DraftRequest(BaseModel):
    player_id: str
    team: str  # "mine" or "opponent"


class LoadDataRequest(BaseModel):
    seasons_back: int = 5
    scoring_format: str = "half_ppr"


# --- Endpoints ---

@app.post("/api/load-data")
def load_data(req: LoadDataRequest):
    """Fetch NFL data, build features, train models, generate projections."""
    global state
    try:
        config = get_roster_config()
        current = config["data"]["current_season"]
        seasons = list(range(current - req.seasons_back, current + 1))

        # Filter to seasons that actually have data (skip future years for stats)
        # nfl_data_py only has seasonal stats through the last completed season,
        # but roster/combine data may be available for the current year
        import nfl_data_py as _nfl
        max_stats_season = 2025  # Latest season with completed stats
        projection_season = max_stats_season + 1  # Season we're projecting
        seasons = [s for s in seasons if s <= max_stats_season]
        if len(seasons) < 2:
            raise HTTPException(status_code=400, detail="Need at least 2 seasons of data.")

        # Load historical stats + current-year roster/combine
        data = load_all_data(list(range(min(seasons), projection_season + 1)))
        seasonal = clean_seasonal_stats(data["seasonal"], min_games=config["data"]["min_games"])
        roster = clean_roster_info(data["roster"])
        team = clean_team_stats(data["team"])
        ol = clean_ol_metrics(data["ol"])

        df = build_feature_matrix(seasonal, roster, team, ol)
        df = add_fantasy_points_to_df(df, format=req.scoring_format)
        # Add regression-to-mean features (requires fantasy_points)
        df = compute_regression_to_mean_features(df)
        # Add stacking features (requires fantasy_points for QB avg)
        df = compute_stacking_features(df)
        # Add teammate dependency features (QB quality → WR/TE/RB, WR quality → QB)
        df = compute_teammate_dependency_features(df)

        # Add ADP features (market wisdom — best predictor available)
        adp_data = None
        try:
            adp_data = fetch_adp_data(seasons=[max(seasons)])
            df = compute_adp_features(df, adp_data)
        except Exception:
            pass  # ADP not critical, continue without it

        # Add injury features (risk assessment)
        try:
            injury_data = fetch_injury_data(seasons)
            df = compute_injury_features(df, injury_data)
        except Exception:
            pass  # Injury data not critical

        # Add college/draft features (critical for rookies)
        try:
            df = compute_college_features(
                df,
                draft_df=data.get("draft"),
                combine_df=data.get("combine"),
                player_info_df=data.get("player_info"),
            )
        except Exception:
            pass  # College data not critical for veterans

        # Train per-position models
        pipeline = PositionPipeline(models=[RidgeModel(), RandomForestModel(), XGBoostModel(), CatBoostModel()])
        pipeline.validate_all(df, min_train_seasons=3)
        pipeline.train_final(df)

        # Create projection-season rows for returning players
        # The model needs a row for each player in the projection season with
        # their current team/position from the latest roster
        import pandas as pd
        latest_season = df["season"].max()
        if projection_season > latest_season and not roster.empty:
            # Get players from their most recent season in the data
            latest_rows = df[df["season"] == latest_season].copy()
            # Get current roster for projection season (updated teams/positions)
            roster_proj = roster[roster["season"] == projection_season] if "season" in roster.columns else pd.DataFrame()

            proj_rows = latest_rows.copy()
            proj_rows["season"] = projection_season
            # Zero out current-season stats (they haven't happened yet)
            stat_cols = [c for c in proj_rows.columns if c in [
                "passing_yards", "passing_tds", "interceptions", "sacks",
                "carries", "rushing_yards", "rushing_tds",
                "receptions", "targets", "receiving_yards", "receiving_tds",
                "attempts", "completions", "games", "fantasy_points",
                "pts_lag0", "pts_lag1",
            ]]
            for c in stat_cols:
                if c in proj_rows.columns:
                    proj_rows[c] = 0

            # Update team/position from current roster if available
            if not roster_proj.empty and "player_id" in roster_proj.columns:
                roster_update = roster_proj[["player_id", "team", "position", "age"]].drop_duplicates("player_id")
                roster_update = roster_update.rename(columns={
                    "team": "team_new", "position": "pos_new", "age": "age_new"
                })
                proj_rows = proj_rows.merge(roster_update, on="player_id", how="left")
                if "team_new" in proj_rows.columns:
                    proj_rows["team"] = proj_rows["team_new"].fillna(proj_rows["team"])
                    proj_rows = proj_rows.drop(columns=["team_new"])
                if "pos_new" in proj_rows.columns:
                    proj_rows["position"] = proj_rows["pos_new"].fillna(proj_rows["position"])
                    proj_rows = proj_rows.drop(columns=["pos_new"])
                if "age_new" in proj_rows.columns:
                    proj_rows["age"] = proj_rows["age_new"].fillna(proj_rows["age"])
                    proj_rows = proj_rows.drop(columns=["age_new"])

            # Recompute college features for projection season (draft_year still valid)
            try:
                proj_rows = compute_college_features(
                    proj_rows,
                    draft_df=data.get("draft"),
                    combine_df=data.get("combine"),
                    player_info_df=data.get("player_info"),
                )
            except Exception:
                pass
            # Recompute rookie features for projection season
            proj_rows = compute_rookie_features(proj_rows)

            # Add projection rows to the dataframe
            df = pd.concat([df, proj_rows], ignore_index=True)

            # Add rookie rows for newly drafted players who have no historical stats
            # These players only exist in draft/combine data, not in seasonal stats
            draft_df = data.get("draft")
            combine_df = data.get("combine")
            if draft_df is not None and not draft_df.empty:
                draft_year_col = "season" if "season" in draft_df.columns else "draft_year"
                if draft_year_col in draft_df.columns:
                    new_rookies = draft_df[draft_df[draft_year_col] == projection_season]
                    if not new_rookies.empty:
                        # Get existing player_ids to avoid duplicates
                        existing_ids = set(df["player_id"].unique()) if "player_id" in df.columns else set()
                        # Filter to offensive positions only
                        off_pos = {"QB", "RB", "WR", "TE"}
                        pos_col = "position" if "position" in new_rookies.columns else "pos"
                        if pos_col in new_rookies.columns:
                            new_rookies = new_rookies[new_rookies[pos_col].str.upper().isin(off_pos)]
                        # Filter out players already in the data
                        if "player_id" in new_rookies.columns:
                            new_rookies = new_rookies[~new_rookies["player_id"].isin(existing_ids)]

                        if not new_rookies.empty:
                            # Create minimal feature rows for rookies
                            rookie_rows = pd.DataFrame()
                            for col in df.columns:
                                if col in new_rookies.columns:
                                    rookie_rows[col] = new_rookies[col].values[:len(new_rookies)]
                                else:
                                    rookie_rows[col] = 0
                            rookie_rows["season"] = projection_season
                            rookie_rows["fantasy_points"] = 0
                            rookie_rows["games"] = 0
                            rookie_rows["is_rookie"] = 1
                            # Set team from draft data
                            if "draft_team" in new_rookies.columns:
                                rookie_rows["team"] = new_rookies["draft_team"].values[:len(new_rookies)]
                            # Set position
                            if pos_col in new_rookies.columns:
                                rookie_rows["position"] = new_rookies[pos_col].str.upper().values[:len(new_rookies)]

                            # Compute college features for rookies
                            try:
                                rookie_rows = compute_college_features(
                                    rookie_rows,
                                    draft_df=draft_df,
                                    combine_df=combine_df,
                                    player_info_df=data.get("player_info"),
                                )
                            except Exception:
                                pass
                            rookie_rows = compute_rookie_features(rookie_rows)

                            df = pd.concat([df, rookie_rows], ignore_index=True)
                            import logging
                            logging.info(f"Added {len(rookie_rows)} rookie rows for {projection_season}")

        # Generate projections for the projection season
        projections = pipeline.predict(df, target_season=projection_season)
        if projections.empty:
            # Fallback: use latest season directly
            projections = pipeline.predict(df, target_season=latest_season)

        # Merge ADP back onto projections (pipeline.predict now includes adp,
        # but re-merge catches any that were missed via player_id)
        if adp_data is not None and not adp_data.empty:
            import pandas as pd
            # Build player_id → adp mapping from the feature matrix (which already
            # has correctly matched ADP via compute_adp_features)
            if "adp" in df.columns and "player_id" in df.columns:
                latest = df[df["season"] == df["season"].max()]
                id_adp = latest[["player_id", "adp"]].drop_duplicates("player_id")
                id_adp = id_adp.rename(columns={"adp": "adp_from_df"})
                projections = projections.merge(id_adp, on="player_id", how="left")
                if "adp_from_df" in projections.columns:
                    if "adp" in projections.columns:
                        projections["adp"] = projections["adp_from_df"].fillna(projections["adp"])
                    else:
                        projections["adp"] = projections["adp_from_df"]
                    projections = projections.drop(columns=["adp_from_df"])
            if "adp" in projections.columns:
                projections["adp"] = projections["adp"].fillna(200)

        # Build player pool — clean NaN values for JSON serialization
        for col in projections.columns:
            if projections[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                projections[col] = projections[col].fillna(0)
        state.player_pool = projections.to_dict("records")
        state.scoring_format = req.scoring_format
        state.pipeline = pipeline
        state.models_trained = True
        # Compute bye weeks for conflict detection
        state.bye_weeks = compute_bye_weeks(season=max(seasons))
        state.save()

        return {
            "status": "ok",
            "players_loaded": len(state.player_pool),
            "positions": projections["position"].value_counts().to_dict() if not projections.empty else {},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/players")
def get_players(position: Optional[str] = None, sort_by: str = "vbd", limit: int = 200):
    """Get available player pool sorted by VBD (value above replacement) by default.

    Uses draft-board sort: interleaves positions so you don't see
    50 RBs in a row. Within each position tier, respects VBD ranking.
    """
    available = state.get_available()
    if not available:
        return []

    # Compute VBD for all available players if not already present
    import pandas as pd
    import numpy as np
    df = pd.DataFrame(available)
    if "vbd" not in df.columns or df["vbd"].isna().all():
        try:
            df = compute_vbd(df, roster_config=state.roster_config)
            # Clean NaN for JSON
            df = df.replace([np.inf, -np.inf], 0)
            for col in df.columns:
                if df[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                    df[col] = df[col].fillna(0)
            available = df.to_dict("records")
            # Update state with VBD values
            for p in state.player_pool:
                if p["player_id"] in {a["player_id"] for a in available}:
                    match = next(a for a in available if a["player_id"] == p["player_id"])
                    p["vbd"] = match.get("vbd", 0)
                    p["replacement_pts"] = match.get("replacement_pts", 0)
        except Exception:
            sort_by = "projected_points"

    if position:
        available = [p for p in available if p.get("position") == position.upper()]

    if sort_by == "projected_points":
        available.sort(key=lambda p: p.get("projected_points", 0) or 0, reverse=True)
    elif sort_by == "vbd":
        # Draft-board sort: interleave positions by VBD tier
        # This prevents all RBs from clustering at the top
        available = _draft_board_sort(available)
    else:
        available.sort(key=lambda p: p.get(sort_by, 0) or 0, reverse=True)

    # Sanitize NaN/inf for JSON serialization
    import math
    for p in available:
        for k, v in p.items():
            try:
                fv = float(v)
                if math.isnan(fv) or math.isinf(fv):
                    p[k] = 0
            except (ValueError, TypeError):
                pass

    return available[:limit]


def _sanitize(records: list[dict] | dict) -> list[dict] | dict:
    """Replace NaN/inf floats with 0 for JSON serialization."""
    import math
    def _clean(v):
        if isinstance(v, float) or (hasattr(v, 'dtype') and hasattr(v, 'item')):
            try:
                fv = float(v)
                if math.isnan(fv) or math.isinf(fv):
                    return 0
            except (ValueError, TypeError):
                pass
        return v
    if isinstance(records, dict):
        for k in records:
            records[k] = _clean(records[k])
            if isinstance(records[k], list):
                for r in records[k]:
                    if isinstance(r, dict):
                        for rk in r:
                            r[rk] = _clean(r[rk])
        return records
    for r in records:
        if isinstance(r, dict):
            for k in r:
                r[k] = _clean(r[k])
    return records


def _add_kicker_defense(projections: "pd.DataFrame", adp_data: Optional["pd.DataFrame"], seasons: list[int]) -> "pd.DataFrame":
    """Add Kicker and Defense players to projections.

    nfl_data_py doesn't include kicker or team defense stats in seasonal data.
    We add them using ADP data and historical average fantasy points.
    """
    if projections.empty:
        return projections

    import pandas as pd
    import numpy as np

    new_players = []

    # Historical average fantasy points (half-PPR)
    # Based on 2019-2024 averages for K and DEF
    k_avg_pts = 110.0   # Top K averages ~110-130 pts/season
    k_range = (90, 140)
    def_avg_pts = 95.0  # Top DEF averages ~90-120 pts/season
    def_range = (70, 120)

    # Add kickers from ADP if available
    if adp_data is not None and not adp_data.empty:
        k_adp = adp_data[adp_data['position'] == 'K'] if 'position' in adp_data.columns else pd.DataFrame()
        for _, row in k_adp.iterrows():
            # Project based on ADP rank (lower ADP = better kicker)
            adp_val = row.get('adp', 200)
            # Kickers are fairly interchangeable; project near average with slight ADP adjustment
            proj_pts = k_avg_pts - (adp_val - 120) * 0.1  # Small ADP adjustment
            proj_pts = max(min(proj_pts, k_range[1]), k_range[0])
            uncertainty = 15.0  # Kickers are relatively predictable
            new_players.append({
                'player_id': row.get('player_id', f"K-{row.get('player_name', '')}"),
                'player_name': row.get('player_name', ''),
                'position': 'K',
                'team': row.get('team', ''),
                'projected_points': round(proj_pts, 1),
                'ci_low': round(proj_pts - 1.28 * uncertainty, 1),
                'ci_high': round(proj_pts + 1.28 * uncertainty, 1),
                'uncertainty': uncertainty,
                'risk': 'low',
                'adp': adp_val,
                'model_name': 'historical_avg',
            })

        # Add defenses from ADP (position is "DST" in FantasyPros)
        def_adp = adp_data[adp_data['position'].isin(['DEF', 'DST'])] if 'position' in adp_data.columns else pd.DataFrame()
        for _, row in def_adp.iterrows():
            adp_val = row.get('adp', 200)
            proj_pts = def_avg_pts - (adp_val - 100) * 0.15
            proj_pts = max(min(proj_pts, def_range[1]), def_range[0])
            uncertainty = 20.0  # Defenses are more volatile
            new_players.append({
                'player_id': row.get('player_id', f"DEF-{row.get('player_name', '')}"),
                'player_name': row.get('player_name', ''),
                'position': 'DEF',
                'team': row.get('team', ''),
                'projected_points': round(proj_pts, 1),
                'ci_low': round(max(proj_pts - 1.28 * uncertainty, 0), 1),
                'ci_high': round(proj_pts + 1.28 * uncertainty, 1),
                'uncertainty': uncertainty,
                'risk': 'medium',
                'adp': adp_val,
                'model_name': 'historical_avg',
            })

    if new_players:
        new_df = pd.DataFrame(new_players)
        projections = pd.concat([projections, new_df], ignore_index=True)

    # Clean NaN values that break JSON serialization
    for col in projections.columns:
        if projections[col].dtype in ['float64', 'float32']:
            projections[col] = projections[col].fillna(0)

    return projections


def _draft_board_sort(players: list[dict]) -> list[dict]:
    """Sort players for a draft board — VBD-first with positional run breaking.

    Sorts primarily by VBD (best available first), but when the same position
    appears 3+ times in a row, the next player from that position is pushed
    down until a different position appears. This prevents 50 RBs in a row
    while keeping the order natural and value-driven.
    """
    # Sort all players by VBD descending
    sorted_players = sorted(players, key=lambda p: p.get("vbd", 0) or 0, reverse=True)

    result = []
    consecutive_pos = 0
    last_pos = None
    deferred = []  # Players pushed back due to run-breaking

    i = 0
    while i < len(sorted_players) or deferred:
        # If we have deferred players, try to insert them when position changes
        if deferred and (not result or result[-1].get("position") != deferred[0].get("position")):
            result.append(deferred.pop(0))
            last_pos = result[-1].get("position")
            consecutive_pos = 1
            continue

        if i >= len(sorted_players):
            # Flush remaining deferred
            result.extend(deferred)
            break

        player = sorted_players[i]
        pos = player.get("position")

        # If same position 3+ times in a row, defer this player
        if pos == last_pos and consecutive_pos >= 3:
            deferred.append(player)
            i += 1
            continue

        result.append(player)
        if pos == last_pos:
            consecutive_pos += 1
        else:
            consecutive_pos = 1
            last_pos = pos
        i += 1

    return result


@app.get("/api/my-team")
def get_my_team():
    """Get your current roster with slot assignments."""
    my_players = [p for p in state.player_pool if p["player_id"] in state.my_team]
    return _sanitize({"players": my_players, "count": len(my_players)})


@app.get("/api/drafted")
def get_drafted():
    """Get players drafted by opponents."""
    opp_players = [p for p in state.player_pool if p["player_id"] in state.opponent_picks]
    return _sanitize({"players": opp_players, "count": len(opp_players)})


@app.post("/api/draft")
def draft_player(req: DraftRequest):
    """Draft a player to your team or mark as opponent's pick."""
    if req.player_id not in [p["player_id"] for p in state.player_pool]:
        raise HTTPException(status_code=404, detail="Player not found")
    if req.player_id in state.my_team or req.player_id in state.opponent_picks:
        raise HTTPException(status_code=400, detail="Player already drafted")

    if req.team == "mine":
        state.my_team.append(req.player_id)
    elif req.team == "opponent":
        state.opponent_picks.append(req.player_id)
    else:
        raise HTTPException(status_code=400, detail="team must be 'mine' or 'opponent'")

    state.save()
    return {"status": "ok", "my_team_size": len(state.my_team), "opponent_picks_size": len(state.opponent_picks)}


@app.delete("/api/draft/{player_id}")
def undo_draft(player_id: str):
    """Undo a draft pick."""
    if player_id in state.my_team:
        state.my_team.remove(player_id)
    elif player_id in state.opponent_picks:
        state.opponent_picks.remove(player_id)
    else:
        raise HTTPException(status_code=404, detail="Player not in any draft list")
    state.save()
    return {"status": "ok"}


@app.get("/api/recommend")
def get_recommendation(picks_ahead: int = 1):
    """Get optimizer recommendation for next picks."""
    if not state.player_pool:
        raise HTTPException(status_code=400, detail="No data loaded. Run /api/load-data first.")

    available = state.get_available()
    if not available:
        raise HTTPException(status_code=400, detail="No players available.")

    projections_df = __import__("pandas").DataFrame(available)
    remaining = sum(state.roster_config["roster_slots"].values()) - len(state.my_team)

    try:
        result = optimize_roster(
            projections_df,
            drafted_players=state.opponent_picks,
            remaining_picks=min(remaining, len(available)),
            scoring_format=state.scoring_format,
        )
        return _sanitize({"recommendations": result.to_dict("records"), "total_projected_points": float(result["projected_points"].sum())})
    except Exception as e:
        # Fallback to greedy
        result = greedy_roster(
            projections_df,
            drafted_players=state.opponent_picks,
            remaining_picks=min(remaining, len(available)),
            scoring_format=state.scoring_format,
        )
        return _sanitize({"recommendations": result.to_dict("records"), "total_projected_points": float(result["projected_points"].sum()) if "projected_points" in result.columns else 0})


@app.get("/api/status")
def get_status():
    """Get current draft status."""
    return _sanitize({
        "models_trained": state.models_trained,
        "my_team_size": len(state.my_team),
        "opponent_picks_size": len(state.opponent_picks),
        "available_players": len(state.get_available()),
        "scoring_format": state.scoring_format,
    })


@app.post("/api/reset")
def reset_draft():
    """Reset the draft state."""
    state.my_team = []
    state.opponent_picks = []
    state.save()
    return {"status": "ok"}


@app.get("/api/bye-conflicts")
def get_bye_conflicts():
    """Check current roster for bye week conflicts."""
    my_players = [p for p in state.player_pool if p["player_id"] in state.my_team]
    conflicts = check_bye_conflicts(my_players, state.bye_weeks, state.roster_config)
    return {
        "conflicts": conflicts,
        "bye_weeks": state.bye_weeks,
        "conflict_count": len(conflicts),
        "critical_count": len([c for c in conflicts if c["severity"] == "critical"]),
    }


@app.get("/api/sleepers")
def get_sleepers(threshold: float = 40):
    """Detect sleepers and busts by comparing model projections vs ADP."""
    if not state.player_pool:
        raise HTTPException(status_code=400, detail="No data loaded.")
    import pandas as pd
    df = pd.DataFrame(state.player_pool)
    # Try to get ADP data
    try:
        adp_data = fetch_adp_data(seasons=[2024])
    except Exception:
        adp_data = None
    results = detect_sleepers_and_busts(df, adp_data, threshold=threshold)
    return {"sleepers": [r for r in results if r["label"] == "SLEEPER"],
            "busts": [r for r in results if r["label"] == "BUST"],
            "total_flagged": len(results)}


@app.get("/api/position-runs")
def get_position_runs(window: int = 6):
    """Detect position runs in recent opponent picks."""
    all_picks = [p for p in state.player_pool if p["player_id"] in state.opponent_picks]
    runs = detect_position_runs(all_picks, window=window)
    return {"runs": runs, "recent_picks_count": len(all_picks)}


@app.get("/api/handcuffs")
def get_handcuffs():
    """Find handcuff RBs for your starting RBs."""
    my_players = [p for p in state.player_pool if p["player_id"] in state.my_team]
    available = state.get_available()
    cuffs = find_handcuffs(my_players, available)
    return {"handcuffs": cuffs}


@app.get("/api/vbd")
def get_vbd(num_teams: int = 12):
    """Get player pool ranked by VBD (value above replacement)."""
    if not state.player_pool:
        raise HTTPException(status_code=400, detail="No data loaded.")
    import pandas as pd
    df = pd.DataFrame(state.get_available())
    vbd_df = compute_vbd(df, num_teams=num_teams, roster_config=state.roster_config)
    vbd_df = vbd_df.sort_values("vbd", ascending=False)
    return vbd_df.head(100).to_dict("records")


@app.get("/api/scarcity")
def get_scarcity(num_teams: int = 12):
    """Get positional scarcity analysis."""
    if not state.player_pool:
        raise HTTPException(status_code=400, detail="No data loaded.")
    import pandas as pd
    df = pd.DataFrame(state.get_available())
    scarcity = compute_positional_scarcity(df, num_teams=num_teams, roster_config=state.roster_config)
    return scarcity.to_dict("records")


@app.get("/api/pick-advice")
def get_pick_advice(pick: int = 1, num_teams: int = 12):
    """Get strategic pick recommendation based on VBD + roster needs."""
    if not state.player_pool:
        raise HTTPException(status_code=400, detail="No data loaded.")
    import pandas as pd
    df = pd.DataFrame(state.get_available())
    my_positions = [p.get("position", "") for p in state.player_pool if p["player_id"] in state.my_team]
    advice = get_pick_recommendation(
        df, current_pick=pick, my_roster_positions=my_positions,
        num_teams=num_teams, roster_config=state.roster_config,
    )
    return advice


# Serve static frontend
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
