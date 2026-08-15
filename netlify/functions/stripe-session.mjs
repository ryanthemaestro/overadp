import Stripe from "stripe";
import { createClient } from "@supabase/supabase-js";
import { verifyPaidCheckoutSession, PurchaseVerificationError } from "./_shared/stripe-purchase.mjs";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function environment() {
  const values = {
    stripeSecret: Netlify.env.get("STRIPE_SECRET_KEY"),
    supabaseUrl: Netlify.env.get("SUPABASE_URL"),
    supabaseServiceKey: Netlify.env.get("SUPABASE_SERVICE_KEY"),
  };
  return Object.values(values).every(Boolean) ? values : null;
}

export default async (request) => {
  if (request.method !== "POST") return jsonResponse({ error: "Method not allowed" }, 405);

  const env = environment();
  if (!env) {
    console.error("Stripe verification configuration is incomplete");
    return jsonResponse({ error: "Payment verification is temporarily unavailable" }, 503);
  }

  let input;
  try {
    input = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid request" }, 400);
  }

  const accessToken = String(input?.access_token || "");
  const sessionId = String(input?.session_id || "");
  if (!accessToken || !sessionId.startsWith("cs_")) {
    return jsonResponse({ error: "Authentication and a valid checkout session are required" }, 400);
  }

  try {
    const supabase = createClient(env.supabaseUrl, env.supabaseServiceKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data: { user }, error: authError } = await supabase.auth.getUser(accessToken);
    if (authError || !user?.id) return jsonResponse({ error: "Invalid or expired session" }, 401);

    const stripe = new Stripe(env.stripeSecret);
    const checkoutSession = await stripe.checkout.sessions.retrieve(sessionId);
    const purchase = verifyPaidCheckoutSession(checkoutSession, user.id);

    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .update({
        plan: "paid",
        plan_type: purchase.plan_type,
        season_paid: purchase.season,
        paid_at: new Date().toISOString(),
      })
      .eq("id", user.id)
      .select("plan, plan_type, season_paid")
      .maybeSingle();

    if (profileError || !profile) {
      console.error("Verified purchase profile update failed", {
        code: profileError?.code,
        message: profileError?.message,
      });
      return jsonResponse({ error: "Payment was verified but access could not be updated" }, 503);
    }

    return jsonResponse({ ...purchase, profile });
  } catch (error) {
    if (error instanceof PurchaseVerificationError) {
      return jsonResponse({ error: error.message, code: error.code }, 409);
    }
    console.error("Payment verification failed", { name: error?.name, message: error?.message });
    return jsonResponse({ error: "Payment could not be verified" }, 502);
  }
};
