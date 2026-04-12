# Subreddit Discovery — Scoring and Filtering

How `discover_subs` finds niche-relevant subreddits.

## Scoring formula

```
niche_relevance_score =
  0.40 * keyword_match(niche, sub_name + sub_description) +
  0.20 * size_fit(subscribers, min_subs, max_subs) +
  0.20 * activity(post_velocity_per_day, min_active=1) +
  0.10 * engagement(avg_upvotes_per_post, avg_comments_per_post) +
  0.10 * mod_tone_fit(strictness, niche)
```

All components are normalized to 0-1 before combining.

### keyword_match

Tokenize the niche string. Tokenize sub name + description. Compute overlap ratio (Jaccard on
stemmed tokens). Boost for exact substring matches. Penalize for off-topic tokens.

Example: niche="small accounting firms" matches `r/Accounting` (high), `r/smallbusiness` (medium),
`r/personalfinance` (low — personal, not firm).

### size_fit

```
if subscribers < min_subs: 0
elif subscribers > max_subs: 0.3       # penalty for too-big (dilution)
elif 10k <= subscribers <= 500k: 1.0   # sweet spot
else: linear interpolation
```

The sweet spot is 10k-500k subscribers because:
- <10k: too small, weak signal, many are dormant
- 10k-500k: active community, identifiable pain signals, not mega-sub noise
- >500k: r/all-tier subs where signal is diluted by off-topic posts

### activity

```
if post_velocity_per_day == 0: 0
elif post_velocity_per_day >= 10: 1.0
else: linear
```

Dead subs (0 posts/day) are filtered out entirely by the `exclude_inactive_days` rule before
scoring.

### engagement

```
(avg_upvotes_normalized + avg_comments_normalized) / 2
```

Both normalized against the 90th percentile for subs of similar size. Engagement is a second-order
signal — a sub with low post velocity but high per-post engagement is still valuable.

### mod_tone_fit

Heuristic based on sidebar content + rule text + recent mod actions (if visible):
- `permissive` — few rules, minimal removals (good for ranting / pain expression)
- `moderate` — clear rules, occasional removals (good balance)
- `strict` — heavy rules, many removals visible (tends to silence pain venting)

For pain mining, `permissive` or `moderate` subs are preferred — strict mods often remove the
raw-pain posts we're looking for, biasing the signal toward polished / acceptable content.

For niche where professional tone matters (e.g. `r/Accounting`), `moderate` is fine.

## Filtering rules

Applied AFTER scoring, BEFORE returning:

1. **Exclude NSFW** (if `exclude_nsfw: true`)
2. **Exclude subs with no posts in `exclude_inactive_days`** — dead community
3. **Exclude subs with <`min_subscribers`** subscribers
4. **Exclude subs with >`max_subscribers`** subscribers (too diluted)
5. **Exclude subs where `niche_relevance_score < 0.2`** (bottom quintile — not relevant enough)
6. **Exclude known-toxic subs** — see `references/ethics-and-ratelimits.md` for the block list
7. **Exclude subs that return `over_18`, `quarantined`, or `private`** on the API

## Mod tone detection heuristic

Without deep scraping, we can infer mod strictness from public signals:

- Count rule lines in `sub.description` or sidebar
- Check `sub.rules` (PRAW) count
- Sample recent posts: what % have `[removed]` or `[deleted]` bodies
- Check AutoModerator presence (heavy AM → stricter)

```
strictness_score = 0.3 * rule_count_normalized +
                   0.4 * removed_rate +
                   0.3 * automod_presence

< 0.3: permissive
0.3-0.7: moderate
> 0.7: strict
```

## Returning results

After scoring and filtering, rank by `niche_relevance_score` descending and return top `limit`.

Include in each record:
- `sample_recent_titles` — 3-5 titles from the last week, PARAPHRASED (not verbatim) to avoid
  revealing user identity via quoted post titles
- `url` — direct link to the sub (for human spot-check)

Never return usernames, post IDs for sample titles, or any identifying data in the discovery output.
