// Invented test records only. Never substitute these for an authorized Yahoo response.
export const leagueKey = '999.l.123', ownKey = leagueKey + '.t.1';
export function player(id, position = 'RB', slot = 'RB', points = 10, more = {}) {
  return { playerKey: '999.p.' + id, name: 'Test Player ' + id, position, eligible: [position], slot,
    team: 'TEST', status: '', byeWeek: 8, seasonPoints: points, pointsSeason: '2026', ownership: '', waiverDate: '', ...more };
}
export function rawPlayer(p) {
  return [[{ player_key: p.playerKey }, { name: { full: p.name } }, { display_position: p.position },
    { eligible_positions: p.eligible.map(position => ({ position })) }, { editorial_team_abbr: p.team },
    { status: p.status }, { bye_weeks: { week: p.byeWeek } }],
    { selected_position: [{ coverage_type: 'week' }, { week: '2' }, { position: p.slot }] },
    { player_points: { coverage_type: 'season', season: p.pointsSeason, total: p.seasonPoints } },
    { ownership: { ownership_type: p.ownership, waiver_date: p.waiverDate } }];
}
export const players = [player(1), player(2, 'RB', 'RB', 0, { status: 'Q' }), player(3, 'RB', 'BN', -2),
  player(4, 'WR', 'WR', 21), player(5, 'QB', 'QB', 28), player(6, 'TE', 'TE', null), player(7, 'WR', 'W/R/T', 12)];
export const team = { teamKey: ownKey, name: 'Test Team One', rank: 1, wins: 1, losses: 0, ties: 0,
  pointsFor: 102.3, pointsAgainst: 93.1, roster: players, rosterAvailable: true, rosterWeek: 2 };
export const otherTeam = { ...team, teamKey: leagueKey + '.t.2', name: 'Test Team Two', rank: 2, wins: 0, losses: 1,
  roster: [player(20, 'RB', 'RB', 15), player(21, 'RB', 'RB', 8), player(22, 'WR', 'BN', 2)] };
export const league = { name: 'Synthetic QA League', season: '2026', teams: '2', currentWeek: 2,
  scoringType: 'head', draftType: 'live', positions: [{ position: 'QB', count: '1' }, { position: 'RB', count: '2' },
    { position: 'WR', count: '2' }, { position: 'TE', count: '1' }, { position: 'W/R/T', count: '1' }, { position: 'BN', count: '6' }],
  scoring: [{ name: 'Passing Yards', value: '0.04' }] };
export const command = { team: { teamKey: ownKey, leagueKey, name: team.name }, league, teams: [team, otherTeam], warnings: [],
  coverage: { returnedTeams: 2, expectedTeams: 2, rosterTeams: 2 }, fetchedAt: '2026-09-14T15:00:00.000Z' };
export const rawOwned = { fantasy_content: { users: { '0': { user: [{ teams: { '0': { team: [{ team_key: ownKey }, { name: team.name }, { managers: { email: 'do-not-return@example.invalid' } }] } } }] } } } };
export const rawSettings = { fantasy_content: { league: [{ league_key: leagueKey, name: league.name, season: '2026', num_teams: 2, current_week: 2 },
  { settings: [{ scoring_type: 'head', draft_type: 'live', roster_positions: league.positions.map(p => ({ roster_position: p })) }] }] } };
export function rawTeam(t, withRoster = true, withStandings = true) {
  return [{ team_key: t.teamKey, name: t.name, managers: { email: 'do-not-return@example.invalid' } },
    ...(withRoster ? [{ roster: { week: 2, players: Object.fromEntries(t.roster.map((p, i) => [i, { player: rawPlayer(p) }])) } }] : []),
    ...(withStandings ? [{ team_standings: { rank: t.rank, outcome_totals: { wins: t.wins, losses: t.losses, ties: t.ties }, points_for: t.pointsFor, points_against: t.pointsAgainst } }] : [])];
}
export const rawRosters = { fantasy_content: { league: [{ league_key: leagueKey }, { teams: { '0': { team: rawTeam(team, true, false) }, '1': { team: rawTeam(otherTeam, true, false) }, count: 2 } }] } };
export const rawStandings = { fantasy_content: { league: [{ league_key: leagueKey }, { standings: { teams: { '0': { team: rawTeam(team, false, true) }, '1': { team: rawTeam(otherTeam, false, true) }, count: 2 } } }] } };
