import { positionSummary, rosterNeeds, pickupCandidates, mergeAvailablePages, availability, isBench, isStarter, canFill } from './insights.mjs';
import { indexPublicPlayers, matchPublicPlayer, publicSummary, publicInjuryNote, normalTeam, formatKickoff } from './public-context.mjs';
import { scorePlayer } from './league-scoring.mjs';
import { priorIndex, matchPrior, estimatePlayer, optimizeLineup, candidateImpact } from './weekly-advice.mjs';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = String(text); if (cls) n.className = cls; return n; };
const fmt = n => Number.isFinite(n) ? n.toFixed(1) : 'Unavailable';
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
let generation = 0, controller, expiry, command = null, page = 0, availableGeneration = 0, availableController;
let loadedCandidates = [];
let cooldownUntil = 0, rateLimitCount = 0;
let publicSnapshot = null, publicIndex = new Map(), priorSnapshot = null, priorPlayers = null;
function publicCurrent() {
  return publicSnapshot && Number(command?.league?.season) === publicSnapshot.season &&
    publicSnapshot.nextWeek === command?.league?.currentWeek &&
    Number.isFinite(Date.parse(publicSnapshot.generatedAt)) &&
    Date.now() - Date.parse(publicSnapshot.generatedAt) <= 48 * 3600000;
}
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
async function loadJevPublicContext() {
  try {
    const response = await fetch('/yahoo/jev-public-2026.json', { cache: 'no-cache' });
    if (!response.ok) throw Error('Jev public snapshot unavailable');
    const data = await response.json();
    if (data.source !== 'Jev analysis of public nflverse data only' || data.season !== 2026 || data.week !== 3) throw Error('Jev public snapshot invalid');
    const choices = Object.values(data.decisions || {});
    const uncertain = choices.filter(value => value === 'uncertain').length;
    $('jev-coverage').textContent = `Jev public-only Week ${data.week} review: ${uncertain}/${choices.length} games uncertain with two weeks of evidence · not used to rank your lineup`;
    $('jev-note').textContent = `Jev's public-only review found ${uncertain} of ${choices.length} games too uncertain to adjust the lineup estimate. It never receives your Yahoo roster.`;
  } catch {
    $('jev-coverage').textContent = 'Independent Jev context unavailable; no AI result is assumed.';
    $('jev-note').textContent = 'Jev public context is unavailable; no AI adjustment is assumed.';
  }
}
function publicMatch(player) { return publicSnapshot?.season === Number(command?.league?.season) ? matchPublicPlayer(player, publicIndex) : null; }
async function loadPublicContext() {
  try {
    const response = await fetch('/yahoo/nflverse-2026.json', { cache: 'no-cache' });
    if (!response.ok) throw Error('Public snapshot unavailable');
    const data = await response.json();
    if (data.source !== 'nflverse' || data.season !== 2026 || !Array.isArray(data.players)) throw Error('Public snapshot invalid');
    publicSnapshot = data; publicIndex = indexPublicPlayers(data);
    populateJevPlayers();
    const ageHours = (Date.now() - Date.parse(data.generatedAt)) / 3600000;
    const stale = !Number.isFinite(ageHours) || ageHours > 48;
    $('public-coverage').textContent = `Independent nflverse 2026: Weeks 1–${data.latestCompletedWeek} actuals · Week ${data.nextWeek} schedule · ${data.players.length} players · snapshot ${new Date(data.generatedAt).toLocaleString()}${stale ? ' · STALE: verify current status in Yahoo' : ''}`;
    if (command) { renderRoster(); renderComparison(); }
  } catch {
    $('public-coverage').textContent = 'Independent nflverse context unavailable. Yahoo roster information remains usable.';
    $('jev-status').textContent = 'Public player list unavailable. Please try again later.';
  }
}
async function loadPriorContext() {
  try {
    const response = await fetch('/yahoo/nflverse-prior-2025.json', { cache: 'no-cache' });
    if (!response.ok) throw Error('Prior season unavailable');
    const data = await response.json();
    if (data.source !== 'nflverse' || data.season !== 2025 || !Array.isArray(data.players)) throw Error('Prior season invalid');
    priorSnapshot = data; priorPlayers = priorIndex(data);
    if (command) { renderRoster(); renderComparison(); }
  } catch { priorSnapshot = null; priorPlayers = null; }
}
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
function resetCandidates() {
  availableGeneration++; availableController?.abort(); availableController = null; page = 0;
  loadedCandidates = [];
  $('candidates').replaceChildren(); $('previous').hidden = true; $('next').hidden = true; $('find').disabled = false;
  $('pickup-status').textContent = 'Choose a position or find available players.';
}
function clearWorkspace() {
  command = null; document.body.classList.remove('loaded'); resetCandidates(); $('workspace').hidden = true; $('empty').hidden = false;
  for (const id of ['comparison', 'roster', 'needs', 'swaps', 'weekly-lineup', 'settings', 'league-heading', 'coverage', 'warnings']) $(id).replaceChildren();
}
function clearData() {
  generation++; controller?.abort(); controller = null; clearTimeout(expiry); clearWorkspace();
  $('team').replaceChildren(new Option('Select your team', '')); $('teams-section').hidden = true; $('load').disabled = true;
}
function connected(on) {
  document.body.classList.toggle('connected', on);
  $('connect').hidden = on; $('disconnect').hidden = !on; $('refresh').hidden = !on;
  if (!on) { clearData(); $('empty-message').textContent = 'Connect Yahoo to see your lineup, available players, and league comparison.'; }
}
function setExpiry(timestamp) {
  if (!Number.isFinite(timestamp)) return;
  clearTimeout(expiry);
  expiry = setTimeout(() => { connected(false); status('Your Yahoo session expired. The displayed league information was cleared.'); }, Math.max(0, timestamp - Date.now()));
}
async function request(action, extra = {}, signal) {
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
function error(e) {
  if (e.name === 'AbortError') return;
  if (e.code === 'SESSION_EXPIRED') connected(false);
  const message = e.code === 'YAHOO_RATE_LIMIT' ? 'Yahoo is limiting requests. Try again after ' + new Date(cooldownUntil).toLocaleTimeString() + '.'
    : e.code === 'YAHOO_ACCESS_DENIED' && Object.hasOwn(denialMessages, e.diagnostic) ? denialMessages[e.diagnostic]
    : messages[e.code] || 'Yahoo could not finish this read. Missing information has not been treated as zero.';
  status(message, true); return message;
}
async function teams() {
  clearData(); const id = generation; controller = new AbortController(); $('refresh').disabled = true;
  status('Reading your current Yahoo football teams…');
  $('empty-message').textContent = 'Opening your league…';
  try {
    const data = await request('teams', {}, controller.signal); if (id !== generation) return;
    for (const team of data.teams) $('team').append(new Option(team.name + ' · league ' + team.leagueKey.split('.l.')[1], team.teamKey));
    $('teams-section').hidden = data.teams.length <= 1;
    if (data.teams.length === 1) {
      $('team').value = data.teams[0].teamKey;
      $('refresh').disabled = false;
      await loadLeague();
    } else if (data.teams.length > 1) {
      $('empty-message').textContent = 'Choose your team above to open your lineup, available players, and league comparison.';
      status('Connected. Choose the team you want to review.');
    } else {
      $('empty-message').textContent = 'No current NFL team was found for this Yahoo account.';
      status('Connected, but Yahoo returned no current NFL teams for this account.');
    }
  } catch (e) { if (id === generation) { $('empty-message').textContent = 'Could not load your Yahoo teams. Try Refresh teams.'; error(e); } }
  finally { if (id === generation) $('refresh').disabled = false; }
}
function makeTable(headings, rows, compact = false) {
  const wrap = el('div', null, 'table-wrap' + (compact ? ' compact' : '')), table = el('table');
  const head = el('thead'), tr = el('tr');
  for (const h of headings) { const th = el('th', h); th.scope = 'col'; tr.append(th); }
  head.append(tr); table.append(head); const body = el('tbody');
  for (const { cells, mine } of rows) {
    const row = el('tr', null, mine ? 'you' : '');
    for (const v of cells) { const td = el('td'); if (v instanceof Node) td.append(v); else td.textContent = v == null || v === '' ? 'Unavailable' : String(v); row.append(td); }
    body.append(row);
  }
  table.append(body); wrap.append(table); return wrap;
}
function playerList(players, available) {
  const list = el('div', null, 'player-list');
  if (!available) return el('span', 'Lineup unavailable', 'muted');
  if (!players.length) return el('span', 'None selected', 'muted');
  for (const p of players) {
    const row = el('div', p.name), flag = availability(p, command.league.currentWeek);
    row.append(el('small', p.slot + (flag.caution ? ' · ' + flag.label : ''))); list.append(row);
  }
  return list;
}
function playerCard(player, { candidate = false, reason = '', impact = null, sortMode = 'gain' } = {}) {
  const pub = publicMatch(player), score = actualScore(player), state = availability(player, command.league.currentWeek);
  const card = el('article', null, 'player-card' + (state.caution ? ' player-alert' : ''));
  const top = el('div', null, 'player-top'), who = el('div');
  who.append(el('strong', player.name), el('span', `${player.position} · ${player.team || 'NFL team not reported'}${candidate ? '' : ` · ${player.slot || 'Slot unknown'}`}`, 'player-meta'));
  const scoreBox = el('div', null, 'score-box');
  const pastPoints = Number.isFinite(score?.points) ? fmt(score.points) : score?.partial && Number.isFinite(score.weekly?.[0]?.knownPoints) ? 'Partial' : '—';
  if (candidate && sortMode === 'gain') {
    scoreBox.append(el('strong', Number.isFinite(impact?.gain) ? `${impact.gain >= 0 ? '+' : ''}${fmt(impact.gain)}` : '—'));
    scoreBox.append(el('small', 'est. lineup gain'));
  } else {
    scoreBox.append(el('strong', pastPoints));
    scoreBox.append(el('small', candidate ? 'past points' : Number.isFinite(score?.points) ? `${score.games} game${score.games === 1 ? '' : 's'} · through W${publicSnapshot.latestCompletedWeek}` : score?.partial ? 'incomplete scoring' : 'no verified score'));
  }
  top.append(who, scoreBox); card.append(top);
  if (candidate) card.append(el('p', sortMode === 'gain'
    ? `Past points: ${pastPoints}${Number.isFinite(score?.points) ? ` through Week ${publicSnapshot.latestCompletedWeek}` : ''}`
    : `Estimated lineup gain: ${Number.isFinite(impact?.gain) ? `${impact.gain >= 0 ? '+' : ''}${fmt(impact.gain)}` : 'unavailable'}`, 'schedule-line'));
  if (state.caution) card.append(el('span', `Yahoo: ${state.label}`, state.blocked ? 'status-blocked flag' : 'status-caution flag'));
  if (candidate) card.append(el('span', player.ownership === 'waivers' ? `Waivers${player.waiverDate ? ` · ${player.waiverDate}` : ''}` : 'Free agent', 'availability-pill'));
  const nextGame = pub?.nextGame || publicSnapshot?.schedule?.[normalTeam(player.team)];
  if (nextGame) card.append(el('p', `Next: vs ${nextGame.opponent} · ${formatKickoff(nextGame) || 'kickoff unavailable'}`, 'schedule-line'));
  if (reason) card.append(el('p', reason, 'card-reason'));
  const details = el('details', null, 'player-detail'); details.append(el('summary', 'Recent stats and scoring detail'));
  details.append(el('p', pub ? publicSummary(pub, publicSnapshot) : player.position === 'DEF' ? 'Team defense stats are incomplete; points allowed cannot be verified here.' : 'No exact public name, team and position match.'));
  if (score?.weekly?.length) details.append(el('p', score.weekly.map(w => `Week ${w.week}: ${Number.isFinite(w.points) ? fmt(w.points) : 'incomplete'} league pts`).join(' · ')));
  if (score?.partial && score.reason) details.append(el('p', `Score incomplete: ${score.reason}. Do not compare as a full total.`, 'warning-text'));
  const injury = publicInjuryNote(pub, publicSnapshot); if (injury) details.append(el('p', injury, 'history-note'));
  card.append(details); return card;
}
function ownTeam() { return command?.teams.find(t => t.teamKey === command.team.teamKey); }
function renderComparison() {
  if (!command) return;
  const pos = $('compare-position').value;
  const summaries = command.teams.map(team => {
    const s = positionSummary(team, pos, command.league.season, p => weekly(p).points);
    return { team, score: s.total, missing: s.missing, starters: s.starters.length };
  });
  const mine = summaries.find(item => item.team.teamKey === command.team.teamKey);
  const comparable = summaries.filter(item => Number.isFinite(item.score) && item.starters === mine?.starters);
  const sorted = [...comparable].sort((a, b) => b.score - a.score);
  const rank = sorted.findIndex(item => item.team.teamKey === command.team.teamKey) + 1;
  const box = el('div', null, 'comparison-summary');
  box.append(el('strong', rank ? `#${rank} of ${sorted.length}` : 'Not rankable', 'comparison-rank'));
  box.append(el('p', `Your ${pos === 'ALL' ? 'current starters' : pos + ' starters'}: ${Number.isFinite(mine?.score) ? fmt(mine.score) + ' provisional points' : 'incomplete estimate'}. ${mine?.starters ?? 0} slot${mine?.starters === 1 ? '' : 's'} represented.`));
  box.append(el('p', `${sorted.length} of ${summaries.length} teams have the same number of starters and complete public scoring in this view. Other teams' rosters are not displayed.`, 'fine'));
  if (pos === 'DEF') box.append(el('p', 'Public defense scoring is incomplete in this league. No defensive rank is inferred.', 'warning'));
  $('comparison').replaceChildren(box);
}
function renderWeekly(mine) {
  const target = $('weekly-lineup');
  if (!mine?.rosterAvailable || !publicCurrent()) {
    target.replaceChildren(el('p', 'A fresh, verified current-week public schedule and roster are needed for lineup advice. No stale recommendation is shown.')); return;
  }
  const result = optimizeLineup(mine, command.league, weekly);
  const list = el('div', null, 'lineup-rows');
  for (const item of result.assignments) {
    const row = el('div', null, 'lineup-row');
    row.append(el('span', item.slot, 'slot-badge'));
    const person = el('div'), name = el('strong', item.player?.name || 'EMPTY');
    person.append(name);
    if (item.estimate?.caution) person.append(el('small', `Status: ${item.estimate.reason}`, 'status-caution'));
    else if (item.estimate?.basis) person.append(el('small', item.estimate.basis, 'estimate-basis'));
    row.append(person);
    row.append(el('span', Number.isFinite(item.estimate?.points) ? `${fmt(item.estimate.points)} est.` : 'No estimate', 'numeric'));
    list.append(row);
  }
  const explanation = el('p', null, 'fine');
  explanation.textContent = `${result.moves.length ? result.moves.map(move => `${move.player.name} into ${move.slot}${move.replaces ? ` over ${move.replaces.name}` : ' (empty slot)'}`).join('; ') + '. ' : 'No clear eligible change beyond status checks. '}${result.unknown ? `${result.unknown} slot(s) lack complete scoring; no full team total shown.` : `Known estimated starter sum ${fmt(result.knownPoints)}.`}`;
  const cautions = result.assignments.filter(item => item.estimate?.caution);
  const contingencies = cautions.map(item => {
    const alternate = optimizeLineup(mine, command.league, p => p.playerKey === item.player.playerKey
      ? { ...weekly(p), playable: false } : weekly(p));
    if (alternate.assignments.some(x => x.player?.playerKey === item.player.playerKey))
      return `${item.player.name} is already locked in this slot; a lineup change is no longer assumed possible.`;
    const currentKeys = new Set(result.assignments.map(x => x.player?.playerKey).filter(Boolean));
    const added = alternate.assignments.filter(x => x.player && !currentKeys.has(x.player.playerKey));
    if (!added.length) return `${item.player.name}: no eligible healthy roster replacement was found. Check waivers.`;
    const first = [...added].sort((a, b) => (a.estimate?.kickoff ?? Infinity) - (b.estimate?.kickoff ?? Infinity))[0];
    const game = publicMatch(first.player)?.nextGame || publicSnapshot.schedule?.[normalTeam(first.player.team)];
    const deadline = game ? formatKickoff(game) : null;
    const early = Number.isFinite(first.estimate?.kickoff) && first.estimate.kickoff < item.estimate.kickoff;
    return `${item.player.name} unavailable → bring in ${added.map(x => `${x.player.name} (${x.slot})`).join(', ')}.${early && deadline ? ` Decide before ${deadline}, when your alternative locks.` : ' Verify the alternative before kickoff.'}`;
  });
  target.replaceChildren(list, explanation,
    ...(cautions.length ? [el('p', `${cautions.map(item => item.player.name).join(', ')}: this plan is conditional on playing. Verify status before each kickoff.`, 'warning')] : []),
    ...contingencies.map(note => el('p', note, 'contingency')));
}
function renderRoster() {
  const mine = ownTeam(), needs = rosterNeeds(mine, command.league);
  const list = el('ul', null, 'need-list');
  needs.forEach(n => list.append(el('li', n.text)));
  $('needs').replaceChildren(!mine.rosterAvailable ? el('p', 'Your lineup could not be loaded. Needs have not been assessed.')
    : needs.length ? list : el('p', 'No unfilled slots or status/bye flags found in the returned current lineup. This does not confirm every starter will play.'));
  renderWeekly(mine);
  const flagged = mine.rosterAvailable ? mine.roster.filter(p => isStarter(p) && availability(p, command.league.currentWeek).caution) : [];
  const swaps = el('div', null, 'swap-list');
  for (const starter of flagged) {
    const options = mine.roster.filter(p => isBench(p) && canFill(p, starter.slot) && !availability(p, command.league.currentWeek).caution);
    const risky = mine.roster.filter(p => isBench(p) && canFill(p, starter.slot) && availability(p, command.league.currentWeek).caution && !availability(p, command.league.currentWeek).blocked);
    const card = el('div', null, 'swap-item');
    const state = availability(starter, command.league.currentWeek);
    card.append(el('strong', `${state.blocked ? 'Sit or replace' : 'Monitor'} ${starter.name} · Yahoo ${state.label}`));
    card.append(el('p', options.length ? `Unflagged eligible bench cover: ${options.map(p => p.name).join(', ')}.` : 'No unflagged eligible bench cover was returned. Review the waiver list.'));
    if (risky.length) card.append(el('p', `Also eligible but status-flagged: ${risky.map(p => `${p.name} (${availability(p, command.league.currentWeek).label})`).join(', ')}. Verify before kickoff.`));
    const look = el('button', `Check ${starter.slot} options`, 'text-button'); look.addEventListener('click', () => searchNeed(starter.slot)); card.append(look);
    swaps.append(card);
  }
  for (const need of needs.filter(n => n.type === 'empty')) {
    const options = mine.roster.filter(p => isBench(p) && canFill(p, need.slot) && !availability(p, command.league.currentWeek).caution);
    const risky = mine.roster.filter(p => isBench(p) && canFill(p, need.slot) && availability(p, command.league.currentWeek).caution && !availability(p, command.league.currentWeek).blocked);
    const card = el('div', null, 'swap-item');
    card.append(el('strong', `${need.slot} starting slot empty`));
    card.append(el('p', options.length ? `Unflagged eligible bench option${options.length === 1 ? '' : 's'}: ${options.map(p => p.name).join(', ')}.` : `No unflagged bench cover. Review ${need.slot}-eligible waivers before kickoff.`));
    if (risky.length) card.append(el('p', `Status-flagged option${risky.length === 1 ? '' : 's'}: ${risky.map(p => `${p.name} (${availability(p, command.league.currentWeek).label})`).join(', ')}. Do not rely on availability without confirmation.`));
    const look = el('button', `Check ${need.slot} options`, 'text-button'); look.addEventListener('click', () => searchNeed(need.slot)); card.append(look);
    swaps.append(card);
  }
  $('swaps').replaceChildren(!mine.rosterAvailable ? el('p', 'Lineup unavailable.') : swaps.childElementCount ? swaps : el('p', 'No flagged starter or empty starting slot requires an immediate cover review. Monitor statuses before each kickoff.'));
  const roster = el('div', null, 'roster-groups');
  for (const [label, members] of [['Starting', mine.roster.filter(isStarter)], ['Bench & reserve', mine.roster.filter(isBench)]]) {
    const group = el('section'); group.append(el('h3', `${label} · ${members.length}`));
    const grid = el('div', null, 'player-grid'); members.forEach(p => grid.append(playerCard(p))); group.append(grid); roster.append(group);
  }
  $('roster').replaceChildren(mine.rosterAvailable ? roster : el('p', 'Roster unavailable.'));
  const setup = makeTable(['Slot', 'Required'], command.league.positions.map(p => ({ cells: [p.position, p.count] })), true);
  const scoring = el('details', null, 'method'); scoring.append(el('summary', 'See league scoring'));
  scoring.append(makeTable(['Category', 'Points'], command.league.scoring.map(s => ({ cells: [s.name, s.value] })), true));
  $('settings').replaceChildren(setup, scoring);
}
function renderCommand() {
  document.body.classList.add('loaded');
  $('league-heading').replaceChildren(el('h2', command.league.name), el('p', command.team.name + ' · ' + command.league.season + ' · Week ' + command.league.currentWeek + ' · ' + command.league.scoringType, 'fine'));
  const c = command.coverage;
  $('coverage').textContent = c.returnedTeams + ' of ' + (c.expectedTeams ?? 'unknown') + ' teams · ' + c.rosterTeams + ' lineups loaded · Read ' + new Date(command.fetchedAt).toLocaleString();
  $('warnings').replaceChildren(...command.warnings.map(w => el('p', w, 'warning')));
  renderComparison(); renderRoster();
  const firstNeed = rosterNeeds(ownTeam(), command.league)[0]?.slot;
  $('pickup-position').value = ['QB','RB','WR','TE','K','DEF'].includes(firstNeed) ? firstNeed : 'ALL';
  $('workspace').hidden = false; $('empty').hidden = true; selectView('roster');
}
function selectView(view) {
  for (const button of document.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === view; button.setAttribute('aria-pressed', String(active)); $(button.dataset.view + '-view').hidden = !active;
  }
  if (view === 'pickups' && command && !$('candidates').childElementCount && !$('find').disabled) findPlayers(0);
}
function populateJevPlayers() {
  const position = $('jev-position').value;
  const players = (publicSnapshot?.players || []).filter(p => p.position === position && p.nextGame)
    .sort((a, b) => a.name.localeCompare(b.name));
  for (const id of ['jev-a', 'jev-b']) {
    $(id).replaceChildren(new Option('Choose a player', ''));
    for (const player of players) $(id).append(new Option(`${player.name} · ${player.team}`, player.id));
  }
  $('jev-status').textContent = players.length ? `${players.length} public ${position} players available for comparison.` : 'No public players available at this position.';
  $('jev-result').replaceChildren(); updateJevButton();
}
function updateJevButton() {
  $('jev-run').disabled = !publicSnapshot || !$('jev-a').value || !$('jev-b').value || $('jev-a').value === $('jev-b').value;
}
async function compareWithJev() {
  const input = { playerAId: $('jev-a').value, playerBId: $('jev-b').value, scoring: $('jev-scoring').value };
  if (!input.playerAId || !input.playerBId || input.playerAId === input.playerBId) return;
  $('jev-run').disabled = true; $('jev-result').replaceChildren(); $('jev-status').textContent = 'Asking Jev using public player data…';
  try {
    const response = await fetch('/.netlify/functions/jev-compare', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'JEV_UNAVAILABLE');
    const chosen = data.choice === 'a' ? data.players.a : data.choice === 'b' ? data.players.b : null;
    const card = el('div', null, 'jev-answer');
    card.append(el('strong', chosen ? `Jev leans: start ${chosen}` : 'Jev cannot make a defensible choice yet'));
    card.append(el('p', `Model decisiveness: ${Math.round(100 * data.confidence)}%. This is not the chance the pick will be right.`));
    card.append(el('p', `Evidence: ${data.evidence === 'stale' ? 'stale public snapshot' : data.evidence === 'limited' ? 'limited, early-season data or injury uncertainty' : 'moderate public sample'}. Public snapshot: ${new Date(data.snapshotAt).toLocaleString()}.`));
    if (data.historicalInjuryNotes?.length) card.append(el('p', data.historicalInjuryNotes.join(' · '), 'warning-text'));
    card.append(el('p', `Jev option weights: ${data.players.a} ${Math.round(100 * data.probabilities.a)}%, ${data.players.b} ${Math.round(100 * data.probabilities.b)}%, too uncertain ${Math.round(100 * data.probabilities.uncertain)}%. These are model weights, not calibrated outcome probabilities.`, 'fine'));
    $('jev-result').replaceChildren(card); $('jev-status').textContent = 'Comparison complete. Verify current player availability before acting.';
  } catch (e) {
    const explanations = { CONNECT_YAHOO_FIRST: 'Connect Yahoo again before comparing players.', STALE_PUBLIC_DATA: 'Public stats are stale. Refresh the nflverse snapshot before using this comparison.', JEV_NOT_CONFIGURED: 'Jev is not configured on the server yet.', JEV_UNAVAILABLE: 'Jev did not complete this comparison. Please try again later.' };
    $('jev-status').textContent = explanations[e.message] || 'Comparison unavailable. No recommendation was assumed.';
  } finally { updateJevButton(); }
}
function searchNeed(slot) {
  $('pool').value = 'BOTH';
  $('pickup-position').value = ['QB','RB','WR','TE','K','DEF'].includes(slot) ? slot : 'ALL';
  resetCandidates(); selectView('pickups');
}
async function loadLeague() {
  const id = ++generation; controller?.abort(); controller = new AbortController(); clearWorkspace(); $('load').disabled = true;
  status('Reading league settings, standings, and current lineups…');
  try {
    const data = await request('command', { teamKey: $('team').value }, controller.signal); if (id !== generation) return;
    command = data; renderCommand(); status('League loaded. Read-only, nothing in Yahoo was changed.');
  } catch (e) { if (id === generation) { $('teams-section').hidden = false; $('empty-message').textContent = 'Could not open this league. Try Open league again, or refresh your teams.'; error(e); } }
  finally { if (id === generation) $('load').disabled = !$('team').value; }
}
async function findPlayers(start = 0) {
  if (!command) return;
  availableController?.abort(); availableController = new AbortController();
  const id = ++availableGeneration, leagueGeneration = generation;
  const teamKey = command.team.teamKey, pool = $('pool').value, position = $('pickup-position').value;
  $('find').disabled = true; $('previous').hidden = true; $('next').hidden = true; $('candidates').replaceChildren();
  $('pickup-status').textContent = pool === 'BOTH' ? 'Checking free agents and waivers…' : 'Checking available players…';
  try {
    const pools = pool === 'BOTH' ? ['FA', 'W'] : [pool];
    const pages = [];
    for (const onePool of pools) {
      const d = await request('available', { teamKey, pool: onePool, position, start: pool === 'BOTH' ? 0 : start }, availableController.signal);
      if (id !== availableGeneration || leagueGeneration !== generation) return;
      if (d.teamKey !== teamKey || d.season !== command.league.season || d.pool !== onePool || d.position !== position) throw Error('Mismatched response');
      pages.push(d);
    }
    if (id !== availableGeneration || leagueGeneration !== generation) return;
    page = pool === 'BOTH' ? 0 : pages[0].start;
    const unique = mergeAvailablePages(pages);
    const ranked = pickupCandidates(unique, ownTeam(), command.league, actualScore);
    const lineup = optimizeLineup(ownTeam(), command.league, weekly);
    for (const candidate of ranked) {
      const projected = weekly(candidate.player);
      candidate.estimate = projected;
      candidate.impact = candidateImpact(candidate.player, lineup, projected);
      if (Number.isFinite(projected.points)) {
        candidate.reason += ` Provisional weekly estimate: ${fmt(projected.points)} points${projected.caution ? ', conditional on playing' : ''}.`;
        if (candidate.impact && Number.isFinite(candidate.impact.gain))
          candidate.reason += candidate.impact.replaced
            ? ` Compared with ${candidate.impact.replaced} at ${candidate.impact.slot}: ${candidate.impact.gain >= 0 ? '+' : ''}${fmt(candidate.impact.gain)} estimated points. This does not account for a required drop.`
            : ` Could fill the vacant ${candidate.impact.slot} slot.`;
      }
    }
    loadedCandidates = ranked;
    renderCandidateCards();
    const count = pages.map(d => `${d.players.length} ${d.pool === 'FA' ? 'free agents' : 'waiver players'}`).join(' + ');
    $('pickup-status').textContent = `${ranked.length} distinct players · ${count} · ${position === 'ALL' ? 'all positions' : position} · ${pool === 'BOTH' ? 'first 25 per pool' : `page ${page / 25 + 1}`} · Read ${new Date(pages.at(-1).fetchedAt).toLocaleTimeString()}${pages.some(d => d.limitReached) ? ' · Browse limit reached; narrow position.' : ''}`;
    $('previous').hidden = pool === 'BOTH' || page === 0; $('next').hidden = pool === 'BOTH' || !pages[0].hasMore;
  } catch (e) {
    if (id === availableGeneration && leagueGeneration === generation) {
      const message = error(e); if (message) $('pickup-status').textContent = message;
    }
  } finally { if (id === availableGeneration) $('find').disabled = false; }
}
function renderCandidateCards() {
  const mode = $('candidate-sort').value;
  $('candidate-sort-label').textContent = mode === 'past' ? 'Sorted by past points' : 'Sorted by estimated lineup gain';
  const sorted = [...loadedCandidates].sort((a, b) => mode === 'past'
    ? (b.points ?? -Infinity) - (a.points ?? -Infinity) || (b.impact?.gain ?? -Infinity) - (a.impact?.gain ?? -Infinity) || a.player.name.localeCompare(b.player.name)
    : (b.impact?.gain ?? -Infinity) - (a.impact?.gain ?? -Infinity) || b.priority - a.priority
      || (b.estimate?.points ?? -Infinity) - (a.estimate?.points ?? -Infinity) || a.player.name.localeCompare(b.player.name));
  const grid = el('div', null, 'player-grid candidate-grid');
  sorted.forEach(c => grid.append(playerCard(c.player, { candidate: true, reason: c.reason, impact: c.impact, sortMode: mode })));
  $('candidates').replaceChildren(sorted.length ? grid : el('div', 'Neither selected pool returned matching players on this page. Try another position or browse the individual pools.', 'empty-result'));
}
$('connect').addEventListener('click', async () => {
  $('connect').disabled = true; status('Opening Yahoo’s authorization page…');
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
$('compare-position').addEventListener('change', renderComparison);
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => selectView(button.dataset.view)));
$('find').addEventListener('click', () => findPlayers(0));
$('previous').addEventListener('click', () => findPlayers(Math.max(0, page - 25)));
$('next').addEventListener('click', () => findPlayers(page + 25));
$('pool').addEventListener('change', resetCandidates);
$('pickup-position').addEventListener('change', resetCandidates);
$('candidate-sort').addEventListener('change', renderCandidateCards);
$('jev-position').addEventListener('change', populateJevPlayers);
for (const id of ['jev-a', 'jev-b']) $(id).addEventListener('change', updateJevButton);
$('jev-run').addEventListener('click', compareWithJev);
async function init() {
  loadPublicContext();
  loadPriorContext();
  loadJevPublicContext();
  if (location.origin !== 'https://overadp.com') {
    connected(false); $('connect').disabled = true;
    if (new URL(location.href).searchParams.get('demo') === '1' && /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(location.origin)) {
      const { demoCommand } = await import('./demo-fixture.mjs');
      command = demoCommand; renderCommand(); status('SYNTHETIC LOCAL PREVIEW. No live Yahoo league data loaded.');
      return;
    }
    status('Preview only. Yahoo authorization will be available on overadp.com after review and publication. No live league data has been loaded.');
    return;
  }
  const reason = new URL(location.href).searchParams.get('error'); history.replaceState(null, '', '/yahoo/');
  try {
    const s = await request('status'); connected(s.connected);
    if (s.connected) await teams(); else status(reason ? messages[reason] || 'Yahoo could not finish authorization. Please try again.' : 'Not connected. Start with the button below.', Boolean(reason));
  } catch (e) { connected(false); error(e); if (e.code === 'NOT_CONFIGURED') $('connect').disabled = true; }
}
window.addEventListener('pagehide', clearData);
window.addEventListener('pageshow', e => { if (e.persisted) init(); });
init();
