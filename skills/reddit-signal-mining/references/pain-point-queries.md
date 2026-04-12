# Pain-Point Extraction — Prompts, Dedup, Scoring

How `mine_pains` turns raw Reddit posts/comments into structured pain records.

## Extraction prompt templates

Each post/comment pair is scanned with multiple prompt variants. A pain is recorded if ANY variant
returns a non-empty extraction. This maximizes recall at the cost of some duplicates (handled by
the dedup step).

### Default prompts (run per post)

```
## Prompt 1: Pain narrative
Given the following Reddit post + top comments:
---
{POST_TEXT}
{COMMENT_TEXT}
---
Extract any pain points the author or commenters describe. A "pain point" is:
- A specific, named frustration with a tool, workflow, or situation
- A problem they tried to solve and couldn't
- A request they made that was ignored by incumbents
- A workaround they built because no good solution exists

Return JSON:
{
  "pains": [
    {"pain": "1-sentence description", "evidence": "paraphrased quote", "frequency_in_thread": int}
  ]
}

If the post is off-topic, a meme, or doesn't contain clear pain, return {"pains": []}.
Do NOT invent pain that isn't clearly in the text. Silence is a valid answer.
```

```
## Prompt 2: Workaround mining
Scan the following Reddit thread for any workarounds users built or use because the "official"
solution is inadequate:
---
{POST_TEXT}
{COMMENT_TEXT}
---
A workaround is a sign of a pain point that has no good commercial solution.

Return JSON:
{
  "workarounds": [
    {
      "underlying_pain": "what problem the workaround is solving",
      "workaround_description": "what they're doing instead",
      "evidence": "paraphrased quote"
    }
  ]
}
```

```
## Prompt 3: Incumbent complaint mining
Find complaints about specific products, tools, or services in this Reddit thread:
---
{POST_TEXT}
{COMMENT_TEXT}
---
For each complaint, capture the product name and what's wrong with it.

Return JSON:
{
  "complaints": [
    {
      "incumbent_product": "specific name",
      "complaint": "what's broken or missing",
      "evidence": "paraphrased quote"
    }
  ]
}
```

```
## Prompt 4: Ignored-request mining
Find requests, feature asks, or wishes in this thread that were unanswered or dismissed:
---
{POST_TEXT}
{COMMENT_TEXT}
---

Return JSON:
{
  "ignored_requests": [
    {
      "request": "what they asked for",
      "context": "what tool/situation they were asking about",
      "evidence": "paraphrased quote"
    }
  ]
}
```

### Niche-specific overrides

Callers can pass `pain_prompt_variants` to override the defaults for specialized niches. For
example, a caller mining `r/cscareerquestions` might use prompts tuned for career pain, while a
caller mining `r/DIY` might use prompts tuned for tool/material/skill gaps.

## Normalization

After running all prompts per post, the skill:
1. Collects all `pain`/`underlying_pain`/`complaint`/`request` fields as candidates
2. Normalizes each candidate to a canonical pain statement:
   - Remove user-specific context ("my client", "our firm" → generic "client", "firm")
   - Strip sentiment ("I HATE that...", "It's SO frustrating when..." → action-neutral)
   - Lowercase, stem
3. Stores raw and normalized forms

## Dedup

The core dedup rule: **if two pains have cosine similarity > 0.85 on their normalized forms, merge
them.**

Cosine similarity is computed over TF-IDF vectors of the normalized pains. For simpler environments
without scikit-learn, a token-set Jaccard ≥ 0.7 is an acceptable proxy.

### Merge rules

When pains A and B are merged into canonical C:

```
C.pain                     = A.pain (the one with higher engagement)
C.frequency                = A.frequency + B.frequency
C.subreddits               = unique(A.subreddits + B.subreddits)
C.example_quotes_paraphrased = top-3 by engagement across A and B (paraphrased)
C.post_dates               = unique(A.post_dates + B.post_dates)
C.engagement.total_upvotes = A.upvotes + B.upvotes
C.engagement.total_comments = A.comments + B.comments
C.existing_workarounds     = union(A.workarounds + B.workarounds)
C.incumbent_mentions       = union(A.incumbents + B.incumbents)
C.post_refs                = A.refs + B.refs
```

## unmet_need_score formula

```
unmet_need_score =
  0.35 * normalized_frequency  +       # how often the pain appears
  0.25 * normalized_engagement +       # upvotes + comments on pain-carrying posts
  0.20 * workaround_density    +       # proportion of mentions that cite a workaround
                                        # (workarounds = pain has no good solution)
  0.15 * incumbent_failure_density +    # proportion of mentions that cite a failing incumbent
  0.05 * recency                        # bias toward pains still being discussed recently
```

All components normalized to 0-1 within the batch.

Interpretation:
- `unmet_need_score > 0.7`: high-confidence unmet need, good founder-ideation input
- `0.4 - 0.7`: medium — worth investigation but not a clear signal
- `< 0.4`: weak — probably ambient grumbling, not a structural pain

## Privacy rules (HR-11 enforcement)

Before emitting a pain record, the skill must:
1. **Paraphrase all `evidence` fields** into `example_quotes_paraphrased`. Default: paraphrase.
   Exception: ≤5 non-identifying words can be quoted verbatim if load-bearing.
2. **Remove any user-identifying content** from the paraphrase:
   - Names (even first names if paired with location/employer)
   - Employer names
   - Specific locations (neighborhood, street)
   - Health status
   - Financial details (specific dollar amounts, income, debt)
3. **Drop any pain** that cannot be paraphrased without losing all meaning (i.e., the "pain" was
   inseparable from the user's identity)

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Extraction returns empty for all posts | Prompt too strict; subreddit has different pain vocabulary | Add a niche-specific prompt variant |
| Dedup over-merges (loses distinct pains) | Similarity threshold too low (0.85 is default) | Raise to 0.9 for diverse niches; keep 0.85 for narrow niches |
| Dedup under-merges (many duplicates in output) | Normalization not aggressive enough | Add more stopwords, stem more aggressively, or raise Jaccard threshold |
| unmet_need_score always clusters around 0.5 | Within-batch normalization flattens the signal | OK for ranking; use absolute thresholds only across large samples |
| Every pain has FinBERT-misfired sentiment | FinBERT applied to non-financial text | Use `all_minilm_l6_v2` or skip sentiment for pain mining |
