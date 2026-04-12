# SLA/SLO Reference

SLI/SLO/SLA hierarchy, error budgets, availability nines, incident impact assessment, and operational readiness.

---

## SLI/SLO/SLA Hierarchy

| Level | Name | Definition | Who Defines It | Example |
|-------|------|-----------|----------------|---------|
| **SLI** | Service Level Indicator | The metric you measure | Engineering team | p99 API response time, error rate, throughput |
| **SLO** | Service Level Objective | The target for the SLI | Engineering + Product | p99 response time < 200ms, error rate < 0.1% |
| **SLA** | Service Level Agreement | Contractual commitment with consequences | Business + Legal | 99.9% availability or customer gets service credits |

**Relationship:** SLIs inform SLOs. SLOs underpin SLAs. Set SLOs tighter than SLAs to create a buffer.

### SLI/SLO/SLA Definition Template

```markdown
## Service: [Service Name]

### SLI 1: Availability
- **Measurement:** Successful requests / Total requests
- **Data source:** Load balancer access logs
- **Measurement window:** Rolling 30 days
- **SLO Target:** 99.9%
- **SLA Commitment:** 99.5%

### SLI 2: Latency
- **Measurement:** Server-side response time at p99
- **Data source:** APM tool (e.g., Datadog, New Relic)
- **Measurement window:** Rolling 30 days
- **SLO Target:** p99 < 200ms
- **SLA Commitment:** p99 < 500ms

### SLI 3: Error Rate
- **Measurement:** 5xx responses / Total responses
- **Data source:** Application metrics
- **Measurement window:** Rolling 7 days
- **SLO Target:** < 0.1%
- **SLA Commitment:** < 0.5%
```

---

## Availability Nines Table

| Availability | Annual Downtime | Monthly Downtime | Weekly Downtime | Daily Downtime |
|-------------|----------------|-----------------|----------------|----------------|
| 99% (two nines) | 3.65 days | 7.31 hours | 1.68 hours | 14.40 minutes |
| 99.5% | 1.83 days | 3.65 hours | 50.40 minutes | 7.20 minutes |
| 99.9% (three nines) | 8.77 hours | 43.83 minutes | 10.08 minutes | 1.44 minutes |
| 99.95% | 4.38 hours | 21.92 minutes | 5.04 minutes | 43.20 seconds |
| 99.99% (four nines) | 52.60 minutes | 4.38 minutes | 1.01 minutes | 8.64 seconds |
| 99.999% (five nines) | 5.26 minutes | 26.30 seconds | 6.05 seconds | 0.86 seconds |

### Choosing the Right Level

| Level | Typical For | Cost Implication |
|-------|------------|------------------|
| 99% | Internal tools, batch systems | Low -- manual recovery acceptable |
| 99.9% | Business applications, web services | Medium -- automated failover needed |
| 99.99% | Financial systems, payment processing | High -- redundancy, active-active, no single points of failure |
| 99.999% | Life-critical, telecom core | Very high -- specialized engineering, extreme redundancy |

**Rule of thumb:** Each additional nine costs roughly 10x more to achieve. Don't over-engineer.

---

## Error Budget

### Concept

```
Error Budget = 1 - SLO Target

Example:
  SLO = 99.9% availability
  Error Budget = 0.1% = 43.83 minutes of downtime per month

This 43.83 minutes is the team's "budget" for failures.
```

### Error Budget Calculation

```
Budget (minutes/month) = 30 days x 24 hours x 60 minutes x (1 - SLO)

99.9% SLO = 43,200 minutes x 0.001 = 43.2 minutes/month
99.95% SLO = 43,200 minutes x 0.0005 = 21.6 minutes/month
99.99% SLO = 43,200 minutes x 0.0001 = 4.32 minutes/month
```

### Error Budget Policy Template

