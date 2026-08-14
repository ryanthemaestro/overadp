const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

// Price IDs for each plan type
const PRICES = {
  season: process.env.STRIPE_PRICE_ID_SEASON || process.env.STRIPE_PRICE_ID,
  draft: process.env.STRIPE_PRICE_ID_DRAFT || process.env.STRIPE_PRICE_ID,
};

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  try {
    const { user_id, email, plan_type, attribution = {} } = JSON.parse(event.body);

    if (!user_id || !email) {
      return { statusCode: 400, body: JSON.stringify({ error: 'User ID and email required' }) };
    }

    const priceId = PRICES[plan_type] || PRICES.season;

    const safePlanType = plan_type === 'draft' ? 'draft' : 'season';
    const metadata = {
      user_id,
      plan_type: safePlanType,
      season: '2026',
    };
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid'].forEach((key) => {
      if (attribution[key]) metadata[key] = String(attribution[key]).slice(0, 120);
    });

    const session = await stripe.checkout.sessions.create({
      payment_method_types: ['card'],
      mode: 'payment',
      customer_email: email,
      client_reference_id: user_id,
      line_items: [
        {
          price: priceId,
          quantity: 1,
        },
      ],
      metadata,
      success_url: `${process.env.SITE_URL}/app/?payment=success&plan=${safePlanType}&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${process.env.SITE_URL}/app/?payment=cancel`,
    });

    return {
      statusCode: 200,
      body: JSON.stringify({ url: session.url }),
    };
  } catch (err) {
    console.error('Checkout error:', err);
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};
