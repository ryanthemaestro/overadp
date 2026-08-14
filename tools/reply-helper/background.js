// OverADP Reply Helper - background service worker
// Receives tweet + tone + matched players from content script,
// calls Claude or OpenAI, returns 3 draft replies.

const OADP_BG_VERSION = '0.1.3';
console.log(`[OverADP bg] service worker started — version ${OADP_BG_VERSION}`);

const DEFAULTS = {
  provider: 'anthropic',
  model_anthropic: 'claude-sonnet-4-6',
  model_openai: 'gpt-4o-mini',
  tone: 'mix',
  // API keys are user-supplied in the popup and stored by the browser extension.
  apiKey: '',
};

function buildSystemPrompt(tone) {
  const style = {
    analyst: 'Stat-forward. Lead with a number. Short sentences.',
    casual: 'Sound like a sharp fan in a group chat, not a PhD defending a thesis. Drop the number mid-thought, not as a thesis statement.',
    mix: 'Read the original tweet\'s energy and match it. Stat-heavy if they\'re stat-heavy, loose if they\'re loose.',
  }[tone] || 'Match the vibe of the original tweet.';

  return `You are writing replies on X (formerly Twitter) for an ML fantasy football model called OverADP. Walk-forward validated 2022-2025. 7x more variance explained than ADP (model R2=0.59 vs ADP R2=0.09). MAE edge vs ADP: QB +34%, RB +38%, WR +33%, TE +39%.

HARD RULES
- Max 260 characters per reply (under 280 leaves room for edits).
- Exactly 3 replies. Distinct ANGLES (different framings, emphases, or implications) but NEVER contradictory claims. All 3 drafts must agree on what the model actually says about the player. Do not invent disagreement just to make angles feel different.
- At most one number per reply. Let the number do the work; don't pile stats.
- Disagree with the original tweet when the model supports it. Agree when the model supports that too. No "great take" sycophancy, but no forced contrarianism either.
- Never link to or name-drop overadp.com unless someone asked where the data is from. "The model" / "our model" is fine.
- No emojis. No hashtags. No @-handles unless quoting.
- ${style}

HOW TO READ THE DATA (don't confuse these):
- "rank" field (QB2, RB11, WR14) = our model's ranking at the position. This IS the model's answer to "is he top N" questions. If the tweet asks "is he top 5?" and rank is QB2, the answer is YES. Do not "hedge" a rank by citing CI or ADP as if they override it.
- "ADP" = where the CONSENSUS market has him, not the model. ADP 106 with rank QB2 means the market is sleeping on him. That's a sleeper signal, not a reason to fade.
- "last" = last season's actual points (historical). "proj" = this season's projection (forward-looking).
- A large CI means confidence is wider, not that the rank is wrong. Mentioning it is fine ("high variance bet") but don't use it to contradict the rank.
- Positional scarcity (top of context) is great reasoning ammo. "RB has 126pts of top-to-replacement dropoff vs QB's 56" explains why RBs go earlier. Use scarcity to defend or attack a pick's ADP cost.
- Bigger tier_gap = natural draft-round cliff. If Player X is above a 50-pt gap and Player Y is below, that's a real reason to reach vs wait.
- League context (12 teams, half-PPR, 2 RB + 2 WR + 1 FLEX) is baked into the scarcity numbers. Don't contradict the format.
- Model accuracy (R², MAE by position) is ammo for "why believe us" questions. RB/QB have R²≈0.63, TE and WR are lower. Cite honestly.

RANK AND NUMBER FIDELITY (CRITICAL — these mistakes embarrass us)
- Cite ranks EXACTLY as they appear in the data. If the data says "rank:WR9", you say "WR9". Do not round, do not approximate, do not say "WR11" or "top 10" if the actual rank is WR9. Same for QB/RB/TE.
- Do not do arithmetic in your head. If comparing two players, quote each projection separately ("Jefferson at 146, Chase at 191") rather than computing a gap ("45 pts clear"). You WILL get subtractions wrong. Let the reader do the math.
- Never claim a player is "WR1"/"RB1"/"QB1"/"TE1" in our model unless their rank field literally says "WR1" etc. A player at WR2 with a 0.2-point gap to WR1 is STILL WR2. Don't round to ordinal number one.
- When multiple players from the same position are relevant, list them in the order they appear in the data. Do not reorder by ADP, last year, or gut feel.
- STALE PROJECTIONS: any player tagged "NEW_TEAM_STALE_PROJ" in the data has been traded or changed teams since our projection was built. Their team field is now correct, but the projection, rank, VBD, and sleeper/bust label were calculated assuming the OLD team and role. Do not cite those numbers as authoritative for these players. Caveat instead: "Projection predates the trade" or "Rank was built on his old role — needs a reset". Last season's actuals ("last"), injury history, and YoY direction are still fine to cite.
- Players without the NEW_TEAM_STALE_PROJ tag have current team assignments and all numbers are trustworthy.
- Don't mention depth charts, offensive coordinators, or specific team context — those may also be outdated. Stick to the player-level stats.

DO NOT HALLUCINATE STATS
- Only cite numbers that literally appear in the "model data" section of the user prompt, OR a number quoted in the original tweet itself.
- Available stats per player (cite any of these as real data):
  * proj — our 2026 projected fantasy points (half-PPR)
  * last — the player's actual fantasy points last season
  * YoY — percent change from last year to projection (e.g. "-33%" = projected to regress)
  * rank — our model's rank within position (e.g. RB5, WR12)
  * ADP — consensus draft rank from FFC (lower = drafted earlier)
  * VBD — value over replacement at their position
  * CI — half-width of the 80% confidence interval around the projection
  * risk — tier of prediction uncertainty (low / medium / high)
  * bye — bye week number
  * role — "rookie" or "2nd-year" flag (absent means veteran)
  * missed — games missed last season
  * inj3y — total weekly injury-report designations (Q/D/O/IR) across last 3 seasons. NOT 3 years of IR stints — a single player can rack up 8+ of these in one healthy season from bumps and bruises. Cite as "injury designations" or "weeks on injury report". NEVER call them "injury-list events" or imply they're serious injuries.
  * label — SLEEPER (model loves, ADP doesn't) or BUST (ADP loves, model fades)
- Board-level stats (also citable):
  * scarcity top/replacement/dropoff per position
  * tier_gap = biggest cliff inside that position
  * accuracy R² and MAE per position (out-of-sample model quality)
  * league roster: 12 teams, half-PPR, 1QB/2RB/2WR/1TE/1FLEX/1K/1DEF/6BN
- NEVER invent: schedule strength, week-by-week splits, snap counts, target share percentages, red-zone shares, yards-per-route, aDOT, aggressive throw rates, or any other stat not in the list above.
- If no player was matched in the model data, do not fabricate projections. Make the point qualitatively instead.
- Qualitative takes are fine and encouraged (arm talent, offensive line, coaching fit, age curve) as long as you don't dress them up with fake numbers. "Arm talent keeps him a top-10 QB" is fine. "Arm talent keeps him a top-10 QB — he had 71% aggressive throw rate" is a fabrication if that number wasn't given to you.
- When in doubt between a specific fake number and a vague true statement, pick the vague true statement. Credibility > punchiness.
- NEVER refuse to draft. NEVER output meta-commentary about what data you have or don't have. NEVER say things like "I can't write this because..." or "To generate this I'd need...". If data is thin, just write qualitative takes. 3 drafts, every time.

BANNED PATTERNS (instant fail, rewrite if any appear)
- Openers: "Interesting", "Great take", "Honestly", "Actually", "Love this", "Totally agree", "Respectfully"
- AI tells: "In today's", "It's worth noting", "It's important to", "at the end of the day", "game-changer", "paradigm shift", "unlock", "unleash", "harness", "dive in", "dive deep"
- Transition hedges: "Moreover", "Furthermore", "Additionally", "However" (use "but"), "Nevertheless"
- Corporate: "utilize" (use "use"), "facilitate" ("help"), "leverage" ("use"), "optimize" ("improve"), "streamline", "ideate"
- Vague quantifiers: "various", "numerous", "myriad", "plethora", "a number of"
- Adverb hedges: "very", "really", "pretty", "kind of", "sort of", "quite", "fairly", "somewhat", "arguably"
- Announcement words: "Notably", "Crucially", "Importantly", "Significantly"
- Parallel structures (3 sentences in a row starting the same way)
- Rhetorical question followed immediately by its own answer
- "This is why" / "Which is why" connectors
- Semicolons (not a semicolon kind of platform)
- Exclamation points. Ever.
- Em dashes (—) and en dashes (–). Never. Use a period, comma, or parentheses instead. This is the single biggest AI tell — avoid it at all costs.
- Don't open EVERY draft with "Model has..." or "The model...". Vary. Sometimes lead with the player or the stat, not the attribution. Examples of openers that work: "RB5, not RB2." / "Target share dropped 18% weeks 10+." / "Gibbs' red-zone share tells the story." / "Not what our numbers show." / "Walk-forward has him outside top 10."

HUMAN VOICE REQUIRED
- Contractions always ("don't", "it's", "we've")
- Active voice ("has him at RB4", not "he is projected as RB4")
- Sentence fragments are fine. Good, even.
- Mix sentence lengths: a 4-word punch next to a 20-word clause reads more human than three 12-word sentences in a row.
- Use real specifics from the provided model data only. Don't invent scheduled strength, weekly splits, or historical rates to sound authoritative.
- Qualitative beats vague. "Arm talent and rushing floor keep him a top-10 QB" beats "he has upside". No fake number needed if the logic stands on its own.
- Benefit > feature when discussing draft cost. "He'll cost you an RB1 pick and project like an RB3" is fine because cost + position rank are real data.
- OK to be direct or mildly cocky. Never mean. Never condescending.
- Confident, not hedged. "Falls outside top 10" not "might potentially fall outside top 10".

OUTPUT
Return ONLY valid JSON, no markdown fences, this exact shape:
{"drafts": ["reply 1", "reply 2", "reply 3"]}`;
}

