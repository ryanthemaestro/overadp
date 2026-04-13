"""Draft strategy: value-based drafting, positional scarcity, and pick recommendations.

Core insight: Don't draft by raw projected points. Draft by VALUE above replacement.

Value-Based Drafting (VBD):
  VBD = projected_points - replacement_points(position)
  replacement_points = projected points of the Nth player at that position,
  where N = num_teams * slots_for_position

Positional Scarcity:
  Scarcity = dropoff from elite to replacement at each position.
  Positions with high scarcity should be drafted earlier.

Bye Week Conflict Avoidance:
  Don't draft two starters with the same bye week unless you have bench coverage.
  Penalize picks that create unresolvable bye week conflicts.

Draft Rules of Thumb (backed by VBD math):
  - RBs early: steepest drop-off, most scarce
  - WRs in rounds 2-5: deep but elite ones separate
  - QBs late: flat position, streamable
  - TE: either get an elite one (rounds 3-4) or wait
  - K/DEF: last two picks always
"""
import pandas as pd
import numpy as np
from typing import Optional
from src.utils.config import get_roster_config


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
    """Compute replacement-level fantasy points for each position.

    Replacement level = projected points of the last starter that would be
    rostered across all teams. E.g., if 12 teams each need 2 RBs, the
    replacement RB is the #24 RB.
    """
    if roster_config is None:
        roster_config = get_roster_config()

    slots = roster_config["roster_slots"]
    flex_eligible = roster_config.get("flex_eligible", ["rb", "wr", "te"])

    replacement = {}

    for pos, count in slots.items():
        if pos in ("flex", "bench"):
            continue

        # Match position names: "defense" in config → "DEF" or "DST" in data
        pos_variants = {pos.upper()}
        if pos.upper() == "DEFENSE":
            pos_variants = {"DEF", "DST", "DEFENSE"}
        pos_players = projections[projections["position"].str.upper().isin(pos_variants)]
        pos_players = pos_players.sort_values("projected_points", ascending=False)

        # Number of starters needed across all teams
        n_starters = num_teams * count

        if len(pos_players) >= n_starters:
            replacement[pos] = pos_players.iloc[n_starters - 1]["projected_points"]
        elif len(pos_players) > 0:
            replacement[pos] = pos_players.iloc[-1]["projected_points"]
        else:
            replacement[pos] = 0.0

    # Flex replacement = best available among flex-eligible replacements
    flex_replacements = []
    for pos in flex_eligible:
        if pos in replacement:
            flex_replacements.append(replacement[pos])
    if flex_replacements:
        replacement["flex"] = min(flex_replacements)

    return replacement


