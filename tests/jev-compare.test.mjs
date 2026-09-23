import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { comparisonPayload, handleComparison } from '../netlify/functions/_shared/jev-compare-core.mjs';
import { seal } from '../netlify/functions/_shared/yahoo-core.mjs';

const current = JSON.parse(readFileSync(new URL('../site/yahoo/nflverse-2026.json', import.meta.url)));
const prior = JSON.parse(readFileSync(new URL('../site/yahoo/nflverse-prior-2025.json', import.meta.url)));
const flowers = current.players.find(p => p.name === 'Zay Flowers');
const williams = current.players.find(p => p.name === 'Jameson Williams');
const input = { playerAId: flowers.id, playerBId: williams.id, scoring: 'standard' };
const secret = 'a'.repeat(64);
const cookie = seal({ accessToken: 'test-only', exp: Date.now() + 60000 }, 'session', secret);
const request = body => new Request('https://overadp.com/.netlify/functions/jev-compare', { method: 'POST',
  headers: { origin: 'https://overadp.com', 'sec-fetch-site': 'same-origin', 'content-type': 'application/json',
    cookie: `__Host-overadp-yahoo-session=${cookie}` }, body: JSON.stringify(body) });

test('Jev state contains only public football facts and manual scoring', () => {
  const data = comparisonPayload(input, current, prior);
  assert.equal(data.players.a, 'Zay Flowers');
  assert.equal(data.players.b, 'Jameson Williams');
  assert.equal(data.evidence, 'limited');
  const state = JSON.stringify(data.state);
  for (const forbidden of ['teamKey', 'leagueKey', 'Yahoo status', 'accessToken', 'waiver'])
    assert.ok(!state.includes(forbidden), forbidden);
});

test('server accepts only known same-position players and exact payload', () => {
  const qb = current.players.find(p => p.position === 'QB');
  assert.throws(() => comparisonPayload({ ...input, teamKey: 'private' }, current, prior), /INVALID_INPUT/);
  assert.throws(() => comparisonPayload({ ...input, playerBId: qb.id }, current, prior), /INVALID_PLAYERS/);
  assert.throws(() => comparisonPayload({ ...input, playerBId: flowers.id }, current, prior), /INVALID_INPUT/);
});

test('function sends only allowlisted public state and returns calibrated wording', async () => {
  let sent;
  const fetcher = async (url, init) => {
    assert.equal(url, 'https://api.typesafe.ai/v1/systemone');
    sent = JSON.parse(init.body);
    return new Response(JSON.stringify({ answers: { start: { choice: 'b', confidence: .62,
      probabilities: { a: .2, b: .7, uncertain: .1 } } } }), { status: 200 });
  };
  const response = await handleComparison(request(input), { env: key => key === 'YAHOO_SESSION_SECRET' ? secret : 'fake-key',
    snapshot: current, prior, fetcher });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.choice, 'b');
  assert.equal(result.confidence, .62);
  assert.match(result.note, /not the chance/);
  assert.ok(!JSON.stringify(sent).includes('test-only'));
  assert.deepEqual(Object.keys(JSON.parse(sent.state)).sort(), ['latestCompletedWeek','options','scoringAssumption','season','snapshotTime','source','upcomingWeek','userSelectedGenericScoring','warning'].sort());
});

test('unauthenticated request does not call the paid API', async () => {
  let calls = 0;
  const bad = new Request('https://overadp.com/.netlify/functions/jev-compare', { method: 'POST',
    headers: { origin: 'https://overadp.com', 'sec-fetch-site': 'same-origin', 'content-type': 'application/json' }, body: JSON.stringify(input) });
  const response = await handleComparison(bad, { env: () => secret, snapshot: current, prior,
    fetcher: async () => { calls++; throw Error('Should not call'); } });
  assert.equal(response.status, 401);
  assert.equal(calls, 0);
});