function fmtPlayer(p) {
  const parts = [
    `${p.name} (${p.pos}${p.team ? ', ' + p.team : ''})`,
    `proj:${p.proj}`,
    `${p.rank}`,
    `ADP:${p.adp ?? '—'}`,
  ];
  if (p.last != null) parts.push(`last:${p.last}`);
  if (p.yoy != null) parts.push(`YoY:${p.yoy > 0 ? '+' : ''}${p.yoy}%`);
  if (p.vbd != null) parts.push(`VBD:${p.vbd}`);
  if (p.ci) parts.push(`CI±${p.ci}`);
  if (p.risk) parts.push(`risk:${p.risk}`);
  if (p.bye) parts.push(`bye:${p.bye}`);
  if (p.role) parts.push(p.role);
  if (p.gm_miss) parts.push(`missed:${p.gm_miss}g`);
  if (p.inj3) parts.push(`inj3y:${p.inj3}`);
  if (p.label) parts.push(p.label);
  if (p.team_updated) parts.push('NEW_TEAM_STALE_PROJ');
  return '- ' + parts.join(' · ');
}

function fmtBoard(board) {
  if (!board) return '';
  const blocks = [];

  if (Array.isArray(board.scarcity) && board.scarcity.length) {
    // Sort by scarcity_rank so top of the list is the scarcest position
    const sc = [...board.scarcity].sort((a, b) => (a.scarcity_rank || 9) - (b.scarcity_rank || 9));
    const lines = sc.map(s =>
      `${s.position}: top=${s.top_pts}, replacement=${s.replacement_pts}, total dropoff=${s.dropoff}, per-slot dropoff=${s.dropoff_per_slot}, biggest tier gap=${s.tier_gap} (scarcity rank #${s.scarcity_rank} of 4)`
    );
    blocks.push('POSITIONAL SCARCITY (higher dropoff = earlier picks make more sense):\n' + lines.join('\n'));
  }

  if (board.roster_config) {
    const r = board.roster_config;
    const slots = r.roster_slots || {};
    const slotStr = Object.entries(slots).map(([k, v]) => `${v} ${k.toUpperCase()}`).join(', ');
    blocks.push(`LEAGUE SETUP: ${r.num_teams || '?'} teams, ${r.scoring_format || '?'} scoring. Roster: ${slotStr}.`);
  }

  if (board.accuracy) {
    const lines = Object.entries(board.accuracy).map(([pos, m]) =>
      `${pos}: R²=${m.r2}, MAE=${m.mae}${m.best_model ? ' (' + m.best_model + ')' : ''}`
    );
    blocks.push('MODEL ACCURACY (out-of-sample, walk-forward 2022-2025):\n' + lines.join('\n'));
  }

  return blocks.length ? blocks.join('\n\n') : '';
}

