---
name: social-trading-signals
description: Use when extracting trading signals from X/Twitter, Reddit, or Telegram, detecting pump-and-dump patterns, identifying bot activity, building sentiment aggregation from social media, or modelling signal decay from social sources
---

# Social Trading Signals

## Overview

Social media contains early signals of market moves — but also massive noise, bots, manipulation, and coordinated pumps. The key is **noise filtering** before signal extraction. Raw social sentiment without bot detection and manipulation checks is worse than useless.

**Core principle:** Treat social signals as leading indicators with short half-lives, not as standalone trading signals.

## When to Use

- Building X/Twitter mention and sentiment pipelines for assets
- Monitoring Reddit communities (r/wallstreetbets, r/CryptoMoonShots) for momentum
- Tracking Telegram channels for early crypto signals
- Detecting pump-and-dump schemes before they peak
- Aggregating multi-platform social sentiment into a normalised score

## Bot Detection

```python
import re
from datetime import datetime, timezone
from typing import Optional

def bot_probability(account: dict) -> float:
    """
    Estimate probability that an X/Twitter account is a bot.
    Returns 0.0 (human) to 1.0 (definitely bot).
    account dict keys: followers, following, age_days, tweet_count,
                       verified, default_avatar, description
    """
    score = 0.0

    # New account (< 30 days old)
    if account.get('age_days', 365) < 30:
        score += 0.3

    # Follower/following ratio near 1.0 (bot farms follow each other)
    f_ratio = account.get('followers', 1) / max(account.get('following', 1), 1)
    if 0.8 < f_ratio < 1.2:
        score += 0.2

    # Very high tweet rate: > 50 tweets/day
    tweets_per_day = account.get('tweet_count', 0) / max(account.get('age_days', 1), 1)
    if tweets_per_day > 50:
        score += 0.3

    # No profile description
    if not account.get('description', ''):
        score += 0.1

    # Default avatar
    if account.get('default_avatar', False):
        score += 0.2

    # Not verified (weak signal alone, but adds in combination)
    if not account.get('verified', False):
        score += 0.05

    return min(score, 1.0)


def filter_bot_posts(posts: list[dict], max_bot_prob: float = 0.5) -> list[dict]:
    """Filter out likely bot posts from a feed."""
    return [p for p in posts
            if bot_probability(p.get('author', {})) < max_bot_prob]
```

## Pump-and-Dump Detection

```python
import pandas as pd
import numpy as np

def detect_pump_dump_pattern(
    price: pd.Series,
    mention_count: pd.Series,
    volume: pd.Series,
    lookback_hours: int = 24,
) -> pd.Series:
    """
    Pump-and-dump signature:
    1. Sudden mention spike (>3× baseline in <2h)
    2. Price follows mentions by 30-120 minutes
    3. Volume spike confirms
    4. Price reversal within 4-12 hours
    Returns probability score [0-1] per timestamp.
    """
    mention_baseline = mention_count.rolling(lookback_hours).mean()
    mention_spike = mention_count / (mention_baseline + 1) > 3.0

    volume_baseline = volume.rolling(lookback_hours).mean()
    volume_spike = volume / (volume_baseline + 1) > 2.0

    price_up = price.pct_change(2) > 0.05  # 5% in 2 periods

    pump_signal = (mention_spike & volume_spike & price_up).astype(float)

    # Smooth slightly
    return pump_signal.rolling(3).mean()


def detect_coordinated_posting(posts: list[dict],
                                time_window_minutes: int = 5,
                                min_cluster_size: int = 10) -> list[dict]:
    """
    Detect coordinated posting bursts (same text pattern, different accounts).
    Returns list of suspected coordination clusters.
    """
    from collections import defaultdict
    import hashlib

    # Group by time bucket
    buckets = defaultdict(list)
    for post in posts:
        ts = post['created_at']
        bucket_key = int(ts.timestamp() // (time_window_minutes * 60))
        # Normalise text (remove tickers, lowercase)
        normalised = re.sub(r'\$[A-Z]+', '', post['text'].lower()).strip()
        text_hash = hashlib.md5(normalised[:50].encode()).hexdigest()[:8]
        buckets[(bucket_key, text_hash)].append(post)

    clusters = []
    for (bucket, text_hash), cluster_posts in buckets.items():
        if len(cluster_posts) >= min_cluster_size:
            clusters.append({
                'bucket': bucket,
                'post_count': len(cluster_posts),
                'unique_authors': len(set(p['author_id'] for p in cluster_posts)),
                'sample_text': cluster_posts[0]['text'][:100],
                'coordination_ratio': 1 - len(set(p['author_id'] for p in cluster_posts)) / len(cluster_posts),
            })

    return clusters
```

## Reddit Sentiment Pipeline

