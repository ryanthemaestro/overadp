import Stripe from "stripe";
import { createClient } from "@supabase/supabase-js";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

export default async function stripeCheckout(request) {
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  try {
    const { access_token: accessToken, attribution = {} } = await request.json();
    if (!accessToken) return json({ error: "Log in again before checkout" }, 401);

    const stripeKey = Netlify.env.get("STRIPE_SECRET_KEY");
    const priceId = Netlify.env.get("STRIPE_PRICE_ID_DRAFT") || Netlify.env.get("STRIPE_PRICE_ID");
    const supabaseUrl = Netlify.env.get("SUPABASE_URL");
    const serviceKey = Netlify.env.get("SUPABASE_SERVICE_KEY");
    const siteUrl = Netlify.env.get("SITE_URL") || "https://overadp.com";
    if (!stripeKey || !priceId || !supabaseUrl || !serviceKey) {
      console.error("Checkout configuration is incomplete");
      return json({ error: "Checkout is temporarily unavailable" }, 503);
    }

    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data: { user }, error: userError } = await supabase.auth.getUser(accessToken);
    if (userError || !user?.id || !user.email) return json({ error: "Log in again before checkout" }, 401);

    const { data: profile } = await supabase
      .from("profiles")
      .select("plan,plan_type")
      .eq("id", user.id)
      .maybeSingle();
    if (profile?.plan === "paid") {
      return json({ error: "Your paid draft is already active" }, 409);
    }

    const stripe = new Stripe(stripeKey);
    const price = await stripe.prices.retrieve(priceId, { expand: ["product"] });
    if (!Number.isInteger(price.unit_amount) || price.unit_amount <= 0) {
      throw new Error("Draft price is not a fixed one-time amount");
    }

    const metadata = { user_id: user.id, plan_type: "draft", season: "2026" };
    for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid"]) {
      if (attribution[key]) metadata[key] = String(attribution[key]).slice(0, 120);
    }

    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      mode: "payment",
      customer_email: user.email,
      client_reference_id: user.id,
      line_items: [{ price: priceId, quantity: 1 }],
      metadata,
      success_url: `${siteUrl}/app/?payment=success&plan=draft&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${siteUrl}/app/?payment=cancel`,
    });

    const productName = typeof price.product === "object" && price.product?.name
      ? price.product.name
      : "OverADP Single Draft";
    return json({
      url: session.url,
      value: price.unit_amount / 100,
      currency: String(price.currency || "usd").toUpperCase(),
      item_id: "overadp_draft",
      item_name: productName,
    });
  } catch (error) {
    console.error("Checkout error", error);
    return json({ error: "Checkout could not be created" }, 500);
  }
}
