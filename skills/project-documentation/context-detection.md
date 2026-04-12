# Context Detection

Reference for `project-documentation`. Detects whether the current work is standalone or part of an integrated system, maps dependencies, and determines impact radius before any changes are made.

**Any skill can call this.** It is not forge/bob/PA-specific.

---

## When to Run

Run context detection at the START of any task that modifies code or configuration:
- Before implementation (forge design phase, bob execution, direct skill work)
- Before testing (determines testing surface)
- Before deployment (determines deployment order)
- When a skill is invoked standalone and needs to understand scope

Skip for:
- Pure documentation tasks
- Read-only queries ("what does X do?")
- Tasks the user explicitly marks as standalone ("just fix this one file")

---

## Detection Flow

```
Step 1: PROJECT CONTEXT
  Check for PROJECT.md in project root
    EXISTS → integrated project. Read components table + interaction edges.
    MISSING → check for package manifest (Step 2)

Step 2: PACKAGE MANIFEST
  Check for package.json, pyproject.toml, go.mod, composer.json,
         Cargo.toml, pom.xml, build.gradle, Gemfile, mix.exs
    EXISTS → read dependencies list. Check for workspace/monorepo config.
    MISSING → likely standalone script or simple project

Step 3: COMPONENT MEMBERSHIP
  If PROJECT.md exists:
    Match CWD or target files against component owned_paths
      MATCH → working inside a documented component. Read its COMPONENT.md.
      NO MATCH → working outside documented components (new component or standalone area)

Step 4: CONSUMER DETECTION
  If inside a component with public interfaces:
    Check who consumes this component (from PROJECT.md interaction edges)
    Check who imports files in this component (grep for import/require/use patterns)
      CONSUMERS FOUND → changes here affect others. Track them.
      NO CONSUMERS → leaf component, changes are isolated

Step 5: DEPENDENCY DEPTH
  Count:
    - How many components depend on this one (downstream consumers)
    - How many components this one depends on (upstream providers)
    - External service dependencies (APIs, databases, queues)
      SCORE = downstream + upstream + external

Step 6: CLASSIFY
  Based on Steps 1-5, assign context_type:
```

## Context Classification

| Context Type | Signals | Impact |
|-------------|---------|--------|
| **standalone** | No PROJECT.md, no consumers, single entry point, no/few package deps | Changes are isolated. Test locally. No cascade risk. |
| **component** | Inside a documented component, has consumers OR providers | Changes may affect consumers. Check interfaces. Test integration points. |
| **library** | Multiple consumers import from this, no own entry point | Changes affect all consumers. Must preserve public API. Requires consumer testing. |
| **service** | Own entry point + API consumers + external dependencies | Changes affect API contract. Must check schema compatibility. May need coordinated deployment. |
| **monorepo-package** | Workspace member, other packages depend on it | Changes may require version bump. Check cross-package imports. |

## Context Report

After detection, produce a context report (in memory, not written to disk unless requested):

```
## Context Report

context_type: component
project: myapp (from PROJECT.md)
component: payment-service (from COMPONENT.md)

### Dependencies (this component depends on)
| dependency | type | interface |
|-----------|------|-----------|
| auth-service | internal component | verify_token(token) -> user_id |
| database | internal component | orders table, payments table |
| Stripe API | external service | POST /v1/charges |
| redis | infrastructure | session cache |

### Consumers (depend on this component)
| consumer | interface | impact if broken |
|----------|-----------|-----------------|
| checkout-flow | POST /api/payments | checkout blocked |
| admin-dashboard | GET /api/payments/history | reporting delayed |
| webhook-handler | payment.completed event | fulfilment stops |

### Change Impact
| change type | risk | action needed |
|------------|------|---------------|
| Internal logic (no interface change) | LOW | Test this component only |
| Interface change (same contract) | MEDIUM | Test this + consumers |
| Breaking interface change | HIGH | Update consumers, coordinate deployment |
| New dependency added | MEDIUM | Check availability, add error handling |
| Dependency removed | HIGH | Verify no other consumer needs it |

### Testing Surface
| scope | what to test | priority |
|-------|-------------|----------|
| Unit | This component's functions | Always |
| Integration | Connections to auth-service, database, Stripe | If interface touched |
| Consumer | checkout-flow, admin-dashboard, webhook-handler | If public interface changed |
| E2E | Full checkout flow | If payment logic changed |

### Performance Profile

| aspect | value | source |
|--------|-------|--------|
| hot_path | [yes/no -- on critical request path?] | PROJECT.md interaction edges |
| has_perf_budget | [yes/no] | COMPONENT.md |
| perf_sensitive_deps | [database, external API, etc.] | COMPONENT.md consumed interfaces |
| recommended_perf_scope | [profile/load-test/query-check/skip] | auto-detected from above |
```

---

## Dependency Scanning Methods

### Package Manifest Scanning

| File | Language/Ecosystem | What to Extract |
|------|-------------------|-----------------|
| `package.json` | Node.js | dependencies, devDependencies, workspaces, scripts.test |
| `pyproject.toml` | Python | project.dependencies, tool.pytest, build-system |
| `requirements.txt` | Python | pinned dependencies with versions |
| `go.mod` | Go | require block, module path |
| `composer.json` | PHP | require, require-dev, autoload |
| `Cargo.toml` | Rust | dependencies, workspace.members |
| `pom.xml` | Java/Maven | dependencies, modules |
| `build.gradle` | Java/Gradle | dependencies block |
| `Gemfile` | Ruby | gem declarations |
| `mix.exs` | Elixir | deps function |

