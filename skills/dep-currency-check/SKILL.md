---
name: dep-currency-check
description: Use when checking dependency currency and known CVEs in any project with manifests — pyproject.toml / package.json / Cargo.toml / go.mod / Gemfile / pom.xml. Surfaces stale library versions and known vulnerabilities BEFORE AI design agents propose using them. Callable from forge Step 1 (advisory), alf Step 2a (data extraction), pre-commit hooks (POSIX `.sh` + Windows hardened `.ps1`), standalone CLI, the `G_DEP_CURRENCY` gate in `_meta/gates.py`, and as a scope_delta source for critical CVEs in direct deps. Trigger on - "check deps", "what versions are stale", "CVE check", "dependency audit", "is this lib current", "freshness check", forge Step 1 auto-invoke when manifests detected.
---

# dep-currency-check

A primitive skill that surfaces **stale library versions** and **known CVEs** in a project's dependencies before AI design agents propose using them. Replaces the recurring rework loop where LLM-generated code references CVE-bearing deps and only gets caught at git push.

## When to use

- **forge Step 1** — auto-invoke when manifests detected; feed `dependency_health` into `shared_context` so design targets current versions
- **alf Step 2a** — structured callable primitive; alf reads JSON instead of parsing 3 model outputs
- **Pre-commit hook** — POSIX `.sh` + Windows enterprise-hardened `.ps1`; defense-in-depth at commit time (advisory mode by default)
- **Standalone CLI** — `python3 -m dep_currency_check <project-root>`
- **`G_DEP_CURRENCY` gate** — opt-in via `.contract/gates.yaml`; the ONLY caller that passes `--mode strict`
- **scope_delta source** — critical CVEs in direct deps become `artifact_kind: file` entries that bob's pause cycle handles

## When NOT to use

- Pure information lookup ("what does this library do?") — use `web-research` or `python-flask-developer` etc. instead
- TRIVIAL / SIMPLE single-file changes that touch no dependency declarations
- Real-time CVE monitoring — this is currency check, NOT zero-day detection
- SBOM emission, license compliance, transitive upgrade planning — separate problem spaces
- Private registry resolution — deferred to v1.1

## Architecture (4-layer)

```
Callers (forge / alf / pre-commit / CLI / G_DEP_CURRENCY / scope_delta)
        |
        v
Orchestrator (dep_currency_check.py)
  - reads ~/.claude/state/sources.json grounding mode
  - probes which community tools are installed (once per run)
  - dispatches: try wrapper -> fall back to HTTP -> compare/report
  - exit-code contract (0/1/2/3/4)
        |
        v
+-- Layer 2A: PRIMARY data path -- community wrappers --+
|   osv_scanner, pip_audit, cargo_audit, govulncheck    |
|   (NO npm_audit -- FP rate too high per Gemini)       |
+-------------------------------------------------------+
        | (fallback when wrapper unavailable)
        v
+-- Layer 2B: FALLBACK data path -- stdlib HTTP --------+
|   manifests / registry / compare / report             |
|   PyPI, npm, crates, go-proxy, RubyGems, Maven        |
|   + OSV.dev /v1/querybatch                            |
+-------------------------------------------------------+
        |
        v
External: registries + OSV.dev + (subprocess) wrappers
```

## Boundary properties

- The CLI is the **only** module that reads `~/.claude/state/sources.json` — air-gap policy centralized
- Layer 2A (community wrappers) is the **primary path**; called first per ecosystem
- Layer 2B (stdlib HTTP) is the **fallback path**; only fires when the corresponding wrapper unavailable
- Cache layer is shared by both 2A and 2B (split TTL: vulns 2h, versions 12-24h, deprecation 7d)
- **NEVER** does an LLM result feed back into a gate or scope_delta entry — LLM is interpretive enrichment only

## Quickstart

```bash
# Standalone scan with markdown rendering of JSON canonical
python3 -m dep_currency_check /path/to/project --format json --render markdown

# Pre-commit hook style (advisory, fast)
python3 -m dep_currency_check "$(git rev-parse --show-toplevel)" \
  --changed-manifests "$CHANGED" --severity critical --format json --quiet

# Strict gate from G_DEP_CURRENCY
python3 -m dep_currency_check /path/to/project --mode strict --format json

# Air-gap CI
python3 -m dep_currency_check /path/to/project --offline --strict-airgap --format json
```

## Output schema

Single canonical data contract: JSON. Schema-versioned (`dep-currency.v1`). All other outputs (markdown, table, yaml) are **renderings** over the canonical JSON with zero authority of their own.

