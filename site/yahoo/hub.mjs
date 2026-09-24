// Team Hub view-model: turns the session's Yahoo data plus public estimates into
// plain-English moves. Pure functions only; nothing here fetches or stores data.
import { availability, isStarter, isBench, canFill, positions } from './insights.mjs';
import { normalTeam } from './public-context.mjs';

const round = n => Math.round(n * 10) / 10;
const RESERVE = new Set(['IR', 'IR+', 'IL', 'NA']);
export const RANK_POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K'];

export function yahooLinks(teamKey) {
  const [, league, team] = /^\d+\.l\.(\d+)\.t\.(\d+)$/.exec(teamKey || '') || [];
  const base = 'https://football.fantasysports.yahoo.com/f1/';
  const id = playerKey => /^\d+\.p\.(\d+)$/.exec(playerKey || '')?.[1] || null;
  return {
    league: league ? base + league : 'https://football.fantasysports.yahoo.com/',
    team: league && team ? `${base}${league}/${team}` : 'https://football.fantasysports.yahoo.com/',
    add: playerKey => league && id(playerKey) ? `${base}${league}/addplayer?apid=${id(playerKey)}` : null,
    player: playerKey => id(playerKey) ? `https://sports.yahoo.com/nfl/players/${id(playerKey)}/` : null,
  };
}

// Short status tag for a player row. Yahoo's own status is the only current source.
export function statusTag(player, week) {
  const state = availability(player, week);
  if (!state.caution) return null;
  const raw = String(player.status || '').toUpperCase();
  if (state.label === 'Bye this week') return { text: 'BYE', tone: 'bad', label: 'on bye this week' };
  if (state.blocked) return { text: raw === 'O' ? 'OUT' : raw || 'OUT', tone: 'bad', label: `listed ${raw === 'O' ? 'Out' : player.status}` };
  if (raw === 'D') return { text: 'DOUBT', tone: 'bad', label: 'listed Doubtful' };
  if (raw === 'Q') return { text: 'QUES', tone: 'warn', label: 'listed Questionable' };
  return { text: raw.slice(0, 6), tone: 'warn', label: `listed ${player.status}` };
}

// "Thu 8:15 PM" and "vs NO" / "@ NO" from an nflverse schedule row (gameId is AWAY_HOME).
export function gameLine(team, game) {
  if (!game) return null;
  const home = String(game.gameId || '').split('_')[3];
  const at = home && normalTeam(team) !== home ? '@' : 'vs';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(game.gameDate || ''), t = /^(\d{1,2}):(\d{2})$/.exec(game.gameTime || '');
  const day = m ? new Intl.DateTimeFormat('en-US', { weekday: 'short', timeZone: 'UTC' })
    .format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 12))) : null;
  const time = t ? `${Number(t[1]) % 12 || 12}:${t[2]} ${Number(t[1]) < 12 ? 'AM' : 'PM'}` : 'time TBD';
  return `${at} ${game.opponent}${day ? ` · ${day} ${time}` : ''}`;
}

// Sum of a team's current starters. Unknown estimates are counted, never treated as zero.
export function starterTotal(team, estimate) {
  if (!team?.rosterAvailable) return { points: null, missing: null, starters: 0 };
  const starters = team.roster.filter(isStarter);
  const values = starters.map(p => estimate(p)?.points);
  const known = values.filter(Number.isFinite);
  return { points: known.length ? round(known.reduce((a, b) => a + b, 0)) : null, missing: values.length - known.length, starters: starters.length };
}

function bestCover(team, slot, estimate, week, starting) {
  return team.roster.filter(p => !starting.has(p.playerKey) && isBench(p) && !RESERVE.has(String(p.slot).toUpperCase()) &&
    canFill(p, slot) && !availability(p, week).caution && estimate(p)?.playable)
    .sort((a, b) => (estimate(b)?.points ?? -Infinity) - (estimate(a)?.points ?? -Infinity))[0] || null;
}

