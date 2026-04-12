---
name: control-m
description: Use when working with BMC Control-M workload automation — server and agent administration, job definition (OS/Script/File Transfer/Database/Application Integrator/Web Services), scheduling (calendars, time zones, cyclic jobs), flow management (conditions, resources, quantitative/control resources), Automation API (jobs-as-code JSON, ctm CLI), monitoring and alerts (Control-M Web, viewpoints), SLA management, role-based access (admin/developer/operator roles), and RHEL agent deployment. Covers Control-M 9.0.21+ and Helix Control-M (SaaS).
---

# BMC Control-M Workload Automation

Covers Control-M 9.0.21+ (on-premises) and Helix Control-M (SaaS). Organized by role: Admin, Developer, Operator/User.

<HARD-RULE>
Always use conditions (In/Out) for job dependencies, never rely on scheduling time alone — time-based sequencing breaks when upstream jobs run late.
</HARD-RULE>

<HARD-RULE>
Never modify active (ordered) jobs in production without hold/free — in-flight changes cause unpredictable behavior.
</HARD-RULE>

<HARD-RULE>
Always use the Automation API (jobs-as-code) for version-controlled job definitions — manual GUI changes create configuration drift that is impossible to audit.
</HARD-RULE>

<HARD-RULE>
Never grant admin/full role to developer accounts — Control-M role separation exists to prevent accidental production job modifications.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [admin-role.md](admin-role.md) | server/agent administration, configuration, security, integrations, and infrastructure management |
| [developer-role.md](developer-role.md) | job definition (OS/Script/File Transfer/Database/Application Integrator), scheduling, flow management, SLA management, and Automation API |
| [operator-reference.md](operator-reference.md) | operator/user tasks (monitoring, active jobs, troubleshooting, batch operations) and quick reference |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Hardcoding paths and server names in job definitions | Jobs break when migrated between environments (dev/test/prod); maintenance requires editing every job | Use Control-M variables, AutoEdit substitution, and connection profiles for environment-specific values |
| Creating linear chains of 50+ jobs without sub-folders | Impossible to monitor, debug, or restart mid-chain; a single failure blocks the entire sequence | Break into logical sub-folders with condition-based dependencies; use Smart Folders for grouping |
| Setting no timeout or unrealistically long timeouts on jobs | Hung jobs hold resources indefinitely; downstream jobs wait forever; batch windows get missed | Set realistic timeouts based on historical runtime + buffer; configure alerts for jobs exceeding threshold |
| Running all batch jobs under a single service account | No auditability; a credential change breaks everything; violates least-privilege principle | Use dedicated service accounts per application or job group; rotate credentials on schedule |
| Skipping calendar validation when scheduling across time zones | Jobs fire at wrong times; DST transitions cause double-runs or missed runs | Use Control-M calendar objects with explicit timezone settings; test scheduling across DST boundaries |

---

## Related Skills

| Domain | Skill |
|---|---|
| RHEL system administration | `rhel-server-admin` |
| Database administration on RHEL | `rhel-databases` |
| Docker/Podman on RHEL | `rhel-docker-host` |
| Monitoring (Prometheus/Grafana) | `rhel-monitoring` |
| CI/CD pipelines | `docker-cicd` |
