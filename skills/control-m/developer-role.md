# Developer Role

Reference file for the `control-m` skill. Covers job definition (OS/Script/File Transfer/Database/Application Integrator), scheduling, flow management, SLA management, and Automation API.

## Developer Role

### 5. Job Definitions

#### Job Types Overview

| Job Type | Use Case | Key Properties |
|---|---|---|
| OS/Command | Run shell commands, scripts | Command, Host, RunAs |
| Script | Execute embedded or referenced scripts | FileName, FilePath |
| File Transfer (MFT) | Move files between systems (FTP/SFTP/S3) | ConnectionProfile, Source, Destination |
| Database | Run SQL queries, stored procedures | ConnectionProfile, Query, Procedure |
| Application Integrator | SAP, Informatica, Hadoop, AWS, Azure jobs | Plugin-specific properties |
| Web Services | REST/SOAP API calls | URL, Method, Headers, Body |
| File Watcher | Wait for file arrival before continuing | Path, Pattern, MinSize, MinAge |

#### Folder Structure

Jobs are organized into folders (logical containers). Folders can be:
- **Regular folders** — manually ordered or scheduled
- **Smart folders (SMART_FOLDER)** — self-contained scheduling units with their own scheduling rules

```json
{
  "PROD_ETL": {
    "Type": "SmartFolder",
    "ControlmServer": "ctmserver01",
    "OrderMethod": "Automatic",
    "Scheduling": {
      "Months": ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"],
      "MonthDays": ["ALL"]
    },
    "Job1_Extract": { ... },
    "Job2_Transform": { ... },
    "Job3_Load": { ... }
  }
}
```

#### OS/Command Job Example

```json
{
  "ETL_Extract_Sales": {
    "Type": "Job:Command",
    "Command": "/opt/etl/bin/extract_sales.sh",
    "Host": "agent-rhel-prod01",
    "RunAs": "etluser",
    "MaxWait": "120",
    "MaxRerun": "3",
    "When": {
      "InCondition": [
        {"Name": "SOURCE_DB_READY-ODAT", "Server": "ctmserver01"}
      ],
      "OutCondition": {
        "CompletionStatus": "OK",
        "Add": [
          {"Name": "ETL_EXTRACT_DONE-ODAT", "Server": "ctmserver01"}
        ]
      }
    }
  }
}
```

#### Database Job Example

```json
{
  "DB_Run_Monthly_Report": {
    "Type": "Job:Database:EmbeddedQuery",
    "ConnectionProfile": "CP_PROD_POSTGRES",
    "Query": "CALL sp_monthly_report(%%ODATE);",
    "Host": "agent-rhel-prod01",
    "RunAs": "dbuser",
    "When": {
      "InCondition": [
        {"Name": "ETL_LOAD_DONE-ODAT", "Server": "ctmserver01"}
      ]
    }
  }
}
```

#### Web Services Job Example (REST API)

```json
{
  "API_Trigger_Report": {
    "Type": "Job:WebServices",
    "URL": "https://api.example.com/v1/reports/generate",
    "HttpMethod": "POST",
    "Headers": {
      "Content-Type": "application/json",
      "Authorization": "Bearer %%GLOBAL_API_TOKEN"
    },
    "Body": "{\"date\": \"%%ODATE\", \"type\": \"daily\"}",
    "SuccessStatusCodes": "200,201,202",
    "Host": "agent-rhel-prod01",
    "RunAs": "apiuser"
  }
}
```

### 6. Scheduling

#### Calendar Types

| Calendar Type | Description | Example |
|---|---|---|
| Regular | Specific named dates | "Company_Holidays_2026" |
| Rule-Based | Rules like "last business day of month" | End-of-month processing |
| Periodic | Recurring intervals (e.g., every 2 weeks) | Bi-weekly payroll |

#### Scheduling Rules in JSON

```json
{
  "Scheduling": {
    "Months": ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"],
    "MonthDays": ["1","15"],
    "WeekDays": ["MON","TUE","WED","THU","FRI"],
    "FromTime": "0600",
    "ToTime": "1800",
    "DaysRelation": "AND",
    "Calendar": "US_Business_Days",
    "ExcludeCalendar": "US_Holidays_2026"
  }
}
```

