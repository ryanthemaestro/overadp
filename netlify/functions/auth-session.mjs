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

export default async function authSession(request) {
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  try {
    const { access_token: accessToken } = await request.json();
    if (!accessToken) return json({ error: "No token provided" }, 401);

    const url = Netlify.env.get("SUPABASE_URL");
    const serviceKey = Netlify.env.get("SUPABASE_SERVICE_KEY");
    if (!url || !serviceKey) return json({ error: "Authentication unavailable" }, 503);

    const supabase = createClient(url, serviceKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data: { user }, error } = await supabase.auth.getUser(accessToken);
    if (error || !user) return json({ error: "Invalid token" }, 401);

    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .select("*")
      .eq("id", user.id)
      .maybeSingle();
    if (profileError) return json({ error: "Profile unavailable" }, 503);

    return json({
      user,
      profile: profile || { plan: "free", plan_type: "draft" },
    });
  } catch (error) {
    console.error("Session error", error);
    return json({ error: "Internal server error" }, 500);
  }
}
