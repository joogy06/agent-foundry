# Admin Role

Reference file for the `control-m` skill. Covers server/agent administration, configuration, security, integrations, and infrastructure management.

## Admin Role

### 1. Architecture

**Core components:**

| Component | Purpose | Default Port |
|---|---|---|
| Control-M/Server | Scheduling engine, job submission, condition management | 7005 (agent comm) |
| Control-M/EM (Enterprise Manager) | Centralized GUI, config server, GCS (Global Conditions Server) | 2370 (EM-Server), 8443 (Web) |
| Control-M/Agent | Runs on target hosts, executes jobs, reports status | 7006 (from server) |
| Control-M Web | Browser-based interface (replaces legacy Desktop) | 8443 (HTTPS) |
| BIM (Business Impact Manager) | SLA tracking, critical path, impact analysis | Integrated with EM |
| Control-M/Forecast | Simulates future schedules without ordering | Integrated with Server |
| Database | PostgreSQL (default 9.0.21+), Oracle, or MSSQL backend | 5432 / 1521 / 1433 |

**Helix Control-M (SaaS):** BMC-managed server/EM in the cloud. Customer deploys agents on-premises. No server infrastructure to manage. API-first design. Same Automation API, different connectivity model (outbound HTTPS from agent to Helix endpoint).

**Data flow:** Job definitions (folders) are deployed to Control-M/Server. On scheduling date, Server orders jobs into the Active Jobs table. Server sends execution requests to Agents. Agents execute and report back. EM aggregates status from all Servers.

### 2. Server & Agent Administration

#### Server Configuration (ctmsys)

```bash
# Access server configuration utility
ctmsys

# Key server parameters
# MAX_DAYS_KEEP_COMPLETED   — days to retain completed job history (default 1)
# COMM_TIMEOUT              — agent communication timeout in seconds (default 120)
# ORDERDAY_FROM             — new day start time (default 00:00)
# ORDERDAY_UNTIL            — new day end time (default 00:00, meaning midnight-to-midnight)
# MAX_CONCURRENT_JOBS       — server-wide concurrency limit
```

#### Server Lifecycle

```bash
# Start/stop Control-M/Server (run as ctmserver user)
ctm_menu                       # interactive menu
shut_ca                        # graceful shutdown (waits for running jobs)
start_ca                       # start server

# Check server status
ctmpsm -LISTALL               # list all server processes
ctmcontb -LIST                 # list active job count

# New Day procedure (manual trigger — normally automatic)
ctmndp                         # run New Day procedure
ctmndp -CONFIRM                # confirm New Day (if confirmation required)
```

#### Agent Installation on RHEL

```bash
# Prerequisites
sudo dnf install -y glibc.i686 libstdc++.i686 compat-libstdc++-33   # 32-bit libs (if needed)
sudo groupadd -g 1500 ctmagent
sudo useradd -u 1500 -g ctmagent -m -d /home/ctmagent -s /bin/bash ctmagent

# Create install directory
sudo mkdir -p /opt/ctm_agent
sudo chown ctmagent:ctmagent /opt/ctm_agent

# Silent install (from agent setup kit)
su - ctmagent
cd /tmp/agent_install
./setup.sh -silent install.xml
# install.xml contains: AGENT_PORT, PRIMARY_SERVER, AUTHORIZED_SERVER_LIST, INSTALL_DIR
```

