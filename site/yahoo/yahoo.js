import { isBench, isStarter, pickupCandidates, mergeAvailablePages } from './insights.mjs';
import { indexPublicPlayers, matchPublicPlayer, normalTeam } from './public-context.mjs';
import { scorePlayer } from './league-scoring.mjs';
import { priorIndex, matchPrior, estimatePlayer, optimizeLineup, candidateImpact } from './weekly-advice.mjs';
import { yahooLinks, statusTag, gameLine, starterTotal, buildMoves, movesGain, positionRanks, tradeIdea, fantasyWeeks, availabilityShare, addValue, describeAdd, PLAYOFF_WEIGHT } from './hub.mjs';
import { rosPerGame } from './ros.mjs';
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
let candidates = [], pickupPosition = 'ALL', addsShown = 6, demo = null;
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
  return estimatePlayer(player, command.league, pub, prior);
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
  if (!r && ['K', 'DEF'].includes(pos)) { const e = weekly(p); r = Number.isFinite(e.points) ? { points: e.points, basis: e.basis } : null; }
  rosCache.set(key, r); return r;
}
function seasonPoints(p, week) { const r = rosPoints(p); return r ? r.points * availabilityShare(p, week, command.league.currentWeek) : 0; }
function nextGame(player) { return publicMatch(player)?.nextGame || publicSnapshot?.schedule?.[normalTeam(player.team)] || null; }
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
function error(e) {
  if (e.name === 'AbortError') return;
  if (e.code === 'SESSION_EXPIRED') connected(false);
  const message = e.code === 'YAHOO_RATE_LIMIT' ? 'Yahoo is limiting requests. Try again after ' + new Date(cooldownUntil).toLocaleTimeString() + '.'
    : e.code === 'YAHOO_ACCESS_DENIED' && Object.hasOwn(denialMessages, e.diagnostic) ? denialMessages[e.diagnostic]
    : messages[e.code] || 'Yahoo could not finish this read. Missing information has not been treated as zero.';
  status(message, true); return message;
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
  command = null; document.body.classList.remove('loaded'); resetCandidates();
  $('hub').hidden = true; $('tabbar').hidden = true;
  for (const id of ['matchup', 'moves', 'glance', 'starters', 'bench', 'ranks', 'trade', 'settings', 'warnings']) $(id).replaceChildren();
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
async function request(action, extra = {}, signal) {
  if (demo) return action === 'command' ? demo.command : action === 'teams' ? { teams: demo.teams } : demo.available(extra);
  if (action !== 'disconnect' && Date.now() < cooldownUntil) throw { code: 'YAHOO_RATE_LIMIT' };
  const r = await fetch('/.netlify/functions/yahoo-api', { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...extra }) });
  const body = await r.json();
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
  const moves = lineup ? buildMoves({ team: mine, league: command.league, lineup, estimate: weekly, pickups: rankedCandidates(), links: yahooLinks(mine.teamKey) }) : [];
  return { mine, lineup, moves, fresh };
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
    top.append(el('span', m.kind === 'lineup' ? 'Start / sit' : m.kind === 'pickup' ? 'Pick up' : 'Watch', 'kind ' + m.kind), el('span', m.impact, 'impact'));
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
  $('starters').replaceChildren(...starters.map(p => playerRow(p, { extraTag: outgoing.has(p.playerKey) ? { text: 'SIT', tone: 'bad' } : null })));
  $('bench').replaceChildren(...(bench.length ? bench.map(p => playerRow(p, { extraTag: incoming.has(p.playerKey) ? { text: 'START', tone: 'good' } : null }))
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
  const { mine, lineup, moves, fresh } = plan();
  renderMatchup(mine, moves); renderMoves(moves, fresh); renderLineup(mine, lineup);
}
function selectView(view) {
  document.body.dataset.view = view;
  for (const b of document.querySelectorAll('button[data-view]')) b.setAttribute('aria-pressed', String(b.dataset.view === view));
  window.scrollTo({ top: 0 });
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
    let why = c.ros ? describeAdd(c.ros) : isDef ? "Defenses aren't ranked: points allowed can't be scored from public stats."
      : c.estimate?.playable === false && c.estimate?.reason ? c.estimate.reason : 'No rest-of-season estimate for this player yet.';
    if (Number.isFinite(c.impact?.gain) && c.impact.gain > 0 && c.impact.replaced) why += ` This week: +${fmt(c.impact.gain)} over ${c.impact.replaced}.`;
    const foot = el('div', null, 'add-foot'), dropText = el('span');
    if (helps && c.ros.drop) dropText.append('Drop ', el('strong', c.ros.drop.name), c.ros.dropStarts ? ` (starts ${c.ros.dropStarts} wk${c.ros.dropStarts === 1 ? '' : 's'})` : ' (never starts)');
    else dropText.textContent = helps ? 'You have an open roster spot' : '';
    foot.append(dropText, yahooButton(p.ownership === 'waivers' ? 'Claim' : 'Add', links.add(p.playerKey) || links.league));
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
  try {
    const pages = [];
    for (const pool of ['FA', 'W']) {
      const d = await request('available', { teamKey, pool, position, start: 0 }, availableController.signal);
      if (id !== availableGeneration || leagueGeneration !== generation) return;
      if (d.teamKey !== teamKey || d.season !== command.league.season || d.pool !== pool || d.position !== position) throw Error('Mismatched response');
      pages.push(d);
    }
    const mine = ownTeam(), lineup = publicCurrent() ? optimizeLineup(mine, command.league, weekly) : null;
    const weeks = fantasyWeeks(command.league);
    mine.roster.forEach(rosPoints);
    candidates = pickupCandidates(mergeAvailablePages(pages), mine, command.league, actualScore).map(c => {
      const estimate = weekly(c.player), r = rosPoints(c.player);
      return { ...c, estimate, impact: lineup ? candidateImpact(c.player, lineup, estimate) : null, rosPg: r?.points ?? null, rosBasis: r?.basis || null,
        ros: r && mine.rosterAvailable && weeks.length ? addValue({ roster: mine.roster, candidate: c.player, league: command.league, weeks, value: seasonPoints }) : null };
    });
    addsShown = 6; renderAdds();
    $('pickup-status').textContent = `${candidates.length} available ${position === 'ALL' ? 'players' : position + 's'} checked · read ${new Date(pages.at(-1).fetchedAt).toLocaleTimeString()}`;
    if (position === 'ALL') renderPlan();
  } catch (e) {
    if (id === availableGeneration && leagueGeneration === generation) { const message = error(e); if (message) $('pickup-status').textContent = message; }
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
  finally { if (id === generation) $('refresh').disabled = false; }
}
async function loadLeague() {
  const id = ++generation; controller?.abort(); controller = new AbortController(); clearWorkspace(); $('load').disabled = true;
  status('Reading your league, lineup and matchup…');
  try {
    const data = await request('command', { teamKey: $('team').value }, controller.signal);
    await contextReady; if (id !== generation) return;
    command = data; rosCache.clear(); renderCommand(); status(demo ? 'SYNTHETIC LOCAL PREVIEW. No live Yahoo league data loaded.' : '');
    findPlayers();
  } catch (e) { if (id === generation) { $('teams-section').hidden = false; error(e); } }
  finally { if (id === generation) $('load').disabled = !$('team').value; }
}

function populateJevPlayers() {
  const position = $('jev-position').value;
  const players = (publicSnapshot?.players || []).filter(p => p.position === position && p.nextGame).sort((a, b) => a.name.localeCompare(b.name));
  for (const id of ['jev-a', 'jev-b']) {
    $(id).replaceChildren(new Option('Choose a player', ''));
    for (const player of players) $(id).append(new Option(`${player.name} · ${player.team}`, player.id));
  }
  $('jev-status').textContent = players.length ? '' : 'No public players available at this position.';
  $('jev-result').replaceChildren(); updateJevButton();
}
function updateJevButton() { $('jev-run').disabled = !publicSnapshot || !$('jev-a').value || !$('jev-b').value || $('jev-a').value === $('jev-b').value; }
async function compareWithJev() {
  const input = { playerAId: $('jev-a').value, playerBId: $('jev-b').value, scoring: $('jev-scoring').value };
  if (!input.playerAId || !input.playerBId || input.playerAId === input.playerBId) return;
  $('jev-run').disabled = true; $('jev-result').replaceChildren(); $('jev-status').textContent = 'Asking Jev…';
  try {
    const response = await fetch('/.netlify/functions/jev-compare', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'JEV_UNAVAILABLE');
    const chosen = data.choice === 'a' ? data.players.a : data.choice === 'b' ? data.players.b : null;
    const card = el('div', null, 'jev-answer');
    card.append(el('strong', chosen ? `Jev leans: start ${chosen}` : 'Too close to call with the data so far'));
    card.append(el('p', `${data.evidence === 'stale' ? 'Public stats are out of date.' : data.evidence === 'limited' ? 'Early-season or injury uncertainty, so treat this as a lean.' : 'Based on a moderate public sample.'} Decisiveness ${Math.round(100 * data.confidence)}%, which is not a win probability.`));
    if (data.historicalInjuryNotes?.length) card.append(el('p', data.historicalInjuryNotes.join(' · '), 'warning-text'));
    $('jev-result').replaceChildren(card); $('jev-status').textContent = 'Confirm injury status in Yahoo before kickoff.';
  } catch (e) {
    const explanations = { CONNECT_YAHOO_FIRST: 'Connect Yahoo again before comparing players.', STALE_PUBLIC_DATA: 'Public stats are stale, so Jev is paused until they update.', JEV_NOT_CONFIGURED: 'Jev is not configured on the server yet.', JEV_UNAVAILABLE: 'Jev did not finish this comparison. Please try again later.' };
    $('jev-status').textContent = explanations[e.message] || 'Comparison unavailable. No recommendation was assumed.';
  } finally { updateJevButton(); }
}
async function loadPublicContext() {
  try {
    const response = await fetch('/yahoo/nflverse-2026.json', { cache: 'no-cache' });
    if (!response.ok) throw Error('Public snapshot unavailable');
    const data = await response.json();
    if (data.source !== 'nflverse' || data.season !== 2026 || !Array.isArray(data.players)) throw Error('Public snapshot invalid');
    publicSnapshot = data; publicIndex = indexPublicPlayers(data); populateJevPlayers();
    const ageHours = (Date.now() - Date.parse(data.generatedAt)) / 3600000;
    $('public-coverage').textContent = `Public stats: nflverse through Week ${data.latestCompletedWeek} · updated ${new Date(data.generatedAt).toLocaleString()}${!Number.isFinite(ageHours) || ageHours > 48 ? ' · out of date, estimates paused' : ''}`;
    if (command) { renderPlan(); renderLeague(); }
  } catch {
    $('public-coverage').textContent = 'Public stats unavailable. Yahoo roster information remains usable.';
    $('jev-status').textContent = 'Public player list unavailable. Please try again later.';
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
  rosCache.clear();
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
$('refresh').addEventListener('click', teams);
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
$('jev-position').addEventListener('change', populateJevPlayers);
for (const id of ['jev-a', 'jev-b']) $(id).addEventListener('change', updateJevButton);
$('jev-run').addEventListener('click', compareWithJev);
async function init() {
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
  const reason = new URL(location.href).searchParams.get('error'); history.replaceState(null, '', '/yahoo/');
  try {
    const s = await request('status'); connected(s.connected);
    if (s.connected) await teams(); else if (reason) status(messages[reason] || 'Yahoo could not finish authorization. Please try again.', true);
  } catch (e) { connected(false); error(e); if (e.code === 'NOT_CONFIGURED') $('connect').disabled = true; }
}
window.addEventListener('pagehide', clearData);
window.addEventListener('pageshow', e => { if (e.persisted) init(); });
init();
