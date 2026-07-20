"""Draft strategy: value-based drafting, positional scarcity, and pick recommendations.

Core insight: Don't draft by raw projected points. Draft by VALUE above replacement.

Value-Based Drafting (VBD):
  VBD = projected_points - replacement_points(position)
  replacement_points = projected points of the Nth player at that position,
  where N = num_teams * slots_for_position

Positional Scarcity:
  - Allocate every exclusive starter slot across the league.
  - Allocate FLEX/Superflex from the best remaining eligible players.
  - Measure each player against the last allocated starter at that position.
  - Use conditional next-turn availability for value-over-next-available.

Bye Week Conflict Avoidance:
  Don't draft two starters with the same bye week unless you have bench coverage.
  Penalize picks that create unresolvable bye week conflicts.

Position labels are descriptive outputs, not hard-coded draft bonuses. The
experimental policy must beat ADP and the production guarded policy on held-
out drafts before it is eligible for the live board.
"""
from typing import Optional

import numpy as np
import pandas as pd

from src.utils.config import get_roster_config


POSITION_KEY_ALIASES = {
    "qb": "QB",
    "rb": "RB",
    "wr": "WR",
    "te": "TE",
    "k": "K",
    "def": "DEF",
    "dst": "DEF",
    "defense": "DEF",
}


def _position_label(value: str) -> str:
    """Normalize config/data position names to the exported labels."""
    key = str(value).strip().lower()
    return POSITION_KEY_ALIASES.get(key, key.upper())


def _slot_demands(
    roster_config: dict,
    num_teams: int,
) -> tuple[dict[str, int], list[dict]]:
    """Return exclusive-position and flexible-slot league-wide demand.

    Flexible slots are described separately because they must be filled from
    the best *remaining* eligible players after exclusive starter slots are
    allocated. Treating FLEX as the minimum of unrelated position baselines
    can put replacement dozens of points below the actual marginal starter.
    """
    slots = roster_config.get("roster_slots", {})
    configured_eligibility = roster_config.get("slot_eligibility", {})
    base_demands: dict[str, int] = {}
    flexible_demands: list[dict] = []

    for raw_key, raw_count in slots.items():
        key = str(raw_key).strip().lower()
        count = max(0, int(raw_count or 0))
        if key == "bench" or count == 0:
            continue

        if key in POSITION_KEY_ALIASES:
            pos = _position_label(key)
            base_demands[pos] = base_demands.get(pos, 0) + num_teams * count
            continue

        eligible = configured_eligibility.get(key)
        if eligible is None and key == "flex":
            eligible = roster_config.get("flex_eligible", ["rb", "wr", "te"])
        if eligible is None and key in ("superflex", "super_flex", "sf"):
            eligible = roster_config.get(
                "superflex_eligible", ["qb", "rb", "wr", "te"]
            )
        if not eligible:
            continue

        flexible_demands.append({
            "slot": key.upper(),
            "count": num_teams * count,
            "eligible": tuple(dict.fromkeys(_position_label(p) for p in eligible)),
        })

    # Fill narrower slot groups first when formats define multiple flex types.
    flexible_demands.sort(key=lambda group: (len(group["eligible"]), group["slot"]))
    return base_demands, flexible_demands


