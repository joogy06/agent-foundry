# Integration: forge Step 1 (advisory only)

Per Codex challenger revision: forge Step 1 NEVER fails. `dependency_health` is **informational context only**. Blocking enforcement lives at bob's WP boundary + pre-commit + `G_DEP_CURRENCY` gate, NOT at design-time.

## Patch location

`~/.claude/skills/forge/SKILL.md` Step 1 — after wiki check, before clarifying questions.

## Patch text (additive paragraph)

```bash
# After wiki binding check, detect manifests and run dep-currency-check (advisory only)
if find "$PWD" -maxdepth 4 -name 'pyproject.toml' -o -name 'package.json' \
  -o -name 'Cargo.toml' -o -name 'go.mod' -o -name 'Gemfile' \
  -o -name 'pom.xml' 2>/dev/null | grep -q .; then
  python3 -m dep_currency_check "$PWD" --format json --severity high --quiet \
    --output /tmp/forge-dep-currency-${FORGE_SESSION_ID:-default}.json 2>&1 || true
fi
```

The `|| true` is mandatory — forge MUST NOT fail on this skill's exit code. Read the JSON if present, ignore otherwise.

## `shared_context` consumer

```yaml
project_context:
  hard_rules: ...
  wiki_findings: ...
  dependency_health:                          # NEW
    grounding_mode: full
    schema_version: dep-currency.v1
    summary: {critical: 0, high: 2, deprecated: 1, current: 47}
    blocking_findings:                        # only critical/high in DIRECT deps
      - package: requests
        ecosystem: python
        declared: ">=2.20,<2.28"
        latest_stable: "2.32.3"
        cves: [CVE-2024-35195]
        impact: "Design proposing new HTTP client code must not target requests <2.32.0"
    advisories: ["crates.io rate-limited; 3 packages cached >24h"]
```

## Skip rules forge MUST honor

- **TRIVIAL/SIMPLE complexity tasks** → skip dep-currency-check (latency budget; advisory anyway)
- **`grounding_mode: internal-only` AND cache cold** → include `grounding_mode: offline-cold-cache` in shared_context.advisories and continue
- **forge session timeout exceeded** → log warning, continue without `dependency_health`

## Why advisory only

Forge is design-phase. Hard-blocking design on dep currency:

1. Creates a circular dependency (the design might be "upgrade this dep")
2. Punishes researchers exploring options
3. Duplicates the enforcement at bob's WP boundary and `G_DEP_CURRENCY` gate

So forge sees `dependency_health` as **context** — design agents reference it ("don't target requests <2.32.0") but the design is never refused on this basis.
