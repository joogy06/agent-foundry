---
name: ibm-websphere
description: Use when installing, configuring, or managing IBM WebSphere Application Server on RHEL 9 — WAS traditional (8.5.5/9.0) profiles and deployment, WebSphere Liberty/Open Liberty configuration and development, application deployment (WAR/EAR), security (SSL/TLS, LTPA, LDAP/AD integration, SAML/OIDC), JVM tuning (heap, GC policies), clustering and ND topology, JDBC data sources, JMS/MQ integration, wsadmin scripting (Jython), systemd services, SELinux contexts, and firewalld rules. Part of the ibm-* skill family.
---

# IBM WebSphere Application Server — RHEL 9 Administration & Development

Companion skill to `rhel-server-admin` and `db2-rhel`. For related workloads see: `rhel-web-servers`, `rhel-docker-host`, `rhel-monitoring`.

<HARD-RULE>
Never deploy applications to a running production cluster without testing on a non-production server first — class loader conflicts and missing dependencies only manifest at runtime.
</HARD-RULE>

<HARD-RULE>
Always regenerate and propagate the web server plugin (plugin-cfg.xml) after topology changes — stale plugin config causes request routing failures.
</HARD-RULE>

<HARD-RULE>
Never store passwords in plain text in wsadmin scripts — use encrypted password files or J2C auth aliases.
</HARD-RULE>

<HARD-RULE>
Always configure connection pool purge policy and aging timeout — stale connections cause intermittent failures that are extremely hard to diagnose.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [install-profiles-deploy.md](install-profiles-deploy.md) | WAS architecture, RHEL 9 installation, profile management, and application deployment (WAR/EAR) |
| [security-jvm-clustering-jdbc.md](security-jvm-clustering-jdbc.md) | security configuration, JVM tuning, clustering/HA, JDBC data sources, and JMS/MQ integration |
| [wsadmin-liberty-rhel.md](wsadmin-liberty-rhel.md) | wsadmin scripting (Jython), WebSphere Liberty/Open Liberty configuration, and RHEL-specific setup |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running WAS traditional when Liberty would suffice | WAS traditional has massive memory footprint, slow startup, complex administration for simple apps | Use Liberty/Open Liberty for new applications; reserve WAS traditional for legacy apps that require it |
| Deploying application changes without restarting in correct order | WAS caches classloaders, JNDI, and datasource connections; stale state causes intermittent failures | Follow the stop-deploy-start sequence; use rolling restarts in clustered environments |
| Configuring JDBC datasources without connection pool tuning | Default pool sizes cause connection exhaustion under load; applications block waiting for connections | Set minPoolSize, maxPoolSize, connectionTimeout, and reapTime based on load testing; monitor pool usage |
| Storing application configuration in server.xml without overrides | Environment-specific config (DB URLs, credentials) hardcoded; requires different builds per environment | Use variable substitution, jvm.options, or bootstrap.properties for environment-specific values |
| Not configuring JVM heap and garbage collection | Default JVM settings (-Xmx512m) are inadequate for production; GC pauses cause request timeouts | Set -Xms/-Xmx to 60-80% of container memory; use verbose:gc logging; tune GC policy for workload |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core RHEL admin (dnf, SELinux, firewalld, LVM) | `rhel-server-admin` |
| Web servers (Nginx, Apache/IHS, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| DB2 LUW on RHEL | `db2-rhel` |
| DB2 on z/OS | `db2-mainframe` |
| IBM Mainframe (JCL, TSO, ISPF) | `ibm-mainframe` |
| Cognos Analytics administration | `cognos-admin` |
| Docker / Podman containers | `rhel-docker-host` |
| Monitoring (Prometheus, Grafana, PCP) | `rhel-monitoring` |
