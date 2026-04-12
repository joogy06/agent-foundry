# Planning Templates Reference

WBS, milestone register, dependency register, and estimation templates for project planning.

---

## WBS Template (3-Level Hierarchy)

Use this as a starter WBS. Adapt the structure to the project's actual deliverables.

```markdown
# [Project Name] -- Work Breakdown Structure

## 1.0 Project Management
  - 1.1 Project Initiation
    - 1.1.1 Project Charter
    - 1.1.2 Stakeholder Analysis
    - 1.1.3 Kickoff Meeting
  - 1.2 Project Planning
    - 1.2.1 WBS Development
    - 1.2.2 Schedule Development
    - 1.2.3 Budget Planning
    - 1.2.4 Risk Assessment
    - 1.2.5 Communication Plan
  - 1.3 Project Execution & Control
    - 1.3.1 Status Reporting
    - 1.3.2 Change Control
    - 1.3.3 Issue Management
    - 1.3.4 Risk Monitoring
  - 1.4 Project Closure
    - 1.4.1 Lessons Learned
    - 1.4.2 Final Report
    - 1.4.3 Handover Documentation

## 2.0 [Deliverable Area 1 -- e.g., Requirements]
  - 2.1 [Sub-Deliverable]
    - 2.1.1 [Work Package]
    - 2.1.2 [Work Package]
  - 2.2 [Sub-Deliverable]
    - 2.2.1 [Work Package]

## 3.0 [Deliverable Area 2 -- e.g., Design]
  - 3.1 [Sub-Deliverable]
    - 3.1.1 [Work Package]
    - 3.1.2 [Work Package]

## 4.0 [Deliverable Area 3 -- e.g., Build/Development]
  - 4.1 [Sub-Deliverable]
    - 4.1.1 [Work Package]

## 5.0 [Deliverable Area 4 -- e.g., Testing]
  - 5.1 [Sub-Deliverable]
    - 5.1.1 [Work Package]

## 6.0 [Deliverable Area 5 -- e.g., Deployment/Release]
  - 6.1 [Sub-Deliverable]
    - 6.1.1 [Work Package]
```

### WBS Validation Checklist

- [ ] 100% of project scope is represented
- [ ] No work package appears in more than one location
- [ ] Each work package is between 8-80 hours of effort
- [ ] All elements are deliverable-oriented (nouns, not verbs)
- [ ] Near-term work is decomposed to work package level
- [ ] Future phases may be at higher levels (rolling wave)
- [ ] WBS dictionary defines scope for each work package

### WBS Dictionary Entry Template

```markdown
**WBS ID:** 2.1.1
**Name:** [Work Package Name]
**Description:** [What this work package produces/delivers]
**Owner:** [Person responsible]
**Estimated Effort:** [hours]
**Estimated Duration:** [days/weeks]
**Dependencies:** [WBS IDs this depends on]
**Acceptance Criteria:** [How we know it's done]
**Assumptions:** [What must be true for this estimate to hold]
```

---

## Milestone Register Template

| ID | Milestone | Target Date | Owner | Criteria | Status | RAG | Actual Date | Notes |
|----|-----------|-------------|-------|----------|--------|-----|-------------|-------|
| M01 | Project Kickoff | [date] | PM | Kickoff meeting held, charter signed | Complete | -- | [date] | |
| M02 | Requirements Approved | [date] | BA Lead | Requirements doc signed off by sponsor | On Track | Green | | |
| M03 | Design Complete | [date] | Architect | Design review passed, all comments resolved | At Risk | Amber | | [note risk] |
| M04 | Development Complete | [date] | Dev Lead | All features implemented, unit tests passing | Not Started | Grey | | |
| M05 | UAT Sign-off | [date] | Test Lead | UAT exit criteria met, no P1/P2 defects open | Not Started | Grey | | |
| M06 | Go-Live | [date] | PM | Production deployment successful, hypercare begins | Not Started | Grey | | |
| M07 | Project Closure | [date] | PM | Lessons learned complete, handover accepted | Not Started | Grey | | |

### Milestone Tracking Rules

- Milestones are binary: complete or not complete (no % progress)
- Each milestone has objective completion criteria
- RAG is based on confidence of hitting the target date:
  - **Green**: on track, no concerns
  - **Amber**: at risk, mitigation in progress
  - **Red**: will miss date without intervention
  - **Grey**: not yet started

