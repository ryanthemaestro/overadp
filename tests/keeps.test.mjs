import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { loadKeeps, saveKeeps } from '../site/yahoo/keeps.mjs';

const memory = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), m }; };
test('locks round-trip per team and store only validated Yahoo player keys', () => {
  const s = memory();
  assert(saveKeeps('461.l.555.t.3', new Set(['461.p.100', 'not-a-key', '<script>']), s));
  assert.deepEqual([...s.m.keys()], ['overadp.keep.461.l.555.t.3']);
  assert.deepEqual(JSON.parse(s.m.get('overadp.keep.461.l.555.t.3')), ['461.p.100']);
  assert.deepEqual([...loadKeeps('461.l.555.t.3', s)], ['461.p.100']);
  assert.equal(loadKeeps('461.l.555.t.9', s).size, 0);
  saveKeeps('461.l.555.t.3', new Set(), s);
  assert.equal(s.m.size, 0, 'clearing removes the entry');
});
test('bad team keys, corrupt data and blocked storage fail quietly', () => {
  const s = memory();
  assert.equal(saveKeeps('../evil', new Set(['461.p.1']), s), false);
  s.setItem('overadp.keep.461.l.555.t.3', '{not json');
  assert.equal(loadKeeps('461.l.555.t.3', s).size, 0);
  const blocked = { getItem() { throw Error('denied'); }, setItem() { throw Error('denied'); }, removeItem() { throw Error('denied'); } };
  assert.equal(loadKeeps('461.l.555.t.3', blocked).size, 0);
  assert.equal(saveKeeps('461.l.555.t.3', new Set(['461.p.1']), blocked), false);
});
test('browser storage is used only by keeps.mjs, and never session storage or IndexedDB', () => {
  const dir = new URL('../site/yahoo/', import.meta.url);
  for (const file of readdirSync(dir).filter(f => /\.m?js$/.test(f))) {
    const code = readFileSync(new URL(file, dir), 'utf8');
    assert(!/sessionStorage|indexedDB|document\.cookie/.test(code), file);
    if (file !== 'keeps.mjs') assert(!/localStorage/.test(code), `${file} must not use localStorage`);
  }
  // The page discloses it where the feature is used.
  const html = readFileSync(new URL('index.html', dir), 'utf8');
  assert.match(html, /Locks are saved in this browser on this device only\. They're never sent to OverADP or Yahoo\./);
});
