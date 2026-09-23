import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { kickoffUtc, estimatePlayer, optimizeLineup, priorIndex, matchPrior, candidateImpact } from '../site/yahoo/weekly-advice.mjs';

const league = { currentWeek: 3, positions: [
  { position: 'QB', count: 1 }, { position: 'RB', count: 1 }, { position: 'WR', count: 1 }, { position: 'TE', count: 1 },
], scoring: [{ name: 'Rush Yds', value: 0.1, positionType: 'O' }] };
const upcoming = { gameDate: '2026-09-27', gameTime: '13:00' };
const player = (name, position, slot, points, status = '') => ({ playerKey: name, name, position, slot,
  team: 'BAL', status, byeWeek: 13, eligible: [position], points });
const est = p => ({ points: p.points, playable: !['O', 'D'].includes(p.status), locked: false, caution: p.status === 'Q' });

test('prior-season artifact is public-only, labeled and includes no Yahoo identifiers', () => {
  const raw = readFileSync(new URL('../site/yahoo/nflverse-prior-2025.json', import.meta.url), 'utf8');
  const data = JSON.parse(raw);
  assert.equal(data.source, 'nflverse');
  assert.equal(data.season, 2025);
  assert.match(data.sourceUrl, /^https:\/\/github\.com\/nflverse\//);
  assert.match(data.sha256, /^[a-f0-9]{64}$/);
  assert.ok(data.players.length >= 500);
  assert.equal(raw.includes('playerKey'), false);
  assert.equal(raw.includes('teamKey'), false);
});

test('Eastern kickoff lock handles daylight-saving and winter dates', () => {
  assert.equal(new Date(kickoffUtc(upcoming)).toISOString(), '2026-09-27T17:00:00.000Z');
  assert.equal(new Date(kickoffUtc({ gameDate: '2026-11-08', gameTime: '13:00' })).toISOString(), '2026-11-08T18:00:00.000Z');
  assert.equal(kickoffUtc({ gameDate: '2026-02-30', gameTime: '13:00' }), null);
});

test('prior player can move teams but ambiguous same-name match is rejected', () => {
  const idx = priorIndex({ players: [{ id: 'one', name: 'Runner Jr.', position: 'RB' }] });
  assert.equal(matchPrior({ id: 'one' }, { name: 'Someone', position: 'RB' }, idx).id, 'one');
  assert.equal(matchPrior(null, { name: 'Runner', position: 'RB' }, idx).id, 'one');
  const dup = priorIndex({ players: [{ id: 'one', name: 'Runner', position: 'RB' }, { id: 'two', name: 'Runner', position: 'RB' }] });
  assert.equal(matchPrior(null, { name: 'Runner', position: 'RB' }, dup), null);
});

test('early-season blend uses the league scoring and never treats unsupported points as zero', () => {
  const p = player('Runner', 'RB', 'RB', 0);
  const current = { nextGame: upcoming, games: [1, 2].map(week => ({ week, rushingYards: 100 })) };
  const prior = { games: [1, 2, 3, 4].map(week => ({ week, rushingYards: 50 })) };
  const out = estimatePlayer(p, league, current, prior, Date.UTC(2026, 8, 22));
  assert.equal(out.points, 7.5);
  assert.equal(estimatePlayer({ ...p, status: 'D' }, league, current, prior).playable, false);
  assert.equal(estimatePlayer(p, league, { nextGame: upcoming, games: [{ week: 1 }] }, null).points, null);
});

test('exact legal lineup fills a missing TE and prefers stronger bench player', () => {
  const roster = [player('QB', 'QB', 'QB', 20), player('RB', 'RB', 'RB', 15),
    player('WR weak', 'WR', 'WR', 7), player('WR strong', 'WR', 'BN', 12), player('TE bench', 'TE', 'BN', 9)];
  const result = optimizeLineup({ rosterAvailable: true, roster }, league, est);
  assert.deepEqual(result.assignments.map(x => x.player?.name), ['QB', 'RB', 'WR strong', 'TE bench']);
  assert.equal(result.moves.length, 2);
  assert.equal(result.knownPoints, 56);
});

test('locked starters stay in place and doubtful players are not selected', () => {
  const roster = [player('QB locked', 'QB', 'QB', 2), player('QB better', 'QB', 'BN', 20),
    player('RB', 'RB', 'RB', 15), player('WR doubtful', 'WR', 'WR', 25, 'D'),
    player('WR healthy', 'WR', 'BN', 10), player('TE', 'TE', 'TE', 6)];
  const result = optimizeLineup({ rosterAvailable: true, roster }, league, p => ({ ...est(p), locked: p.name === 'QB locked' }));
  assert.equal(result.assignments[0].player.name, 'QB locked');
  assert.equal(result.assignments[2].player.name, 'WR healthy');
});

test('waiver impact prioritizes a vacant eligible slot without inventing unknown points', () => {
  const roster = [player('QB', 'QB', 'QB', 20), player('RB', 'RB', 'RB', 15), player('WR', 'WR', 'WR', 10)];
  const lineup = optimizeLineup({ rosterAvailable: true, roster }, league, est);
  const pickup = player('TE available', 'TE', '', 8);
  assert.deepEqual(candidateImpact(pickup, lineup, est(pickup)), { slot: 'TE', replaced: null, gain: 8 });
  assert.equal(candidateImpact(pickup, lineup, { points: null, playable: true }), null);
});

test('a tiny estimated edge does not replace a healthy current starter', () => {
  const roster = [player('QB starter', 'QB', 'QB', 18.7), player('QB bench', 'QB', 'BN', 18.8),
    player('RB', 'RB', 'RB', 15), player('WR', 'WR', 'WR', 10), player('TE', 'TE', 'TE', 7)];
  const result = optimizeLineup({ rosterAvailable: true, roster }, league, est);
  assert.equal(result.assignments[0].player.name, 'QB starter');
});
