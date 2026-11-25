# BigQuery export and Google Trends

Owned by `seo-data-analyst`; moved out of SKILL.md to keep it short. Costs and tiers were not re-checked on 2026-09-27; confirm on the vendor pricing page before quoting.

## BigQuery (Power Tool)

Both GSC and GA4 can export to BigQuery for unlimited, unsampled data access.

| Feature | GSC Export | GA4 Export |
|---------|-----------|------------|
| Data | Site/URL impression tables | Raw event-level data |
| Granularity | Aggregated (like API) | Every event with all parameters |
| Sampling | None | None |
| Cost (small store) | ~$0/month (free tier) | ~$0-5/month |
| Setup | GSC Settings → Bulk data export | GA4 Admin → BigQuery Links |

**For small e-commerce:** BigQuery free tier (10 GB storage, 1 TB queries/month) is likely sufficient.

## Google Trends (Keyword Research)

No official stable API. Options:
- **pytrends** (Python): Free but unreliable, may break
- **SerpAPI Google Trends**: $75-275/month, reliable
- **Manual**: trends.google.com — compare keywords, identify seasonality, geographic demand

Use Google Trends for: seasonal trend identification, geographic demand analysis, comparing keyword popularity, identifying rising topics for content planning.
