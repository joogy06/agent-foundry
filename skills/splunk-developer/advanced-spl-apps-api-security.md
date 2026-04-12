# Advanced SPL, App Development, REST API, and Security

Reference file for the `splunk-developer` skill. Covers advanced SPL patterns, app development, REST API usage, and security/compliance searches.

## 10. App Development

### App Directory Structure

```
$SPLUNK_HOME/etc/apps/my_custom_app/
├── app.conf                         # App metadata
├── default/                         # Shipped defaults (version-controlled)
│   ├── app.conf
│   ├── data/
│   │   └── ui/
│   │       ├── nav/
│   │       │   └── default.xml      # Navigation menu
│   │       └── views/
│   │           ├── dashboard1.xml   # Dashboard definitions
│   │           └── dashboard2.xml
│   ├── eventtypes.conf
│   ├── macros.conf
│   ├── props.conf
│   ├── savedsearches.conf
│   ├── tags.conf
│   └── transforms.conf
├── local/                           # User overrides (not version-controlled)
├── lookups/                         # CSV lookup files
│   └── asset_inventory.csv
├── metadata/
│   ├── default.meta                 # Permissions for shipped objects
│   └── local.meta
├── bin/                             # Scripts, custom commands
│   └── my_custom_command.py
├── appserver/
│   └── static/                      # Custom JS, CSS, images
│       ├── appIcon.png              # 36x36 app icon
│       └── screenshot.png           # App screenshot
├── README/                          # REST endpoint spec files
│   └── inputs.conf.spec
└── static/
    └── appIcon_2x.png              # 72x72 retina icon
```

### app.conf

```ini
[install]
is_configured = true
build = 1

[ui]
is_visible = true
label = My Custom App

[launcher]
author = YourName
description = Custom Splunk app for web operations monitoring
version = 1.0.0

[package]
id = my_custom_app
check_for_updates = false
```

### default.meta

```ini
[]
access = read : [ * ], write : [ admin, power ]
export = system

[views]
access = read : [ * ], write : [ admin ]
export = system

[savedsearches]
access = read : [ * ], write : [ admin, power ]
export = system
```

### Navigation (default.xml)

```xml
<nav search_view="search" color="#65A637">
  <view name="overview" default="true" />
  <view name="error_analysis" />
  <view name="performance" />
  <collection label="Reports">
    <saved name="Daily Error Summary" />
    <saved name="Top Slow Endpoints" />
  </collection>
  <collection label="Settings">
    <view name="inputs" />
    <a href="/manager/my_custom_app/data/lookup-table-files" target="_blank">Lookups</a>
  </collection>
</nav>
```

### Custom Search Command (Python)

`bin/my_custom_command.py`:

```python
#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from splunklib.searchcommands import dispatch, StreamingCommand, Configuration, Option, validators

@Configuration()
class MyCustomCommand(StreamingCommand):
    threshold = Option(require=False, validate=validators.Float(), default=100.0)

    def stream(self, records):
        for record in records:
            value = float(record.get("response_time", 0))
            record["is_above_threshold"] = "true" if value > self.threshold else "false"
            record["normalized_rt"] = round(value / self.threshold, 3)
            yield record

dispatch(MyCustomCommand, sys.argv, sys.stdin, sys.stdout, __name__)
```

`default/commands.conf`:

```ini
[mycustomcommand]
filename = my_custom_command.py
chunked = true
python.version = python3
```

Usage in SPL: `index=web_logs sourcetype=access_combined | mycustomcommand threshold=500`

### App Packaging

```bash
# Validate app with Splunk AppInspect
pip install splunk-appinspect
splunk-appinspect inspect my_custom_app/ --mode precert

# Package using slim (Splunk packaging tool)
slim package my_custom_app/

# Or manually tar (exclude local/ directory)
cd $SPLUNK_HOME/etc/apps
COPYFILE_DISABLE=1 tar czf my_custom_app.tar.gz \
  --exclude='my_custom_app/local' \
  --exclude='my_custom_app/local.meta' \
  my_custom_app/
```

---

## 11. REST API

### Authentication

```bash
# Session-based authentication (returns session key)
curl -k https://splunk.example.com:8089/services/auth/login \
  -d username=admin -d password=changeme

# Use session key in subsequent requests
curl -k -H "Authorization: Splunk <session_key>" \
  https://splunk.example.com:8089/services/server/info

# Bearer token (Splunk 7.3+ with token auth enabled)
curl -k -H "Authorization: Bearer <token>" \
  https://splunk.example.com:8089/services/server/info
```

### Search Job Lifecycle

