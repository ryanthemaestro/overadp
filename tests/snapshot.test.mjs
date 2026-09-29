import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url)));
test('2026 public context has real weekly coverage and traceable hashes', () => {
  const data = read('../site/yahoo/nflverse-2026.json');
  assert.equal(data.source, 'nflverse');
  assert.equal(data.season, 2026);
  // Refreshed daily, so check shape rather than a specific week.
  assert.ok(Number.isInteger(data.latestCompletedWeek) && data.latestCompletedWeek >= 1);
  assert.ok(Number.isInteger(data.nextWeek) && data.nextWeek > data.latestCompletedWeek && data.nextWeek <= 18);
  const scheduled = Object.keys(data.schedule).length;
  assert.ok(scheduled >= 20 && scheduled <= 32 && scheduled % 2 === 0, 'teams with a game this week (bye weeks allowed)');
  assert.equal(Object.keys(data.teamStats).length, 32);
  assert.ok(data.players.length > 400);
  for (const hash of Object.values(data.hashes)) assert.match(hash, /^[a-f0-9]{64}$/);
  assert.ok(data.players.every(p => p.games.every(g => g.week <= data.latestCompletedWeek)));
  assert.ok(!JSON.stringify(data).includes('teamKey'));
  assert.ok(!JSON.stringify(data).includes('leagueKey'));
});
test('browser code has no third-party AI calls or browser storage', () => {
  const code = readFileSync(new URL('../site/yahoo/yahoo.js', import.meta.url), 'utf8');
  assert.ok(!code.includes('api.typesafe.ai'));
  assert.ok(!code.includes('TYPESAFE_API_KEY'));
  assert.ok(!code.includes('localStorage'));
  assert.ok(!code.includes('sessionStorage'));
});
test('snapshot builds mid-week, after the Thursday game, before the week is over', async () => {
  const { mkdtempSync, mkdirSync, writeFileSync } = await import('node:fs');
  const { execFileSync } = await import('node:child_process');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const dir = mkdtempSync(join(tmpdir(), 'snapshot-'));
  mkdirSync(join(dir, 'site/yahoo'), { recursive: true });
  const day = n => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);
  const file = (name, rows) => { writeFileSync(join(dir, name), rows.map(r => r.join(',')).join('\n') + '\n'); return join(dir, name); };
  // Week 1 is final; in week 2, AAA-CCC played Thursday and BBB-DDD is still to come.
  const games = file('games.csv', [['season', 'game_type', 'week', 'gameday', 'gametime', 'game_id', 'home_team', 'away_team', 'home_score', 'away_score'],
    ['2026', 'REG', '1', day(-9), '13:00', 'g1', 'AAA', 'BBB', '20', '17'], ['2026', 'REG', '1', day(-9), '13:00', 'g2', 'CCC', 'DDD', '24', '10'],
    ['2026', 'REG', '2', day(-2), '20:15', 'g3', 'AAA', 'CCC', '27', '3'], ['2026', 'REG', '2', day(1), '13:00', 'g4', 'BBB', 'DDD', '', '']]);
  const players = file('players.csv', [['season', 'season_type', 'week', 'player_id', 'player_display_name', 'position', 'team', 'opponent_team', 'fantasy_points'],
    ...['AAA', 'BBB', 'CCC', 'DDD'].map(t => ['2026', 'REG', '1', `p${t}`, `Player ${t}`, 'WR', t, 'XXX', '10']),
    ['2026', 'REG', '2', 'pAAA', 'Player AAA', 'WR', 'AAA', 'CCC', '30'], ['2026', 'REG', '2', 'pCCC', 'Player CCC', 'WR', 'CCC', 'AAA', '2']]);
  const teams = file('teams.csv', [['season', 'season_type', 'week', 'team', 'def_sacks'],
    ...['AAA', 'BBB', 'CCC', 'DDD'].map(t => ['2026', 'REG', '1', t, '2']), ['2026', 'REG', '2', 'AAA', '5'], ['2026', 'REG', '2', 'CCC', '1']]);
  const injuries = file('injuries.csv', [['season', 'season_type', 'week', 'gsis_id', 'report_status'], ['2026', 'REG', '2', 'pBBB', 'Questionable']]);
  execFileSync(process.execPath, [new URL('../scripts/build_yahoo_public_context.mjs', import.meta.url).pathname, players, teams, injuries, games], { cwd: dir });
  const data = JSON.parse(readFileSync(join(dir, 'site/yahoo/nflverse-2026.json')));
  assert.equal(data.nextWeek, 2);
  assert.equal(data.latestCompletedWeek, 1, 'a week counts once all its games are played');
  assert.ok(data.players.every(p => p.games.every(g => g.week === 1)), 'Thursday stats wait for the rest of the week');
  assert.ok(Object.values(data.teamStats).every(t => t.defenseGames.every(g => g.week === 1)));
  assert.deepEqual(Object.keys(data.schedule).sort(), ['AAA', 'BBB', 'CCC', 'DDD'], 'teams that already played keep their week 2 game');
  assert.equal(data.players.find(p => p.id === 'pBBB').recentInjury.reportStatus, 'Questionable', 'this week\'s injury reports still count');
});
