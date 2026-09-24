import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

// This build consumes only public nflverse CSV snapshots. Yahoo data never enters it.
const [playersPath, teamsPath, injuriesPath, gamesPath, priorTeamsPath] = process.argv.slice(2);
if (![playersPath, teamsPath, injuriesPath, gamesPath].every(Boolean)) {
  throw Error('Usage: node build-public-context.mjs PLAYER_CSV TEAM_CSV INJURY_CSV GAMES_CSV [PRIOR_SEASON_TEAM_CSV]');
}
function csv(path) {
  const source = readFileSync(path, 'utf8');
  const rows = []; let row = [], value = '', quoted = false;
  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    if (quoted && ch === '"' && source[i + 1] === '"') { value += '"'; i++; }
    else if (ch === '"') quoted = !quoted;
    else if (!quoted && ch === ',') { row.push(value); value = ''; }
    else if (!quoted && ch === '\n') { row.push(value.replace(/\r$/, '')); rows.push(row); row = []; value = ''; }
    else value += ch;
  }
  if (value || row.length) { row.push(value); rows.push(row); }
  const header = rows.shift();
  return { hash: createHash('sha256').update(source).digest('hex'), rows: rows.filter(r => r.length === header.length).map(r => Object.fromEntries(header.map((h, i) => [h, r[i]]))) };
}
const playerInput = csv(playersPath), teamInput = csv(teamsPath), injuryInput = csv(injuriesPath), gameInput = csv(gamesPath);
const regularPlayers = playerInput.rows.filter(r => r.season === '2026' && r.season_type === 'REG' && ['QB', 'RB', 'WR', 'TE', 'K'].includes(r.position) && r.player_id && r.player_display_name);
const completedWeeks = [...new Set(regularPlayers.map(r => Number(r.week)))].sort((a, b) => a - b);
const latestCompletedWeek = completedWeeks.at(-1);
const playerMap = new Map();
const num = v => v === '' || v == null ? null : Number(v);
const playerFields = {
  attempts: 'attempts', passingYards: 'passing_yards', passingTds: 'passing_tds', interceptions: 'passing_interceptions',
  rushingYards: 'rushing_yards', rushingTds: 'rushing_tds', receptions: 'receptions',
  receivingYards: 'receiving_yards', receivingTds: 'receiving_tds',
  passingTwo: 'passing_2pt_conversions', rushingTwo: 'rushing_2pt_conversions',
  receivingTwo: 'receiving_2pt_conversions', fumblesLost: 'fumbles_lost_total',
  returnTds: 'special_teams_tds', offensiveFumbleTds: 'fumble_recovery_tds',
  fg0: 'fg_made_0_19', fg20: 'fg_made_20_29', fg30: 'fg_made_30_39',
  fg40: 'fg_made_40_49', fg50: 'fg_made_50_59', fg60: 'fg_made_60_', patMade: 'pat_made',
};
const pickStats = (row, fields) => Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, num(row[field])]));
for (const r of regularPlayers) {
  const id = r.player_id;
  if (!playerMap.has(id)) playerMap.set(id, { id, name: r.player_display_name, team: r.team, position: r.position, games: [] });
  const p = playerMap.get(id);
  p.team = r.team;
  p.games.push({ week: Number(r.week), opponent: r.opponent_team, points: num(r.fantasy_points),
    targets: num(r.targets), carries: num(r.carries), ...pickStats(r, playerFields) });
}
const injuryMap = new Map();
for (const r of injuryInput.rows.filter(x => x.season === '2026' && x.season_type === 'REG' && x.gsis_id)) {
  const week = Number(r.week);
  if (!injuryMap.has(r.gsis_id) || week > injuryMap.get(r.gsis_id).week) {
    injuryMap.set(r.gsis_id, { week, reportStatus: r.report_status || null, practiceStatus: r.practice_status || null, injury: r.report_primary_injury || r.practice_primary_injury || null });
  }
}
const now = new Date();
const futureGames = gameInput.rows.filter(r => r.season === '2026' && r.game_type === 'REG' && !r.home_score && !r.away_score && new Date(`${r.gameday}T23:59:59Z`) >= now).sort((a, b) => a.gameday.localeCompare(b.gameday) || a.gametime.localeCompare(b.gametime));
const nextWeek = Math.min(...futureGames.map(r => Number(r.week)));
const nextGames = futureGames.filter(r => Number(r.week) === nextWeek);
// Kicker context (research/ros_calibration/kickers.py): the betting line's implied team
// total and whether the game is indoors (unknown retractable roofs count as outdoors).
const indoor = r => ['dome', 'closed'].includes(r.roof);
const implied = (r, home) => {
  const total = num(r.total_line), spread = num(r.spread_line);
  return Number.isFinite(total) && Number.isFinite(spread) ? Number(((total + (home ? spread : -spread)) / 2).toFixed(2)) : null;
};
const schedule = Object.fromEntries(nextGames.flatMap(r => [
  [r.home_team, { opponent: r.away_team, gameDate: r.gameday, gameTime: r.gametime, gameId: r.game_id, impliedTotal: implied(r, true), indoor: indoor(r), home: true }],
  [r.away_team, { opponent: r.home_team, gameDate: r.gameday, gameTime: r.gametime, gameId: r.game_id, impliedTotal: implied(r, false), indoor: indoor(r), home: false }],
]));
const regular = gameInput.rows.filter(r => r.game_type === 'REG');
const pointsPerGame = season => {
  const scored = {};
  for (const r of regular.filter(r => r.season === season && r.home_score !== '' && r.away_score !== ''))
    for (const [team, pts] of [[r.home_team, r.home_score], [r.away_team, r.away_score]]) (scored[team] ||= []).push(Number(pts));
  return Object.fromEntries(Object.entries(scored).map(([team, v]) => [team, Number((v.reduce((a, b) => a + b, 0) / v.length).toFixed(2))]));
};
const currentPpg = pointsPerGame('2026'), priorPpg = pointsPerGame('2025');
const remaining = regular.filter(r => r.season === '2026' && Number(r.week) >= nextWeek && Number(r.week) <= 17);
// Defense context (research/ros_calibration/defenses.py): opponents' scoring so far,
// shrunk toward last season with four games of weight, averaged over the remaining schedule;
// and last season's defense points per game under Yahoo's default scoring.
const scoredGames = season => regular.filter(r => r.season === season && r.home_score !== '' && r.away_score !== '');
const offense = {};
for (const r of scoredGames('2026')) for (const [team, pts] of [[r.home_team, r.home_score], [r.away_team, r.away_score]]) (offense[team] ||= []).push(Number(pts));
const leaguePrior = Object.values(priorPpg).reduce((a, b) => a + b, 0) / Math.max(1, Object.keys(priorPpg).length);
const strength = team => { const v = offense[team] || [], prior = priorPpg[team] ?? leaguePrior; return (prior * 4 + v.reduce((a, b) => a + b, 0)) / (4 + v.length); };
const defenseTiers = pa => pa === 0 ? 10 : pa <= 6 ? 7 : pa <= 13 ? 4 : pa <= 20 ? 1 : pa <= 27 ? 0 : pa <= 34 ? -1 : -4;
const priorDefense = {};
if (priorTeamsPath) {
  const allowed = {};
  for (const r of scoredGames('2025')) { allowed[`${r.home_team}|${r.week}`] = Number(r.away_score); allowed[`${r.away_team}|${r.week}`] = Number(r.home_score); }
  for (const r of csv(priorTeamsPath).rows.filter(x => x.season === '2025' && x.season_type === 'REG' && Number(x.week) <= 17)) {
    const pa = allowed[`${r.team}|${r.week}`];
    if (!Number.isFinite(pa)) continue;
    const v = k => num(r[k]) || 0;
    const pts = v('def_sacks') + 2 * v('def_interceptions') + 2 * v('fumble_recovery_opp') + 6 * (v('def_tds') + v('special_teams_tds')) +
      2 * v('def_safeties') + 2 * (v('def_punt_blocks') + v('def_fg_blocks') + v('def_pat_blocks')) + defenseTiers(pa);
    (priorDefense[r.team] ||= []).push(pts);
  }
}
const teamContext = Object.fromEntries([...new Set(remaining.flatMap(r => [r.home_team, r.away_team]))].map(team => {
  const games = remaining.filter(r => r.home_team === team || r.away_team === team);
  const opponents = games.map(r => r.home_team === team ? r.away_team : r.home_team);
  const pd = priorDefense[team];
  return [team, { pointsPerGame: currentPpg[team] ?? null, priorPointsPerGame: priorPpg[team] ?? null,
    offenseStrength: Number(strength(team).toFixed(2)),
    remainingSchedule: games.map(r => ({ week: Number(r.week), opponent: r.home_team === team ? r.away_team : r.home_team, home: r.home_team === team })),
    remainingIndoorShare: games.length ? Number((games.filter(indoor).length / games.length).toFixed(3)) : null,
    remainingOpponentOffense: opponents.length ? Number((opponents.reduce((a, t) => a + strength(t), 0) / opponents.length).toFixed(2)) : null,
    priorDefensePointsPerGame: pd?.length >= 8 ? Number((pd.reduce((a, b) => a + b, 0) / pd.length).toFixed(2)) : null }];
}));
const players = [...playerMap.values()].map(p => {
  p.games.sort((a, b) => a.week - b.week);
  const scored = p.games.filter(g => Number.isFinite(g.points));
  p.averagePoints = scored.length ? Number((scored.reduce((s, g) => s + g.points, 0) / scored.length).toFixed(2)) : null;
  p.recentInjury = injuryMap.get(p.id) || null;
  p.nextGame = schedule[p.team] || null;
  return p;
});
const teamRows = teamInput.rows.filter(r => r.season === '2026' && r.season_type === 'REG');
// Final scores give each defense's points allowed (the opponent's score).
const allowedThisSeason = {};
for (const r of gameInput.rows.filter(r => r.season === '2026' && r.game_type === 'REG' && r.home_score !== '' && r.away_score !== '')) {
  allowedThisSeason[`${r.home_team}|${Number(r.week)}`] = Number(r.away_score); allowedThisSeason[`${r.away_team}|${Number(r.week)}`] = Number(r.home_score);
}
const defenseFields = { sacks: 'def_sacks', interceptions: 'def_interceptions',
  fumbleRecoveries: 'fumble_recovery_opp', touchdowns: 'def_tds', safeties: 'def_safeties',
  puntBlocks: 'def_punt_blocks', patBlocks: 'def_pat_blocks', fgBlocks: 'def_fg_blocks',
  returnTds: 'special_teams_tds', twoPointReturns: 'def_2pt_made' };
