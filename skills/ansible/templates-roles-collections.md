# Templates, Roles, and Collections

Reference file for the `ansible` skill. Covers Jinja2 templates, file management modules, role design (Galaxy structure, defaults, dependencies), and collections (installing, using, creating custom collections).

## 3. Templates & Files

### Jinja2 Templates

Template file `templates/nginx.conf.j2`:

```jinja2
# Managed by Ansible — DO NOT EDIT MANUALLY
# Generated: {{ ansible_date_time.iso8601 }}

worker_processes {{ ansible_processor_vcpus }};
worker_rlimit_nofile 65535;

events {
    worker_connections {{ nginx_worker_connections | default(4096) }};
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent"';

    access_log /var/log/nginx/access.log main;

{% for vhost in nginx_vhosts %}
    server {
        listen {{ vhost.port | default(80) }};
        server_name {{ vhost.server_name }};
        root {{ vhost.root | default('/var/www/html') }};

{% if vhost.ssl | default(false) %}
        listen {{ vhost.ssl_port | default(443) }} ssl;
        ssl_certificate {{ vhost.ssl_cert }};
        ssl_certificate_key {{ vhost.ssl_key }};
{% endif %}

{% for location in vhost.locations | default([]) %}
        location {{ location.path }} {
            proxy_pass {{ location.backend }};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
{% endfor %}
    }
{% endfor %}
}
```

### Common Jinja2 Filters

```yaml
# Default values
"{{ variable | default('fallback') }}"
"{{ optional_list | default([], true) }}"     # true = also default on empty string

# String manipulation
"{{ hostname | upper }}"
"{{ fqdn | regex_replace('\\.example\\.com$', '') }}"
"{{ items | join(', ') }}"
"{{ password | password_hash('sha512', salt) }}"

# Data format conversion
"{{ data | to_json }}"
"{{ data | to_yaml }}"
"{{ data | to_nice_json(indent=2) }}"
"{{ '{"key":"val"}' | from_json }}"

# List/dict operations
"{{ users | map(attribute='name') | list }}"
"{{ servers | selectattr('role', 'equalto', 'web') | list }}"
"{{ list1 | union(list2) }}"
"{{ list1 | intersect(list2) }}"
"{{ list1 | difference(list2) }}"
"{{ dict1 | combine(dict2, recursive=True) }}"

# IP address filters
"{{ ansible_default_ipv4.address | ansible.utils.ipaddr('network/prefix') }}"
"{{ '192.168.1.0/24' | ansible.utils.ipsubnet(28, 3) }}"

# Comparison
"{{ version | version_compare('2.0', '>=') }}"    # deprecated, use 'version' test
"{{ version is version('2.0', '>=') }}"
```

### File Management Modules

```yaml
tasks:
  # Template (Jinja2 rendering)
  - name: Deploy application config
    ansible.builtin.template:
      src: app.conf.j2
      dest: /etc/app/app.conf
      owner: app
      group: app
      mode: "0640"
      backup: true                   # creates .bak before overwrite
      validate: "/usr/sbin/app-check %s"   # validate before placing

  # Copy (static files)
  - name: Deploy SSL certificate
    ansible.builtin.copy:
      src: files/certs/app.crt
      dest: /etc/pki/tls/certs/app.crt
      owner: root
      group: root
      mode: "0644"

  # Copy with inline content
  - name: Create environment file
    ansible.builtin.copy:
      content: |
        APP_ENV={{ app_env }}
        APP_PORT={{ app_port }}
        DB_HOST={{ db_host }}
      dest: /etc/app/environment
      mode: "0600"

  # Lineinfile (surgical edits)
  - name: Set SELINUX to enforcing
    ansible.builtin.lineinfile:
      path: /etc/selinux/config
      regexp: '^SELINUX='
      line: 'SELINUX=enforcing'

  # Blockinfile (managed blocks)
  - name: Add custom SSH banner
    ansible.builtin.blockinfile:
      path: /etc/ssh/sshd_config
      marker: "# {mark} ANSIBLE MANAGED — SSH BANNER"
      block: |
        Banner /etc/issue.net
        PrintMotd no

  # File (create dirs, symlinks, permissions)
  - name: Create log directory
    ansible.builtin.file:
      path: /var/log/app
      state: directory
      owner: app
      group: app
      mode: "0750"
      recurse: true

  # Synchronize (rsync wrapper)
  - name: Sync application code
    ansible.posix.synchronize:
      src: /local/app/
      dest: /opt/app/
      delete: true
      rsync_opts:
        - "--exclude=.git"
```

---

## 4. Role Design

### Galaxy Structure

```
roles/
└── webserver/
    ├── defaults/
    │   └── main.yml          # lowest-precedence variables (user overrides these)
    ├── vars/
    │   └── main.yml          # high-precedence variables (internal, not for users)
    ├── tasks/
    │   ├── main.yml          # entry point — includes sub-task files
    │   ├── install.yml
    │   ├── configure.yml
    │   └── service.yml
    ├── handlers/
    │   └── main.yml
    ├── templates/
    │   └── nginx.conf.j2
    ├── files/
    │   └── index.html
    ├── meta/
    │   └── main.yml          # Galaxy metadata, dependencies
    ├── molecule/
    │   └── default/
    │       ├── converge.yml
    │       ├── verify.yml
    │       └── molecule.yml
    ├── README.md
    └── LICENSE
```

### defaults/main.yml vs vars/main.yml

