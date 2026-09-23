import { randomBytes, createHash, createCipheriv, createDecipheriv, timingSafeEqual } from 'node:crypto';
import { classifyDenial, DENIAL_REASONS } from './yahoo-denial.mjs';

export const ORIGIN = 'https://overadp.com';
export const CALLBACK = `${ORIGIN}/.netlify/functions/yahoo-callback`;
export const AUTH_URL = 'https://api.login.yahoo.com/oauth2/request_auth';
export const TOKEN_URL = 'https://api.login.yahoo.com/oauth2/get_token';
const API = 'https://fantasysports.yahooapis.com/fantasy/v2/';
const STATE_COOKIE = '__Host-overadp-yahoo-state';
const SESSION_COOKIE = '__Host-overadp-yahoo-session';
const TEAM_KEY = /^\d{1,8}\.l\.\d{1,12}\.t\.\d{1,6}$/;
const PLAYER_KEY = /^\d{1,8}\.p\.\d{1,12}$/;
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF'];
const SECURE_HEADERS = {
  'Cache-Control': 'private, no-store, max-age=0',
  'CDN-Cache-Control': 'no-store',
  'Netlify-CDN-Cache-Control': 'no-store',
  'Pragma': 'no-cache',
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
  'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  'Access-Control-Allow-Origin': ORIGIN,
  'Vary': 'Origin',
};
class SafeError extends Error {
  constructor(code, status = 400, diagnostic) {
    super(code); this.code = code; this.status = status;
    if (DENIAL_REASONS.includes(diagnostic)) this.diagnostic = diagnostic;
  }
}
const reply = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { ...SECURE_HEADERS, 'Content-Type': 'application/json; charset=utf-8' },
});
const cookie = (name, value, age) => `${name}=${value}; Max-Age=${age}; Path=/; Secure; HttpOnly; SameSite=Lax`;
const clear = (response, name) => response.headers.append('Set-Cookie', cookie(name, '', 0));
function readCookie(request, name) {
  const parts = (request.headers.get('cookie') || '').split(';').map(x => x.trim());
  const matches = parts.filter(x => x.startsWith(`${name}=`));
  return matches.length === 1 ? matches[0].slice(name.length + 1) : '';
}
function config(env) {
  const clientId = env('YAHOO_CLIENT_ID');
  const clientSecret = env('YAHOO_CLIENT_SECRET');
  const sessionSecret = env('YAHOO_SESSION_SECRET');
  if (env('YAHOO_ENABLED') !== 'true' || !clientId || !clientSecret ||
      !/^[a-f0-9]{64}$/i.test(sessionSecret || '')) throw new SafeError('NOT_CONFIGURED', 503);
  return { clientId, clientSecret, sessionSecret };
}
export function seal(value, purpose, secret) {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', Buffer.from(secret, 'hex'), iv);
  cipher.setAAD(Buffer.from(`overadp-yahoo-v1:${purpose}`));
  const body = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString('base64url');
}
export function unseal(value, purpose, secret, now) {
  try {
    if (!/^[a-zA-Z0-9_-]{40,3600}$/.test(value)) return null;
    const raw = Buffer.from(value, 'base64url');
    const decipher = createDecipheriv('aes-256-gcm', Buffer.from(secret, 'hex'), raw.subarray(0, 12));
    decipher.setAAD(Buffer.from(`overadp-yahoo-v1:${purpose}`));
    decipher.setAuthTag(raw.subarray(12, 28));
    const data = JSON.parse(Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString('utf8'));
    if (!Number.isFinite(data.exp) || data.exp <= now) return null;
    return data;
  } catch { return null; }
}
function sameOriginPost(request) {
  if (request.method !== 'POST') throw new SafeError('METHOD_NOT_ALLOWED', 405);
  if (new URL(request.url).origin !== ORIGIN || request.headers.get('origin') !== ORIGIN ||
      !['same-origin', null].includes(request.headers.get('sec-fetch-site'))) throw new SafeError('BAD_ORIGIN', 403);
  if (!(request.headers.get('content-type') || '').toLowerCase().startsWith('application/json'))
    throw new SafeError('JSON_REQUIRED', 415);
}
async function boundedJSON(response, limit) {
  if (Number(response.headers.get('content-length') || 0) > limit) throw new SafeError('RESPONSE_TOO_LARGE', 502);
  const reader = response.body?.getReader();
  if (!reader) throw new SafeError('INVALID_RESPONSE', 502);
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > limit) throw new SafeError('RESPONSE_TOO_LARGE', 502);
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch (error) {
    await reader.cancel().catch(() => {});
    if (error instanceof SafeError) throw error;
    throw new SafeError('INVALID_RESPONSE', 502);
  }
}
// Yahoo represents collections using arrays and numbered objects. Read only named nodes.
export function nodes(value, name) {
  const found = []; let visited = 0;
  function walk(v, depth) {
    if (++visited > 70000 || depth > 50) throw new SafeError('INVALID_RESPONSE', 502);
    if (!v || typeof v !== 'object') return;
    for (const [k, child] of Object.entries(v)) {
      if (k === name) found.push(child);
      else walk(child, depth + 1);
    }
  }
  walk(value, 0); return found;
}
export function fields(value) {
  if (!Array.isArray(value)) return value && typeof value === 'object' ? value : {};
  return Object.assign({}, ...value.map(v => fields(v)));
}
const text = (v, max = 200) => typeof v === 'string' || typeof v === 'number' ? String(v).slice(0, max) : '';
const number = v => ['string', 'number'].includes(typeof v) && String(v).trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : null;
export function parseTeams(raw) {
  const result = new Map();
  for (const value of nodes(raw, 'team')) {
    const t = fields(value), key = text(t.team_key, 60);
    if (TEAM_KEY.test(key)) result.set(key, { teamKey: key, name: text(t.name) || 'Yahoo team',
      leagueKey: key.split('.t.')[0] });
  }
  return [...result.values()].slice(0, 100);
}
export function parseLeague(raw) {
  const league = fields(nodes(raw, 'league')[0]);
  const settings = fields(nodes(league, 'settings')[0]);
  return {
    name: text(league.name) || 'Yahoo league', season: text(league.season),
    currentWeek: number(league.current_week),
    teams: text(settings.num_teams || league.num_teams),
    scoringType: text(settings.scoring_type || league.scoring_type), draftType: text(settings.draft_type),
    positions: nodes(settings.roster_positions, 'roster_position').map(x => {
      const p = fields(x); return { position: text(p.position, 25), count: text(p.count, 4) };
    }),
    scoring: (() => {
      const labels = new Map(nodes(settings.stat_categories, 'stat').map(x => {
        const s = fields(x); return [String(s.stat_id), text(s.display_name || s.name)];
      }));
      return nodes(settings.stat_modifiers, 'stat').map(x => {
        const s = fields(x); return { name: labels.get(String(s.stat_id)) || `Stat ${text(s.stat_id, 12)}`, value: text(s.value, 24) };
      });
    })(),
  };
}
export function parseRoster(raw, season = '') {
  const seen = new Set();
  return nodes(raw, 'player').map(value => {
    const p = fields(value), name = fields(p.name), selected = fields(p.selected_position);
    const points = fields(p.player_points), ownership = fields(p.ownership);
    const key = text(p.player_key, 60);
    if (PLAYER_KEY.test(key)) {
      if (seen.has(key)) throw new SafeError('INVALID_RESPONSE', 502);
      seen.add(key);
    }
    const eligible = [...new Set(nodes(p.eligible_positions, 'position').map(x => text(x, 20)))];
    const seasonMatches = points.coverage_type === 'season' && (!season || String(points.season) === season);
    return { name: text(name.full) || 'Player', position: text(p.display_position, 30),
      playerKey: PLAYER_KEY.test(key) ? key : '', eligible,
      team: text(p.editorial_team_abbr, 12), status: text(p.status, 40), slot: text(selected.position, 20),
      rosterWeek: number(selected.week), byeWeek: number(fields(p.bye_weeks).week),
      seasonPoints: seasonMatches ? number(points.total) : null,
      pointsSeason: seasonMatches ? text(points.season, 4) : '',
      ownership: ['freeagents', 'waivers', 'team'].includes(ownership.ownership_type) ? ownership.ownership_type : '',
      waiverDate: text(ownership.waiver_date, 40),
    };
  }).slice(0, 100);
}
export function parseLeagueTeams(raw, leagueKey, season) {
  const result = new Map();
  for (const value of nodes(raw, 'team')) {
    const t = fields(value), key = text(t.team_key, 60);
    if (!TEAM_KEY.test(key) || key.split('.t.')[0] !== leagueKey) continue;
    const standings = fields(t.team_standings), record = fields(standings.outcome_totals);
    result.set(key, { teamKey: key, name: text(t.name) || 'Yahoo team',
      rank: number(standings.rank), wins: number(record.wins), losses: number(record.losses), ties: number(record.ties),
      pointsFor: number(standings.points_for), pointsAgainst: number(standings.points_against),
      roster: parseRoster(t.roster, season), rosterAvailable: Boolean(t.roster),
      rosterWeek: number(fields(t.roster).week),
    });
  }
  return [...result.values()].slice(0, 32);
}
// Only the opponent's key leaves the scoreboard; scores and projections are not relayed.
export function parseMatchup(raw, teamKey, week) {
  for (const value of nodes(raw, 'matchup')) {
    const m = fields(value);
    if (number(m.week) !== week) continue;
    const keys = nodes(value, 'team').map(t => text(fields(t).team_key, 60)).filter(k => TEAM_KEY.test(k));
    if (keys.length === 2 && keys.includes(teamKey)) return { week, opponentKey: keys.find(k => k !== teamKey) || null };
  }
  return null;
}
async function yahoo(path, accessToken, fetcher) {
  const response = await fetcher(API + path + '?format=json', {
    headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
    signal: AbortSignal.timeout(12000), redirect: 'error', cache: 'no-store',
  });
  if (response.status === 401) throw new SafeError('SESSION_EXPIRED', 401);
  if (response.status === 403) throw new SafeError('YAHOO_ACCESS_DENIED', 403, await classifyDenial(response));
  if (response.status === 429) throw new SafeError('YAHOO_RATE_LIMIT', 429);
  if (!response.ok) throw new SafeError('YAHOO_UNAVAILABLE', 502);
  return boundedJSON(response, 2_000_000);
}
export async function handle(kind, request, { env, fetcher = fetch, now = () => Date.now() } = {}) {
  let response;
  try {
    // Disconnect must work even when a feature flag or credentials have been removed.
    if (kind === 'api') {
      sameOriginPost(request);
      const body = await boundedJSON(request, 2048);
      if (body.action === 'disconnect') {
        response = reply({ connected: false }); clear(response, SESSION_COOKIE); clear(response, STATE_COOKIE); return response;
      }
      const cfg = config(env);
      const session = unseal(readCookie(request, SESSION_COOKIE), 'session', cfg.sessionSecret, now());
      if (body.action === 'status') return reply({ connected: Boolean(session?.accessToken), configured: true, expiresAt: session?.exp ?? null });
      if (!session?.accessToken) throw new SafeError('SESSION_EXPIRED', 401);
      if (!['teams', 'league', 'command', 'available'].includes(body.action)) throw new SafeError('INVALID_ACTION');
      if (body.action !== 'teams' && !TEAM_KEY.test(body.teamKey || '')) throw new SafeError('INVALID_TEAM');
      if (body.action === 'available' &&
          (!POSITIONS.includes(body.position) || !['FA', 'W'].includes(body.pool) ||
           !Number.isInteger(body.start) || body.start < 0 || body.start > 475 || body.start % 25 !== 0))
        throw new SafeError('INVALID_FILTER');
      const teams = parseTeams(await yahoo('users;use_login=1/games;game_keys=nfl/teams', session.accessToken, fetcher));
      if (body.action === 'teams') return reply({ teams, expiresAt: session.exp });
      // Verify ownership on every request, without caching Yahoo team/league data.
      const team = teams.find(t => t.teamKey === body.teamKey);
      if (!team) throw new SafeError('TEAM_NOT_AUTHORIZED', 403);
      if (body.action === 'available') {
        // Build paths only from allowlisted filters. Never accept an arbitrary Yahoo path.
        const league = parseLeague(await yahoo(`league/${team.leagueKey}/settings`, session.accessToken, fetcher));
        if (!/^20\d{2}$/.test(league.season)) throw new SafeError('INVALID_RESPONSE', 502);
        const position = body.position === 'ALL' ? '' : `;position=${body.position}`;
        const raw = await yahoo(`league/${team.leagueKey}/players;status=${body.pool}${position};sort=PTS;sort_type=season;sort_season=${league.season};start=${body.start};count=25;out=stats,ownership`, session.accessToken, fetcher);
        const returned = parseRoster(raw, league.season);
        const pool = body.pool === 'FA' ? 'freeagents' : 'waivers';
        // Ownership can change during the request. Do not recommend a known taken player.
        const players = returned.filter(p => p.playerKey && (!p.ownership || p.ownership === pool))
          .map(p => ({ ...p, ownership: p.ownership || pool }));
        return reply({ teamKey: team.teamKey, leagueKey: team.leagueKey, season: league.season, players,
          pool: body.pool, position: body.position, start: body.start, pageSize: 25,
          hasMore: returned.length === 25 && body.start < 475, limitReached: returned.length === 25 && body.start === 475,
          fetchedAt: new Date(now()).toISOString() });
      }
      if (body.action === 'command') {
        const league = parseLeague(await yahoo(`league/${team.leagueKey}/settings`, session.accessToken, fetcher));
        if (!/^20\d{2}$/.test(league.season) || !Number.isInteger(league.currentWeek) || league.currentWeek < 1 || league.currentWeek > 18)
          throw new SafeError('NO_CURRENT_WEEK', 422);
        const results = await Promise.allSettled([
          yahoo(`league/${team.leagueKey}/standings`, session.accessToken, fetcher),
          yahoo(`league/${team.leagueKey}/teams/roster;week=${league.currentWeek}/players/stats`, session.accessToken, fetcher),
          yahoo(`league/${team.leagueKey}/scoreboard;week=${league.currentWeek}`, session.accessToken, fetcher),
        ]);
        // Never swallow an expired session, access denial, or rate limit as an empty roster.
        for (const r of results.slice(0, 2)) if (r.status === 'rejected' && [401, 403, 429].includes(r.reason?.status)) throw r.reason;
        // The scoreboard is optional (e.g. leagues without head-to-head), but an expired session or rate limit still stops here.
        if (results[2].status === 'rejected' && [401, 429].includes(results[2].reason?.status)) throw results[2].reason;
        if (results.slice(0, 2).every(r => r.status === 'rejected')) throw new SafeError('YAHOO_UNAVAILABLE', 502);
        const matchup = results[2].status === 'fulfilled' ? parseMatchup(results[2].value, team.teamKey, league.currentWeek) : null;
        const standings = results[0].status === 'fulfilled' ? parseLeagueTeams(results[0].value, team.leagueKey, league.season) : [];
        const rosters = results[1].status === 'fulfilled' ? parseLeagueTeams(results[1].value, team.leagueKey, league.season) : [];
        for (const roster of rosters) {
          if (roster.rosterWeek !== league.currentWeek || roster.roster.some(p => p.rosterWeek !== null && p.rosterWeek !== league.currentWeek)) {
            roster.rosterAvailable = false; roster.roster = [];
          }
        }
        const rosterMap = new Map(rosters.map(t => [t.teamKey, t]));
        const combined = new Map(standings.map(t => [t.teamKey, { ...t, roster: rosterMap.get(t.teamKey)?.roster || [],
          rosterAvailable: rosterMap.get(t.teamKey)?.rosterAvailable || false, rosterWeek: rosterMap.get(t.teamKey)?.rosterWeek ?? null }]));
        for (const t of rosters) if (!combined.has(t.teamKey)) combined.set(t.teamKey, t);
        const allTeams = [...combined.values()];
        if (!allTeams.some(t => t.teamKey === team.teamKey)) throw new SafeError('INVALID_RESPONSE', 502);
        const warnings = [];
        if (!standings.length) warnings.push('Standings could not be loaded. Missing results are not zero.');
        if (allTeams.some(t => !t.rosterAvailable)) warnings.push('Some current lineups could not be loaded. Refresh to retry.');
        if (allTeams.length !== number(league.teams)) warnings.push('Yahoo returned partial team coverage. Do not treat this as a complete league comparison.');
        return reply({ team, league, teams: allTeams, warnings,
          matchup: matchup && allTeams.some(t => t.teamKey === matchup.opponentKey) ? matchup : null,
          coverage: { returnedTeams: allTeams.length, expectedTeams: number(league.teams), rosterTeams: allTeams.filter(t => t.rosterAvailable).length },
          fetchedAt: new Date(now()).toISOString() });
      }
      const [leagueRaw, rosterRaw] = await Promise.all([
        yahoo(`league/${team.leagueKey}/settings`, session.accessToken, fetcher),
        yahoo(`team/${team.teamKey}/roster`, session.accessToken, fetcher),
      ]);
      return reply({ team, league: parseLeague(leagueRaw), roster: parseRoster(rosterRaw), fetchedAt: new Date(now()).toISOString() });
    }
    if (kind === 'start') {
      sameOriginPost(request);
      const cfg = config(env);
      const state = randomBytes(32).toString('base64url'), verifier = randomBytes(48).toString('base64url');
      const url = new URL(AUTH_URL);
      Object.entries({ client_id: cfg.clientId, redirect_uri: CALLBACK, response_type: 'code', scope: 'fspt-r',
        state, code_challenge: createHash('sha256').update(verifier).digest('base64url'), code_challenge_method: 'S256' })
        .forEach(([key, value]) => url.searchParams.set(key, value));
      response = reply({ authorizationUrl: url.toString() });
      response.headers.append('Set-Cookie', cookie(STATE_COOKIE, seal({ state, verifier, exp: now() + 600000 }, 'state', cfg.sessionSecret), 600));
      return response;
    }
    if (kind !== 'callback' || request.method !== 'GET' || new URL(request.url).origin !== ORIGIN)
      throw new SafeError('METHOD_NOT_ALLOWED', 405);
    const cfg = config(env), url = new URL(request.url);
    const saved = unseal(readCookie(request, STATE_COOKIE), 'state', cfg.sessionSecret, now());
    const state = url.searchParams.get('state') || '';
    if (!saved?.state || state.length !== saved.state.length ||
        !timingSafeEqual(Buffer.from(state), Buffer.from(saved.state))) throw new SafeError('INVALID_STATE');
    if (url.searchParams.has('error')) throw new SafeError('AUTH_DECLINED');
    const code = url.searchParams.get('code');
    if (!code || code.length > 2048) throw new SafeError('MISSING_CODE');
    const tokenResponse = await fetcher(TOKEN_URL, {
      method: 'POST', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(12000),
      headers: { Authorization: `Basic ${Buffer.from(`${cfg.clientId}:${cfg.clientSecret}`).toString('base64')}`,
        'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: new URLSearchParams({ grant_type: 'authorization_code', code, redirect_uri: CALLBACK, code_verifier: saved.verifier }).toString(),
    });
    if (!tokenResponse.ok) throw new SafeError('TOKEN_EXCHANGE_FAILED', 502);
    const token = await boundedJSON(tokenResponse, 32000);
    const ttl = Math.min(3600, Math.floor(Number(token.expires_in)));
    if (typeof token.access_token !== 'string' || !token.access_token || !Number.isFinite(ttl) || ttl < 1 ||
        (token.token_type && token.token_type.toLowerCase() !== 'bearer')) throw new SafeError('INVALID_TOKEN', 502);
    // Deliberately discard refresh tokens. No background access or persistent fantasy data store.
    const encrypted = seal({ accessToken: token.access_token, exp: now() + ttl * 1000 }, 'session', cfg.sessionSecret);
    if (encrypted.length > 3500) throw new SafeError('INVALID_TOKEN', 502);
    response = new Response(null, { status: 303, headers: { ...SECURE_HEADERS, Location: '/yahoo/?connected=1' } });
    response.headers.append('Set-Cookie', cookie(SESSION_COOKIE, encrypted, ttl));
    clear(response, STATE_COOKIE); return response;
  } catch (error) {
    const code = error instanceof SafeError ? error.code : 'TEMPORARY_ERROR';
    const status = error instanceof SafeError ? error.status : 502;
    // Never reflect upstream payloads, exception messages, authorization codes, or tokens.
    response = kind === 'callback'
      ? new Response(null, { status: 303, headers: { ...SECURE_HEADERS, Location: `/yahoo/?error=${code}` } })
      : reply({ error: code, ...(code === 'YAHOO_ACCESS_DENIED' && DENIAL_REASONS.includes(error.diagnostic) ? { diagnostic: error.diagnostic } : {}) }, status);
    if (kind === 'callback') clear(response, STATE_COOKIE);
    if (status === 401) clear(response, SESSION_COOKIE);
    if (status === 429) response.headers.set('Retry-After', '60');
    return response;
  }
}