```python
import praw
import pandas as pd
from datetime import datetime, timezone

SUBREDDITS_BY_ASSET_CLASS = {
    'crypto':  ['CryptoCurrency', 'CryptoMoonShots', 'Bitcoin', 'ethereum'],
    'stocks':  ['wallstreetbets', 'stocks', 'investing', 'StockMarket'],
    'options': ['options', 'thetagang', 'wallstreetbets'],
}

def fetch_reddit_mentions(
    reddit: praw.Reddit,
    query: str,
    subreddits: list[str],
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch mentions of a ticker/asset across subreddits."""
    records = []
    for sub_name in subreddits:
        sub = reddit.subreddit(sub_name)
        for post in sub.search(query, sort='new', limit=limit):
            records.append({
                'subreddit': sub_name,
                'title': post.title,
                'score': post.score,
                'comments': post.num_comments,
                'created': datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                'upvote_ratio': post.upvote_ratio,
                'flair': post.link_flair_text,
            })
    return pd.DataFrame(records)


def reddit_engagement_score(df: pd.DataFrame) -> float:
    """
    Weighted engagement score.
    Upvote-ratio-weighted to reduce downvoted FUD.
    """
    if df.empty:
        return 0.0
    weighted = (df['score'] * df['upvote_ratio'] * (1 + df['comments'] * 0.1))
    return float(weighted.sum())
```

## Signal Decay Model

```python
import numpy as np

def apply_signal_decay(
    signal_values: pd.Series,
    halflife_hours: float = 6.0,
    timestamp_col: pd.DatetimeIndex = None,
) -> pd.Series:
    """
    Exponential decay applied to social signal strength.
    Social signals lose relevance fast — typical halflife 4-12h.
    """
    if timestamp_col is None:
        timestamp_col = signal_values.index

    now = pd.Timestamp.utcnow().tz_localize(None)
    if hasattr(timestamp_col[0], 'tzinfo') and timestamp_col[0].tzinfo:
        now = pd.Timestamp.utcnow()

    age_hours = (now - timestamp_col).total_seconds() / 3600
    decay_factor = np.exp(-np.log(2) * age_hours / halflife_hours)
    return signal_values * decay_factor


# Signal half-lives by source (empirical)
SIGNAL_HALFLIVES = {
    'twitter_breaking_news': 2,     # hours
    'twitter_influencer':    6,
    'reddit_post':           12,
    'telegram_alert':        1,
    'news_headline':         4,
    'earnings_mention':      48,
}
```

## Multi-Platform Aggregation

```python
def aggregate_social_sentiment(
    twitter_score: float,    # normalised [-1, 1]
    reddit_score: float,
    telegram_score: float,
    weights: dict = None,
) -> dict:
    """
    Weighted aggregate of social sentiment signals.
    Weights reflect data quality and market relevance.
    """
    if weights is None:
        weights = {'twitter': 0.40, 'reddit': 0.35, 'telegram': 0.25}

    composite = (
        twitter_score  * weights['twitter'] +
        reddit_score   * weights['reddit'] +
        telegram_score * weights['telegram']
    )

    return {
        'composite_score': composite,
        'signal': 'bullish' if composite > 0.3 else 'bearish' if composite < -0.3 else 'neutral',
        'confidence': abs(composite),
    }
```

## Quick Reference — Source Characteristics

| Source | Latency | Noise | Reliability | Best For |
|--------|---------|-------|-------------|----------|
| X/Twitter | Minutes | Very High | Low-Medium | Trend detection |
| Reddit WSB | Hours | High | Medium | Retail momentum |
| Telegram | Minutes | Very High | Low | Crypto pump alerts |
| StockTwits | Hours | Medium | Medium | Equity retail sentiment |
| News RSS | Minutes | Low | High | Fundamental events |

## Common Mistakes

1. **No bot filtering** — bots can represent 30-70% of crypto Twitter traffic
2. **Linear mention count** — raw mention count is meaningless without baseline normalisation
3. **Ignoring account quality** — 1 mention from a 1M-follower account ≠ 1000 mentions from bots
4. **No pump-dump check** — acting on social spikes without checking pump signatures = getting dumped on
5. **Stale signal** — social sentiment from 6+ hours ago has minimal predictive value for crypto
6. **Single platform** — one platform can be artificially manipulated; multi-source aggregation is more robust

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Treating all social media posts as equal signal sources | Bot accounts, paid promoters, and coordinated pump groups dominate crypto social media; noise overwhelms signal | Score sources by historical accuracy, account age, follower quality; weight verified accounts and known traders higher |
| Acting on social sentiment spikes without delay | By the time retail social media is excited, smart money has already positioned; you buy the top | Build in a signal delay (1-4 hours); validate social spikes against order flow and price action before entering |
| No bot detection on social data feeds | Bot farms generate artificial consensus; 60-80% of crypto Twitter volume during pumps may be automated | Implement bot scoring (account age, tweet patterns, follower/following ratio, content similarity); filter before aggregation |
| Using raw mention count as a trading signal | Popular tokens are always mentioned; absolute count says nothing about sentiment change | Use rate-of-change in mentions, sentiment shift (positive-to-negative ratio change), and anomaly detection |
| Not modelling signal decay | A Reddit post from 3 days ago still weighted equally to one from 3 minutes ago; stale signals mislead | Apply exponential decay with half-life tuned to platform (Twitter: 2-4 hours, Reddit: 6-12 hours, Telegram: 1-2 hours) |
