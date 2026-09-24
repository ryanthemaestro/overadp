import test from 'node:test';
import assert from 'node:assert/strict';
import { handle, seal, parseMatchup, ORIGIN } from '../netlify/functions/_shared/yahoo-core.mjs';
import { teamsFixture } from './yahoo.test.mjs';
const secret = 'ab'.repeat(32), time = 1800000000000;
const env = key => ({ YAHOO_ENABLED: 'true', YAHOO_CLIENT_ID: 'test-client', YAHOO_CLIENT_SECRET: 'test-secret', YAHOO_SESSION_SECRET: secret })[key];
const deps = { env, now: () => time };
const cookie = '__Host-overadp-yahoo-session=' + seal({ accessToken: 'private-access', exp: time + 60000 }, 'session', secret);
const post = body => new Request(`${ORIGIN}/.netlify/functions/yahoo-api`, {
  method: 'POST', headers: { origin: ORIGIN, 'content-type': 'application/json', cookie }, body: JSON.stringify(body) });
const json = obj => new Response(JSON.stringify(obj), { headers: { 'content-type': 'application/json' } });
// Synthetic fixtures shaped like Yahoo's numbered-object collections.
const team = (key, extra = {}) => ({ team: [[{ team_key: key }, { name: 'Team ' + key.split('.t.')[1] }], extra] });
const scoreboard = week => ({ fantasy_content: { league: [{ league_key: '999.l.123' }, { scoreboard: { '0': { matchups: {
  '0': { matchup: { week: String(week), status: 'preevent', '0': { teams: { '0': team('999.l.123.t.4', { team_projected_points: { total: '99' } }), '1': team('999.l.123.t.7'), count: 2 } } } },
  '1': { matchup: { week: String(week), '0': { teams: { '0': team('999.l.123.t.1'), '1': team('999.l.123.t.2'), count: 2 } } } },
  count: 2 } } } }] } });
const settings = { fantasy_content: { league: [[{ name: 'Example League' }, { season: '2026' }, { current_week: '3' }, { end_week: '17' }, { num_teams: '4' }],
  { settings: [{ playoff_start_week: '15', uses_playoff: '1', roster_positions: [{ roster_position: { position: 'QB', count: 1 } }] }] }] } };
const standings = { fantasy_content: { league: [{}, { standings: [{ teams: Object.fromEntries(['4', '7', '1', '2'].map((id, i) =>
  [String(i), { team: [[{ team_key: `999.l.123.t.${id}` }, { name: 'Team ' + id }], { team_standings: { rank: String(i + 1), outcome_totals: { wins: '1', losses: '1', ties: '0' } } }] }])) }] }] } };
const rosters = { fantasy_content: { league: [{}, { teams: Object.fromEntries(['4', '7', '1', '2'].map((id, i) =>
  [String(i), { team: [[{ team_key: `999.l.123.t.${id}` }], { roster: { week: '3', '0': { players: {} } } }] }])) }] } };

test('parseMatchup returns only the opponent key for the requested week', () => {
  assert.deepEqual(parseMatchup(scoreboard(3), '999.l.123.t.4', 3), { week: 3, opponentKey: '999.l.123.t.7' });
  assert.deepEqual(parseMatchup(scoreboard(3), '999.l.123.t.2', 3), { week: 3, opponentKey: '999.l.123.t.1' });
  assert.equal(parseMatchup(scoreboard(2), '999.l.123.t.4', 3), null);
  assert.equal(parseMatchup(scoreboard(3), '999.l.123.t.9', 3), null);
  assert.equal(parseMatchup({}, '999.l.123.t.4', 3), null);
});

function fetcherWith(scoreboardResponse) {
  const urls = [];
  const fetcher = async url => {
    urls.push(url);
    if (url.includes('/users;')) return json(teamsFixture);
    if (url.includes('/scoreboard')) return scoreboardResponse();
    if (url.includes('/standings')) return json(standings);
    if (url.includes('/teams/roster')) return json(rosters);
    return json(settings);
  };
  return { fetcher, urls };
}
test('command includes this week\'s opponent from a read-only scoreboard request', async () => {
  const { fetcher, urls } = fetcherWith(() => json(scoreboard(3)));
  const r = await handle('api', post({ action: 'command', teamKey: '999.l.123.t.4' }), { ...deps, fetcher });
  assert.equal(r.status, 200);
  const body = await r.json();
  assert.deepEqual(body.matchup, { week: 3, opponentKey: '999.l.123.t.7' });
  assert.equal(body.league.playoffStartWeek, 15); assert.equal(body.league.endWeek, 17);
  assert(urls.some(u => u.includes('league/999.l.123/scoreboard;week=3?format=json')));
  assert(!JSON.stringify(body).includes('team_projected_points'));
});
test('a denied or failed scoreboard leaves the matchup out without failing the league', async () => {
  for (const status of [403, 500]) {
    const { fetcher } = fetcherWith(() => new Response('upstream', { status }));
    const r = await handle('api', post({ action: 'command', teamKey: '999.l.123.t.4' }), { ...deps, fetcher });
    assert.equal(r.status, 200, String(status));
    assert.equal((await r.json()).matchup, null);
  }
});
test('a rate-limited scoreboard still stops the request', async () => {
  const { fetcher } = fetcherWith(() => new Response('slow down', { status: 429 }));
  const r = await handle('api', post({ action: 'command', teamKey: '999.l.123.t.4' }), { ...deps, fetcher });
  assert.equal(r.status, 429);
});
