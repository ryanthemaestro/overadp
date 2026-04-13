const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const { createClient } = require('@supabase/supabase-js');

exports.handler = async (event) => {
  const sig = event.headers['stripe-signature'];

  let stripeEvent;

  try {
    stripeEvent = stripe.webhooks.constructEvent(
      event.body,
      sig,
      process.env.STRIPE_WEBHOOK_SECRET
    );
  } catch (err) {
    console.error('Webhook signature verification failed:', err.message);
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid signature' }) };
  }

  const supabase = createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_SERVICE_KEY
  );

  try {
    switch (stripeEvent.type) {
      case 'checkout.session.completed': {
        const session = stripeEvent.data.object;
        const userId = session.metadata.user_id;
        const season = session.metadata.season;
        const planType = session.metadata.plan_type || 'season';

        // Update profile to paid with plan_type
        const { error } = await supabase
          .from('profiles')
          .update({
            plan: 'paid',
            plan_type: planType,
            season_paid: season,
            paid_at: new Date().toISOString(),
          })
          .eq('id', userId);

        if (error) {
          console.error('Profile update error:', error);
          return { statusCode: 500, body: JSON.stringify({ error: 'DB update failed' }) };
        }

        console.log(`User ${userId} paid for ${planType} (${season})`);
        break;
      }

      default:
        console.log(`Unhandled event type: ${stripeEvent.type}`);
    }

    return { statusCode: 200, body: JSON.stringify({ received: true }) };
  } catch (err) {
    console.error('Webhook handler error:', err);
    return { statusCode: 500, body: JSON.stringify({ error: 'Handler failed' }) };
  }
};