def compute_vbd(
    projections: pd.DataFrame,
    num_teams: int = 12,
    roster_config: Optional[dict] = None,
) -> pd.DataFrame:
    """Add VBD (value above replacement) to projections.

    VBD = projected_points - replacement_points(position)

    Higher VBD = more valuable relative to what's available at that position.
    This is the correct way to rank players across positions.
    """
    df = projections.copy()

    replacement = compute_replacement_levels(df, num_teams, roster_config)

    def get_replacement(row):
        pos = row["position"].lower()
        # DEF in data → "defense" in config; DST in data → "defense" in config
        pos_to_config = {"def": "defense", "dst": "defense"}
        config_key = pos_to_config.get(pos, pos)
        return replacement.get(pos, replacement.get(config_key, replacement.get(row["position"], 0.0)))

    df["replacement_pts"] = df.apply(get_replacement, axis=1)
    df["vbd"] = df["projected_points"] - df["replacement_pts"]
    df["vbd"] = df["vbd"].clip(lower=0)  # Below replacement = 0 VBD

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

    slots = roster_config["roster_slots"]
    results = []

    for pos, count in slots.items():
        if pos in ("flex", "bench"):
            continue

        # Match position names: "defense" in config → "DEF" or "DST" in data
        pos_variants = {pos.upper()}
        if pos.upper() == "DEFENSE":
            pos_variants = {"DEF", "DST", "DEFENSE"}
        pos_players = projections[projections["position"].str.upper().isin(pos_variants)]
        pos_players = pos_players.sort_values("projected_points", ascending=False)

        if len(pos_players) < 2:
            continue

        n_starters = num_teams * count
        top_pts = pos_players.iloc[0]["projected_points"]

        if len(pos_players) >= n_starters:
            repl_pts = pos_players.iloc[n_starters - 1]["projected_points"]
        else:
            repl_pts = pos_players.iloc[-1]["projected_points"]

        # Drop-off from top to replacement
        dropoff = top_pts - repl_pts

        # Drop-off per starter slot (normalized)
        dropoff_per_slot = dropoff / count if count > 0 else dropoff

        # Tier gaps: how much value drops between tiers
        tier_size = max(n_starters, 1)
        if len(pos_players) >= tier_size + 4:
            tier1_avg = pos_players.iloc[:tier_size]["projected_points"].mean()
            tier2_avg = pos_players.iloc[tier_size:tier_size * 2]["projected_points"].mean()
            tier_gap = tier1_avg - tier2_avg
        else:
            tier_gap = 0

        results.append({
            "position": pos.upper(),
            "top_pts": round(top_pts, 1),
            "replacement_pts": round(repl_pts, 1),
            "dropoff": round(dropoff, 1),
            "dropoff_per_slot": round(dropoff_per_slot, 1),
            "tier_gap": round(tier_gap, 1),
            "n_players": len(pos_players),
            "starters_needed": n_starters,
            "scarcity_rank": 0,  # filled below
        })

    df = pd.DataFrame(results)
    if not df.empty:
        # Rank by tier_gap (how steep the cliff is between tiers)
        # This is the most actionable metric: a big tier_gap means
        # there's a clear advantage to drafting early at that position
        df = df.sort_values("tier_gap", ascending=False)
        df["scarcity_rank"] = range(1, len(df) + 1)

    return df


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
    threshold: float = 40,
) -> list[dict]:
    """Detect sleepers (model >> ADP) and busts (ADP >> model).

    A sleeper is a player the model ranks much higher than the market.
    A bust is a player the market overvalues vs our model.

    Args:
        threshold: Minimum ADP gap to flag (in pick positions).
    """
    if adp_data is None or adp_data.empty or projections.empty:
        return []

    # Merge projections with ADP
    if "adp" not in projections.columns:
        proj = projections.copy()
        if "player_name" in adp_data.columns and "player_name" in proj.columns:
            adp_sub = adp_data[["player_name", "adp"]].dropna(subset=["adp"]).drop_duplicates("player_name")
            proj = proj.merge(adp_sub, on="player_name", how="left", suffixes=("", "_adp"))
        if "adp" not in proj.columns:
            return []

    df = projections if "adp" in projections.columns else proj
    df = df[df["adp"].notna()].copy()

    # Exclude K and DEF — their projections are from historical averages, not the model,
    # so comparing them to ADP always produces false sleepers/busts
    if "position" in df.columns:
        df = df[~df["position"].isin(["K", "DEF", "DST"])]

    # Exclude fringe players with near-zero projections (no meaningful data)
    if "projected_points" in df.columns:
        df = df[df["projected_points"] > 20]

    if df.empty:
        return []

    # Model rank vs ADP rank
    df["model_rank"] = df["projected_points"].rank(ascending=False)
    df["adp_rank"] = df["adp"]

    # Gap: positive = sleeper (model ranks higher), negative = bust
    df["adp_gap"] = df["adp_rank"] - df["model_rank"]

    results = []
    for _, row in df.iterrows():
        gap = row["adp_gap"]
        if abs(gap) >= threshold:
            label = "SLEEPER" if gap > 0 else "BUST"
            results.append({
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "team": row.get("team", ""),
                "projected_points": round(row.get("projected_points", 0), 1),
                "model_rank": int(row["model_rank"]),
                "adp": round(row["adp"], 1),
                "adp_gap": round(gap, 1),
                "label": label,
                "reason": f"Model rank #{int(row['model_rank'])} vs ADP #{round(row['adp'], 0)} — {label}",
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
