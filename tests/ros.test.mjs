import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { rosPerGame, scoringRatio, HALF_PPR } from '../site/yahoo/ros.mjs';

const model = JSON.parse(readFileSync(new URL('../site/yahoo/ros-model.json', import.meta.url)));
const snapshot = JSON.parse(readFileSync(new URL('./fixtures/nflverse-2026-week2.json', import.meta.url)));
const halfLeague = { scoring: HALF_PPR };
const pprLeague = { scoring: HALF_PPR.map(r => r.name === 'Rec' ? { ...r, value: '1' } : r) };

test('model file covers every modeled position and bucket, with held-out errors', () => {
  for (const pos of ['QB', 'RB', 'WR', 'TE']) {
    assert.deepEqual(Object.keys(model.positions[pos]).sort(), model.buckets.map(([a, b]) => `${a}-${b}`).sort());
    for (const coef of Object.values(model.positions[pos])) assert.equal(coef.length, model.features.length);
    assert(model.held_out_mae[pos]['weeks 2-5'] < model.preseason_only_mae[pos]['weeks 2-5']);
  }
});
test('no games yet: the v6 preseason projection per game', () => {
  const r = rosPerGame({ position: 'WR', current: { games: [] }, prior: null, v6: { projected_points: 170 }, league: halfLeague, model });
  assert.equal(r.points, 10); assert.equal(r.basis, 'v6 preseason projection');
});
test('with games played, results and usage move the estimate from the preseason view', () => {
  const wr = snapshot.players.find(p => p.position === 'WR' && p.games.length === 2 && p.averagePoints > 15);
  const low = rosPerGame({ position: 'WR', current: wr, prior: null, v6: { projected_points: 60 }, league: halfLeague, model });
  assert(low.points > 60 / 17, 'a hot start lifts a low preseason projection');
  assert.match(low.basis, /v6 projection \+ 2 games this season/);
});
test('league scoring converts from half-PPR using the player\'s own games', () => {
  const wr = snapshot.players.find(p => p.position === 'WR' && p.averagePoints > 10 && p.games.some(g => g.receptions > 4));
  assert(scoringRatio('WR', wr.games, pprLeague) > 1);
  const half = rosPerGame({ position: 'WR', current: wr, prior: null, v6: { projected_points: 150 }, league: halfLeague, model });
  const ppr = rosPerGame({ position: 'WR', current: wr, prior: null, v6: { projected_points: 150 }, league: pprLeague, model });
  assert(ppr.points > half.points);
});
test('kickers, defenses and players with no data get no rest-of-season model', () => {
  assert.equal(rosPerGame({ position: 'K', current: null, prior: null, v6: null, league: halfLeague, model }), null);
  assert.equal(rosPerGame({ position: 'WR', current: { games: [] }, prior: null, v6: null, league: halfLeague, model }), null);
});

// ---- Kickers ----
import { kickerPerGame, DEFAULT_K } from '../site/yahoo/ros.mjs';
const kicker = snapshot.players.find(p => p.position === 'K' && p.games.length === 2);
const ctx = { KC: { pointsPerGame: 30, priorPointsPerGame: 25, remainingIndoorShare: 0.2 }, DET: { pointsPerGame: 30, priorPointsPerGame: 25, remainingIndoorShare: 0.8 } };
const kLeague = { scoring: DEFAULT_K };
test('kicker model ships both parts and a K start/sit table', () => {
  assert.deepEqual(model.kicker.rest_of_season.features, ['intercept', 'base', 'obs0', 'indoor_share']);
  assert(model.kicker.next_week.features.includes('implied'));
  assert(model.start_sit.accuracy.K['1-2'] > 0.5);
});
test('rest of season: an indoor schedule is worth more, and results pull toward the league', () => {
  const outdoor = kickerPerGame({ kind: 'season', current: kicker, prior: null, team: 'KC', context: ctx, league: kLeague, model });
  const dome = kickerPerGame({ kind: 'season', current: kicker, prior: null, team: 'DET', context: ctx, league: kLeague, model });
  assert(dome.points > outdoor.points);
  assert(outdoor.points > 4 && outdoor.points < 12, String(outdoor.points));
  assert.match(outdoor.basis, /league-average start \+ 2 games, 20% of remaining games indoors/);
});
test('next week: a higher implied team total projects more', () => {
  const game = total => ({ impliedTotal: total, indoor: false });
  const low = kickerPerGame({ kind: 'week', current: kicker, prior: null, team: 'KC', context: ctx, game: game(17), league: kLeague, model });
  const high = kickerPerGame({ kind: 'week', current: kicker, prior: null, team: 'KC', context: ctx, game: game(30), league: kLeague, model });
  assert(high.points > low.points);
  assert.equal(kickerPerGame({ kind: 'week', current: kicker, prior: null, team: 'KC', context: ctx, game: null, league: kLeague, model }), null);
});

// ---- Defenses ----
import { defensePerGame, DEFAULT_DEF } from '../site/yahoo/ros.mjs';
import { scoreGame } from '../site/yahoo/league-scoring.mjs';
const defGame = (week, pointsAllowed) => ({ week, sacks: 3, interceptions: 1, fumbleRecoveries: 0, touchdowns: 0, safeties: 0, puntBlocks: 0,
  patBlocks: 0, fgBlocks: 0, returnTds: 0, twoPointReturns: 0, pointsAllowed });