def compute_league_slot_allocation(
    projections: pd.DataFrame,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> dict:
    """Allocate league-wide starter slots and return true marginal baselines.

    Exclusive slots (QB/RB/WR/TE/etc.) are filled first. FLEX and Superflex
    slots are then filled from the highest-projected remaining eligible player,
    which makes the marginal FLEX value an actual player cutoff rather than the
    minimum of independently calculated position cutoffs.
    """
    config = roster_config or get_roster_config()
    if projections.empty:
        return {
            "num_teams": int(num_teams),
            "base_slot_counts": {},
            "flex_slot_counts": {},
            "flex_eligible": {},
            "flex_allocations": {},
            "selected_counts": {},
            "base_replacement": {},
            "flex_replacement": {},
            "effective_replacement": {},
        }
    if "position" not in projections or "projected_points" not in projections:
        raise ValueError("projections must contain position and projected_points")

    base_demands, flexible_demands = _slot_demands(config, int(num_teams))
    work = projections[["position", "projected_points"]].copy()
    work["position"] = work["position"].map(_position_label)
    work["projected_points"] = pd.to_numeric(
        work["projected_points"], errors="coerce"
    ).fillna(0.0)

    all_positions = set(base_demands)
    for group in flexible_demands:
        all_positions.update(group["eligible"])
    points_by_pos = {
        pos: work.loc[work["position"] == pos, "projected_points"]
        .sort_values(ascending=False)
        .to_numpy(dtype=float)
        for pos in sorted(all_positions)
    }

    selected_counts = {pos: 0 for pos in all_positions}
    base_replacement: dict[str, float] = {}
    for pos, demand in base_demands.items():
        values = points_by_pos.get(pos, np.asarray([], dtype=float))
        selected = min(int(demand), len(values))
        selected_counts[pos] = selected
        base_replacement[pos] = float(values[selected - 1]) if selected else 0.0

    flex_replacement: dict[str, float] = {}
    flex_allocations: dict[str, dict[str, int]] = {}
    for group in flexible_demands:
        slot = group["slot"]
        allocations = {pos: 0 for pos in group["eligible"]}
        marginal = 0.0
        for _ in range(group["count"]):
            best_pos = None
            best_points = -np.inf
            for pos in group["eligible"]:
                values = points_by_pos.get(pos, np.asarray([], dtype=float))
                cursor = selected_counts.get(pos, 0)
                if cursor < len(values) and values[cursor] > best_points:
                    best_pos = pos
                    best_points = float(values[cursor])
            if best_pos is None:
                break
            selected_counts[best_pos] = selected_counts.get(best_pos, 0) + 1
            allocations[best_pos] += 1
            marginal = best_points
        flex_allocations[slot] = allocations
        flex_replacement[slot] = float(marginal)

    # Once flexible slots have been assigned, each position's replacement is
    # the final allocated starter at that position. A shared FLEX cutoff is a
    # property of the slot auction, not a baseline that should be granted to
    # every FLEX-eligible player (which would double-count the same slot).
    effective_replacement: dict[str, float] = {}
    for pos in sorted(all_positions):
        values = points_by_pos.get(pos, np.asarray([], dtype=float))
        selected = selected_counts.get(pos, 0)
        effective_replacement[pos] = (
            float(values[selected - 1]) if selected and selected <= len(values) else 0.0
        )

    return {
        "num_teams": int(num_teams),
        "base_slot_counts": dict(sorted(base_demands.items())),
        "flex_slot_counts": {g["slot"]: g["count"] for g in flexible_demands},
        "flex_eligible": {g["slot"]: list(g["eligible"]) for g in flexible_demands},
        "flex_allocations": flex_allocations,
        "selected_counts": dict(sorted(selected_counts.items())),
        "base_replacement": dict(sorted(base_replacement.items())),
        "flex_replacement": flex_replacement,
        "effective_replacement": effective_replacement,
    }


def compute_bye_weeks(season: int = 2024) -> dict[str, list[int]]:
    """Compute bye weeks for each team from the NFL schedule.

    Returns dict mapping team abbrev → list of bye weeks.
    """
    try:
        import nfl_data_py as nfl
        sched = nfl.import_schedules([season])
        sched = sched[sched["game_type"] == "REG"]
        all_weeks = set(range(1, 19))
        teams = set(sched["away_team"].unique()) | set(sched["home_team"].unique())
        byes = {}
        for team in teams:
            played = set(sched[(sched["away_team"] == team) | (sched["home_team"] == team)]["week"].unique())
            bye = sorted(all_weeks - played)
            if bye:
                byes[team] = bye
        return byes
    except Exception:
        return {}


def check_bye_conflicts(
    roster: list[dict],
    bye_weeks: dict[str, list[int]],
    roster_config: Optional[dict] = None,
) -> list[dict]:
    """Check for bye week conflicts in a roster.

    A conflict occurs when two STARTERS at the same position share a bye week
    and there's no bench player at that position to cover them.

    Returns list of conflict dicts:
        {week, position, players: [...], has_coverage: bool, severity: 'critical'|'warning'}
    """
    if not roster or not bye_weeks:
        return []

    config = roster_config or get_roster_config()
    conflicts = []

    # Group players by position
    pos_groups = {}
    for p in roster:
        pos = p.get("position", "")
        if pos not in pos_groups:
            pos_groups[pos] = []
        pos_groups[pos].append(p)

    # Check each position for bye overlaps
    for pos, players in pos_groups.items():
        if pos in ("K", "DEF"):
            continue  # Streamable, don't worry about bye

        # Get bye weeks for each player
        player_byes = []
        for p in players:
            team = p.get("team", "")
            p_byes = bye_weeks.get(team, [])
            player_byes.append((p, p_byes))

        # Count starters per bye week
        bye_counts = {}
        for p, p_byes in player_byes:
            for wk in p_byes:
                if wk not in bye_counts:
                    bye_counts[wk] = []
                bye_counts[wk].append(p)

        # Check for conflicts: multiple starters on same bye
        for wk, wk_players in bye_counts.items():
            if len(wk_players) >= 2:
                # Check if bench has coverage
                bench_at_pos = [p for p in pos_groups.get(pos, [])
                                if p not in wk_players]
                has_coverage = len(bench_at_pos) > 0
                conflicts.append({
                    "week": wk,
                    "position": pos,
                    "players": [{"name": p.get("player_name", ""), "team": p.get("team", "")} for p in wk_players],
                    "has_coverage": has_coverage,
                    "severity": "warning" if has_coverage else "critical",
                })

    return sorted(conflicts, key=lambda c: (c["severity"] == "warning", c["week"]))


def compute_bye_penalty(
    player: dict,
    current_roster: list[dict],
    bye_weeks: dict[str, list[int]],
    roster_config: Optional[dict] = None,
) -> float:
    """Compute VBD penalty for drafting a player with bye week conflicts.

    Returns a penalty value (0 = no conflict, higher = worse conflict).
    Critical conflicts (no bench coverage) get a 15% VBD penalty.
    Warning conflicts (has coverage) get a 5% penalty.
    """
    if not current_roster or not bye_weeks:
        return 0.0

    pos = player.get("position", "")
    team = player.get("team", "")
    player_bye = bye_weeks.get(team, [])

    if not player_bye or pos in ("K", "DEF"):
        return 0.0

    # Check each bye week against current roster
    penalty = 0.0
    for wk in player_bye:
        # Count same-position starters on same bye
        same_pos_same_bye = [
            p for p in current_roster
            if p.get("position") == pos
            and wk in bye_weeks.get(p.get("team", ""), [])
        ]
        if same_pos_same_bye:
            # Already have a starter on this bye week
            config = roster_config or get_roster_config()
            slots = config.get("roster_slots", {})
            pos_slots = slots.get(pos.lower(), 1)

            # Check bench coverage
            bench_at_pos = [
                p for p in current_roster
                if p.get("position") == pos
                and wk not in bye_weeks.get(p.get("team", ""), [])
            ]
            if len(bench_at_pos) < len(same_pos_same_bye):
                penalty += 0.15  # Critical: no bench coverage
            else:
                penalty += 0.05  # Warning: has coverage but still suboptimal

    return min(penalty, 0.30)  # Cap at 30% penalty


def compute_replacement_levels(
    projections: pd.DataFrame,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> dict[str, float]:
    """Compute effective replacement points after correct flexible allocation."""
    config = roster_config or get_roster_config()
    allocation = compute_league_slot_allocation(projections, num_teams, config)
    replacement = {
        pos.lower(): value
        for pos, value in allocation["effective_replacement"].items()
    }
    if "DEF" in allocation["effective_replacement"]:
        replacement["defense"] = allocation["effective_replacement"]["DEF"]
    for slot, value in allocation["flex_replacement"].items():
        replacement[slot.lower()] = value
    return replacement


def compute_vbd(
    projections: pd.DataFrame,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> pd.DataFrame:
    """Add VBD (value above replacement) to projections.

    VBD = projected_points - replacement_points(position)

    Higher VBD = more projected points than the final allocated starter at the
    same position after flexible slots have been filled.
    """
    df = projections.copy()

    replacement = compute_replacement_levels(df, num_teams, roster_config)

    def get_replacement(row):
        pos = _position_label(row["position"]).lower()
        # DEF in data → "defense" in config; DST in data → "defense" in config
        pos_to_config = {"def": "defense", "dst": "defense"}
        config_key = pos_to_config.get(pos, pos)
        return replacement.get(pos, replacement.get(config_key, replacement.get(row["position"], 0.0)))

    df["replacement_pts"] = df.apply(get_replacement, axis=1)
    df["vbd"] = df["projected_points"] - df["replacement_pts"]
    # Keep signed VBD so the board can distinguish marginal and genuinely
    # below-replacement players. Consumers that need the legacy floor can use
    # vbd_positive explicitly instead of silently collapsing the whole tail.
    df["vbd_positive"] = df["vbd"].clip(lower=0)

    return df


def compute_positional_scarcity(
    projections: pd.DataFrame,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> pd.DataFrame:
    """Compute positional scarcity metrics.

    Scarcity = how much value drops from elite to replacement at each position.
    High scarcity positions should be drafted earlier.
    """
    if roster_config is None:
        roster_config = get_roster_config()

    allocation = compute_league_slot_allocation(projections, num_teams, roster_config)
    positions = sorted(allocation["effective_replacement"])
    results = []

    normalized_positions = projections["position"].map(_position_label)
    for pos in positions:
        pos_players = projections[normalized_positions == pos]
        pos_players = pos_players.sort_values("projected_points", ascending=False)

        if len(pos_players) < 2:
            continue

        n_starters = int(allocation["selected_counts"].get(pos, 0))
        top_pts = pos_players.iloc[0]["projected_points"]
        repl_pts = float(allocation["effective_replacement"].get(pos, 0.0))

        # Drop-off from top to replacement
        dropoff = top_pts - repl_pts

        base_slots_per_team = allocation["base_slot_counts"].get(pos, 0) / max(num_teams, 1)
        dropoff_per_slot = dropoff / max(base_slots_per_team, 1)

        selected_points = pos_players.iloc[:n_starters]["projected_points"]
        starter_advantage = float((selected_points - repl_pts).clip(lower=0).mean()) if n_starters else 0.0

        # Measure the cliff at the actual starter/replacement boundary, not the
        # average of an entire top tier versus another arbitrary full tier.
        window = min(max(1, num_teams // 4), n_starters, max(len(pos_players) - n_starters, 0))
        if window > 0:
            last_starters = pos_players.iloc[n_starters - window:n_starters]["projected_points"].mean()
            next_players = pos_players.iloc[n_starters:n_starters + window]["projected_points"].mean()
            replacement_cliff = max(0.0, float(last_starters - next_players))
        else:
            replacement_cliff = 0.0

        flex_starters = sum(
            group.get(pos, 0) for group in allocation["flex_allocations"].values()
        )
        scarcity_score = starter_advantage + replacement_cliff

        results.append({
            "position": pos,
            "top_pts": round(top_pts, 1),
            "replacement_pts": round(repl_pts, 1),
            "dropoff": round(dropoff, 1),
            "dropoff_per_slot": round(dropoff_per_slot, 1),
            "tier_gap": round(replacement_cliff, 1),
            "replacement_cliff": round(replacement_cliff, 1),
            "starter_advantage": round(starter_advantage, 1),
            "scarcity_score": round(scarcity_score, 1),
            "n_players": len(pos_players),
            "starters_needed": n_starters,
            "flex_starters": flex_starters,
            "scarcity_rank": 0,  # filled below
        })

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("scarcity_score", ascending=False)
        df["scarcity_rank"] = range(1, len(df) + 1)

    return df


def conditional_probability_gone(
    adp: np.ndarray | pd.Series | float,
    current_pick: int,
    next_pick: int,
    scale: Optional[float] = None,
) -> np.ndarray:
    """Estimate next-turn draft risk conditional on being available now."""
    values = np.asarray(adp, dtype=float)
    turn_gap = max(1, int(next_pick) - int(current_pick))
    spread = float(scale or max(5.0, min(14.0, turn_gap / 3.0)))
    current_cdf = 1.0 / (1.0 + np.exp(-np.clip((current_pick - values) / spread, -30, 30)))
    next_cdf = 1.0 / (1.0 + np.exp(-np.clip((next_pick - values) / spread, -30, 30)))
    survived = np.maximum(1.0 - current_cdf, 1e-8)
    return np.clip((next_cdf - current_cdf) / survived, 0.0, 1.0)


def expected_best_available_value(
    values: np.ndarray | pd.Series,
    availability: np.ndarray | pd.Series,
    exclude_index: Optional[int] = None,
) -> float:
    """Expected best next-turn value under independent availability odds."""
    vals = np.asarray(values, dtype=float)
    probs = np.asarray(availability, dtype=float)
    if exclude_index is not None and 0 <= exclude_index < len(vals):
        keep = np.ones(len(vals), dtype=bool)
        keep[exclude_index] = False
        vals, probs = vals[keep], probs[keep]
    keep = np.isfinite(vals) & np.isfinite(probs) & (vals > 0) & (probs > 0)
    vals, probs = vals[keep], np.clip(probs[keep], 0.0, 1.0)
    if not len(vals):
        return 0.0
    order = np.argsort(-vals)
    expected = 0.0
    none_better = 1.0
    for idx in order:
        expected += none_better * probs[idx] * vals[idx]
        none_better *= 1.0 - probs[idx]
        if none_better < 1e-8:
            break
    return float(expected)


def compute_next_pick_values(
    projections: pd.DataFrame,
    current_pick: int,
    next_pick: int,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
    adp_column: str = "adp",
) -> pd.DataFrame:
    """Add conditional availability and value-over-next-available (VONA)."""
    valued = compute_vbd(projections, num_teams, roster_config)
    if adp_column in valued:
        adp = pd.to_numeric(valued[adp_column], errors="coerce").fillna(200.0)
    else:
        adp = pd.Series(200.0, index=valued.index)
    p_gone = conditional_probability_gone(adp, current_pick, next_pick)
    valued["p_gone_next"] = p_gone
    valued["p_available_next"] = 1.0 - p_gone
    valued["expected_next_vbd"] = 0.0

    normalized_positions = valued["position"].map(_position_label)
    for pos in normalized_positions.unique():
        group_indices = np.flatnonzero((normalized_positions == pos).to_numpy())
        group_values = valued.iloc[group_indices]["vbd"].to_numpy(dtype=float)
        group_probs = valued.iloc[group_indices]["p_available_next"].to_numpy(dtype=float)
        for local_idx, frame_idx in enumerate(group_indices):
            valued.iat[
                frame_idx, valued.columns.get_loc("expected_next_vbd")
            ] = expected_best_available_value(group_values, group_probs, local_idx)

    valued["vona"] = valued["vbd"] - valued["expected_next_vbd"]
    return valued


def generate_draft_plan(
    projections: pd.DataFrame,
    total_picks: int = 16,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> pd.DataFrame:
    """Generate a round-by-round draft strategy based on VBD and scarcity.

    Returns a plan showing which positions to target in each round,
    based on where the biggest VBD gaps exist.
    """
    if roster_config is None:
        roster_config = get_roster_config()

    slots = roster_config["roster_slots"]

    # Add VBD
    vbd_df = compute_vbd(projections, num_teams, roster_config)
    scarcity = compute_positional_scarcity(projections, num_teams, roster_config)

    # Sort by VBD (this is the "true" draft board)
    vbd_df = vbd_df.sort_values("vbd", ascending=False).reset_index(drop=True)
    vbd_df["overall_rank"] = range(1, len(vbd_df) + 1)

    # Build round-by-round plan
    picks_per_round = num_teams
    plan = []

    for pick_num in range(1, total_picks + 1):
        round_num = (pick_num - 1) // picks_per_round + 1
        pick_in_round = ((pick_num - 1) % picks_per_round) + 1

        # Expected players available at this pick
        if pick_num <= len(vbd_df):
            expected_player = vbd_df.iloc[pick_num - 1]
            target_pos = expected_player["position"]
            target_name = expected_player.get("player_name", expected_player.get("player_id", ""))
            target_vbd = expected_player["vbd"]
            target_pts = expected_player["projected_points"]
        else:
            target_pos = "—"
            target_name = "—"
            target_vbd = 0
            target_pts = 0

        # Strategy note based on round
        if round_num <= 2:
            strategy = "ELITE TIER: Best available RB/WR"
        elif round_num <= 4:
            strategy = "CORE BUILDERS: RB/WR depth or elite TE"
        elif round_num <= 7:
            strategy = "MID-ROUND VALUE: Fill remaining RB/WR, consider QB"
        elif round_num <= 10:
            strategy = "UPSIDE PICKS: QB if needed, breakout candidates"
        elif round_num <= 13:
            strategy = "DEPTH: Bench RB/WR with upside, TE if needed"
        else:
            strategy = "CLOSEOUT: K, DEF, handcuff RBs"

        plan.append({
            "pick": pick_num,
            "round": round_num,
            "pick_in_round": pick_in_round,
            "target_position": target_pos,
            "target_player": target_name,
            "projected_pts": round(target_pts, 1),
            "vbd": round(target_vbd, 1),
            "strategy": strategy,
        })

    return pd.DataFrame(plan)


def get_pick_recommendation(
    projections: pd.DataFrame,
    current_pick: int,
    my_roster_positions: list[str],
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> dict:
    """Get a specific pick recommendation with reasoning.

    Considers:
    - VBD ranking
    - Positional needs still unfilled
    - Must-fill starter slots (don't wait too long on a position)
    """
    if roster_config is None:
        roster_config = get_roster_config()

    slots = roster_config["roster_slots"]
    flex_eligible = roster_config.get("flex_eligible", ["rb", "wr", "te"])

    # Add VBD
    vbd_df = compute_vbd(projections, num_teams, roster_config)

    # Count what we have
    pos_counts = {}
    for p in my_roster_positions:
        p_lower = p.lower()
        pos_counts[p_lower] = pos_counts.get(p_lower, 0) + 1

    # Identify unfilled starter slots
    needs = {}
    for pos, count in slots.items():
        if pos in ("flex", "bench"):
            continue
        have = pos_counts.get(pos, 0)
        if have < count:
            needs[pos] = count - have

    # Must-draft positions: if we're past round 8 and still need a starter
    # at a position, prioritize filling it
    round_num = (current_pick - 1) // num_teams + 1
    must_draft = []
    if round_num >= 6:
        for pos, need in needs.items():
            if pos in ("qb", "te") and need > 0:
                must_draft.append(pos.upper())

    # Score each available player
    vbd_df = vbd_df.sort_values("vbd", ascending=False).reset_index(drop=True)

    recommendations = []
    for _, row in vbd_df.head(30).iterrows():
        pos = row["position"].upper()
        pos_lower = pos.lower()

        # Bonus for filling a need
        need_bonus = 0
        if pos_lower in needs:
            need_bonus = 30 * needs[pos_lower]  # significant bonus

        # Bonus for must-draft positions
        if pos in must_draft:
            need_bonus += 50

        # Penalty if already stacked at position
        have = pos_counts.get(pos_lower, 0)
        slot_count = slots.get(pos_lower, 0)
        if have >= slot_count + 1 and pos_lower not in flex_eligible:
            need_bonus -= 20  # already have starters + bench

        score = row["vbd"] + need_bonus
        recommendations.append({
            "player_id": row.get("player_id", ""),
            "player_name": row.get("player_name", ""),
            "position": pos,
            "team": row.get("team", ""),
            "projected_points": round(row["projected_points"], 1),
            "vbd": round(row["vbd"], 1),
            "need_bonus": round(need_bonus, 1),
            "score": round(score, 1),
            "reason": _build_reason(row, pos_lower, needs, must_draft, have, slot_count),
        })

    recommendations.sort(key=lambda x: x["score"], reverse=True)

    return {
        "pick": current_pick,
        "round": round_num,
        "needs": needs,
        "must_draft": must_draft,
        "top_recommendations": recommendations[:5],
    }


def _build_reason(row, pos_lower, needs, must_draft, have, slot_count):
    """Build a human-readable reason for a recommendation."""
    reasons = []
    name = row.get("player_name", "Player")

    if pos_lower in needs:
        reasons.append(f"fills {needs[pos_lower]} open {pos_lower.upper()} slot(s)")
    if pos_lower.upper() in must_draft:
        reasons.append("MUST DRAFT — starter slot still open late")
    if row["vbd"] > 50:
        reasons.append(f"elite VBD ({row['vbd']:.0f})")
    if have >= slot_count + 1:
        reasons.append("already stacked at position")

    if not reasons:
        reasons.append(f"best VBD available ({row['vbd']:.0f})")

    return f"{name}: " + "; ".join(reasons)


def detect_sleepers_and_busts(
    projections: pd.DataFrame,
    adp_data: Optional[pd.DataFrame] = None,
    pos_rank_threshold: int = 6,
) -> list[dict]:
    """Detect sleepers (model >> ADP) and busts (ADP >> model).

    Uses positional rank gap rather than overall rank delta — a WR ranked
    WR15 by the model but going at WR35 in ADP is actionable; an overall
    pick-count delta is polluted by position density and ADP=0 noise.

    Only players with a real ADP (> 0, within draftable range) are
    considered.  ADP=0 means the market hasn't ranked them at all, so
    there's no market signal to compare against.

    Args:
        pos_rank_threshold: Minimum positional rank gap to flag (default 6).
    """
    if adp_data is None or adp_data.empty or projections.empty:
        return []

    # Merge projections with ADP if not already present
    if "adp" not in projections.columns:
        proj = projections.copy()
        if "player_name" in adp_data.columns and "player_name" in proj.columns:
            adp_sub = (adp_data[["player_name", "adp"]]
                       .dropna(subset=["adp"])
                       .drop_duplicates("player_name"))
            proj = proj.merge(adp_sub, on="player_name", how="left", suffixes=("", "_adp"))
        if "adp" not in proj.columns:
            return []
        df = proj
    else:
        df = projections.copy()

    # --- Hard filters ---
    # Must have a real ADP: market has ranked this player and they're draftable.
    # The export uses 200 as the no-market-data sentinel, so only values below
    # 200 represent a real current ADP observation.
    df = df[df["adp"].notna() & (df["adp"] > 0) & (df["adp"] < 200)].copy()

    # Skill positions only (K/DEF use historical averages, not the ML model)
    if "position" in df.columns:
        df = df[df["position"].isin(["QB", "RB", "WR", "TE"])]

    # Fantasy-relevant only: at least ~3 good games worth of points
    if "projected_points" in df.columns:
        df = df[df["projected_points"] >= 40]

    if df.empty:
        return []

    # --- Positional ranks ---
    # Model positional rank: 1 = best projected at position
    df["model_pos_rank"] = (df.groupby("position")["projected_points"]
                             .rank(ascending=False, method="min"))

    # ADP positional rank: derive from overall ADP within position
    # (sort by ADP within position, assign 1..N)
    df = df.sort_values("adp")
    df["adp_pos_rank"] = (df.groupby("position")["adp"]
                           .rank(ascending=True, method="min"))

    # Gap: positive = sleeper (model ranks them higher than ADP does)
    df["pos_gap"] = df["adp_pos_rank"] - df["model_pos_rank"]

    results = []
    for _, row in df.iterrows():
        gap = row["pos_gap"]
        if abs(gap) < pos_rank_threshold:
            continue

        label = "SLEEPER" if gap > 0 else "BUST"

        # Skip bust flags for confirmed 2nd-year breakout players —
        # the model over-regresses these and ADP is likely right.
        if (label == "BUST"
                and row.get("is_2nd_year", 0) == 1
                and row.get("pts_lag1", 0) > 100):
            continue

        pos = row.get("position", "")
        model_pr = int(row["model_pos_rank"])
        adp_pr = int(row["adp_pos_rank"])
        reason = (
            f"Model {pos}{model_pr} · ADP {pos}{adp_pr} "
            f"({'undervalued' if label == 'SLEEPER' else 'overvalued'} by {int(abs(gap))} spots)"
        )

        results.append({
            "player_name": row.get("player_name", ""),
            "position": pos,
            "team": row.get("team", ""),
            "projected_points": round(row.get("projected_points", 0), 1),
            "model_rank": int(row.get("model_rank", model_pr)),
            "model_pos_rank": model_pr,
            "adp": round(row["adp"], 1),
            "adp_pos_rank": adp_pr,
            "adp_gap": round(gap, 1),
            "label": label,
            "reason": reason,
        })

    return sorted(results, key=lambda x: abs(x["adp_gap"]), reverse=True)


def detect_position_runs(
    recent_picks: list[dict],
    window: int = 6,
    run_threshold: int = 3,
) -> list[dict]:
    """Detect position runs in recent draft picks.

    A run occurs when 3+ players at the same position are drafted
    in quick succession. This signals scarcity urgency.

    Args:
        recent_picks: List of recently drafted players with 'position' key.
        window: Number of recent picks to analyze.
        run_threshold: Minimum consecutive same-position picks to flag.
    """
    if len(recent_picks) < run_threshold:
        return []

    recent = recent_picks[-window:]
    runs = []

    # Count positions in recent window
    pos_counts = {}
    for p in recent:
        pos = p.get("position", "")
        if pos:
            pos_counts[pos] = pos_counts.get(pos, 0) + 1

    for pos, count in pos_counts.items():
        if count >= run_threshold:
            players = [p.get("player_name", "") for p in recent if p.get("position") == pos]
            runs.append({
                "position": pos,
                "count": count,
                "window": window,
                "players": players,
                "message": f"🔥 {pos} RUN: {count} {pos}s drafted in last {window} picks — grab one before the tier drops",
            })

    return sorted(runs, key=lambda x: x["count"], reverse=True)


def find_handcuffs(
    roster: list[dict],
    available: list[dict],
    top_n: int = 3,
) -> list[dict]:
    """Find handcuff RBs — backups for your fragile starters.

    Handcuffs are backup RBs on the same team as your starting RB.
    If your starter gets hurt, the handcuff becomes the starter.

    Args:
        roster: Your current roster players.
        available: Available players in the pool.
        top_n: Number of handcuff suggestions to return.
    """
    if not roster or not available:
        return []

    # Find RBs on my roster
    my_rbs = [p for p in roster if p.get("position") == "RB"]
    if not my_rbs:
        return []

    handcuffs = []
    for rb in my_rbs:
        team = rb.get("team", "")
        if not team:
            continue

        # Find backup RBs on same team
        backups = [
            p for p in available
            if p.get("position") == "RB"
            and p.get("team") == team
            and p.get("player_id") != rb.get("player_id")
        ]

        for backup in backups:
            handcuffs.append({
                "starter_name": rb.get("player_name", ""),
                "starter_team": team,
                "handcuff_name": backup.get("player_name", ""),
                "handcuff_proj": round(backup.get("projected_points", 0), 1),
                "handcuff_adp": backup.get("adp", None),
                "reason": f"Handcuff for {rb.get('player_name', '')} — if he goes down, {backup.get('player_name', '')} takes over",
            })

    # Sort by starter's projected points (protect your best RBs first)
    rb_proj_map = {rb.get("player_name", ""): rb.get("projected_points", 0) for rb in my_rbs}
    handcuffs.sort(key=lambda h: rb_proj_map.get(h["starter_name"], 0), reverse=True)

    return handcuffs[:top_n]
