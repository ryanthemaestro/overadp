import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { handle, seal, unseal, parseTeams, parseLeague, parseRoster, ORIGIN, CALLBACK, TOKEN_URL } from '../netlify/functions/_shared/yahoo-core.mjs';
const secret = 'ab'.repeat(32), time = 1800000000000;
const env = key => ({ YAHOO_ENABLED: 'true', YAHOO_CLIENT_ID: 'test-client', YAHOO_CLIENT_SECRET: 'test-secret', YAHOO_SESSION_SECRET: secret })[key];
const deps = { env, now: () => time };
const session = () => '__Host-overadp-yahoo-session=' + seal({ accessToken: 'private-access', exp: time + 60000 }, 'session', secret);
const post = (body = {}, cookie = '', headers = {}) => new Request(`${ORIGIN}/.netlify/functions/yahoo-api`, {
  method: 'POST', headers: { origin: ORIGIN, 'content-type': 'application/json', cookie, ...headers }, body: JSON.stringify(body),
});
const json = obj => new Response(JSON.stringify(obj), { headers: { 'content-type': 'application/json' } });
// Synthetic fixtures only. These are not captured Yahoo user data.
export const teamsFixture = { fantasy_content: { users: { '0': { user: [ { guid: 'DO-NOT-RETURN' }, { games: { '0': { game: [ { game_key: '999' }, { teams: { '0': { team: [[{ team_key: '999.l.123.t.4' }, { name: 'Example Team' }, { managers: [{ email: 'private@example.invalid' }] }]] }, count: 1 } } ] } } } ] } } } };
export const leagueFixture = { fantasy_content: { league: [ [ { name: 'Example League' }, { season: '2026' } ], { settings: [{ num_teams: 10, scoring_type: 'head', draft_type: 'live', roster_positions: [{ roster_position: { position: 'QB', count: 1 } }, { roster_position: { position: 'BN', count: 6 } }], stat_categories: { stats: [{ stat: { stat_id: 4, name: 'Passing Yards' } }] }, stat_modifiers: { stats: [{ stat: { stat_id: 4, value: 0.04 } }] } }] } ] } };
export const rosterFixture = { fantasy_content: { team: [{ roster: { players: { '0': { player: [[{ player_key: '999.p.1' }, { name: { full: '<b>Example Player</b>' } }, { display_position: 'RB' }, { editorial_team_abbr: 'EX' }, { status: 'Q' }], { selected_position: [{ coverage_type: 'week' }, { position: 'BN' }] }] }, count: 1 } } }] } };
test('authenticated encryption rejects tampering, wrong purpose and expiry', () => {
  const value = seal({ accessToken: 'do-not-leak', exp: time + 1 }, 'session', secret);
  assert(!value.includes('do-not-leak'));
  assert.equal(unseal(value, 'session', secret, time).accessToken, 'do-not-leak');
  assert.equal(unseal(value, 'state', secret, time), null);
  assert.equal(unseal(value, 'session', 'cd'.repeat(32), time), null);
  assert.equal(unseal(value, 'session', secret, time + 1), null);
  // Flip one character to a *different* one (overwriting with 'A' was a no-op 1 time in 64).
  assert.equal(unseal(value.slice(0, 20) + (value[20] === 'A' ? 'B' : 'A') + value.slice(21), 'session', secret, time), null);
});
test('start uses state, S256 PKCE, exact callback and read-only scope', async () => {
  const r = await handle('start', post(), deps), body = await r.json();
  const url = new URL(body.authorizationUrl);
  assert.equal(r.status, 200); assert.equal(url.searchParams.get('scope'), 'fspt-r');
  assert.equal(url.searchParams.get('redirect_uri'), CALLBACK);
  assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
  assert.equal(url.searchParams.get('state').length, 43);
  const cookie = r.headers.get('set-cookie');
  assert.match(cookie, /Secure; HttpOnly; SameSite=Lax/); assert.match(cookie, /Max-Age=600/);
  assert(!JSON.stringify(body).includes('test-secret'));
});
test('disabled connection fails closed', async () => {
  const r = await handle('start', post(), { ...deps, env: () => undefined });
  assert.equal(r.status, 503); assert.equal((await r.json()).error, 'NOT_CONFIGURED');
});
test('CSRF checks reject foreign/missing Origin and cross-site request metadata', async () => {
  for (const headers of [{ origin: 'https://attacker.invalid' }, { origin: '' }, { 'sec-fetch-site': 'cross-site' }]) {
    assert.equal((await handle('api', post({ action: 'status' }, session(), headers), deps)).status, 403);
  }
  assert.equal((await handle('api', new Request(`${ORIGIN}/.netlify/functions/yahoo-api`), deps)).status, 405);
  assert.equal((await handle('api', post({}, '', { 'content-type': 'text/plain' }), deps)).status, 415);
});
test('callback exchanges code only after verifying state; refresh token is discarded', async () => {
  const start = await handle('start', post(), deps), auth = new URL((await start.json()).authorizationUrl);
  const stateCookie = start.headers.get('set-cookie').split(';')[0];
  let calls = 0;
  const fetcher = async (url, options) => {
    calls++; assert.equal(url, TOKEN_URL); assert.equal(options.method, 'POST');
    assert.equal(new URLSearchParams(options.body).get('redirect_uri'), CALLBACK);
    assert.equal(new URLSearchParams(options.body).get('code_verifier').length, 64);
    assert.match(options.headers.Authorization, /^Basic /);
    return json({ access_token: 'private-access', refresh_token: 'must-be-discarded', expires_in: 7200, token_type: 'bearer' });
  };
  const good = await handle('callback', new Request(`${CALLBACK}?state=${auth.searchParams.get('state')}&code=private-code`, { headers: { cookie: stateCookie } }), { ...deps, fetcher });
  assert.equal(calls, 1); assert.equal(good.status, 303); assert.equal(good.headers.get('location'), '/yahoo/?connected=1');
  const encrypted = good.headers.getSetCookie().find(x => x.startsWith('__Host-overadp-yahoo-session=')).split(';')[0].split('=')[1];
  const decoded = unseal(encrypted, 'session', secret, time);
  assert.equal(decoded.exp, time + 3600000); assert.equal(decoded.accessToken, 'private-access');
  assert.equal(decoded.refresh_token, undefined); assert(!JSON.stringify([...good.headers]).includes('private-access'));
  const bad = await handle('callback', new Request(`${CALLBACK}?state=wrong&code=private-code`, { headers: { cookie: stateCookie } }), { ...deps, fetcher });
  assert.equal(calls, 1); assert.match(bad.headers.get('location'), /INVALID_STATE/);
});
test('expired state cannot trigger token exchange', async () => {
  const state = seal({ state: 'x', verifier: 'y', exp: time - 1 }, 'state', secret);
  const r = await handle('callback', new Request(`${CALLBACK}?state=x&code=z`, { headers: { cookie: `__Host-overadp-yahoo-state=${state}` } }), { ...deps, fetcher: () => { throw Error('must not fetch'); } });
  assert.match(r.headers.get('location'), /INVALID_STATE/);
});
test('connection status does not expose tokens or call Yahoo', async () => {
  const r = await handle('api', post({ action: 'status' }, session()), { ...deps, fetcher: () => { throw Error('must not fetch'); } });
  assert.deepEqual(await r.json(), { connected: true, configured: true, expiresAt: time + 60000 });
  assert.match(r.headers.get('cache-control'), /no-store/);
  assert.equal(r.headers.get('access-control-allow-origin'), ORIGIN);
});
test('disconnect clears both cookies even when disabled', async () => {
  const r = await handle('api', post({ action: 'disconnect' }, session()), { ...deps, env: () => undefined });
  assert.equal(r.status, 200); assert.equal(r.headers.getSetCookie().length, 2);
  assert(r.headers.getSetCookie().every(x => x.includes('Max-Age=0')));
});
test('missing/duplicate/tampered sessions cannot read data', async () => {
  for (const cookies of ['', '__Host-overadp-yahoo-session=garbage', `${session()}; ${session()}`]) {
    const r = await handle('api', post({ action: 'teams' }, cookies), deps); assert.equal(r.status, 401);
  }
});
test('allowlisted actions and strict keys reject arbitrary proxying', async () => {
  for (const body of [{ action: 'https://attacker.invalid' }, { action: 'league', teamKey: '../../evil' }, { action: 'league', teamKey: '999.l.123.t.4?evil' }]) {
    assert.equal((await handle('api', post(body, session()), deps)).status, 400);
  }
});
test('parsers handle Yahoo-shaped nested arrays and minimize private information', () => {
  assert.deepEqual(parseTeams(teamsFixture), [{ teamKey: '999.l.123.t.4', name: 'Example Team', leagueKey: '999.l.123' }]);
  const league = parseLeague(leagueFixture);
  assert.equal(league.name, 'Example League'); assert.equal(league.positions.length, 2);
  assert.deepEqual(league.scoring, [{ name: 'Passing Yards', value: '0.04' }]);
  assert.equal(parseRoster(rosterFixture)[0].slot, 'BN');
  assert(!JSON.stringify(parseTeams(teamsFixture)).includes('private@example'));
});
test('league requests check ownership and read only settings and roster endpoints', async () => {
  const urls = [];
  const fetcher = async (url, options) => {
    urls.push(url); assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, 'Bearer private-access');
    assert.equal(options.method, undefined);
    return json(url.includes('/users;') ? teamsFixture : url.includes('/league/') ? leagueFixture : rosterFixture);
  };
  const r = await handle('api', post({ action: 'league', teamKey: '999.l.123.t.4' }, session()), { ...deps, fetcher });
  assert.equal(r.status, 200); const body = await r.json(); assert.equal(body.roster.length, 1); assert.equal(urls.length, 3);
  assert(urls.every(x => x.startsWith('https://fantasysports.yahooapis.com/fantasy/v2/')));
  assert(!JSON.stringify(body).includes('private@example'));
  urls.length = 0;
  const bad = await handle('api', post({ action: 'league', teamKey: '999.l.999.t.9' }, session()), { ...deps, fetcher });
  assert.equal(bad.status, 403); assert.equal(urls.length, 1);
});
test('upstream errors are redacted and rate limits do not retry', async () => {
  for (const [status, expected] of [[401, 'SESSION_EXPIRED'], [403, 'YAHOO_ACCESS_DENIED'], [429, 'YAHOO_RATE_LIMIT'], [500, 'YAHOO_UNAVAILABLE']]) {
    let count = 0;
    const r = await handle('api', post({ action: 'teams' }, session()), { ...deps, fetcher: async () => { count++; return new Response('secret-upstream-body', { status }); } });
    assert.equal((await r.json()).error, expected); assert.equal(count, 1);
  }
});
test('request and response size limits fail safely', async () => {
  const big = await handle('api', post({ action: 'status', padding: 'x'.repeat(5000) }), deps);
  assert.equal(big.status, 502);
  const r = await handle('api', post({ action: 'teams' }, session()), { ...deps, fetcher: async () => new Response('secret', { headers: { 'content-length': '3000000' } }) });
  assert.equal(r.status, 502); assert.equal((await r.json()).error, 'RESPONSE_TOO_LARGE');
});
test('private frontend has no analytics, unsafe HTML sinks, persistent storage, or tokens', () => {
  const js = readFileSync(new URL('../site/yahoo/yahoo.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../site/yahoo/index.html', import.meta.url), 'utf8');
  assert(!/localStorage|sessionStorage|indexedDB|innerHTML|gtag\(|access_token|refresh_token/.test(js));
  assert(!/googletagmanager|google-analytics|supabase|fbq\(/.test(html));
  assert.deepEqual([...html.matchAll(/<script[^>]*src="([^"]+)"/g)].map(m => m[1]), ['/yahoo/yahoo.js']);
  assert.match(html, /Fantasy data provided by/); assert.match(js, /pagehide/);
});
