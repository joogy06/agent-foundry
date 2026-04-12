---
name: development-lifecycle
description: Use at the start of any development task — feature, bugfix, refactor, or infrastructure change. Defines mandatory SDLC phases that must be completed with evidence before work is considered done. Enforces testing, security review, and documentation gates.
---

# Development Lifecycle

## Overview

Every development task follows mandatory phases. No phase can be skipped. No work is "done" until all gates pass with evidence. This is a rigid process skill — follow it exactly.

<HARD-GATE>
Work is NOT complete until ALL applicable gates have passed with evidence.
Saying "I tested it" is not evidence. A passing test output is evidence.
Saying "it's secure" is not evidence. A security checklist with checks is evidence.
Skipping a gate "because the change is small" is a violation.
</HARD-GATE>

## The Lifecycle

```
PLAN → IMPLEMENT → TEST → SECURE → DOCUMENT → REVIEW → DONE
```

Every task passes through these phases. Small tasks may combine phases but **never skip them**.

## Phase 1: PLAN

**Gate: Plan exists before code is written.**

| Task Size | Planning Requirement |
|-----------|---------------------|
| Trivial (config change, typo fix) | Mental plan stated in response |
| Small (single file, clear approach) | Brief description of approach |
| Medium (multiple files, design choice) | Written plan (forge design doc or inline) |
| Large (architecture, multi-day) | Full design doc via forge, user-approved |

**Evidence:** The plan (or statement of approach) must exist in the conversation before any implementation begins.

## Phase 2: IMPLEMENT

**Gate: Code follows project conventions and skill guidance.**

Before writing code:
1. Check for applicable skills (forge step 4 — skill gap detection)
2. Invoke domain skills for the work type
3. Follow security patterns from relevant skills (never optional)

During implementation:
- One concern per commit
- Backup files before editing (per project rules)
- Respect session_control.md file locks
- Follow the coding patterns in loaded skills

### Pre-Test Discovery

Before running tests, identify the project's test infrastructure:

1. Check PROJECT.md ## Testing section -> use documented commands
2. If not documented, scan:
   - package.json scripts (test, test:unit, test:e2e, lint)
   - pyproject.toml [tool.pytest], [tool.ruff], [tool.mypy]
   - Makefile/Taskfile targets (test, lint, check)
   - CI config (.github/workflows/, .gitlab-ci.yml, Jenkinsfile)
   - Test directories (tests/, test/, __tests__/, spec/)
3. Record the commands you'll use before running them
4. If no test infrastructure found: note in evidence, suggest creating tests

## Phase 3: TEST

**Gate: Tests pass and output is shown.**

<HARD-GATE>
"I tested it mentally" is NOT testing.
"It should work" is NOT evidence.
You must RUN something and SHOW the output.
</HARD-GATE>

### Contract-Driven Sub-Phases (when a contract map exists)

For any WP whose component is tracked in `progress/contract-map.yaml`, Phase 3 is split into four sub-phases that correspond to the integration ledger's stages. Each sub-phase has its own gate and ledger transition. See `ledger-mapping.yaml` in this skill directory for the machine-readable SDLC-to-ledger contract.

| Sub-phase | Gate | Evidence | Ledger transition |
|---|---|---|---|
| **3a: SCAFFOLD** | `sample-data-scaffolding` produced fixtures | `tests/fixtures/<component>/manifest.yaml` exists, hashes match, `produced_by: skill:sample-data-scaffolding` | PLANNED → SCAFFOLDED |
| **3b: UNIT** | Unit tests pass via `trusted_runner.run_trusted_test_suite` | Audit bundle at `.ledger/evidence/<component>/unit-test-bundle.json`, `produced_by: bob-trusted-runner` | SCAFFOLDED → UNIT_TESTED |
| **3c: INTEGRATION** | `integration-flow-testing` generated per-point tests AND they pass via bob's trusted runner | Integration-test audit bundle, `produced_by: bob-trusted-runner` | UNIT_TESTED → INTEGRATED |
| **3d: FLOW** | Declared flow tests pass AND metacognitive audit approves (cold Claude + Codex via `audit_spawn.py`, ≥3 structured disagreements) | Flow-test audit bundle + audit JSON record (both verdicts) | INTEGRATED → VERIFIED |

