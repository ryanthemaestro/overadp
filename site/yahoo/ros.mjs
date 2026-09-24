// Rest-of-season points per game, calibrated on 2019-2025 held-out seasons
// (research/ros_calibration). Blends the v6 preseason projection with this
// season's results and usage, then converts to the league's own scoring.
import { scoreGame } from './league-scoring.mjs';

// nflverse's half-PPR definition, the target the model was calibrated on.
export const HALF_PPR = [
  ['Pass Yds', 0.04], ['Pass TD', 4], ['Int', -2], ['Rush Yds', 0.1], ['Rush TD', 6], ['Rec', 0.5],
  ['Rec Yds', 0.1], ['Rec TD', 6], ['Ret TD', 6], ['2-PT', 2], ['Fum Lost', -2], ['Off Fumb TD', 6],
].map(([name, value]) => ({ name, value: String(value) }));
const MODELED = new Set(['QB', 'RB', 'WR', 'TE']);
const round = n => Math.round(n * 100) / 100;

function bucketFor(model, games) {
  const b = model.buckets.find(([lo, hi]) => games >= lo && games <= hi);
  return b ? `${b[0]}-${b[1]}` : null;
}
function perGame(games, pick) {
  const values = games.map(pick).filter(Number.isFinite);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}
// How this league's scoring compares with half-PPR for this player's own games.
export function scoringRatio(position, games, league) {
  let lg = 0, half = 0;
  for (const g of games) {
    const a = scoreGame(g, position, league.scoring)?.points, b = scoreGame(g, position, HALF_PPR)?.points;
    if (Number.isFinite(a) && Number.isFinite(b)) { lg += a; half += b; }
  }
  return half >= 10 ? Math.min(2, Math.max(0.5, lg / half)) : null;
}

/**
 * @param current  nflverse 2026 player (games so far) or null
 * @param prior    nflverse 2025 player or null
 * @param v6       players.json row (season half-PPR projection) or null
 */
export function rosPerGame({ position, current, prior, v6, league, model }) {
  const pos = String(position || '').toUpperCase();
  if (!MODELED.has(pos) || !model?.positions?.[pos]) return null;
  const games = current?.games || [];
  const half = g => scoreGame(g, pos, HALF_PPR)?.points;
  const priorPg = prior?.games?.length >= 4 ? perGame(prior.games, half) : null;
  const pre = Number.isFinite(v6?.projected_points) ? v6.projected_points / 17 : priorPg;
  const observed = perGame(games, half);
  if (!Number.isFinite(pre) && !Number.isFinite(observed)) return null;
  const n = games.length, key = bucketFor(model, n), coef = key && model.positions[pos][key];
  let pg, basis;
  if (!n || !coef) { pg = pre; basis = Number.isFinite(v6?.projected_points) ? 'v6 preseason projection' : 'last season average'; }
  else {
    const x = [1, Number.isFinite(pre) ? pre : observed, observed ?? 0, perGame(games, g => g.targets) ?? 0,
      perGame(games, g => g.carries) ?? 0, perGame(games, g => g.attempts) ?? 0];
    pg = Math.max(0, x.reduce((sum, v, i) => sum + v * coef[i], 0));
    basis = `${Number.isFinite(v6?.projected_points) ? 'v6 projection' : 'last season'} + ${n} game${n === 1 ? '' : 's'} this season`;
  }
  const ratio = scoringRatio(pos, [...games, ...(prior?.games || [])], league) ?? 1;
  return { points: round(pg * ratio), halfPpr: round(pg), basis, games: n };
}

// ---- Kickers (research/ros_calibration/kickers.py) ----
// Calibrated on Yahoo's default kicker scoring, then converted to the league's.
export const DEFAULT_K = [['FG 0-19', 3], ['FG 20-29', 3], ['FG 30-39', 3], ['FG 40-49', 4], ['FG 50+', 5], ['PAT Made', 1]]
  .map(([name, value]) => ({ name, value: String(value) }));
function kickerInputs(current, prior, model) {
  const pts = g => scoreGame(g, 'K', DEFAULT_K)?.points;
  const games = current?.games || [], priorPg = prior?.games?.length >= 4 ? perGame(prior.games, pts) : null;
  return { n: games.length, base: Number.isFinite(priorPg) ? priorPg : model.kicker.fallback_base, obs: perGame(games, pts) ?? 0, priorPg };
}
function applyKicker(part, features, values, n) {
  const key = bucketFor(part, n), coef = key && part.by_bucket[key];
  return coef ? Math.max(0, features.reduce((sum, f, i) => sum + coef[i] * values[f], 0)) : null;
}
/**
 * kind 'season': rest-of-season points per game (waivers, drops).
 * kind 'week': next game, using the betting line's implied team total and roof (start/sit).
 */
