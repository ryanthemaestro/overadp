import snapshot from '../../site/yahoo/nflverse-2026.json' with { type: 'json' };
import prior from '../../site/yahoo/nflverse-prior-2025.json' with { type: 'json' };
import { handleComparison } from './_shared/jev-compare-core.mjs';

export default request => handleComparison(request, {
  env: name => Netlify.env.get(name), snapshot, prior,
});

// Netlify enforces this before invoking the paid TypeSafe call.
export const config = { rateLimit: { windowLimit: 3, windowSize: 60, aggregateBy: ['ip', 'domain'] } };
