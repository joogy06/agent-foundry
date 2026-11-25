# Referrers, channel groups and server logs

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: status_snapshot
    subject: ai-referrer-table
    verified_against: "chatgpt.com UTM verified; other assistant referrers practitioner-tested only"
    verified_on: 2026-09-27
    review_by: 2026-12-26
-->

V = vendor page fetched 2026-09-27; I = inferred or practitioner-tested only.

## Referrer and UTM behaviour

| Assistant | Arrives as | Evidence |
|---|---|---|
| ChatGPT | `utm_source=chatgpt.com` added automatically; referrer `chatgpt.com` | **V** https://help.openai.com/en/articles/12627856-publishers-and-developers-faq |
| Perplexity | referrer `perplexity.ai`, no UTM | I |
| Gemini | referrer `gemini.google.com`, no UTM | I |
| Claude | referrer `claude.ai`, no UTM | I |
| Copilot | referrer `copilot.microsoft.com` or `copilot.com` | I |
| DeepSeek | named by GA4 as an AI Assistant source; domain unverified | V (named) / I (domain) |
| Meta AI, Grok, Duck.ai | `meta.ai`, `grok.com`, `duck.ai` | I, unverified |
| Siri AI, in-app browsers | often no referrer: Direct | I |
| AI Overviews / AI Mode | `google.com`, counted as Organic | V https://support.google.com/analytics/answer/9164320 |

A `chat.openai.com` filter is dead: that domain was retired in 2024.

## GA4

1. **Use the built-in AI Assistant channel first** (default channel group, from 2026-05-13) [V
   https://support.google.com/analytics/answer/9756891]. Its referrer list is not published, so do not
   assume it covers every row above.
2. **Custom channel group, only to extend it.** Copy the default group, add a channel above
   Referral, Organic Search and Direct with *source matches regex*:

   ```
   (^|\.)(chatgpt\.com|perplexity\.ai|gemini\.google\.com|claude\.ai|copilot\.microsoft\.com|copilot\.com|meta\.ai|grok\.com|duck\.ai)$
   ```

   **[I] Re-verify each domain against your own referral report before relying on it**, and never
   match `google.com` here: that would move all organic search into the AI channel.
3. Custom channel groups apply to data from their creation onward in some reports; compare periods
   only within one definition.

## Cloudflare (only if the site is on it)

AI Crawl Control shows per-crawler analytics on all plans and "Referrals from AI platforms" on paid
plans [V https://developers.cloudflare.com/ai-crawl-control/].

## Server logs: user-triggered agents

The class of each UA, and its IP-list URL, lives in
`ai-search-optimizer/references/crawlers.md`. For measurement, only the **user-triggered** class
means a person asked about you right now: ChatGPT-User, Perplexity-User, Claude-User, Google-Agent,
meta-externalfetcher, Amzn-User, DuckAssistBot.

```bash
# 1) Count hits per user-triggered agent and path (combined log format)
grep -E 'ChatGPT-User|Perplexity-User|Claude-User|Google-Agent|meta-externalfetcher|Amzn-User|DuckAssistBot' access.log \
  | awk -F'"' '{split($2,r," "); print $6 "\t" r[2]}' | sort | uniq -c | sort -rn | head -50
```

```python
# 2) Keep only hits whose IP is in the vendor's published list (never trust the UA alone)
import ipaddress, json, urllib.request
def ranges(url):
    doc = json.load(urllib.request.urlopen(url, timeout=20))
    return [ipaddress.ip_network(p.get("ipv4Prefix") or p.get("ipv6Prefix"))
            for p in doc.get("prefixes", [])]
def verified(ip, nets):
    addr = ipaddress.ip_address(ip)
    return any(addr in n for n in nets)
```

The prefix-list shape above is Google's and OpenAI's style [I]; check each vendor's JSON before use.
Web Bot Auth signatures, where sent, verify identity without IP lists (see the crawler table).

Read the result as **demand signal per page**, not as visits: a ChatGPT-User fetch of a product URL
means someone asked ChatGPT about it. Pair it with the session and order levels for the same pages.