// Ranked, plain-English actions for this week. `lineup` is optimizeLineup()'s result.
export function buildMoves({ team, league, lineup, estimate, pickups = [], links = yahooLinks(team?.teamKey) }) {
  if (!team?.rosterAvailable || !lineup || lineup.unavailable) return [];
  const week = league.currentWeek, moves = [];
  const moved = new Set();
  for (const move of lineup.moves || []) {
    const incoming = move.player, outgoing = move.replaces;
    const inEst = move.estimate, outEst = outgoing ? estimate(outgoing) : null;
    const tag = outgoing ? statusTag(outgoing, week) : null;
    const gain = Number.isFinite(inEst?.points) && Number.isFinite(outEst?.points) && outEst.playable ? round(inEst.points - outEst.points) : null;
    const why = !outgoing ? `Your ${move.slot} slot is empty. ${incoming.name} is your best eligible bench option.`
      : tag ? `${outgoing.name} is ${tag.label} in Yahoo. ${incoming.name}${statusTag(incoming, week) ? '' : ' has no injury tag'}${Number.isFinite(inEst?.points) ? `${statusTag(incoming, week) ? '' : ' and'} projects ${inEst.points.toFixed(1)} points` : ''}.`
        : `${incoming.name} projects ${gain != null ? `${gain.toFixed(1)} more points` : 'higher'} than ${outgoing.name} this week.`;
    moves.push({ kind: 'lineup', priority: !outgoing || tag?.tone === 'bad' ? 4 : 3,
      headline: outgoing ? `Start ${incoming.name} over ${outgoing.name}` : `Start ${incoming.name} at ${move.slot}`,
      why, impact: gain != null && gain > 0 ? `+${gain.toFixed(1)} pts` : tag ? 'Avoid a zero' : 'Fill slot',
      action: 'Set lineup', href: links.team, basis: inEst?.basis || null });
    moved.add(incoming.playerKey); if (outgoing) moved.add(outgoing.playerKey);
  }
  const startingKeys = new Set((lineup.assignments || []).map(a => a.player?.playerKey).filter(Boolean));
  // Current starters the optimizer left alone: an Out/Doubtful one it could not replace
  // still needs a card, and a Questionable one still starting needs a watch.
  for (const p of team.roster.filter(p => isStarter(p) && !moved.has(p.playerKey))) {
    const tag = statusTag(p, week);
    if (!tag || (tag.tone === 'warn' && !startingKeys.has(p.playerKey))) continue;
    const cover = bestCover(team, p.slot, estimate, week, startingKeys), slot = String(p.slot).replace('W/R/T', 'FLEX');
    if (tag.tone === 'bad') {
      moves.push({ kind: 'lineup', priority: 4, headline: `Replace ${p.name}`,
        why: `${p.name} is ${tag.label} in Yahoo. ${cover ? `${cover.name} can fill your ${slot} slot.` : `Nobody healthy on your bench can fill ${slot}; see Waivers.`}`,
        impact: 'Avoid a zero', action: 'Set lineup', href: links.team, basis: null });
      continue;
    }
    moves.push({ kind: 'watch', priority: 2, headline: `Check ${p.name} before kickoff`,
      why: `${p.name} is ${tag.label} in Yahoo. ${cover ? `If ruled out, your best backup is ${cover.name}.` : 'You have no healthy backup on your bench; see Waivers.'}`,
      impact: 'Status', action: 'Open lineup', href: links.team, basis: null });
  }
  // The best add by rest-of-season value, if it's worth at least ~1 point a week.
  const best = pickups.filter(c => c.ros?.gain >= Math.max(6, c.ros.of)).sort((a, b) => b.ros.gain - a.ros.gain)[0];
  if (best) {
    const p = best.player, pool = p.ownership === 'waivers' ? `On waivers${p.waiverDate ? ` until ${p.waiverDate}` : ''}` : 'Free agent';
    moves.push({ kind: 'pickup', priority: 1, headline: `Add ${p.name}${best.ros.drop ? `, drop ${best.ros.drop.name}` : ''}`,
      why: `${pool}. ${describeAdd(best.ros)}`,
      impact: `+${best.ros.gain.toFixed(1)} pts ROS`, action: p.ownership === 'waivers' ? 'Claim in Yahoo' : 'Add in Yahoo',
      href: links.add(p.playerKey) || links.league, basis: best.rosBasis || null });
  }
  return moves.sort((a, b) => b.priority - a.priority).slice(0, 4);
}

// Points the listed moves are worth this week (lineup swaps plus the top add).
export function movesGain(moves) {
  return round(moves.reduce((sum, m) => sum + (Number(/^\+(\d+(?:\.\d+)?) pts$/.exec(m.impact)?.[1]) || 0), 0));
}