```yaml
# defaults/main.yml — PUBLIC interface, users override these
webserver_port: 80
webserver_worker_connections: 4096
webserver_ssl_enabled: false
webserver_ssl_cert: ""
webserver_ssl_key: ""
webserver_vhosts: []
webserver_extra_packages: []

# vars/main.yml — PRIVATE internals, not meant for user override
_webserver_config_path: /etc/nginx/nginx.conf
_webserver_service_name: nginx
_webserver_user: nginx
```

Convention: prefix private vars with `_` to signal they are internal.

### tasks/main.yml — Modular Includes

```yaml
---
- name: Include OS-specific variables
  ansible.builtin.include_vars: "{{ item }}"
  with_first_found:
    - "{{ ansible_distribution }}-{{ ansible_distribution_major_version }}.yml"
    - "{{ ansible_os_family }}.yml"
    - default.yml

- name: Install web server packages
  ansible.builtin.include_tasks: install.yml
  tags: [install]

- name: Configure web server
  ansible.builtin.include_tasks: configure.yml
  tags: [configure]

- name: Manage web server service
  ansible.builtin.include_tasks: service.yml
  tags: [service]
```

### meta/main.yml — Dependencies

```yaml
---
galaxy_info:
  author: your_name
  description: Installs and configures Nginx web server
  license: MIT
  min_ansible_version: "2.15"
  platforms:
    - name: EL
      versions: [9]
    - name: Ubuntu
      versions: [jammy, noble]
  galaxy_tags:
    - web
    - nginx

dependencies:
  - role: common
  - role: firewall
    vars:
      firewall_allowed_ports:
        - 80/tcp
        - 443/tcp
```

### Scaffolding a New Role

```bash
# Create role skeleton
ansible-galaxy role init roles/myapp

# Install roles from requirements
ansible-galaxy role install -r requirements.yml -p roles/

# requirements.yml
roles:
  - name: geerlingguy.nginx
    version: "6.2.0"
  - name: geerlingguy.certbot
    version: "5.1.0"
  - src: git+https://git.internal.com/ansible/common.git
    scm: git
    version: v2.0.0
    name: common
```

### When to Create a Role vs Inline Tasks

Create a role when:
- Logic is reused across 2+ playbooks
- Component has its own variables, templates, and handlers
- You want to test it independently with Molecule
- It represents a distinct infrastructure component (web server, database, monitoring agent)

Use inline tasks when:
- Logic is one-off or play-specific
- Less than 10 tasks with no templates or handlers
- Quick prototyping before refactoring into a role

---

## 5. Collections

### Installing Collections

```yaml
# collections/requirements.yml
collections:
  - name: ansible.posix
    version: ">=1.5.0"
  - name: community.general
    version: ">=9.0.0"
  - name: community.crypto
  - name: ansible.utils
  - name: amazon.aws
    version: ">=7.0.0"
  - name: azure.azcollection
  - name: community.vmware
  - name: ansible.netcommon
  - name: cisco.ios

  # From a private Automation Hub
  - name: company.internal
    source: https://hub.internal.com/api/galaxy/content/published/
```

```bash
# Install from requirements file
ansible-galaxy collection install -r collections/requirements.yml -p ./collections/

# Install a single collection
ansible-galaxy collection install community.general

# List installed collections
ansible-galaxy collection list
```

### Using FQCN (Fully Qualified Collection Names)

```yaml
# CORRECT — always use FQCN
- name: Install package
  ansible.builtin.dnf:
    name: nginx
    state: present

- name: Manage SELinux boolean
  ansible.posix.seboolean:
    name: httpd_can_network_connect
    state: true
    persistent: true

# WRONG — bare module names (deprecated, ambiguous)
- name: Install package
  dnf:
    name: nginx
```

### Key Built-in and Community Modules

| Collection | Common Modules |
|---|---|
| `ansible.builtin` | `dnf`, `apt`, `yum`, `copy`, `template`, `file`, `lineinfile`, `systemd`, `user`, `group`, `command`, `shell`, `uri`, `get_url`, `unarchive`, `debug`, `assert`, `set_fact`, `stat`, `wait_for`, `cron` |
| `ansible.posix` | `firewalld`, `seboolean`, `selinux`, `sysctl`, `synchronize`, `authorized_key`, `mount`, `at` |
| `community.general` | `nmcli`, `timezone`, `modprobe`, `pam_limits`, `ini_file`, `xml`, `json_query`, `slack`, `terraform` |
| `community.crypto` | `openssl_privatekey`, `openssl_csr`, `x509_certificate`, `acme_certificate` |
| `amazon.aws` | `ec2_instance`, `s3_bucket`, `rds_instance`, `iam_role`, `lambda`, `cloudformation` |
| `community.vmware` | `vmware_guest`, `vmware_datastore_info`, `vmware_cluster_info` |

### Creating a Custom Collection

```bash
# Initialize collection structure
ansible-galaxy collection init mycompany.myplatform
cd mycompany/myplatform/

# Structure:
# mycompany/myplatform/
# ├── galaxy.yml
# ├── plugins/
# │   ├── modules/
# │   ├── module_utils/
# │   ├── filter/
# │   └── lookup/
# ├── roles/
# ├── playbooks/
# ├── docs/
# └── meta/runtime.yml

# Build and publish
ansible-galaxy collection build
ansible-galaxy collection publish mycompany-myplatform-1.0.0.tar.gz --api-key=<token>
```

---

