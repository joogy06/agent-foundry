# Operator/User Role and Quick Reference

Reference file for the `control-m` skill. Covers operator/user tasks (monitoring, active jobs, troubleshooting, batch operations) and quick reference.

## Operator / User Role

### 11. Monitoring

#### Control-M Web Interface

Access at `https://ctmserver01:8443` (or Helix URL). Key views:

- **Monitoring > Active Jobs** — all currently ordered jobs with real-time status
- **Monitoring > Viewpoints** — saved filters for specific job sets (e.g., "Prod ETL", "Failed Jobs")
- **Planning > Job Definitions** — browse and edit definitions (developers/admins)

#### Job Status Lifecycle

```
Defined (in folder)
  |
  v
Wait Scheduling (not yet scheduling date)
  |
  v
Wait Condition (In-conditions not yet satisfied)
  |
  v
Wait Resource (quantitative/control resource not available)
  |
  v
Wait Host (agent not available or hostgroup full)
  |
  v
Executing (running on agent)
  |
  v
Ended OK  /  Ended Not OK
  |              |
  v              v
Post-processing  Alert / Rerun / Manual intervention
```

#### Monitoring via Automation API

```bash
# Get all active jobs with status
ctm run jobs:status::get -s "ctm=ctmserver01&status=Executing"

# Get jobs that ended not OK
ctm run jobs:status::get -s "ctm=ctmserver01&status=Ended Not OK"

# Get jobs in a specific folder
ctm run jobs:status::get -s "ctm=ctmserver01&folder=PROD_ETL"

# Get specific job log
ctm run job:log::get "ctmserver01:00042"

# Get job output (stdout/stderr)
ctm run job:output::get "ctmserver01:00042"

# Get historical runs (requires archive)
ctm reporting jobs::get -s "fromTime=20260401000000&toTime=20260401235959&folder=PROD_ETL"
```

#### Custom Viewpoints

Viewpoints are saved query filters. Common useful viewpoints:

| Viewpoint | Filter Criteria |
|---|---|
| Failed Jobs | `status=Ended Not OK` |
| Long Running | `status=Executing AND startedBefore=2h` |
| SLA at Risk | BIM critical path jobs with delay |
| My Team's Jobs | `folder=TEAM_*` |
| Waiting on Conditions | `status=Wait Condition` |

### 12. Operations

#### Common Operational Actions

```bash
# Hold a job (prevent execution)
ctm run job:hold "ctmserver01:00042"

# Free a held job (allow execution)
ctm run job:free "ctmserver01:00042"

# Rerun a completed job
ctm run job:rerun "ctmserver01:00042"

# Kill a running job
ctm run job:kill "ctmserver01:00042"

# Force OK (mark failed job as successful — use sparingly)
ctm run job:setToOK "ctmserver01:00042"

# Order an additional job on-demand
ctm run order ctmserver01 "PROD_ETL" "ETL_Extract_Sales" -odat "20260401"

# Confirm a manual confirmation step
ctm run job:confirm "ctmserver01:00042"
```

#### Restart from Step (Multi-Step Jobs)

For jobs with multiple steps (e.g., Application Integrator jobs), you can restart from a specific step after partial failure:

```bash
ctm run job:rerun "ctmserver01:00042" -from "Step3_LoadData"
```

#### Batch Operations

```bash
# Hold all jobs in a folder
ctm run jobs:hold -s "ctm=ctmserver01&folder=PROD_ETL"

# Free all jobs in a folder
ctm run jobs:free -s "ctm=ctmserver01&folder=PROD_ETL"

# Rerun all failed jobs in a folder
ctm run jobs:rerun -s "ctm=ctmserver01&folder=PROD_ETL&status=Ended Not OK"
```

### 13. SLA Management

#### BIM (Business Impact Manager)

BIM tracks business services that depend on Control-M job chains. It provides:
- **Service definitions** — map critical job flows to business services
- **SLA compliance** — track on-time completion against committed SLAs
- **Critical path** — visualize the longest dependency chain
- **Impact analysis** — what-if scenarios ("if this job is delayed 30 min, which services are impacted?")

#### Service Definition

```json
{
  "Service_Daily_ETL": {
    "Type": "BIM:Service",
    "ServiceName": "Daily ETL Pipeline",
    "SLA": {
      "CompletionTime": "0800",
      "TimeZone": "US/Eastern"
    },
    "Jobs": [
      {"Folder": "PROD_ETL", "Job": "ETL_Load_Final"},
      {"Folder": "PROD_REPORTS", "Job": "Report_Generation"}
    ],
    "AlertOnRisk": true,
    "AlertLeadTime": "60"
  }
}
```

#### SLA Monitoring

```bash
# Get BIM service status
ctm reporting bim:services::get \
  -s "fromTime=20260401000000&toTime=20260401235959"

# Get critical path for a service
ctm reporting bim:service:criticalpath::get "Service_Daily_ETL"
```

#### Impact Analysis

In Control-M Web > BIM > select service > "What-If Analysis":
- Simulate job delays and see impact on downstream services
- Identify which jobs are on the critical path (any delay = SLA miss)
- Proactive alerting when a job on the critical path starts late or runs longer than average

### 14. Alerting

#### Alert Types