Key scheduling fields:
- **MonthDays** — `ALL`, specific days (`1`, `15`, `L` for last), or `D1`-`D31` for working days
- **WeekDays** — `MON` through `SUN`
- **DaysRelation** — `AND` (must match both MonthDays and WeekDays) or `OR` (match either)
- **FromTime/ToTime** — submit window (HHMM, 24-hour format)
- **Calendar/ExcludeCalendar** — reference named calendars

#### Cyclic Jobs (Interval-Based)

```json
{
  "CYCLIC_Health_Check": {
    "Type": "Job:Command",
    "Command": "/opt/monitoring/health_check.sh",
    "Host": "agent-rhel-prod01",
    "RunAs": "monuser",
    "Cyclic": {
      "Type": "Cyclic",
      "IntervalMinutes": "15",
      "FromTime": "0600",
      "ToTime": "2200"
    }
  }
}
```

Cyclic jobs rerun at fixed intervals within a submit window. They remain in the Active Jobs table and resubmit automatically.

#### Time Zones

```json
{
  "US_EAST_Daily_Job": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/daily.sh",
    "Host": "agent-us-east",
    "TimeZone": "US/Eastern",
    "Scheduling": {
      "FromTime": "0800",
      "ToTime": "1700"
    }
  }
}
```

Time zones ensure jobs schedule relative to local time, not server time. Critical for multi-region deployments.

### 7. Flow Control

#### In-Conditions and Out-Conditions

Conditions are the primary dependency mechanism. Format: `CONDITION_NAME-ODAT` where `ODAT` is the scheduling date.

```json
{
  "Job_A": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/job_a.sh",
    "Host": "agent01",
    "When": {
      "OutCondition": {
        "CompletionStatus": "OK",
        "Add": [
          {"Name": "JOB_A_DONE-ODAT", "Server": "ctmserver01"}
        ]
      }
    }
  },
  "Job_B": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/job_b.sh",
    "Host": "agent01",
    "When": {
      "InCondition": [
        {"Name": "JOB_A_DONE-ODAT", "Server": "ctmserver01"}
      ]
    }
  }
}
```

#### Quantitative Resources (Semaphores)

Limit concurrent job execution — e.g., only 5 jobs may hit the database simultaneously.

```json
{
  "DB_Query_Job": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/db_query.sh",
    "Host": "agent01",
    "Resources": {
      "Quantitative": [
        {"Name": "RES_DB_CONNECTIONS", "Quantity": "1"}
      ]
    }
  }
}
```

Define the resource on the server:

```bash
# Create quantitative resource with max 5 concurrent
ctm config server:resource::add ctmserver01.example.com "RES_DB_CONNECTIONS" 5
```

#### Control Resources (Mutual Exclusion)

Prevent two jobs from running simultaneously — e.g., only one backup job at a time.

```json
{
  "Backup_Job": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/backup.sh",
    "Host": "agent01",
    "Resources": {
      "Control": [
        {"Name": "RES_BACKUP_LOCK", "Type": "Exclusive"}
      ]
    }
  }
}
```

#### IF-THEN-ELSE Logic

```json
{
  "Job_With_Logic": {
    "Type": "Job:Command",
    "Command": "/opt/scripts/process.sh",
    "Host": "agent01",
    "ActionIfSuccess": {
      "Type": "If",
      "CompletionStatus": "OK",
      "Mail": {
        "To": "team@example.com",
        "Subject": "Job %%JOBNAME completed OK on %%ODATE",
        "Urgency": "Regular"
      },
      "AddCondition": {"Name": "PROCESS_DONE-ODAT"}
    },
    "ActionIfFailure": {
      "Type": "If",
      "CompletionStatus": "NOTOK",
      "Mail": {
        "To": "oncall@example.com",
        "Subject": "ALERT: %%JOBNAME FAILED on %%ODATE",
        "Urgency": "Urgent"
      },
      "SetToOK": false,
      "Rerun": {
        "Every": "5",
        "Times": "3"
      }
    }
  }
}
```

#### Sub-Folders as Sub-Flows

Use sub-folders to group related jobs within a smart folder. The sub-folder can have its own conditions, acting as a sub-flow:

