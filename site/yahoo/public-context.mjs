// Public nflverse data is joined to Yahoo's session data only in this browser.
// Neither source is sent to a third-party AI service here.
const teams = { JAX: 'JAC', LAR: 'LA', STL: 'LA', WSH: 'WAS', OAK: 'LV', SD: 'LAC' };
export const normalTeam = value => teams[String(value || '').toUpperCase()] || String(value || '').toUpperCase();
export function normalName(value) {
  return String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, '').replace(/[^a-z0-9]/g, '');
}
export function indexPublicPlayers(snapshot) {
  const map = new Map();
  for (const player of snapshot?.players || []) {
    const key = `${normalName(player.name)}|${normalTeam(player.team)}|${player.position}`;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(player);
  }
  return map;
}
export function matchPublicPlayer(player, index) {
  const key = `${normalName(player.name)}|${normalTeam(player.team)}|${String(player.position || '').toUpperCase()}`;
  const matches = index.get(key) || [];
  return matches.length === 1 ? matches[0] : null;
}
export function formatKickoff(game) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(game?.gameDate || '');
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
  if (!Number.isFinite(date.valueOf()) || date.toISOString().slice(0, 10) !== game.gameDate) return null;
  const day = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
  const time = /^(\d{1,2}):(\d{2})$/.exec(game.gameTime || '');
  if (!time || Number(time[1]) > 23 || Number(time[2]) > 59) return `${day} · time TBD`;
  const hour = Number(time[1]);
  return `${day} · ${hour % 12 || 12}:${time[2]} ${hour < 12 ? 'AM' : 'PM'} ET`;
}
export function publicSummary(player, snapshot) {
  if (!player) return 'No verified nflverse match';
  if (player.position === 'K') return player.nextGame
    ? `Week ${snapshot.nextWeek} vs ${player.nextGame.opponent} · ${formatKickoff(player.nextGame) || 'kickoff unavailable'} · league points above are calculated from public kicking stats`
    : 'League points above are calculated from public kicking stats; no upcoming game is listed.';
  const games = player.games || [];
  const last = games.at(-1);
  const usage = last ? (player.position === 'QB'
    ? [Number.isFinite(last.passingYards) ? `${last.passingYards} pass yds` : null, Number.isFinite(last.carries) ? `${last.carries} carries` : null]
    : player.position === 'RB'
      ? [Number.isFinite(last.carries) ? `${last.carries} carries` : null, Number.isFinite(last.targets) ? `${last.targets} targets` : null]
      : [Number.isFinite(last.targets) ? `${last.targets} targets` : null, Number.isFinite(last.receptions) ? `${last.receptions} catches` : null])
    .filter(Boolean).join(' · ') : '';
  const game = player.nextGame ? `Week ${snapshot.nextWeek} vs ${player.nextGame.opponent} · ${formatKickoff(player.nextGame) || 'kickoff unavailable'}` : `No Week ${snapshot.nextWeek} game listed`;
  const recent = last ? ` · Week ${last.week} actual ${Number.isFinite(last.points) ? last.points.toFixed(1) : '—'} public standard pts${usage ? ` · ${usage}` : ''}` : '';
  return `${games.length} recorded game${games.length === 1 ? '' : 's'} · ${Number.isFinite(player.averagePoints) ? player.averagePoints.toFixed(1) : '—'} public standard pts/game${recent} · ${game}`;
}
export function publicInjuryNote(player, snapshot) {
  const report = player?.recentInjury;
  if (!report) return null;
  if (snapshot && report.week !== snapshot.latestCompletedWeek) return null;
  if (!report.reportStatus && /^full participation/i.test(report.practiceStatus || '')) return null;
  return `Week ${report.week} historical injury report: ${report.reportStatus || report.practiceStatus || report.injury || 'listed'}. Not a current playing-status determination.`;
}
