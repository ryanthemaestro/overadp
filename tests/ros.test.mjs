import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { rosPerGame, scoringRatio, HALF_PPR } from '../site/yahoo/ros.mjs';

const model = JSON.parse(readFileSync(new URL('../site/yahoo/ros-model.json', import.meta.url)));
const snapshot = JSON.parse(readFileSync(new URL('./fixtures/nflverse-2026-week2.json', import.meta.url)));
const halfLeague = { scoring: HALF_PPR };
const pprLeague = { scoring: HALF_PPR.map(r => r.name === 'Rec' ? { ...r, value: '1' } : r) };

test('model file covers every modeled position and bucket, with held-out errors', () => {
  for (const pos of ['QB', 'RB', 'WR', 'TE']) {
    assert.deepEqual(Object.keys(model.positions[pos]).sort(), model.buckets.map(([a, b]) => `${a}-${b}`).sort());
    for (const coef of Object.values(model.positions[pos])) assert.equal(coef.length, model.features.length);
    assert(model.held_out_mae[pos]['weeks 2-5'] < model.preseason_only_mae[pos]['weeks 2-5']);
  }
});
test('no games yet: the v6 preseason projection per game', () => {
  const r = rosPerGame({ position: 'WR', current: { games: [] }, prior: null, v6: { projected_points: 170 }, league: halfLeague, model });
  assert.equal(r.points, 10); assert.equal(r.basis, 'v6 preseason projection');
});
test('with games played, results and usage move the estimate from the preseason view', () => {
  const wr = snapshot.players.find(p => p.position === 'WR' && p.games.length === 2 && p.averagePoints > 15);
  const low = rosPerGame({ position: 'WR', current: wr, prior: null, v6: { projected_points: 60 }, league: halfLeague, model });
  assert(low.points > 60 / 17, 'a hot start lifts a low preseason projection');
  assert.match(low.basis, /v6 projection \+ 2 games this season/);
});
test('league scoring converts from half-PPR using the player\'s own games', () => {
  const wr = snapshot.players.find(p => p.position === 'WR' && p.averagePoints > 10 && p.games.some(g => g.receptions > 4));
  assert(scoringRatio('WR', wr.games, pprLeague) > 1);
  const half = rosPerGame({ position: 'WR', current: wr, prior: null, v6: { projected_points: 150 }, league: halfLeague, model });
  const ppr = rosPerGame({ position: 'WR', current: wr, prior: null, v6: { projected_points: 150 }, league: pprLeague, model });
  assert(ppr.points > half.points);
});
test('kickers, defenses and players with no data get no rest-of-season model', () => {
  assert.equal(rosPerGame({ position: 'K', current: null, prior: null, v6: null, league: halfLeague, model }), null);
  assert.equal(rosPerGame({ position: 'WR', current: { games: [] }, prior: null, v6: null, league: halfLeague, model }), null);
});