**Backwards compatibility:** WPs without a contract map continue to run the traditional Phase 3 (single TEST gate). The sub-phases apply ONLY when `progress/contract-map.yaml` exists for the WP's component.

**Authoritative precedence:** when the SDLC phase and the integration ledger disagree, **the ledger wins**. Consult `~/.claude/skills/development-lifecycle/ledger-mapping.yaml` to translate between SDLC and ledger states.

| Change Type | Minimum Testing |
|-------------|----------------|
| PHP/theme template | Load the page, verify no errors (browser or curl) |
| CSS changes | Visual verification (screenshot or browser check) |
| Python code | Run the test suite, show output |
| API changes | Call the endpoint, show response |
| Database changes | Run migration, verify schema |
| Config changes | Restart service, verify it starts |
| Any change | Verify the specific behavior that was changed works |

### Testing Checklist

- [ ] **Happy path** — Does the intended behavior work?
- [ ] **Error path** — What happens with bad input?
- [ ] **Regression** — Did existing functionality break? (run existing tests)
- [ ] **Edge cases** — Empty data, large data, special characters, null values
- [ ] **Cross-device** — If UI: tested on mobile viewport?

**Evidence required:** Test command + output pasted or referenced. Not "tests pass" — show it.

### Performance Dimension (conditional)

Applies when the change touches: API endpoints, database queries, UI rendering, batch processes, or hot-path code identified by context-detection.

Does NOT apply to: config-only changes, documentation, CSS/copy, test-only changes.

| Change Type | Performance Check |
|-------------|------------------|
| New/modified API endpoint | Response time at expected concurrency (hey, k6, wrk) |
| Database query change | EXPLAIN ANALYZE output, execution time |
| Frontend page/component | LCP measurement (Lighthouse or CWV) |
| Batch process/worker | Throughput (items/sec) + peak memory |
| Hot-path code (per context-detection) | Profile before and after |

Evidence: tool command + numeric output shown. "It loads fast" is not evidence.
If component has performance budget: compare against budget.
If no budget: record measurement as initial baseline.

## Phase 4: SECURE

**Gate: Security checklist completed for the change type.**

### Universal Security Checks (All Changes)

- [ ] No secrets hardcoded (API keys, passwords, tokens)
- [ ] No sensitive data in logs
- [ ] Dependencies checked for known vulnerabilities

### Web/PHP Security (WordPress/WooCommerce)

- [ ] All user input sanitized (`sanitize_text_field`, `absint`, etc.)
- [ ] All output escaped (`esc_html`, `esc_attr`, `esc_url`)
- [ ] All DB queries use `$wpdb->prepare()`
- [ ] All forms verify nonces
- [ ] All privileged actions check `current_user_can()`
- [ ] No `eval()`, `extract()`, or `unserialize()` on user data

### Python Security

- [ ] All user input validated (Pydantic/Marshmallow at boundary)
- [ ] All DB queries parameterized (ORM or prepared statements)
- [ ] No `eval()`, `pickle.loads()`, `yaml.load()`, `os.system()` with user data
- [ ] Authentication/authorization on all endpoints
- [ ] CORS configured restrictively

### API Security

- [ ] Authentication required on all non-public endpoints
- [ ] Rate limiting on auth endpoints
- [ ] Input validation on all parameters
- [ ] Error messages don't leak internal details

### Payment/Financial

- [ ] No raw card data stored
- [ ] PCI DSS compliance maintained
- [ ] TLS enforced for all payment flows

**Evidence required:** Completed checklist with each item checked or marked N/A with reason.

**Not applicable?** If a section doesn't apply (e.g., no Python in a CSS change), mark it N/A — but the Universal checks ALWAYS apply.

## Phase 5: DOCUMENT

**Gate: Changes are documented proportional to their impact.**

**Contract-mapped components:** the DOCUMENT phase now requires the component to be at stage VERIFIED in `progress/integration-ledger.md`. Advancing to DOCUMENTED increments the ledger status VERIFIED → DOCUMENTED. DOCUMENTED is a prerequisite for DONE. History.md and index.md entries may be written ONLY at the DOCUMENTED transition — writing them earlier desynchronizes human-readable docs from the ledger state.

