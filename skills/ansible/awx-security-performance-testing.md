# AWX, Security, Performance, and Testing

Reference file for the `ansible` skill. Covers AWX/Ansible Automation Platform (job templates, workflows, RBAC, surveys, API), security patterns (secret management, SSH hardening, lint rules), performance tuning (forks, pipelining, mitogen, fact caching), and testing (Molecule, ansible-lint, CI integration).

## 10. Security

### SSH Key Management

```yaml
# Distribute SSH keys via playbook
- name: Configure SSH access
  hosts: all
  become: true
  tasks:
    - name: Create ansible service account
      ansible.builtin.user:
        name: ansible
        shell: /bin/bash
        groups: wheel
        append: true
        create_home: true

    - name: Deploy authorized keys
      ansible.posix.authorized_key:
        user: ansible
        key: "{{ lookup('file', 'files/ssh_keys/' + item + '.pub') }}"
        state: present
        exclusive: false
      loop: "{{ authorized_admins }}"

    - name: Harden SSH daemon
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: "{{ item.regexp }}"
        line: "{{ item.line }}"
      loop:
        - { regexp: '^#?PermitRootLogin', line: 'PermitRootLogin no' }
        - { regexp: '^#?PasswordAuthentication', line: 'PasswordAuthentication no' }
        - { regexp: '^#?PubkeyAuthentication', line: 'PubkeyAuthentication yes' }
        - { regexp: '^#?MaxAuthTries', line: 'MaxAuthTries 3' }
      notify: Restart sshd

  handlers:
    - name: Restart sshd
      ansible.builtin.systemd:
        name: sshd
        state: restarted
```

### Become Methods

```yaml
# sudo (default)
become: true
become_method: sudo
become_user: root

# su
become_method: su

# pbrun (PowerBroker)
become_method: community.general.pbrun

# dzdo (Centrify DirectAuthorize)
become_method: community.general.dzdo

# Per-task become
- name: Run as postgres user
  ansible.builtin.command: pg_isready
  become: true
  become_user: postgres
  become_method: sudo
  changed_when: false
```

### HashiCorp Vault Integration

```yaml
# Lookup plugin — fetch secrets at runtime
tasks:
  - name: Retrieve database password from HashiCorp Vault
    ansible.builtin.set_fact:
      db_password: "{{ lookup('community.hashi_vault.hashi_vault',
        'secret/data/myapp/database:password',
        url='https://vault.internal.com:8200',
        token=lookup('env', 'VAULT_TOKEN')
      ) }}"

  - name: Use secret in template
    ansible.builtin.template:
      src: db.conf.j2
      dest: /etc/app/db.conf
      mode: "0600"
```

```bash
# Install the HashiCorp Vault collection
ansible-galaxy collection install community.hashi_vault
```

### Privilege Escalation Patterns

```yaml
# Limit become scope — don't blanket-become on the whole play
- name: Mixed privilege tasks
  hosts: webservers
  become: false                   # default: no elevation

  tasks:
    - name: Check application version (no privilege needed)
      ansible.builtin.command: /opt/app/bin/version
      changed_when: false

    - name: Install system package (needs root)
      ansible.builtin.dnf:
        name: nginx
        state: present
      become: true                # elevate only for this task

    - name: Reload nginx config (needs root)
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
      become: true
```

### Audit Logging

```yaml
# Enable callback plugin for audit trail
# ansible.cfg
[defaults]
callbacks_enabled = ansible.builtin.log_plays
log_path = /var/log/ansible/ansible.log

# In AWX/AAP: all job output is stored in the database with full audit trail
# including who launched, when, what changed, and complete stdout
```

---

## 11. Performance Tuning

### Forks (Concurrent Hosts)

```ini
# ansible.cfg
[defaults]
forks = 50              # default is 5 — increase based on control node resources
# Rule of thumb: 1 fork ≈ 50-100MB RAM on the control node
```

```bash
# Override at runtime
ansible-playbook site.yml --forks 30
```

### SSH Pipelining

