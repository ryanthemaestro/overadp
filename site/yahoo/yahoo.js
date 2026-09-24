import { isBench, isStarter, pickupCandidates, mergeAvailablePages } from './insights.mjs';
import { indexPublicPlayers, matchPublicPlayer, normalTeam, normalName } from './public-context.mjs';
import { scorePlayer } from './league-scoring.mjs';
import { priorIndex, matchPrior, estimatePlayer, optimizeLineup, candidateImpact } from './weekly-advice.mjs';
import { yahooLinks, statusTag, gameLine, starterTotal, buildMoves, movesGain, positionRanks, tradeIdea, fantasyWeeks, availabilityShare, addValue, describeAdd, PLAYOFF_WEIGHT, startSit, closestCalls, dropOrder, mustLeaveIR, likelyReturn } from './hub.mjs';
import { rosPerGame, kickerPerGame, defensePerGame } from './ros.mjs';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = String(text); if (cls) n.className = cls; return n; };
const fmt = n => Number.isFinite(n) ? n.toFixed(1) : '—';
const messages = {
  NOT_CONFIGURED: 'The Yahoo connection is being set up. Please check back shortly.',
  SESSION_EXPIRED: 'Your Yahoo connection expired. Connect again to continue.',
  YAHOO_ACCESS_DENIED: 'Yahoo refused this API read without a recognized error reason. Diagnostic: UNCLASSIFIED.',
  YAHOO_RATE_LIMIT: 'Yahoo is limiting requests. Please wait before trying again.',
  NO_CURRENT_WEEK: 'Yahoo has not supplied a current NFL week for this league. No lineups have been assumed.',
  AUTH_DECLINED: 'Yahoo authorization was cancelled. Nothing was connected.',
  INVALID_STATE: 'That connection attempt could not be verified. Please connect again.',
  TOKEN_EXCHANGE_FAILED: 'Yahoo could not complete the connection. Please try again or contact support.',
  YAHOO_UNAVAILABLE: "Yahoo's servers didn't answer that request. Try Refresh in a minute.",
  SERVER_UNAVAILABLE: 'Our server hiccuped while reading Yahoo. Try Refresh in a minute.',
  INVALID_RESPONSE: "Yahoo sent data we couldn't read. Try Refresh; if it keeps happening, tell us.",
  RESPONSE_TOO_LARGE: "Yahoo sent more data than expected. Try a narrower position filter.",
  TEAM_NOT_AUTHORIZED: "Yahoo says this account can't read that team. Try Refresh or reconnect.",
};
const denialMessages = Object.freeze({
  APPLICATION_NOT_AUTHORIZED: 'Yahoo accepted sign-in but reports that this application is not authorized for the requested Fantasy API access. Diagnostic: APPLICATION_NOT_AUTHORIZED.',
  INSUFFICIENT_SCOPE: 'Yahoo reports that the granted token lacks a required permission. Diagnostic: INSUFFICIENT_SCOPE.',
  ACCOUNT_NOT_AUTHORIZED: 'Yahoo reports that this account has not authorized the application. Diagnostic: ACCOUNT_NOT_AUTHORIZED.',
  RESOURCE_ACCESS_DENIED: 'Yahoo denied access to the requested fantasy resource. Diagnostic: RESOURCE_ACCESS_DENIED.',
  INVALID_GAME_KEY: 'Yahoo rejected the game identifier in the API request. Diagnostic: INVALID_GAME_KEY.',
  TOKEN_REJECTED: 'Yahoo rejected the access token for this read. Try connecting again. Diagnostic: TOKEN_REJECTED.',
  HTML_REJECTION: 'Yahoo returned a web-page rejection instead of an API error. Diagnostic: HTML_REJECTION.',
  UNCLASSIFIED: messages.YAHOO_ACCESS_DENIED,
});
const POS_CLASS = { QB: 'QB', RB: 'RB', WR: 'WR', TE: 'TE', K: 'K', DEF: 'DEF', 'D/ST': 'DEF' };
let generation = 0, controller, expiry, command = null, availableGeneration = 0, availableController;
let candidates = [], pickupPosition = 'ALL', addsShown = 6, demo = null, comparePicks = [], keeps = new Set(), keepsTeam = null;
let cooldownUntil = 0, rateLimitCount = 0;
let publicSnapshot = null, publicIndex = new Map(), priorSnapshot = null, priorPlayers = null, contextReady = null;
let v6Index = new Map(), rosModel = null;
const rosCache = new Map();
function publicCurrent() {
  return publicSnapshot && Number(command?.league?.season) === publicSnapshot.season &&
    publicSnapshot.nextWeek === command?.league?.currentWeek &&
    Number.isFinite(Date.parse(publicSnapshot.generatedAt)) &&
    Date.now() - Date.parse(publicSnapshot.generatedAt) <= 48 * 3600000;
}
function publicMatch(player) { return publicSnapshot?.season === Number(command?.league?.season) ? matchPublicPlayer(player, publicIndex) : null; }
function weekly(player) {
  if (!publicCurrent()) return { points: null, playable: false, reason: 'Current-week public snapshot unavailable or stale' };
  const matched = publicMatch(player);
  const pub = matched || { nextGame: publicSnapshot.schedule?.[normalTeam(player.team)], games: [] };
  const prior = priorSnapshot?.season === publicSnapshot.season - 1 ? matchPrior(matched, player, priorPlayers) : null;
  const estimate = estimatePlayer(player, command.league, pub, prior);
  // One model everywhere: the calibrated projection replaces the older this-week average.
  const pos = String(player.position || '').toUpperCase().split(/[,/]/)[0];
  if (estimate.playable && ['QB', 'RB', 'WR', 'TE'].includes(pos)) {
    const r = rosPoints(player);
    if (r) return { ...estimate, points: r.points, basis: r.basis };
  }
  // Kickers this week: the next-week kicker model, which uses the betting line.
  if (estimate.playable && pos === 'K' && rosModel) {
    const r = kickerPerGame({ kind: 'week', current: matched, prior, team: normalTeam(player.team), context: publicSnapshot.teamContext,
      game: pub.nextGame, league: command.league, model: rosModel });
    if (r) return { ...estimate, points: r.points, basis: r.basis };
  }
  // Defenses this week: the next-week defense model, driven by the betting line.
  if (estimate.playable && pos === 'DEF' && rosModel) {
    const r = defensePerGame({ kind: 'week', team: normalTeam(player.team), snapshot: publicSnapshot, league: command.league, model: rosModel });
    if (r) return { ...estimate, points: r.points, basis: r.basis };
  }
  return estimate;
}
function actualScore(player) {
  if (!publicSnapshot || publicSnapshot.season !== Number(command?.league?.season)) return null;
  if (String(player.position).toUpperCase().replace('D/ST', 'DEF') === 'DEF')
    return scorePlayer({ position: 'DEF', team: normalTeam(player.team) }, command.league, publicSnapshot.teamStats);
  return scorePlayer(publicMatch(player), command.league, publicSnapshot.teamStats);
}
// Rest-of-season points per game in this league's scoring (calibrated model for
// QB/RB/WR/TE; this week's estimate for K and DEF). Byes fall back to the v6 file.
function rosPoints(p) {
  const key = p.playerKey || p.name;
  if (rosCache.has(key)) return rosCache.get(key);
  const pos = String(p.position || '').toUpperCase().split(/[,/]/)[0].replace('D/ST', 'DEF');
  const current = publicSnapshot ? publicMatch(p) : null, v6 = current ? v6Index.get(current.id) : null;
  if (!Number.isInteger(p.byeWeek) && Number.isInteger(v6?.bye)) p.byeWeek = v6.bye;
  let r = rosModel ? rosPerGame({ position: pos, current, prior: priorPlayers ? matchPrior(current, p, priorPlayers) : null, v6, league: command.league, model: rosModel }) : null;
  if (!r && pos === 'K' && rosModel && publicSnapshot)
    r = kickerPerGame({ kind: 'season', current, prior: priorPlayers ? matchPrior(current, p, priorPlayers) : null, team: normalTeam(p.team),
      context: publicSnapshot.teamContext, game: nextGame(p), league: command.league, model: rosModel });
  if (!r && pos === 'DEF' && rosModel && publicSnapshot)
    r = defensePerGame({ kind: 'season', team: normalTeam(p.team), snapshot: publicSnapshot, league: command.league, model: rosModel });
  if (!r && ['K', 'DEF'].includes(pos)) { const e = weekly(p); r = Number.isFinite(e.points) ? { points: e.points, basis: e.basis } : null; }
  rosCache.set(key, r); return r;
}
// Defenses are valued week by week against each opponent, so a second defense gets
// credit for the weeks its matchup is better (streaming), not just for byes.
const defenseWeekCache = new Map();
function defenseWeek(p, week) {
  const key = `${normalTeam(p.team)}|${week}`;
  if (!defenseWeekCache.has(key)) {
    const kind = week === publicSnapshot?.nextWeek ? 'week' : 'future';
    defenseWeekCache.set(key, rosModel && publicSnapshot ? defensePerGame({ kind, team: normalTeam(p.team), week, snapshot: publicSnapshot, league: command.league, model: rosModel }) : null);
  }
  return defenseWeekCache.get(key);
}
// Injury type (latest public report) and team games missed since the player last played,
// used by the measured return curves. Public nflverse data only.
function annotateInjury(p) {
  if (p.injuryAnnotated) return p;
  const pub = publicMatch(p), team = normalTeam(p.team);
  const teamWeeks = (publicSnapshot?.teamStats?.[team]?.defenseGames || []).map(g => g.week);
  const last = Math.max(0, ...(pub?.games || []).map(g => g.week));
  const report = pub?.recentInjury, text = String(report?.injury || '').toLowerCase();
  p.injuryGroup = (rosModel?.availability?.groups || []).find(g => text.includes(g.toLowerCase())) || (text ? 'Other' : null);
  p.gamesMissed = pub ? teamWeeks.filter(w => w > last).length : 0;
  p.injuryAnnotated = true;
  return p;
}
function seasonPoints(p, week) {
  const share = availabilityShare(annotateInjury(p), week, command.league.currentWeek, rosModel?.availability);
  if (/^(DEF|D\/ST)$/i.test(String(p.position))) {
    const w = defenseWeek(p, week);
    if (w) return w.points * share;
  }
  const r = rosPoints(p); return r ? r.points * share : 0;
}
function nextGame(player) { return publicMatch(player)?.nextGame || publicSnapshot?.schedule?.[normalTeam(player.team)] || null; }
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
// A confirmation that clears itself unless something else replaced it meanwhile.
function notice(text) { status(text); setTimeout(() => { if ($('status').textContent === text) status(''); }, 4000); }
// `where` names the step for errors on our side; `target` shows the message there
// instead of in the page-wide banner. Only fixed text and short error codes are shown.
function error(e, where = '', target = null) {
  if (e.name === 'AbortError') return;
  if (e.code === 'SESSION_EXPIRED') connected(false);
  const code = /^[A-Z_]{3,40}$/.test(e.code || '') ? e.code : null;
  const message = e.code === 'YAHOO_RATE_LIMIT' ? 'Yahoo is limiting requests. Try again after ' + new Date(cooldownUntil).toLocaleTimeString() + '.'
    : e.code === 'YAHOO_ACCESS_DENIED' && Object.hasOwn(denialMessages, e.diagnostic) ? denialMessages[e.diagnostic]
    : messages[e.code] || (code ? `Yahoo could not finish this read (${code}). Missing information has not been treated as zero.`
      : `Something went wrong on our side${where ? ` while ${where}` : ''} (${/^[A-Za-z]{1,30}$/.test(e.name || '') ? e.name : 'Error'}). Refresh to retry.`);
  if (target) { target.textContent = message; target.classList.add('error-text'); } else status(message, true);
  return message;
}
function arrowIcon() {
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); path.setAttribute('d', 'M7 17 17 7M8 7h9v9');
  svg.append(path); return svg;
}
function yahooButton(label, href, primary = true) {
  const a = el('a', label, 'button' + (primary ? ' primary' : ''));
  a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.append(arrowIcon()); return a;
}
function posClass(position) { return 'pos-' + (POS_CLASS[String(position).toUpperCase().split(/[,/]/)[0]] || 'FLEX'); }
function tagEl(tag) { return tag ? el('span', tag.text, 'tag ' + tag.tone) : null; }

