---
name: ubuntu-monitoring
description: Use when setting up monitoring and logging on Ubuntu 24.04 LTS — Prometheus and node_exporter, Grafana dashboards, Loki/Alloy log aggregation (Promtail legacy), ELK stack (Elasticsearch, Logstash, Kibana), alerting with Alertmanager, systemd journal management, rsyslog, and health check patterns. Part of the ubuntu-* skill family.
---

# Ubuntu Server 24.04 LTS — Monitoring and Logging

<!-- FRESHNESS:v1
anchors:
  - kind: status_snapshot
    subject: log-shipping-stack
    verified_against: "Promtail EOL 2026-03-02 (LTS since 2025-02-13); Grafana Alloy is the supported log shipper — Alloy 1.16.x current"
    verified_on: "2026-06-10"
  - kind: status_snapshot
    subject: version-pins
    verified_against: "Prometheus 3.12.0, node_exporter 1.11.1, Alertmanager 0.32.1, Loki 3.7.2, blackbox_exporter 0.28.0"
    verified_on: "2026-06-10"
volatility: high
-->

Companion skill to `ubuntu-server-admin`. Covers metrics collection, visualization, log aggregation, alerting, and health checks on Ubuntu Server 24.04.4 LTS (Noble Numbat).

<HARD-RULE>
Always verify the Ubuntu version before applying advice. Packages, paths, and repo signing methods differ between releases.
```bash
lsb_release -a   # or cat /etc/os-release
uname -r          # kernel version
```
</HARD-RULE>

<HARD-RULE>
Monitoring stacks can consume significant resources. Always size memory and disk before deploying. A Prometheus + Grafana + Loki stack needs at minimum 2 GB RAM and 20 GB disk for small environments. Elasticsearch alone requires at least 4 GB RAM (see JVM heap section).
</HARD-RULE>

---

## 1. Prometheus

### Installation (Binary Method)

```bash
# Create system user
sudo useradd -r -s /usr/sbin/nologin prometheus

# Create directories
sudo mkdir -p /etc/prometheus /var/lib/prometheus
sudo chown prometheus:prometheus /var/lib/prometheus

# Download and install (check https://prometheus.io/download/ for latest)
PROM_VER="3.12.0"   # verified current 2026-06-10
cd /tmp
curl -LO "https://github.com/prometheus/prometheus/releases/download/v${PROM_VER}/prometheus-${PROM_VER}.linux-amd64.tar.gz"
tar xzf "prometheus-${PROM_VER}.linux-amd64.tar.gz"
sudo cp "prometheus-${PROM_VER}.linux-amd64"/{prometheus,promtool} /usr/local/bin/
sudo chown -R prometheus:prometheus /etc/prometheus
```

Note: Prometheus 3.x tarballs no longer ship the example `consoles/` and `console_libraries/` directories (removed in 3.0). If you are upgrading an existing 2.x install rather than doing a fresh install, read the official 2.x → 3.x migration guide first.

### Configuration — `/etc/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  scrape_timeout: 10s

