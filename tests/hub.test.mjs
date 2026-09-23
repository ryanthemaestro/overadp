import test from 'node:test';
import assert from 'node:assert/strict';
import { yahooLinks, statusTag, gameLine, starterTotal, dropCandidate, buildMoves, movesGain, positionRanks, tradeIdea } from '../site/yahoo/hub.mjs';
import { optimizeLineup } from '../site/yahoo/weekly-advice.mjs';

// Synthetic league: 1 QB, 2 RB, 1 WR, 1 FLEX, 3 bench, 1 IR.
const league = { season: '2026', currentWeek: 3, positions: ['QB:1', 'RB:2', 'WR:1', 'W/R/T:1', 'BN:3', 'IR:1']
  .map(x => ({ position: x.split(':')[0], count: x.split(':')[1] })) };
let n = 1;
const P = (name, position, slot, status = '') => ({ name, position, slot, status, playerKey: `461.p.${n++}`, eligible: [position], team: 'KC', byeWeek: null });
const points = { QB1: 20, RB1: 15, RB2: 9, RBbench: 11, WR1: 12, FLEX1: 10, WRbench: 6, TEbench: 3, IRguy: 14 };
const estimateFor = (overrides = {}) => p => {
  const pts = overrides[p.name] ?? points[p.name];
  const out = ['O', 'D'].includes(p.status) || p.slot === 'IR';
  return { points: out ? null : pts ?? null, playable: !out && pts != null, locked: false, kickoff: 2e12, basis: '2025 + 2026 games', caution: p.status === 'Q' };
};
function team(statuses = {}) {
  n = 1;
  return { teamKey: '461.l.555.t.3', name: 'Mine', rosterAvailable: true, roster: [
    P('QB1', 'QB', 'QB', statuses.QB1), P('RB1', 'RB', 'RB', statuses.RB1), P('RB2', 'RB', 'RB', statuses.RB2),
    P('WR1', 'WR', 'WR', statuses.WR1), P('FLEX1', 'WR', 'W/R/T'), P('RBbench', 'RB', 'BN'), P('WRbench', 'WR', 'BN'),
    P('TEbench', 'TE', 'BN'), P('IRguy', 'RB', 'IR') ] };
}
const movesFor = (t, estimate, pickups = [], drop = null) =>
  buildMoves({ team: t, league, lineup: optimizeLineup(t, league, estimate, 0), estimate, pickups, drop });