```bash
# Create search job
curl -k -H "Authorization: Splunk <session_key>" \
  https://splunk.example.com:8089/services/search/jobs \
  -d search="search index=web_logs sourcetype=access_combined earliest=-1h | stats count by status" \
  -d earliest_time="-1h" \
  -d latest_time="now" \
  -d output_mode=json

# Returns: {"sid": "<search_id>"}

# Check job status
curl -k -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/services/search/jobs/<search_id>?output_mode=json" \
  | python3 -m json.tool | grep dispatchState

# Get results (when dispatchState=DONE)
curl -k -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/services/search/jobs/<search_id>/results?output_mode=json&count=0"

# One-shot search (synchronous — blocks until complete)
curl -k -H "Authorization: Splunk <session_key>" \
  https://splunk.example.com:8089/services/search/jobs/export \
  -d search="search index=web_logs sourcetype=access_combined earliest=-5m | stats count by host" \
  -d output_mode=json \
  -d earliest_time="-5m" \
  -d latest_time="now"
```

### KV Store CRUD

```bash
# List collections
curl -k -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/servicesNS/nobody/my_custom_app/storage/collections/config?output_mode=json"

# Insert record
curl -k -H "Authorization: Splunk <session_key>" \
  -H "Content-Type: application/json" \
  https://splunk.example.com:8089/servicesNS/nobody/my_custom_app/storage/collections/data/kv_app_config \
  -d '{"key": "max_retries", "value": "5", "updated_by": "admin"}'

# Query records (with filter)
curl -k -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/servicesNS/nobody/my_custom_app/storage/collections/data/kv_app_config?output_mode=json&query=%7B%22key%22%3A%22max_retries%22%7D"

# Update record by _key
curl -k -X POST -H "Authorization: Splunk <session_key>" \
  -H "Content-Type: application/json" \
  "https://splunk.example.com:8089/servicesNS/nobody/my_custom_app/storage/collections/data/kv_app_config/<_key_value>" \
  -d '{"key": "max_retries", "value": "10", "updated_by": "admin"}'

# Delete record
curl -k -X DELETE -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/servicesNS/nobody/my_custom_app/storage/collections/data/kv_app_config/<_key_value>"
```

### Python SDK (splunklib)

```python
import splunklib.client as client
import splunklib.results as results

# Connect
service = client.connect(
    host="splunk.example.com",
    port=8089,
    username="admin",
    password="changeme",
    scheme="https"
)

# Run a one-shot search
query = """search index=web_logs sourcetype=access_combined earliest=-1h
| stats count by host, status"""
result_stream = service.jobs.oneshot(query, output_mode="json", count=0)

for result in results.JSONResultsReader(result_stream):
    if isinstance(result, dict):
        print(f"Host: {result['host']}, Status: {result['status']}, Count: {result['count']}")

# Run an async search job
job = service.jobs.create(query, earliest_time="-1h", latest_time="now")
while not job.is_done():
    import time
    time.sleep(1)

for result in results.JSONResultsReader(job.results(output_mode="json", count=0)):
    if isinstance(result, dict):
        print(result)

# Manage saved searches
for saved_search in service.saved_searches:
    print(f"{saved_search.name}: {saved_search['search']}")

# KV Store operations
collection = service.kvstore["kv_app_config"]
collection.data.insert({"key": "timeout", "value": "30"})
records = collection.data.query()
```

### Saved Search Management

```bash
# List saved searches
curl -k -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/servicesNS/-/-/saved/searches?output_mode=json&count=0"

# Create a saved search
curl -k -H "Authorization: Splunk <session_key>" \
  https://splunk.example.com:8089/servicesNS/admin/my_custom_app/saved/searches \
  -d name="High Error Rate" \
  -d search="index=web_logs sourcetype=access_combined earliest=-5m | stats count(eval(status>=500)) AS errors, count AS total | eval rate=round(errors/total*100,2) | where rate>5" \
  -d cron_schedule="*/5 * * * *" \
  -d is_scheduled=1 \
  -d dispatch.earliest_time="-5m" \
  -d dispatch.latest_time="now" \
  -d actions="email" \
  -d "action.email.to=ops@example.com"

# Update a saved search
curl -k -X POST -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/servicesNS/admin/my_custom_app/saved/searches/High%20Error%20Rate" \
  -d cron_schedule="*/10 * * * *"

# Delete a saved search
curl -k -X DELETE -H "Authorization: Splunk <session_key>" \
  "https://splunk.example.com:8089/servicesNS/admin/my_custom_app/saved/searches/High%20Error%20Rate"
```

---

## 12. Security & Compliance

### Role-Based Access Control

**authorize.conf:**

```ini
[role_soc_analyst]
# Index access
srchIndexesAllowed = main;web_logs;app_logs;auth_logs;os_logs
srchIndexesDefault = main
# Search restrictions
srchFilter = (index=web_logs OR index=app_logs OR index=auth_logs OR index=os_logs)
srchDiskQuota = 500
srchJobsQuota = 10
rtSrchJobsQuota = 3
# Capabilities
importRoles = user
srchMaxTime = 3600
# Data model acceleration access
cumulativeRTSrchJobsQuota = 5
cumulativeSrchJobsQuota = 20

[role_app_developer]
srchIndexesAllowed = app_logs;web_logs
srchIndexesDefault = app_logs
srchFilter = (index=app_logs OR index=web_logs)
importRoles = power
srchMaxTime = 600

[role_executive]
srchIndexesAllowed = summary
srchIndexesDefault = summary
importRoles = user
srchMaxTime = 300
```