```ini
# ansible.cfg — reduces SSH operations (no temp file on remote)
[ssh_connection]
pipelining = True
# Requires: requiretty must NOT be set in sudoers on managed nodes
# Comment out "Defaults requiretty" in /etc/sudoers if needed

ssh_args = -o ControlMaster=auto -o ControlPersist=60s
```

### Fact Caching

```ini
# ansible.cfg — avoid re-gathering facts on every run
[defaults]
gathering = smart        # only gather if facts not in cache
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 3600    # seconds

# Or use Redis for shared cache across multiple control nodes
fact_caching = community.general.redis
fact_caching_connection = redis01:6379:0
fact_caching_timeout = 3600
```

### Mitogen Strategy (3-5x Speedup)

```bash
# Install mitogen
python3 -m pip install mitogen
```

```ini
# ansible.cfg
[defaults]
strategy_plugins = /path/to/mitogen/ansible_mitogen/plugins/strategy
strategy = mitogen_linear
```

Mitogen eliminates most SSH round-trips by deploying a small Python interpreter on the remote host. Not compatible with all connection plugins.

### Async Tasks for Parallelism

```yaml
# Launch operations on all hosts simultaneously, then collect results
- name: Trigger yum update on all hosts (don't wait)
  ansible.builtin.dnf:
    name: "*"
    state: latest
    security: true
  async: 3600
  poll: 0
  register: yum_update

- name: Wait for all updates to complete
  ansible.builtin.async_status:
    jid: "{{ yum_update.ansible_job_id }}"
  register: update_result
  until: update_result.finished
  retries: 120
  delay: 30
```

### Profiling with Callback Plugins

```ini
# ansible.cfg — identify slow tasks
[defaults]
callbacks_enabled = ansible.builtin.profile_tasks, ansible.builtin.profile_roles, ansible.builtin.timer

# profile_tasks output example:
# Thursday 20 March 2026  14:02:33 +0000 (0:00:05.123)   0:02:41.567 *****
# Deploy application -------------------------------------------- 45.23s
# Run database migration ---------------------------------------- 32.11s
# Install packages ---------------------------------------------- 18.45s
```

### Other Performance Tips

```yaml
# Disable fact gathering when not needed
- hosts: all
  gather_facts: false

# Gather only specific fact subsets
- hosts: all
  gather_facts: true
  gather_subset:
    - network
    - hardware

# Use free strategy when task order between hosts doesn't matter
- hosts: all
  strategy: free

# Avoid unnecessary includes — import is faster (parsed once at load)
# Use include_tasks only when you need runtime-variable filenames

# Limit SSH round-trips
# - Combine related tasks using modules that accept lists
# - Use package manager list syntax instead of looping
- name: Install all packages at once (1 SSH call)
  ansible.builtin.dnf:
    name:
      - nginx
      - redis
      - python3-pip
      - git
    state: present
# NOT: loop over each package (4 SSH calls)
```

---

## 12. Testing

### ansible-lint

```bash
# Install
python3 -m pip install --user ansible-lint

# Run on a playbook
ansible-lint playbooks/site.yml

# Run on entire project
ansible-lint

# Skip specific rules
ansible-lint --skip-list yaml[truthy],name[casing]
```

Configuration `.ansible-lint`:

```yaml
---
skip_list:
  - yaml[truthy]         # allow yes/no in YAML
  - name[casing]         # allow flexible task name casing

warn_list:
  - experimental

enable_list:
  - fqcn[action-core]    # enforce FQCN for builtin modules
  - fqcn[action]         # enforce FQCN for all modules
  - no-changed-when      # require changed_when on command/shell

exclude_paths:
  - .cache/
  - .github/
  - collections/

use_default_rules: true
offline: false
```

Common rules and fixes:

| Rule | Problem | Fix |
|---|---|---|
| `fqcn[action-core]` | Bare module name `copy` | Use `ansible.builtin.copy` |
| `no-changed-when` | command/shell without changed_when | Add `changed_when: false` or condition |
| `risky-shell-pipe` | shell with pipes (can hide errors) | Add `set -o pipefail` or use purpose-built modules |
| `yaml[truthy]` | `yes`/`no` instead of `true`/`false` | Use `true`/`false` |
| `name[missing]` | Task without a name | Add descriptive `name:` |
| `no-jinja-when` | Jinja2 delimiters in `when:` | Remove `{{ }}` from `when:` conditions |

