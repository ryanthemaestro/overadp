import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeAvailablePages, pickupCandidates } from '../site/yahoo/insights.mjs';
test('a zero free-agent page does not hide players on waivers', () => {
  const player = { playerKey: 'nfl.p.1', name: 'Available Tight End', position: 'TE', eligible: ['TE'],
    ownership: 'waivers', status: '', team: 'SEA' };
  const merged = mergeAvailablePages([{ pool: 'FA', players: [] }, { pool: 'W', players: [player] }]);
  assert.deepEqual(merged, [player]);
  const league = { season: '2026', currentWeek: 3, positions: [{ position: 'TE', count: 1 }] };
  const team = { rosterAvailable: true, roster: [] };
  const candidates = pickupCandidates(merged, team, league, () => ({ points: 19, average: 9.5 }));
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].priority, 3);
  assert.equal(candidates[0].points, 19);
});
test('duplicate player keys across pools are not shown twice', () => {
  const player = { playerKey: 'nfl.p.1', ownership: 'freeagents' };
  assert.equal(mergeAvailablePages([{ players: [player] }, { players: [{ ...player, ownership: 'waivers' }] }]).length, 1);
});
