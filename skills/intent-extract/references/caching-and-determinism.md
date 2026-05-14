# Caching and Determinism

The intent-extract skill is content-addressable: re-running on the same
inputs returns the same output without an LLM call. This document
specifies the cache key, eviction rules, and determinism contract.

## Cache key derivation

Cache key = sha256 of:

```
component_id \x00 content_hash \x00 extractor_version \x00 model_id \x00 template_hash
```

where:

- `component_id` — the contract-map component being extracted
- `content_hash` — sha256 of (sorted file sha256s joined by `\n`) for
  every source file resolved from `components[].source_paths`
- `extractor_version` — currently `"1.0.0"` (bumped when the skill
  changes its output shape)
- `model_id` — e.g. `"claude-opus-4-7"` (bumped when the model family
  changes — Opus 4.6 → 4.7 etc.)
- `template_hash` — sha256 of `templates/prompt-base.txt` (bumped when
  the prompt changes)

Any change to ANY of these five inputs invalidates the cache entry and
forces a regeneration. This is the right behaviour — we want caches to
miss on prompt drift, model updates, and source mutation.

## Cache path layout

```
<project_root>/.wiring/intent-cache/<cache_key>.yaml
<project_root>/.wiring/runs/<run_id>/intent/<component_id>.yaml  # hard-link
```

The cache is **project-local**, not global. This is deliberate: cached
intent for project A has no business serving project B, even if a
component happens to have the same name and source content. Different
projects have different consumers downstream.

## TTL eviction

Default TTL is **30 days** (`EVO_INTENT_CACHE_TTL_DAYS`). The
`cache.evict_stale()` helper removes any cache file older than the TTL
on its mtime. Eviction is opportunistic — there is no daemon. evo's
sandbox cleanup (`EVO_SANDBOX_TTL_HOURS`) runs in parallel and may
remove the entire `.wiring/` tree for a stale run.

## Hit rate expectations

On a typical legacy-code maintenance workflow (commit, run evo, fix
something small, run evo again):

- Cold first run: 0% hit, full LLM cost (~$0.70 for 10k LOC / 15 comps)
- Warm second run with 5% file churn: ~95% hit (only churned components
  regenerate); ~$0.04
- "Different mode but same workspace" (mode-a then mode-b): 100% hit on
  intent files; only drift-report differs

The 95%+ warm-run hit ratio is what makes the skill economically viable
on real codebases.

## Determinism contract

Three classes per design §5.1.5:

| Class | Meaning |
|---|---|
| `deterministic` | Pure mechanical fields (entry_points, side_effects, error_paths). No LLM needed; LLM is a hint but the gate validates against static.jsonl. |
| `cached_interpretive` | LLM output served from cache. Byte-identical to the previous regeneration. |
| `fresh_interpretive` | Cache miss; LLM was called this run. The two-arm verification step produced this output. |

`consistency_score` is the similarity (per `two_arm_verify.text_similarity`)
between the current cached output and the most recent fresh regeneration.
Score < 0.95 on a cache hit means the cache is suspect (different LLM
emitted "the same thing" much differently); the run.py logic flags but
does not auto-invalidate. Operators can `rm -rf .wiring/intent-cache` to
force regeneration.

## When determinism breaks

Three known sources of non-determinism that are NOT covered by the cache:

1. **Newline handling in source files** — files that change `\r\n` ↔ `\n`
   produce different content_hash even though content is "the same".
   Use `dos2unix` consistently.
2. **LLM token sampling** — at temperature=0 most providers are still
   ~deterministic, but tail-token disagreement happens. The two-arm
   verification catches this and flags as `interpretive`.
3. **Model-side updates** — `claude-opus-4-7` is a moving target until a
   pinned snapshot. Cache invalidation on `model_id` change handles this.

## How to debug a cache miss

```bash
# What cache key would this component get?
python3 -c "
import sys
sys.path.insert(0, '~/.claude/skills/intent-extract/scripts')
from cache import content_hash, cache_key
from prompt_template import template_hash
from pathlib import Path
files = [Path('src/auth/routes.py'), Path('src/auth/jwt.py')]
ch = content_hash(files)
key = cache_key('auth-service', ch, '1.0.0', 'claude-opus-4-7', template_hash())
print(f'content_hash={ch}')
print(f'cache_key={key}')
print(f'expected file: .wiring/intent-cache/{key}.yaml')
"
```

This lets operators verify whether they're hitting the cache as expected.