```markdown
## Error Budget Policy -- [Service Name]

### Budget Remaining Thresholds

| Budget Remaining | Actions |
|-----------------|---------|
| > 50% | Normal operations. Feature releases proceed normally. |
| 25-50% | Caution. Prioritize reliability work. Review recent incidents. |
| 10-25% | Warning. Freeze non-critical feature releases. Focus on reliability. |
| 0-10% | Critical. Freeze ALL feature releases. All engineering on reliability. |
| Exhausted (0%) | Freeze everything. Post-mortem required. Recovery plan before any release. |

### Monthly Review
- Review error budget consumption at sprint planning
- Top incidents contributing to budget burn
- Reliability improvements planned vs completed
- Decision: can we release features this sprint?

### Reset
- Error budget resets on the [1st/rolling window] of each month
- Carry-over: if budget was exhausted, carry a 10% penalty into next period
```

---

## Incident Impact Assessment Template

```markdown
## Incident Impact on Delivery

### Incident Summary
- **Incident ID:** [INC-NNN]
- **Duration:** [X hours]
- **Severity:** [P1/P2/P3]
- **Services Affected:** [list]

### Capacity Impact
- **Engineers pulled into incident response:** [N] people
- **Hours spent on response:** [X] hours
- **Hours spent on post-mortem + remediation:** [X] hours
- **Total capacity lost:** [X] person-hours = [X] story points equivalent

### Sprint Impact
- **Current sprint velocity (planned):** [X] points
- **Capacity reduction due to incident:** [X] points ([X]%)
- **Adjusted sprint scope recommendation:** [X] points
- **Items to de-scope:** [list specific items to defer]

### SLO Impact
- **Error budget consumed by this incident:** [X] minutes ([X]% of monthly budget)
- **Remaining error budget:** [X] minutes
- **Feature release recommendation:** [proceed / pause / freeze]

### Follow-Up Actions
| Action | Owner | Deadline | Sprint |
|--------|-------|----------|--------|
| [Remediation action] | [name] | [date] | [sprint] |
| [Monitoring improvement] | [name] | [date] | [sprint] |
| [Process change] | [name] | [date] | [sprint] |
```

---

## Operational Readiness Checklist

Before declaring a service production-ready, verify:

### Monitoring and Observability

- [ ] Key SLIs are measured and dashboarded
- [ ] Alerts configured for SLO breach (early warning at 90% of threshold)
- [ ] Logs are structured, searchable, and retained for [N] days
- [ ] Distributed tracing is enabled for cross-service calls
- [ ] Dashboard includes: request rate, error rate, latency (p50, p95, p99), saturation

### Incident Response

- [ ] On-call rotation defined and staffed
- [ ] Escalation path documented (L1 --> L2 --> L3)
- [ ] Runbook exists for top 5 known failure modes
- [ ] Incident communication template prepared (status page, stakeholder updates)
- [ ] Post-mortem process defined and practiced

### Reliability

- [ ] No single points of failure in the architecture
- [ ] Failover tested (database, load balancer, region)
- [ ] Graceful degradation implemented (circuit breakers, fallbacks)
- [ ] Chaos testing performed or planned
- [ ] Capacity planning reviewed (can handle 2x current peak load)

### Deployment

- [ ] Automated deployment pipeline (CI/CD)
- [ ] Rollback mechanism tested and documented
- [ ] Canary or blue/green deployment strategy in place
- [ ] Feature flags available for new functionality
- [ ] Deployment runbook documented

### Data and Security

- [ ] Data backup and recovery tested
- [ ] Recovery Time Objective (RTO) and Recovery Point Objective (RPO) defined
- [ ] Security scan clean (SAST, DAST, dependency scan)
- [ ] Access controls and authentication verified
- [ ] Data encryption at rest and in transit confirmed

### Documentation

- [ ] Architecture diagram up to date
- [ ] API documentation published
- [ ] Dependency map documented (upstream and downstream)
- [ ] SLI/SLO definitions published
- [ ] Contact information for service owners accessible
