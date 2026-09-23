import test from 'node:test';
import assert from 'node:assert/strict';
import { pickupCandidates } from '../site/yahoo/insights.mjs';
import { player, team, league } from './command-fixtures.mjs';

test('missing Yahoo scores use public recent-score tie break without elevating flagged players', () => {
  const own = { ...team, roster: [player(1, 'TE', 'BN', null, { status: 'D' })] };
  const setup = { ...league, positions: [{ position: 'TE', count: 1 }], currentWeek: 2 };
  const candidates = [
    player(90, 'TE', '', null, { ownership: 'waivers' }),
    player(91, 'TE', '', null, { ownership: 'waivers' }),
    player(92, 'TE', '', null, { ownership: 'waivers', status: 'Q' }),
  ];
  const scores = { '999.p.90': 4, '999.p.91': 9, '999.p.92': 20 };
  const ranked = pickupCandidates(candidates, own, setup, p => scores[p.playerKey]);
  assert.deepEqual(ranked.map(x => x.player.playerKey), ['999.p.91', '999.p.90', '999.p.92']);
  assert.match(ranked[0].reason, /0 unflagged eligible bench options/);
});
