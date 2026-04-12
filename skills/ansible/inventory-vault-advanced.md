# Inventory, Vault, and Advanced Patterns

Reference file for the `ansible` skill. Covers inventory management (static/dynamic, group_vars/host_vars, patterns), Ansible Vault (encryption commands, vault IDs, rekeying), and advanced patterns (delegation, serial/rolling, async, custom modules, callback plugins, dynamic includes).

## 6. Inventory

### Static Inventory — INI Format

```ini
# inventory/hosts.ini
[webservers]
web01 ansible_host=10.0.1.10
web02 ansible_host=10.0.1.11
web03 ansible_host=10.0.1.12

[dbservers]
db01 ansible_host=10.0.2.10 ansible_user=dbadmin
db02 ansible_host=10.0.2.11 ansible_user=dbadmin

[loadbalancers]
lb01 ansible_host=10.0.0.10

[production:children]
webservers
dbservers
loadbalancers

[production:vars]
env=production
ntp_server=ntp.internal.com
```

### Static Inventory — YAML Format (preferred)

```yaml
# inventory/hosts.yml
all:
  vars:
    ansible_user: ansible
    ansible_ssh_private_key_file: ~/.ssh/ansible_ed25519
  children:
    production:
      children:
        webservers:
          hosts:
            web01:
              ansible_host: 10.0.1.10
            web02:
              ansible_host: 10.0.1.11
            web03:
              ansible_host: 10.0.1.12
          vars:
            http_port: 80
        dbservers:
          hosts:
            db01:
              ansible_host: 10.0.2.10
              postgres_version: 16
            db02:
              ansible_host: 10.0.2.11
              postgres_version: 16
          vars:
            db_backup_enabled: true
        loadbalancers:
          hosts:
            lb01:
              ansible_host: 10.0.0.10
    staging:
      children:
        staging_web:
          hosts:
            stg-web01:
              ansible_host: 10.1.1.10
```

### host_vars and group_vars Directories

```
inventory/
├── hosts.yml
├── group_vars/
│   ├── all.yml                 # applies to every host
│   ├── all/
│   │   ├── vars.yml
│   │   └── vault.yml           # encrypted with ansible-vault
│   ├── webservers.yml
│   ├── dbservers.yml
│   └── production.yml
└── host_vars/
    ├── web01.yml
    └── db01.yml
```

```yaml
# inventory/group_vars/all.yml
---
ntp_servers:
  - ntp1.internal.com
  - ntp2.internal.com
dns_servers:
  - 10.0.0.2
  - 10.0.0.3
admin_email: ops@example.com

# inventory/group_vars/webservers.yml
---
nginx_worker_connections: 4096
nginx_ssl_protocols: "TLSv1.2 TLSv1.3"

# inventory/host_vars/db01.yml
---
postgres_max_connections: 300
postgres_shared_buffers: 8GB
```

### Dynamic Inventory — AWS EC2

```yaml
# inventory/aws_ec2.yml
plugin: amazon.aws.aws_ec2
regions:
  - us-east-1
  - eu-west-1
filters:
  tag:Environment:
    - production
    - staging
  instance-state-name: running
keyed_groups:
  - key: tags.Role
    prefix: role
    separator: "_"
  - key: tags.Environment
    prefix: env
  - key: placement.region
    prefix: aws_region
hostnames:
  - tag:Name
  - private-ip-address
compose:
  ansible_host: private_ip_address
  ansible_user: "'ec2-user'"
```

```bash
# Test dynamic inventory
ansible-inventory -i inventory/aws_ec2.yml --list
ansible-inventory -i inventory/aws_ec2.yml --graph
```

### Dynamic Inventory — VMware

```yaml
# inventory/vmware.yml
plugin: community.vmware.vmware_vm_inventory
hostname: vcenter.internal.com
username: ansible@vsphere.local
password: "{{ lookup('env', 'VMWARE_PASSWORD') }}"
validate_certs: false
with_nested_properties: true
properties:
  - name
  - guest.ipAddress
  - config.guestId
  - runtime.powerState
filters:
  - runtime.powerState == "poweredOn"
keyed_groups:
  - key: config.guestId
    prefix: os
hostnames:
  - name
compose:
  ansible_host: guest.ipAddress
```

### Inventory Patterns

```bash
# Target specific groups
ansible-playbook site.yml --limit webservers

# Pattern matching
ansible-playbook site.yml --limit 'webservers:&production'   # intersection
ansible-playbook site.yml --limit 'webservers:!web03'        # exclusion
ansible-playbook site.yml --limit 'webservers:dbservers'     # union
ansible-playbook site.yml --limit '*.example.com'            # wildcard
ansible-playbook site.yml --limit 'web[01:03]'               # range
```

