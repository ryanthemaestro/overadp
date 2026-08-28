import { createClient } from "@supabase/supabase-js";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function cleanIds(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map((id) => String(id).slice(0, 80)).filter(Boolean))].slice(0, 300);
}

function cleanSettings(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const serialized = JSON.stringify(value);
  return serialized.length <= 5000 ? JSON.parse(serialized) : null;
}

export default async function draftAccess(request) {
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  try {
    const input = await request.json();
    const accessToken = input?.access_token;
    const action = input?.action;
    if (!accessToken || !["resume", "save", "complete"].includes(action)) {
      return json({ error: "Valid access token and action required" }, 400);
    }

    const url = Netlify.env.get("SUPABASE_URL");
    const serviceKey = Netlify.env.get("SUPABASE_SERVICE_KEY");
    if (!url || !serviceKey) return json({ error: "Draft access unavailable" }, 503);
    const supabase = createClient(url, serviceKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });

    const { data: { user }, error: userError } = await supabase.auth.getUser(accessToken);
    if (userError || !user) return json({ error: "Session expired" }, 401);
    const { data: authoritativeUserData } = await supabase.auth.admin.getUserById(user.id);
    const authoritativeUser = authoritativeUserData?.user || user;

    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .select("plan,plan_type,season_paid,paid_at")
      .eq("id", user.id)
      .maybeSingle();
    if (profileError) return json({ error: "Draft access unavailable" }, 503);
    if (profile?.plan !== "paid" || profile?.plan_type !== "draft") {
      return json({ authorized: false, plan: "free" });
    }

    let entitlementId = String(profile.season_paid || "");
    if (!entitlementId.startsWith("draft:")) {
      entitlementId = `draft:legacy:${user.id}:${profile.paid_at || "unknown"}`;
      const { error: normalizeError } = await supabase
        .from("profiles")
        .update({ season_paid: entitlementId, plan_type: "draft" })
        .eq("id", user.id);
      if (normalizeError) return json({ error: "Draft access unavailable" }, 503);
    }

    const current = authoritativeUser.app_metadata?.overadp_draft;
    let state = current?.entitlement_id === entitlementId && current?.status === "active"
      ? current
      : {
          entitlement_id: entitlementId,
          status: "active",
          my_team_ids: [],
          opponent_ids: [],
          settings: null,
          updated_at: new Date().toISOString(),
        };

    if (action === "save") {
      if (input.entitlement_id !== entitlementId) return json({ error: "Draft entitlement changed" }, 409);
      state = {
        ...state,
        my_team_ids: cleanIds(input.state?.my_team_ids),
        opponent_ids: cleanIds(input.state?.opponent_ids),
        settings: cleanSettings(input.state?.settings),
        updated_at: new Date().toISOString(),
      };
    }

    if (action === "complete") {
      if (input.entitlement_id !== entitlementId) return json({ error: "Draft entitlement changed" }, 409);
      const completed = { ...state, status: "completed", completed_at: new Date().toISOString() };
      const { error: metadataError } = await supabase.auth.admin.updateUserById(user.id, {
        app_metadata: { ...authoritativeUser.app_metadata, overadp_draft: completed },
      });
      if (metadataError) return json({ error: "Could not complete draft" }, 503);
      const { error: completionError } = await supabase
        .from("profiles")
        .update({ plan: "free", season_paid: `completed:${entitlementId}` })
        .eq("id", user.id)
        .eq("season_paid", entitlementId);
      if (completionError) return json({ error: "Could not complete draft" }, 503);
      return json({ authorized: false, plan: "free", completed: true });
    }

    const { error: metadataError } = await supabase.auth.admin.updateUserById(user.id, {
      app_metadata: { ...authoritativeUser.app_metadata, overadp_draft: state },
    });
    if (metadataError) return json({ error: "Could not save draft" }, 503);

    return json({ authorized: true, plan: "paid", plan_type: "draft", entitlement_id: entitlementId, state });
  } catch (error) {
    console.error("Draft access error", error);
    return json({ error: "Draft access unavailable" }, 500);
  }
}