export function kickerPerGame({ kind, current, prior, team, context, game, league, model }) {
  if (!model?.kicker) return null;
  const { n, base, obs, priorPg } = kickerInputs(current, prior, model);
  const ctx = context?.[team] || {};
  const values = { intercept: 1, base, obs0: obs, indoor_share: ctx.remainingIndoorShare ?? 0,
    team_ppg: ctx.pointsPerGame ?? ctx.priorPointsPerGame, team_prior: ctx.priorPointsPerGame,
    implied: game?.impliedTotal, indoor_next: game?.indoor ? 1 : 0 };
  const part = kind === 'week' ? model.kicker.next_week : model.kicker.rest_of_season;
  if (part.features.some(f => !Number.isFinite(values[f]))) return null;
  const pg = applyKicker(part, part.features, values, n);
  if (!Number.isFinite(pg)) return null;
  let lg = 0, dflt = 0;
  for (const g of [...(current?.games || []), ...(prior?.games || [])]) {
    const a = scoreGame(g, 'K', league.scoring)?.points, b = scoreGame(g, 'K', DEFAULT_K)?.points;
    if (Number.isFinite(a) && Number.isFinite(b)) { lg += a; dflt += b; }
  }
  const ratio = dflt >= 10 ? Math.min(2, Math.max(0.5, lg / dflt)) : 1;
  const basis = kind === 'week' ? `kicker model with this week's betting line${game?.indoor ? ', indoors' : ''}` :
    `kicker model: ${Number.isFinite(priorPg) ? 'last season' : 'league-average start'}${n ? ` + ${n} game${n === 1 ? '' : 's'}` : ''}, ${Math.round(100 * (ctx.remainingIndoorShare ?? 0))}% of remaining games indoors`;
  return { points: Math.round(pg * ratio * 100) / 100, basis, games: n };
}

// ---- Team defenses (research/ros_calibration/defenses.py) ----
export const DEFAULT_DEF = [['Sack', 1], ['Int', 2], ['Fum Rec', 2], ['TD', 6], ['Safe', 2], ['Blk Kick', 2], ['Ret TD', 6],
  ['Pts Allow 0', 10], ['Pts Allow 1-6', 7], ['Pts Allow 7-13', 4], ['Pts Allow 14-20', 1], ['Pts Allow 21-27', 0], ['Pts Allow 28-34', -1], ['Pts Allow 35+', -4]]
  .map(([name, value]) => ({ name, value: String(value) }));
/**
 * kind 'season': rest-of-season points per game, from last season, this season and the
 * strength of the offenses still to come. kind 'week': the next game, from the betting
 * line's projected points for the opponent.
 */
export function defensePerGame({ kind, team, week, snapshot, league, model }) {
  if (!model?.defense || !snapshot) return null;
  const ctx = snapshot.teamContext?.[team] || {}, game = snapshot.schedule?.[team];
  const games = (snapshot.teamStats?.[team]?.defenseGames || []).filter(g => Number.isFinite(g.pointsAllowed));
  const pts = g => scoreGame(g, 'DEF', DEFAULT_DEF)?.points;
  const values = { intercept: 1, base: ctx.priorDefensePointsPerGame ?? model.defense.fallback_base, obs0: perGame(games, pts) ?? 0,
    opp_off: ctx.remainingOpponentOffense, opp_implied: game ? snapshot.schedule?.[game.opponent]?.impliedTotal : null, home: game?.home ? 1 : 0 };
  const part = kind === 'week' ? model.defense.next_week : kind === 'future' ? model.defense.future_week : model.defense.rest_of_season;
  if (kind === 'future') {
    // A later week: that week's opponent's scoring so far (no betting line exists yet).
    const g = ctx.remainingSchedule?.find(x => x.week === week);
    if (!g) return { points: 0, basis: 'bye week', games: games.length };
    values.next_opp_off = snapshot.teamContext?.[g.opponent]?.offenseStrength; values.home = g.home ? 1 : 0;
  }
  if (!part || part.features.some(f => !Number.isFinite(values[f]))) return null;
  const key = bucketFor(part, games.length), coef = key && part.by_bucket[key];
  if (!coef) return null;
  const pg = part.features.reduce((sum, f, i) => sum + coef[i] * values[f], 0);
  // Convert to the league's scoring using this season's games (unscorable rules keep the default).
  let lg = 0, dflt = 0;
  for (const g of games) {
    const a = scoreGame(g, 'DEF', league.scoring)?.points, b = pts(g);
    if (Number.isFinite(a) && Number.isFinite(b)) { lg += a; dflt += b; }
  }
  const ratio = Math.abs(dflt) >= 5 ? Math.min(2, Math.max(0.5, lg / dflt)) : 1;
  const basis = kind === 'future' ? `defense model: week ${week} opponent scoring ${values.next_opp_off.toFixed(1)} points a game`
    : kind === 'week' ? `defense model: opponent projected for ${values.opp_implied} points by the betting line`
    : `defense model: last season + ${games.length} game${games.length === 1 ? '' : 's'}, remaining opponents averaging ${values.opp_off.toFixed(1)} points`;
  return { points: Math.round(pg * ratio * 100) / 100, basis, games: games.length };
}