---

## 7. Ansible Vault

### Encrypting Files

```bash
# Create a new encrypted file
ansible-vault create group_vars/all/vault.yml

# Encrypt an existing file
ansible-vault encrypt group_vars/production/secrets.yml

# Decrypt (for editing outside vault)
ansible-vault decrypt group_vars/production/secrets.yml

# Edit encrypted file in-place
ansible-vault edit group_vars/all/vault.yml

# Rekey (change password)
ansible-vault rekey group_vars/all/vault.yml

# View contents without decrypting file
ansible-vault view group_vars/all/vault.yml
```

### Encrypting Single Variables (Inline)

```bash
# Encrypt a single value
ansible-vault encrypt_string 'SuperS3cretP@ss!' --name 'db_password'

# Output (paste into your vars file):
# db_password: !vault |
#   $ANSIBLE_VAULT;1.1;AES256
#   6438313339...
```

```yaml
# In your vars file — mix encrypted and plain variables
db_host: db01.internal.com
db_port: 5432
db_user: appuser
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  6438313339326166363233616530373365643963306632623564643839616531
  ...
```

### Vault Password Files

```bash
# Use a password file (avoid interactive prompt)
ansible-playbook site.yml --vault-password-file ~/.vault_pass

# Password file should be plain text, single line, mode 0600
echo 'MyVaultP@ssw0rd' > ~/.vault_pass
chmod 600 ~/.vault_pass

# Or use a script that outputs the password
ansible-playbook site.yml --vault-password-file vault_pass.sh
```

### Multi-Vault IDs

```bash
# Encrypt with named vault IDs
ansible-vault encrypt --vault-id prod@prompt group_vars/production/vault.yml
ansible-vault encrypt --vault-id dev@~/.dev_vault_pass group_vars/staging/vault.yml

# Run playbook with multiple vault IDs
ansible-playbook site.yml \
  --vault-id prod@~/.prod_vault_pass \
  --vault-id dev@~/.dev_vault_pass
```

### Vault in CI/CD

```bash
# Pass vault password via environment variable
export ANSIBLE_VAULT_PASSWORD_FILE=<(echo "$VAULT_PASSWORD")
ansible-playbook site.yml

# Or use a wrapper script: vault_pass.sh
#!/bin/bash
echo "$VAULT_PASSWORD"

# In CI/CD pipeline (GitHub Actions example):
# env:
#   VAULT_PASSWORD: ${{ secrets.ANSIBLE_VAULT_PASSWORD }}
# steps:
#   - run: |
#       echo "$VAULT_PASSWORD" > .vault_pass
#       chmod 600 .vault_pass
#       ansible-playbook -i inventory/ site.yml --vault-password-file .vault_pass
#       rm -f .vault_pass
```

---

## 8. Advanced Patterns

### Delegation

```yaml
tasks:
  # Run task on a different host
  - name: Add host to load balancer
    ansible.builtin.command: /usr/local/bin/lb-add {{ inventory_hostname }}
    delegate_to: lb01
    changed_when: true

  # Run on localhost (API calls, DNS updates)
  - name: Create DNS record via API
    ansible.builtin.uri:
      url: "https://dns.internal.com/api/records"
      method: POST
      body_format: json
      body:
        name: "{{ inventory_hostname }}"
        type: A
        value: "{{ ansible_default_ipv4.address }}"
      headers:
        Authorization: "Bearer {{ dns_api_token }}"
    delegate_to: localhost
    run_once: true
```

### Rolling Updates (serial)

```yaml
- name: Rolling update of web servers
  hosts: webservers
  serial: 2                       # update 2 hosts at a time
  max_fail_percentage: 25         # abort if >25% fail

  pre_tasks:
    - name: Disable in load balancer
      ansible.builtin.uri:
        url: "http://lb01/api/disable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost

  roles:
    - role: deploy_app

  post_tasks:
    - name: Wait for health check
      ansible.builtin.uri:
        url: "http://{{ inventory_hostname }}:{{ http_port }}/health"
        status_code: 200
      retries: 10
      delay: 5
      delegate_to: localhost

    - name: Re-enable in load balancer
      ansible.builtin.uri:
        url: "http://lb01/api/enable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
```

```yaml
# Stepped serial — increasingly larger batches
serial:
  - 1       # first: single canary host
  - 3       # then: 3 hosts
  - "25%"   # then: 25% of remaining
```

