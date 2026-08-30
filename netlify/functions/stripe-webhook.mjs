import Stripe from "stripe";
import { createClient } from "@supabase/supabase-js";
import { activatePaidDraft } from "./_shared/activate-paid-draft.mjs";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export default async function stripeWebhook(request) {
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  const stripeKey = Netlify.env.get("STRIPE_SECRET_KEY");
  const webhookSecret = Netlify.env.get("STRIPE_WEBHOOK_SECRET");
  const signature = request.headers.get("stripe-signature");
  if (!stripeKey || !webhookSecret || !signature) return json({ error: "Webhook unavailable" }, 503);

  let stripeEvent;
  try {
    const stripe = new Stripe(stripeKey);
    stripeEvent = stripe.webhooks.constructEvent(await request.text(), signature, webhookSecret);
  } catch (error) {
    console.error("Webhook signature verification failed", error?.message);
    return json({ error: "Invalid signature" }, 400);
  }

  if (stripeEvent.type !== "checkout.session.completed") return json({ received: true });

  const session = stripeEvent.data.object;
  if (session.payment_status !== "paid") {
    console.warn("Ignoring completed checkout without paid status", session.id, session.payment_status);
    return json({ received: true });
  }

  const userId = session.metadata?.user_id || session.client_reference_id;
  if (!userId || session.metadata?.plan_type !== "draft") {
    console.error("Paid checkout is missing valid draft metadata", session.id);
    return json({ error: "Invalid checkout metadata" }, 400);
  }

  const supabaseUrl = Netlify.env.get("SUPABASE_URL");
  const serviceKey = Netlify.env.get("SUPABASE_SERVICE_KEY");
  if (!supabaseUrl || !serviceKey) return json({ error: "Database unavailable" }, 503);
  const supabase = createClient(supabaseUrl, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  try {
    const activation = await activatePaidDraft({
      supabase,
      userId,
      sessionId: session.id,
      fallbackEmail: session.customer_details?.email || session.customer_email,
    });
    if (activation.status === "completed") {
      console.log(`Ignored completed draft entitlement replay (${session.id})`);
      return json({ received: true });
    }
  } catch (error) {
    console.error("Paid draft activation failed", error);
    return json({ error: "Database update failed" }, 500);
  }

  console.log(`User ${userId} paid for one draft (${session.id})`);
  return json({ received: true });
}