| Change Impact | Documentation Required |
|---------------|----------------------|
| Trivial (typo, config) | Commit message sufficient |
| Small (single feature/fix) | Commit message + brief inline comments if logic isn't obvious |
| Medium (new feature, API change) | Update relevant docs (README, API docs, project instructions file if conventions changed) |
| Large (architecture, new system) | Design doc + updated docs + migration guide if applicable |

### What to Document

- **Why** the change was made (not just what changed — git diff shows what)
- **How to use** new features or APIs
- **Breaking changes** and migration steps
- **Configuration** changes needed
- **Dependencies** added and why

### Project Documentation Updates (per `project-documentation` skill)

- Update `history.md` with what was done (date, action, files, reason)
- Update `index.md` if new files were created
- Update subfolder `INDEX.md` if files added to documented folders
- If these files don't exist, create them from templates in the `project-documentation` skill

**Evidence required:** Documentation exists and is referenced. For trivial changes, the commit message IS the documentation.

## Phase 6: REVIEW

**Gate: Another agent or the user has reviewed the work.**

| Context | Review Method |
|---------|--------------|
| Forge team task | Challenger/QA agent reviews (built into forge) |
| Solo task (no team) | Present summary to user with: what changed, test results, security checklist |
| Production deployment | User approval required before deploy |

### Review Checklist

- [ ] Code matches the plan/design
- [ ] Tests pass (evidence shown)
- [ ] Security checklist completed
- [ ] Documentation updated
- [ ] No unintended changes (check `git diff`)
- [ ] No temporary/debug code left in

**Evidence required:** Review completed — either by challenger agent or user acknowledgment.

## Phase 7: DONE

Work is DONE when:
1. All applicable gates have evidence
2. Review is complete
3. Changes are committed (if requested)
4. User is informed of what was done

**"Done" means provably done, not probably done.**

## Quick Reference — Minimum Evidence Per Phase

| Phase | Evidence |
|-------|---------|
| PLAN | Approach stated before coding |
| IMPLEMENT | Code written following skills and conventions |
| TEST | Test command + output shown |
| SECURE | Security checklist completed (checked or N/A) |
| DOCUMENT | Docs updated or commit message covers it |
| REVIEW | Challenger reviewed or user informed |

## Integration with Forge

When forge is running a team, this lifecycle applies to **every specialist task**:

1. Manager assigns task → specialist plans approach
2. Specialist implements → follows domain skills
3. Specialist tests → shows output
4. Specialist runs security checklist → completes applicable items
5. Specialist documents → updates relevant docs
6. Challenger reviews → checks all gates
7. Only THEN is the task marked complete

Forge's existing quality gates map directly:
- Code Review = Phase 6 (REVIEW)
- UX Review = Phase 3 (TEST — visual verification)
- Regression Testing = Phase 3 (TEST — regression)
- Design Compliance = Phase 6 (REVIEW — matches plan)

## Red Flags — STOP

These thoughts mean you're about to skip a gate:

| Thought | Reality |
|---------|---------|
| "This change is too small to test" | Small changes break things. Test it. |
| "Security doesn't apply to CSS" | Universal checks always apply (no secrets, no sensitive data) |
| "I'll document it later" | Later never comes. Document now. |
| "The tests would be trivial" | Then they'll take 30 seconds. Write them. |
| "I already know it works" | Prove it. Show the output. |
| "It's just a refactor, nothing changed" | Then tests should pass. Run them and show it. |
| "The user didn't ask for tests" | Tests aren't optional. The lifecycle requires them. |
| "Skipping review to save time" | Reviews catch bugs. Skipping costs more time. |

**All of these mean: STOP. Complete the gate.**

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Say "tests pass" without showing output | No evidence = no verification |
| Skip security checklist on "simple" changes | Simple changes introduce vulnerabilities too |
| Leave TODO comments as "documentation" | TODOs are debt, not documentation |
| Mark work done before review | Review is the final gate, not optional |
| Batch all testing to the end | Test each piece as you build — catches issues early |
| Skip planning for "obvious" tasks | Obvious tasks have hidden complexity. State the plan. |
| Combine security + testing into "it works" | Separate concerns — working ≠ secure |