### Async and Poll (Long-Running Tasks)

```yaml
tasks:
  # Fire and forget — don't wait
  - name: Start long backup job
    ansible.builtin.command: /usr/local/bin/full-backup.sh
    async: 3600            # allow up to 1 hour
    poll: 0                # don't wait (fire-and-forget)
    register: backup_job
    changed_when: true

  # ... do other tasks while backup runs ...

  # Check on async job later
  - name: Wait for backup to complete
    ansible.builtin.async_status:
      jid: "{{ backup_job.ansible_job_id }}"
    register: backup_result
    until: backup_result.finished
    retries: 60
    delay: 60

  # Async with polling (wait, but with timeout)
  - name: Run database vacuum
    ansible.builtin.command: vacuumdb --all --full
    async: 1800            # 30 minute timeout
    poll: 30               # check every 30 seconds
    changed_when: true
```

### Strategy Plugins

```yaml
# Linear (default) — all hosts complete task N before moving to N+1
- hosts: all
  strategy: linear

# Free — each host runs as fast as possible, independently
- hosts: all
  strategy: free

# Debug — interactive debugger on failure
- hosts: all
  strategy: debug
  # On failure, drop into debugger: p task, p task.args, p result, redo, continue

# Host pinned — each host gets a dedicated worker
- hosts: all
  strategy: host_pinned
```

### Include vs Import (Dynamic vs Static)

```yaml
# import_tasks — STATIC: parsed at playbook load time
# - Tags, when, and other directives apply to ALL tasks inside
# - Cannot use variables in the filename that are set during play
- name: Import database tasks
  ansible.builtin.import_tasks: tasks/database.yml
  when: deploy_database | default(true)
  tags: [database]

# include_tasks — DYNAMIC: parsed at runtime when reached
# - Can use runtime variables in filename
# - Tags only apply to the include statement, not inner tasks (unless using apply)
- name: Include OS-specific tasks
  ansible.builtin.include_tasks: "tasks/{{ ansible_os_family | lower }}.yml"

# include_tasks with tag inheritance
- name: Include with tags
  ansible.builtin.include_tasks:
    file: tasks/setup.yml
    apply:
      tags: [setup]
  tags: [setup]

# import_role — STATIC
- ansible.builtin.import_role:
    name: nginx

# include_role — DYNAMIC (can use runtime variables)
- ansible.builtin.include_role:
    name: "{{ web_server_role }}"
```

### Custom Filter Plugins

```python
# filter_plugins/custom_filters.py
class FilterModule:
    def filters(self):
        return {
            'to_cidr': self.to_cidr,
            'normalize_hostname': self.normalize_hostname,
        }

    @staticmethod
    def to_cidr(ip, prefix=24):
        """Convert IP to CIDR notation."""
        return f"{ip}/{prefix}"

    @staticmethod
    def normalize_hostname(name):
        """Lowercase and strip domain."""
        return name.lower().split('.')[0]
```

Usage: `"{{ my_ip | to_cidr(28) }}"` returns `10.0.1.5/28`.

### Custom Lookup Plugins

```python
# lookup_plugins/custom_secret.py
from ansible.plugins.lookup import LookupBase
from ansible.errors import AnsibleError
import requests

class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        results = []
        vault_url = kwargs.get('vault_url', 'https://vault.internal.com')
        token = kwargs.get('token', variables.get('vault_token'))
        for term in terms:
            try:
                resp = requests.get(
                    f"{vault_url}/v1/secret/data/{term}",
                    headers={"X-Vault-Token": token}
                )
                resp.raise_for_status()
                results.append(resp.json()['data']['data']['value'])
            except Exception as e:
                raise AnsibleError(f"Error looking up {term}: {e}")
        return results
```

Usage: `"{{ lookup('custom_secret', 'db/password', vault_url='https://vault.internal.com') }}"`.

---

## 9. AWX / Ansible Automation Platform

### AWX Installation (Kubernetes)

```bash
# Install AWX Operator via Helm
helm repo add awx-operator https://ansible-community.github.io/awx-operator-helm/
helm install awx-operator awx-operator/awx-operator -n awx --create-namespace

# Create AWX instance
cat <<'EOF' | kubectl apply -n awx -f -
apiVersion: awx.ansible.com/v1beta1
kind: AWX
metadata:
  name: awx
spec:
  service_type: NodePort
  nodeport_port: 30080
  admin_user: admin
  postgres_storage_class: standard
  projects_persistence: true
  projects_storage_size: 10Gi
EOF

# Retrieve admin password
kubectl get secret awx-admin-password -n awx -o jsonpath='{.data.password}' | base64 -d
```