```json
{
  "PROD_PIPELINE": {
    "Type": "SmartFolder",
    "ETL_SubFolder": {
      "Type": "SubFolder",
      "Job_Extract": { ... },
      "Job_Transform": { ... },
      "Job_Load": { ... }
    },
    "Report_SubFolder": {
      "Type": "SubFolder",
      "When": {
        "InCondition": [
          {"Name": "ETL_COMPLETE-ODAT", "Server": "ctmserver01"}
        ]
      },
      "Job_Generate_Report": { ... },
      "Job_Distribute_Report": { ... }
    }
  }
}
```

### 8. Automation API (Jobs-as-Code)

#### ctm CLI — Core Commands

```bash
# Login
ctm session login -e https://ctmserver01:8443/automation-api \
  -u admin -p "$CTM_PASSWORD"

# Helix login
ctm session login -e https://YOUR_TENANT.us1.controlm.com/automation-api \
  -u apiuser -p "$CTM_API_KEY"

# Build — validate JSON syntax and semantics without deploying
ctm build jobs_definition.json

# Deploy — push job definitions to Control-M/Server (creates/updates definitions)
ctm deploy jobs_definition.json

# Run — order jobs for immediate execution
ctm run jobs_definition.json

# Run with specific order date
ctm run order ctmserver01 "PROD_ETL" -odat "20260401"

# Get job status
ctm run status "$RUN_ID"

# Get job log
ctm run job:log::get "$JOB_ID"

# Get job output
ctm run job:output::get "$JOB_ID"

# Wait for job completion (useful in CI/CD)
ctm run wait "$RUN_ID" -t 3600
```

#### Build / Deploy / Run Cycle

```
Developer writes JSON  -->  ctm build (validate)  -->  ctm deploy (push definitions)
                                                          |
                                      Definitions stored on Control-M/Server
                                                          |
                                      ctm run order (schedule/execute)
```

#### CI/CD Pipeline Integration (GitHub Actions Example)

```yaml
name: Control-M Deploy
on:
  push:
    branches: [main]
    paths: ['controlm/**']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install ctm CLI
        run: |
          npm install -g ctm-cli
          ctm env add prod https://ctmserver01:8443/automation-api

      - name: Login
        run: ctm session login -e prod -u ${{ secrets.CTM_USER }} -p ${{ secrets.CTM_PASS }}

      - name: Build (validate)
        run: ctm build controlm/jobs/*.json

      - name: Deploy to Dev
        if: github.ref != 'refs/heads/main'
        run: |
          ctm deploy controlm/jobs/*.json \
            -d controlm/deploy-descriptors/dev.json

      - name: Deploy to Prod
        if: github.ref == 'refs/heads/main'
        run: |
          ctm deploy controlm/jobs/*.json \
            -d controlm/deploy-descriptors/prod.json

      - name: Logout
        if: always()
        run: ctm session logout
```

#### Deploy Descriptor (Environment Promotion)

Deploy descriptors transform job definitions for different environments:

```json
{
  "DeployDescriptor": {
    "Property": [
      {
        "Attribute": "Host",
        "Source": "agent-dev-*",
        "Target": "agent-prod-*"
      },
      {
        "Attribute": "RunAs",
        "Source": "devuser",
        "Target": "produser"
      },
      {
        "Attribute": "Folder",
        "Source": "DEV_*",
        "Target": "PROD_*"
      }
    ]
  }
}
```

```bash
# Deploy with descriptor (transforms dev definitions for prod)
ctm deploy jobs_dev.json -d deploy_descriptor_prod.json
```

#### Version Control Integration

Recommended Git repository structure:

```
controlm/
  jobs/
    etl/
      etl_daily.json
      etl_monthly.json
    reports/
      daily_reports.json
    file_transfers/
      sftp_inbound.json
  connection-profiles/
    cp_prod_db.json
    cp_prod_sftp.json
  calendars/
    us_business_days.json
  deploy-descriptors/
    dev.json
    test.json
    prod.json
  README.md
```

### 9. Variables & Parameters

#### System Variables (AutoEdit)

