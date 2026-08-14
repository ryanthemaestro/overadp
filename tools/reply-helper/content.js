// OverADP Reply Helper - content script
// Runs on x.com / twitter.com. Watches for tweets, injects "Δ Draft" button,
// extracts tweet text on click, sends to background for LLM drafting.

(() => {
  console.log('%c[OverADP Reply Helper] loaded. version 0.1.3', 'color:#00ff6a;font-weight:bold');
  const PROCESSED_ATTR = 'data-oadp-processed';
  let playersCompact = null;
  let board = null;

  // Lazy-load compact player stats + board context (bundled with extension)
  fetch(chrome.runtime.getURL('players_compact.json'))
    .then(r => r.json())
    .then(data => { playersCompact = data; })
    .catch(e => console.warn('[OverADP] players_compact.json missing', e));
  fetch(chrome.runtime.getURL('board.json'))
    .then(r => r.json())
    .then(data => { board = data; })
    .catch(e => console.warn('[OverADP] board.json missing', e));

  // ---------- DOM scanning ----------

  function extractTweet(article) {
    const textEl = article.querySelector('[data-testid="tweetText"]');
    const userEl = article.querySelector('[data-testid="User-Name"]');
    if (!textEl) return null;
    const text = textEl.innerText.trim();
    let author = 'someone';
    let handle = '';
    if (userEl) {
      const lines = userEl.innerText.split('\n').filter(Boolean);
      author = lines[0] || 'someone';
      const handleLine = lines.find(l => l.startsWith('@'));
      if (handleLine) handle = handleLine.trim();
    }
    return { text, author, handle };
  }

  function mentionedPlayers(text) {
    if (!playersCompact) return [];
    const t = text.toLowerCase();
    const hits = [];
    for (const p of playersCompact) {
      // Match full name OR "last name" if last name is >= 5 chars (to avoid false hits on "Kelce" style)
      const full = p.name.toLowerCase();
      const last = full.split(' ').slice(1).join(' ');
      if (t.includes(full) || (last.length >= 5 && t.includes(last))) {
        hits.push(p);
        if (hits.length >= 6) break;
      }
    }
    return hits;
  }

  // Position-ranked pool: top N per position so the model can answer rank/tier
  // questions even when no specific player is named in the tweet.
  function positionPool(topN = 30) {
    if (!playersCompact) return { QB: [], RB: [], WR: [], TE: [] };
    const pool = { QB: [], RB: [], WR: [], TE: [] };
    for (const p of playersCompact) {
      if (pool[p.pos] && pool[p.pos].length < topN) pool[p.pos].push(p);
    }
    return pool;
  }

  // Sleepers/busts: model vs ADP disagreement. Always relevant to "breakout",
  // "value", "bust" style tweets.
  function labeled() {
    if (!playersCompact) return [];
    return playersCompact.filter(p => p.label);
  }

  // ---------- Button injection ----------

  function findActionBar(article) {
    // X's DOM: each tweet has multiple role=group divs. The one we want contains
    // the reply button (data-testid="reply"). Walk up from it to find the group container.
    const replyBtn = article.querySelector('[data-testid="reply"]');
    if (replyBtn) {
      let el = replyBtn;
      for (let i = 0; i < 6 && el; i++) {
        if (el.getAttribute && el.getAttribute('role') === 'group') return el;
        el = el.parentElement;
      }
    }
    // Fallback: last role=group in the article (historically the actions bar)
    const groups = article.querySelectorAll('[role="group"]');
    if (groups.length) return groups[groups.length - 1];
    return null;
  }

  function injectButton(article) {
    if (article.getAttribute(PROCESSED_ATTR)) return;
    const actionBar = findActionBar(article);
    if (!actionBar) return; // tweet not fully rendered yet; observer will catch it
    article.setAttribute(PROCESSED_ATTR, '1');

    const btn = document.createElement('button');
    btn.className = 'oadp-draft-btn';
    btn.innerHTML = '<span class="oadp-delta">Δ</span> Draft';
    btn.title = 'Draft OverADP reply';
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const tweet = extractTweet(article);
      if (!tweet) { alert('Could not read tweet text'); return; }
      openDraftOverlay(tweet);
    });
    // Wrap in a div so flex layout of the action bar doesn't squish it
    const wrap = document.createElement('div');
    wrap.className = 'oadp-btn-wrap';
    wrap.appendChild(btn);
    actionBar.appendChild(wrap);
  }

  // ---------- Draft overlay ----------

  function openDraftOverlay(tweet) {
    const existing = document.getElementById('oadp-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'oadp-overlay';
    overlay.innerHTML = `
      <div class="oadp-modal">
        <div class="oadp-head">
          <div class="oadp-title"><span class="oadp-delta">Δ</span> OverADP Drafts</div>
          <button class="oadp-close" aria-label="Close">×</button>
        </div>
        <div class="oadp-src">
          <div class="oadp-src-author">${escapeHtml(tweet.author)} ${escapeHtml(tweet.handle)}</div>
          <div class="oadp-src-text">${escapeHtml(tweet.text)}</div>
        </div>
        <div class="oadp-controls">
          <label>Tone
            <select id="oadp-tone">
              <option value="mix">Mix (data + casual)</option>
              <option value="analyst">Analyst (stats-heavy)</option>
              <option value="casual">Casual (data receipts)</option>
            </select>
          </label>
          <button id="oadp-regen" class="oadp-btn">Generate</button>
        </div>
        <div id="oadp-drafts" class="oadp-drafts"><div class="oadp-empty">Click Generate for 3 drafts.</div></div>
        <div class="oadp-footer">Drafts reference your model. You post manually — stays within X's ToS.</div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector('.oadp-close').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    // Restore tone preference (safe if extension context got invalidated)
    try {
      if (chrome.runtime?.id) {
        chrome.storage.sync.get(['tone'], ({ tone }) => {
          if (chrome.runtime.lastError) return;
          if (tone) overlay.querySelector('#oadp-tone').value = tone;
        });
      }
    } catch (_) { /* invalidated; ignore */ }

    const regen = () => {
      // Guard against "extension context invalidated" after reload
      if (!chrome.runtime?.id) {
        renderDrafts(overlay, 'error', 'Extension was reloaded. Hard-refresh this tab (Ctrl+Shift+R) to reconnect.');
        return;
      }
      const tone = overlay.querySelector('#oadp-tone').value;
      try { chrome.storage.sync.set({ tone }); } catch (_) {}
      const players = mentionedPlayers(tweet.text);
      const pool = positionPool(50);
      const labels = labeled();
      renderDrafts(overlay, 'loading');
      try {
        chrome.runtime.sendMessage(
          { type: 'draft', tweet, tone, players, pool, labels, board },
          (resp) => {
            if (chrome.runtime.lastError) {
              const msg = chrome.runtime.lastError.message || '';
              if (msg.includes('context invalidated') || msg.includes('Receiving end')) {
                renderDrafts(overlay, 'error', 'Extension was reloaded. Hard-refresh this tab (Ctrl+Shift+R) to reconnect.');
              } else {
                renderDrafts(overlay, 'error', msg);
              }
              return;
            }
            if (!resp || !resp.ok) {
              renderDrafts(overlay, 'error', resp ? resp.error : 'No response');
              return;
            }
            renderDrafts(overlay, 'ok', resp.drafts);
          }
        );
      } catch (e) {
        renderDrafts(overlay, 'error', 'Extension was reloaded. Hard-refresh this tab (Ctrl+Shift+R) to reconnect.');
      }
    };
    overlay.querySelector('#oadp-regen').addEventListener('click', regen);
    regen(); // auto-run on open
  }

  function renderDrafts(overlay, state, payload) {
    const wrap = overlay.querySelector('#oadp-drafts');
    if (state === 'loading') {
      wrap.innerHTML = '<div class="oadp-empty">Drafting… (2-5s)</div>';
      return;
    }
    if (state === 'error') {
      wrap.innerHTML = `<div class="oadp-error">Error: ${escapeHtml(payload || 'unknown')}<br>Check your API key in the extension popup.</div>`;
      return;
    }
    const drafts = Array.isArray(payload) ? payload : [];
    if (!drafts.length) { wrap.innerHTML = '<div class="oadp-empty">No drafts returned.</div>'; return; }
    wrap.innerHTML = drafts.map((d, i) => `
      <div class="oadp-draft">
        <div class="oadp-draft-num">#${i + 1} · ${d.length} chars</div>
        <div class="oadp-draft-text">${escapeHtml(d)}</div>
        <div class="oadp-draft-actions">
          <button class="oadp-btn oadp-copy" data-text="${escapeHtml(d)}">Copy</button>
        </div>
      </div>
    `).join('');
    wrap.querySelectorAll('.oadp-copy').forEach(b => {
      b.addEventListener('click', () => {
        const txt = b.getAttribute('data-text');
        // Unescape entities back to original text for clipboard
        const tmp = document.createElement('textarea');
        tmp.innerHTML = txt;
        navigator.clipboard.writeText(tmp.value).then(() => {
          b.textContent = 'Copied ✓';
          setTimeout(() => { b.textContent = 'Copy'; }, 1500);
        });
      });
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------- Mutation observer ----------

  function scan(root = document) {
    const articles = root.querySelectorAll('article[data-testid="tweet"]');
    articles.forEach(injectButton);
  }
  scan();
  const obs = new MutationObserver((muts) => {
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1) {
          if (n.matches && n.matches('article[data-testid="tweet"]')) injectButton(n);
          else if (n.querySelectorAll) scan(n);
        }
      }
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });
})();