// Rank every team at each position by its best healthy players there (as many as
// the league starts). Teams without enough estimated players are left unranked,
// never counted as zero, and labels need at least five comparable teams.
export function positionRanks(command, estimate) {
  const mineKey = command.team.teamKey, out = [], byTeam = new Map(command.teams.map(t => [t.teamKey, {}]));
  for (const pos of RANK_POSITIONS) {
    const need = (command.league.positions || []).filter(p => String(p.position).toUpperCase() === pos).reduce((n, p) => n + Number(p.count || 0), 0);
    const rows = command.teams.map(t => {
      if (!t.rosterAvailable || !need) return { key: t.teamKey, total: null };
      const values = t.roster.filter(p => positions(p).includes(pos)).map(p => estimate(p))
        .filter(e => e?.playable && Number.isFinite(e.points)).map(e => e.points).sort((a, b) => b - a);
      return { key: t.teamKey, total: values.length >= need ? round(values.slice(0, need).reduce((a, b) => a + b, 0)) : null };
    });
    const comparable = rows.filter(r => Number.isFinite(r.total)).sort((a, b) => b.total - a.total);
    comparable.forEach((r, i) => { byTeam.get(r.key)[pos] = { rank: i + 1, of: comparable.length }; });
    const rank = comparable.findIndex(r => r.key === mineKey) + 1;
    out.push({ pos, rank: rank || null, of: comparable.length, points: rows.find(r => r.key === mineKey)?.total ?? null });
  }
  return { ranks: out, byTeam };
}

export function tradeIdea({ ranks, byTeam }, mineKey) {
  const rated = ranks.filter(r => r.rank && r.of >= 6);
  const strong = rated.filter(r => r.rank <= 3).sort((a, b) => a.rank - b.rank)[0];
  const weak = rated.filter(r => r.rank > r.of - 3).sort((a, b) => b.rank - a.rank)[0];
  if (!strong || !weak) return null;
  const partners = [...byTeam.entries()].filter(([key, r]) => key !== mineKey &&
    r[weak.pos]?.rank <= 3 && r[strong.pos]?.rank > r[strong.pos]?.of - 3).length;
  return { strong: strong.pos, weak: weak.pos, partners };
}

// ---- Rest-of-season roster value -------------------------------------------
// Value of an add = starting-lineup points it adds to *this* roster over the
// remaining weeks through the fantasy playoffs, after the best possible drop.
export const PLAYOFF_WEIGHT = 1.5;
const LONG_OUT = new Set(['IR', 'IR-R', 'IR-NR', 'PUP', 'PUP-R', 'PUP-P', 'NFI', 'NFI-R', 'SUSP', 'NA']);
const SLOT_OUT = new Set(['IR', 'IR+', 'IL', 'NA']);
// Yahoo gives no return date, so long-term statuses are assumed out for four weeks.
const LONG_OUT_WEEKS = 4;

