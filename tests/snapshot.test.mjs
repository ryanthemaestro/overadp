import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url)));
test('2026 public context has real weekly coverage and traceable hashes', () => {
  const data = read('../site/yahoo/nflverse-2026.json');
  assert.equal(data.source, 'nflverse');
  assert.equal(data.season, 2026);
  assert.equal(data.latestCompletedWeek, 2);
  assert.equal(data.nextWeek, 3);
  assert.equal(Object.keys(data.schedule).length, 32);
  assert.equal(Object.keys(data.teamStats).length, 32);
  assert.ok(data.players.length > 400);
  for (const hash of Object.values(data.hashes)) assert.match(hash, /^[a-f0-9]{64}$/);
  assert.ok(data.players.every(p => p.games.every(g => g.week <= data.latestCompletedWeek)));
  assert.ok(!JSON.stringify(data).includes('teamKey'));
  assert.ok(!JSON.stringify(data).includes('leagueKey'));
});
test('Jev artifact is independent public-only, complete, and explicitly uncertain', () => {
  const data = read('../site/yahoo/jev-public-2026.json');
  assert.equal(data.source, 'Jev analysis of public nflverse data only');
  assert.equal(data.week, 3);
  assert.equal(Object.keys(data.decisions).length, 16);
  assert.ok(Object.values(data.decisions).every(v => ['elevated', 'ordinary', 'reduced', 'uncertain'].includes(v)));
  assert.match(data.evidenceWarning, /not a projection/);
  assert.ok(!JSON.stringify(data).includes('teamKey'));
  assert.ok(!JSON.stringify(data).includes('leagueKey'));
});
test('browser does not send Yahoo session data to Jev', () => {
  const code = readFileSync(new URL('../site/yahoo/yahoo.js', import.meta.url), 'utf8');
  assert.ok(!code.includes('api.typesafe.ai'));
  assert.ok(!code.includes('TYPESAFE_API_KEY'));
  assert.ok(!code.includes('localStorage'));
  assert.ok(!code.includes('sessionStorage'));
});
