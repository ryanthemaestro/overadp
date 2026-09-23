import test from 'node:test';
import assert from 'node:assert/strict';
import { indexPublicPlayers, matchPublicPlayer, normalName, publicInjuryNote, publicSummary, formatKickoff } from '../site/yahoo/public-context.mjs';

test('join requires unique exact name, team and position', () => {
  const p = { name: 'Brian Thomas Jr.', team: 'JAC', position: 'WR', games: [] };
  const idx = indexPublicPlayers({ players: [p] });
  assert.equal(matchPublicPlayer({ name: 'Brian Thomas Jr.', team: 'JAX', position: 'WR' }, idx), p);
  assert.equal(matchPublicPlayer({ name: 'Brian Thomas Jr.', team: 'CHI', position: 'WR' }, idx), null);
  assert.equal(matchPublicPlayer({ name: 'Brian Thomas Jr.', team: 'JAX', position: 'RB' }, idx), null);
  assert.equal(matchPublicPlayer({ name: 'Different Person', team: 'JAX', position: 'WR' }, idx), null);
  assert.equal(matchPublicPlayer({ name: 'Brian Thomas Jr.', team: 'JAX', position: 'WR' }, indexPublicPlayers({ players: [p, p] })), null);
});
test('public summary labels standard points and historical injury rather than a forecast', () => {
  const p = { games: [{ week: 2, targets: 8, carries: 0 }], averagePoints: 12.4, recentInjury: { week: 2, reportStatus: 'Questionable' }, nextGame: { opponent: 'BAL', gameDate: '2026-09-27' } };
  assert.match(publicSummary(p, { nextWeek: 3 }), /public standard pts\/game/);
  assert.match(publicInjuryNote(p), /historical injury report/);
  assert.equal(normalName('Zay Flowers III'), normalName('Zay Flowers'));
});
test('kickoff dates show the weekday and Eastern clock without changing the listed time', () => {
  assert.equal(formatKickoff({ gameDate: '2026-09-24', gameTime: '20:15' }), 'Thursday, Sep 24 · 8:15 PM ET');
  assert.equal(formatKickoff({ gameDate: '2026-09-27', gameTime: '13:00' }), 'Sunday, Sep 27 · 1:00 PM ET');
  assert.equal(formatKickoff({ gameDate: '2026-09-28', gameTime: '20:15' }), 'Monday, Sep 28 · 8:15 PM ET');
  assert.equal(formatKickoff({ gameDate: '2026-09-31', gameTime: '20:15' }), null);
  assert.equal(formatKickoff({ gameDate: '2026-09-27', gameTime: '' }), 'Sunday, Sep 27 · time TBD');
});
test('kicker summary does not claim a nonexistent standard score, old injury history is suppressed', () => {
  const kicker = { position: 'K', games: [{ week: 2, points: 0 }], averagePoints: 0,
    nextGame: { opponent: 'NYG', gameDate: '2026-09-28', gameTime: '20:15' } };
  assert.match(publicSummary(kicker, { nextWeek: 3 }), /Monday, Sep 28 · 8:15 PM ET/);
  assert.match(publicSummary(kicker, { nextWeek: 3 }), /league points above are calculated from public kicking stats/);
  assert.doesNotMatch(publicSummary(kicker, { nextWeek: 3 }), /0\.0 public standard/);
  assert.equal(publicInjuryNote({ recentInjury: { week: 1, reportStatus: 'Questionable' } }, { latestCompletedWeek: 2 }), null);
});