```json
{
  "schema_version": "dep-currency.v1",
  "generated_at": "2026-05-12T14:00:00Z",
  "project_root": "/path/to/project",
  "grounding_mode": "full",
  "manifests_scanned": ["pyproject.toml", "poetry.lock"],
  "summary": {"critical": 1, "high": 0, "deprecated": 1, "current": 47},
  "findings": [/* one per Dependency with gap, cves, blocks_build */],
  "advisories": ["osv-scanner unavailable for python; fell back to OSV.dev HTTP"],
  "osv_records": [/* embedded OSV-format vulnerability records */]
}
```

See `references/output-schema.md` for full schema + examples (including offline-cold-cache shape).

## Exit codes (CLI + gate)

| Code | Meaning |
|---|---|
| 0 | Pass — no strict-blocking findings (advisory findings still reported) |
| 1 | STRICT BLOCK — critical CVE in DIRECT + PRODUCTION dep with fix-available AND `--mode strict` |
| 2 | Soft finding — reportable but not blocking, OR strict mode with non-critical findings |
| 3 | Environmental error — parse failure, no python3, malformed manifest |
| 4 | Offline + cold cache for required packages (warn unless `--strict-airgap`) |

The pre-commit hook does NOT pass `--mode strict` — commit-time stays advisory. Only `G_DEP_CURRENCY` (opted in via `.contract/gates.yaml`) passes strict.

## Integration

See `references/integration-*.md` files for caller-specific plumbing:

- `references/integration-forge.md` — forge Step 1 advisory auto-invoke
- `references/integration-alf.md` — alf Step 2a replacement
- `references/integration-precommit.md` — POSIX + Windows hook templates
- `references/integration-gate.md` — `G_DEP_CURRENCY` gate contract
- `references/integration-scope-delta.md` — S029 hook for critical-CVE-in-direct-dep
- `references/air-gap-mode.md` — sources.json grounding + offline behavior
- `references/windows-hardening.md` — `.ps1` pre-commit enterprise rules

Other reference docs:

- `references/ecosystem-quirks.md` — per-registry edge cases
- `references/http-protocol.md` — exact GET URLs, response shapes, rate limits
- `references/cache-design.md` — split-TTL cache layout + ETag sidecar
- `references/osv-integration.md` — OSV.dev `/v1/querybatch` usage
- `references/community-tools.md` — when to wrap pip-audit / cargo-audit / osv-scanner / govulncheck
- `references/llm-fallback.md` — bounded firing rules + prompt templates
- `references/output-schema.md` — JSON canonical schema + rendering layer
- `references/anti-patterns.md` — 15+ anti-patterns

## Anti-patterns (table)

| Don't | Why |
|---|---|
| Add `requests` / `httpx` / `pydantic` to make the HTTP layer "nicer" | Skill MUST work in the global skills library without virtualenv. Stdlib is the contract. |
| Block on the LLM fallback | Codex/agy can hang. 30s subprocess timeout, hard. On timeout, treat as "couldn't interpret" and continue. |
| Skip lockfile scanning ("manifest-only is enough") | Majority of CVEs hide in transitive deps. Read lockfiles for direct + first-level transitive minimum. |
| Wrap `npm audit` | FP rate too high (Gemini research). Use OSV-direct for npm. |
| Treat the 24h cache TTL as a hard rule | 24h is the FLOOR for AUTOMATIC refresh. `--no-cache` always bypasses. Vulns get 2h TTL. |
| Fail loudly on a single registry being unreachable | Multi-ecosystem projects must produce partial reports. Mark deferred + advisory; never abort. |
| Query GHSA directly | OSV aggregates GHSA. Direct GHSA = redundant queries + extra auth surface. |
| Mint a new `scope_delta.v1 artifact_kind` for CVEs | Schema frozen. Reuse `file` + `extractor_meta.source: dep-currency-check`. |
| Read `~/.claude/state/sources.json` once at module load | Sessions can flip air-gap state. Read fresh on every CLI invocation. |
| Auto-install pre-commit hooks on session start | Too invasive. Document the one-liner; never write to `.git/hooks/` automatically. |
| Trust the User-Agent default for crates.io | crates.io REJECTS missing User-Agent. Always set explicit User-Agent header. |
| Forget capital-letter escaping for Go modules | `github.com/Azure/foo` → `github.com/!azure/foo` for proxy.golang.org. Common gotcha. |
| Use `-ExecutionPolicy Bypass` in the `.ps1` pre-commit | Enterprise machines have this blocked at GPO. Use `-NoProfile -NonInteractive -File`. |
| Dedupe scope_delta AFTER `write_record` | Produces the 2000+-record explosion documented in `_meta/gates.py`. Dedup key `(manifest_path, package, cve_id)` BEFORE write. |
| Use LLM output to set `blocks_build` flag or trigger scope_delta | LLM verdicts are `confidence_level: interpretive` — NEVER feed mechanical decision paths. |
