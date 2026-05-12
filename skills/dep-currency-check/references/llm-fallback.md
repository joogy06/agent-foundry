# LLM fallback — bounded firing rules

## When LLM fallback fires

ONLY when ALL of:

1. Registry returns `deprecated: true` with prose >200 chars AND no machine-readable `successor` field → ask LLM to extract `successor` + `urgency`
2. (Opt-in via `--llm-cve-judge`) A CVE applies to a version range that includes the declared range AND the CVE summary mentions a specific feature/code path → ask LLM to judge applicability

## When LLM fallback NEVER fires

- `--offline` set
- `--no-llm` set
- `--strict-airgap` set
- Pre-commit hook context (commit-time MUST be fast + deterministic)
- Registry data is already structurally clear (`deprecated: false`)
- `grounding_mode: internal-only` in `~/.claude/state/sources.json`

## Output marking (Codex challenger requirement)

EVERY LLM-derived field is tagged:

```yaml
deprecation_verdict:
  is_deprecated: true
  successor: foo-ng
  urgency: near-term            # immediate | near-term | informational
  confidence_level: interpretive  # LLM-derived, treat with caution
  source: llm                    # NOT osv, NOT pypi, NOT registry
  source_links:                  # ALWAYS link to underlying changelog / release notes
    - https://example.com/foo/CHANGELOG.md#v3.0.0
    - https://example.com/foo/issues/123
  consulted_model: gpt-5.5      # served_by capture per cross-cli-deliberation
```

## LLM verdicts NEVER feed into

- `blocks_build` flag computation (only structured CVE + version data does)
- `G_DEP_CURRENCY` gate decisions
- `scope_delta` entry emission (only structured findings trigger scope_delta)
- Pre-commit hook exit code

LLM enrichment is purely **report-text decoration** — surfaces the interpretation to the user, who makes the judgment. The mechanical decision paths (gate / scope_delta / hook) stay grounded in registry + OSV data only.

## Mechanics

- **Subprocess**: `codex exec --ephemeral -s read-only` preferred, `gemini -m gemini-3.1-pro-preview -p` fallback
- **Timeout**: 30s hard per fallback call
- **Captures `served_by`** per cross-cli-deliberation pattern — tier matters
- **Cache**: verdict cached at `deprecation/<ecosystem>/<package>.json` with 7-day TTL; re-invokes only on notice text change

## Gemini env (host-specific)

Per global CLAUDE.md, ALWAYS use:
```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -m gemini-3.1-pro-preview -p "..."
```

## Prompt template (deprecation interpretation)

```
You are reading a registry deprecation notice for package `<package>` (ecosystem: <ecosystem>).

Notice text (verbatim):
---
<notice text>
---

Return ONLY this JSON (no prose, no markdown fences):
{
  "is_deprecated": true|false,
  "successor": "<package name>" or null,
  "urgency": "immediate"|"near-term"|"informational",
  "evidence": "<verbatim quote from notice>"
}

Rules:
- "immediate" = security/breaking; users MUST migrate now
- "near-term" = author recommends migrating soon; no security issue
- "informational" = "we've moved" / aesthetic
- successor: ONLY if the notice names a specific replacement package; otherwise null
```

## Failure modes

- LLM unavailable (`codex` and `gemini` both missing or fail) → return `None`; report uses raw deprecation prose
- LLM returns non-JSON or malformed JSON → return `None`; report uses raw deprecation prose
- LLM times out (30s) → return `None`; report uses raw deprecation prose
- LLM verdict is internally contradictory (e.g., `is_deprecated: false` but `urgency: immediate`) → return `None`

Never block, never raise. The skill ALWAYS produces a Report — LLM enrichment is purely additive.