### AAP Installation (RHEL — Subscription Required)

```bash
# Download AAP installer from access.redhat.com
tar xzf ansible-automation-platform-setup-bundle-*.tar.gz
cd ansible-automation-platform-setup-bundle-*/

# Edit inventory for single-node install
cat > inventory <<'EOF'
[automationcontroller]
aap01.internal.com

[automationhub]
aap01.internal.com

[database]
aap01.internal.com

[all:vars]
admin_password='StrongAdm1nP@ss!'
pg_host='aap01.internal.com'
pg_port=5432
pg_database='awx'
pg_username='awx'
pg_password='StrongPgP@ss!'
automationhub_admin_password='HubAdm1nP@ss!'
automationhub_pg_host='aap01.internal.com'
automationhub_pg_port=5432
automationhub_pg_database='automationhub'
automationhub_pg_username='automationhub'
automationhub_pg_password='HubPgP@ss!'
EOF

sudo ./setup.sh
```

### Core AWX/AAP Concepts

**Organizations** — top-level grouping for teams, projects, inventories, credentials.

**Projects** — link to a Git repository (or local directory) containing playbooks.

```
Project → Git SCM → https://git.internal.com/ansible/infra.git
  Branch: main
  Update on launch: Yes
  Credential: Git SSH key
```

**Inventories** — can be static (manual), sourced from project, or dynamic (cloud/SCM).

**Credentials** — securely stored, types include:
- Machine (SSH key/password for managed hosts)
- Source Control (Git auth)
- Vault (Ansible Vault password)
- Cloud (AWS, Azure, GCP, VMware)
- Container Registry
- Custom credential types

**Job Templates** — tie together project + inventory + credentials + playbook.

```
Job Template: "Deploy Web App"
  Project: infra-repo
  Playbook: playbooks/deploy_webapp.yml
  Inventory: Production Servers
  Credentials: [Machine — SSH Key, Vault — Prod Vault]
  Extra Variables: version=2.5.0
  Limit: webservers
  Verbosity: 0 (Normal)
  Forks: 20
  Job Tags: deploy
  Enable Privilege Escalation: Yes
```

### Workflow Templates

Workflows chain multiple job templates with conditional logic:

```
[Update Packages] → success → [Deploy App] → success → [Smoke Tests]
                                            → failure → [Rollback]
                  → failure → [Send Alert]
```

- Nodes: job templates, project syncs, inventory syncs, approval nodes
- Convergence: any or all (how to handle multiple incoming paths)
- Extra variables: set at workflow level, passed to all nodes
- Surveys: prompt for runtime input before workflow starts

### Surveys (Runtime Parameters)

Surveys add a user-friendly form before job/workflow execution:

```yaml
# Survey fields (configured in UI or API):
- variable: target_env
  question: "Target environment?"
  type: multiplechoice
  choices: ["staging", "production"]
  required: true
  default: staging

- variable: app_version
  question: "Application version to deploy?"
  type: text
  required: true
  min: 3
  max: 20

- variable: run_migration
  question: "Run database migration?"
  type: multiplechoice
  choices: ["yes", "no"]
  default: "no"

- variable: notify_channel
  question: "Slack channel for notifications"
  type: text
  required: false
  default: "#deployments"
```

### RBAC (Role-Based Access Control)

| Role | Scope | Permissions |
|---|---|---|
| System Administrator | Global | Full control over everything |
| System Auditor | Global | Read-only access to everything |
| Organization Admin | Org | Full control within organization |
| Organization Auditor | Org | Read-only within organization |
| Admin (resource) | Single resource | Full control over one template/inventory/etc |
| Execute | Job Template | Can launch jobs |
| Use | Credential/Inventory | Can use in job templates but not edit |
| Update | Project/Inventory | Can trigger SCM/inventory sync |
| Read | Any | View-only access |

Best practice: create Teams, assign roles to teams, add users to teams. Avoid per-user permissions.

### Schedules and Notifications

```
# Schedule (cron-like)
Job Template: "Nightly Patching"
Schedule: 0 2 * * 0    # Sundays at 02:00 UTC
Timezone: UTC
Enabled: Yes

# Notification Templates
Type: Slack
URL: https://hooks.slack.com/services/T00/B00/XXXX
Channel: #ansible-alerts
Events: [started, success, failure]
```

---

