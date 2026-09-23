import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { scoreGame, scorePlayer } from '../site/yahoo/league-scoring.mjs';
const snapshot = JSON.parse(readFileSync(new URL('../site/yahoo/nflverse-2026.json', import.meta.url)));
const league = { scoring: [
  ['Pass Yds', .04], ['Pass TD', 4], ['Int', -1], ['Rush Yds', .1], ['Rush TD', 6],
  ['Rec', .5], ['Rec Yds', .1], ['Rec TD', 6], ['Ret TD', 6], ['2-PT', 2],
  ['Fum Lost', -2], ['Off Fumb TD', 6], ['FG 0-19', 3], ['FG 20-29', 3],
  ['FG 30-39', 3], ['FG 40-49', 4], ['FG 50+', 5], ['PAT Made', 1],
  ['Sack', 1], ['Int', 2], ['Fum Rec', 2], ['TD', 6], ['Safe', 2],
  ['Blk Kick', 2], ['Ret TD', 6], ['Pts Allow 0', 10], ['XPR', 2],
].map(([name, value]) => ({ name, value: String(value) })) };
test('the real league half-PPR rules score offense from weekly nflverse fields', () => {
  const lamar = snapshot.players.find(p => p.name === 'Lamar Jackson');
  assert.ok(lamar);
  const score = scorePlayer(lamar, league, snapshot.teamStats);
  assert.equal(score.games, 2);
  assert.equal(score.weekly[0].points, 24.96);
  assert.equal(score.weekly[1].points, 15.8); // Yahoo uses -1 interception, nflverse standard uses -2.
  assert.equal(score.points, 40.76);
  const receiver = snapshot.players.find(p => p.position === 'WR' && p.games.some(g => g.receptions > 0));
  const game = receiver.games.find(g => g.receptions > 0);
  const withoutPpr = { ...league, scoring: league.scoring.map(rule => rule.name === 'Rec' ? { ...rule, value: '0' } : rule) };
  assert.equal(scoreGame(game, 'WR', league.scoring).points - scoreGame(game, 'WR', withoutPpr.scoring).points, game.receptions * .5);
});
test('kicker buckets and PAT are scored without confusing standard nflverse fantasy points', () => {
  const mevis = snapshot.players.find(p => p.name === 'Harrison Mevis');
  assert.ok(mevis);
  const score = scorePlayer(mevis, league, snapshot.teamStats);
  assert.equal(score.partial, false);
  assert.ok(Number.isFinite(score.points));
});
test('missing stats and defense points allowed remain incomplete, not zero', () => {
  const missing = scoreGame({ passingYards: 100 }, 'QB', league.scoring);
  assert.equal(missing.points, null);
  assert.equal(missing.partial, true);
  const defense = scorePlayer({ position: 'DEF', team: 'SEA' }, league, snapshot.teamStats);
  assert.equal(defense?.points, null);
  assert.equal(defense?.partial, true);
  assert.match(defense.reason, /points allowed/);
});
