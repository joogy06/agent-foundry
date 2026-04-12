# Loki, PCP, ELK Stack, rsyslog, Cockpit, and Health Checks

Reference file for the `rhel-monitoring` skill. Covers Loki + Promtail, Performance Co-Pilot (PCP), ELK Stack, rsyslog, Cockpit monitoring, health check patterns, and SELinux contexts.

## 6. Performance Co-Pilot (PCP)

PCP is Red Hat's native performance monitoring toolkit, included in RHEL repositories. It provides lightweight, extensible, real-time and historical metrics collection.

### Installation

```bash
# Core PCP with sensible defaults
sudo dnf install -y pcp pcp-zeroconf

# Start and enable
sudo systemctl enable --now pmcd pmlogger

# Verify
pcp
pminfo -f kernel.all.load
```

`pcp-zeroconf` automatically configures `pmcd` (collector daemon) and `pmlogger` (archiver) with sane defaults, logging to `/var/log/pcp/pmlogger/$(hostname)`.

### Key PCP Commands

```bash
# System summary (like top)
pmstat
pmstat -s 10                           # 10 samples

# Detailed metrics browser
pminfo                                 # list all available metrics
pminfo -dt kernel.all.load             # describe metric with type info
pminfo -f mem.util.available           # fetch current value
pminfo -f disk.dev.read_bytes          # disk I/O per device

# Report tool (flexible output like sar)
pmrep kernel.all.load -s 5 -t 2       # 5 samples, 2-second interval
pmrep -g disk.dev.read disk.dev.write  # disk I/O with gnuplot-style headers
pmrep -o csv -F /tmp/metrics.csv \
  kernel.all.load mem.util.available   # export to CSV

# Interactive process-level view
pmval kernel.percpu.cpu.user           # per-CPU user time
pmdumplog -l /var/log/pcp/pmlogger/$(hostname)/latest  # inspect archive
```

### PCP Archives and Historical Data

```bash
# Replay recorded data
pmrep -a /var/log/pcp/pmlogger/$(hostname)/latest \
  -S "-1hour" -T "-30min" \
  kernel.all.load mem.util.available

# Custom pmlogger config for application-specific metrics
# /etc/pcp/pmlogger/config.d/myapp.config
log mandatory on 10sec {
    kernel.all.load
    mem.util.available
    mem.util.used
    disk.all.read_bytes
    disk.all.write_bytes
    network.interface.in.bytes
    network.interface.out.bytes
}

# Adjust archive retention (default is 14 days)
# Edit /etc/pcp/pmlogger/control.d/local
# The -c flag points to config, -r rotates archives
```

### PMDA Agents (Extend Metrics Collection)

```bash
# List installed PMDAs
pminfo -L 2>&1 | head

# Install useful PMDAs
sudo dnf install -y pcp-pmda-dm        # device-mapper / LVM
sudo dnf install -y pcp-pmda-postfix   # Postfix mail
sudo dnf install -y pcp-pmda-openmetrics  # scrape Prometheus endpoints

# Activate a PMDA
cd /var/lib/pcp/pmdas/dm
sudo ./Install

cd /var/lib/pcp/pmdas/openmetrics
sudo ./Install
# Configure openmetrics PMDA to scrape node_exporter
echo "http://localhost:9100/metrics" | sudo tee /var/lib/pcp/pmdas/openmetrics/config.d/node_exporter.url
sudo systemctl restart pmcd
```

### Grafana PCP Plugin

```bash
# Install the PCP Grafana plugin
sudo dnf install -y pcp-gui grafana-pcp

# Enable the pmproxy API for Grafana
sudo systemctl enable --now pmproxy

# Firewall for pmproxy
sudo firewall-cmd --permanent --add-port=44322/tcp
sudo firewall-cmd --reload
```

After installing, enable the "Performance Co-Pilot" datasource in Grafana. PCP provides built-in dashboards: PCP Vector (live), PCP Redis (historical), and PCP Checklist (best practices).

### PCP vs Prometheus

| Factor | PCP | Prometheus |
|---|---|---|
| Origin | Red Hat native, in RHEL repos | CNCF, binary install |
| Collection | Agent-based (pmcd + PMDAs) | Pull-based scraping |
| Storage | Log-based archives | TSDB |
| Granularity | Sub-second capable | 15s typical minimum |
| Ecosystem | Smaller, RHEL-focused | Huge community |
| Best for | Deep OS-level perf analysis | Multi-host fleet monitoring |
| Recommendation | Use both — PCP for deep dives, Prometheus for fleet |

---

## 7. ELK Stack (Elasticsearch, Logstash, Kibana)

<HARD-RULE>
Elasticsearch JVM heap: set to exactly 50% of available RAM, never exceed 32 GB. Below 4 GB total RAM the JVM will be unstable. For a dedicated node, 8 GB RAM minimum is strongly recommended. Set both -Xms and -Xmx to the same value to avoid resize pauses.
</HARD-RULE>

### Elasticsearch Installation

```bash
sudo rpm --import https://artifacts.elastic.co/GPG-KEY-elasticsearch

cat <<'EOF' | sudo tee /etc/yum.repos.d/elasticsearch.repo
[elasticsearch-8.x]
name=Elasticsearch repository for 8.x packages
baseurl=https://artifacts.elastic.co/packages/8.x/yum
gpgcheck=1
gpgkey=https://artifacts.elastic.co/GPG-KEY-elasticsearch
enabled=1
autorefresh=1
type=rpm-md
EOF

sudo dnf install -y elasticsearch
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
sudo firewall-cmd --permanent --add-port=9200/tcp
sudo firewall-cmd --reload

# Verify
curl -s http://localhost:9200/_cluster/health?pretty
```

