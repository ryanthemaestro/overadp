const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const projectRoot = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(projectRoot, 'site/app/index.html'), 'utf8');
const statusStart = html.indexOf('function injuryStatusInfo(player)');
const statusEnd = html.indexOf('function injuryUpdatedInfo(value)');
const modelStart = html.indexOf('function frontLoadedAvailability(expectedMissed');
const modelEnd = html.indexOf('function getBoardOrder(availablePlayers)');

assert.notEqual(statusStart, -1, 'injury status function was not found');
assert.notEqual(statusEnd, -1, 'injury status function end was not found');
assert.notEqual(modelStart, -1, 'availability model start was not found');
assert.notEqual(modelEnd, -1, 'availability model end was not found');

const context = {
  scarcityData: [
    {position: 'RB', replacement_pts: 139.6},
    {position: 'WR', replacement_pts: 125.4},
    {position: 'QB', replacement_pts: 243.2},
    {position: 'TE', replacement_pts: 111.0},
  ],
  rosterConfig: {bench_size: 6},
  getRosterPlan: () => ({numTeams: 12, bench: 6}),
};
vm.createContext(context);
vm.runInContext(
  `${html.slice(statusStart, statusEnd)}\n${html.slice(modelStart, modelEnd)}`,
  context
);

test('replaces internal Week 1 labels with standard questionable shorthand', () => {
  const info = context.injuryStatusInfo({
    injury_status: 'INJ',
    season_outlook: 'monitor_week_1',
  });
  assert.equal(info.code, 'Q');
  assert.equal(info.tier, 'q');
});

test('shows the confirmed suspension length in the badge', () => {
  const info = context.injuryStatusInfo({
    injury_status: 'Suspension',
    suspension_games: 4,
  });
  assert.equal(info.code, 'SUSP · 4G');
  assert.equal(info.tier, 'sus');
});

test('suspension value retains post-return upside and replacement production', () => {
  const result = context.injuryAvailabilityAdjustment({
    injury_status: 'Suspension',
    suspension_games: 4,
    expected_games_missed: 4,
    projected_points: 300,
    vbd: 175,
    position: 'WR',
  });

  assert.deepEqual(Array.from(result.weeklyAvailability.slice(0, 5)), [0, 0, 0, 0, 1]);
  assert.equal(result.expectedGamesMissed, 4);
  assert.ok(result.replacementPoints > 0);
  assert.ok(result.adjustedProjection > 245 && result.adjustedProjection < 255);
  assert.ok(result.adjustedVbd > 115 && result.adjustedVbd < 135);
  assert.match(result.reason, /4-game suspension priced in/);
});

test('questionable status is represented as a probability instead of a ban', () => {
  const result = context.injuryAvailabilityAdjustment({
    injury_status: 'Questionable',
    projected_points: 220,
    vbd: 90,
    position: 'RB',
  });

  assert.ok(result.weeklyAvailability[0] > 0 && result.weeklyAvailability[0] < 1);
  assert.ok(result.adjustedVbd < 90);
  assert.ok(result.adjustedVbd > 80);
});
