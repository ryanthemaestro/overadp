import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "site/app/index.html").read_text()
ADS_README = (ROOT / "marketing/google-ads/README.md").read_text()


class TrackingContractTests(unittest.TestCase):
    def test_stripe_return_preserves_acquisition_source(self):
        self.assertIn("ignore_referrer: isVerifiedPaymentReturn", APP_HTML)
        self.assertNotIn("source:'stripe_verified'", APP_HTML)
        self.assertIn("verification_method:'stripe'", APP_HTML)

    def test_checkout_events_follow_successful_session_creation(self):
        response_check = APP_HTML.index("if(!res.ok||!data.url)")
        begin_checkout = APP_HTML.index("gaEvent('begin_checkout'", response_check)
        checkout_started = APP_HTML.index("gaEvent('checkout_started'", response_check)
        redirect = APP_HTML.index("window.location.href=data.url", response_check)
        self.assertLess(response_check, begin_checkout)
        self.assertLess(begin_checkout, checkout_started)
        self.assertLess(checkout_started, redirect)

    def test_reporting_docs_use_live_event_names(self):
        self.assertNotIn("free_preview_completed", ADS_README)
        self.assertIn("`proof_demo_completed`", ADS_README)
        self.assertIn("`offer_shown`", ADS_README)


if __name__ == "__main__":
    unittest.main()
