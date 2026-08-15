export class PurchaseVerificationError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "PurchaseVerificationError";
    this.code = code;
  }
}

export function normalizePlanType(value) {
  if (value === "draft" || value === "season") return value;
  throw new PurchaseVerificationError("invalid_plan", "Checkout session has an invalid plan");
}

export function verifyPaidCheckoutSession(session, userId) {
  if (!session || typeof session !== "object") {
    throw new PurchaseVerificationError("missing_session", "Checkout session was not found");
  }
  if (!userId) {
    throw new PurchaseVerificationError("missing_user", "An authenticated user is required");
  }
  if (session.mode !== "payment" || session.status !== "complete" || session.payment_status !== "paid") {
    throw new PurchaseVerificationError("not_paid", "Checkout session is not paid and complete");
  }

  const metadataUserId = session.metadata?.user_id;
  if (session.client_reference_id !== userId || metadataUserId !== userId) {
    throw new PurchaseVerificationError("wrong_user", "Checkout session does not belong to this user");
  }

  const amountTotal = Number(session.amount_total);
  if (!Number.isInteger(amountTotal) || amountTotal <= 0 || !session.currency) {
    throw new PurchaseVerificationError("invalid_amount", "Checkout session has an invalid amount");
  }

  const planType = normalizePlanType(session.metadata?.plan_type);
  return {
    verified: true,
    session_id: session.id,
    plan_type: planType,
    value: amountTotal / 100,
    currency: String(session.currency).toUpperCase(),
    season: session.metadata?.season || "2026",
  };
}
