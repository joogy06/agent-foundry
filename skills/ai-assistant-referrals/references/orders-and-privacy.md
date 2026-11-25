# Order-level attribution, surveys and UK privacy

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: woocommerce-order-attribution
    source_url: https://woocommerce.com/document/order-attribution-tracking/
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "Order Attribution precedence, 30-minute session, sbjs_* cookies, WP Consent API."
  - kind: external_fact
    subject: duaa-s112
    source_url: https://www.legislation.gov.uk/ukpga/2025/18/section/112
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "Statistical-purposes exception in force 2026-02-05."
-->

V = page fetched 2026-09-27; I = inferred.

## WooCommerce Order Attribution

Core WooCommerce stores the origin of each order [V https://woocommerce.com/document/order-attribution-tracking/]:

- UTM parameters and referrer, per order, visible on the order screen and filterable in the order list.
- **Precedence:** UTM or organic beats referral, which beats direct.
- A **30-minute session**; six `sbjs_*` cookies; integrates with the **WP Consent API**, so declined
  consent can mean no attribution for that order.

Because ChatGPT adds `utm_source=chatgpt.com` [V], ChatGPT orders are normally attributed as UTM
source `chatgpt.com`; other assistants arrive as referral origins.

**Counting a month (read-only).** The order meta keys are `_wc_order_attribution_source_type`,
`_wc_order_attribution_utm_source`, `_wc_order_attribution_utm_medium` and
`_wc_order_attribution_referrer` [I: confirm all four on one real order before trusting the
query]. With HPOS they live in `wp_wc_orders_meta`, otherwise in `wp_postmeta`.

Paid and organic must stay separate lines. Tag every ChatGPT Ads link
`utm_source=chatgpt.com&utm_medium=paid` (in the ads platform's final-URL suffix) so the split
holds. The query classifies each order's medium into a **channel**:

- **paid**: any medium GA4 treats as paid, `^(.*cp.*|ppc|retargeting|paid.*)$` case-insensitive
  (cpc, cpm, cpv, ppc, paid, paidsearch, paid_social, retargeting) [V
  https://support.google.com/analytics/answer/9756891], plus the display mediums (display,
  banner, interstitial, expandable), which GA4 puts in its paid Display channel.
- **organic**: no medium (ChatGPT itself adds only `utm_source`), `organic` or `referral`.
- **unclassified**: anything else (email, affiliate, a typo). Report it as its own line and list
  its mediums; never fold it into organic.

```sql
-- HPOS; completed and processing orders in the month, by attributed source AND channel [I]
SELECT src.meta_value AS utm_source,
       CASE
         WHEN LOWER(COALESCE(med.meta_value, '')) IN ('', '(none)', 'organic', 'referral') THEN 'organic'
         WHEN LOWER(med.meta_value) LIKE '%cp%' OR LOWER(med.meta_value) LIKE 'paid%'
           OR LOWER(med.meta_value) IN ('ppc', 'retargeting', 'display', 'banner',
                                        'interstitial', 'expandable') THEN 'paid'
         ELSE 'unclassified'
       END AS channel,
       COUNT(*) AS orders, SUM(o.total_amount) AS revenue
FROM wp_wc_orders o
JOIN wp_wc_orders_meta src ON src.order_id = o.id AND src.meta_key = '_wc_order_attribution_utm_source'
LEFT JOIN wp_wc_orders_meta med ON med.order_id = o.id AND med.meta_key = '_wc_order_attribution_utm_medium'
WHERE o.status IN ('wc-completed','wc-processing')
  AND o.date_created_gmt >= '2026-09-01' AND o.date_created_gmt < '2026-10-01'
GROUP BY src.meta_value, channel ORDER BY revenue DESC;
```

Report `chatgpt.com` / `paid` as ChatGPT Ads, `chatgpt.com` / `organic` as organic ChatGPT, and
`chatgpt.com` / `unclassified` as its own line with the mediums named. Repeat with `_wc_order_attribution_referrer LIKE '%perplexity.ai%'` (and the other
referrer domains) for assistants that send no UTM. Exclude refunds and test orders. Use the REST
API or a read replica rather than production SQL where you can.

## Post-purchase survey

One optional question on the thank-you page: *"How did you first hear about us?"* with an
"AI assistant (ChatGPT, Gemini, Copilot...)" option and a free-text field, stored as order meta.
It is the only instrument that sees zero-click influence [I, practice, no vendor source]. Report
the response rate beside the result; a low rate makes it a signal, not a measure.

## UK privacy

| Question | Position | Evidence |
|---|---|---|
| Can basic analytics run without consent? | Possibly, under the **DUAA 2025 s.112** statistical-purposes exception, in force 2026-02-05, **if** users get clear information, a free way to object, and the provider acts only as your processor | V https://www.legislation.gov.uk/ukpga/2025/18/section/112 and the ICO page on the exceptions |
| GA4 with Google Signals or ads linking | Likely still needs consent (Google uses the data for its own purposes) | I |
| Order Attribution cookies | Behave per your consent set-up through the WP Consent API | V (integration) / I (your configuration) |
| Server logs | No storage or access on the device, so outside PECR; still personal data under UK GDPR (IP addresses): state a purpose and a retention period | I |

This is a measurement skill, not legal advice. When a set-up depends on the exception, write down
the three conditions and how each is met, and have that checked.
