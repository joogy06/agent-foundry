---
name: rhel-monitoring
description: Use when setting up monitoring and logging on RHEL 9 (and AlmaLinux/Rocky 9) — Prometheus and node_exporter, Grafana dashboards, Loki/Promtail log aggregation, ELK stack, Alertmanager, Performance Co-Pilot (PCP), rsyslog, systemd journal management, Cockpit monitoring, and health check patterns. Part of the rhel-* skill family.
family: rhel
applies_when: os_family == rhel
---

# Red Hat Enterprise Linux 9 — Monitoring and Logging

Companion skill to `rhel-server-admin`. Covers metrics collection, visualization, log aggregation, alerting, and health checks on RHEL 9.x (and compatible: AlmaLinux 9, Rocky Linux 9, Oracle Linux 9).

<HARD-RULE>
Always verify the RHEL version before applying advice. Packages, paths, and available repos differ between major releases.
```bash
cat /etc/redhat-release
cat /etc/os-release
uname -r
```
</HARD-RULE>

<HARD-RULE>
Monitoring stacks can consume significant resources. Always size memory and disk before deploying. A Prometheus + Grafana + Loki stack needs at minimum 2 GB RAM and 20 GB disk for small environments. Elasticsearch alone requires at least 4 GB RAM (see JVM heap section).
</HARD-RULE>

<HARD-RULE>
On RHEL 9, SELinux is enforcing by default. When installing monitoring services that bind to non-standard ports or read log files, you must set proper SELinux contexts and booleans rather than disabling SELinux. Use `ausearch -m AVC --start recent` and `sealert` to diagnose denials.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [loki-pcp-elk-rsyslog-healthchecks.md](loki-pcp-elk-rsyslog-healthchecks.md) | Loki + Promtail, Performance Co-Pilot (PCP), ELK Stack, rsyslog, Cockpit monitoring, health check patterns, and SELinux contexts |
| [prometheus-grafana-alertmanager.md](prometheus-grafana-alertmanager.md) | Prometheus installation and configuration, node_exporter, Grafana dashboards, and Alertmanager setup |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Alerting on every metric threshold without tuning | Alert fatigue — operators ignore alerts when 90% are noise; real incidents get buried | Start with critical alerts only (disk 90%, memory 95%, service down); tune thresholds based on baseline; review alert volume weekly |
| No log rotation or retention policy | /var/log fills the root filesystem; system stops functioning; log data from 3 years ago wastes storage | Configure logrotate for all application logs; set journal retention (SystemMaxUse); archive to central logging |
| Monitoring only system metrics, not application health | CPU and memory look fine while the application returns 500 errors; users report outage before monitoring detects it | Add application-level health endpoints; monitor HTTP status codes, response latency, and error rates alongside system metrics |
| Installing Prometheus without persistent storage | Prometheus restart loses all historical data; capacity planning and trend analysis become impossible | Configure Prometheus with persistent volume (--storage.tsdb.path); set retention period (--storage.tsdb.retention.time) |
| Not correlating logs with metrics during incidents | Metrics show a spike but no context; logs show errors but no timing; incident diagnosis takes hours instead of minutes | Use shared labels/tags across metrics (Prometheus) and logs (Loki/ELK); link dashboards to log queries for drill-down |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (packages, users, firewall, disk) | `rhel-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Docker / Podman containers | `rhel-docker-host` |
| File sharing (NFS, Samba, Stratis) | `rhel-file-storage` |
| DNS, DHCP, NTP | `rhel-network-infra` |
| NVIDIA GPU, Ollama, CUDA | `rhel-ollama-nvidia` |