function resetCandidates() {
  availableGeneration++; availableController?.abort(); availableController = null;
  candidates = []; addsShown = 6; $('candidates').replaceChildren(); $('more-adds').hidden = true; $('pickup-status').textContent = '';
}
function clearWorkspace() {
  command = null; document.body.classList.remove('loaded'); resetCandidates(); comparePicks = []; renderCompare();
  $('hub').hidden = true; $('tabbar').hidden = true;
  for (const id of ['matchup', 'moves', 'glance', 'starters', 'bench', 'drop-order', 'ranks', 'trade', 'settings', 'warnings']) $(id).replaceChildren();
}
function clearData() {
  generation++; controller?.abort(); controller = null; clearTimeout(expiry); clearWorkspace();
  $('team').replaceChildren(new Option('Select your team', '')); $('teams-section').hidden = true; $('load').disabled = true;
}
function connected(on) {
  document.body.classList.toggle('connected', on);
  $('connect-panel').hidden = on; $('yahoo-chip').hidden = !on; $('disconnect').hidden = !on; $('refresh').hidden = !on;
  if (!on) { clearData(); $('empty-message').textContent = 'OverADP only reads your team. You make every change in Yahoo.'; }
}
function setExpiry(timestamp) {
  if (!Number.isFinite(timestamp)) return;
  clearTimeout(expiry);
  expiry = setTimeout(() => { connected(false); status('Your Yahoo session expired. The displayed league information was cleared.'); }, Math.max(0, timestamp - Date.now()));
}
async function request(action, extra = {}, signal, retried = false) {
  if (demo) return action === 'command' ? demo.command : action === 'teams' ? { teams: demo.teams } : demo.available(extra);
  if (action !== 'disconnect' && Date.now() < cooldownUntil) throw { code: 'YAHOO_RATE_LIMIT' };
  const r = await fetch('/.netlify/functions/yahoo-api', { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...extra }) });
  // A platform error (e.g. a cold start) returns plain text, not our JSON.
  let body; try { body = await r.json(); } catch { body = { error: r.ok ? 'INVALID_RESPONSE' : 'SERVER_UNAVAILABLE' }; }
  // Reads are safe to repeat once after a server-side hiccup.
  if (!retried && action !== 'disconnect' && ['SERVER_UNAVAILABLE', 'YAHOO_UNAVAILABLE'].includes(body.error)) {
    await new Promise(done => setTimeout(done, 800));
    return request(action, extra, signal, true);
  }
  if (r.status === 429) {
    const seconds = Math.max(60, Number(r.headers.get('retry-after')) || 0, Math.min(900, 60 * 2 ** rateLimitCount++));
    cooldownUntil = Date.now() + seconds * 1000;
  }
  if (!r.ok) throw { code: body.error, diagnostic: body.diagnostic };
  rateLimitCount = 0; setExpiry(body.expiresAt); return body;
}