### Logstash Installation and Pipeline

```bash
sudo dnf install -y logstash
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
sudo dnf install -y kibana
```

Config — `/etc/kibana/kibana.yml`:

```yaml
server.port: 5601
server.host: "0.0.0.0"
elasticsearch.hosts: ["http://localhost:9200"]
```

```bash
sudo systemctl enable --now kibana
sudo firewall-cmd --permanent --add-port=5601/tcp
sudo firewall-cmd --reload
```

### Filebeat (Log Shipper)

```bash
sudo dnf install -y filebeat
```

Config — `/etc/filebeat/filebeat.yml`:

```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/messages
      - /var/log/secure
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

<HARD-RULE>
Elasticsearch disk watermarks: by default, Elasticsearch stops allocating shards when disk usage reaches 85% (low watermark) and relocates shards at 90% (high watermark). Monitor disk with `curl localhost:9200/_cat/allocation?v`. Set up ILM policies and alerts before you run out of space.
</HARD-RULE>

---

## 8. rsyslog (RHEL Default)

rsyslog is the default system logger on RHEL 9. Main config: `/etc/rsyslog.conf`, drop-ins: `/etc/rsyslog.d/*.conf`.

### Default RHEL Log Paths

| Log file | Content |
|---|---|
| `/var/log/messages` | General system messages (equivalent of Ubuntu's syslog) |
| `/var/log/secure` | Authentication and authorization (equivalent of auth.log) |
| `/var/log/maillog` | Mail subsystem |
| `/var/log/cron` | Cron job output |
| `/var/log/boot.log` | Boot messages |
| `/var/log/audit/audit.log` | SELinux and audit events |

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
sudo firewall-cmd --permanent --add-port=514/tcp
sudo firewall-cmd --permanent --add-port=514/udp
sudo firewall-cmd --reload

# SELinux — allow rsyslog to listen on the network
sudo setsebool -P nis_enabled 1
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

### Systemd Journal Management

```bash
journalctl -u <service>
journalctl -u <service> -f               # follow live
journalctl -u <service> --since "1h ago"
journalctl -u <service> -p err            # priority filter
journalctl -b                             # current boot
journalctl -b -1                          # previous boot
journalctl --disk-usage

# Persist logs across reboots (default on RHEL 9 if /var/log/journal exists)
sudo mkdir -p /var/log/journal

# /etc/systemd/journald.conf
SystemMaxUse=500M
MaxRetentionSec=30day

# Vacuum
sudo journalctl --vacuum-size=200M
sudo journalctl --vacuum-time=7d
```

---

## 9. Cockpit Monitoring

Cockpit is RHEL's built-in web console with integrated system monitoring.

```bash
# Install (often pre-installed on RHEL 9)
sudo dnf install -y cockpit cockpit-pcp
sudo systemctl enable --now cockpit.socket
sudo firewall-cmd --permanent --add-service=cockpit
sudo firewall-cmd --reload

# Access at https://<server-ip>:9090
```

The `cockpit-pcp` package adds historical performance graphs to the Cockpit dashboard, backed by PCP archives. It shows CPU, memory, disk I/O, and network charts without needing Grafana.

---

## 10. Health Check Patterns

### Systemd Watchdog

Add watchdog support to a custom service:

```ini
# /etc/systemd/system/myapp.service — add to [Service]
WatchdogSec=30
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
for svc in prometheus node_exporter grafana-server pmcd pmlogger; do
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

---

## SELinux Contexts for Monitoring Services

When running monitoring daemons from `/usr/local/bin`, SELinux may block execution or network binding.

```bash
# Check for denials
sudo ausearch -m AVC --start recent
sudo sealert -a /var/log/audit/audit.log

# Common fixes for monitoring services
# Allow Prometheus/Grafana to bind to their ports
sudo semanage port -a -t http_port_t -p tcp 9090   # Prometheus
sudo semanage port -a -t http_port_t -p tcp 3000   # Grafana
sudo semanage port -a -t http_port_t -p tcp 9093   # Alertmanager
sudo semanage port -a -t http_port_t -p tcp 3100   # Loki

# Set file contexts for binaries installed to /usr/local/bin
sudo semanage fcontext -a -t bin_t "/usr/local/bin/prometheus"
sudo semanage fcontext -a -t bin_t "/usr/local/bin/node_exporter"
sudo semanage fcontext -a -t bin_t "/usr/local/bin/alertmanager"
sudo semanage fcontext -a -t bin_t "/usr/local/bin/loki"
sudo semanage fcontext -a -t bin_t "/usr/local/bin/promtail"
sudo restorecon -v /usr/local/bin/{prometheus,node_exporter,alertmanager,loki,promtail}

# If custom policies are needed, generate from denials
sudo ausearch -m AVC -ts recent | audit2allow -M mymonitoring
sudo semodule -i mymonitoring.pp
```

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (packages, users, firewall, disk) | `rhel-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Docker / Podman containers | `rhel-docker-host` |
| File sharing (NFS, Samba, Stratis) | `rhel-file-storage` |
| DNS, DHCP, NTP | `rhel-network-infra` |
| NVIDIA GPU, Ollama, CUDA | `rhel-ollama-nvidia` |
