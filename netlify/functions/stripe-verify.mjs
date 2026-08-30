import Stripe from "stripe";
import { createClient } from "@supabase/supabase-js";
import { activatePaidDraft } from "./_shared/activate-paid-draft.mjs";

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
    const { session_id: sessionId, access_token: accessToken } = await req.json();

    if (!sessionId || !accessToken) {
      return json({ error: "Session ID and login required" }, 400);
    }

    const stripeSecretKey = Netlify.env.get("STRIPE_SECRET_KEY");
    if (!stripeSecretKey) {
      console.error("Stripe verification error: STRIPE_SECRET_KEY is missing");
      return json({ error: "Payment verification unavailable" }, 500);
    }

    const supabaseUrl = Netlify.env.get("SUPABASE_URL");
    const serviceKey = Netlify.env.get("SUPABASE_SERVICE_KEY");
    if (!supabaseUrl || !serviceKey) return json({ error: "Payment verification unavailable" }, 503);
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data: { user }, error: userError } = await supabase.auth.getUser(accessToken);
    if (userError || !user) return json({ error: "Log in again to verify payment" }, 401);

    const stripe = new Stripe(stripeSecretKey);
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    const sessionUserId = session.metadata?.user_id || session.client_reference_id;

    if (!sessionUserId || sessionUserId !== user.id) {
      return json({ error: "Checkout session does not belong to this user" }, 403);
    }

    if (session.status !== "complete" || session.payment_status !== "paid") {
      return json({ error: "Payment is not complete", verified: false }, 409);
    }
    if (session.metadata?.plan_type !== "draft") {
      return json({ error: "Checkout is not a draft purchase", verified: false }, 409);
    }

    const activation = await activatePaidDraft({
      supabase,
      userId: user.id,
      sessionId: session.id,
      fallbackEmail: user.email,
    });

    return json({
      verified: true,
      access_granted: activation.status === "active",
      transaction_id: session.id,
      plan_type: "draft",
      value: Number(session.amount_total || 0) / 100,
      currency: String(session.currency || "usd").toUpperCase(),
    });
  } catch (error) {
    console.error("Stripe verification error:", error);
    return json({ error: "Unable to verify payment" }, 500);
  }
};
