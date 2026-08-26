const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const projectRoot = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(projectRoot, 'site/app/index.html'), 'utf8');
const players = JSON.parse(fs.readFileSync(path.join(projectRoot, 'site/app/data/players.json'), 'utf8'));
const matcherStart = html.indexOf('function voiceNormalize(value)');
const matcherEnd = html.indexOf('async function loadVoiceModel()');

assert.notEqual(matcherStart, -1, 'voice matcher start was not found');
assert.notEqual(matcherEnd, -1, 'voice matcher end was not found');

const context = {
  allPlayers: players,
  myTeamIds: [],
  opponentIds: []
};
vm.createContext(context);
vm.runInContext(html.slice(matcherStart, matcherEnd), context);

test('extracts team and position context from natural player descriptions', () => {
  const parsed = context.voicePlayerContext('Javonte Williams running back from the Cowboys');
  assert.deepEqual(
    JSON.parse(JSON.stringify(parsed)),
    {name: 'javonte williams', team: 'DAL', position: 'RB'}
  );
});

test('matches an exact name with team and position descriptions', () => {
  const match = context.voiceMatchPlayer('Javonte Williams running back from the Cowboys');
  assert.equal(match.player.player_name, 'Javonte Williams');
  assert.equal(match.exact, true);
  assert.equal(match.confident, true);
});

test('uses Dallas context to rescue a fuzzy first name', () => {
  const match = context.voiceMatchPlayer('Jante Williams from Dallas');
  assert.equal(match.player.player_name, 'Javonte Williams');
  assert.equal(match.context.team, 'DAL');
  assert.equal(match.confident, true);
  assert.ok(match.score >= 0.64);
});

test('combines fuzzy name, position, and team context', () => {
  const match = context.voiceMatchPlayer('Jante Williams running back from Dallas');
  assert.equal(match.player.player_name, 'Javonte Williams');
  assert.equal(match.context.team, 'DAL');
  assert.equal(match.context.position, 'RB');
  assert.equal(match.confident, true);
});

test('does not treat a bare common surname as a confident match', () => {
  const match = context.voiceMatchPlayer('Williams');
  assert.equal(match.confident, false);
});

test('adds descriptive player phrases to the offline speech grammar', () => {
  const grammar = new Set(JSON.parse(context.voiceGrammar()));
  assert.equal(grammar.has('taken javonte williams running back'), true);
  assert.equal(grammar.has('taken javonte williams from dallas'), true);
  assert.equal(grammar.has('draft javonte williams from the dallas cowboys'), true);
  assert.equal(grammar.has('draft javonte williams running back from dallas'), true);
});