### yamllint

```bash
python3 -m pip install --user yamllint
yamllint .
```

Configuration `.yamllint`:

```yaml
---
extends: default
rules:
  line-length:
    max: 160
  truthy:
    allowed-values: ['true', 'false', 'yes', 'no']   # Ansible convention
  comments-indentation: disable
  braces:
    max-spaces-inside: 1
```

### Molecule

```bash
# Install Molecule with Docker driver
python3 -m pip install --user "molecule[docker]"

# Or with Podman
python3 -m pip install --user "molecule[podman]"

# Initialize Molecule in an existing role
cd roles/webserver/
molecule init scenario --driver-name docker
```

Molecule directory structure:

```
roles/webserver/molecule/
└── default/
    ├── molecule.yml        # scenario configuration
    ├── converge.yml        # playbook that applies the role
    ├── verify.yml          # tests to validate the result
    ├── prepare.yml         # optional: pre-test setup
    └── cleanup.yml         # optional: post-test cleanup
```

`molecule.yml`:

```yaml
---
dependency:
  name: galaxy
  options:
    requirements-file: requirements.yml

driver:
  name: docker

platforms:
  - name: rhel9
    image: redhat/ubi9-init
    pre_build_image: true
    privileged: true
    command: /usr/sbin/init
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw
    cgroupns_mode: host

  - name: ubuntu2404
    image: ubuntu:24.04
    pre_build_image: true
    command: /bin/bash
    tmpfs:
      - /run
      - /tmp

provisioner:
  name: ansible
  config_options:
    defaults:
      callbacks_enabled: profile_tasks
  inventory:
    group_vars:
      all:
        webserver_port: 8080
  lint: |
    set -e
    ansible-lint

verifier:
  name: ansible
```

`converge.yml`:

```yaml
---
- name: Converge
  hosts: all
  become: true
  roles:
    - role: webserver
      vars:
        webserver_port: 8080
        webserver_ssl_enabled: false
```

`verify.yml`:

```yaml
---
- name: Verify
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Check nginx is installed
      ansible.builtin.package_facts:
        manager: auto

    - name: Assert nginx package is installed
      ansible.builtin.assert:
        that: "'nginx' in ansible_facts.packages"
        fail_msg: "nginx is not installed"

    - name: Check nginx is running
      ansible.builtin.service_facts:

    - name: Assert nginx service is running
      ansible.builtin.assert:
        that:
          - "'nginx.service' in ansible_facts.services"
          - "ansible_facts.services['nginx.service'].state == 'running'"
        fail_msg: "nginx service is not running"

    - name: Check nginx is listening on configured port
      ansible.builtin.wait_for:
        port: 8080
        timeout: 10
```

### Molecule Commands

```bash
# Full test cycle (dependency → create → converge → verify → destroy)
molecule test

# Individual steps
molecule create          # spin up test containers
molecule converge        # run the role/playbook
molecule verify          # run verification tests
molecule login -h rhel9  # SSH into a test container for debugging
molecule destroy         # tear down test containers
molecule lint            # run linters only

# Re-converge without destroying (faster iteration)
molecule converge        # apply changes
molecule verify          # re-verify

# Test a specific scenario
molecule test -s security
```

### CI/CD Pipeline for Roles

```yaml
# .github/workflows/ansible-role.yml
name: Ansible Role CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: |
          pip install ansible-core ansible-lint yamllint
          yamllint .
          ansible-lint

  molecule:
    needs: lint
    runs-on: ubuntu-latest
    strategy:
      matrix:
        distro: [redhat/ubi9-init, ubuntu:24.04]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: |
          pip install ansible-core "molecule[docker]"
          pip install -r requirements.txt
      - run: molecule test
        env:
          MOLECULE_DISTRO: ${{ matrix.distro }}

  publish:
    needs: molecule
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: |
          pip install ansible-core
          ansible-galaxy role import --api-key ${{ secrets.GALAXY_API_KEY }} \
            ${{ github.repository_owner }} ${{ github.event.repository.name }}
```

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

