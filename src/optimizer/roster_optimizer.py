"""Roster optimizer: integer programming solver for best fantasy roster.

Maximizes projected fantasy points subject to:
- Position slot constraints (1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, etc.)
- Already-drafted players excluded
- Remaining pick limit
"""
import pandas as pd
import numpy as np
from typing import Optional
from src.utils.config import get_roster_config

try:
    from pulp import LpMaximize, LpProblem, LpVariable, lpSum, LpBinary, LpStatus, value, PULP_CBC_CMD
    HAS_PULP = True
except ImportError:
    HAS_PULP = False


def optimize_roster(
    player_projections: pd.DataFrame,
    drafted_players: Optional[list[str]] = None,
    remaining_picks: Optional[int] = None,
    scoring_format: str = "half_ppr",
    roster_config: Optional[dict] = None,
) -> pd.DataFrame:
    """Optimize roster selection using integer programming.

    Args:
        player_projections: Must have columns: player_id, player_name, position, projected_points
        drafted_players: Already-drafted player IDs to exclude
        remaining_picks: Picks left in draft
        scoring_format: Scoring format to use
        roster_config: Override default roster config

    Returns:
        DataFrame of selected players with projected points and assigned slot
    """
    if not HAS_PULP:
        raise ImportError("pulp required: pip install pulp")

    config = roster_config or get_roster_config()
    slots = config["roster_slots"]
    flex_eligible = config["flex_eligible"]

    drafted_players = drafted_players or []
    if remaining_picks is None:
        remaining_picks = sum(slots.values()) - len(drafted_players)

    # Filter out drafted
    available = player_projections[~player_projections["player_id"].isin(drafted_players)].copy()

    points_col = f"projected_points_{scoring_format}" if f"projected_points_{scoring_format}" in available.columns else "projected_points"

    # Build problem
    prob = LpProblem("fantasy_roster", LpMaximize)

    # Decision variables
    player_vars = {row["player_id"]: LpVariable(f"pick_{row['player_id']}", cat=LpBinary)
                   for _, row in available.iterrows()}

    # Objective: maximize projected points
    prob += lpSum(player_vars[r["player_id"]] * r[points_col] for _, r in available.iterrows())

    # Constraint: total picks
    prob += lpSum(player_vars.values()) <= remaining_picks

    # Position constraints
    for pos, count in slots.items():
        if pos in ("flex", "bench"):
            continue
        # Match both config key and common abbreviations
        pos_aliases = [pos, pos.upper()]
        if pos == "defense":
            pos_aliases += ["DEF", "DST"]
        elif pos == "k":
            pos_aliases.append("K")
        pos_players = available[available["position"].isin(pos_aliases)]["player_id"].tolist()
        if pos_players:
            # Max: slot count + possible flex overflow
            flex_bonus = 1 if pos in flex_eligible else 0
            prob += lpSum(player_vars[pid] for pid in pos_players) <= count + flex_bonus
            # Min: must fill starter slots (only if enough players available)
            if len(pos_players) >= count:
                prob += lpSum(player_vars[pid] for pid in pos_players) >= count

    # Solve (suppress CBC output)
    try:
        prob.solve(PULP_CBC_CMD(msg=0))
    except Exception:
        prob.solve()

    # Extract results
    selected_ids = [pid for pid, var in player_vars.items() if var.varValue == 1]
    selected = available[available["player_id"].isin(selected_ids)].copy()
    selected = selected.sort_values(points_col, ascending=False).reset_index(drop=True)

    # Assign roster slots
    selected["roster_slot"] = _assign_slots(selected, slots, flex_eligible)

    return selected


def _normalize_position(pos: str) -> str:
    """Normalize position names to match roster config keys (lowercase)."""
    mapping = {"DEF": "defense", "DST": "defense"}
    upper = pos.upper()
    return mapping.get(upper, upper.lower())


def _assign_slots(selected: pd.DataFrame, slots: dict, flex_eligible: list[str]) -> list[str]:
    """Assign each selected player to a roster slot (QB1, RB1, WR2, FLEX, BN, etc.)."""
    assignments = []
    slot_counts = {pos: 0 for pos in slots}
    flex_used = False

    for _, row in selected.iterrows():
        pos = _normalize_position(row["position"])
        if slot_counts.get(pos, 0) < slots.get(pos, 0):
            slot_counts[pos] += 1
            assignments.append(f"{pos}{slot_counts[pos]}")
        elif pos in flex_eligible and not flex_used:
            flex_used = True
            assignments.append("FLEX")
        else:
            slot_counts["bench"] = slot_counts.get("bench", 0) + 1
            assignments.append(f"BN{slot_counts['bench']}")

    return assignments


def greedy_roster(
    player_projections: pd.DataFrame,
    drafted_players: Optional[list[str]] = None,
    remaining_picks: Optional[int] = None,
    scoring_format: str = "half_ppr",
    roster_config: Optional[dict] = None,
) -> pd.DataFrame:
    """Greedy fallback if PuLP unavailable. Picks highest-value player that fits roster needs.

    Less optimal than ILP but works without pulp.
    """
    config = roster_config or get_roster_config()
    slots = config["roster_slots"]
    flex_eligible = config["flex_eligible"]

    drafted_players = drafted_players or []
    remaining_picks = remaining_picks or (sum(slots.values()) - len(drafted_players))

    points_col = f"projected_points_{scoring_format}" if f"projected_points_{scoring_format}" in player_projections.columns else "projected_points"

    available = player_projections[~player_projections["player_id"].isin(drafted_players)].copy()
    available = available.sort_values(points_col, ascending=False)

    filled = {pos: 0 for pos in slots}
    selected = []

    for _, row in available.iterrows():
        if len(selected) >= remaining_picks:
            break
        pos = row["position"]

        # Can fill starter slot?
        if filled.get(pos, 0) < slots.get(pos, 0):
            filled[pos] += 1
            selected.append(row)
        # Can fill flex?
        elif pos in flex_eligible and filled.get("flex", 0) < slots.get("flex", 0):
            filled["flex"] += 1
            selected.append(row)
        # Bench?
        elif filled.get("bench", 0) < slots.get("bench", 0):
            filled["bench"] += 1
            selected.append(row)

    return pd.DataFrame(selected).reset_index(drop=True)
