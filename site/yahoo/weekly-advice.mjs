import { availability, canFill, isStarter } from './insights.mjs';
import { normalName } from './public-context.mjs';
import { scorePlayer } from './league-scoring.mjs';

const round = n => Math.round(n * 10) / 10;
const bench = new Set(['BN', 'BE', 'IR', 'IR+', 'IL', 'NA']);
const starterSlots = league => (league.positions || []).flatMap(item => {
  const count = Number(item.count), slot = String(item.position).toUpperCase();
  return bench.has(slot) || !Number.isInteger(count) || count < 1 ? [] : Array.from({ length: count }, (_, i) => ({ slot, index: i }));
});
export function priorIndex(snapshot) {
  const byId = new Map(), byName = new Map();
  for (const player of snapshot?.players || []) {
    byId.set(player.id, player);
    const key = `${normalName(player.name)}|${player.position}`;
    if (!byName.has(key)) byName.set(key, []);
    byName.get(key).push(player);
  }
  return { byId, byName };
}
export function matchPrior(publicPlayer, yahooPlayer, index) {
  if (!index) return null;
  if (publicPlayer?.id && index.byId.has(publicPlayer.id)) {
    const match = index.byId.get(publicPlayer.id);
    if (match.position === String(yahooPlayer.position).toUpperCase()) return match;
  }
  const matches = index.byName.get(`${normalName(yahooPlayer.name)}|${String(yahooPlayer.position).toUpperCase()}`) || [];
  return matches.length === 1 ? matches[0] : null;
}
// nflverse schedule stores local Eastern clock time; derive its UTC offset for
// the game date so lock checks work on both sides of daylight-saving changes.
export function kickoffUtc(game) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(game?.gameDate || '') || !/^\d{1,2}:\d{2}$/.test(game?.gameTime || '')) return null;
  const [y, m, d] = game.gameDate.split('-').map(Number), [hour, minute] = game.gameTime.split(':').map(Number);
  if (hour > 23 || minute > 59) return null;
  const probe = new Date(Date.UTC(y, m - 1, d, 17));
  if (probe.toISOString().slice(0, 10) !== game.gameDate) return null;
  const tz = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'shortOffset' })
    .formatToParts(probe).find(part => part.type === 'timeZoneName')?.value;
  const offset = /GMT([+-])(\d{1,2})(?::(\d{2}))?/.exec(tz || '');
  if (!offset) return null;
  const minutes = (offset[1] === '+' ? 1 : -1) * (Number(offset[2]) * 60 + Number(offset[3] || 0));
  return Date.UTC(y, m - 1, d, hour, minute) - minutes * 60000;
}
export function estimatePlayer(player, league, current, previous, now = Date.now()) {
  const state = availability(player, league.currentWeek);
  const game = current?.nextGame;
  const kickoff = kickoffUtc(game);
  if (state.blocked) return { points: null, playable: false, locked: kickoff != null && now >= kickoff, reason: state.label };
  if (String(player.status || '').toUpperCase() === 'D')
    return { points: null, playable: false, locked: kickoff != null && now >= kickoff, reason: 'Yahoo doubtful; excluded from the primary plan' };
  if (!game || kickoff == null) return { points: null, playable: false, locked: true, reason: 'Verified kickoff unavailable; leave current starter unchanged' };
  const currentScore = current && scorePlayer(current, league), priorScore = previous && scorePlayer(previous, league);
  const recent = Number.isFinite(currentScore?.average) ? currentScore.average : null;
  const baseline = Number.isFinite(priorScore?.average) ? priorScore.average : null;
  let points = null, basis = 'insufficient public scoring data';
  if (recent != null && baseline != null) {
    // Deliberately conservative with only one or two current-season games.
    const weight = Math.min(0.5, (currentScore.games || 0) / 4);
    points = round((1 - weight) * baseline + weight * recent);
    basis = `2025 ${priorScore.games}-game average + 2026 ${currentScore.games}-game average`;
  } else if (baseline != null) { points = round(baseline); basis = `2025 ${priorScore.games}-game average only`; }
  else if (recent != null) { points = round(recent); basis = `2026 ${currentScore.games}-game average only`; }
  return { points, basis, playable: true, locked: now >= kickoff, kickoff, caution: state.caution,
    reason: state.caution ? `Yahoo ${state.label}; conditional on playing` : null,
    sparse: baseline == null || recent == null || (currentScore?.games || 0) < 3 };
}
export function optimizeLineup(team, league, estimate, now = Date.now()) {
  if (!team?.rosterAvailable) return { assignments: [], complete: false, moves: [], unavailable: true };
  const slots = starterSlots(league), players = team.roster || [];
  const estimates = players.map(player => estimate(player, now));
  const locked = new Map(), used = new Set();
  for (let si = 0; si < slots.length; si++) {
    const current = players.findIndex((p, pi) => !used.has(pi) && isStarter(p) && String(p.slot).toUpperCase() === slots[si].slot);
    if (current >= 0 && estimates[current]?.locked) { locked.set(si, current); used.add(current); }
  }
  // Exact small-roster assignment, including empty-slot penalties. This is
  // browser-local and never transmits a league roster to a third-party model.
  let states = new Map([[0, { utility: 0, selected: [] }]]);
  for (let si = 0; si < slots.length; si++) {
    const next = new Map(), fixed = locked.get(si);
    for (const [mask, state] of states) {
      const choices = fixed != null ? [fixed] : [-1, ...players.map((_, i) => i)];
      for (const pi of choices) {
        if (pi >= 0 && (mask & (1 << pi))) continue;
        if (pi >= 0 && fixed == null && (used.has(pi) || !canFill(players[pi], slots[si].slot)
            || !estimates[pi]?.playable || estimates[pi]?.locked || bench.has(String(players[pi].slot).toUpperCase()) && ['IR', 'IR+', 'IL', 'NA'].includes(String(players[pi].slot).toUpperCase()))) continue;
        // A one- or two-game estimate is too noisy to justify a marginal
        // healthy-starter swap. Filling an empty slot remains worthwhile.
        const benchSwitchPenalty = pi >= 0 && ['BN', 'BE'].includes(String(players[pi].slot).toUpperCase()) ? 2 : 0;
        const value = pi < 0 ? -100 : Number.isFinite(estimates[pi]?.points)
          ? estimates[pi].points - benchSwitchPenalty : -20 - benchSwitchPenalty;
        const nextMask = pi < 0 ? mask : mask | (1 << pi), utility = state.utility + value;
        if (!next.has(nextMask) || utility > next.get(nextMask).utility)
          next.set(nextMask, { utility, selected: [...state.selected, pi] });
      }
    }
    states = next;
  }
  const best = [...states.values()].sort((a, b) => b.utility - a.utility)[0] || { selected: [] };
  const assignments = slots.map((slot, i) => ({ slot: slot.slot, player: players[best.selected[i]] || null,
    estimate: estimates[best.selected[i]] || null, locked: locked.has(i) }));
  const occupied = new Set();
  const current = slots.map(slot => {
    const index = players.findIndex((p, i) => !occupied.has(i) && isStarter(p) && String(p.slot).toUpperCase() === slot.slot);
    if (index >= 0) occupied.add(index);
    return players[index] || null;
  });
  const selected = new Set(assignments.map(item => item.player?.playerKey).filter(Boolean));
  const moves = assignments.filter(item => item.player && !current.some(p => p?.playerKey === item.player.playerKey))
    .map(item => ({ ...item, replaces: current.find(p => p && !selected.has(p.playerKey) && canFill(p, item.slot)) || null }));
  return { assignments, moves, estimates, complete: assignments.every(item => item.player && Number.isFinite(item.estimate?.points)),
    knownPoints: round(assignments.reduce((sum, item) => sum + (item.estimate?.points || 0), 0)),
    unknown: assignments.filter(item => !Number.isFinite(item.estimate?.points)).length };
}
export function candidateImpact(candidate, lineup, estimate) {
  if (!estimate?.playable || !Number.isFinite(estimate.points) || !lineup?.assignments?.length) return null;
  const options = lineup.assignments.filter(item => !item.locked && canFill(candidate, item.slot));
  if (!options.length) return null;
  const opportunities = options.map(item => ({ slot: item.slot, replaced: item.player?.name || null,
    gain: item.player && Number.isFinite(item.estimate?.points) ? round(estimate.points - item.estimate.points)
      : item.player ? null : estimate.points }));
  opportunities.sort((a, b) => Number(b.replaced === null) - Number(a.replaced === null) ||
    (b.gain ?? -Infinity) - (a.gain ?? -Infinity));
  return opportunities[0];
}