| Variable | Description | Example Value |
|---|---|---|
| `%%ODATE` | Original scheduling date (YYYYMMDD or DDMMYY depending on config) | `20260401` |
| `%%ORDERID` | Unique run order ID | `00042` |
| `%%JOBNAME` | Current job name | `ETL_Extract_Sales` |
| `%%SCHEDTAB` | Folder (scheduling table) name | `PROD_ETL` |
| `%%NODEID` | Agent name executing the job | `agent-rhel-prod01` |
| `%%$ODATE` | ODATE in different formats via modifier | See below |
| `%%CALCDATE` | Calculate date offsets | `%%CALCDATE %%ODATE -1` (yesterday) |
| `%%TIME` | Current time (HHMM) | `1430` |

#### Date Format Modifiers

```bash
# In job command or script
%%$ODATE ODAT(-1)          # yesterday: 20260331
%%$ODATE OYEAR             # year: 2026
%%$ODATE OMONTH            # month: 04
%%$ODATE ODAY              # day: 01
%%$ODATE OJULDAY           # Julian day: 091
%%$ODATE CENT              # century: 20
%%$ODATE 4DIGYR-2DIGMN     # 2026-04
```

#### User-Defined Variables

```json
{
  "ETL_Job": {
    "Type": "Job:Command",
    "Command": "/opt/etl/run.sh -env %%ENV -batch %%BATCH_SIZE",
    "Host": "agent01",
    "Variables": [
      {"Name": "%%ENV", "Value": "production"},
      {"Name": "%%BATCH_SIZE", "Value": "10000"}
    ]
  }
}
```

#### Global Variables

```bash
# Set a global variable (visible across all servers/agents)
ctm config global:variable::set "GLOBAL_DB_HOST" "db-prod01.example.com"

# Get a global variable
ctm config global:variable::get "GLOBAL_DB_HOST"

# Use in job definitions as: %%GLOBAL_DB_HOST
```

#### Variable Resolution Order

1. Job-level variables (highest priority)
2. Folder-level variables
3. Global variables (Control-M/EM level)
4. System variables (%%ODATE, %%JOBNAME, etc.)

### 10. File Transfer (MFT)

#### Connection Profiles

```bash
# Create SFTP connection profile
ctm config connectionprofile:centralized::add \
  -f sftp_profile.json
```

```json
{
  "CP_PROD_SFTP": {
    "Type": "ConnectionProfile:FileTransfer:SFTP",
    "TargetAgent": "agent-rhel-prod01",
    "TargetPort": "22",
    "Host": "sftp.partner.com",
    "Port": "22",
    "User": "filetransfer",
    "PrivateKeyFile": "/home/ctmagent/.ssh/partner_key",
    "Passphrase": {"Secret": "SFTP_PARTNER_PASSPHRASE"}
  }
}
```

#### File Transfer Job

```json
{
  "MFT_Receive_Daily_Feed": {
    "Type": "Job:FileTransfer",
    "ConnectionProfileSrc": "CP_PROD_SFTP",
    "ConnectionProfileDest": "CP_LOCAL_AGENT",
    "FileTransfers": [
      {
        "Src": "/outbound/daily_feed_%%ODATE.csv",
        "Dest": "/data/inbound/daily_feed_%%ODATE.csv",
        "TransferOption": "Binary",
        "PostActionSrc": "Rename",
        "PostActionSrcPath": "/outbound/archive/daily_feed_%%ODATE.csv"
      }
    ],
    "Host": "agent-rhel-prod01",
    "RunAs": "ctmagent"
  }
}
```

#### S3 / Cloud Storage Transfer

```json
{
  "CP_AWS_S3": {
    "Type": "ConnectionProfile:FileTransfer:S3",
    "S3BucketName": "my-data-bucket",
    "Region": "us-east-1",
    "AccessKey": {"Secret": "AWS_ACCESS_KEY"},
    "SecretAccessKey": {"Secret": "AWS_SECRET_KEY"}
  }
}
```

#### File Watcher Job

```json
{
  "FW_Wait_For_File": {
    "Type": "Job:FileWatcher",
    "Path": "/data/inbound/",
    "Pattern": "daily_feed_*.csv",
    "MinFileSize": "1KB",
    "MinFileAge": "30",
    "TimeLimit": "120",
    "Host": "agent-rhel-prod01",
    "RunAs": "ctmagent",
    "When": {
      "OutCondition": {
        "CompletionStatus": "OK",
        "Add": [
          {"Name": "DAILY_FILE_ARRIVED-ODAT", "Server": "ctmserver01"}
        ]
      }
    }
  }
}
```

---

