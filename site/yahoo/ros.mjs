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
