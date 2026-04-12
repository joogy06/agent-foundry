# Quality Templates Reference

Definition of Done, acceptance criteria, quality gates, tech debt register, and defect severity classification.

---

## Definition of Done (DoD) Checklist Templates

### Story-Level DoD (Individual Work Item)

```markdown
## Definition of Done -- Story Level

- [ ] Code is written and follows team coding standards
- [ ] Code is peer reviewed (at least one approving review)
- [ ] Unit tests written and passing (coverage meets team threshold)
- [ ] Integration tests passing (where applicable)
- [ ] No new static analysis warnings (linting clean)
- [ ] Acceptance criteria verified by developer
- [ ] Documentation updated (if user-facing changes)
- [ ] Deployed to development/staging environment
- [ ] No regression in existing functionality
```

### Sprint-Level DoD (Collection of Work)

```markdown
## Definition of Done -- Sprint Level

All story-level DoD criteria met for every completed story, PLUS:
- [ ] All sprint backlog items meet story-level DoD
- [ ] Integration between sprint items verified
- [ ] Sprint-level regression suite passing
- [ ] Performance benchmarks maintained (no degradation beyond threshold)
- [ ] Sprint demo prepared and reviewed
- [ ] Sprint metrics calculated and recorded
- [ ] Technical debt items identified and logged
```

### Release-Level DoD (Production-Ready)

```markdown
## Definition of Done -- Release Level

All sprint-level DoD criteria met, PLUS:
- [ ] Full regression suite passing
- [ ] Performance/load testing complete and within SLA
- [ ] Security scan complete -- no critical or high vulnerabilities
- [ ] User acceptance testing (UAT) sign-off received
- [ ] Release notes prepared
- [ ] Runbook/operational documentation updated
- [ ] Rollback plan documented and tested
- [ ] Monitoring and alerting configured for new features
- [ ] Data migration scripts tested (if applicable)
- [ ] Go/no-go decision recorded
```

### DoD Evolution Guidance

| Team Maturity | Recommended DoD Items |
|--------------|----------------------|
| New team (0-3 months) | Code review, unit tests, manual testing, deployed to staging |
| Established (3-12 months) | Add: integration tests, static analysis, acceptance criteria, documentation |
| Mature (12+ months) | Add: performance tests, security scan, automated deployment, monitoring |

**Rule:** Only add DoD items the team can reliably achieve. An aspirational DoD that gets ignored is worse than a simple DoD that's always met.

---

## Acceptance Criteria Template (Given/When/Then)

```markdown
## Story: [Story Title]

### Acceptance Criteria

**Criteria 1: [Descriptive Name]**
- Given [precondition or context]
- When [action or trigger]
- Then [expected outcome]
- And [additional expected outcome]

**Criteria 2: [Descriptive Name]**
- Given [precondition]
- When [action]
- Then [outcome]

### Edge Cases
- Given [unusual input or condition]
- When [action]
- Then [expected handling -- error message, fallback, etc.]

### Non-Functional Criteria
- Response time: < [X]ms for [operation]
- Error handling: [specific error scenarios and expected responses]
- Accessibility: [specific WCAG criteria if applicable]
```

### Acceptance Criteria Quality Checklist

- [ ] Each criterion is independently testable
- [ ] Criteria cover the happy path AND edge cases
- [ ] Criteria are written from the user's perspective
- [ ] No implementation details in criteria (what, not how)
- [ ] Non-functional requirements specified where relevant
- [ ] Criteria are unambiguous (two people reading them would agree on pass/fail)

---

## Quality Gate Checklist Per Environment

### Development Environment Gate

| Check | Tool/Method | Pass Criteria |
|-------|------------|---------------|
| Code compiles | Build system | Zero errors |
| Unit tests | Test framework | 100% pass, coverage >= [X]% |
| Static analysis | Linter, SonarQube | No new critical/major issues |
| Code review | PR review | At least 1 approval, no blocking comments |
| Feature flag | Feature management | New features behind flags |