---

## Dependency Register Template

| ID | Predecessor | Successor | Type | Lag | Owner | Risk | Status | Notes |
|----|-------------|-----------|------|-----|-------|------|--------|-------|
| D01 | 2.1.1 Requirements Doc | 3.1.1 Design Start | FS | 0 | PM | Med | Active | Design cannot start without approved requirements |
| D02 | External: API Team | 4.1.2 Integration Build | FS | 5d | PM | High | Active | API availability confirmed for [date] |
| D03 | 4.1.1 Backend Dev | 4.1.3 Integration Test | FS | 0 | Dev Lead | Low | Active | Standard dependency |
| D04 | 3.1.2 DB Design | 4.1.1 Backend Dev | SS | 3d | Architect | Low | Active | Can start backend 3 days after DB design starts |

### Dependency Types Reference

| Type | Meaning | Example | Frequency |
|------|---------|---------|-----------|
| FS | Finish-to-Start | Testing starts when development finishes | ~90% of dependencies |
| FF | Finish-to-Finish | Documentation finishes when testing finishes | ~5% |
| SS | Start-to-Start | Training starts when deployment starts | ~4% |
| SF | Start-to-Finish | New system starts before old system finishes | ~1% (rare) |

### External Dependency Tracking

External dependencies require extra attention:

| External Dependency | Provider | Committed Date | Confidence | Fallback Plan |
|---------------------|----------|----------------|------------|---------------|
| API v3 availability | Platform Team | [date] | Medium | Use mock API for dev, delay integration by 2 weeks |
| Security review completion | InfoSec | [date] | High | None -- regulatory requirement |
| Test environment provisioned | Infrastructure | [date] | Low | Use shared environment with time slots |

---

## Estimation Templates

### Three-Point PERT Estimation

```
E (Expected) = (O + 4M + P) / 6
SD (Standard Deviation) = (P - O) / 6
Variance = SD^2

Where:
  O = Optimistic estimate (best case, ~5% probability)
  M = Most Likely estimate (mode, most probable)
  P = Pessimistic estimate (worst case, ~5% probability)
```

| Work Package | Optimistic | Most Likely | Pessimistic | Expected | SD | 95% Range |
|-------------|------------|-------------|-------------|----------|----|----|
| 2.1.1 Requirements Doc | 5d | 8d | 15d | 8.7d | 1.7d | 5.3d - 12.0d |
| 3.1.1 Architecture Design | 3d | 5d | 10d | 5.5d | 1.2d | 3.2d - 7.8d |
| 4.1.1 Backend Development | 15d | 20d | 35d | 21.7d | 3.3d | 15.0d - 28.3d |
| 4.1.2 Frontend Development | 10d | 15d | 25d | 15.8d | 2.5d | 10.8d - 20.8d |

**95% Confidence Range:** Expected +/- 2 * SD

### Estimation Technique Selection

| Situation | Recommended Technique | Accuracy Range |
|-----------|-----------------------|----------------|
| Early project, similar past project exists | Analogous | -25% to +75% |
| Have a reliable cost/duration driver | Parametric | -15% to +25% |
| Have expert judgment but uncertainty | Three-Point (PERT) | -10% to +25% |
| Detailed WBS available, need accuracy | Bottom-Up | -5% to +10% |
| Very early, high uncertainty | T-Shirt (S/M/L/XL) | Order of magnitude only |

### Bottom-Up Estimation Roll-Up

```markdown
## Bottom-Up Estimate: [Deliverable Area]

| WBS | Work Package | Effort (hrs) | Duration (days) | Resources | Cost |
|-----|-------------|-------------|----------------|-----------|------|
| 4.1.1 | Component A build | 40h | 5d | 1 senior dev | $X |
| 4.1.2 | Component B build | 80h | 10d | 1 senior + 1 mid dev | $X |
| 4.1.3 | Integration | 24h | 3d | 1 senior dev | $X |
| 4.1.4 | Unit testing | 16h | 2d | 1 mid dev | $X |
| **Total** | | **160h** | **20d** (with parallelism: 15d) | | **$X** |

### Assumptions
- [Team members are available full-time]
- [Requirements are stable -- no scope changes]
- [Development environment is ready]
- [No external dependency delays]

### Contingency
- Schedule contingency: +20% = 3 additional days
- Cost contingency: +15% = $X additional
```