rule_files:
  - /etc/prometheus/rules/*.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - localhost:9093

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "node"
    static_configs:
      - targets:
          - "localhost:9100"
          - "10.0.1.51:9100"
          - "10.0.1.52:9100"

  - job_name: "custom-app"
    metrics_path: /metrics
    scheme: http
    static_configs:
      - targets: ["localhost:8080"]
```

### Recording Rules — `/etc/prometheus/rules/recording.yml`

```yaml
groups:
  - name: node_recording
    interval: 15s
    rules:
      - record: node:cpu_utilization:ratio
        expr: 1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
      - record: node:memory_utilization:ratio
        expr: 1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
      - record: node:filesystem_usage:ratio
        expr: 1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})
```

### Systemd Service — `/etc/systemd/system/prometheus.service`

```ini
[Unit]
Description=Prometheus Monitoring
After=network-online.target
Wants=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.retention.size=10GB \
  --web.listen-address=0.0.0.0:9090 \
  --web.enable-lifecycle
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
sudo ufw allow from 10.0.0.0/8 to any port 9090 proto tcp
```

<HARD-RULE>
Prometheus storage sizing: estimate ~2 bytes per sample. For 500 active time series scraped every 15 s with 30-day retention: 500 * (86400/15) * 30 * 2 = ~1.7 GB. Always set both `retention.time` and `retention.size` to prevent disk exhaustion. Monitor `prometheus_tsdb_storage_size_bytes` to track actual usage.
</HARD-RULE>

### Validate Config

```bash
promtool check config /etc/prometheus/prometheus.yml
promtool check rules /etc/prometheus/rules/recording.yml
```

---

## 2. node_exporter

### Installation

```bash
sudo useradd -r -s /usr/sbin/nologin node_exporter

NODE_VER="1.11.1"   # verified current 2026-06-10
cd /tmp
curl -LO "https://github.com/prometheus/node_exporter/releases/download/v${NODE_VER}/node_exporter-${NODE_VER}.linux-amd64.tar.gz"
tar xzf "node_exporter-${NODE_VER}.linux-amd64.tar.gz"
sudo cp "node_exporter-${NODE_VER}.linux-amd64/node_exporter" /usr/local/bin/
```

### Systemd Service — `/etc/systemd/system/node_exporter.service`

```ini
[Unit]
Description=Node Exporter
After=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter \
  --collector.textfile.directory=/var/lib/node_exporter/textfile_collector \
  --collector.systemd \
  --collector.processes
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/lib/node_exporter/textfile_collector
sudo chown node_exporter:node_exporter /var/lib/node_exporter/textfile_collector
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
sudo ufw allow from 10.0.0.0/8 to any port 9100 proto tcp
```

### Custom Textfile Collector Example

```bash
# Write custom metrics for Prometheus to scrape
# Run via cron or systemd timer — output to textfile_collector directory
cat <<'SCRIPT' | sudo tee /usr/local/bin/custom-metrics.sh
#!/bin/bash
OUTPUT="/var/lib/node_exporter/textfile_collector/custom.prom"
# Pending apt updates
UPDATES=$(apt list --upgradable 2>/dev/null | grep -c upgradable)
echo "apt_upgradable_packages ${UPDATES}" > "${OUTPUT}.tmp"
# Reboot required
REBOOT=0
[ -f /var/run/reboot-required ] && REBOOT=1
echo "node_reboot_required ${REBOOT}" >> "${OUTPUT}.tmp"
mv "${OUTPUT}.tmp" "${OUTPUT}"
SCRIPT
sudo chmod +x /usr/local/bin/custom-metrics.sh
```

### Key Metrics to Monitor

| Metric | PromQL | Alert threshold |
|---|---|---|
| CPU usage | `node:cpu_utilization:ratio` | > 0.85 for 10m |
| Memory usage | `node:memory_utilization:ratio` | > 0.90 for 5m |
| Disk usage | `node:filesystem_usage:ratio` | > 0.85 |
| Disk I/O util | `rate(node_disk_io_time_seconds_total[5m])` | > 0.90 for 15m |
| Network errors | `rate(node_network_receive_errs_total[5m])` | > 0 |
| Systemd failed | `node_systemd_unit_state{state="failed"}` | == 1 |

---

## 3. Grafana

### Installation from Official Repository

```bash
sudo apt install -y apt-transport-https software-properties-common
curl -fsSL https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update
sudo apt install -y grafana
sudo systemctl enable --now grafana-server
sudo ufw allow 3000/tcp
```

Default login: `admin` / `admin` (change immediately on first login).

### Provisioning Datasources — `/etc/grafana/provisioning/datasources/prometheus.yaml`

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:9090
    isDefault: true
    editable: false
  - name: Loki
    type: loki
    access: proxy
    url: http://localhost:3100
    editable: false
```

### Provisioning Dashboards — `/etc/grafana/provisioning/dashboards/default.yaml`

```yaml
apiVersion: 1
providers:
  - name: default
    orgId: 1
    folder: Provisioned
    type: file
    disableDeletion: false
    updateIntervalSeconds: 60
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

### Import Community Dashboards

```bash
# Download "Node Exporter Full" dashboard (ID 1860) for file provisioning
sudo mkdir -p /var/lib/grafana/dashboards
curl -s "https://grafana.com/api/dashboards/1860/revisions/latest/download" \
  | sudo tee /var/lib/grafana/dashboards/node-exporter-full.json > /dev/null

# Or import via API
curl -s -X POST http://admin:admin@localhost:3000/api/dashboards/import \
  -H "Content-Type: application/json" \
  -d '{
    "dashboard": { "id": null },
    "overwrite": true,
    "inputs": [{ "name": "DS_PROMETHEUS", "type": "datasource", "pluginId": "prometheus", "value": "Prometheus" }],
    "folderId": 0
  }'
```

### Grafana Config Highlights — `/etc/grafana/grafana.ini`

```ini
[server]
http_port = 3000
root_url = http://grafana.example.com:3000

[security]
admin_password = changeme_on_first_boot
disable_gravatar = true

[auth.anonymous]
enabled = false

[log]
mode = console file
level = warn
```

```bash
sudo systemctl restart grafana-server
```

---

## 4. Alertmanager

### Installation

```bash
sudo useradd -r -s /usr/sbin/nologin alertmanager
AM_VER="0.32.1"   # verified current 2026-06-10
cd /tmp
curl -LO "https://github.com/prometheus/alertmanager/releases/download/v${AM_VER}/alertmanager-${AM_VER}.linux-amd64.tar.gz"
tar xzf "alertmanager-${AM_VER}.linux-amd64.tar.gz"
sudo cp "alertmanager-${AM_VER}.linux-amd64"/{alertmanager,amtool} /usr/local/bin/
sudo mkdir -p /etc/alertmanager /var/lib/alertmanager
sudo chown alertmanager:alertmanager /var/lib/alertmanager
```

### Configuration — `/etc/alertmanager/alertmanager.yml`

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: "smtp.example.com:587"
  smtp_from: "alerts@example.com"
  smtp_auth_username: "alerts@example.com"
  smtp_auth_password: "app-password-here"
  smtp_require_tls: true

route:
  receiver: default-email
  group_by: [alertname, instance]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: slack-critical
      repeat_interval: 1h
    - match:
        severity: page
      receiver: pagerduty

receivers:
  - name: default-email
    email_configs:
      - to: "ops-team@example.com"
        send_resolved: true

  - name: slack-critical
    slack_configs:
      - api_url: "https://hooks.slack.com/services/T00/B00/XXXX"
        channel: "#alerts-critical"
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
        send_resolved: true

  - name: pagerduty
    pagerduty_configs:
      - service_key: "your-pagerduty-integration-key"
        severity: critical

inhibit_rules:
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: [alertname, instance]
```

### Systemd Service — `/etc/systemd/system/alertmanager.service`

```ini
[Unit]
Description=Alertmanager
After=network-online.target

[Service]
User=alertmanager
Group=alertmanager
Type=simple
ExecStart=/usr/local/bin/alertmanager \
  --config.file=/etc/alertmanager/alertmanager.yml \
  --storage.path=/var/lib/alertmanager \
  --web.listen-address=0.0.0.0:9093
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alertmanager
```

### Alert Rules in Prometheus — `/etc/prometheus/rules/alerts.yml`

```yaml
groups:
  - name: node_alerts
    rules:
      - alert: HighCPU
        expr: node:cpu_utilization:ratio > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
          description: "CPU usage is {{ $value | humanizePercentage }} for 10+ minutes."

      - alert: HighMemory
        expr: node:memory_utilization:ratio > 0.90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Memory critically high on {{ $labels.instance }}"

      - alert: DiskSpaceLow
        expr: node:filesystem_usage:ratio > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk space above 85% on {{ $labels.instance }}"

      - alert: InstanceDown
        expr: up == 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Instance {{ $labels.instance }} is unreachable"

  - name: prometheus_alerts
    rules:
      - alert: PrometheusTargetMissing
        expr: up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus target {{ $labels.instance }} is down"
```

### Manage Silences

```bash
# Create a silence via amtool
amtool --alertmanager.url=http://localhost:9093 silence add \
  alertname="HighCPU" instance="10.0.1.51:9100" \
  --comment="Maintenance window" --duration=2h

# List active silences
amtool --alertmanager.url=http://localhost:9093 silence query

# Expire a silence
amtool --alertmanager.url=http://localhost:9093 silence expire <silence-id>
```

---

## 5. Loki + Grafana Alloy (Log Shipping)

> **Log-shipper status (verified 2026-06-10):** Grafana deprecated **Promtail** in February 2025 (LTS from 2025-02-13) in favor of **Grafana Alloy**, and Promtail reached **end of life on 2026-03-02** — no further updates, including security fixes. **Use Alloy for ALL new installs.** The Promtail material is kept below only as a clearly-marked LEGACY/migration appendix for existing deployments.

### Loki Installation

```bash
sudo useradd -r -s /usr/sbin/nologin loki
LOKI_VER="3.7.2"   # verified current 2026-06-10
cd /tmp
curl -LO "https://github.com/grafana/loki/releases/download/v${LOKI_VER}/loki-linux-amd64.zip"
sudo apt install -y unzip
unzip loki-linux-amd64.zip
sudo cp loki-linux-amd64 /usr/local/bin/loki
sudo chmod +x /usr/local/bin/loki
sudo mkdir -p /etc/loki /var/lib/loki
sudo chown loki:loki /var/lib/loki
```

### Loki Config — `/etc/loki/loki.yml`

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /var/lib/loki
  storage:
    filesystem:
      chunks_directory: /var/lib/loki/chunks
      rules_directory: /var/lib/loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 30d
  max_query_series: 5000
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20

compactor:
  working_directory: /var/lib/loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
```

### Loki Systemd Service — `/etc/systemd/system/loki.service`

```ini
[Unit]
Description=Loki Log Aggregation
After=network-online.target

[Service]
User=loki
Group=loki
Type=simple
ExecStart=/usr/local/bin/loki -config.file=/etc/loki/loki.yml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Grafana Alloy — Log Shipper (PRIMARY)

Alloy is Grafana's OpenTelemetry-based collector and the supported replacement for Promtail (Alloy 1.16.x current as of 2026-06). It installs from the same Grafana apt repository configured in section 3 — if you already added that repo, just install the package:

```bash
# Repo already added in section 3? Then simply:
sudo apt update
sudo apt install -y alloy

# Otherwise add the Grafana repo first (same as section 3):
curl -fsSL https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install -y alloy
```

The package installs a systemd service named `alloy` running as the `alloy` user, with config at `/etc/alloy/config.alloy` and service options (e.g. `CUSTOM_ARGS`) in `/etc/default/alloy`. Grant it read access to the journal and privileged log files instead of running it as root:

```bash
sudo usermod -aG systemd-journal,adm alloy   # journal + /var/log/syslog,auth.log (root:adm on Ubuntu)
```

### Alloy Config — `/etc/alloy/config.alloy`

Alloy uses its own HCL-like syntax (not YAML). Pipeline: journal + file sources → optional relabel → `loki.write` push to Loki on :3100.

```alloy
// ── Systemd journal ────────────────────────────────────────────
loki.relabel "journal" {
  forward_to = []   // rules-only component; consumed via .rules below

  rule {
    source_labels = ["__journal__systemd_unit"]
    target_label  = "unit"
  }
  rule {
    source_labels = ["__journal__hostname"]
    target_label  = "hostname"
  }
}

loki.source.journal "system" {
  max_age       = "12h"
  labels        = { job = "systemd-journal" }
  relabel_rules = loki.relabel.journal.rules
  forward_to    = [loki.write.local.receiver]
}

// ── Plain log files ────────────────────────────────────────────
local.file_match "system_logs" {
  path_targets = [
    { __address__ = "localhost", __path__ = "/var/log/syslog",      job = "syslog" },
    { __address__ = "localhost", __path__ = "/var/log/auth.log",    job = "authlog" },
    { __address__ = "localhost", __path__ = "/var/log/myapp/*.log", job = "app" },
  ]
}

loki.source.file "system_logs" {
  targets    = local.file_match.system_logs.targets
  forward_to = [loki.write.local.receiver]
}

// ── Push to Loki ───────────────────────────────────────────────
loki.write "local" {
  endpoint {
    url = "http://localhost:3100/loki/api/v1/push"
  }
  external_labels = {}
}
```

```bash
# Syntax check (parses + formats the file; errors on invalid config)
alloy fmt /etc/alloy/config.alloy

sudo systemctl daemon-reload
sudo systemctl enable --now loki alloy
sudo systemctl reload alloy    # after later config edits
sudo ufw allow from 10.0.0.0/8 to any port 3100 proto tcp
```

Alloy serves a debug UI on `127.0.0.1:12345` by default (component health, live pipeline graph) — check it when logs are not arriving.

---

### LEGACY — Promtail (EOL, migration only)

> **Do NOT use Promtail for new installs.** Deprecated February 2025; end of life since 2026-03-02 (no security fixes). This appendix exists only for understanding/migrating existing Promtail deployments.

**Migrating an existing deployment:** Alloy ships a converter that translates a Promtail YAML config into Alloy syntax:

```bash
alloy convert --source-format=promtail --output=/etc/alloy/config.alloy /etc/promtail/promtail.yml
# Review the output, then disable promtail and enable alloy:
sudo systemctl disable --now promtail
sudo systemctl enable --now alloy
```

#### Legacy Promtail Install (reference only)

```bash
cd /tmp
curl -LO "https://github.com/grafana/loki/releases/download/v${LOKI_VER}/promtail-linux-amd64.zip"
unzip promtail-linux-amd64.zip
sudo cp promtail-linux-amd64 /usr/local/bin/promtail
sudo chmod +x /usr/local/bin/promtail
sudo mkdir -p /etc/promtail
```

#### Legacy Promtail Config — `/etc/promtail/promtail.yml`

```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://localhost:3100/loki/api/v1/push

scrape_configs:
  # Systemd journal
  - job_name: journal
    journal:
      max_age: 12h
      labels:
        job: systemd-journal
    relabel_configs:
      - source_labels: [__journal__systemd_unit]
        target_label: unit
      - source_labels: [__journal__hostname]
        target_label: hostname

  # System log files
  - job_name: syslog
    static_configs:
      - targets: [localhost]
        labels:
          job: syslog
          __path__: /var/log/syslog

  - job_name: authlog
    static_configs:
      - targets: [localhost]
        labels:
          job: authlog
          __path__: /var/log/auth.log

  # Application logs (wildcard)
  - job_name: app-logs
    static_configs:
      - targets: [localhost]
        labels:
          job: app
          __path__: /var/log/myapp/*.log
```

#### Legacy Promtail Systemd Service — `/etc/systemd/system/promtail.service`

```ini
[Unit]
Description=Promtail Log Collector
After=network-online.target

[Service]
User=root
Type=simple
ExecStart=/usr/local/bin/promtail -config.file=/etc/promtail/promtail.yml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Note: Promtail ran as root to read journal and privileged log files — one more reason to prefer Alloy (group-based access, see above). End of legacy appendix.

### LogQL Query Examples

```
# All logs from a specific unit
{unit="nginx.service"}

# Filter by content
{job="syslog"} |= "error"
{job="authlog"} |= "Failed password"

# Regex filter
{unit="ssh.service"} |~ "Failed|Invalid"

# Rate of errors (logs per second over 5m)
rate({job="syslog"} |= "error" [5m])

# Top source IPs for SSH failures
topk(10, count_over_time({job="authlog"} |= "Failed password" [1h]))

# JSON log parsing
{job="app"} | json | status >= 500
```

---

## 6. ELK Stack (Elasticsearch, Logstash, Kibana)

<HARD-RULE>
Elasticsearch JVM heap: set to exactly 50% of available RAM, never exceed 32 GB. Below 4 GB total RAM the JVM will be unstable. For a dedicated node, 8 GB RAM minimum is strongly recommended. Set both -Xms and -Xmx to the same value to avoid resize pauses.
</HARD-RULE>

### Elasticsearch Installation

```bash
curl -fsSL https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo gpg --dearmor -o /usr/share/keyrings/elasticsearch.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/elasticsearch.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/elastic-8.x.list
sudo apt update
sudo apt install -y elasticsearch
```

### Elasticsearch Config — `/etc/elasticsearch/elasticsearch.yml`

```yaml
cluster.name: homelab-logging
node.name: elk-01
path.data: /var/lib/elasticsearch
path.logs: /var/log/elasticsearch
network.host: 0.0.0.0
http.port: 9200
discovery.type: single-node

# Disable security for internal/lab use (enable in production)
xpack.security.enabled: false
xpack.security.enrollment.enabled: false
```

### JVM Heap — `/etc/elasticsearch/jvm.options.d/heap.options`

```
-Xms4g
-Xmx4g
```

```bash
sudo systemctl enable --now elasticsearch
# Verify
curl -s http://localhost:9200/_cluster/health?pretty
```

### Logstash Installation and Pipeline

```bash
sudo apt install -y logstash
```

Pipeline config — `/etc/logstash/conf.d/syslog.conf`:

```ruby
input {
  beats {
    port => 5044
  }
}

filter {
  if [fields][log_type] == "syslog" {
    grok {
      match => { "message" => "%{SYSLOGTIMESTAMP:syslog_timestamp} %{SYSLOGHOST:hostname} %{DATA:program}(?:\[%{POSINT:pid}\])?: %{GREEDYDATA:log_message}" }
    }
    date {
      match => [ "syslog_timestamp", "MMM  d HH:mm:ss", "MMM dd HH:mm:ss" ]
    }
  }
}

output {
  elasticsearch {
    hosts => ["http://localhost:9200"]
    index => "syslog-%{+YYYY.MM.dd}"
  }
}
```

```bash
sudo systemctl enable --now logstash
```

### Kibana

```bash
sudo apt install -y kibana
```

Config — `/etc/kibana/kibana.yml`:

```yaml
server.port: 5601
server.host: "0.0.0.0"
elasticsearch.hosts: ["http://localhost:9200"]
```

```bash
sudo systemctl enable --now kibana
sudo ufw allow 5601/tcp
```

### Filebeat (Log Shipper)

```bash
sudo apt install -y filebeat
```

Config — `/etc/filebeat/filebeat.yml`:

```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/syslog
      - /var/log/auth.log
    fields:
      log_type: syslog

  - type: log
    enabled: true
    paths:
      - /var/log/nginx/access.log
    fields:
      log_type: nginx-access

output.logstash:
  hosts: ["localhost:5044"]
```

```bash
sudo filebeat modules enable system
sudo filebeat setup --pipelines --modules system
sudo systemctl enable --now filebeat
```

### Index Lifecycle Management (ILM) Basics

```bash
# Create an ILM policy via API
curl -s -X PUT "http://localhost:9200/_ilm/policy/logs-cleanup" \
  -H "Content-Type: application/json" -d '{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_age": "7d",
            "max_primary_shard_size": "25gb"
          }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
```

<HARD-RULE>
Elasticsearch disk watermarks: by default, Elasticsearch stops allocating shards when disk usage reaches 85% (low watermark) and relocates shards at 90% (high watermark). Monitor disk with `curl localhost:9200/_cat/allocation?v`. Set up ILM policies and alerts before you run out of space.
</HARD-RULE>

---

## 7. rsyslog

### Remote Syslog Collection (Central Server)

Add to `/etc/rsyslog.d/10-remote.conf` on the central server:

```bash
# UDP reception (traditional, faster, no delivery guarantee)
module(load="imudp")
input(type="imudp" port="514")

# TCP reception (reliable delivery)
module(load="imtcp")
input(type="imtcp" port="514")
```

### Template-Based File Output

```bash
# /etc/rsyslog.d/20-remote-hosts.conf
# Separate log files per remote host and program
template(name="RemoteHostLog" type="string"
  string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")

if $fromhost-ip != '127.0.0.1' then {
  action(type="omfile" dynaFile="RemoteHostLog")
  stop
}
```

```bash
sudo mkdir -p /var/log/remote
sudo systemctl restart rsyslog
sudo ufw allow 514/tcp
sudo ufw allow 514/udp
```

### Forwarding to Central Server (Client)

Add to `/etc/rsyslog.d/50-forward.conf` on each client:

```bash
# Forward all logs via TCP (@@) — use single @ for UDP
*.* @@logserver.example.com:514

# Forward only auth logs
auth,authpriv.* @@logserver.example.com:514

# Queue for reliability during network outage
action(
  type="omfwd"
  target="logserver.example.com"
  port="514"
  protocol="tcp"
  queue.type="LinkedList"
  queue.size="10000"
  queue.filename="fwd_to_central"
  queue.saveonshutdown="on"
  action.resumeRetryCount="-1"
)
```

```bash
sudo systemctl restart rsyslog
```

### TCP vs UDP

| Factor | UDP (single @) | TCP (double @@) |
|---|---|---|
| Delivery | Best-effort, may drop | Reliable, ordered |
| Overhead | Lower | Slightly higher |
| Use case | High-volume, non-critical | Audit/compliance logs |
| Recommendation | Avoid for important logs | **Preferred default** |

---

## 8. Health Check Patterns

### Systemd Watchdog

Add watchdog support to a custom service:

```ini
# /etc/systemd/system/myapp.service — add to [Service]
WatchdogSec=30
# The application must call sd_notify("WATCHDOG=1") within this interval.
# If using a wrapper script or app that doesn't support sd_notify:
Type=notify
NotifyAccess=all
```

For apps that do not support sd_notify natively, use a wrapper:

```bash
# /usr/local/bin/watchdog-wrapper.sh
#!/bin/bash
/opt/myapp/bin/server &
APP_PID=$!
while kill -0 "$APP_PID" 2>/dev/null; do
    if curl -sf http://localhost:8080/health > /dev/null; then
        systemd-notify WATCHDOG=1
    fi
    sleep 10
done
exit 1
```

### Custom Health Check Script with Systemd Timer

Service — `/etc/systemd/system/health-check.service`:

```ini
[Unit]
Description=System health check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/health-check.sh
```

Timer — `/etc/systemd/system/health-check.timer`:

```ini
[Unit]
Description=Run health check every 5 minutes

[Timer]
OnBootSec=60
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

Script — `/usr/local/bin/health-check.sh`:

```bash
#!/bin/bash
set -euo pipefail

LOG_TAG="health-check"
ALERT_FILE="/var/lib/node_exporter/textfile_collector/health.prom"

check_passed=1

# Check disk space (alert if any mount > 85%)
while read -r usage mount; do
    pct="${usage%\%}"
    if [ "$pct" -gt 85 ]; then
        logger -t "$LOG_TAG" "WARN: ${mount} is at ${usage}"
        check_passed=0
    fi
done < <(df -h --output=pcent,target | tail -n+2 | grep -v tmpfs)

# Check systemd failed units
FAILED=$(systemctl --failed --no-legend | wc -l)
if [ "$FAILED" -gt 0 ]; then
    logger -t "$LOG_TAG" "WARN: ${FAILED} failed systemd units"
    check_passed=0
fi

# Check critical services
for svc in prometheus node_exporter grafana-server; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        : # running
    elif systemctl list-unit-files "$svc.service" | grep -q "$svc"; then
        logger -t "$LOG_TAG" "CRIT: ${svc} is not running"
        check_passed=0
    fi
done

# Check memory (alert if available < 10%)
MEM_AVAIL=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
MEM_TOTAL=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
MEM_PCT=$(( (MEM_TOTAL - MEM_AVAIL) * 100 / MEM_TOTAL ))
if [ "$MEM_PCT" -gt 90 ]; then
    logger -t "$LOG_TAG" "WARN: Memory usage at ${MEM_PCT}%"
    check_passed=0
fi

# Export result as Prometheus metric
echo "node_health_check_passed ${check_passed}" > "${ALERT_FILE}.tmp"
echo "node_health_check_timestamp $(date +%s)" >> "${ALERT_FILE}.tmp"
mv "${ALERT_FILE}.tmp" "$ALERT_FILE"

logger -t "$LOG_TAG" "Health check completed — passed=${check_passed}"
```

```bash
sudo chmod +x /usr/local/bin/health-check.sh
sudo systemctl daemon-reload
sudo systemctl enable --now health-check.timer
```

### Uptime Monitoring with Blackbox Exporter

```bash
BB_VER="0.28.0"   # verified current 2026-06-10
cd /tmp
curl -LO "https://github.com/prometheus/blackbox_exporter/releases/download/v${BB_VER}/blackbox_exporter-${BB_VER}.linux-amd64.tar.gz"
tar xzf "blackbox_exporter-${BB_VER}.linux-amd64.tar.gz"
sudo cp "blackbox_exporter-${BB_VER}.linux-amd64/blackbox_exporter" /usr/local/bin/
```

Blackbox config — `/etc/blackbox_exporter/blackbox.yml`:

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      follow_redirects: true
  icmp:
    prober: icmp
    timeout: 5s
  tcp_connect:
    prober: tcp
    timeout: 5s
```

Prometheus scrape config for blackbox:

```yaml
# Add to scrape_configs in prometheus.yml
  - job_name: "blackbox-http"
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://app.example.com
          - https://grafana.example.com:3000
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9115
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Alerting on every metric without baseline tuning | Alert fatigue — 50 alerts per day means operators ignore all of them; real incidents get missed | Establish baselines for 2 weeks; set alerts only for actionable anomalies; review and tune alert thresholds monthly |
| No persistent storage for Prometheus | Prometheus restart loses all metric history; cannot do capacity planning or trend analysis | Configure `--storage.tsdb.path` on persistent volume; set retention with `--storage.tsdb.retention.time` |
| Monitoring system metrics only (CPU, RAM, disk) | Server metrics look healthy while application returns errors; users report outage before monitoring detects it | Add application health checks, HTTP status code monitoring, response latency tracking alongside infrastructure metrics |
| Grafana dashboards without variable templates | One dashboard per server/service; 50 servers = 50 dashboards to maintain; inconsistent layouts | Use Grafana template variables (instance, job, namespace); one dashboard serves all instances with dropdown selection |
| Not forwarding logs to central system | Logs only on individual servers; cross-service debugging requires SSH to each server; compliance audits fail | Deploy Alloy→Loki or Filebeat→ELK; forward all application and system logs; retain per compliance requirements |
| Fresh installs still shipping logs with Promtail | Promtail is EOL since 2026-03-02 — no updates, no security fixes; new deployments start life unsupported | Use Grafana Alloy for all new installs; migrate existing Promtail configs with `alloy convert --source-format=promtail` |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (packages, users, firewall, disk) | `ubuntu-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `ubuntu-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `ubuntu-databases` |
| Docker / containers | `ubuntu-docker-host` |
| File sharing (NFS, Samba, ZFS) | `ubuntu-file-storage` |
| DNS, DHCP, NTP | `ubuntu-network-infra` |
| NVIDIA GPU, Ollama, CUDA | `ubuntu-ollama-nvidia` |
