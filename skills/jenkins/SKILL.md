---
name: jenkins
description: Use when installing, configuring, or developing with Jenkins CI/CD — server administration (installation on RHEL, systemd, reverse proxy, backup), security (RBAC, LDAP/AD, credentials management, script approval), declarative and scripted pipelines (Jenkinsfile), shared libraries, multibranch pipelines, agent management (SSH/JNLP/Docker/Kubernetes agents), plugin management, job DSL, Blue Ocean, Jenkins Configuration as Code (JCasC), and pipeline best practices. Part of the cicd-* skill family.
---

# Jenkins CI/CD — Administration & Development

For Docker agent patterns see `docker-admin` and `docker-cicd`. For reverse proxy configuration see `rhel-web-servers` or `ubuntu-web-servers`.

<HARD-RULE>
Never store credentials in Jenkinsfile or pipeline code — always use the Credentials plugin with credential IDs and withCredentials() blocks.
</HARD-RULE>

<HARD-RULE>
Never run builds on the Jenkins controller — always use agents; controller builds are a security risk and degrade controller performance.
</HARD-RULE>

<HARD-RULE>
Always use declarative pipeline syntax for new pipelines — scripted pipelines are harder to maintain and lack built-in validation.
</HARD-RULE>

<HARD-RULE>
Never skip the script approval process — unapproved scripts can execute arbitrary code on the controller with full system access.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [admin-security-agents.md](admin-security-agents.md) | architecture overview, RHEL 9 installation, security (RBAC, LDAP/AD, credentials), and agent management (SSH, Docker, Kubernetes) |
| [backup-jcasc-pipelines.md](backup-jcasc-pipelines.md) | backup/disaster recovery, Jenkins Configuration as Code (JCasC), and declarative pipeline syntax and patterns |
| [libraries-multibranch-patterns-dsl.md](libraries-multibranch-patterns-dsl.md) | shared libraries, multibranch pipelines, advanced pipeline patterns (parallel, matrix, docker agents), and Job DSL |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Configuring jobs through the UI instead of Jenkinsfile | No version control, no code review, no audit trail; configuration drift between environments | Use declarative Jenkinsfile in SCM; treat pipeline as code; review changes through PRs |
| Running builds on the Jenkins controller node | Controller becomes unstable; resource contention; security risk if builds have network access | Use dedicated agents (Docker, SSH, or cloud agents); controller should only orchestrate |
| Storing credentials in pipeline scripts or environment variables | Plaintext secrets in build logs, SCM history, and console output | Use Jenkins Credentials store with proper scoping; access via credentials() binding in Jenkinsfile |
| No pipeline timeout or resource limits | Stuck builds consume executor slots indefinitely; queue backs up; other builds starve | Set `timeout` in pipeline options; configure executor limits per node; use `lock` for shared resources |
| Not backing up Jenkins configuration | Controller disk failure loses all job configs, credentials, and build history; days of manual recreation | Schedule daily backups of JENKINS_HOME (or use SCM-based config with JCasC); test restore quarterly |

---

## Related Skills

| Topic | Skill |
|---|---|
| Docker agent patterns, Dockerfile best practices | `docker-admin`, `docker-cicd` |
| Docker networking, storage, security | `docker-networking`, `docker-storage`, `docker-security` |
| Docker Compose for local Jenkins stacks | `docker-compose-patterns` |
| Reverse proxy (Nginx/Apache) for Jenkins | `rhel-web-servers`, `ubuntu-web-servers` |
| RHEL system admin (systemd, firewalld, SELinux) | `rhel-server-admin` |
| Kubernetes cluster management | (kubernetes skill — planned) |
| LDAP/AD/SSO configuration | `windows-sso`, `linux-centrify` |
| Git workflows and branching strategies | (git skill — planned) |
| IBM WebSphere deployments from Jenkins | `ibm-websphere` |
| IBM MQ integration in pipelines | `ibm-mq` |
| BMC Control-M job scheduling alongside Jenkins | `control-m` |
