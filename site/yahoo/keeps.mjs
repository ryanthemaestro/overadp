// Players a manager has locked against drop suggestions (e.g. a league that
// requires a backup K or DEF). Saved in this browser only, never sent to OverADP
// or Yahoo, and limited to validated Yahoo team and player keys. This is the only
// Team Hub file allowed to use browser storage (see tests/yahoo.test.mjs).
const PREFIX = 'overadp.keep.';
const TEAM = /^\d{1,8}\.l\.\d{1,12}\.t\.\d{1,6}$/, PLAYER = /^\d{1,8}\.p\.\d{1,12}$/;
const MAX = 50;
const store = storage => { try { return storage ?? globalThis.localStorage ?? null; } catch { return null; } };

export function loadKeeps(teamKey, storage) {
  try {
    const s = store(storage);
    if (!s || !TEAM.test(teamKey || '')) return new Set();
    const list = JSON.parse(s.getItem(PREFIX + teamKey) || '[]');
    return new Set(Array.isArray(list) ? list.filter(k => typeof k === 'string' && PLAYER.test(k)).slice(0, MAX) : []);
  } catch { return new Set(); }
}
export function saveKeeps(teamKey, keys, storage) {
  try {
    const s = store(storage);
    if (!s || !TEAM.test(teamKey || '')) return false;
    const list = [...keys].filter(k => typeof k === 'string' && PLAYER.test(k)).slice(0, MAX);
    if (list.length) s.setItem(PREFIX + teamKey, JSON.stringify(list)); else s.removeItem(PREFIX + teamKey);
    return true;
  } catch { return false; }
}
