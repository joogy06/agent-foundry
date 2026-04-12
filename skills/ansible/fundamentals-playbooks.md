# Ansible Fundamentals and Playbook Development

Reference file for the `ansible` skill. Covers installation, playbook structure, ad-hoc commands, ansible.cfg, connection types, tasks (core patterns, variables, conditionals, loops, blocks, error handling), handlers, includes vs imports.

## 1. Fundamentals

### Installation

```bash
# Python pip (recommended for latest ansible-core)
python3 -m pip install --user ansible-core    # minimal, just ansible-core
python3 -m pip install --user ansible          # full package with community collections

# RHEL 9 / AlmaLinux / Rocky
sudo dnf install -y ansible-core               # from AppStream

# Ubuntu 24.04
sudo apt update && sudo apt install -y ansible

# Verify
ansible --version
ansible-community --version 2>/dev/null        # full package only
```

### Playbook Structure

```yaml
---
- name: Configure web servers
  hosts: webservers
  become: true
  gather_facts: true
  vars:
    http_port: 8080
    max_clients: 200

  pre_tasks:
    - name: Update package cache
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

  roles:
    - role: common
    - role: nginx
      vars:
        nginx_port: "{{ http_port }}"

  tasks:
    - name: Ensure application config is deployed
      ansible.builtin.template:
        src: app.conf.j2
        dest: /etc/app/app.conf
        owner: root
        group: root
        mode: "0644"
      notify: Restart application

  handlers:
    - name: Restart application
      ansible.builtin.systemd:
        name: app
        state: restarted
        daemon_reload: true

  post_tasks:
    - name: Verify application is listening
      ansible.builtin.uri:
        url: "http://localhost:{{ http_port }}/health"
        status_code: 200
      retries: 5
      delay: 3
```

### Ad-Hoc Commands

```bash
# Ping all hosts
ansible all -m ansible.builtin.ping

# Gather facts from a group
ansible webservers -m ansible.builtin.setup -a "filter=ansible_distribution*"

# Run a command (use sparingly — prefer modules)
ansible dbservers -m ansible.builtin.command -a "pg_isready -h 127.0.0.1"

# Copy a file
ansible all -m ansible.builtin.copy -a "src=/tmp/motd dest=/etc/motd" --become

# Install a package
ansible webservers -m ansible.builtin.dnf -a "name=nginx state=present" --become

# Limit to specific hosts
ansible webservers -m ansible.builtin.service -a "name=nginx state=started" --limit web01
```

### ansible.cfg Precedence (highest to lowest)

1. `ANSIBLE_CONFIG` environment variable
2. `./ansible.cfg` (current directory)
3. `~/.ansible.cfg` (home directory)
4. `/etc/ansible/ansible.cfg` (system-wide)

Typical project-level `ansible.cfg`:

```ini
[defaults]
inventory = ./inventory/
roles_path = ./roles:~/.ansible/roles
collections_path = ./collections:~/.ansible/collections
remote_user = ansible
host_key_checking = False
retry_files_enabled = False
stdout_callback = yaml
callbacks_enabled = profile_tasks
forks = 20
timeout = 30

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o PreferSharedKey=yes
```

### Connection Types

```yaml
# SSH (default for Linux/Unix)
ansible_connection: ssh

# WinRM (Windows targets)
ansible_connection: winrm
ansible_winrm_transport: ntlm        # or kerberos, credssp
ansible_winrm_server_cert_validation: ignore

# Local (run on control node itself)
ansible_connection: local

# Docker container
ansible_connection: community.docker.docker

# Network devices
ansible_connection: ansible.netcommon.network_cli
ansible_network_os: cisco.ios.ios
```

### Python Requirements on Managed Nodes

Ansible requires Python on managed nodes (except for `raw` and `script` modules). Minimum Python 3.8+ for ansible-core 2.16+.

```yaml
# Bootstrap Python on a fresh node
- name: Bootstrap Python
  hosts: new_servers
  gather_facts: false
  tasks:
    - name: Install Python 3 (raw module — no Python needed)
      ansible.builtin.raw: |
        if command -v apt-get >/dev/null; then
          apt-get update && apt-get install -y python3
        elif command -v dnf >/dev/null; then
          dnf install -y python3
        fi
      changed_when: true
```

---

## 2. Playbook Development

### Tasks — Core Patterns

```yaml
tasks:
  # Basic task with FQCN
  - name: Install required packages
    ansible.builtin.dnf:
      name:
        - nginx
        - python3-pip
        - git
      state: present

  # Register output for later use
  - name: Check if config exists
    ansible.builtin.stat:
      path: /etc/app/config.yml
    register: config_file

  - name: Generate default config
    ansible.builtin.template:
      src: config.yml.j2
      dest: /etc/app/config.yml
    when: not config_file.stat.exists

  # changed_when / failed_when overrides
  - name: Get current version
    ansible.builtin.command: /usr/local/bin/app --version
    register: app_version
    changed_when: false              # read-only command, never changes state
    failed_when: app_version.rc not in [0, 1]

  # Ignore errors and handle manually
  - name: Check optional service
    ansible.builtin.systemd:
      name: optional-agent
      state: started
    register: agent_result
    ignore_errors: true

  - name: Log agent status
    ansible.builtin.debug:
      msg: "Agent not available — skipping"
    when: agent_result is failed
```

### Handlers — notify and listen

