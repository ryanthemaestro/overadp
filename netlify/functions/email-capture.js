const { createClient } = require('@supabase/supabase-js');

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  try {
    const { email, source } = JSON.parse(event.body);

    if (!email) {
      return { statusCode: 400, body: JSON.stringify({ error: 'Email required' }) };
    }

    const supabase = createClient(
      process.env.SUPABASE_URL,
      process.env.SUPABASE_SERVICE_KEY
    );

    // Upsert to email list (avoid duplicates)
    const { error } = await supabase
      .from('email_list')
      .upsert(
        { email, source: source || 'landing', created_at: new Date().toISOString() },
        { onConflict: 'email' }
      );

    if (error) {
      console.error('Email capture error:', error);
      return { statusCode: 500, body: JSON.stringify({ error: 'Failed to save email' }) };
    }

    return {
      statusCode: 200,
      body: JSON.stringify({ success: true }),
    };
  } catch (err) {
    console.error('Email capture error:', err);
    return { statusCode: 500, body: JSON.stringify({ error: 'Internal server error' }) };
  }
};