export function fantasyWeeks(league) {
  const start = Number(league.currentWeek), end = Math.min(Number(league.endWeek) || 17, 17);
  const playoff = Number(league.playoffStartWeek) || 15;
  if (!Number.isInteger(start)) return [];
  return Array.from({ length: Math.max(0, end - start + 1) }, (_, i) => {
    const week = start + i;
    return { week, playoff: week >= playoff, weight: week >= playoff ? PLAYOFF_WEIGHT : 1 };
  });
}
export function availabilityShare(player, week, currentWeek) {
  if (player.byeWeek === week) return 0;
  const status = String(player.status || '').toUpperCase();
  if (LONG_OUT.has(status) || SLOT_OUT.has(String(player.slot || '').toUpperCase()))
    return week < currentWeek + LONG_OUT_WEEKS ? 0 : 0.8;
  if (week !== currentWeek) return 1;
  return status === 'O' ? 0 : status === 'D' ? 0.25 : status === 'Q' ? 0.75 : 1;
}
export function starterSlots(league) {
  return (league.positions || []).flatMap(p => {
    const slot = String(p.position).toUpperCase(), n = Number(p.count);
    return ['BN', 'BE', ...SLOT_OUT].includes(slot) || !Number.isInteger(n) ? [] : Array(n).fill(slot);
  });
}
export function rosterCapacity(league) {
  return (league.positions || []).filter(p => !SLOT_OUT.has(String(p.position).toUpperCase()))
    .reduce((n, p) => n + (Number(p.count) || 0), 0);
}
// Greedy lineup: best players take their own position's slot first, then a flex.
export function bestLineup(players, slots, value) {
  const open = slots.map(slot => ({ slot, flex: !['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].includes(slot), player: null }));
  const ranked = players.map(p => ({ p, v: value(p) })).filter(x => x.v > 0).sort((a, b) => b.v - a.v);
  let points = 0;
  for (const { p, v } of ranked) {
    const spot = open.find(s => !s.player && !s.flex && canFill(p, s.slot)) || open.find(s => !s.player && s.flex && canFill(p, s.slot));
    if (spot) { spot.player = p; points += v; }
  }
  return { points, starters: new Set(open.filter(s => s.player).map(s => s.player.playerKey)) };
}
export function seasonValue(roster, league, weeks, value) {
  const slots = starterSlots(league);
  let total = 0; const byWeek = new Map();
  for (const w of weeks) {
    const lineup = bestLineup(roster, slots, p => value(p, w.week));
    total += w.weight * lineup.points; byWeek.set(w.week, lineup.starters);
  }
  return { total, byWeek };
}
export function addValue({ roster, candidate, league, weeks, value }) {
  const base = seasonValue(roster, league, weeks, value);
  // Never suggest a drop that leaves a required slot (a lone K or DEF, say) unfillable,
  // even when public stats can't score that player.
  const need = {};
  for (const slot of starterSlots(league)) if (['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].includes(slot)) need[slot] = (need[slot] || 0) + 1;
  const fillsAll = players => Object.entries(need).every(([slot, n]) => players.filter(p => canFill(p, slot)).length >= n);
  const droppable = roster.filter(p => !SLOT_OUT.has(String(p.slot || '').toUpperCase()))
    .filter(p => fillsAll(roster.filter(x => x !== p).concat(candidate)));
  const active = roster.filter(p => !SLOT_OUT.has(String(p.slot || '').toUpperCase()));
  const options = active.length < rosterCapacity(league) ? [null] : droppable;
  if (!options.length) return null;
  // Among equally good drops, let go of the player with the least projected value.
  const raw = p => p ? weeks.reduce((sum, w) => sum + value(p, w.week), 0) : 0;
  let best = null;
  for (const drop of options) {
    const next = roster.filter(p => p !== drop).concat(candidate);
    const result = seasonValue(next, league, weeks, value);
    const better = !best || result.total > best.result.total + 1e-9 ||
      (Math.abs(result.total - best.result.total) <= 1e-9 && raw(drop) < raw(best.drop));
    if (better) best = { drop, result };
  }
  const startWeeks = weeks.filter(w => best.result.byWeek.get(w.week)?.has(candidate.playerKey));
  const displaced = new Map();
  for (const w of startWeeks) for (const key of base.byWeek.get(w.week) || [])
    if (!best.result.byWeek.get(w.week).has(key) && key !== best.drop?.playerKey) displaced.set(key, (displaced.get(key) || 0) + 1);
  const topKey = [...displaced.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  // Byes covered: the add starts in a week when a usual starter at its position is off.
  const usual = p => weeks.filter(w => base.byWeek.get(w.week)?.has(p.playerKey)).length >= weeks.length / 2;
  const byeWeeks = startWeeks.filter(w => roster.some(p => p.byeWeek === w.week && String(p.position) === String(candidate.position) && usual(p)))
    .map(w => w.week);
  const dropStarts = best.drop ? weeks.filter(w => base.byWeek.get(w.week)?.has(best.drop.playerKey)).length : 0;
  return { gain: Math.round((best.result.total - base.total) * 10) / 10, drop: best.drop, dropStarts,
    starts: startWeeks.length, playoffStarts: startWeeks.filter(w => w.playoff).length, of: weeks.length,
    displaced: roster.find(p => p.playerKey === topKey) || null, byeWeeks };
}
export function describeAdd(r) {
  if (!r) return 'No rest-of-season estimate for this player yet.';
  if (r.gain <= 0) return r.starts ? `Would start ${r.starts} of ${r.of} weeks, but costs more than it adds after the drop.` : `Wouldn't crack your lineup in any of the remaining ${r.of} weeks.`;
  const parts = [`Starts for you in ${r.starts} of ${r.of} weeks${r.playoffStarts ? `, including ${r.playoffStarts} playoff week${r.playoffStarts === 1 ? '' : 's'}` : ''}`];
  if (r.displaced) parts.push(`mostly over ${r.displaced.name}`);
  let text = parts.join(', ') + '.';
  if (r.byeWeeks.length) text += ` Covers bye week${r.byeWeeks.length === 1 ? '' : 's'} ${r.byeWeeks.join(', ')}.`;
  return text;
}
