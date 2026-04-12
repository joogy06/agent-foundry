---
name: ansible
description: Use when automating infrastructure with Ansible — playbook development (tasks, handlers, variables, templates, conditionals, loops), role design (Galaxy structure, defaults, dependencies), inventory management (static/dynamic, groups, host_vars/group_vars), collections (ansible.builtin, community, custom), Ansible Vault (encryption), AWX/Ansible Automation Platform (job templates, workflows, RBAC, surveys), module development, testing (Molecule, ansible-lint), and performance tuning (forks, pipelining, async). Part of the automation-* skill family.
---

# Ansible Automation — Admin & Developer

Covers Ansible core (ansible-core 2.15+/2.16+/2.17+), collections ecosystem, AWX/Ansible Automation Platform, and testing. For target node configuration see: `rhel-server-admin`, `ubuntu-server-admin`, `windows-powershell`.

<HARD-RULE>
Never store plaintext secrets in playbooks or inventory — always use Ansible Vault or external secret managers (HashiCorp Vault, AWS Secrets Manager).
</HARD-RULE>

<HARD-RULE>
Always use fully qualified collection names (FQCN) for modules — bare module names are deprecated and cause ambiguity with collections.
</HARD-RULE>

<HARD-RULE>
Never use command/shell modules when a purpose-built module exists — idempotent modules (apt, yum, copy, template, service) are safer and provide proper changed/ok reporting.
</HARD-RULE>

<HARD-RULE>
Always set changed_when on command/shell tasks — without it, Ansible always reports changed, making idempotency checks useless.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [awx-security-performance-testing.md](awx-security-performance-testing.md) | AWX/Ansible Automation Platform (job templates, workflows, RBAC, surveys, API), security patterns (secret management, SSH hardening, lint rules), performance tuning (forks, pipelining, mitogen, fact caching), and testing (Molecule, ansible-lint, CI integration) |
| [fundamentals-playbooks.md](fundamentals-playbooks.md) | installation, playbook structure, ad-hoc commands, ansible.cfg, connection types, tasks (core patterns, variables, conditionals, loops, blocks, error handling), handlers, includes vs imports |
| [inventory-vault-advanced.md](inventory-vault-advanced.md) | inventory management (static/dynamic, group_vars/host_vars, patterns), Ansible Vault (encryption commands, vault IDs, rekeying), and advanced patterns (delegation, serial/rolling, async, custom modules, callback plugins, dynamic includes) |
| [templates-roles-collections.md](templates-roles-collections.md) | Jinja2 templates, file management modules, role design (Galaxy structure, defaults, dependencies), and collections (installing, using, creating custom collections) |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `command`/`shell` for package installs | Not idempotent — reruns always show changed, no rollback, no version pinning | Use `ansible.builtin.dnf`, `ansible.builtin.apt`, or platform-specific package modules |
| Hardcoding IPs and hostnames in playbooks | Breaks when inventory changes, makes playbooks non-portable | Use inventory variables, `host_vars`/`group_vars`, and dynamic inventory plugins |
| One massive playbook with no roles | Becomes unmaintainable past 200 lines, no reuse across projects | Break into roles with Galaxy structure; one role = one concern |
| Storing vault password in the repo | Anyone with repo access can decrypt all secrets | Use `--vault-password-file` pointing to a file outside the repo, or integrate with external secret manager |
| Running playbooks without `--check --diff` first in production | Unexpected changes hit live systems with no preview | Always dry-run with `--check --diff` on production inventories before applying |
| Ignoring `ansible-lint` warnings | Leads to deprecated syntax, bare module names, and missing `changed_when` — breaks on ansible-core upgrades | Run `ansible-lint` in CI; treat warnings as errors for production playbooks |

---

## Related Skills

| Domain | Skill |
|---|---|
| RHEL server admin (targets) | `rhel-server-admin` |
| Ubuntu server admin (targets) | `ubuntu-server-admin` |
| Windows PowerShell (WinRM targets) | `windows-powershell` |
| Docker containers | `docker-admin` |
| Database config on RHEL | `rhel-databases` |
| Database config on Ubuntu | `ubuntu-databases` |
| IBM MQ automation | `ibm-mq` |
| IBM WebSphere automation | `ibm-websphere` |
| Centrify/AD integration | `linux-centrify` |
| BMC Control-M job scheduling | `control-m` |