### Testing/QA Environment Gate

| Check | Tool/Method | Pass Criteria |
|-------|------------|---------------|
| Integration tests | Test framework | 100% pass |
| API contract tests | Contract testing tool | No breaking changes |
| Regression suite | Automated test suite | 100% pass |
| Exploratory testing | QA team | No P1/P2 defects found |
| Test data clean | Data management | Test data doesn't leak to prod |

### Staging/Pre-Production Gate

| Check | Tool/Method | Pass Criteria |
|-------|------------|---------------|
| Performance test | Load testing tool | Response times within SLA |
| Security scan | SAST/DAST tool | No critical/high vulnerabilities |
| UAT sign-off | Business stakeholders | Formal acceptance |
| Data migration | Migration scripts | Data integrity verified |
| Rollback test | Deployment pipeline | Rollback successfully tested |

### Production Gate

| Check | Tool/Method | Pass Criteria |
|-------|------------|---------------|
| Smoke tests | Automated | Core functionality verified |
| Monitoring | APM, logs | No error spikes |
| Alerting | Alert system | Alerts configured and verified |
| Runbook | Documentation | Updated and accessible |
| Go/No-Go | Release authority | Explicit decision recorded |

---

## Tech Debt Register Template

| ID | Description | Quadrant | Impact | Effort | Priority | Status | Owner | Sprint |
|----|-------------|----------|--------|--------|----------|--------|-------|--------|
| TD01 | Hardcoded config values need extraction to env vars | Prudent-Deliberate | Medium (deployment friction) | Small (2h) | High | Open | [name] | Sprint 5 |
| TD02 | No retry logic on external API calls | Reckless-Inadvertent | High (production failures) | Medium (1d) | Critical | In Progress | [name] | Sprint 4 |
| TD03 | Test suite takes 45 min -- needs parallelization | Prudent-Deliberate | High (slow feedback) | Large (3d) | Medium | Open | [name] | Backlog |
| TD04 | Legacy auth module uses deprecated crypto library | Reckless-Deliberate | Critical (security) | Large (5d) | Critical | Planned | [name] | Sprint 5 |
| TD05 | Duplicated validation logic across 3 services | Prudent-Inadvertent | Medium (maintenance) | Medium (2d) | Low | Open | [name] | Backlog |

### Tech Debt Quadrant Model

```
                DELIBERATE                    INADVERTENT
         (We chose to do this)          (We didn't know better)

RECKLESS  "We don't have time       "What's a dependency
          for design"                injection?"
          [Fix urgently]            [Fix + educate]

PRUDENT   "We'll ship now and       "Now we know how we
          refactor later"            should have done it"
          [Schedule paydown]        [Fix when touched]
```

### Tech Debt Budget
- Reserve 15-20% of sprint capacity for tech debt reduction
- Prioritize by: security risk > reliability impact > developer friction > maintainability
- Track tech debt item completion in sprint reviews

---

## Defect Severity Classification

| Severity | Definition | Response Time | Examples |
|----------|-----------|---------------|---------|
| **Critical (P1)** | System down, data loss, security breach, no workaround | Immediate (within 1 hour) | Production outage, data corruption, authentication bypass |
| **Major (P2)** | Key feature broken, significant impact, workaround exists but painful | Same day | Cannot complete core workflow, incorrect calculations, performance degraded >50% |
| **Minor (P3)** | Feature partially broken, easy workaround available | Within sprint | UI glitch with workaround, minor data display error, edge case failure |
| **Cosmetic (P4)** | Visual or text issue, no functional impact | Backlog | Typo, alignment issue, inconsistent formatting |

### Escaped Defect Analysis

When a defect reaches production, ask:
1. **Where should this have been caught?** (unit test, integration test, QA, UAT)
2. **Why wasn't it caught?** (no test, test gap, test environment mismatch)
3. **What can we add to prevent similar escapes?** (test case, monitoring, quality gate)

Track escaped defects as a quality metric. Trend should be decreasing. If increasing, the quality process has gaps.
