import { createClient } from "@supabase/supabase-js";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function requiredEnvironment() {
  const values = {
    url: Netlify.env.get("SUPABASE_URL"),
    anonKey: Netlify.env.get("SUPABASE_ANON_KEY"),
    serviceKey: Netlify.env.get("SUPABASE_SERVICE_KEY"),
  };
  return Object.values(values).every(Boolean) ? values : null;
}

function supabaseClient(url, key) {
  return createClient(url, key, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}

function publicRegistrationError(error) {
  const message = String(error?.message || "").toLowerCase();
  if (message.includes("already") || message.includes("registered") || message.includes("exists")) {
    return {
      status: 409,
      body: {
        error: "An account already exists for this email. Choose Log in below.",
        code: "account_exists",
      },
    };
  }
  if (message.includes("password")) {
    return {
      status: 400,
      body: { error: "Choose a stronger password with at least 6 characters." },
    };
  }
  return {
    status: 400,
    body: { error: "Account creation failed. Please try again." },
  };
}

export default async function authRegister(request) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  const environment = requiredEnvironment();
  if (!environment) {
    console.error("Auth registration configuration is incomplete");
    return jsonResponse({
      error: "Authentication is temporarily unavailable. Please try again shortly.",
      retryable: true,
    }, 503);
  }

  let credentials;
  try {
    credentials = await request.json();
  } catch {
    return jsonResponse({ error: "A valid email and password are required" }, 400);
  }

  const email = String(credentials?.email || "").trim().toLowerCase();
  const password = String(credentials?.password || "");
  if (!email || !password) {
    return jsonResponse({ error: "Email and password required" }, 400);
  }
  if (password.length < 6) {
    return jsonResponse({ error: "Password must be at least 6 characters" }, 400);
  }

  const supabaseAdmin = supabaseClient(environment.url, environment.serviceKey);
  const supabaseAnon = supabaseClient(environment.url, environment.anonKey);

  try {
    // Create an already-confirmed password account server-side. The old public
    // signUp() path sent an email that was immediately made redundant by an
    // admin confirmation and could exhaust Supabase's email quota at checkout.
    const { data: created, error: createError } = await supabaseAdmin.auth.admin.createUser({
      email,
      password,
      email_confirm: true,
    });

    if (createError || !created?.user) {
      const response = publicRegistrationError(createError);
      return jsonResponse(response.body, response.status);
    }

    const userId = created.user.id;
    const { error: profileError } = await supabaseAdmin
      .from("profiles")
      .upsert({
        id: userId,
        email,
        plan: "free",
        plan_type: "season",
        created_at: new Date().toISOString(),
      }, { onConflict: "id" });

    if (profileError) {
      console.error("Auth registration profile creation failed", {
        code: profileError.code,
        message: profileError.message,
      });
      await supabaseAdmin.auth.admin.deleteUser(userId).catch(() => {});
      return jsonResponse({
        error: "Your account could not be prepared. Please try again.",
        retryable: true,
      }, 503);
    }

    const { data: loginData, error: loginError } = await supabaseAnon.auth.signInWithPassword({
      email,
      password,
    });

    if (loginError || !loginData?.user || !loginData?.session) {
      console.error("Auth registration sign-in failed", {
        message: loginError?.message,
        userId,
      });
      return jsonResponse({
        error: "Your account was created. Choose Log in below to continue.",
        code: "account_created",
      }, 409);
    }

    // Marketing capture is deliberately non-blocking; account and checkout
    // should never fail because the optional email-list write did.
    await supabaseAdmin
      .from("email_list")
      .insert({ email, source: "register", created_at: new Date().toISOString() })
      .then(() => {})
      .catch(() => {});

    return jsonResponse({
      user: loginData.user,
      session: loginData.session,
      profile: { plan: "free", plan_type: "season" },
    });
  } catch (error) {
    console.error("Auth registration upstream request failed", {
      name: error?.name,
      message: error?.message,
    });
    return jsonResponse({
      error: "Authentication is temporarily unavailable. Please try again shortly.",
      retryable: true,
    }, 503);
  }
}
