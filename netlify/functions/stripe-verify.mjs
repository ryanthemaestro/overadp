import Stripe from "stripe";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export default async (req) => {
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  try {
    const { session_id: sessionId, user_id: userId } = await req.json();

    if (!sessionId || !userId) {
      return json({ error: "Session ID and user ID required" }, 400);
    }

    const stripeSecretKey = Netlify.env.get("STRIPE_SECRET_KEY");
    if (!stripeSecretKey) {
      console.error("Stripe verification error: STRIPE_SECRET_KEY is missing");
      return json({ error: "Payment verification unavailable" }, 500);
    }

    const stripe = new Stripe(stripeSecretKey);
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    const sessionUserId = session.metadata?.user_id || session.client_reference_id;

    if (!sessionUserId || sessionUserId !== userId) {
      return json({ error: "Checkout session does not belong to this user" }, 403);
    }

    if (session.status !== "complete" || session.payment_status !== "paid") {
      return json({ error: "Payment is not complete", verified: false }, 409);
    }

    const planType = session.metadata?.plan_type === "draft" ? "draft" : "season";

    return json({
      verified: true,
      transaction_id: session.id,
      plan_type: planType,
      value: Number(session.amount_total || 0) / 100,
      currency: String(session.currency || "usd").toUpperCase(),
    });
  } catch (error) {
    console.error("Stripe verification error:", error);
    return json({ error: "Unable to verify payment" }, 500);
  }
};
