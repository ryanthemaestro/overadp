const { createClient } = require('@supabase/supabase-js');

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  try {
    const { access_token } = JSON.parse(event.body);

    if (!access_token) {
      return { statusCode: 401, body: JSON.stringify({ error: 'No token provided' }) };
    }

    const supabase = createClient(
      process.env.SUPABASE_URL,
      process.env.SUPABASE_SERVICE_KEY
    );

    // Verify token and get user
    const { data: { user }, error } = await supabase.auth.getUser(access_token);

    if (error || !user) {
      return { statusCode: 401, body: JSON.stringify({ error: 'Invalid token' }) };
    }

    // Get profile
    const { data: profile } = await supabase
      .from('profiles')
      .select('*')
      .eq('id', user.id)
      .single();

    return {
      statusCode: 200,
      body: JSON.stringify({
        user,
        profile: profile || { plan: 'free', plan_type: 'season' },
      }),
    };
  } catch (err) {
    console.error('Session error:', err);
    return { statusCode: 500, body: JSON.stringify({ error: 'Internal server error' }) };
  }
};