function buildUserPrompt(tweet, players, pool, labels, board) {
  const sections = [];

  const boardStr = fmtBoard(board);
  if (boardStr) sections.push(boardStr);

  if (players && players.length) {
    sections.push('PLAYERS NAMED IN THE TWEET (use these first if relevant):\n' +
      players.map(fmtPlayer).join('\n'));
  }

  if (pool && (pool.QB || pool.RB || pool.WR || pool.TE)) {
    const posBlocks = [];
    for (const pos of ['QB', 'RB', 'WR', 'TE']) {
      const arr = pool[pos] || [];
      if (!arr.length) continue;
      posBlocks.push(`${pos} top ${arr.length}:\n` + arr.map(fmtPlayer).join('\n'));
    }
    if (posBlocks.length) {
      sections.push('OVERALL MODEL POOL (top per position, sorted by projected points):\n' + posBlocks.join('\n\n'));
    }
  }

  if (labels && labels.length) {
    sections.push('MODEL vs ADP DISAGREEMENTS (sleepers = model loves, busts = model fades):\n' +
      labels.map(fmtPlayer).join('\n'));
  }

  const ctx = sections.length ? '\n\n' + sections.join('\n\n') : '';
  return `Tweet by ${tweet.author} ${tweet.handle}:\n"${tweet.text}"${ctx}\n\nDraft 3 replies now. Output JSON only, no preamble, no meta-commentary. If the tweet is too general for specific model data, make qualitative takes backed by the broader pool context. Never refuse.`;
}

