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

// ---- Kickers ----
import { kickerPerGame, DEFAULT_K } from '../site/yahoo/ros.mjs';
const kicker = snapshot.players.find(p => p.position === 'K' && p.games.length === 2);
const ctx = { KC: { pointsPerGame: 30, priorPointsPerGame: 25, remainingIndoorShare: 0.2 }, DET: { pointsPerGame: 30, priorPointsPerGame: 25, remainingIndoorShare: 0.8 } };
const kLeague = { scoring: DEFAULT_K };
test('kicker model ships both parts and a K start/sit table', () => {
  assert.deepEqual(model.kicker.rest_of_season.features, ['intercept', 'base', 'obs0', 'indoor_share']);
  assert(model.kicker.next_week.features.includes('implied'));
  assert(model.start_sit.accuracy.K['1-2'] > 0.5);
});
test('rest of season: an indoor schedule is worth more, and results pull toward the league', () => {
  const outdoor = kickerPerGame({ kind: 'season', current: kicker, prior: null, team: 'KC', context: ctx, league: kLeague, model });
  const dome = kickerPerGame({ kind: 'season', current: kicker, prior: null, team: 'DET', context: ctx, league: kLeague, model });
  assert(dome.points > outdoor.points);
  assert(outdoor.points > 4 && outdoor.points < 12, String(outdoor.points));
  assert.match(outdoor.basis, /league-average start \+ 2 games, 20% of remaining games indoors/);
});
test('next week: a higher implied team total projects more', () => {
  const game = total => ({ impliedTotal: total, indoor: false });
  const low = kickerPerGame({ kind: 'week', current: kicker, prior: null, team: 'KC', context: ctx, game: game(17), league: kLeague, model });
  const high = kickerPerGame({ kind: 'week', current: kicker, prior: null, team: 'KC', context: ctx, game: game(30), league: kLeague, model });
  assert(high.points > low.points);
  assert.equal(kickerPerGame({ kind: 'week', current: kicker, prior: null, team: 'KC', context: ctx, game: null, league: kLeague, model }), null);
});
