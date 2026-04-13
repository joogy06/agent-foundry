---
name: knowledge-grounding
description: Use when checking what knowledge sources are available (wikis, docs, Confluence, Jira, vector stores, internet), determining grounding mode (internal-only vs full), routing queries to the best source, or flagging ungrounded answers. Covers source discovery, air-gap detection, grounding tiers (verified/grounded/inferred/training-only), and strict_airgap enforcement.
---

# Knowledge Grounding -- Source Discovery and Answer Provenance

## Overview

Discovers available knowledge sources, produces a manifest, routes queries to the best source, and flags ungrounded answers. Companion to env-adoption (which handles tool availability). Two-tier state: persistent manifest (`~/.claude/state/sources.json`) and volatile session state (`$XDG_RUNTIME_DIR/knowledge-grounding/session-<id>.json`).

## When to Use

- Session start (after env-adoption) -- discover available knowledge sources
- Before answering factual questions -- check what sources can ground the answer
- On air-gapped / enterprise systems -- detect what is reachable
- When a query returns training-only results -- flag explicitly with tier
- When `strict_airgap: true` -- enforce user override for ungrounded answers

## When NOT to Use

- Do not replace wiki auto_consult -- this skill composes with `.wiki-link` behavior
- Do not use for tool availability -- that is env-adoption
- Do not use for search execution -- that is web-research, wiki, confluence-rest-api

## Operations

| Operation | Command | Purpose |
|-----------|---------|---------|
| **discover** | `bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh discover` | Scan local sources, internet canary, write manifest |
| **status** | `bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh status` | Human-readable knowledge landscape |
| **get** | `bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh get <path>` | Shell-friendly accessor (thin jq wrapper) |

### discover flags

| Flag | Effect |
|------|--------|
| `--force` | Re-probe even if manifest is fresh (<24h) |
| `--remote` | Also probe remote endpoints immediately (adds latency) |
| `--silent` | No stdout, just write state files |
| `--json` | Output combined manifest + session as JSON |

### get paths

```bash
discover.sh get internet_reachable           # true/false
discover.sh get grounding_mode               # internal-only / full
discover.sh get strict_airgap                # true/false
discover.sh get sources.wiki_trading.path    # /path/to/wiki
discover.sh get sources.internet.reachable   # true/false
discover.sh get session.active_sources       # JSON array
```

## Routing Logic (per-query priority)

When answering a factual question, check sources in this order. Stop at the first tier that produces a match. Combine if multiple tiers contribute.

| Priority | Source Type | Check | Skill/Tool |
|----------|-----------|-------|------------|
| 1 | Wiki (auto_consult first) | grep for keywords | wiki skill |
| 2 | Project docs (local) | grep docs/, PROJECT.md, COMPONENT.md | Read/Grep |
| 3 | Git repo docs (local) | grep configured doc_paths | Read/Grep |
| 4 | Vector store | semantic search if configured | research-vectorization |
| 5 | Confluence (remote, lazy) | CQL search | confluence-rest-api |
| 6 | Jira (remote, context) | JQL search | jira-rest-api |
| 7 | Internet | web search | web-research (only if `internet_reachable: true`) |
| 8 | Training data | always available | flag explicitly as tier 4 |

**Manifest provides facts only. This routing logic decides per-query.**

## Grounding Tiers

| Tier | Label | Meaning | When to use |
|------|-------|---------|------------|
| 1 | **verified** | Direct match in wiki, Confluence, or git docs with citation | Source found, content matches query |
| 2 | **grounded** | Partial match or semantic similarity from vector/multi-source | Related content found, synthesized |
| 3 | **inferred** | Cross-referenced from multiple weak signals | No direct match, patterns align |
| 4 | **training-only** | No internal source -- model training knowledge only | Nothing found; flag explicitly |

Every answer should include grounding metadata:
- `[Grounding: verified | source: wiki_trading/page-name]`
- `[Grounding: training-only | no internal sources matched]`

In `strict_airgap` mode (opt-in), tier 4 answers require explicit user override: "No internal source found. This would use model training data (cutoff May 2025). Proceed? [y/n]"

## Integration

| Touchpoint | Behavior |
|-----------|----------|
| **CLAUDE.md session start** | After env-adoption, run `discover.sh discover --silent` |
| **forge step 1** | Read sources.json, include active sources in shared_context |
| **web-research** | Check `internet_reachable` before attempting search; suggest local sources if false |
| **wiki auto_consult** | Unchanged -- grounding skill defers to existing `.wiki-link` behavior |
| **All answers** | Append grounding metadata (tier + source citation) when answering factual questions |

See `references/integration.md` for detailed patterns.

## Anti-Patterns

| Don't | Why | Do Instead |
|-------|-----|------------|
| Replace wiki auto_consult | Breaks existing behavior, two routing paths | Defer to .wiki-link, augment with sources |
| Probe remote endpoints at session start | Hangs on air-gapped systems, violates <3s | Lazy probe on first query needing remote source |
| Bake routing logic into manifest JSON | Routing rules change, manifest becomes stale policy | Manifest = facts, SKILL.md = routing logic |
| Score confidence by source type alone | Stale wiki page is not better than training data | Consider match quality, freshness, provenance |
| Block on training-only answers by default | Most systems are not strict air-gap | strict_airgap is opt-in, default=off |
| Auto-detect enterprise endpoints | URLs are not discoverable, wrong guesses waste time | Config file for enterprise, auto-detect for local |
