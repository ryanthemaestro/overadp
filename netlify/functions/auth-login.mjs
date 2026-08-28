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

export default async (request) => {
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  const environment = requiredEnvironment();
  if (!environment) {
    console.error("Auth login configuration is incomplete");
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

  try {
    const supabaseAnon = supabaseClient(environment.url, environment.anonKey);
    const { data, error } = await supabaseAnon.auth.signInWithPassword({ email, password });

    if (error || !data?.user || !data?.session) {
      return jsonResponse({ error: error?.message || "Invalid login credentials" }, 401);
    }

    const supabaseAdmin = supabaseClient(environment.url, environment.serviceKey);
    const { data: profile, error: profileError } = await supabaseAdmin
      .from("profiles")
      .select("*")
      .eq("id", data.user.id)
      .maybeSingle();

    if (profileError) {
      console.error("Auth login profile lookup failed", {
        code: profileError.code,
        message: profileError.message,
      });
      return jsonResponse({
        error: "Your account was verified, but the profile service is unavailable. Please retry.",
        retryable: true,
      }, 503);
    }

    return jsonResponse({
      user: data.user,
      session: data.session,
      profile: profile || { plan: "free", plan_type: "draft" },
    });
  } catch (error) {
    console.error("Auth login upstream request failed", {
      name: error?.name,
      message: error?.message,
    });
    return jsonResponse({
      error: "Authentication is waking up or temporarily unavailable. Please retry in a minute.",
      retryable: true,
    }, 503);
  }
};
