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
    api_delta_findings:                       # v1.1 — major_behind / deprecated only
      - package: pandas
        ecosystem: python
        from_version: "1.5.3"
        to_version: "2.2.3"
        breaking_lines:
          - "pandas 2.0.0: Series.append() removed"
          - "pandas 2.0.0: deprecated get_option('compute.use_numexpr')"
        repo_url: https://github.com/pandas-dev/pandas
    advisories: ["crates.io rate-limited; 3 packages cached >24h"]
```

### `api_delta` field (v1.1)

Per-finding optional block surfaced when `gap_kind in {major_behind, deprecated}` AND a GitHub repo URL is discoverable from the registry metadata. Today covers Python (PyPI `project_urls`), JavaScript (npm `repository.url`), and Rust (crates.io `repository`); other ecosystems gracefully degrade to `api_delta: null`.

Shape:

```json
{
  "source": "github_releases",
  "repo_url": "https://github.com/<owner>/<repo>",
  "from_version": "<declared>",
  "to_version": "<latest>",
  "versions_in_range": ["2.0.0", "2.1.0", "2.2.0"],
  "breaking_lines": ["<package> <ver>: <keyword-extracted line>", ...],
  "release_notes_excerpt": "## 2.0.0\n...",
  "truncated": false
}
```

Caps: ≤5 versions, ≤15 breaking lines, ≤3 KB total release-notes excerpt. Cached 7 days under the `changelog` namespace.

**Why this matters for design agents**: when the AI's training-era knowledge of a library lags its current API surface, blind reuse of remembered patterns ships dead/dropped/changed APIs. The forge approach-agent prompt now mandates version-awareness — each approach agent must name the version it designs against and consult `api_delta` if the lib is flagged stale. See `~/.claude/skills/forge/SKILL.md` "Approach Agent (Claude)" template.

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