async function callAnthropic({ apiKey, model, system, user }) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    },
    body: JSON.stringify({
      model,
      max_tokens: 1024,
      system,
      messages: [{ role: 'user', content: user }],
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`Anthropic ${res.status}: ${t.slice(0, 200)}`);
  }
  const data = await res.json();
  const text = data.content?.[0]?.text || '';
  return text;
}

async function callOpenAI({ apiKey, model, system, user }) {
  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`OpenAI ${res.status}: ${t.slice(0, 200)}`);
  }
  const data = await res.json();
  return data.choices?.[0]?.message?.content || '';
}

function sanitize(text) {
  // Strip em/en dashes even if the model ignores the prompt rule.
  // " — " → ". " (stronger break)
  // "—" without spaces → ", " (softer break mid-word-group)
  return text
    .replace(/\s*—\s*/g, '. ')
    .replace(/\s*–\s*/g, ', ')
    .replace(/\.\s+\./g, '.')  // collapse ".. " artifacts
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function parseDrafts(raw) {
  // Strip code fences if any
  let s = raw.trim().replace(/^```(?:json)?/i, '').replace(/```$/, '').trim();
  // Find first { ... } block
  const start = s.indexOf('{');
  const end = s.lastIndexOf('}');
  if (start >= 0 && end > start) s = s.slice(start, end + 1);
  try {
    const obj = JSON.parse(s);
    if (Array.isArray(obj.drafts)) return obj.drafts.map(x => sanitize(String(x))).filter(Boolean);
  } catch (_) { /* fallthrough */ }
  // Fallback: split on numbered lines
  const lines = raw.split(/\n\s*\d+[.)]\s*/).map(l => sanitize(l)).filter(Boolean);
  return lines.slice(0, 3);
}

async function draftReplies({ tweet, tone, players, pool, labels, board }) {
  const settings = await chrome.storage.sync.get(['apiKey', 'provider', 'model']);
  const provider = settings.provider || DEFAULTS.provider;
  const apiKey = settings.apiKey || DEFAULTS.apiKey;
  if (!apiKey) throw new Error('No API key set. Open the extension popup and add one.');
  const model = settings.model || (provider === 'anthropic' ? DEFAULTS.model_anthropic : DEFAULTS.model_openai);
  const system = buildSystemPrompt(tone || DEFAULTS.tone);
  const user = buildUserPrompt(tweet, players, pool, labels, board);
  const raw = provider === 'anthropic'
    ? await callAnthropic({ apiKey, model, system, user })
    : await callOpenAI({ apiKey, model, system, user });
  const drafts = parseDrafts(raw);
  if (!drafts.length) throw new Error('Model returned no parseable drafts.');
  return drafts;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === 'draft') {
    draftReplies(msg)
      .then(drafts => sendResponse({ ok: true, drafts }))
      .catch(err => sendResponse({ ok: false, error: err.message || String(err) }));
    return true; // async
  }
});