### Import/Require Scanning

Scan target files and their directory for import patterns:

```bash
# Python
grep -rn "^from \|^import " src/ --include="*.py"

# JavaScript/TypeScript
grep -rn "^import \|require(" src/ --include="*.ts" --include="*.js" --include="*.tsx"

# PHP
grep -rn "^use \|require_once\|include " src/ --include="*.php"

# Go
grep -rn "^import" src/ --include="*.go"
```

Map imports to:
- **Internal modules** (relative paths, same package) — intra-component deps
- **Sibling components** (other src/ directories, other packages) — inter-component deps
- **External packages** (node_modules, site-packages, vendor) — external deps

### Consumer Detection

Find who imports FROM the component being modified:

```bash
# Find consumers of src/payment/ across the project
grep -rn "from.*payment\|import.*payment\|require.*payment" src/ --include="*.py" --include="*.ts" --include="*.js" --include="*.php" | grep -v "src/payment/"
```

This gives a list of files outside the component that depend on it.

---

## Integration with Other Skills

### How Skills Use Context Detection

Skills should check context BEFORE deciding their approach:

```
IF context_type == standalone:
  - Test this component only
  - No need to check consumers
  - Skip integration testing
  - Deployment is independent

IF context_type == component:
  - Test this component + integration points
  - Check if public interfaces changed
  - If interface changed → identify affected consumers
  - Deployment may need coordination

IF context_type == library:
  - MUST preserve public API unless explicitly breaking
  - Test all consumers after changes
  - Version bump if interface changes
  - Communicate breaking changes

IF context_type == service:
  - Check API contract (OpenAPI/GraphQL schema if available)
  - Test API endpoints
  - Check for backward compatibility
  - Deployment order matters (dependencies first)

IF hot_path == true:
  - Performance measurement mandatory in TEST phase
  - Load test recommended at expected concurrency

IF hot_path == false AND no perf budget:
  - Performance measurement optional
  - Baseline measurement recommended for new endpoints/queries
```

### Integration Points

| Skill | How It Uses Context |
|-------|-------------------|
| **forge** | Complexity assessment considers dependency depth. More consumers = more complex. |
| **bob** | Work package scope includes consumer testing when context_type != standalone. |
| **agent-teams** | Cross-team contracts informed by actual component interfaces. |
| **team-manager** | QA testing surface determined by context report. |
| **development-lifecycle** | TEST phase scope scales with context_type. |
| **project-documentation** | Context detection feeds into COMPONENT.md consumer/provider tables. |
| **Any domain skill** | Checks context before deciding testing approach. |

### PA Integration (Optional)

If PA is active (MCP tools available):
- Log context detection result via `pa_log_action()`
- Store dependency snapshot for future reference
- Compare with previous snapshot to detect dependency drift

If PA is not active:
- Context detection works identically, just without logging

---

## Dependency Tracking Across Sessions

### When to Re-Run Detection

| Trigger | Action |
|---------|--------|
| New session in same project | Re-run if PROJECT.md changed since last detection |
| New file created | Re-run if file is in a component's owned_paths |
| Package manifest changed | Re-scan dependencies |
| COMPONENT.md updated | Re-read interfaces and consumers |
| After implementation | Verify no new dependencies were introduced silently |

### Staleness Detection

If PROJECT.md or COMPONENT.md has `last_verified_at` in metadata:
- Check if any files in `owned_paths` were modified after `last_verified_at`
- If yes → flag: "Component docs may be stale. Interfaces may have changed."
- Run context detection fresh rather than trusting cached data

---

## Breaking Change Detection (Lightweight)

When context detection finds consumers, do a lightweight breaking-change check:

```
1. Read COMPONENT.md public interfaces table
2. Read actual code exports (functions, classes, API routes)
3. Compare: any interface in docs that doesn't exist in code? → STALE DOC
4. Compare: any code export not in docs? → UNDOCUMENTED INTERFACE
5. If current task CHANGES a public interface:
   → Flag: "This interface has N consumers. Breaking change?"
   → List consumers with file paths
   → Recommend: update consumers, or add backward compatibility
```

This is not a full breaking-change detector — it's a lightweight check that any skill can run in seconds.

---

## Size Constraints

| Item | Max |
|------|-----|
| Dependencies to scan | 50 (skip the rest, note truncation) |
| Consumers to trace | 20 (skip the rest, note truncation) |
| Import scan depth | 3 directory levels from component root |
| Time budget for detection | 10 seconds (skip slow scans, note what was skipped) |

If detection exceeds limits, produce a partial report and note what was skipped. A partial context report is better than no context report.

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Skip context detection for "simple" tasks | Simple tasks in integrated projects can still break consumers |
| Cache context across sessions without re-checking | Dependencies change. Always verify freshness. |
| Block on context detection for standalone projects | If no PROJECT.md and no consumers, classify as standalone and move on quickly |
| Run full import scan on monorepos with 1000+ files | Use time budget. Scan component scope only. |
| Assume context_type from project name or directory | Always detect from evidence (manifests, imports, docs) |
| Write context report to disk by default | Keep in memory unless user requests persistence |
