const { createClient } = require('@supabase/supabase-js');

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  try {
    const { refresh_token } = JSON.parse(event.body);

    if (!refresh_token) {
      return { statusCode: 400, body: JSON.stringify({ error: 'No refresh token provided' }) };
    }

    const supabase = createClient(
      process.env.SUPABASE_URL,
      process.env.SUPABASE_SERVICE_KEY
    );

    // Use refresh token to get new session
    const { data, error } = await supabase.auth.refreshSession({
      refresh_token
    });

    if (error || !data.session) {
      return { statusCode: 401, body: JSON.stringify({ error: 'Refresh token expired' }) };
    }

    return {
      statusCode: 200,
      body: JSON.stringify({
        session: {
          access_token: data.session.access_token,
          refresh_token: data.session.refresh_token,
        },
        user: data.session.user,
      }),
    };
  } catch (err) {
    console.error('Refresh error:', err);
    return { statusCode: 500, body: JSON.stringify({ error: 'Internal server error' }) };
  }
};
