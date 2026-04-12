# Prometheus, node_exporter, Grafana, and Alertmanager

Reference file for the `rhel-monitoring` skill. Covers Prometheus installation and configuration, node_exporter, Grafana dashboards, and Alertmanager setup.

## 1. Prometheus

### Installation (Binary Method)

```bash
# Create system user
sudo useradd -r -s /sbin/nologin prometheus

# Create directories
sudo mkdir -p /etc/prometheus/rules /var/lib/prometheus
sudo chown prometheus:prometheus /var/lib/prometheus

# Download and install (check https://prometheus.io/download/ for latest)
PROM_VER="2.53.3"
cd /tmp
curl -LO "https://github.com/prometheus/prometheus/releases/download/v${PROM_VER}/prometheus-${PROM_VER}.linux-amd64.tar.gz"
tar xzf "prometheus-${PROM_VER}.linux-amd64.tar.gz"
sudo cp "prometheus-${PROM_VER}.linux-amd64"/{prometheus,promtool} /usr/local/bin/
sudo cp -r "prometheus-${PROM_VER}.linux-amd64"/{consoles,console_libraries} /etc/prometheus/
sudo chown -R prometheus:prometheus /etc/prometheus
```

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

# Firewall
sudo firewall-cmd --permanent --add-port=9090/tcp
sudo firewall-cmd --reload

# SELinux — allow Prometheus to bind to its port and read config
# If you see AVC denials, create a custom policy:
# sudo ausearch -m AVC -ts recent | audit2allow -M prometheus-custom
# sudo semodule -i prometheus-custom.pp
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
sudo useradd -r -s /sbin/nologin node_exporter

NODE_VER="1.8.2"
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

# Firewall — restrict to monitoring network
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="9100" protocol="tcp" accept'
sudo firewall-cmd --reload
```

### Custom Textfile Collector Example

```bash
cat <<'SCRIPT' | sudo tee /usr/local/bin/custom-metrics.sh
#!/bin/bash
OUTPUT="/var/lib/node_exporter/textfile_collector/custom.prom"
# Pending dnf updates
UPDATES=$(dnf check-update --quiet 2>/dev/null | grep -c '^\S')
echo "dnf_upgradable_packages ${UPDATES}" > "${OUTPUT}.tmp"
# Reboot required (check for kernel mismatch)
RUNNING=$(uname -r)
LATEST=$(rpm -q --last kernel | head -1 | awk '{print $1}' | sed 's/kernel-//')
REBOOT=0
[ "$RUNNING" != "$LATEST" ] && REBOOT=1
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
cat <<'EOF' | sudo tee /etc/yum.repos.d/grafana.repo
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
EOF

sudo dnf install -y grafana
sudo systemctl enable --now grafana-server
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload
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
  - name: PCP Redis
    type: redis-datasource
    access: proxy
    url: http://localhost:44322
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
sudo useradd -r -s /sbin/nologin alertmanager
AM_VER="0.27.0"
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
sudo firewall-cmd --permanent --add-port=9093/tcp
sudo firewall-cmd --reload
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
```

### Manage Silences

```bash
amtool --alertmanager.url=http://localhost:9093 silence add \
  alertname="HighCPU" instance="10.0.1.51:9100" \
  --comment="Maintenance window" --duration=2h

amtool --alertmanager.url=http://localhost:9093 silence query
amtool --alertmanager.url=http://localhost:9093 silence expire <silence-id>
```

---

## 5. Loki + Promtail

### Loki Installation

```bash
sudo useradd -r -s /sbin/nologin loki
LOKI_VER="3.1.1"
cd /tmp
curl -LO "https://github.com/grafana/loki/releases/download/v${LOKI_VER}/loki-linux-amd64.zip"
sudo dnf install -y unzip
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

### Promtail Installation and Config

```bash
cd /tmp
curl -LO "https://github.com/grafana/loki/releases/download/v${LOKI_VER}/promtail-linux-amd64.zip"
unzip promtail-linux-amd64.zip
sudo cp promtail-linux-amd64 /usr/local/bin/promtail
sudo chmod +x /usr/local/bin/promtail
sudo mkdir -p /etc/promtail
```

### Promtail Config — `/etc/promtail/promtail.yml`

RHEL 9 uses `/var/log/messages` (not `/var/log/syslog`) and `/var/log/secure` (not `/var/log/auth.log`).

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

  # RHEL system messages
  - job_name: messages
    static_configs:
      - targets: [localhost]
        labels:
          job: messages
          __path__: /var/log/messages

  # RHEL authentication log
  - job_name: secure
    static_configs:
      - targets: [localhost]
        labels:
          job: secure
          __path__: /var/log/secure

  # Audit log
  - job_name: audit
    static_configs:
      - targets: [localhost]
        labels:
          job: audit
          __path__: /var/log/audit/audit.log

  # Application logs (wildcard)
  - job_name: app-logs
    static_configs:
      - targets: [localhost]
        labels:
          job: app
          __path__: /var/log/myapp/*.log
```

### Promtail Systemd Service — `/etc/systemd/system/promtail.service`

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

Note: Promtail runs as root to read journal, `/var/log/secure`, and audit logs.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now loki promtail
sudo firewall-cmd --permanent --add-port=3100/tcp
sudo firewall-cmd --reload
```

### LogQL Query Examples

```
# All logs from a specific unit
{unit="nginx.service"}

# Filter RHEL messages log
{job="messages"} |= "error"

# SSH failures from /var/log/secure
{job="secure"} |= "Failed password"
{job="secure"} |~ "Failed|Invalid"

# SELinux denials from audit log
{job="audit"} |= "avc:  denied"

# Rate of errors (logs per second over 5m)
rate({job="messages"} |= "error" [5m])

# Top source IPs for SSH failures
topk(10, count_over_time({job="secure"} |= "Failed password" [1h]))

# JSON log parsing
{job="app"} | json | status >= 500
```

---

