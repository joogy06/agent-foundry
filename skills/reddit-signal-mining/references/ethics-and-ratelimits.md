# Ethics, Rate Limits, and Reddit ToS Compliance

This is the load-bearing privacy/ethics reference for `reddit-signal-mining`. HR-11 from the founder
family hard rules (Reddit PII leakage prevention) is enforced here.

## PRAW Setup Walkthrough

### 1. Create a Reddit app

Go to https://www.reddit.com/prefs/apps → "are you a developer? create an app..." → fill:

- Name: `reddit-signal-mining`
- App type: `script` (for personal use) OR `web app` (if deploying multi-user)
- Description: `Research signal mining for founder-ideation skill`
- About URL: leave blank for script apps
- Redirect URI: `http://localhost:8080` (required even for script apps)

Click `create app`. You'll get:
- `client_id` (just below "personal use script")
- `client_secret`

### 2. Store credentials

```bash
mkdir -p ~/.config/reddit-signal-mining
cat > ~/.config/reddit-signal-mining/praw.env <<EOF
REDDIT_CLIENT_ID=<paste here>
REDDIT_CLIENT_SECRET=<paste here>
REDDIT_USER_AGENT=reddit-signal-mining/1.0 by u/<your reddit username>
# Only for script-type apps:
REDDIT_USERNAME=<your reddit username>
REDDIT_PASSWORD=<your reddit password>
EOF
chmod 0600 ~/.config/reddit-signal-mining/praw.env
```

### 3. Install PRAW

```bash
pip install praw
```

### 4. Verify

```python
import os, praw
from pathlib import Path
env = Path.home() / ".config/reddit-signal-mining/praw.env"
for line in env.read_text().strip().splitlines():
    k, v = line.split("=", 1)
    os.environ[k] = v

r = praw.Reddit(
    client_id=os.environ["REDDIT_CLIENT_ID"],
    client_secret=os.environ["REDDIT_CLIENT_SECRET"],
    user_agent=os.environ["REDDIT_USER_AGENT"],
    username=os.environ.get("REDDIT_USERNAME"),
    password=os.environ.get("REDDIT_PASSWORD"),
)
print(r.user.me())  # Your username = success
```

### 5. Public JSON fallback (no credentials needed)

```python
import urllib.request, json
req = urllib.request.Request(
    "https://www.reddit.com/r/Accounting/new.json?limit=100",
    headers={"User-Agent": "reddit-signal-mining/1.0 (research)"}
)
data = json.load(urllib.request.urlopen(req))
for child in data["data"]["children"]:
    post = child["data"]
    print(post["title"], post["score"])
```

Public JSON has stricter limits (~60 req/min) and no comment thread expansion.

## Rate Limits

### PRAW mode

Reddit API: 60 requests/minute per OAuth app (authenticated), 10 req/min unauthenticated.

PRAW handles rate-limit tracking internally via `Response.headers["x-ratelimit-remaining"]`. When
remaining drops below 10, PRAW sleeps. The skill adds an extra safety margin:

```python
# After every PRAW call
if getattr(reddit.auth, "limits", {}).get("remaining", 999) < 20:
    time.sleep(5)
```

### Public JSON mode

No headers; rate limit enforced by Reddit's edge. On 429:

```python
backoff = 1
while backoff <= 16:
    try:
        response = urllib.request.urlopen(req)
        break
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(backoff)
            backoff *= 2
        else:
            raise
else:
    # Circuit breaker opens for this sub
    gaps.append(sub)
    continue
```

### Circuit breaker

Per-sub failure counter. 3 consecutive 429/5xx → open circuit, skip sub for 5 minutes, note gap.
Single successful fetch between failures resets counter.

## ToS Compliance Rules

The skill enforces these hard rules (violation = refuse the operation):

1. **No scraping of HTML pages.** Only `reddit.com/*.json` endpoints and PRAW.
2. **No bypassing `[deleted]` or `[removed]` content.** If Reddit hides it, we don't fetch it from
   cache / Wayback / Pushshift / anywhere.
3. **No access to private or quarantined subs.** Even with credentials that could access them,
   skip by policy.
4. **No access to NSFW subs** unless `exclude_nsfw: false` is explicitly set by the caller AND the
   user has opted in (the niche requires it — rare).
5. **No storage of usernames.** Usernames are transient, used only to fetch content, never
   persisted. Not in output records. Not in logs.
6. **No persistent identifier tracking.** Each session is fresh; no linking of posts across
   sessions by the same user.
7. **No ML training.** Data returned is for research analysis in one session. Not aggregated into
   a training corpus across sessions.
8. **Respect `robots.txt`** — the skill honors Reddit's published crawl policy.
9. **User-Agent must identify the skill.** Never impersonate a browser or another tool.

## Privacy / Paraphrase Protocol (HR-11)

### Default: paraphrase

Every `example_quotes` field is paraphrased before output. The paraphrase must:
- Preserve the pain structure (what the user is frustrated about)
- Strip identifying details (names, employers, locations, specific amounts, health details)
- Be written in third person or generic first person ("a user reported..." / "I'm struggling
  with X")
- Not be a verbatim copy of the original post

### Exception: short non-identifying phrases

A 1-5 word phrase may be quoted verbatim if:
- It contains no identifying information (no names, places, specific amounts)
- It is load-bearing (the exact wording matters for the pain extraction)

Examples:
- OK verbatim: `"can't get bank feed to reconcile"`
- NOT OK verbatim: `"my practice in Sheffield billing £80k/yr can't get..."`

### What never goes in output

- Usernames (any form)
- Post IDs (except as opaque `post_refs` for citation)
- Subreddit-specific slang that could identify a small community
- Direct quotes from posts that reveal:
  - Author's name / handle
  - Employer
  - Specific geographic location (city level or smaller)
  - Health status, medical condition
  - Financial specifics (exact income, debt, account balance)
  - Legal situation
  - Relationship / family details
  - Political affiliation

### Dropped pain test

If, after removing identifying content, a pain statement loses its meaning, DROP the pain record
entirely rather than emit a degraded version. It's better to return 4 pain records than 5 with one
that has been sanitized to meaninglessness.

## Block list

Subs known to be toxic, manipulative, or actively hostile to research scraping. The skill refuses
to fetch from these by default. Callers can override with an explicit flag, but the default is NO.

(Block list is intentionally not hard-coded into the skill — it drifts. Callers should maintain
their own block list per niche. Standard filters: `quarantined: true`, `over_18: true` without
explicit opt-in, and any sub where the mod team has publicly requested no scraping.)

## What to do when blocked

If Reddit blocks the client (permanent 403), the skill:
1. Emits a clear error message with the HTTP status
2. Suggests the caller switch auth mode (PRAW ↔ public JSON)
3. Does NOT retry with a different User-Agent
4. Does NOT attempt to rotate IPs / use a proxy

If the block is persistent across both modes, the skill returns an empty result with metadata
`auth_mode: "blocked", gaps: [all_requested_subs]`. The caller decides what to do (fall back to
GDELT, ask the user for manual data, etc.).
