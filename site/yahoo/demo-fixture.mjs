// SYNTHETIC local preview only (loaded on localhost with ?demo=1). Invented league,
// teams and statuses built from the public nflverse snapshot. Never live Yahoo data.
const SCORING = [
  ['Pass Yds', 0.04], ['Pass TD', 4], ['Int', -1], ['Rush Yds', 0.1], ['Rush TD', 6], ['Rec', 0.5], ['Rec Yds', 0.1],
  ['Rec TD', 6], ['Ret TD', 6], ['2-PT', 2], ['Fum Lost', -2], ['Off Fumb TD', 6],
  ['FG 0-19', 3], ['FG 20-29', 3], ['FG 30-39', 3], ['FG 40-49', 4], ['FG 50+', 5], ['PAT Made', 1],
  ['Sack', 1], ['Int', 2], ['Fum Rec', 2], ['TD', 6], ['Safe', 2], ['Blk Kick', 2], ['Ret TD', 6], ['Pts Allow 0', 10],
  ['Pts Allow 1-6', 7], ['Pts Allow 7-13', 4], ['Pts Allow 14-20', 1], ['Pts Allow 21-27', 0], ['Pts Allow 28-34', -1], ['Pts Allow 35+', -4],
].map(([name, value]) => ({ name, value: String(value) }));
const POSITIONS = [['QB', 1], ['WR', 2], ['RB', 2], ['TE', 1], ['W/R/T', 1], ['K', 1], ['DEF', 1], ['BN', 6], ['IR', 1]]
  .map(([position, count]) => ({ position, count: String(count) }));
const NAMES = ['Taco Corp', 'Fourth & Long', 'Sample Squad', 'Gridiron Gang', 'Hail Marys', 'Red Zone Regulars',
  'Waiver Wire Warriors', 'Blitz Brigade', 'End Zone Elite', 'Bye Week Blues'];
const QUOTA = { QB: 2, RB: 5, WR: 5, TE: 2, K: 1 };
const DEFENSES = ['BAL', 'PIT', 'DEN', 'SF', 'BUF', 'PHI', 'KC', 'DAL', 'MIN', 'HOU', 'DET', 'GB', 'NYJ', 'CLE'];