```yaml
tasks:
  - name: Deploy nginx config
    ansible.builtin.template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    notify:
      - Validate nginx config
      - Reload nginx

  - name: Deploy SSL certificate
    ansible.builtin.copy:
      src: "{{ ssl_cert_file }}"
      dest: /etc/pki/tls/certs/app.crt
    notify: Reload nginx

handlers:
  - name: Validate nginx config
    ansible.builtin.command: nginx -t
    changed_when: false
    listen: "Validate and reload nginx"

  - name: Reload nginx
    ansible.builtin.systemd:
      name: nginx
      state: reloaded
    listen: "Validate and reload nginx"
```

Handlers run once at end of play, in definition order (not notification order). Use `meta: flush_handlers` to force immediate execution.

### Variable Precedence (highest to lowest)

1. Extra vars (`-e` / `--extra-vars`) — always win
2. Task vars (`vars:` in a task)
3. Block vars
4. Role and include params
5. `set_fact` / registered vars
6. Play vars_files, vars_prompt, play vars
7. Host facts / cached facts
8. `host_vars/hostname`
9. `group_vars/child_group`
10. `group_vars/parent_group`
11. `group_vars/all`
12. Role defaults (`defaults/main.yml`) — always lose

```yaml
# CLI extra vars (highest precedence)
ansible-playbook site.yml -e "http_port=9090 env=production"

# Extra vars from file
ansible-playbook site.yml -e @vars/production.yml
```

### Facts

```yaml
tasks:
  # Access gathered facts
  - name: Show OS info
    ansible.builtin.debug:
      msg: "{{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_version'] }}"

  # Custom facts (place .fact files on managed nodes)
  # /etc/ansible/facts.d/app.fact (INI or JSON)
  # Accessed as: ansible_local.app.section.key

  # Set runtime facts
  - name: Determine deployment tier
    ansible.builtin.set_fact:
      deploy_tier: "{{ 'production' if 'prod' in group_names else 'staging' }}"
      cacheable: true     # persists across plays if fact caching is enabled
```

### Conditionals

```yaml
tasks:
  # Simple when
  - name: Install EPEL (RHEL only)
    ansible.builtin.dnf:
      name: epel-release
      state: present
    when: ansible_distribution == "RedHat" or ansible_distribution == "AlmaLinux"

  # Complex conditions
  - name: Restart service if config changed and not in maintenance
    ansible.builtin.systemd:
      name: app
      state: restarted
    when:
      - config_result is changed          # AND logic (list = AND)
      - not maintenance_mode | default(false)
      - ansible_memtotal_mb >= 2048

  # Conditional on registered output
  - name: Run migration
    ansible.builtin.command: /app/migrate.sh
    when: app_version.stdout is version('2.0', '<')
    changed_when: "'Migrated' in migration_result.stdout"
    register: migration_result
```

### Loops

```yaml
tasks:
  # Simple loop
  - name: Create application users
    ansible.builtin.user:
      name: "{{ item }}"
      shell: /bin/bash
      groups: appusers
      append: true
    loop:
      - alice
      - bob
      - charlie

  # Loop with dictionaries
  - name: Configure firewall rules
    ansible.posix.firewalld:
      port: "{{ item.port }}/{{ item.proto }}"
      permanent: true
      immediate: true
      state: enabled
    loop:
      - { port: 80, proto: tcp }
      - { port: 443, proto: tcp }
      - { port: 8080, proto: tcp }

  # Loop with index
  - name: Create data directories
    ansible.builtin.file:
      path: "/data/vol{{ idx }}"
      state: directory
      mode: "0755"
    loop: "{{ range(1, 5) | list }}"
    loop_control:
      loop_var: idx
      label: "vol{{ idx }}"           # cleaner output

  # Nested loop (subelements)
  - name: Add SSH keys for each user
    ansible.posix.authorized_key:
      user: "{{ item.0.name }}"
      key: "{{ item.1 }}"
    loop: "{{ users | subelements('ssh_keys') }}"

  # Loop over dictionary
  - name: Set sysctl values
    ansible.posix.sysctl:
      name: "{{ item.key }}"
      value: "{{ item.value }}"
      sysctl_set: true
      reload: true
    loop: "{{ sysctl_params | dict2items }}"

  # Fileglob loop
  - name: Copy all config snippets
    ansible.builtin.copy:
      src: "{{ item }}"
      dest: /etc/app/conf.d/
    with_fileglob:
      - "files/conf.d/*.conf"
```

### Blocks — Error Handling

```yaml
tasks:
  - name: Deploy with rollback capability
    block:
      - name: Deploy new version
        ansible.builtin.unarchive:
          src: "https://releases.example.com/app-{{ version }}.tar.gz"
          dest: /opt/app/
          remote_src: true

      - name: Run database migration
        ansible.builtin.command: /opt/app/migrate.sh
        changed_when: "'Applied' in migrate_result.stdout"
        register: migrate_result

      - name: Restart application
        ansible.builtin.systemd:
          name: app
          state: restarted

    rescue:
      - name: Rollback to previous version
        ansible.builtin.command: /opt/app/rollback.sh
        changed_when: true

      - name: Send failure notification
        ansible.builtin.uri:
          url: "https://hooks.slack.com/services/T00/B00/XXXX"
          method: POST
          body_format: json
          body:
            text: "Deployment of {{ version }} failed on {{ inventory_hostname }}"

    always:
      - name: Ensure app service is running
        ansible.builtin.systemd:
          name: app
          state: started
```

---