const teamStats = Object.fromEntries([...new Set(teamRows.map(r => r.team))].map(team => {
  const rows = teamRows.filter(r => r.team === team).sort((a, b) => Number(a.week) - Number(b.week));
  const total = field => rows.reduce((sum, r) => sum + (num(r[field]) || 0), 0);
  return [team, { games: rows.length, passAttempts: total('attempts'), passingYards: total('passing_yards'),
    carries: total('carries'), rushingYards: total('rushing_yards'), defensiveSacks: total('def_sacks'),
    defensiveInterceptions: total('def_interceptions'), defenseGames: rows.map(r => ({ week: Number(r.week), ...pickStats(r, defenseFields), pointsAllowed: allowedThisSeason[`${team}|${r.week}`] ?? null })) }];
}));
const output = {
  source: 'nflverse', season: 2026, generatedAt: now.toISOString(), latestCompletedWeek, nextWeek,
  sourceUrls: {
    playerStats: 'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv',
    teamStats: 'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2026.csv',
    injuries: 'https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv',
    schedule: 'https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv',
  },
  hashes: { playerStats: playerInput.hash, teamStats: teamInput.hash, injuries: injuryInput.hash, schedule: gameInput.hash,
    ...(priorTeamsPath ? { priorTeamStats: csv(priorTeamsPath).hash } : {}) },
  coverage: { playerRows: regularPlayers.length, teamRows: teamRows.length, injuryRows: injuryInput.rows.length, scheduledGames: nextGames.length },
  players, schedule, teamStats, teamContext,
};
const target = resolve('site/yahoo/nflverse-2026.json');
writeFileSync(target, JSON.stringify(output));
process.stdout.write(`${target}: ${players.length} players, latest week ${latestCompletedWeek}, upcoming week ${nextWeek}\n`);