test('Yahoo links are built only from well-formed keys', () => {
  const links = yahooLinks('461.l.555.t.3');
  assert.equal(links.team, 'https://football.fantasysports.yahoo.com/f1/555/3');
  assert.equal(links.add('461.p.30123'), 'https://football.fantasysports.yahoo.com/f1/555/addplayer?apid=30123');
  assert.equal(links.add('not-a-key'), null);
  assert.equal(yahooLinks('bad').team, 'https://football.fantasysports.yahoo.com/');
});
test('status tags use Yahoo status only and mark byes', () => {
  assert.equal(statusTag({ status: '' }, 3), null);
  assert.deepEqual(statusTag({ status: 'Q' }, 3), { text: 'Q', tone: 'warn', label: 'listed Questionable' });
  assert.equal(statusTag({ status: 'O' }, 3).text, 'OUT');
  assert.equal(statusTag({ status: 'D' }, 3).tone, 'bad');
  assert.equal(statusTag({ status: '', byeWeek: 3 }, 3).text, 'BYE');
});
test('game lines read home/away from the nflverse game id', () => {
  const game = { opponent: 'NO', gameDate: '2026-09-24', gameTime: '20:15', gameId: '2026_03_NO_SEA' };
  assert.equal(gameLine('SEA', game), 'vs NO · Thu 8:15 PM');
  assert.equal(gameLine('NO', { ...game, opponent: 'SEA' }), '@ SEA · Thu 8:15 PM');
  assert.equal(gameLine('SEA', null), null);
});
test('starter totals count unknown estimates instead of treating them as zero', () => {
  const t = team({ RB2: 'O' });
  assert.deepEqual(starterTotal(t, estimateFor()), { points: 57, missing: 1, starters: 5 });
});
test('an Out starter becomes a start/sit move with a healthy replacement', () => {
  const moves = movesFor(team({ RB2: 'O' }), estimateFor());
  assert.equal(moves[0].kind, 'lineup');
  assert.equal(moves[0].headline, 'Start RBbench over RB2');
  assert.match(moves[0].why, /RB2 is listed Out in Yahoo/);
  assert.equal(moves[0].impact, 'Avoid a zero');
  assert.equal(moves[0].href, 'https://football.fantasysports.yahoo.com/f1/555/3');
});
test('a questionable starter gets a watch card whose backup is not already starting', () => {
  const t = team({ WR1: 'Q' });
  const moves = movesFor(t, estimateFor({ WR1: 12 }));
  const watch = moves.find(m => m.kind === 'watch');
  assert.equal(watch.headline, 'Check WR1 before kickoff');
  assert.match(watch.why, /best backup is WRbench/);
});
test('an Out starter with no bench cover says so instead of inventing a backup', () => {
  const t = team({ QB1: 'O' });
  const moves = movesFor(t, estimateFor());
  const card = moves.find(m => m.headline === 'Replace QB1');
  assert(card); assert.match(card.why, /Nobody healthy on your bench can fill QB/);
});
test('small healthy-starter edges do not trigger swaps', () => {
  // RBbench is only 1.5 points better than RB2; the optimizer's switch penalty keeps RB2.
  const moves = movesFor(team(), estimateFor({ RBbench: 10.5 }));
  assert.equal(moves.filter(m => m.kind === 'lineup').length, 0);
});
test('only a meaningful, healthy pickup that would start becomes a move', () => {
  const add = { player: { name: 'Waiver WR', playerKey: '461.p.999', ownership: 'freeagents' }, estimate: { playable: true, points: 14, basis: 'x' }, impact: { slot: 'WR', replaced: 'WR1', gain: 2 } };
  const small = { ...add, impact: { ...add.impact, gain: 1 } };
  const risky = { ...add, estimate: { ...add.estimate, caution: true } };
  assert.equal(movesFor(team(), estimateFor(), [small]).length, 0);
  assert.equal(movesFor(team(), estimateFor(), [risky]).length, 0);
  const [move] = movesFor(team(), estimateFor(), [add], { name: 'TEbench' });
  assert.equal(move.headline, 'Add Waiver WR, drop TEbench');
  assert.equal(move.href, 'https://football.fantasysports.yahoo.com/f1/555/addplayer?apid=999');
  assert.equal(movesGain([move, { impact: 'Avoid a zero' }, { impact: '+1.5 pts' }]), 3.5);
});
test('drop candidates skip IR and a team\'s only player at a started position', () => {
  const t = team();
  assert.equal(dropCandidate(t, league, estimateFor()).name, 'TEbench');
  const onlyWrOnBench = { ...t, roster: t.roster.filter(p => p.name !== 'TEbench') };
  assert.equal(dropCandidate(onlyWrOnBench, league, estimateFor()).name, 'WRbench');
});
test('position ranks use best healthy players and leave incomplete teams unranked', () => {
  const mine = team({ RB2: 'O' });
  const others = Array.from({ length: 6 }, (_, i) => ({ ...team(), teamKey: `461.l.555.t.${10 + i}`, name: `T${i}` }));
  const blank = { teamKey: '461.l.555.t.99', rosterAvailable: false, roster: [] };
  const command = { team: { teamKey: mine.teamKey }, league, teams: [mine, ...others, blank] };
  const scale = new Map(others.map((t, i) => [t, 1.1 + i * 0.1]));
  const estimate = p => {
    const owner = command.teams.find(t => t.roster.includes(p)), e = estimateFor()(p);
    return scale.has(owner) && Number.isFinite(e.points) ? { ...e, points: e.points * scale.get(owner) } : e;
  };
  const { ranks, byTeam } = positionRanks(command, estimate);
  const rb = ranks.find(r => r.pos === 'RB');
  // RB2 is out, but RBbench is healthy, so the RB group is still ranked (15 + 11 = 26).
  assert.equal(rb.points, 26); assert.equal(rb.of, 7); assert.equal(rb.rank, 7);
  assert.equal(byTeam.get('461.l.555.t.99').RB, undefined);
  assert.equal(ranks.find(r => r.pos === 'QB').rank, 7);
  assert.equal(ranks.find(r => r.pos === 'K').rank, null);
  assert.equal(tradeIdea({ ranks, byTeam }, mine.teamKey), null);
});
