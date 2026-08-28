import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "site/app/index.html").read_text()
CHECKOUT = (ROOT / "netlify/functions/stripe-checkout.mjs").read_text()
WEBHOOK = (ROOT / "netlify/functions/stripe-webhook.mjs").read_text()
DRAFT_ACCESS = (ROOT / "netlify/functions/draft-access.mjs").read_text()
NETLIFY = (ROOT / "netlify.toml").read_text()


class CommerceContractTests(unittest.TestCase):
    def test_only_single_draft_offer_is_published(self):
        searched = [
            ROOT / "site",
            ROOT / "scripts/generate_hub_pages.py",
            ROOT / "marketing/google-ads/README.md",
        ]
        files = []
        for item in searched:
            files.extend(item.rglob("*.html") if item.is_dir() else [item])
        published = "\n".join(path.read_text(errors="ignore") for path in files)
        self.assertNotIn("$24.99", published)
        self.assertIn("One complete draft", APP)

    def test_checkout_authenticates_user_and_reports_stripe_price(self):
        self.assertIn("supabase.auth.getUser(accessToken)", CHECKOUT)
        self.assertNotIn("user_id, email", CHECKOUT)
        self.assertIn("stripe.prices.retrieve", CHECKOUT)
        self.assertIn("value: price.unit_amount / 100", CHECKOUT)
        self.assertNotIn("24.99", CHECKOUT)

    def test_paid_access_is_not_trusted_from_local_storage(self):
        hydrate = APP[APP.index("function hydrateCachedAuth"):APP.index("async function resumePaidDraft")]
        self.assertNotIn("lsGetAuth('plan'", hydrate)
        self.assertIn("serverEntitlementVerified = false", hydrate)
        self.assertIn("userPlan==='paid'&&serverEntitlementVerified", APP)

    def test_single_draft_reset_consumes_server_entitlement(self):
        self.assertIn("action:owner?'reset':'complete'", APP)
        self.assertIn("paid_access_consumed:paid", APP)
        self.assertIn('["resume", "save", "reset", "complete"]', DRAFT_ACCESS)
        self.assertIn('update({ plan: "free"', DRAFT_ACCESS)

    def test_owner_access_is_server_configured_and_never_consumed(self):
        self.assertIn('Netlify.env.get("OVERADP_OWNER_EMAILS")', DRAFT_ACCESS)
        self.assertIn('app_metadata?.overadp_role === "owner"', DRAFT_ACCESS)
        self.assertNotIn("ryan.a.stover", DRAFT_ACCESS)
        self.assertIn('role: owner ? "owner" : "customer"', DRAFT_ACCESS)
        self.assertIn("action:owner?'reset':'complete'", APP)
        self.assertIn("paid_access_consumed:paid&&!owner", APP)
        self.assertIn("statusEl.textContent = isOwner() ? '✓ OWNER' : '✓ PRO'", APP)

    def test_every_authenticated_account_checks_server_entitlement(self):
        self.assertGreaterEqual(APP.count("await resumePaidDraft(token);"), 2)

    def test_webhook_requires_paid_status(self):
        self.assertIn('session.payment_status !== "paid"', WEBHOOK)
        self.assertIn('plan_type: "draft"', WEBHOOK)

    def test_policies_and_security_headers_are_published(self):
        for page in ("privacy", "terms", "refunds"):
            self.assertTrue((ROOT / f"site/{page}/index.html").exists())
        self.assertIn('X-Content-Type-Options = "nosniff"', NETLIFY)
        self.assertIn('Referrer-Policy = "strict-origin-when-cross-origin"', NETLIFY)
        self.assertNotIn('Access-Control-Allow-Origin = "*"', NETLIFY)

    def test_stale_help_numbers_and_export_label_are_gone(self):
        self.assertNotIn("Kittle, 136 pts", APP)
        self.assertNotIn("Lamar, 245 pts", APP)
        self.assertIn("Model Uncertainty Tier", APP)


if __name__ == "__main__":
    unittest.main()
