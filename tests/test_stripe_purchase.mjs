import test from "node:test";
import assert from "node:assert/strict";

import {
  PurchaseVerificationError,
  verifyPaidCheckoutSession,
} from "../netlify/functions/_shared/stripe-purchase.mjs";

function paidSession(overrides = {}) {
  return {
    id: "cs_test_verified",
    mode: "payment",
    status: "complete",
    payment_status: "paid",
    client_reference_id: "user-123",
    amount_total: 699,
    currency: "usd",
    metadata: { user_id: "user-123", plan_type: "draft", season: "2026" },
    ...overrides,
  };
}

test("returns analytics values only for a paid session owned by the user", () => {
  assert.deepEqual(verifyPaidCheckoutSession(paidSession(), "user-123"), {
    verified: true,
    session_id: "cs_test_verified",
    plan_type: "draft",
    value: 6.99,
    currency: "USD",
    season: "2026",
  });
});

for (const [name, session, userId, expectedCode] of [
  ["rejects unpaid sessions", paidSession({ payment_status: "unpaid" }), "user-123", "not_paid"],
  ["rejects another user's session", paidSession(), "user-999", "wrong_user"],
  ["rejects an unknown plan", paidSession({ metadata: { user_id: "user-123", plan_type: "trial" } }), "user-123", "invalid_plan"],
  ["rejects a missing amount", paidSession({ amount_total: null }), "user-123", "invalid_amount"],
]) {
  test(name, () => {
    assert.throws(
      () => verifyPaidCheckoutSession(session, userId),
      (error) => error instanceof PurchaseVerificationError && error.code === expectedCode,
    );
  });
}
