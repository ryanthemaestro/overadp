const { createClient } = require('@supabase/supabase-js');

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  try {
    const { email, password } = JSON.parse(event.body);

    if (!email || !password) {
      return { statusCode: 400, body: JSON.stringify({ error: 'Email and password required' }) };
    }

    // Use anon key for signup — it returns a session; service key does not
    const supabaseAnon = createClient(
      process.env.SUPABASE_URL,
      process.env.SUPABASE_ANON_KEY
    );

    // Sign up the user
    const { data: authData, error: authError } = await supabaseAnon.auth.signUp({
      email,
      password,
    });

    if (authError) {
      return { statusCode: 400, body: JSON.stringify({ error: authError.message }) };
    }

    const userId = authData.user.id;

    // Use service key for admin operations (profiles, email_list, auto-confirm)
    const supabaseAdmin = createClient(
      process.env.SUPABASE_URL,
      process.env.SUPABASE_SERVICE_KEY
    );

    // Auto-confirm email so user gets a session immediately
    try {
      await supabaseAdmin.auth.admin.updateUserById(userId, { email_confirm: true });
    } catch (confirmErr) {
      console.error('Auto-confirm error:', confirmErr);
    }

    // If no session was returned, sign in to get one
    let session = authData.session;
    if (!session) {
      const { data: loginData } = await supabaseAnon.auth.signInWithPassword({ email, password });
      session = loginData?.session || null;
    }

    // Create profile
    const { error: profileError } = await supabaseAdmin
      .from('profiles')
      .insert({ id: userId, email, plan: 'free', created_at: new Date().toISOString() });

    if (profileError) {
      console.error('Profile creation error:', profileError);
    }

    // Add to email list
    await supabaseAdmin
      .from('email_list')
      .insert({ email, source: 'register', created_at: new Date().toISOString() })
      .then(() => {})
      .catch(() => {});

    return {
      statusCode: 200,
      body: JSON.stringify({
        user: authData.user,
        session: session,
      }),
    };
  } catch (err) {
    console.error('Register error:', err);
    return { statusCode: 500, body: JSON.stringify({ error: 'Internal server error' }) };
  }
};