Silent install XML example (`install.xml`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<AutomatedInstallation>
  <installDir>/opt/ctm_agent</installDir>
  <agentPort>7006</agentPort>
  <primaryServer>ctmserver01.example.com</primaryServer>
  <authorizedServers>ctmserver01.example.com|ctmserver02.example.com</authorizedServers>
  <agentName>agent-rhel-prod01</agentName>
</AutomatedInstallation>
```

#### Agent via Automation API (preferred method)

```bash
# Install agent using ctm CLI (downloads and installs from server)
ctm provision agent::install \
  ctmserver01.example.com \
  agent-rhel-prod01 \
  7006

# Verify agent connectivity
ctm config server:agents::get ctmserver01.example.com

# List all agents registered to a server
ctm config server:agents::get ctmserver01.example.com -s "name=*"
```

#### Agent Diagnostics

```bash
# Run agent diagnostic (as ctmagent user)
ag_diag_comm

# Check agent-to-server connectivity
ag_ping                        # ping from agent to server
tcping ctmserver01.example.com 7005  # verify port reachability

# Agent process check
ps -ef | grep p_ctmag          # p_ctmag = agent listener process

# Agent log files
tail -f /opt/ctm_agent/proclog/agent_log.txt
tail -f /opt/ctm_agent/proclog/diag_log.txt
```

#### Hostgroups and Host Aliases

```bash
# Create a hostgroup (logical group of agents for load balancing)
ctm config server:hostgroup::add ctmserver01.example.com "HG_APP_SERVERS"

# Add agents to hostgroup
ctm config server:hostgroup:agent::add ctmserver01.example.com "HG_APP_SERVERS" "agent-rhel-prod01"
ctm config server:hostgroup:agent::add ctmserver01.example.com "HG_APP_SERVERS" "agent-rhel-prod02"

# List agents in a hostgroup
ctm config server:hostgroup:agents::get ctmserver01.example.com "HG_APP_SERVERS"
```

### 3. Security & Roles

#### Role-Based Access Model

| Role | Access | Typical Use |
|---|---|---|
| Browse | View jobs, logs, output — no modifications | Auditors, observers |
| Update | Add/modify job definitions in dev folders, view all | Developers |
| Full | All operations including production folder changes | Operators, senior admins |
| Admin | EM configuration, user/role management, server config | Platform admins only |

#### User & Authorization Management

```bash
# Automation API — create a user
ctm config authorization:user::add \
  -f user_definition.json

# user_definition.json
{
  "Name": "john.developer",
  "FullName": "John Developer",
  "Description": "App team developer",
  "Roles": ["DeveloperRole"],
  "Password": "CHANGE_ME_ON_FIRST_LOGIN"
}

# Create a role with folder-level authorization
ctm config authorization:role::add \
  -f role_definition.json

# role_definition.json
{
  "Name": "DeveloperRole",
  "Description": "Developer access to dev folders only",
  "Privileges": {
    "Folder": "DEV_*",
    "Run": false,
    "FolderUpdate": true,
    "JobDefinition": "Update",
    "ActiveJobs": "Browse"
  }
}
```

#### LDAP/Active Directory Integration

Configure in Control-M/EM Configuration Manager:

- **LDAP URL:** `ldaps://ldap.example.com:636`
- **Base DN:** `dc=example,dc=com`
- **User Search Filter:** `(&(objectClass=user)(sAMAccountName={0}))`
- **Group Search Filter:** `(&(objectClass=group)(member={0}))`
- Map LDAP groups to Control-M roles (e.g., `CTM-Developers` -> `DeveloperRole`)

#### API Key Management

```bash
# Generate API token for automation (CI/CD pipelines)
ctm session login -u api_user -p "$CTM_PASSWORD"
# Returns a session token — use in subsequent requests

# For long-lived tokens (Helix Control-M)
# Generate in Control-M Web > Settings > API Keys
# Use as: ctm session login -token "<api_key>"
```

#### Audit Trail

```bash
# Query audit log via Automation API
ctm reporting audit::get \
  -s "fromTime=20260301000000&toTime=20260331235959&action=OrderJob"

# Common audit actions: Login, OrderJob, HoldJob, FreeJob, ForceOK, DeleteJob, UpdateFolder
```

### 4. RHEL-Specific Administration

#### Systemd Service for Agent

Create `/etc/systemd/system/ctm_agent.service`:

```ini
[Unit]
Description=Control-M Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=ctmagent
Group=ctmagent
Environment="HOME=/home/ctmagent"
Environment="CONTROLM=/opt/ctm_agent"
ExecStart=/opt/ctm_agent/scripts/start-ag -u ctmagent -p 7006
ExecStop=/opt/ctm_agent/scripts/shut-ag -u ctmagent -p 7006
Restart=on-failure
RestartSec=30
LimitNOFILE=65536
TimeoutStartSec=120
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ctm_agent
sudo systemctl status ctm_agent
journalctl -u ctm_agent -f
```

#### Firewalld Rules

```bash
# Agent ports — allow from Control-M/Server only
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.10/32" port port="7006" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.10/32" port port="7005" protocol="tcp" accept'

# If running Control-M Web on this host
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/16" port port="8443" protocol="tcp" accept'

# Apply
sudo firewall-cmd --reload
sudo firewall-cmd --list-rich-rules
```

#### SELinux Contexts

```bash
# Label Control-M agent directories
sudo semanage fcontext -a -t bin_t "/opt/ctm_agent/scripts(/.*)?"
sudo semanage fcontext -a -t var_log_t "/opt/ctm_agent/proclog(/.*)?"
sudo semanage fcontext -a -t usr_t "/opt/ctm_agent(/.*)?"
sudo restorecon -Rv /opt/ctm_agent

# If using non-standard agent port
sudo semanage port -a -t unreserved_port_t -p tcp 7006
sudo semanage port -a -t unreserved_port_t -p tcp 7005

# Troubleshoot SELinux denials
sudo ausearch -m AVC -c p_ctmag --start recent
sudo sealert -a /var/log/audit/audit.log
```

#### User and Resource Limits

```bash
# /etc/security/limits.d/99-ctmagent.conf
ctmagent   soft   nofile   65536
ctmagent   hard   nofile   65536
ctmagent   soft   nproc    16384
ctmagent   hard   nproc    16384
```

---