export function buildDemo(snapshot) {
  const league = { name: 'Sample League', season: String(snapshot.season), currentWeek: snapshot.nextWeek, endWeek: 17, playoffStartWeek: 15, teams: '10',
    scoringType: 'head', draftType: 'live', positions: POSITIONS, scoring: SCORING };
  let n = 1000;
  const toYahoo = p => ({ name: p.name, position: p.position, playerKey: `461.p.${n++}`, eligible: [p.position],
    team: p.team, status: '', slot: 'BN', rosterWeek: league.currentWeek, byeWeek: null, seasonPoints: null, pointsSeason: '', ownership: '', waiverDate: '' });
  const pool = [...snapshot.players].filter(p => p.nextGame && Number.isFinite(p.averagePoints))
    .sort((a, b) => b.averagePoints - a.averagePoints);
  const teams = NAMES.map((name, i) => ({ teamKey: `461.l.99999.t.${i + 1}`, name, rank: null, wins: null, losses: null, ties: 0,
    pointsFor: null, pointsAgainst: null, roster: [], rosterAvailable: true, rosterWeek: league.currentWeek }));
  const taken = new Set(), counts = teams.map(() => ({}));
  for (let round = 0, pick = 0; round < 15; round++) {
    const order = round % 2 ? [...teams.keys()].reverse() : [...teams.keys()];
    for (const t of order) {
      const p = pool.find(x => !taken.has(x.id) && (counts[t][x.position] || 0) < QUOTA[x.position] &&
        // Leave some mid-tier talent on waivers so the demo has real pickups.
        !(pick++ % 7 === 3 && round > 5));
      if (!p) continue;
      taken.add(p.id); counts[t][p.position] = (counts[t][p.position] || 0) + 1; teams[t].roster.push(toYahoo(p));
    }
  }
  teams.forEach((t, i) => t.roster.push({ ...toYahoo({ name: `${DEFENSES[i]} Defense`, position: 'DEF', team: DEFENSES[i] }) }));
  const avg = new Map(snapshot.players.map(p => [p.name, p.averagePoints]));
  for (const t of teams) {
    const byAvg = pos => t.roster.filter(p => p.position === pos).sort((a, b) => (avg.get(b.name) ?? 0) - (avg.get(a.name) ?? 0));
    const start = (pos, slot, k) => byAvg(pos).filter(p => p.slot === 'BN').slice(0, k).forEach(p => { p.slot = slot; });
    start('QB', 'QB', 1); start('RB', 'RB', 2); start('WR', 'WR', 2); start('TE', 'TE', 1); start('K', 'K', 1); start('DEF', 'DEF', 1);
    t.roster.filter(p => p.slot === 'BN' && ['RB', 'WR', 'TE'].includes(p.position))
      .sort((a, b) => (avg.get(b.name) ?? 0) - (avg.get(a.name) ?? 0))[0].slot = 'W/R/T';
  }
  // Give "my" team the situations the hub should explain.
  const mine = teams[3], rb = mine.roster.filter(p => p.slot === 'RB'), wr = mine.roster.filter(p => p.slot === 'WR');
  rb[1].status = 'O';
  wr[0].status = 'Q';
  const benchWr = mine.roster.filter(p => p.slot === 'BN' && p.position === 'WR').sort((a, b) => (avg.get(b.name) ?? 0) - (avg.get(a.name) ?? 0))[0];
  if (benchWr) { benchWr.slot = 'WR'; wr[1].slot = 'BN'; }
  // An IR player upgraded from Out to Doubtful, who must come back to the roster.
  const irBack = mine.roster.filter(p => p.slot === 'BN' && p.position === 'RB').at(-1);
  if (irBack) { irBack.slot = 'IR'; irBack.status = 'D'; }
  const records = [[2, 0], [2, 0], [1, 1], [1, 1], [1, 1], [1, 1], [1, 1], [1, 1], [0, 2], [0, 2]];
  teams.forEach((t, i) => { [t.wins, t.losses] = records[(i * 7) % 10]; t.rank = i + 1; });
  const available = pool.filter(p => !taken.has(p.id)).slice(0, 60).map((p, i) => ({ ...toYahoo(p), slot: '',
    ownership: i % 6 === 2 ? 'waivers' : 'freeagents', waiverDate: i % 6 === 2 ? 'Wed' : '' }))
    // A few unrostered kickers (the draft only takes one per team).
    .concat(snapshot.players.filter(p => p.position === 'K' && p.nextGame && !taken.has(p.id)).slice(0, 4).map(p => ({ ...toYahoo(p), slot: '', ownership: 'freeagents' })))
    // Unrostered defenses: public stats can't score them, which the ranking must tolerate.
    .concat(DEFENSES.slice(teams.length).map(team => ({ ...toYahoo({ name: `${team} Defense`, position: 'DEF', team }), slot: '', ownership: 'freeagents' })));
  const command = { team: { teamKey: mine.teamKey, name: mine.name, leagueKey: '461.l.99999' }, league, teams,
    matchup: { week: league.currentWeek, opponentKey: teams[0].teamKey },
    warnings: ['SYNTHETIC LOCAL PREVIEW: invented league, teams and injury tags. Not live Yahoo data.'],
    coverage: { returnedTeams: 10, expectedTeams: 10, rosterTeams: 10 }, fetchedAt: new Date().toISOString() };
  return {
    command,
    teams: [{ teamKey: mine.teamKey, name: mine.name, leagueKey: '461.l.99999' }],
    available({ pool: which, position }) {
      const own = which === 'FA' ? 'freeagents' : 'waivers';
      return { teamKey: mine.teamKey, season: league.season, pool: which, position, start: 0,
        players: available.filter(p => p.ownership === own && (position === 'ALL' || p.position === position)).slice(0, 25),
        hasMore: false, fetchedAt: new Date().toISOString() };
    },
  };
}
