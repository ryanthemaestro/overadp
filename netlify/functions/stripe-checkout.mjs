import Stripe from "stripe";
import { createClient } from "@supabase/supabase-js";
import { normalizePlanType, PurchaseVerificationError } from "./_shared/stripe-purchase.mjs";

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
    siteUrl: Netlify.env.get("SITE_URL"),
    seasonPrice: Netlify.env.get("STRIPE_PRICE_ID_SEASON") || Netlify.env.get("STRIPE_PRICE_ID"),
    draftPrice: Netlify.env.get("STRIPE_PRICE_ID_DRAFT") || Netlify.env.get("STRIPE_PRICE_ID"),
  };
  return Object.values(values).every(Boolean) ? values : null;
}

export default async (request) => {
  if (request.method !== "POST") return jsonResponse({ error: "Method not allowed" }, 405);

  const env = environment();
  if (!env) {
    console.error("Stripe checkout configuration is incomplete");
    return jsonResponse({ error: "Checkout is temporarily unavailable" }, 503);
  }

  let input;
  try {
    input = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid request" }, 400);
  }

  const accessToken = String(input?.access_token || "");
  if (!accessToken) return jsonResponse({ error: "Authentication required" }, 401);

  let planType;
  try {
    planType = normalizePlanType(input?.plan_type || "season");
  } catch (error) {
    if (error instanceof PurchaseVerificationError) return jsonResponse({ error: error.message }, 400);
    throw error;
  }

  try {
    const supabase = createClient(env.supabaseUrl, env.supabaseServiceKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data: { user }, error: authError } = await supabase.auth.getUser(accessToken);
    if (authError || !user?.id || !user?.email) {
      return jsonResponse({ error: "Invalid or expired session" }, 401);
    }

    const metadata = {
      user_id: user.id,
      plan_type: planType,
      season: "2026",
    };
    for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid"]) {
      if (input?.attribution?.[key]) metadata[key] = String(input.attribution[key]).slice(0, 120);
    }

    const stripe = new Stripe(env.stripeSecret);
    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      mode: "payment",
      customer_email: user.email,
      client_reference_id: user.id,
      line_items: [{ price: planType === "draft" ? env.draftPrice : env.seasonPrice, quantity: 1 }],
      metadata,
      success_url: `${env.siteUrl.replace(/\/$/, "")}/app/?payment=success&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${env.siteUrl.replace(/\/$/, "")}/app/?payment=cancel`,
    });

    return jsonResponse({ url: session.url });
  } catch (error) {
    console.error("Checkout error", { name: error?.name, message: error?.message });
    return jsonResponse({ error: "Checkout is temporarily unavailable" }, 500);
  }
};