function ownTeam() { return command?.teams.find(t => t.teamKey === command.team.teamKey); }
function currentLineup(team) {
  return { moves: [], assignments: team.roster.filter(isStarter).map(p => ({ slot: p.slot, player: p, estimate: weekly(p) })) };
}
function plan() {
  const mine = ownTeam();
  const fresh = publicCurrent();
  const lineup = mine?.rosterAvailable ? (fresh ? optimizeLineup(mine, command.league, weekly) : currentLineup(mine)) : null;
  const weeks = fantasyWeeks(command.league);
  const drops = mine?.rosterAvailable && weeks.length ? dropOrder({ roster: mine.roster, league: command.league, weeks, value: seasonPoints, keep: keeps }) : [];
  const moves = lineup ? buildMoves({ team: mine, league: command.league, lineup, estimate: weekly, pickups: rankedCandidates(), drops, links: yahooLinks(mine.teamKey) }) : [];
  return { mine, lineup, moves, fresh, drops };
}

function renderMatchup(mine, moves) {
  const box = $('matchup'), opponent = command.teams.find(t => t.teamKey === command.matchup?.opponentKey);
  const me = starterTotal(mine, weekly), them = opponent ? starterTotal(opponent, weekly) : null;
  const top = el('div', null, 'matchup-top');
  top.append(el('span', opponent ? "This week's matchup" : 'Your starters this week', 'eyebrow'));
  const kickoffs = mine.roster.filter(isStarter).map(p => weekly(p)).filter(e => Number.isFinite(e.kickoff) && e.kickoff > Date.now()).map(e => e.kickoff);
  const first = mine.roster.filter(isStarter).map(p => ({ p, e: weekly(p) })).filter(x => x.e.kickoff === Math.min(...kickoffs))[0];
  if (first) top.append(el('span', `First game ${gameLine(first.p.team, nextGame(first.p))?.split(' · ')[1] || ''}`, 'fine'));
  const sides = el('div', null, 'matchup-sides');
  const side = (label, total, cls) => {
    const s = el('div', null, 'side ' + cls);
    s.append(el('span', label, 'side-name'), el('span', total?.points != null ? fmt(total.points) : '—', 'side-pts'),
      el('span', total?.missing ? `est. points · ${total.missing} without an estimate` : 'est. points', 'fine'));
    return s;
  };
  sides.append(side('You', me, 'mine'));
  if (opponent) sides.append(side(`${opponent.name}${Number.isFinite(opponent.wins) ? ` · ${opponent.wins}–${opponent.losses}` : ''}`, them, 'right'));
  box.replaceChildren(top, sides);
  if (opponent && Number.isFinite(me.points) && Number.isFinite(them?.points)) {
    const bar = el('div', null, 'bar'), a = el('span'), b = el('span');
    a.style.flexGrow = String(me.points); b.style.flexGrow = String(them.points); bar.append(a, b); box.append(bar);
  }
  const gain = movesGain(moves), note = el('p', null, 'matchup-note');
  if (!publicCurrent()) note.textContent = 'Point estimates are paused until the public stats update. Yahoo statuses below are current.';
  else if (gain > 0) { note.append('Making the moves below adds about '); note.append(el('strong', `${fmt(gain)} points`)); note.append('.'); }
  else note.textContent = opponent && Number.isFinite(me.points) && Number.isFinite(them?.points)
    ? (me.points >= them.points ? 'You are the projected favorite as set.' : 'You are the projected underdog as set. Check Waivers for upgrades.')
    : 'Your lineup is set as well as your roster allows.';
  box.append(note);
}
function renderMoves(moves, fresh) {
  $('moves-title').textContent = moves.length ? `${moves.length} move${moves.length === 1 ? '' : 's'} this week` : 'Moves this week';
  $('moves-sub').textContent = moves.length > 1 ? 'Most important first' : '';
  if (!moves.length) {
    const box = el('div', null, 'card all-clear'), ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); path.setAttribute('d', 'M20 6 9 17l-5-5'); svg.append(path);
    const text = el('div'); text.append(el('strong', fresh ? 'Nothing to change right now' : 'No status problems in your lineup'),
      el('p', fresh ? 'Your best healthy players are starting and no free agent clearly beats them. Check back after injury reports.' : 'Point estimates are paused until the public stats update, so only Yahoo injury tags were checked.'));
    box.append(svg, text); $('moves').replaceChildren(box); return;
  }
  $('moves').replaceChildren(...moves.map(m => {
    const card = el('article', null, 'move'), top = el('div', null, 'move-top');
    top.append(el('span', m.kind === 'lineup' ? 'Start / sit' : m.kind === 'pickup' ? 'Pick up' : m.kind === 'roster' ? 'Roster fix' : 'Watch', 'kind ' + m.kind), el('span', m.impact, 'impact'));
    const actions = el('div', null, 'move-actions');
    actions.append(yahooButton(m.action, m.href));
    card.append(top, el('p', m.headline, 'move-title'), el('p', m.why, 'move-why'), actions);
    if (m.basis) { const d = el('details', null, 'basis'); d.append(el('summary', 'How is this estimated?'), el('p', `Based on ${m.basis} under your league's scoring.`)); card.append(d); }
    return card;
  }));
}
function playerRow(p, { slot = p.slot, extraTag = null, compact = false } = {}) {
  const e = weekly(p), row = el('div', null, 'row' + (compact ? ' compact' : ''));
  const tag = statusTag(p, command.league.currentWeek);
  if (tag) row.classList.add('flagged');
  const slotName = String(slot || p.position).toUpperCase().replace('W/R/T', 'FLEX');
  row.append(el('span', slotName, 'slot ' + (slotName === 'FLEX' || slotName === 'BN' ? posClass(p.position) : posClass(slotName))));
  const who = el('div', null, 'who'), line = el('div', null, 'name-line');
  line.append(el('span', p.name, 'name'));
  for (const t of [tag, extraTag, e.locked && Number.isFinite(e.kickoff) ? { text: 'LOCKED', tone: 'lock' } : null]) if (t) line.append(tagEl(t));
  who.append(line);
  if (!compact) who.append(el('span', gameLine(p.team, nextGame(p)) || `${String(p.team || 'Team').toUpperCase()} · no game found`, 'game'));
  row.append(who, el('span', fmt(e.points), 'pts'));
  if (!compact) row.append(compareButton(p));
  return row;
}
function renderLineup(mine, lineup) {
  $('edit-lineup').href = yahooLinks(mine.teamKey).team;
  if (!mine.rosterAvailable) { $('starters').replaceChildren(el('p', 'Yahoo did not return your current lineup. Try Refresh.', 'empty')); $('bench').replaceChildren(); return; }
  const order = command.league.positions.map(p => String(p.position).toUpperCase());
  const starters = mine.roster.filter(isStarter).sort((a, b) => order.indexOf(String(a.slot).toUpperCase()) - order.indexOf(String(b.slot).toUpperCase()));
  const bench = mine.roster.filter(isBench);
  const incoming = new Set((lineup?.moves || []).map(m => m.player.playerKey));
  const outgoing = new Set((lineup?.moves || []).map(m => m.replaces?.playerKey).filter(Boolean));
  const withLock = (row, p) => { row.insertBefore(lockButton(p), row.lastChild); return row; };
  $('starters').replaceChildren(...starters.map(p => withLock(playerRow(p, { extraTag: outgoing.has(p.playerKey) ? { text: 'SIT', tone: 'bad' } : null }), p)));
  $('bench').replaceChildren(...(bench.length ? bench.map(p => withLock(playerRow(p, { extraTag: mustLeaveIR(p) ? { text: 'OFF IR', tone: 'bad' } : incoming.has(p.playerKey) ? { text: 'START', tone: 'good' } : null }), p))
    : [el('p', 'No bench players.', 'empty')]));
  $('glance').replaceChildren(...starters.map(p => playerRow(p, { compact: true, extraTag: outgoing.has(p.playerKey) ? { text: 'SIT', tone: 'bad' } : null })));
  const asSet = starterTotal(mine, weekly), best = lineup?.knownPoints;
  const summary = $('lineup-summary'); summary.replaceChildren();
  if (!publicCurrent()) summary.textContent = 'Point estimates are paused until the public stats update. Injury tags come straight from Yahoo.';
  else {
    summary.append('Est. ', el('strong', fmt(asSet.points)), ' as set');
    if (lineup?.moves?.length && Number.isFinite(best) && best > asSet.points) { const s = el('strong', fmt(best), 'hi'); summary.append(' · ', s, ' with the suggested changes'); }
  }
}
// ---- Start/sit compare ----
function compareButton(p) {
  const b = el('button', '⇄', 'compare-btn'); b.type = 'button'; b.dataset.key = p.playerKey;
  b.setAttribute('aria-label', `Compare ${p.name}`); b.setAttribute('aria-pressed', String(comparePicks.some(x => x.playerKey === p.playerKey)));
  b.addEventListener('click', () => toggleCompare(p)); return b;
}
function toggleCompare(p) {
  const i = comparePicks.findIndex(x => x.playerKey === p.playerKey);
  if (i >= 0) comparePicks.splice(i, 1); else { if (comparePicks.length === 2) comparePicks.shift(); comparePicks.push(p); }
  renderCompare();
}
function renderCompare() {
  if (!command) comparePicks = [];
  const tray = $('compare-tray'); tray.hidden = !comparePicks.length;
  document.body.classList.toggle('tray-open', !tray.hidden);
  $('tray-picks').replaceChildren(...comparePicks.map(p => {
    const chip = el('div', null, 'tray-chip'), pos = String(p.position).split(/[,/]/)[0];
    chip.append(el('span', pos, 'slot ' + posClass(pos)), el('span', p.name, 'name'), el('span', fmt(weekly(p).points), 'pts'));
    return chip;
  }), ...(comparePicks.length === 1 ? [el('p', 'Pick one more player to compare.', 'fine')] : []));
  const [a, b] = comparePicks;
  $('tray-verdict').textContent = b ? startSit({ player: a, estimate: weekly(a) }, { player: b, estimate: weekly(b) }, rosModel, command.league.currentWeek).text : '';
  document.querySelectorAll('.compare-btn').forEach(btn => btn.setAttribute('aria-pressed', String(comparePicks.some(x => x.playerKey === btn.dataset.key))));
}
// A searched player: use the Yahoo record if they're rostered or available (it carries status).
function comparablePlayer(pub) {
  const same = p => normalName(p.name) === normalName(pub.name) && normalTeam(p.team) === normalTeam(pub.team);
  return command.teams.flatMap(t => t.roster).find(same) || candidates.map(c => c.player).find(same) ||
    { name: pub.name, position: pub.position, team: pub.team, playerKey: `pub.${pub.id}`, status: '', slot: '', eligible: [pub.position] };
}
function renderSearch() {
  // Match the start of any part of the name ("kel" finds Kelce, "tra" finds Travis), or the full name.
  const q = normalName($('player-search').value);
  const matches = name => normalName(name).startsWith(q) || String(name).split(/[\s.'-]+/).some(part => normalName(part).startsWith(q));
  const hits = q.length < 2 || !publicSnapshot ? [] : publicSnapshot.players.filter(p => matches(p.name) && p.nextGame)
    .sort((a, b) => (b.averagePoints ?? 0) - (a.averagePoints ?? 0)).slice(0, 6);
  $('search-results').replaceChildren(...hits.map(pub => {
    const b = el('button', null, 'search-hit'); b.type = 'button';
    b.append(el('span', pub.position, 'slot ' + posClass(pub.position)), el('span', pub.name, 'name'), el('span', pub.team, 'game'));
    b.addEventListener('click', () => { toggleCompare(comparablePlayer(pub)); $('player-search').value = ''; renderSearch(); });
    return b;
  }), ...(q.length >= 2 && !hits.length ? [el('p', 'No player with a game this week matches that name.', 'fine')] : []));
}
function renderCalls(mine, lineup) {
  const calls = publicCurrent() ? closestCalls({ team: mine, lineup, estimate: weekly }) : [];
  $('calls').replaceChildren(...(calls.length ? calls.map(c => {
    const b = el('button', null, 'call'); b.type = 'button';
    b.append(el('span', c.slot, 'slot ' + posClass(c.slot === 'FLEX' ? c.starter.position : c.slot)),
      el('span', `${c.starter.name} vs ${c.alt.name}`, 'call-names'),
      el('span', c.gap < 1 ? 'Toss-up' : `${c.benchAhead ? 'Bench' : 'Starter'} +${fmt(c.gap)}`, 'call-gap' + (c.benchAhead ? ' ahead' : '')));
    b.addEventListener('click', () => { comparePicks = [c.starter, c.alt]; renderCompare(); });
    return b;
  }) : [el('p', publicCurrent() ? 'No close calls: every starter projects at least 3 points ahead of your best bench option.' : 'Projections are paused until the public stats update.', 'empty')]));
}
function renderDrops(drops) {
  const locked = (ownTeam()?.roster || []).filter(p => keeps.has(p.playerKey)).map(p => p.name);
  $('kept-list').textContent = locked.length ? `Locked: ${locked.join(', ')}.` : '';
  $('clear-keeps').hidden = !locked.length;
  $('drop-order').replaceChildren(...(drops.length ? drops.slice(0, 4).map((d, i) => {
    const row = el('div', null, 'row compact');
    row.append(el('span', String(i + 1), 'add-rank'), el('span', d.player.name, 'name drop-name'),
      el('span', d.cost <= 0.05 ? 'never starts' : `−${fmt(d.cost)} pts`, 'pts drop-cost'));
    return row;
  }) : [el('p', 'Rest-of-season projections are needed to rank drops.', 'empty')]));
}
function renderLeague() {
  const { ranks, byTeam } = positionRanks(command, weekly);
  $('ranks').replaceChildren(...ranks.map(r => {
    const row = el('div', null, 'rank-row'), body = el('div', null, 'rank-body'), line = el('div', null, 'rank-line');
    const label = !r.rank ? 'Not enough data to rank' : r.of < 5 ? `Only ${r.of} teams could be compared` : r.rank <= 3 ? 'Strength' : r.rank > r.of - 3 ? 'Weak spot' : 'Middle of the pack';
    line.append(el('span', label), el('span', r.rank ? `${r.rank} of ${r.of}` : '—'));
    const meter = el('div', null, 'meter'), fill = el('span', null, r.rank && r.of >= 5 && r.rank <= 3 ? 'strong' : r.rank && r.of >= 5 && r.rank > r.of - 3 ? 'weak' : '');
    fill.style.width = r.rank ? `${Math.round(100 * (r.of - r.rank + 1) / r.of)}%` : '0%'; meter.append(fill);
    body.append(line, meter); row.append(el('span', r.pos, 'slot ' + posClass(r.pos)), body); return row;
  }));
  const idea = tradeIdea({ ranks, byTeam }, command.team.teamKey);
  $('trade').hidden = !idea;
  if (idea) $('trade').replaceChildren(el('p', 'Trade idea', 'eyebrow'), el('p', `You're deep at ${idea.strong} and thin at ${idea.weak}`, 'title'),
    el('p', idea.partners ? `${idea.partners} team${idea.partners === 1 ? ' is' : 's are'} the reverse: strong at ${idea.weak}, weak at ${idea.strong}. That's where a trade is most likely to help both sides.`
      : `No team is clearly the reverse right now, so a ${idea.strong}-for-${idea.weak} trade may take a sweetener.`, 'body'));
  const table = (headings, rows) => {
    const t = el('table'), head = el('tr'); headings.forEach(h => { const th = el('th', h); th.scope = 'col'; head.append(th); }); t.append(head);
    rows.forEach(cells => { const tr = el('tr'); cells.forEach(c => tr.append(el('td', c))); t.append(tr); }); return t;
  };
  $('settings').replaceChildren(table(['Slot', 'Count'], command.league.positions.map(p => [p.position, p.count])),
    table(['Scoring', 'Points'], command.league.scoring.map(s => [s.name, s.value])));
}
function renderCommand() {
  document.body.classList.add('loaded');
  const mine = ownTeam();
  $('team-meta').textContent = `${command.league.name} · Week ${command.league.currentWeek}${Number.isFinite(mine?.wins) ? ` · ${mine.wins}–${mine.losses}${mine.ties ? `–${mine.ties}` : ''}` : ''}`;
  $('team-name').textContent = command.team.name;
  $('warnings').replaceChildren(...command.warnings.map(w => el('p', w, 'warning')));
  const weeks = fantasyWeeks(command.league), firstPlayoff = weeks.find(w => w.playoff);
  if (weeks.length) $('waivers-note').textContent = `Ranked by the starting-lineup points each player adds to your team from Week ${weeks[0].week} through Week ${weeks.at(-1).week}${firstPlayoff ? `, with playoff weeks (${firstPlayoff.week}+) counting ${PLAYOFF_WEIGHT}×` : ''}, after the best drop. Byes, injuries and flex spots included.`;
  renderPlan(); renderLeague();
  $('hub').hidden = false; $('tabbar').hidden = false; $('teams-section').hidden = $('team').options.length <= 2;
}
function renderPlan() {
  const { mine, lineup, moves, fresh, drops } = plan();
  renderMatchup(mine, moves); renderMoves(moves, fresh); renderLineup(mine, lineup); renderDrops(drops); renderCalls(mine, lineup); renderCompare();
}
const VIEWS = ['week', 'lineup', 'waivers', 'league'];
// The tab lives in the address (#waivers), so a refresh or pull-to-refresh returns to it.
function selectView(view, scroll = true) {
  if (!VIEWS.includes(view)) view = 'week';
  document.body.dataset.view = view;
  const keep = new URL(location.href).searchParams.get('demo') === '1' ? '?demo=1' : '';
  history.replaceState(null, '', '/yahoo/' + keep + (view === 'week' ? '' : '#' + view));
  for (const b of document.querySelectorAll('button[data-view]')) b.setAttribute('aria-pressed', String(b.dataset.view === view));
  if (scroll) window.scrollTo({ top: 0 });
}

// Season value of an add against this roster, respecting locked players.
function valueCandidate(c) {
  const mine = ownTeam(), weeks = fantasyWeeks(command.league);
  return { ...c, ros: Number.isFinite(c.rosPg) && mine?.rosterAvailable && weeks.length
    ? addValue({ roster: mine.roster, candidate: c.player, league: command.league, weeks, value: seasonPoints, keep: keeps }) : null };
}
// ---- Locks: keep players out of drop suggestions for this visit ----
// Kept in memory only. The Yahoo API agreement (2(c)(vii)) bars storing, caching or
// indexing Yahoo Fantasy Information, so locks are never written to the device.
const LOCK = 'M7 11V7a5 5 0 0 1 10 0v4M5 11h14v10H5z';
function lockButton(p) {
  const on = keeps.has(p.playerKey), b = el('button', null, 'keep-btn'); b.type = 'button';
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); path.setAttribute('d', LOCK); svg.append(path); b.append(svg);
  b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', `${on ? 'Unlock' : 'Lock'} ${p.name} ${on ? '(may be suggested as a drop)' : '(never suggest dropping)'}`);
  b.addEventListener('click', () => { if (on) keeps.delete(p.playerKey); else keeps.add(p.playerKey); applyKeeps(); });
  return b;
}
function applyKeeps() {
  candidates = candidates.map(valueCandidate); renderPlan(); renderAdds();
}
function rankedCandidates() {
  return [...candidates].sort((a, b) => (b.ros?.gain ?? -Infinity) - (a.ros?.gain ?? -Infinity)
    || (b.rosPg ?? -Infinity) - (a.rosPg ?? -Infinity) || a.player.name.localeCompare(b.player.name));
}
function renderAdds() {
  const sorted = rankedCandidates(), links = yahooLinks(command.team.teamKey);
  $('candidates').replaceChildren(...(sorted.length ? sorted.slice(0, addsShown).map((c, i) => {
    const p = c.player, gain = c.ros?.gain, helps = Number.isFinite(gain) && gain > 0;
    const card = el('article', null, 'add' + (i === 0 && helps ? ' top' : '')), head = el('div', null, 'add-head');
    const who = el('div', null, 'who'), line = el('div', null, 'name-line');
    line.append(el('span', String(p.position).split(',')[0], 'slot ' + posClass(p.position)), el('span', p.name, 'name'));
    const tag = statusTag(p, command.league.currentWeek); if (tag) line.append(tagEl(tag));
    who.append(line, el('span', `${String(p.team || 'FA').toUpperCase()} · ${p.ownership === 'waivers' ? `Waivers${p.waiverDate ? ` until ${p.waiverDate}` : ''}` : 'Free agent'}${Number.isFinite(c.rosPg) ? ` · ${fmt(c.rosPg)} pts/game` : ''}`, 'game'));
    const g = el('div', null, 'add-gain');
    g.append(el('strong', helps ? `+${fmt(gain)}` : '0', helps ? '' : 'none'), el('span', 'pts rest of season'));
    head.append(el('span', String(i + 1), 'add-rank'), who, g);
    const isDef = /DEF|D\/ST/i.test(String(p.position));
    let why = c.ros ? describeAdd(c.ros) : isDef ? "No projection for this defense yet (its season data or betting line is missing)."
      : c.estimate?.playable === false && c.estimate?.reason ? c.estimate.reason : 'No rest-of-season estimate for this player yet.';
    if (Number.isFinite(c.impact?.gain) && c.impact.gain > 0 && c.impact.replaced) why += ` This week: +${fmt(c.impact.gain)} over ${c.impact.replaced}.`;
    const back = likelyReturn(annotateInjury(p), rosModel?.availability);
    if (back) why += ` ${p.injuryGroup && p.injuryGroup !== 'Other' ? `${p.injuryGroup} injury: ` : ''}players in this spot have usually been back about ${back} game${back === 1 ? '' : 's'} from now, and the value above counts that.`;
    const foot = el('div', null, 'add-foot'), dropText = el('span');
    if (helps && c.ros.dropDetails?.length) {
      dropText.append('Drop ');
      const samePos = d => String(d.player.position).split(',')[0] === String(p.position).split(',')[0];
      c.ros.dropDetails.forEach((d, j) => { if (j) dropText.append(' and '); dropText.append(el('strong', d.player.name), !d.starts ? ' (never starts)' : samePos(d) ? ' (replaced)' : ` (starts ${d.starts} wk${d.starts === 1 ? '' : 's'})`); });
    }
    else dropText.textContent = helps ? 'You have an open roster spot' : '';
    const actions = el('div', null, 'add-actions');
    actions.append(compareButton(p), yahooButton(p.ownership === 'waivers' ? 'Claim' : 'Add', links.add(p.playerKey) || links.league));
    foot.append(dropText, actions);
    card.append(head, el('p', why, 'add-why'), foot); return card;
  }) : [el('p', 'No available players matched this filter.', 'empty card')]));
  $('more-adds').hidden = sorted.length <= addsShown;
}
async function findPlayers() {
  if (!command) return;
  availableController?.abort(); availableController = new AbortController();
  const id = ++availableGeneration, leagueGeneration = generation;
  const teamKey = command.team.teamKey, position = pickupPosition;
  $('pickup-status').textContent = 'Checking free agents and waivers…';
  $('pickup-status').classList.remove('error-text');
  const pages = [], failed = [];
  try {
    for (const pool of ['FA', 'W']) {
      try {
        const d = await request('available', { teamKey, pool, position, start: 0 }, availableController.signal);
        if (d.teamKey !== teamKey || d.season !== command.league.season || d.pool !== pool || d.position !== position) throw { code: 'INVALID_RESPONSE' };
        pages.push(d);
      } catch (e) {
        // Keep one pool's results if the other fails, unless the session or rate limit is the problem.
        if (e.name === 'AbortError' || ['SESSION_EXPIRED', 'YAHOO_RATE_LIMIT', 'YAHOO_ACCESS_DENIED'].includes(e.code)) throw e;
        failed.push({ pool, e });
      }
      if (id !== availableGeneration || leagueGeneration !== generation) return;
    }
    if (!pages.length) throw failed[0].e;
  } catch (e) {
    if (id === availableGeneration && leagueGeneration === generation) error(e, 'reading available players', $('pickup-status'));
    return;
  }
  try {
    const mine = ownTeam(), lineup = publicCurrent() ? optimizeLineup(mine, command.league, weekly) : null;
    mine.roster.forEach(rosPoints);
    candidates = pickupCandidates(mergeAvailablePages(pages), mine, command.league, actualScore).map(c => {
      const estimate = weekly(c.player), r = rosPoints(c.player);
      return valueCandidate({ ...c, estimate, impact: lineup ? candidateImpact(c.player, lineup, estimate) : null, rosPg: r?.points ?? null, rosBasis: r?.basis || null });
    });
    addsShown = 6; renderAdds();
    $('pickup-status').textContent = `${candidates.length} available ${position === 'ALL' ? 'players' : position + 's'} checked · read ${new Date(pages.at(-1).fetchedAt).toLocaleTimeString()}` +
      (failed.length ? ` · ${failed[0].pool === 'W' ? 'Waiver-wire' : 'Free-agent'} list unavailable right now, so it isn't included` : '');
    if (position === 'ALL') renderPlan();
  } catch (e) {
    if (id === availableGeneration && leagueGeneration === generation) error(e, 'ranking available players', $('pickup-status'));
  }
}

async function teams() {
  clearData(); const id = generation; controller = new AbortController(); $('refresh').disabled = true;
  status('Reading your Yahoo football teams…');
  try {
    const data = await request('teams', {}, controller.signal); if (id !== generation) return;
    for (const team of data.teams) $('team').append(new Option(team.name + ' · league ' + team.leagueKey.split('.l.')[1], team.teamKey));
    if (data.teams.length === 1) { $('team').value = data.teams[0].teamKey; await loadLeague(); }
    else if (data.teams.length > 1) { $('teams-section').hidden = false; status('Connected. Choose the team you want to open.'); }
    else status('Connected, but Yahoo returned no current NFL teams for this account.');
  } catch (e) { if (id === generation) error(e); }
  // Always re-enable: loading the league bumps `generation`, so a generation check here
  // used to leave Refresh disabled after every page load.
  finally { $('refresh').disabled = false; }
}
// Refresh in place: re-read the league from Yahoo without clearing the page, so the
// reader keeps their tab and scroll position and sees that something happened.
async function refresh() {
  if (!command) return teams();
  const button = $('refresh'), id = ++generation;
  controller?.abort(); controller = new AbortController();
  button.disabled = true; button.textContent = 'Refreshing…'; status('Reading your league from Yahoo…');
  try {
    const data = await request('command', { teamKey: command.team.teamKey }, controller.signal);
    if (id !== generation) return;
    command = data; rosCache.clear(); defenseWeekCache.clear(); renderCommand(); resetCandidates(); findPlayers();
    notice(`Updated from Yahoo at ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}.`);
  } catch (e) { if (id === generation) error(e, 'refreshing your league'); }
  finally { button.disabled = false; button.textContent = 'Refresh'; }
}
async function loadLeague() {
  const id = ++generation; controller?.abort(); controller = new AbortController(); clearWorkspace(); $('load').disabled = true;
  status('Reading your league, lineup and matchup…');
  try {
    const data = await request('command', { teamKey: $('team').value }, controller.signal);
    await contextReady; if (id !== generation) return;
    command = data; if (command.team.teamKey !== keepsTeam) { keeps = new Set(); keepsTeam = command.team.teamKey; } rosCache.clear(); defenseWeekCache.clear(); renderCommand(); status(demo ? 'SYNTHETIC LOCAL PREVIEW. No live Yahoo league data loaded.' : '');
    findPlayers();
  } catch (e) { if (id === generation) { $('teams-section').hidden = false; error(e); } }
  finally { if (id === generation) $('load').disabled = !$('team').value; }
}

async function loadPublicContext() {
  try {
    const response = await fetch('/yahoo/nflverse-2026.json', { cache: 'no-cache' });
    if (!response.ok) throw Error('Public snapshot unavailable');
    const data = await response.json();
    if (data.source !== 'nflverse' || data.season !== 2026 || !Array.isArray(data.players)) throw Error('Public snapshot invalid');
    publicSnapshot = data; publicIndex = indexPublicPlayers(data);
    const ageHours = (Date.now() - Date.parse(data.generatedAt)) / 3600000;
    $('public-coverage').textContent = `Public stats: nflverse through Week ${data.latestCompletedWeek} · updated ${new Date(data.generatedAt).toLocaleString()}${!Number.isFinite(ageHours) || ageHours > 48 ? ' · out of date, estimates paused' : ''}`;
    if (command) { renderPlan(); renderLeague(); }
  } catch {
    $('public-coverage').textContent = 'Public stats unavailable. Yahoo roster information remains usable.';
  }
}
async function loadRosContext() {
  try {
    const [players, model] = await Promise.all(['/app/data/players.json', '/yahoo/ros-model.json'].map(async url => {
      const r = await fetch(url, { cache: 'no-cache' }); if (!r.ok) throw Error(url); return r.json();
    }));
    if (!Array.isArray(players) || model.version !== 1) throw Error('Rest-of-season inputs invalid');
    v6Index = new Map(players.map(p => [p.player_id, p])); rosModel = model;
  } catch { v6Index = new Map(); rosModel = null; }
  rosCache.clear(); defenseWeekCache.clear();
}
async function loadPriorContext() {
  try {
    const response = await fetch('/yahoo/nflverse-prior-2025.json', { cache: 'no-cache' });
    if (!response.ok) throw Error('Prior season unavailable');
    const data = await response.json();
    if (data.source !== 'nflverse' || data.season !== 2025 || !Array.isArray(data.players)) throw Error('Prior season invalid');
    priorSnapshot = data; priorPlayers = priorIndex(data);
    if (command) { renderPlan(); renderLeague(); }
  } catch { priorSnapshot = null; priorPlayers = null; }
}
$('connect').addEventListener('click', async () => {
  $('connect').disabled = true; status('Opening Yahoo’s sign-in page…');
  try {
    const r = await fetch('/.netlify/functions/yahoo-start', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await r.json(); if (!r.ok) throw { code: data.error };
    const url = new URL(data.authorizationUrl);
    if (url.origin !== 'https://api.login.yahoo.com' || url.pathname !== '/oauth2/request_auth') throw Error('Invalid destination');
    location.assign(url.href);
  } catch (e) { error(e); $('connect').disabled = false; }
});
$('disconnect').addEventListener('click', async () => {
  clearData(); $('disconnect').disabled = true;
  try { await request('disconnect'); connected(false); status('Disconnected. Displayed Yahoo data was cleared.'); }
  catch (e) { error(e); } finally { $('disconnect').disabled = false; }
});
$('refresh').addEventListener('click', refresh);
$('team').addEventListener('change', () => { generation++; controller?.abort(); clearWorkspace(); $('load').disabled = !$('team').value; });
$('load').addEventListener('click', loadLeague);
document.querySelectorAll('button[data-view]').forEach(b => b.addEventListener('click', () => selectView(b.dataset.view)));
document.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => selectView(b.dataset.go)));
document.querySelectorAll('.chip[data-pos]').forEach(chip => chip.addEventListener('click', () => {
  pickupPosition = chip.dataset.pos;
  document.querySelectorAll('.chip[data-pos]').forEach(c => c.setAttribute('aria-pressed', String(c === chip)));
  resetCandidates(); findPlayers();
}));
$('more-adds').addEventListener('click', () => { addsShown += 6; renderAdds(); });
$('tray-clear').addEventListener('click', () => { comparePicks = []; renderCompare(); });
$('clear-keeps').addEventListener('click', () => { keeps = new Set(); applyKeeps(); });
$('player-search').addEventListener('input', renderSearch);
async function init() {
  const reason = new URL(location.href).searchParams.get('error');
  selectView(location.hash.slice(1), false);
  const publicReady = loadPublicContext();
  // Estimates depend on both public files; wait for them so rankings never change under the reader.
  contextReady = Promise.allSettled([publicReady, loadPriorContext(), loadRosContext()]);
  if (location.origin !== 'https://overadp.com') {
    connected(false); $('connect').disabled = true;
    if (new URL(location.href).searchParams.get('demo') === '1' && /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(location.origin)) {
      await publicReady;
      const { buildDemo } = await import('./demo-fixture.mjs');
      demo = buildDemo(publicSnapshot); connected(true); await teams();
      return;
    }
    status('Preview only. Yahoo sign-in works on overadp.com. No live league data has been loaded.');
    return;
  }
  try {
    const s = await request('status'); connected(s.connected);
    if (s.connected) await teams(); else if (reason) status(messages[reason] || 'Yahoo could not finish authorization. Please try again.', true);
  } catch (e) { connected(false); error(e); if (e.code === 'NOT_CONFIGURED') $('connect').disabled = true; }
}
window.addEventListener('pagehide', clearData);
window.addEventListener('pageshow', e => { if (e.persisted) init(); });
init();
