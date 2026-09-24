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
