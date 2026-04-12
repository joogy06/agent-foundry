# Risk Templates Reference

Risk register, probability/impact matrix, RAID log, risk category taxonomy, and response decision tree.

---

## Risk Register Template

| ID | Risk Description | Category | Probability (1-5) | Impact (1-5) | Score | Response Strategy | Response Actions | Owner | Trigger | Status | Last Reviewed |
|----|-----------------|----------|-------------------|-------------|-------|-------------------|-----------------|-------|---------|--------|---------------|
| R01 | Key developer leaves during critical build phase | Organizational | 2 | 5 | 10 | Mitigate | Cross-train second dev on critical components; document architecture decisions | Dev Lead | Resignation notice | Active | [date] |
| R02 | Third-party API changes break integration | Technical | 3 | 4 | 12 | Mitigate | Pin API version; build adapter layer; monitor API changelog | Architect | API deprecation notice | Active | [date] |
| R03 | Regulatory requirement changes scope | External | 2 | 5 | 10 | Accept | Reserve 10% contingency budget; establish regulatory monitoring | PM | New regulation published | Watch | [date] |
| R04 | Performance requirements not met at scale | Technical | 3 | 4 | 12 | Mitigate | Conduct early performance testing; establish performance baselines | Tech Lead | Load test results | Active | [date] |
| R05 | Vendor delivers late | External | 4 | 3 | 12 | Transfer | Contractual penalty clause; identify alternative vendor | PM | Milestone miss | Active | [date] |

---

## 5x5 Probability/Impact Matrix

```
                          IMPACT
              1-Minimal  2-Minor  3-Moderate  4-Major  5-Severe
         5    |   5    |   10   |    15    |   20   |   25   |  5-Almost Certain
P    4    |   4    |    8   |    12    |   16   |   20   |  4-Likely
R    3    |   3    |    6   |     9    |   12   |   15   |  3-Possible
O    2    |   2    |    4   |     6    |    8   |   10   |  2-Unlikely
B    1    |   1    |    2   |     3    |    4   |    5   |  1-Rare
```

### RAG Scoring Thresholds

| Score Range | RAG | Action |
|-------------|-----|--------|
| 15-25 | Red (Critical) | Immediate escalation. Active mitigation required. Steerco visibility. |
| 8-12 | Amber (Significant) | Active monitoring. Mitigation plan required. PM review weekly. |
| 4-6 | Yellow (Moderate) | Watchlist. Review monthly. Mitigation plan recommended. |
| 1-3 | Green (Low) | Accept. Review quarterly. No active mitigation required. |

### Probability Scale

| Score | Label | Quantitative | Description |
|-------|-------|-------------|-------------|
| 5 | Almost Certain | >80% | Expected to occur in most circumstances |
| 4 | Likely | 60-80% | Will probably occur in most circumstances |
| 3 | Possible | 30-60% | Might occur at some time |
| 2 | Unlikely | 10-30% | Could occur but not expected |
| 1 | Rare | <10% | May occur only in exceptional circumstances |

### Impact Scale

| Score | Label | Schedule Impact | Cost Impact | Quality Impact |
|-------|-------|----------------|-------------|----------------|
| 5 | Severe | >20% delay | >20% overrun | Major deliverable unusable |
| 4 | Major | 10-20% delay | 10-20% overrun | Significant rework required |
| 3 | Moderate | 5-10% delay | 5-10% overrun | Some rework, workaround available |
| 2 | Minor | <5% delay | <5% overrun | Minor quality reduction |
| 1 | Minimal | Negligible | Negligible | Cosmetic only |

---

## RAID Log Template (Unified Tracker)

| ID | Type | Description | Priority | Owner | Status | Due Date | Resolution |
|----|------|-------------|----------|-------|--------|----------|------------|
| R01 | Risk | Key developer departure during build | High | Dev Lead | Active | Ongoing | Cross-training in progress |
| A01 | Assumption | Requirements are stable after sign-off | Medium | BA Lead | Active | [date] | Monitor change requests |
| I01 | Issue | Test environment unavailable for 2 weeks | Critical | Infra Lead | In Progress | [date] | Escalated to IT, using shared env |
| D01 | Dependency | API Team delivers v3 by March 15 | High | PM | Active | Mar 15 | Weekly check-in scheduled |
| R02 | Risk | Budget cut mid-project | Medium | PM | Watch | Ongoing | Contingency plan drafted |
| A02 | Assumption | Team maintains 80% availability | Low | PM | Active | Ongoing | Track in weekly capacity review |
| I02 | Issue | Security scan found 3 critical vulnerabilities | Critical | Security Lead | In Progress | [date] | Patches being applied |
| D02 | Dependency | Legal review of data processing agreement | Medium | Legal | Active | [date] | Draft sent for review |

### RAID Type Definitions

| Type | Definition | When It Changes |
|------|-----------|-----------------|
| **Risk** | Uncertain event that, if it occurs, will affect the project | Becomes an Issue when probability = 100% |
| **Assumption** | Something believed to be true but not yet proven | Becomes a Risk if proven false, or closes if validated |
| **Issue** | A problem that has already occurred and needs resolution | Closes when resolved |
| **Dependency** | Something the project needs from outside the project team | Closes when delivered, becomes an Issue if late |

---

## Risk Category Taxonomy

### Technical Risks
- Architecture decisions that may not scale
- Technology that is new to the team
- Integration complexity between systems
- Performance under load
- Security vulnerabilities
- Data migration complexity
- Technical debt accumulation

### Organizational Risks
- Key person dependencies
- Team skill gaps
- Resource availability and competing priorities
- Organizational restructuring
- Low stakeholder engagement
- Poor communication between teams

### External Risks
- Regulatory or compliance changes
- Vendor/supplier reliability
- Market changes affecting requirements
- Third-party service outages
- Economic conditions affecting budget
- Force majeure events

### Project Management Risks
- Scope creep without change control
- Unrealistic schedule or budget
- Poor requirements definition
- Inadequate testing strategy
- Stakeholder expectation mismatch
- Communication breakdown

---

## Risk Response Decision Tree

```
Is the risk a THREAT or OPPORTUNITY?

THREAT:
  Can you eliminate the cause entirely?
    YES --> AVOID (change scope, approach, or plan to eliminate the risk)
    NO  --> Can you shift the impact to a third party?
      YES --> TRANSFER (insurance, contractual terms, outsourcing)
      NO  --> Can you reduce probability or impact?
        YES --> MITIGATE (take actions to reduce likelihood or consequences)
        NO  --> ACCEPT
          Is the impact tolerable within contingency?
            YES --> Passive Accept (acknowledge, no action, absorb if it occurs)
            NO  --> Active Accept (allocate contingency reserve specifically for this risk)

OPPORTUNITY:
  Can you ensure the opportunity definitely occurs?
    YES --> EXPLOIT (take actions to guarantee it happens)
    NO  --> Can you partner with someone to realize it?
      YES --> SHARE (joint venture, partnership, teaming agreement)
      NO  --> Can you increase probability or impact?
        YES --> ENHANCE (take actions to increase likelihood or positive impact)
        NO  --> ACCEPT (take the benefit if it comes, no proactive action)
```

### Response Quality Checklist

- [ ] Response is proportional to the risk score (do not spend $100K mitigating a $10K risk)
- [ ] Response has a specific owner (not "the team")
- [ ] Response has measurable success criteria
- [ ] Response has a timeline or trigger
- [ ] Residual risk (after response) is acceptable
- [ ] Response does not introduce new risks that are worse than the original
- [ ] Budget for the response is allocated