| Alert Type | Trigger | Priority |
|---|---|---|
| Job failure | Job ends Not OK | Urgent |
| SLA risk | BIM detects SLA completion at risk | Urgent |
| Resource shortage | Quantitative resource at max, jobs queuing | Warning |
| Long running | Job exceeds average runtime by threshold | Warning |
| Agent unavailable | Agent loses connectivity to server | Critical |

#### Notification Configuration (Shout Destinations)

```bash
# Define shout (notification) destinations
ctm config server:shout::add ctmserver01.example.com \
  -f shout_config.json
```

```json
{
  "ShoutDestination": {
    "Email_OnCall": {
      "Type": "Email",
      "To": "oncall@example.com",
      "Cc": "ops-team@example.com",
      "Subject": "Control-M Alert: %%JOBNAME on %%NODEID",
      "Message": "Job %%JOBNAME in folder %%SCHEDTAB ended %%COMPSTAT at %%TIME on %%ODATE. Order ID: %%ORDERID."
    },
    "Webhook_PagerDuty": {
      "Type": "Script",
      "Script": "/opt/ctm/scripts/pagerduty_alert.sh",
      "Arguments": "%%JOBNAME %%COMPSTAT %%SCHEDTAB %%ODATE"
    },
    "SNMP_Monitoring": {
      "Type": "SNMP",
      "Destination": "monitoring.example.com",
      "Port": "162",
      "Community": "ctm-alerts"
    }
  }
}
```

#### Job-Level Alerting

```json
{
  "Critical_Job": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/critical_process.sh",
    "Host": "agent01",
    "Notification": {
      "OnFailure": {
        "Destination": "Email_OnCall",
        "Urgency": "Urgent",
        "Message": "CRITICAL: %%JOBNAME failed. Immediate attention required."
      },
      "OnLateSubmission": {
        "Destination": "Email_OnCall",
        "Urgency": "Warning",
        "Minutes": "30"
      },
      "OnExecutionTime": {
        "Destination": "Webhook_PagerDuty",
        "Urgency": "Warning",
        "Minutes": "120",
        "Message": "Job %%JOBNAME running longer than 120 minutes."
      }
    }
  }
}
```

#### Alert Escalation Pattern

```
Minute 0  — Job fails → email to oncall@example.com
Minute 15 — Not acknowledged → page via PagerDuty
Minute 30 — Not resolved → escalate to ops-manager@example.com
Minute 60 — Not resolved → trigger incident management webhook
```

Implement by chaining shout destinations with time-based escalation rules in the alert configuration or by using an external incident management tool triggered via REST webhook.

---

## Quick Reference

### Automation API — Common ctm Commands

```bash
ctm session login                    # authenticate
ctm session logout                   # end session
ctm build <file.json>                # validate definitions
ctm deploy <file.json>               # push definitions to server
ctm deploy <file.json> -d <desc>     # deploy with deploy descriptor
ctm run <file.json>                  # order and run immediately
ctm run order <server> <folder>      # order a folder
ctm run status <runId>               # check run status
ctm run wait <runId> -t <seconds>    # wait for completion
ctm run job:log::get <jobId>         # get job log
ctm run job:output::get <jobId>      # get job output
ctm run job:hold <jobId>             # hold job
ctm run job:free <jobId>             # free job
ctm run job:rerun <jobId>            # rerun job
ctm run job:kill <jobId>             # kill running job
ctm run job:setToOK <jobId>          # force OK
ctm config server:agents::get <srv>  # list agents
ctm config global:variable::set      # set global variable
ctm reporting audit::get             # query audit log
```

### Default Ports

| Port | Service |
|---|---|
| 7005 | Agent-to-Server communication |
| 7006 | Server-to-Agent communication |
| 8443 | Control-M Web (HTTPS) |
| 2370 | EM-to-Server communication |
| 2380 | EM Config Agent |
| 443 | Helix Control-M (outbound HTTPS from agent) |

### Key File Locations (RHEL Agent)

| Path | Purpose |
|---|---|
| `/opt/ctm_agent/` | Agent installation directory |
| `/opt/ctm_agent/proclog/` | Agent process logs |
| `/opt/ctm_agent/ctm/scripts/` | Agent lifecycle scripts |
| `/opt/ctm_agent/data/` | Agent runtime data |
| `/home/ctmagent/` | Agent user home directory |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Hardcoding paths and server names in job definitions | Jobs break when migrated between environments (dev/test/prod); maintenance requires editing every job | Use Control-M variables, AutoEdit substitution, and connection profiles for environment-specific values |
| Creating linear chains of 50+ jobs without sub-folders | Impossible to monitor, debug, or restart mid-chain; a single failure blocks the entire sequence | Break into logical sub-folders with condition-based dependencies; use Smart Folders for grouping |
| Setting no timeout or unrealistically long timeouts on jobs | Hung jobs hold resources indefinitely; downstream jobs wait forever; batch windows get missed | Set realistic timeouts based on historical runtime + buffer; configure alerts for jobs exceeding threshold |
| Running all batch jobs under a single service account | No auditability; a credential change breaks everything; violates least-privilege principle | Use dedicated service accounts per application or job group; rotate credentials on schedule |
| Skipping calendar validation when scheduling across time zones | Jobs fire at wrong times; DST transitions cause double-runs or missed runs | Use Control-M calendar objects with explicit timezone settings; test scheduling across DST boundaries |
