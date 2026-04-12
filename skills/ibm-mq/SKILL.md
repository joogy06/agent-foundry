---
name: ibm-mq
description: Use when installing, configuring, or managing IBM MQ on RHEL 9 — queue manager creation and administration, queues (local/remote/alias/model), channels (sender/receiver/server-conn/client-conn), listeners, triggers, clustering, publish/subscribe, MQ security (TLS, channel auth rules, OAM), dead-letter queue handling, MQ Explorer, runmqsc commands, MQ developer patterns (JMS, MQI, Python/pymqi, .NET), performance tuning, systemd services, SELinux contexts, and firewalld rules. Part of the ibm-* skill family.
---

# IBM MQ on Red Hat Enterprise Linux 9

Companion skill to `rhel-server-admin`. For other IBM workloads see: `ibm-websphere`, `db2-rhel`, `db2-mainframe`. For enterprise connectors see: `python-enterprise-connectors`.

<HARD-RULE>
Always define and monitor a dead-letter queue for every queue manager — undeliverable messages without a DLQ are silently discarded.
</HARD-RULE>

<HARD-RULE>
Never use MCAUSER('mqm') on SVRCONN channels — it grants full admin access; use specific service accounts.
</HARD-RULE>

<HARD-RULE>
Always configure CHLAUTH before exposing queue managers to the network — default MQ allows unauthenticated connections.
</HARD-RULE>

<HARD-RULE>
Never change channel names or XMITQ names on active sender/receiver pairs without coordinating both ends — mismatched definitions cause channel failures and message loss.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [channels-clustering-pubsub.md](channels-clustering-pubsub.md) | channels, listeners/triggers, MQ clustering, and publish/subscribe messaging |
| [install-queues.md](install-queues.md) | MQ architecture, RHEL 9 installation, queue manager administration, and queue types (local, remote, alias, model) |
| [security-dev-performance-rhel.md](security-dev-performance-rhel.md) | MQ security, developer patterns (JMS, Spring JMS, MQ classes for Java), performance tuning, monitoring, and RHEL-specific configuration |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Not setting MAXDEPTH and queue-full alerts | Queues fill up silently; producers block or lose messages; cascading failures across applications | Set MAXDEPTH based on peak throughput; configure events (QDPHIEV/QDPLOEV) and monitoring alerts |
| Using SYSTEM.DEFAULT.* queues for application traffic | Default queues lack proper security, monitoring, and tuning; shared with system traffic | Create dedicated application queues with explicit MAXDEPTH, MAXMSGL, and security profiles |
| Running all channels with SVRCONN and no channel authentication | Any client can connect to any queue manager; no audit trail; wide-open security posture | Configure CHLAUTH rules; use TLS on all channels; restrict connections by IP and user |
| Not configuring dead-letter queue (DLQ) handling | Undeliverable messages pile up in DLQ with no processing; eventually fills disk or hits MAXDEPTH | Configure DLQ handler (runmqdlq) with rules for retry, alert, and discard; monitor DLQ depth |
| Persistent messages on high-throughput queues without log tuning | Every persistent message forces a log write; default log sizes cause log-full conditions under load | Size logs (LOGPRIMARY, LOGSECONDARY) for peak message rate; consider non-persistent for idempotent workloads |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core RHEL admin (dnf, SELinux, firewalld, LVM) | `rhel-server-admin` |
| WebSphere Application Server | `ibm-websphere` |
| DB2 on RHEL | `db2-rhel` |
| DB2 on z/OS | `db2-mainframe` |
| Python MQ connectors | `python-enterprise-connectors` |
| Docker / Podman containers | `rhel-docker-host` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| IBM mainframe (JCL, VSAM, TSO) | `ibm-mainframe` |