const defSnap = oppImplied => ({
  teamContext: { BAL: { priorDefensePointsPerGame: 7, remainingOpponentOffense: 21 } },
  teamStats: { BAL: { defenseGames: [defGame(1, 10), defGame(2, 24)] } },
  schedule: { BAL: { opponent: 'DAL', home: false }, DAL: { opponent: 'BAL', impliedTotal: oppImplied, home: true } } });
test('points-allowed tiers score from the final score; missing scores stay incomplete', () => {
  assert.equal(scoreGame(defGame(1, 10), 'DEF', DEFAULT_DEF).points, 3 + 2 + 4);
  assert.equal(scoreGame(defGame(1, 0), 'DEF', DEFAULT_DEF).points, 3 + 2 + 10);
  assert.equal(scoreGame(defGame(1, 40), 'DEF', DEFAULT_DEF).points, 3 + 2 - 4);
  const noScore = scoreGame(defGame(1, null), 'DEF', DEFAULT_DEF);
  assert.equal(noScore.points, null); assert.deepEqual(noScore.missing, ['points allowed']);
});
test('defense model ships both parts and a DEF start/sit table', () => {
  assert(model.defense.next_week.features.includes('opp_implied'));
  assert(model.defense.rest_of_season.features.includes('opp_off'));
  assert(model.start_sit.accuracy.DEF['3-5'] > 0.65);
});
test('next week: facing a lower-scoring opponent projects more', () => {
  const soft = defensePerGame({ kind: 'week', team: 'BAL', snapshot: defSnap(16), league: { scoring: DEFAULT_DEF }, model });
  const tough = defensePerGame({ kind: 'week', team: 'BAL', snapshot: defSnap(30), league: { scoring: DEFAULT_DEF }, model });
  assert(soft.points > tough.points + 3, `${soft.points} vs ${tough.points}`);
  assert.match(soft.basis, /opponent projected for 16 points/);
  const season = defensePerGame({ kind: 'season', team: 'BAL', snapshot: defSnap(20), league: { scoring: DEFAULT_DEF }, model });
  assert(season.points > 2 && season.points < 12, String(season.points));
  assert.equal(defensePerGame({ kind: 'week', team: 'BAL', snapshot: defSnap(null), league: { scoring: DEFAULT_DEF }, model }), null);
});
test('later weeks: each defense is valued against that week\'s opponent, and byes are zero', () => {
  const snap = defSnap(20);
  snap.teamContext.BAL.remainingSchedule = [{ week: 4, opponent: 'WEAK', home: true }, { week: 5, opponent: 'STRONG', home: false }];
  snap.teamContext.WEAK = { offenseStrength: 15 }; snap.teamContext.STRONG = { offenseStrength: 31 };
  const args = week => ({ kind: 'future', team: 'BAL', week, snapshot: snap, league: { scoring: DEFAULT_DEF }, model });
  const weak = defensePerGame(args(4)), strong = defensePerGame(args(5));
  assert(weak.points > strong.points, `${weak.points} vs ${strong.points}`);
  assert.match(weak.basis, /week 4 opponent scoring 15\.0 points a game/);
  assert.deepEqual(defensePerGame(args(6)), { points: 0, basis: 'bye week', games: 2 });
});

// ---- Injury return curves (research/ros_calibration/injuries.py) ----
import { availabilityShare, likelyReturn } from '../site/yahoo/hub.mjs';
const avail = model.availability;
test('availability model ships measured curves and beats the previous assumptions held out', () => {
  assert(avail.out.all[2] > 0.6, 'most Out players miss a second game');
  assert(avail.held_out_brier.calibrated < avail.held_out_brier['previous page']);
  assert(avail.questionable > 0.5 && avail.questionable < 0.8);
  assert(avail.doubtful < 0.1);
});
test('an Out player is not assumed back next week; knee absences run longer than concussions', () => {
  const knee = { status: 'O', injuryGroup: 'Knee', gamesMissed: 0 }, conc = { status: 'O', injuryGroup: 'Concussion', gamesMissed: 0 };
  assert.equal(availabilityShare(knee, 3, 3, avail), 0);
  assert(availabilityShare(knee, 4, 3, avail) < 0.5);
  assert(availabilityShare(conc, 4, 3, avail) > availabilityShare(knee, 4, 3, avail));
  assert(availabilityShare(knee, 12, 3, avail) > 0.6, 'most are back within ~9 games');
  assert(likelyReturn(knee, avail) > likelyReturn(conc, avail));
});
test('IR, Questionable and Doubtful use measured rates; healthy players are unaffected', () => {
  const ir = { status: 'IR', slot: 'IR', gamesMissed: 1 };
  assert.equal(availabilityShare(ir, 3, 3, avail), 0);
  assert(availabilityShare(ir, 5, 3, avail) < 0.5);
  assert.equal(availabilityShare({ status: 'Q' }, 3, 3, avail), avail.questionable);
  assert.equal(availabilityShare({ status: 'D' }, 3, 3, avail), avail.doubtful);
  assert(availabilityShare({ status: 'D' }, 4, 3, avail) < 0.5, 'a Doubtful player usually misses more than this week');
  assert.equal(availabilityShare({ status: '' }, 5, 3, avail), 1);
  assert.equal(availabilityShare({ status: 'O', byeWeek: 5 }, 5, 3, avail), 0);
  assert.equal(likelyReturn({ status: '' }, avail), null);
});
test('defense add values carry the measured discount for top-ranked pickups', () => {
  const f = model.defense.add_value_factor;
  assert(f > 0.5 && f < 1, String(f));
});
