import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

// This build consumes only public nflverse CSV snapshots. Yahoo data never enters it.
const [playersPath, teamsPath, injuriesPath, gamesPath] = process.argv.slice(2);
if (![playersPath, teamsPath, injuriesPath, gamesPath].every(Boolean)) {
  throw Error('Usage: node build-public-context.mjs PLAYER_CSV TEAM_CSV INJURY_CSV GAMES_CSV');
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
  passingYards: 'passing_yards', passingTds: 'passing_tds', interceptions: 'passing_interceptions',
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
const schedule = Object.fromEntries(nextGames.flatMap(r => [
  [r.home_team, { opponent: r.away_team, gameDate: r.gameday, gameTime: r.gametime, gameId: r.game_id }],
  [r.away_team, { opponent: r.home_team, gameDate: r.gameday, gameTime: r.gametime, gameId: r.game_id }],
]));
const players = [...playerMap.values()].map(p => {
  p.games.sort((a, b) => a.week - b.week);
  const scored = p.games.filter(g => Number.isFinite(g.points));
  p.averagePoints = scored.length ? Number((scored.reduce((s, g) => s + g.points, 0) / scored.length).toFixed(2)) : null;
  p.recentInjury = injuryMap.get(p.id) || null;
  p.nextGame = schedule[p.team] || null;
  return p;
});
const teamRows = teamInput.rows.filter(r => r.season === '2026' && r.season_type === 'REG');
const defenseFields = { sacks: 'def_sacks', interceptions: 'def_interceptions',
  fumbleRecoveries: 'fumble_recovery_opp', touchdowns: 'def_tds', safeties: 'def_safeties',
  puntBlocks: 'def_punt_blocks', patBlocks: 'def_pat_blocks', fgBlocks: 'def_fg_blocks',
  returnTds: 'special_teams_tds', twoPointReturns: 'def_2pt_made' };
const teamStats = Object.fromEntries([...new Set(teamRows.map(r => r.team))].map(team => {
  const rows = teamRows.filter(r => r.team === team).sort((a, b) => Number(a.week) - Number(b.week));
  const total = field => rows.reduce((sum, r) => sum + (num(r[field]) || 0), 0);
  return [team, { games: rows.length, passAttempts: total('attempts'), passingYards: total('passing_yards'),
    carries: total('carries'), rushingYards: total('rushing_yards'), defensiveSacks: total('def_sacks'),
    defensiveInterceptions: total('def_interceptions'), defenseGames: rows.map(r => ({ week: Number(r.week), ...pickStats(r, defenseFields) })) }];
}));
const output = {
  source: 'nflverse', season: 2026, generatedAt: now.toISOString(), latestCompletedWeek, nextWeek,
  sourceUrls: {
    playerStats: 'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv',
    teamStats: 'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2026.csv',
    injuries: 'https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv',
    schedule: 'https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv',
  },
  hashes: { playerStats: playerInput.hash, teamStats: teamInput.hash, injuries: injuryInput.hash, schedule: gameInput.hash },
  coverage: { playerRows: regularPlayers.length, teamRows: teamRows.length, injuryRows: injuryInput.rows.length, scheduledGames: nextGames.length },
  players, schedule, teamStats,
};
const target = resolve('site/yahoo/nflverse-2026.json');
writeFileSync(target, JSON.stringify(output));
process.stdout.write(`${target}: ${players.length} players, latest week ${latestCompletedWeek}, upcoming week ${nextWeek}\n`);
