// Reconstruct observed points from public nflverse game stats using the Yahoo
// league's session-only scoring settings. Never infer missing stats as zero.
const OFFENSE = new Map([
  ['Pass Yds', g => g.passingYards], ['Pass TD', g => g.passingTds],
  ['Int', g => g.interceptions], ['Rush Yds', g => g.rushingYards],
  ['Rush TD', g => g.rushingTds], ['Rec', g => g.receptions],
  ['Rec Yds', g => g.receivingYards], ['Rec TD', g => g.receivingTds],
  ['Ret TD', g => g.returnTds],
  ['2-PT', g => finiteSum(g.passingTwo, g.rushingTwo, g.receivingTwo)],
  ['Fum Lost', g => g.fumblesLost], ['Off Fumb TD', g => g.offensiveFumbleTds],
]);
const KICKER = new Map([
  ['FG 0-19', g => g.fg0], ['FG 20-29', g => g.fg20],
  ['FG 30-39', g => g.fg30], ['FG 40-49', g => g.fg40],
  ['FG 50+', g => finiteSum(g.fg50, g.fg60)], ['PAT Made', g => g.patMade],
]);
const DEFENSE = new Map([
  ['Sack', g => g.sacks], ['Int', g => g.interceptions],
  ['Fum Rec', g => g.fumbleRecoveries], ['TD', g => g.touchdowns],
  ['Safe', g => g.safeties],
  ['Blk Kick', g => finiteSum(g.puntBlocks, g.patBlocks, g.fgBlocks)],
  ['Ret TD', g => g.returnTds], ['XPR', g => g.twoPointReturns],
  // Yahoo's points-allowed tiers: 1 for the tier the final score falls in, else 0.
  ...[['0', 0, 0], ['1-6', 1, 6], ['7-13', 7, 13], ['14-20', 14, 20], ['21-27', 21, 27], ['28-34', 28, 34], ['35+', 35, Infinity]]
    .map(([label, lo, hi]) => [`Pts Allow ${label}`, g => Number.isFinite(g.pointsAllowed) ? Number(g.pointsAllowed >= lo && g.pointsAllowed <= hi) : null]),
]);
const round = n => Math.round((n + Number.EPSILON) * 100) / 100;
const finiteSum = (...numbers) => numbers.every(Number.isFinite) ? numbers.reduce((a, b) => a + b, 0) : null;
export function scoreGame(game, position, scoring) {
  if (!game || !Array.isArray(scoring) || !scoring.length) return { points: null, partial: true, reason: 'Scoring or game stats unavailable' };
  const pos = String(position || '').toUpperCase().replace('D/ST', 'DEF');
  const rules = pos === 'K' ? KICKER : pos === 'DEF' ? DEFENSE : OFFENSE;
  // Yahoo returns stat modifiers in offense, kicking, defense groups. This
  // keeps the two distinct "Int" and "Ret TD" rules from cross-scoring.
  const firstKicker = scoring.findIndex(r => /^FG |^PAT /.test(r.name));
  const firstDefense = scoring.findIndex(r => r.name === 'Sack');
  const typed = scoring.every(r => r.positionType);
  const relevant = typed ? scoring.filter(r => r.positionType === (pos === 'DEF' ? 'DT' : pos === 'K' ? 'K' : 'O'))
    : pos === 'K' ? scoring.slice(firstKicker < 0 ? scoring.length : firstKicker, firstDefense < 0 ? undefined : firstDefense)
      : pos === 'DEF' ? scoring.slice(firstDefense < 0 ? scoring.length : firstDefense)
        : scoring.slice(0, firstKicker < 0 ? firstDefense < 0 ? undefined : firstDefense : firstKicker);
  let points = 0, applied = 0; const missing = [];
  for (const rule of relevant) {
    const name = String(rule.name || '').trim();
    // Names shared across position groups are interpreted only in the player's group.
    if (!rules.has(name)) {
      if (Number(rule.value) !== 0) missing.push(/^Pts Allow /.test(name) ? 'points allowed' : name);
      continue;
    }
    const modifier = Number(rule.value), stat = rules.get(name)(game);
    if (!Number.isFinite(modifier) || !Number.isFinite(stat)) { missing.push(/^Pts Allow /.test(name) ? 'points allowed' : name); continue; }
    points += modifier * stat; applied++;
  }
  if (!applied) return { points: null, partial: true, reason: 'No supported scoring rules' };
  const absent = [...new Set(missing)];
  return { points: absent.length ? null : round(points), partial: Boolean(absent.length),
    knownPoints: round(points), missing: absent, reason: absent.length ? `Not scored: ${absent.join(', ')}` : null };
}
export function scorePlayer(player, league, teamStats) {
  if (!player || !league) return null;
  const defense = player.position === 'DEF';
  const games = defense ? teamStats?.[player.team]?.defenseGames : player.games;
  if (!Array.isArray(games) || !games.length) return null;
  const weekly = games.map(g => ({ week: g.week, ...scoreGame(g, player.position, league.scoring) }));
  const complete = weekly.every(g => Number.isFinite(g.points));
  return { weekly, games: games.length, points: complete ? round(weekly.reduce((n, g) => n + g.points, 0)) : null,
    average: complete ? round(weekly.reduce((n, g) => n + g.points, 0) / games.length) : null,
    partial: !complete, reason: [...new Set(weekly.flatMap(g => g.missing || []))].join(', ') };
}
