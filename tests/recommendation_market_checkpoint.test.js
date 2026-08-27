const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const appPath = path.join(__dirname, '..', 'site', 'app', 'index.html');
const source = fs.readFileSync(appPath, 'utf8');
const helperMatch = source.match(
  /function qualifiesForMarketCheckpoint[\s\S]*?(?=\nfunction getRecommendations)/
);

assert.ok(helperMatch, 'market-checkpoint quality helper should exist');

const context = {};
vm.createContext(context);
vm.runInContext(`${helperMatch[0]}; this.qualifiesForMarketCheckpoint = qualifiesForMarketCheckpoint;`, context);

const qualifies = context.qualifiesForMarketCheckpoint;

test('rejects a severe model outlier even when its ADP is overdue', () => {
  assert.equal(qualifies({ model_rank: 359 }, 82), false);
  assert.equal(qualifies({ model_rank: 150 }, 82), false);
});

test('keeps credible market-checkpoint candidates eligible', () => {
  assert.equal(qualifies({ model_rank: 65 }, 82), true);
  assert.equal(qualifies({ model_rank: 40 }, 11), true);
  assert.equal(qualifies({ model_rank: 240 }, 150), true);
});

test('rejects missing and invalid model ranks', () => {
  assert.equal(qualifies({}, 82), false);
  assert.equal(qualifies({ model_rank: 'not-a-rank' }, 82), false);
  assert.equal(qualifies({ model_rank: 0 }, 82), false);
});

test('market-checkpoint injection uses the model-quality guard', () => {
  assert.match(
    source,
    /const marketCheckpoints=draftNowPool[\s\S]*?qualifiesForMarketCheckpoint\(p,pickNum\)/
  );
});
