import { createDecipheriv } from 'node:crypto';

const ORIGIN = 'https://overadp.com';
const SESSION = '__Host-overadp-yahoo-session';
const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'private, no-store, max-age=0',
  'CDN-Cache-Control': 'no-store',
  'Netlify-CDN-Cache-Control': 'no-store',
  'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
};
const reply = (body, status = 200) => new Response(JSON.stringify(body), { status, headers });

function signedIn(request, secret, now) {
  if (!/^[a-f0-9]{64}$/i.test(secret || '')) return false;
  const parts = (request.headers.get('cookie') || '').split(';').map(x => x.trim()).filter(x => x.startsWith(`${SESSION}=`));
  if (parts.length !== 1) return false;
  const token = parts[0].slice(SESSION.length + 1);
  if (!/^[a-zA-Z0-9_-]{40,3600}$/.test(token)) return false;
  try {
    const raw = Buffer.from(token, 'base64url');
    const decipher = createDecipheriv('aes-256-gcm', Buffer.from(secret, 'hex'), raw.subarray(0, 12));
    decipher.setAAD(Buffer.from('overadp-yahoo-v1:session'));
    decipher.setAuthTag(raw.subarray(12, 28));
    const session = JSON.parse(Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString('utf8'));
    return Boolean(session.accessToken && Number.isFinite(session.exp) && session.exp > now());
  } catch { return false; }
}

const mean = (rows, key) => rows.length ? Math.round(10 * rows.reduce((sum, row) => sum + (Number(row[key]) || 0), 0) / rows.length) / 10 : null;
function playerFacts(player, prior, snapshot) {
  const previous = prior.players.find(p => p.id === player.id)?.games || [];
  const recent = player.games || [];
  const game = player.nextGame;
  const opponent = game?.opponent;
  const opponentStats = snapshot.teamStats?.[opponent];
  return {
    name: player.name, nflTeam: player.team, position: player.position,
    currentSeasonGames: recent.length, priorSeasonGames: previous.length,
    current: { pointsPerGameStandard: mean(recent, 'points'), targetsPerGame: mean(recent, 'targets'),
      carriesPerGame: mean(recent, 'carries'), receptionsPerGame: mean(recent, 'receptions'),
      receivingYardsPerGame: mean(recent, 'receivingYards'), rushingYardsPerGame: mean(recent, 'rushingYards'),
      passingYardsPerGame: mean(recent, 'passingYards'), touchdowns: recent.reduce((n, g) => n + (g.rushingTds || 0) + (g.receivingTds || 0) + (g.passingTds || 0), 0),
      latestRecordedWeek: recent.at(-1)?.week ?? null },
    prior: { receptionsPerGame: mean(previous, 'receptions'), receivingYardsPerGame: mean(previous, 'receivingYards'),
      rushingYardsPerGame: mean(previous, 'rushingYards'), passingYardsPerGame: mean(previous, 'passingYards'),
      rushingTds: previous.reduce((n, g) => n + (g.rushingTds || 0), 0),
      receivingTds: previous.reduce((n, g) => n + (g.receivingTds || 0), 0),
      passingTds: previous.reduce((n, g) => n + (g.passingTds || 0), 0) },
    nextGame: game ? { opponent, date: game.gameDate, time: game.gameTime,
      opponentPublicDefenseStats: opponentStats ? { games: opponentStats.games,
        sacks: opponentStats.defensiveSacks, interceptions: opponentStats.defensiveInterceptions } : null } : null,
    historicalInjuryReport: player.recentInjury || null,
  };
}

