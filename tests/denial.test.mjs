import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { classifyDenial, DENIAL_REASONS } from '../netlify/functions/_shared/yahoo-denial.mjs';
import { handle, seal } from '../netlify/functions/_shared/yahoo-core.mjs';
const now = 1800000000000, secret = 'ab'.repeat(32);
const env = key => ({ YAHOO_ENABLED: 'true', YAHOO_CLIENT_ID: 'test-id', YAHOO_CLIENT_SECRET: 'test-secret', YAHOO_SESSION_SECRET: secret })[key];
const session = '__Host-overadp-yahoo-session=' + seal({ accessToken: 'PRIVATE-TOKEN', exp: now + 60000 }, 'session', secret);
const post = (cookie = session) => new Request('https://overadp.com/.netlify/functions/yahoo-api', { method: 'POST', headers: { origin: 'https://overadp.com', 'content-type': 'application/json', cookie }, body: '{"action":"teams"}' });
const response = description => new Response(JSON.stringify({ error: { description } }), { status: 403 });
test('application denial becomes one fixed category', async () => {
  assert.equal(await classifyDenial(response('This application is not authorized to perform this action')), 'APPLICATION_NOT_AUTHORIZED');
});
test('explicit scope, account, resource, game and token reasons are distinguished', async () => {
  for (const [text, code] of [['insufficient_scope', 'INSUFFICIENT_SCOPE'], ['ACCOUNT_NOT_AUTHORIZED', 'ACCOUNT_NOT_AUTHORIZED'], ['You are not allowed to view this league', 'RESOURCE_ACCESS_DENIED'], ['Invalid game key specified', 'INVALID_GAME_KEY'], ['TOKEN_EXPIRED', 'TOKEN_REJECTED']]) {
    assert.equal(await classifyDenial(response(text)), code);
  }
});
test('top-level OAuth error strings and descriptions are handled', async () => {
  assert.equal(await classifyDenial(new Response('{"error":"insufficient_scope","error_description":"PRIVATE"}')), 'INSUFFICIENT_SCOPE');
});
test('XML description is classified without echoing embedded private data', async () => {
  assert.equal(await classifyDenial(new Response('<?xml version="1.0"?><error><description>This application is not authorized to perform this action</description><detail>PRIVATE</detail></error>')), 'APPLICATION_NOT_AUTHORIZED');
});
test('HTML is not mislabeled as an application-permission failure', async () => {
  assert.equal(await classifyDenial(new Response('<!DOCTYPE html><html>This application is not authorized PRIVATE</html>')), 'HTML_REJECTION');
});
test('arbitrary text, absent or malformed fields remain unclassified', async () => {
  for (const text of ['PRIVATE', '<invalid>', '{}', 'null', '{"error":null}', '{"error":{"description":{"secret":"PRIVATE"}}}', '{"error":{"description":"Permission denied"}}']) {
    assert.equal(await classifyDenial(new Response(text)), 'UNCLASSIFIED');
  }
});
test('no substring inference from unrelated fantasy fields', async () => {
  assert.equal(await classifyDenial(new Response('{"team":{"name":"This application is not authorized"}}')), 'UNCLASSIFIED');
});
test('oversized advertised error body is cancelled', async () => {
  let cancelled = false;
  const body = new ReadableStream({ cancel() { cancelled = true; } });
  assert.equal(await classifyDenial(new Response(body, { headers: { 'content-length': '9000' } })), 'UNCLASSIFIED'); assert(cancelled);
});
test('oversized streamed body is cancelled without reading indefinitely', async () => {
  let cancelled = false;
  const body = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(8193)); }, cancel() { cancelled = true; } });
  assert.equal(await classifyDenial(new Response(body)), 'UNCLASSIFIED'); assert(cancelled);
});
test('failed upstream error stream has a safe fallback', async () => {
  const body = new ReadableStream({ start(c) { c.error(new Error('PRIVATE')); } });
  assert.equal(await classifyDenial(new Response(body)), 'UNCLASSIFIED');
});
test('authenticated denial returns only an allowlisted diagnostic and never retries', async () => {
  let calls = 0;
  const r = await handle('api', post(), { env, now: () => now, fetcher: async () => { calls++; return response('This application is not authorized to perform this action. PRIVATE-TOKEN private@example.invalid'); } });
  assert.equal(r.status, 403); assert.equal(calls, 1);
  assert.deepEqual(await r.json(), { error: 'YAHOO_ACCESS_DENIED', diagnostic: 'APPLICATION_NOT_AUTHORIZED' });
  assert.match(r.headers.get('cache-control'), /no-store/);
});
test('unauthenticated requests cannot inspect upstream reasons or invoke Yahoo', async () => {
  const r = await handle('api', post(''), { env, now: () => now, fetcher: () => { throw Error('Must not call'); } });
  assert.equal(r.status, 401); assert.deepEqual(await r.json(), { error: 'SESSION_EXPIRED' });
});
test('non-403 errors remain redacted with no extra diagnostic', async () => {
  for (const status of [401, 429, 500]) {
    const r = await handle('api', post(), { env, now: () => now, fetcher: async () => new Response('PRIVATE', { status }) });
    const body = await r.json(); assert(!Object.hasOwn(body, 'diagnostic')); assert(!JSON.stringify(body).includes('PRIVATE'));
  }
});
test('frontend uses only fixed known diagnostic strings and no new unsafe sinks', () => {
  const source = fs.readFileSync(new URL('../site/yahoo/yahoo.js', import.meta.url), 'utf8');
  assert.match(source, /Object\.hasOwn\(denialMessages, e\.diagnostic\)/);
  for (const reason of DENIAL_REASONS) assert(source.includes(reason));
  assert(!/console\.|innerHTML|localStorage|sessionStorage|indexedDB/.test(source));
});
test('rendered diagnostics use fixed text even for unknown or prototype keys', () => {
  const source = fs.readFileSync(new URL('../site/yahoo/yahoo.js', import.meta.url), 'utf8');
  const declarations = source.slice(0, source.indexOf("$('connect').addEventListener")).replace(/^import .*\n/gm, '');
  for (const diagnostic of [...DENIAL_REASONS, 'PRIVATE-TOKEN', '__proto__', 'constructor']) {
    const status = { textContent: '', classList: { toggle() {} } };
    const context = vm.createContext({ document: { getElementById: () => status }, input: { code: 'YAHOO_ACCESS_DENIED', diagnostic } });
    vm.runInContext(declarations + '\nerror(input);', context);
    const expected = DENIAL_REASONS.includes(diagnostic) ? diagnostic : 'UNCLASSIFIED';
    assert.match(status.textContent, new RegExp('Diagnostic: ' + expected + '\\.'));
    assert(!status.textContent.includes('PRIVATE-TOKEN'));
  }
});
