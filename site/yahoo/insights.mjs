// Deterministic session-only summaries, not a learned model or future-points forecast.
const BENCH = new Set(['BN', 'BE', 'IR', 'IR+', 'IL', 'NA']);
const OUT = new Set(['O', 'OUT', 'IR', 'PUP', 'SUSP', 'SUSPENDED', 'NA', 'NFI']);
const slotName = s => String(s || '').toUpperCase().replace('D/ST', 'DEF');
export const isBench = p => BENCH.has(slotName(p.slot));
export const isStarter = p => Boolean(p.slot) && !isBench(p);
export function positions(p) {
  return String(p.position || '').toUpperCase().replace('D/ST', 'DEF').split(/[,/ ]+/).filter(Boolean);
}
export function canFill(p, slot) {
  const s = slotName(slot);
  if (BENCH.has(s)) return false;
  if ((p.eligible || []).map(slotName).includes(s)) return true;
  const group = { FLEX: ['RB', 'WR', 'TE'], 'W/R/T': ['RB', 'WR', 'TE'], 'W/R': ['RB', 'WR'],
    'W/T': ['WR', 'TE'], 'WR/TE': ['WR', 'TE'], 'Q/W/R/T': ['QB', 'RB', 'WR', 'TE'],
    SUPERFLEX: ['QB', 'RB', 'WR', 'TE'] }[s] || [s];
  return positions(p).some(x => group.includes(x));
}
export function availability(p, week) {
  const status = String(p.status || '').toUpperCase();
  if (OUT.has(status)) return { blocked: true, caution: true, label: p.status };
  if (Number.isInteger(week) && p.byeWeek === week) return { blocked: true, caution: true, label: 'Bye this week' };
  return { blocked: false, caution: Boolean(status), label: p.status || 'No status flag reported' };
}
export function positionSummary(team, position, season, pointsFor = p => p.pointsSeason === season ? p.seasonPoints : null) {
  if (!team.rosterAvailable) return { starters: [], bench: [], total: null, missing: null };
  const group = team.roster.filter(p => position === 'ALL' || positions(p).includes(position));
  const starters = group.filter(isStarter), bench = group.filter(isBench);
  const scored = starters.map(pointsFor);
  const missing = scored.filter(p => !Number.isFinite(p)).length;
  return { starters, bench, missing,
    total: starters.length && missing === 0 ? scored.reduce((sum, p) => sum + p, 0) : null };
}
export function rosterNeeds(team, league) {
  if (!team?.rosterAvailable) return [];
  const needs = [];
  for (const setting of league.positions) {
    const slot = slotName(setting.position), required = Number(setting.count);
    if (BENCH.has(slot) || !Number.isInteger(required) || required < 1) continue;
    const starters = team.roster.filter(p => isStarter(p) && slotName(p.slot) === slot);
    const empty = Math.max(0, required - starters.length);
    if (empty) needs.push({ slot, type: 'empty', priority: 3, text: `${empty} unfilled ${slot} starting slot${empty > 1 ? 's' : ''}` });
    for (const p of starters.filter(p => availability(p, league.currentWeek).caution))
      needs.push({ slot, type: 'flag', priority: availability(p, league.currentWeek).blocked ? 2 : 1,
        text: `${p.name}: ${availability(p, league.currentWeek).label}` });
  }
  return needs.sort((a, b) => b.priority - a.priority);
}
export function pickupCandidates(players, team, league, observedScore = () => null) {
  const needs = rosterNeeds(team, league), owned = new Set((team?.roster || []).map(p => p.playerKey));
  return players.filter(p => !owned.has(p.playerKey) && ['freeagents', 'waivers'].includes(p.ownership)).map(p => {
    const state = availability(p, league.currentWeek);
    const fits = league.positions.filter(s => Number(s.count) > 0 && canFill(p, s.position)).map(s => s.position);
    const need = needs.find(n => canFill(p, n.slot));
    const cover = need ? (team?.roster || []).filter(x => isBench(x) && canFill(x, need.slot) && !availability(x, league.currentWeek).caution).length : null;
    let reason = !team?.rosterAvailable ? 'Your lineup is unavailable. Roster fit has not been assessed.'
      : need ? `${need.text}. Eligible at ${need.slot}. ${cover} unflagged eligible bench option${cover === 1 ? '' : 's'} already on your team.`
        : fits.length ? `Eligible at ${fits.join(', ')}. A depth candidate, not a confirmed upgrade.` : 'No matching starting slot in this league.';
    if (state.blocked) reason = `${state.label}. Not an immediate replacement. ${reason}`;
    else if (state.caution) reason = `${state.label}: check availability before considering a claim. ${reason}`;
    const supplied = observedScore(p), recent = Number.isFinite(supplied) ? { average: supplied } : supplied;
    return { player: p, reason, priority: !fits.length || state.blocked ? -1 : Math.max(0, (need?.priority || 0) - (state.caution ? 1 : 0)),
      points: Number.isFinite(recent?.points) ? recent.points : null,
      recentScore: Number.isFinite(recent?.average) ? recent.average : null };
  }).sort((a, b) => b.priority - a.priority || (b.recentScore ?? -Infinity) - (a.recentScore ?? -Infinity)
    || (b.points ?? -Infinity) - (a.points ?? -Infinity) || a.player.name.localeCompare(b.player.name));
}
export function mergeAvailablePages(pages) {
  return [...new Map(pages.flatMap(page => page.players || []).filter(p => p.playerKey).map(p => [p.playerKey, p])).values()];
}