export function comparisonPayload(input, snapshot, prior) {
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      Object.keys(input).sort().join(',') !== 'playerAId,playerBId,scoring') throw Error('INVALID_INPUT');
  const { playerAId, playerBId, scoring } = input;
  if (!['standard', 'half_ppr', 'ppr'].includes(scoring) || playerAId === playerBId) throw Error('INVALID_INPUT');
  const byId = new Map(snapshot.players.map(player => [player.id, player]));
  const a = byId.get(playerAId), b = byId.get(playerBId);
  if (!a || !b || !['QB', 'RB', 'WR', 'TE'].includes(a.position) || a.position !== b.position) throw Error('INVALID_PLAYERS');
  if (snapshot.source !== 'nflverse' || prior.source !== 'nflverse' || prior.season !== snapshot.season - 1) throw Error('INVALID_SNAPSHOT');
  const state = {
    source: 'Independent public nflverse data only. No Yahoo roster, league, scoring settings, or account data.',
    season: snapshot.season, upcomingWeek: snapshot.nextWeek, latestCompletedWeek: snapshot.latestCompletedWeek,
    snapshotTime: snapshot.generatedAt,
    userSelectedGenericScoring: scoring,
    scoringAssumption: 'Generic standard fantasy scoring: 1 point/10 rush or receiving yards, 6 per rush/receiving TD, 1/25 pass yards, 4/pass TD, -2/interception, -2/lost fumble; reception bonus 0, 0.5, or 1.',
    warning: 'Historical injury report is not a current clearance. Two current-season games or fewer; do not assume availability. No reliable injury probability or calibrated fantasy forecast.',
    options: { a: playerFacts(a, prior, snapshot), b: playerFacts(b, prior, snapshot) },
  };
  const questions = { start: { type: 'choice',
    instructions: 'For the upcoming week, choose the player with stronger expected fantasy scoring under the generic scoring assumption, using only the supplied public facts. Weigh prior-season sample, recent usage, opponent, and the possibility of missing the game. If evidence is insufficient or availability cannot be assessed, choose uncertain. This is a start/sit comparison, not a certainty claim.',
    criteria: { a: `Start ${a.name} over ${b.name}`, b: `Start ${b.name} over ${a.name}`,
      uncertain: 'No defensible start/sit distinction from supplied facts, including unresolved availability' } } };
  const injury = [a, b].filter(p => p.recentInjury).map(p => `${p.name}: historical ${p.recentInjury.reportStatus || 'injury report'} in Week ${p.recentInjury.week}; not current clearance`);
  const evidence = recentGamesLabel(a, b, snapshot);
  return { state, questions, players: { a: a.name, b: b.name }, evidence, injury, week: snapshot.nextWeek, generatedAt: snapshot.generatedAt };
}

function recentGamesLabel(a, b, snapshot) {
  const hours = (Date.now() - Date.parse(snapshot.generatedAt)) / 3600000;
  if (!Number.isFinite(hours) || hours > 48 || hours < -1) return 'stale';
  if ((a.games?.length || 0) < 3 || (b.games?.length || 0) < 3 || a.recentInjury || b.recentInjury) return 'limited';
  return 'moderate';
}

export async function handleComparison(request, { env, snapshot, prior, fetcher = fetch, now = Date.now } = {}) {
  if (request.method !== 'POST') return reply({ error: 'METHOD_NOT_ALLOWED' }, 405);
  if (new URL(request.url).origin !== ORIGIN || request.headers.get('origin') !== ORIGIN ||
      request.headers.get('sec-fetch-site') !== 'same-origin') return reply({ error: 'BAD_ORIGIN' }, 403);
  if (!(request.headers.get('content-type') || '').toLowerCase().startsWith('application/json')) return reply({ error: 'JSON_REQUIRED' }, 415);
  if (!signedIn(request, env('YAHOO_SESSION_SECRET'), now)) return reply({ error: 'CONNECT_YAHOO_FIRST' }, 401);
  if (Number(request.headers.get('content-length') || 0) > 512) return reply({ error: 'INVALID_INPUT' }, 400);
  let payload;
  try {
    const raw = await request.text();
    if (raw.length > 512) throw Error('INVALID_INPUT');
    payload = comparisonPayload(JSON.parse(raw), snapshot, prior);
  } catch { return reply({ error: 'INVALID_INPUT' }, 400); }
  if ((now() - Date.parse(snapshot.generatedAt)) > 48 * 3600000) return reply({ error: 'STALE_PUBLIC_DATA' }, 503);
  const key = env('TYPESAFE_API_KEY');
  if (!key) return reply({ error: 'JEV_NOT_CONFIGURED' }, 503);
  try {
    const upstream = await fetcher('https://api.typesafe.ai/v1/systemone', { method: 'POST', redirect: 'error',
      signal: AbortSignal.timeout(20000),
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'jev-latest', state: JSON.stringify(payload.state), questions: payload.questions }) });
    if (!upstream.ok) return reply({ error: 'JEV_UNAVAILABLE' }, 502);
    const data = await upstream.json();
    const answer = data.answers?.start;
    if (!['a', 'b', 'uncertain'].includes(answer?.choice) || !Number.isFinite(answer.confidence) ||
        answer.confidence < 0 || answer.confidence > 1 || !answer.probabilities ||
        !['a', 'b', 'uncertain'].every(k => Number.isFinite(answer.probabilities[k])))
      return reply({ error: 'JEV_INVALID_RESULT' }, 502);
    return reply({ choice: answer.choice, players: payload.players, probabilities: answer.probabilities,
      confidence: answer.confidence, evidence: payload.evidence, historicalInjuryNotes: payload.injury,
      week: payload.week, snapshotAt: payload.generatedAt,
      note: 'Jev confidence is decisiveness among options, not the chance this start/sit choice is correct. Confirm current availability before kickoff.' });
  } catch { return reply({ error: 'JEV_UNAVAILABLE' }, 502); }
}
