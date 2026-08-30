export async function activatePaidDraft({ supabase, userId, sessionId, fallbackEmail = "" }) {
  const entitlementId = `draft:${sessionId}`;
  const { data: profile, error: profileReadError } = await supabase
    .from("profiles")
    .select("season_paid")
    .eq("id", userId)
    .maybeSingle();
  if (profileReadError) throw profileReadError;

  const { data: userData, error: getUserError } = await supabase.auth.admin.getUserById(userId);
  if (getUserError || !userData?.user) throw getUserError || new Error("Paid user was not found");

  const user = userData.user;
  const existingMetadata = user.app_metadata || {};
  const existingDraft = existingMetadata.overadp_draft;
  const alreadyCompleted = profile?.season_paid === `completed:${entitlementId}`
    || (existingDraft?.entitlement_id === entitlementId && existingDraft?.status === "completed");
  if (alreadyCompleted) return { entitlementId, status: "completed" };

  const email = String(user.email || fallbackEmail || "").trim();
  if (!email) throw new Error("Paid user email is missing");
  const { error: profileError } = await supabase
    .from("profiles")
    .upsert({
      id: userId,
      email,
      plan: "paid",
      plan_type: "draft",
      season_paid: entitlementId,
      paid_at: new Date().toISOString(),
    }, { onConflict: "id" });
  if (profileError) throw profileError;

  const draftState = existingDraft?.entitlement_id === entitlementId && existingDraft?.status === "active"
    ? existingDraft
    : {
        entitlement_id: entitlementId,
        status: "active",
        my_team_ids: [],
        opponent_ids: [],
        settings: null,
        updated_at: new Date().toISOString(),
      };
  const { error: metadataError } = await supabase.auth.admin.updateUserById(userId, {
    app_metadata: { ...existingMetadata, overadp_draft: draftState },
  });
  if (metadataError) throw metadataError;

  return { entitlementId, status: "active" };
}
