# OverADP Google Search launch

This is a controlled product-message test, not a scale campaign. The $6.99 entry product cannot support an expensive acquisition cost, so the first $100 is a learning budget with hard stop conditions.

## Campaign settings

- Campaign: `GOOG_Search_NonBrand_DraftAssistant_202608`
- Goal: website sales
- Type: Search only
- Networks: Google Search only; disable Search Partners and Display
- Location: United States, presence only
- Language: English
- Budget: $10/day for 10 days; $100 maximum without a review
- Bidding: Manual CPC while purchase volume is below 30/month
- Starting max CPC: $1.25; raise by no more than 20% every 48 hours if qualified terms receive no impressions
- Absolute max CPC for this test: $2.00
- Ad schedule: all day initially; segment results by hour before restricting
- Final URL: `https://overadp.com/draft-assistant/`
- Auto-tagging: enabled
- Campaign URL suffix: `utm_source=google&utm_medium=cpc&utm_campaign=2026_draft_assistant&utm_term={keyword}&utm_content={creative}`

Do not launch Performance Max, Display, broad match, competitor terms, or Search Partners during this test. They add too much ambiguity for a $100 learning budget.

## Conversion configuration

The site sends these GA4 events:

1. `purchase` — primary conversion; value is $6.99 or $24.99.
2. `proof_demo_completed` — secondary conversion; diagnostic only.
3. `draft_pick_recorded` — diagnostic activation event; keep it secondary.
4. `sign_up` — secondary conversion; account creation.

Before launch:

1. Link Google Ads and GA4 property `G-8GM0JH1DM4`.
2. Enable Google Ads auto-tagging.
3. Trigger each event once in a test session so it appears in GA4.
4. Mark `purchase` as the primary Google Ads conversion. Keep
   `proof_demo_completed`, `draft_pick_recorded`, and `sign_up` secondary so
   they are available for funnel diagnosis without teaching bidding to optimize
   for free activity.
5. Import them into Google Ads.
6. Set only `purchase` as Primary. Keep the other three Secondary so bidding does not optimize for free activity.
7. Verify the purchase event includes `currency`, `value`, and `transaction_id`.

The app also sends GA4's recommended `begin_checkout` event and the internal
`checkout_started` event only after Stripe successfully creates a Checkout
Session. A failed request is recorded as `checkout_error`, not as a checkout.

## Attribution hygiene

The Stripe success return sets GA4's `ignore_referrer` option so
`checkout.stripe.com` does not replace the source that acquired the customer.
Also add `checkout.stripe.com` under GA4 **Admin > Data streams > Web > Configure
tag settings > List unwanted referrals**. The code protects payment returns;
the stream setting protects any other Stripe referrals.

Use `verification_method: stripe` on the diagnostic `purchase_complete` event.
Do not use an event parameter named `source` for verification metadata because
traffic-source reporting can interpret it as acquisition data.

## Import order

1. Create the campaign with the settings above in Google Ads or Google Ads Editor.
2. Import `keywords.csv`.
3. Import `responsive-search-ads.csv`; map headline and description columns during the import review.
4. Add every term in `negative-keywords.csv` as a campaign-level phrase or exact negative.
5. Add callouts: `5 Picks Free`, `No Recurring Subscription`, `Roster-Aware Picks`, `Public Methodology`.
6. Add a structured snippet with header `Types`: `Target Intel`, `VBD`, `ADP Signals`, `Risk Ranges`.
7. Confirm every ad resolves to the dedicated landing page and retains the `gclid`.

## Stop and continue rules

Review daily, but do not make bid changes more than once every 48 hours.

- Pause a search term immediately if it is clearly about the NFL Draft, DFS, betting, dynasty, auction drafts, another sport, support, or employment.
- Pause a keyword after 20 clicks with zero `draft_pick_recorded` events.
- If landing-page-to-War-Room clickthrough is below 20% after 100 visits, fix the landing page before buying more traffic.
- If fewer than 10% of War Room visitors reach three picks after 50 visitors, fix activation before buying more traffic.
- If no purchases occur after 100 qualified clicks, stop the campaign and review recordings/feedback; do not increase budget.
- Continue beyond $100 only if at least one purchase and five preview completions can be attributed to qualified search terms.

## Weekly search-term review

Promote converting search terms from phrase to exact. Add irrelevant terms as negatives. Compare purchases, not just clicks or preview completions. The economic target is ultimately blended CAC below the blended revenue per buyer; this first test is too small to claim profitability.

## Paid-search funnel report

Run the repeatable GA4 paid-search funnel from the repository root:

```bash
npm run ga4:funnel
```

The report queries GA4 property `533452511` from August 21, 2026 through today,
filters sessions to `google / cpc`, and measures this closed funnel:

1. `recommendation_viewed`
2. `draft_pick_recorded`
3. `proof_demo_completed`
4. `offer_shown`
5. `checkout_intent_preauth`
6. `checkout_started`
7. `purchase`

Useful options:

```bash
# Change the date range
npm run ga4:funnel -- --start-date 2026-08-15 --end-date today

# Compare paid search with all traffic
npm run ga4:funnel -- --all-traffic

# Inspect the raw GA4 response
npm run ga4:funnel -- --json
```

Authentication uses `GOOGLE_ANALYTICS_ACCESS_TOKEN` if supplied. Otherwise the
script uses the active `gcloud` user to impersonate the existing keyless reader
`ga4-reader@ggc-ads-api.iam.gserviceaccount.com`. That reader receives only a
short-lived `analytics.readonly` token; no private key is stored in the repo or
on disk.

The defaults can be changed without editing the script:

```bash
GA4_SERVICE_ACCOUNT=reader@example.iam.gserviceaccount.com \
GA4_QUOTA_PROJECT=example-project npm run ga4:funnel
```

The reader service account must have the GA4 property's **Viewer** role. Do not
grant Editor or Administrator; the report only reads aggregated event data.

Do not add campaign UTMs to internal links from the landing page to `/app/`.
Incoming UTMs and `gclid` are carried forward, but internal UTMs would reset the
session campaign and hide paid activation under a source such as
`campaign_landing / website`.

The Data API can run and return the funnel but cannot save a Funnel Exploration
inside the GA4 user interface. The script is the repeatable source of truth.