### Splunk Enterprise Security (ES) — Correlation Searches

```spl
# Brute force detection correlation search
index=auth_logs sourcetype=linux_secure "Failed password" earliest=-5m
| stats count AS failure_count, dc(user) AS targeted_users, values(user) AS users by src_ip
| where failure_count > 20 OR targeted_users > 5
| eval severity=case(
    failure_count > 100, "critical",
    failure_count > 50, "high",
    failure_count > 20, "medium",
    1=1, "low")

# Lateral movement detection
index=auth_logs sourcetype=wineventlog EventCode=4624 Logon_Type=3 earliest=-1h
| stats dc(dest) AS unique_hosts, values(dest) AS hosts by src_ip, user
| where unique_hosts > 5
| eval severity=if(unique_hosts > 10, "critical", "high")

# Data exfiltration detection
index=proxy_logs sourcetype=squid earliest=-1h
| stats sum(bytes_out) AS total_bytes_out by src_ip, user
| eval mb_out=round(total_bytes_out/1048576, 2)
| where mb_out > 500
| eval severity=case(mb_out > 2000, "critical", mb_out > 1000, "high", 1=1, "medium")
```

### Notable Events

```spl
# Create notable event from correlation search (ES adaptive response action)
index=auth_logs sourcetype=linux_secure "Failed password" earliest=-5m
| stats count by src_ip, user
| where count > 20
| sendalert notable param.security_domain="access"
  param.severity="high"
  param.rule_name="Brute Force Attempt"
  param.rule_title="Brute Force: $result.count$ failures from $result.src_ip$"
  param.rule_description="Detected $result.count$ failed login attempts from $result.src_ip$ targeting user $result.user$ in the last 5 minutes."
  param.src="$result.src_ip$"
  param.dest=""
  param.user="$result.user$"
```

### Risk-Based Alerting (RBA)

```spl
# Assign risk score to events instead of direct alerts
# This reduces alert fatigue by aggregating risk before alerting

# Step 1: Risk-generating searches (multiple low-confidence signals)
index=auth_logs sourcetype=linux_secure "Failed password" earliest=-5m
| stats count by src_ip
| where count > 5
| eval risk_score=count * 2
| eval risk_object=src_ip, risk_object_type="system"
| eval risk_message="Failed login attempts: ".count." from ".src_ip
| collect index=risk

index=web_logs sourcetype=access_combined status=403 earliest=-5m
| stats count by clientip
| where count > 10
| eval risk_score=count
| eval risk_object=clientip, risk_object_type="system"
| eval risk_message="Forbidden access attempts: ".count." from ".clientip
| collect index=risk

# Step 2: Risk aggregation alert (single high-confidence alert)
index=risk earliest=-1h
| stats sum(risk_score) AS total_risk, values(risk_message) AS signals, dc(source) AS signal_count by risk_object
| where total_risk > 100 AND signal_count > 2
| sort - total_risk
```

### CIM Mapping for Security Use Cases

Common CIM data models for security:

| Data Model | Use Case | Key Fields |
|---|---|---|
| Authentication | Login success/failure | action, app, src, dest, user |
| Network Traffic | Firewall, IDS/IPS | action, src_ip, dest_ip, dest_port, transport, bytes |
| Web | Proxy, WAF | action, src, dest, url, status, http_method |
| Endpoint | EDR, AV | action, dest, file_name, file_hash, process_name, user |
| Change | Configuration changes | action, object, object_category, user, command |

```ini
# props.conf — CIM Authentication mapping
[linux_secure]
FIELDALIAS-cim_src = src_ip AS src
FIELDALIAS-cim_dest = host AS dest
EVAL-action = case(match(_raw, "Accepted"), "success", match(_raw, "Failed"), "failure", 1=1, "unknown")
EVAL-app = "sshd"
LOOKUP-user_enrichment = ad_users_lookup sAMAccountName AS user OUTPUT department, manager, title
```

### Credential Storage

```bash
# Store credentials securely (Splunk credential store)
curl -k -H "Authorization: Splunk <session_key>" \
  https://splunk.example.com:8089/servicesNS/nobody/my_custom_app/storage/passwords \
  -d name=api_key \
  -d password=secret_value_here \
  -d realm=my_custom_app
```

Access from Python search command:

```python
import splunklib.client as client

def get_credential(session_key, app, realm, username):
    service = client.connect(token=session_key, app=app)
    for credential in service.storage_passwords:
        if credential.realm == realm and credential.username == username:
            return credential.clear_password
    return None
```

---

## Related Skills

| Workload | Skill |
|---|---|
| RHEL monitoring (Prometheus, Grafana, ELK) | `rhel-monitoring` |
| Ubuntu monitoring (Prometheus, Grafana, logging) | `ubuntu-monitoring` |
| Large file / log analysis | `large-file-analysis` |
| Docker container logging | `docker-admin` |
| Python SDK development | `python-flask-developer` |
| Data warehouse / data pipeline design | `data-warehouse`, `data-lake` |
