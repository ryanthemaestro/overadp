// Diagnostic categories only. Never return/log the upstream body, URL, token,
// account identifiers, manager details or private fantasy data.
export const DENIAL_REASONS = Object.freeze([
  'APPLICATION_NOT_AUTHORIZED', 'INSUFFICIENT_SCOPE', 'RESOURCE_ACCESS_DENIED',
  'INVALID_GAME_KEY', 'ACCOUNT_NOT_AUTHORIZED', 'TOKEN_REJECTED',
  'HTML_REJECTION', 'UNCLASSIFIED',
]);
const limit = 8192;
async function boundedErrorText(response) {
  const reader = response.body?.getReader();
  if (!reader) return '';
  let size = 0; const chunks = [];
  try {
    if (Number(response.headers.get('content-length')) > limit) return '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > limit) return '';
      chunks.push(value);
    }
    return Buffer.concat(chunks).toString('utf8');
  } finally { await reader.cancel().catch(() => {}); }
}
export async function classifyDenial(response) {
  try {
    const raw = await boundedErrorText(response);
    if (!raw) return 'UNCLASSIFIED';
    // Distinguish an HTML rejection without guessing it is an app permission.
    if (/^\s*(?:<!doctype html\b|<html\b)/i.test(raw)) return 'HTML_REJECTION';
    let descriptions = [];
    try {
      const data = JSON.parse(raw);
      const error = data?.error;
      const node = error && typeof error === 'object' && !Array.isArray(error) ? error : {};
      descriptions = [typeof error === 'string' ? error : '', node.code, node.description, node.message, data?.error_description]
        .filter(value => typeof value === 'string');
    } catch {
      // Yahoo also serves XML errors. Inspect only its explicit description.
      if (/^\s*(?:<\?xml[^>]*>\s*)?<error\b/i.test(raw)) {
        descriptions = [...raw.matchAll(/<description>([^<]*)<\/description>/gi)].map(m => m[1]);
      }
    }
    const description = descriptions.join(' ').toLowerCase();
    if (/\b(?:this|the) application is not authorized(?: to perform this action)?\b/.test(description)) return 'APPLICATION_NOT_AUTHORIZED';
    if (/\binsufficient[_ ]scope\b|\b(?:missing|required) oauth scope\b/.test(description)) return 'INSUFFICIENT_SCOPE';
    if (/\baccount_not_authorized\b/.test(description)) return 'ACCOUNT_NOT_AUTHORIZED';
    if (/\binvalid game (?:key|id)\b/.test(description)) return 'INVALID_GAME_KEY';
    if (/\b(?:invalid_token|token_expired|token_rejected)\b|\baccess token (?:has expired|is invalid)\b/.test(description)) return 'TOKEN_REJECTED';
    if (/\bnot a member of (?:this|the) league\b|\b(?:you|user) (?:is|are) not allowed to (?:access|view)\b/.test(description)) return 'RESOURCE_ACCESS_DENIED';
  } catch { /* Transport, parsing or cancellation failure: retain safe fallback. */ }
  return 'UNCLASSIFIED';
}
