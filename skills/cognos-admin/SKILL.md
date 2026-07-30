---
name: cognos-admin
description: Use when administering IBM Cognos Analytics or using its APIs — installation and configuration, security (namespaces/roles/capabilities), content administration, report management, Framework Manager modeling, REST API (session/content/reports/dashboards), data source connections, scheduling and bursting, performance tuning, and Cognos on Cloud Pak for Data. Covers Cognos Analytics 12.x (11.2.x legacy — out of standard support 2026-04).
disambiguation: Runs the Cognos SERVER — install, security namespaces, capabilities, content store, admin APIs. Authoring and consuming reports as an end user is cognos-user.
---

# IBM Cognos Analytics — Administration & API

<HARD-RULE>
Always back up the content store database before any Cognos upgrade or major configuration change. Use pg_dump, db2 backup, or the appropriate RDBMS tool, and verify the backup restores cleanly to a scratch instance before proceeding.
</HARD-RULE>

<HARD-RULE>
Never grant the System Administrator capability broadly — it bypasses all content security. Assign it only to a small, named group of platform administrators, and audit membership quarterly.
</HARD-RULE>

<HARD-RULE>
Always use Framework Manager security filters for row-level data security — report-level filters can be bypassed by users with authoring permissions. Security filters are enforced at the query layer regardless of how the data is accessed.
</HARD-RULE>

<HARD-RULE>
Never expose the Cognos dispatcher port (9300/9380) directly to the internet — always front with a reverse proxy (Apache, Nginx, or IBM HTTP Server) with TLS termination. The dispatcher protocol is not designed for untrusted networks.
</HARD-RULE>

---

## 1. Architecture

> **Version lifecycle (verified 2026-06):** Cognos Analytics 11.2.x exited IBM standard support on 2026-04-30 (extended/sustained support tiers continue per IBM lifecycle — verify current terms). New installs and upgrades should target 12.x; treat 11.2.x guidance below as legacy-maintenance only.

### Core Components

| Component | Role | Default Port |
|---|---|---|
| Gateway | Entry point — reverse proxy to dispatchers, handles HTTP/HTTPS | 80/443 (web server) |
| Content Manager | Manages content store DB, security, sessions, configuration | 9300 (internal) |
| Dispatcher | Routes requests to services, load balancing | 9300/9380 |
| Query Service | Executes queries against data sources | Internal |
| Report Service | Renders reports (interactive/HTML) | Internal |
| Batch Report Service | Runs scheduled/burst reports | Internal |
| Presentation Service | Serves Cognos Analytics UI (dashboards, stories, explorations) | Internal |
| Data Integration Service | ETL / data movement (if licensed) | Internal |

### Content Store

The content store is a relational database that holds all Cognos metadata — reports, folders, schedules, security policies, user preferences, deployment specs. Supported databases:

- **PostgreSQL** (bundled with 12.x installer)
- **IBM DB2**
- **Microsoft SQL Server**
- **Oracle Database**

The content store does NOT store report output data or data source data — only metadata and configuration.

### Process Flow

```
Browser → Gateway (IHS/Apache/Nginx) → Dispatcher → Content Manager → Content Store DB
                                          ↓
                                    Query Service → Data Source (RDBMS/OLAP)
                                          ↓
                                    Report Service → Rendered Output
```

Authentication flow: Browser → Gateway → CAM (Cognos Access Manager) → Authentication Namespace (LDAP/AD/OIDC/SAML) → Session Token → Dispatcher.

---

## 2. Installation & Configuration

### Prerequisites

```bash
# RHEL/CentOS — required libraries
sudo dnf install -y libX11 libXext libXrender fontconfig freetype \
  libpng libjpeg-turbo libXtst libXi nss nspr \
  glibc.i686 libstdc++.i686

# Verify ulimits (add to /etc/security/limits.d/cognos.conf)
cognos  soft  nofile  65536
cognos  hard  nofile  65536
cognos  soft  nproc   16384
cognos  hard  nproc   16384
```

### Silent Install (Linux)

```bash
# Extract installer
tar xzf ca_server_12.0.x_linux_x86.tar.gz -C /tmp/cognos-install

# Create response file for silent install
cat > /tmp/cognos-response.properties <<'EOF'
INSTALLER_UI=silent
USER_INSTALL_DIR=/opt/ibm/cognos/analytics
LICENSE_ACCEPTED=true
CHOSEN_INSTALL_SET=Express
EOF

# Run silent install
/tmp/cognos-install/install.sh -i silent -f /tmp/cognos-response.properties
```

### Content Store Setup — PostgreSQL

```bash
# Create content store database (using bundled or external PostgreSQL)
sudo -u postgres psql <<'EOF'
CREATE ROLE cognos WITH LOGIN PASSWORD 'CognosCS!2024' VALID UNTIL '2028-01-01';
CREATE DATABASE cognoscs OWNER cognos ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8';
GRANT ALL PRIVILEGES ON DATABASE cognoscs TO cognos;
EOF
```

### Content Store Setup — DB2

```bash
# Create DB2 database for content store
db2 "CREATE DATABASE COGNOSCS AUTOMATIC STORAGE YES USING CODESET UTF-8 TERRITORY US COLLATE USING IDENTITY PAGESIZE 16384"
db2 "CONNECT TO COGNOSCS"
db2 "CREATE BUFFERPOOL BP16K IMMEDIATE SIZE 1000 AUTOMATIC PAGESIZE 16 K"
db2 "CREATE REGULAR TABLESPACE COGNOSTS PAGESIZE 16 K MANAGED BY AUTOMATIC STORAGE BUFFERPOOL BP16K"
db2 "GRANT DBADM ON DATABASE TO USER cognos"
```

### Content Store Setup — SQL Server

```sql
-- SQL Server content store
CREATE DATABASE cognoscs COLLATE Latin1_General_CS_AS;
GO
USE cognoscs;
CREATE LOGIN cognos WITH PASSWORD = 'CognosCS!2024';
CREATE USER cognos FOR LOGIN cognos;
ALTER ROLE db_owner ADD MEMBER cognos;
GO
```

### cogconfig.sh — Configuration Tool

```bash
# Launch configuration UI (X11 forwarding or VNC required)
/opt/ibm/cognos/analytics/bin64/cogconfig.sh

# Key configuration locations
# Config XML: /opt/ibm/cognos/analytics/configuration/cogstartup.xml
# Templates:  /opt/ibm/cognos/analytics/configuration/templates/
```

Key cogstartup.xml settings:

```xml
<!-- Content store connection -->
<crn:parameter name="contentStoreURI">
  <crn:value>jdbc:postgresql://dbhost:5432/cognoscs</crn:value>
</crn:parameter>

<!-- Gateway URI (external-facing URL) -->
<crn:parameter name="externalDispatcherURI">
  <crn:value>http://cognos-server:9300/p2pd/servlet/dispatch</crn:value>
</crn:parameter>

<!-- Gateway settings -->
<crn:parameter name="gateway">
  <crn:value>http://cognos-server:443/bi/v1/disp</crn:value>
</crn:parameter>

<!-- Internal dispatcher URI -->
<crn:parameter name="internalDispatcherURI">
  <crn:value>http://localhost:9300/p2pd/servlet/dispatch</crn:value>
</crn:parameter>
```

### Cryptographic Keys

```bash
# Generate new cryptographic keys (required on fresh install)
/opt/ibm/cognos/analytics/bin64/cogconfig.sh -s

# Export keys for backup (critical — lost keys = inaccessible content store)
cp /opt/ibm/cognos/analytics/configuration/signkeypair/*.* /backup/cognos/keys/
cp /opt/ibm/cognos/analytics/configuration/encryptkeypair/*.* /backup/cognos/keys/
```

### Start / Stop Cognos Service

```bash
# Start Cognos Analytics
/opt/ibm/cognos/analytics/bin64/cogserver.sh -start

# Stop Cognos Analytics
/opt/ibm/cognos/analytics/bin64/cogserver.sh -stop

# Check status
/opt/ibm/cognos/analytics/bin64/cogserver.sh -status

# Tail the main log
tail -f /opt/ibm/cognos/analytics/logs/cogserver.log
```

### Systemd Service (Production)

`/etc/systemd/system/cognos.service`:

```ini
[Unit]
Description=IBM Cognos Analytics
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=forking
User=cognos
Group=cognos
ExecStart=/opt/ibm/cognos/analytics/bin64/cogserver.sh -start
ExecStop=/opt/ibm/cognos/analytics/bin64/cogserver.sh -stop
TimeoutStartSec=300
TimeoutStopSec=120
LimitNOFILE=65536
LimitNPROC=16384

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cognos
```

---

## 3. Security

### Authentication Namespaces

Cognos supports multiple authentication providers configured in cogstartup.xml via Cognos Configuration:

**LDAP / Active Directory:**

```xml
<crn:parameter name="AAA_Namespace">
  <crn:value>
    <crn:instance name="CorporateAD" class="NTLM">
      <crn:property name="connection">ldap://dc01.corp.local:389</crn:property>
      <crn:property name="baseDN">dc=corp,dc=local</crn:property>
      <crn:property name="userLookup">(sAMAccountName=${userID})</crn:property>
      <crn:property name="bindCredentials">CN=CognosSvc,OU=Service,DC=corp,DC=local</crn:property>
      <crn:property name="sizeLimit">500</crn:property>
    </crn:instance>
  </crn:value>
</crn:parameter>
```

**OIDC (OpenID Connect) — Cognos 12.x:**

Configure via Administration Console > Security > Authentication:
- Provider URL (e.g., `https://idp.corp.local/realms/cognos/.well-known/openid-configuration`)
- Client ID and Secret
- Redirect URI: `https://cognos.corp.local/bi/completeLogin.jsp`
- Claim mapping: `preferred_username` → Cognos identity
- Scope: `openid profile email`

**SAML 2.0:**

Configure via Cognos Configuration:
- Identity Provider metadata XML import
- Service Provider entity ID and ACS URL
- Certificate exchange (IdP signing cert, SP encryption cert)
- NameID format mapping

### Groups, Roles, and Capabilities

```
Built-in security objects hierarchy:
├── Cognos namespace (built-in)
│   ├── Everyone group
│   ├── All Authenticated Users group
│   ├── Anonymous
│   └── Built-in roles:
│       ├── System Administrators
│       ├── Directory Administrators
│       ├── Report Administrators
│       ├── Analytics Administrators
│       ├── Analytics Users
│       ├── Authors
│       └── Consumers
└── External namespaces (AD/LDAP/OIDC/SAML)
    ├── Groups (mapped from directory)
    └── Users (authenticated from directory)
```

**Key Capabilities** (Administration Console > Security > Capabilities):

| Capability | Risk Level | Description |
|---|---|---|
| Administration | HIGH | Full admin console access |
| Manage content | HIGH | Create/modify/delete any content |
| Generate output | LOW | Run reports |
| Schedule | LOW | Create schedules |
| Burst reports | MEDIUM | Configure burst distribution |
| Create/delete | MEDIUM | Author new content |
| HTML items in report | HIGH | Can embed arbitrary HTML/JS |
| Adaptive Analytics | LOW | Use AI assistant features |

**Security Policy Best Practice:**

```
Content → Properties → Permissions:
  ├── Traverse (see the folder in navigation)
  ├── Read (view/run the report)
  ├── Write (edit the report)
  ├── Execute (run schedules)
  └── Set Policy (change permissions on this object)

Apply at folder level, let child objects inherit.
Break inheritance only when a subfolder needs different access.
```

### Multitenancy

Cognos 12.x supports multitenancy for SaaS/shared deployments:

- Tenant ID mapped from authentication claim or LDAP attribute
- Content isolation per tenant (each tenant sees only their folders)
- Separate data source connections per tenant
- Tenant-level theme/branding customization
- Configure via Administration Console > Multitenancy

---

## 4. Content Administration

### Administration Console

Access at: `https://cognos-server/bi/v1/disp?b_action=xts.run&m=portal/admin/admin.xts`

Or navigate: Manage > Administration Console (gear icon in Cognos Analytics UI).

### Content Organization

```
Content store structure:
├── Team content (shared across organization)
│   ├── Packages (published FM metadata)
│   ├── Reports
│   ├── Dashboards
│   └── Data modules
├── My content (per-user private area)
├── Administration (admin-only)
│   ├── Configuration
│   ├── Distribution lists
│   └── Deployment
└── Samples (out-of-box demo content)
```

### Content Deployment (Import/Export)

```bash
# Export a deployment archive via command line
/opt/ibm/cognos/analytics/bin64/contentManagerService.sh \
  -export \
  -name "Q4_2025_Backup" \
  -archive "/backup/cognos/Q4_2025_Backup.zip" \
  -password "ExportP@ss!2024"

# Import a deployment archive
/opt/ibm/cognos/analytics/bin64/contentManagerService.sh \
  -import \
  -name "Q4_2025_Backup" \
  -archive "/backup/cognos/Q4_2025_Backup.zip" \
  -password "ExportP@ss!2024"
```

Via Administration Console:
1. Configuration > Content Administration > New Export / New Import
2. Select folders/packages to include
3. Choose conflict resolution (replace, keep existing, or rename)
4. Set password for archive encryption
5. Run immediately or schedule

### Search Index

```bash
# Rebuild the content search index
# Administration Console > Configuration > Search Index > Rebuild
# Or via REST API:
curl -X POST "https://cognos-server/api/v1/search/reindex" \
  -H "IBM-BA-Authorization: CAMPassport ${CAM_PASSPORT}" \
  -H "Content-Type: application/json"
```

### Content Store Maintenance

```bash
# Consistency check (finds orphaned objects, broken references)
# Administration Console > Configuration > Content Administration > Consistency Check

# Prune old report outputs (versions) to save content store space
# Administration Console > Configuration > Content Administration
# Set "Number of report versions to keep" per folder or globally
```

---

## 5. Framework Manager

### Project Creation

```bash
# Launch Framework Manager (Windows client application)
# Start > IBM Cognos > Framework Manager

# Create new project:
# 1. File > New Project
# 2. Select language (locale)
# 3. Connect to data source
# 4. Import metadata (schemas/tables/views)
# 5. Build query subjects and relationships
# 6. Publish package to Cognos server
```

### Data Source Connections in FM

```
Project > Data Sources > New Data Source:
  Name: WarehouseDW
  Type: JDBC (or native)
  Connection string: jdbc:db2://dwhost:50000/SALESDB
  Signon: CognosDWUser (mapped credentials)
  Schema filter: DW_SCHEMA
```

### Query Subjects

```
Three types:
1. Data source query subject — direct table/view import
2. Model query subject — virtual table built from other query subjects (abstraction layer)
3. Stored procedure query subject — wraps a stored procedure

Best practice: Create a 3-layer model:
  Layer 1 — Database (physical tables, 1:1 with source)
  Layer 2 — Business (renamed columns, calculated items, joins abstracted)
  Layer 3 — Presentation (user-facing packages, organized by business area)
```

### Relationships

```
Define joins between query subjects:
  Type: Inner / Outer (Left/Right/Full)
  Cardinality: 1:1, 1:n, n:n
  Expression: [DIM_CUSTOMER].[CUST_ID] = [FACT_SALES].[CUST_ID]

Determinants: Define granularity for multi-grain facts
  - Set on the query subject
  - Define which keys uniquely identify a row at each grain
  - Prevents double-counting in reports with multiple fact tables
```

### Security Filters (Row-Level Security)

```
Query Subject > Properties > Security Filters:
  Filter: [SALES_REGION] = #sq($account.parameters.region)#
  Applied to: Sales Managers group

This generates a WHERE clause appended to every query using this query subject.
Users CANNOT bypass this — it is enforced at the query generation layer.

Multiple filters on the same group: AND logic
Multiple groups with different filters: user gets the union (OR) of their group filters
```

### Publishing Packages

```
1. Select query subjects/folders for the package
2. Define package-level security (which groups/roles can access)
3. Verify relationships and resolve ambiguous paths
4. Publish to Cognos Connection:
   Actions > Package > Publish Package
   Target: Team Content > Packages > [Folder]
   Options: Overwrite existing, Verify package

Republish after any model change — reports use the published package, not the FM project directly.
```

---

## 6. REST API

Base URL: `https://cognos-server/api/v1`

### Authentication — Session Management

```bash
# Create session (get CAM passport)
CAM_PASSPORT=$(curl -s -X PUT "https://cognos-server/api/v1/session" \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": [
      {"name": "CAMNamespace", "value": "CorporateAD"},
      {"name": "CAMUsername", "value": "admin"},
      {"name": "CAMPassword", "value": "P@ssw0rd"}
    ]
  }' \
  -c cookies.txt \
  | jq -r '.session_key // empty')

# Verify session
curl -s "https://cognos-server/api/v1/session" \
  -b cookies.txt | jq '.account'

# Delete session (logout)
curl -s -X DELETE "https://cognos-server/api/v1/session" \
  -b cookies.txt
```

### Content Operations

```bash
# List root content folders
curl -s "https://cognos-server/api/v1/content" \
  -b cookies.txt | jq '.content[]'

# List items in Team Content
curl -s "https://cognos-server/api/v1/content?parent=/content/team" \
  -b cookies.txt | jq '.content[] | {id, defaultName, type}'

# Search content by name
curl -s "https://cognos-server/api/v1/content?searchPattern=Sales%20Report" \
  -b cookies.txt | jq '.content[]'

# Get specific content item by store ID
curl -s "https://cognos-server/api/v1/content/i12345678-abcd-1234-5678-abcdef012345" \
  -b cookies.txt | jq '.'

# Create a folder
curl -s -X POST "https://cognos-server/api/v1/content" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "defaultName": "Q1 2026 Reports",
    "type": "folder",
    "parent": "/content/team/Financials"
  }'

# Delete content item
curl -s -X DELETE "https://cognos-server/api/v1/content/i12345678-abcd-1234-5678-abcdef012345" \
  -b cookies.txt

# Update content item properties
curl -s -X PUT "https://cognos-server/api/v1/content/i12345678-abcd-1234-5678-abcdef012345" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"defaultName": "Updated Report Name", "defaultDescription": "Revised for Q2"}'
```

### Pagination

```bash
# Content listing with pagination (default page size varies, max 999)
curl -s "https://cognos-server/api/v1/content?parent=/content/team&offset=0&limit=50" \
  -b cookies.txt | jq '{total: .count, items: [.content[] | .defaultName]}'

# Next page
curl -s "https://cognos-server/api/v1/content?parent=/content/team&offset=50&limit=50" \
  -b cookies.txt
```

### Running Reports

```bash
# Run a report synchronously (HTML output)
curl -s -X POST "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/run" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"format": "HTML"}' \
  -o report_output.html

# Run a report synchronously (PDF output)
curl -s -X POST "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/run" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"format": "PDF"}' \
  -o report_output.pdf

# Run with prompt values
curl -s -X POST "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/run" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "format": "CSV",
    "promptValues": [
      {"name": "p_Year", "value": ["2025"]},
      {"name": "p_Region", "value": ["EMEA", "APAC"]}
    ]
  }' \
  -o report_output.csv

# Available output formats: HTML, PDF, CSV, XML, XLSX (spreadsheetML)
```

### Asynchronous Report Execution

```bash
# Start async execution
EXECUTION_ID=$(curl -s -X POST \
  "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/run?async=true" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"format": "PDF"}' \
  | jq -r '.executionID')

# Poll execution status
curl -s "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/executions/${EXECUTION_ID}" \
  -b cookies.txt | jq '.status'
# Status values: running, completed, failed, cancelled

# Download output when completed
curl -s "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/executions/${EXECUTION_ID}/output" \
  -b cookies.txt \
  -o async_report.pdf

# Cancel a running execution
curl -s -X DELETE \
  "https://cognos-server/api/v1/reports/i12345678-abcd-1234-5678-abcdef012345/executions/${EXECUTION_ID}" \
  -b cookies.txt
```

### Dashboard API

```bash
# List dashboards
curl -s "https://cognos-server/api/v1/content?type=exploration&parent=/content/team" \
  -b cookies.txt | jq '.content[] | {id, defaultName}'

# Get dashboard specification
curl -s "https://cognos-server/api/v1/dashboards/iDASH-1234-5678/specification" \
  -b cookies.txt | jq '.'

# List data modules (dashboard data sources)
curl -s "https://cognos-server/api/v1/content?type=dataModule" \
  -b cookies.txt | jq '.content[] | {id, defaultName}'
```

### Users and Groups API

```bash
# List users in a namespace
curl -s "https://cognos-server/api/v1/users?namespace=CorporateAD&limit=50" \
  -b cookies.txt | jq '.users[] | {id, defaultName, email}'

# Get current user profile
curl -s "https://cognos-server/api/v1/session/identity" \
  -b cookies.txt | jq '.'

# List roles
curl -s "https://cognos-server/api/v1/roles" \
  -b cookies.txt | jq '.roles[] | {id, defaultName, members: .members | length}'
```

### Data Sources API

```bash
# List data source connections
curl -s "https://cognos-server/api/v1/datasources" \
  -b cookies.txt | jq '.dataSources[] | {id, defaultName, connectionString}'

# Test a data source connection
curl -s -X POST "https://cognos-server/api/v1/datasources/iDS-1234-5678/test" \
  -b cookies.txt | jq '.status'
```

---

## 7. Report Authoring

### Cognos Analytics Authoring (Web-Based)

Report types:
- **Reports** — pixel-perfect paginated reports (successor to Report Studio)
- **Dashboards** — interactive visual analytics with drag-and-drop
- **Stories** — guided narrative presentations of data
- **Explorations** — AI-assisted data discovery
- **Notebooks** — Jupyter-based data science integration

### Key Authoring Concepts

**Data Items:**
```
Query > Data Items:
  [Revenue] = [FACT_SALES].[AMOUNT]
  [Profit Margin %] = ([Revenue] - [Cost]) / [Revenue] * 100
  [YTD Revenue] = total([Revenue] for report)
  [Running Total] = running-total([Revenue])
```

**Filters:**
```
Detail filter:    [SALES_DATE] >= #prompt('StartDate', 'date')#
Summary filter:   [Revenue] > 100000
Context filter:   Applied at query level before aggregation
```

**Prompts:**
```
Prompt types:
  Value prompt      — dropdown/list selection
  Text box prompt   — free text input
  Date prompt       — calendar picker
  Date range prompt — from/to date pair
  Cascading prompt  — child values filtered by parent selection

Prompt macro: #prompt('ParamName', 'datatype', 'defaultValue')#
Optional prompt:   #promptmany('Region', 'string', '')#
```

**Conditional Formatting:**
```
Style variable > Boolean condition:
  If [Profit Margin %] < 10 → background red, text white
  If [Profit Margin %] between 10 and 25 → background yellow
  If [Profit Margin %] > 25 → background green
```

**Drill-Through:**
```
Source report > Drill-through definition:
  Target: /content/team/Detail Reports/Sales Detail
  Parameters: p_CustomerID = [CUST_ID], p_Year = [YEAR]
  Action: Run the report
  Format: HTML
  Open in: New window
```

### Burst Reports

```
Burst configuration (report properties):
  Burst key:        [SALES_REGION]
  Burst recipient:  Email distribution list per region
  Output format:    PDF
  Delivery method:  Email / Save to folder

Each unique value of the burst key generates a separate output
delivered only to the matching recipient list.

Example: Regional sales report bursts to 5 regions,
each regional manager receives only their region's PDF.
```

### Active Reports

Active Reports are self-contained interactive HTML files that work offline:
- Embed data at report generation time
- Recipients can filter/sort/drill without server connection
- Distributed via email or portal
- Limited to dataset sizes that fit in the HTML file (typically < 100K rows)

---

## 8. Scheduling & Bursting

### Schedule Management

Via Cognos Analytics UI:
1. Open report > Properties > Schedule tab
2. Set frequency: hourly, daily, weekly, monthly, yearly, or custom cron
3. Set time zone, start/end dates
4. Choose format (HTML, PDF, CSV, XLSX)
5. Set delivery: save to content store, email, print, FTP

Via Administration Console:
- View all schedules: Administration > Schedules
- Enable/disable schedules in bulk
- View run history and past outputs

### Credential Management

```
Scheduled reports that hit secured data sources need stored credentials:
  1. Data source signon — stored in content store (encrypted)
  2. Trusted credentials — service account with run-as permissions
  3. Per-user credentials — each user stores their own (for personalized data access)

Best practice: Use a service account signon for batch/scheduled reports
and per-user credentials for interactive sessions.
```

### Event-Based Scheduling

```
Trigger types:
  1. Time-based — cron schedule
  2. Event-based — trigger report after ETL job completes
     - External script calls REST API to trigger the schedule
     - Or use a "trigger" object in content store

# Trigger a schedule via REST API
curl -s -X POST \
  "https://cognos-server/api/v1/content/iSCHEDULE-1234-5678/run" \
  -b cookies.txt
```

### Burst Configuration via API

```bash
# Get report burst options
curl -s "https://cognos-server/api/v1/reports/iREPORT-1234-5678/burstOptions" \
  -b cookies.txt | jq '.'

# Burst distribution is typically configured in the report spec
# and managed via Administration Console > Distribution Lists
```

---

## 9. Data Source Connections

### Connection Types

| Type | Use Case | Configuration |
|---|---|---|
| JDBC | Cross-platform, most common | Driver JAR in `drivers/` directory |
| Native (CLI) | DB2, Oracle — best performance | Requires native client install |
| ODBC | Legacy / Windows sources | ODBC DSN on Cognos server |
| JNDI | Application server managed pools | Rare in standalone installs |

### JDBC Configuration

```bash
# Place JDBC driver JARs in:
/opt/ibm/cognos/analytics/drivers/

# Examples:
# PostgreSQL: postgresql-42.7.x.jar
# SQL Server: mssql-jdbc-12.x.jre11.jar
# Oracle:     ojdbc11.jar
# MySQL:      mysql-connector-j-8.x.jar
# DB2:        db2jcc4.jar

# Restart Cognos after adding drivers
/opt/ibm/cognos/analytics/bin64/cogserver.sh -stop
/opt/ibm/cognos/analytics/bin64/cogserver.sh -start
```

### Connection Strings

```
PostgreSQL:  jdbc:postgresql://host:5432/database
DB2:         jdbc:db2://host:50000/database
SQL Server:  jdbc:sqlserver://host:1433;databaseName=database;encrypt=true
Oracle:      jdbc:oracle:thin:@host:1521:SID
             jdbc:oracle:thin:@//host:1521/service_name
MySQL:       jdbc:mysql://host:3306/database?useSSL=true
```

### Signon Mappings

```
Data Source > Signon:
  1. Credentials stored in content store (encrypted with Cognos crypto keys)
  2. Signon maps Cognos groups/users to database credentials
  3. Multiple signons per data source — matched by group membership

Example:
  Signon "DW_ReadOnly"  → DB user: dw_reader  → Group: All Authenticated Users
  Signon "DW_Admin"     → DB user: dw_admin   → Group: Data Administrators
```

### Query Mode

```
Framework Manager > Data Source > Query Mode:
  Dynamic:    SQL generated per-report, optimized for the target RDBMS
  Compatible: Cognos-generated SQL that works across databases (less optimized)
  Design:     Used only during FM modeling, not in production

Always use Dynamic mode for production — generates vendor-specific SQL
(e.g., DB2 OLAP functions, Oracle analytic functions, SQL Server CTEs).
Compatible mode generates generic SQL that may miss RDBMS optimizations.
```

### Connection Pooling

```xml
<!-- cogstartup.xml — connection pool settings -->
<crn:parameter name="cm.pool.timeout">60</crn:parameter>
<crn:parameter name="cm.pool.max">50</crn:parameter>

<!-- Per data source (set in Administration Console > Data Sources):
     Max connections: 50 (default)
     Connection timeout: 60 seconds
     Idle timeout: 300 seconds
-->
```

---

## 10. Performance

### Dispatcher Routing & Load Balancing

```
Multi-server topology:
  Server 1: Gateway + Content Manager + Dispatcher (admin)
  Server 2: Dispatcher (interactive reports — Report Service, Query Service)
  Server 3: Dispatcher (batch reports — Batch Report Service)
  Server 4: Dispatcher (dashboards — Presentation Service)

Routing rules (Administration Console > Configuration > Dispatchers):
  Route interactive requests to Server 2
  Route scheduled/batch requests to Server 3
  Route dashboard requests to Server 4
  Weighted round-robin between servers of the same type
```

### Query Optimization in Framework Manager

```
Performance techniques:
  1. Minimize star schema fan traps — use determinants
  2. Use model query subjects to pre-join common dimensions
  3. Set query processing to "Database only" (avoid local processing)
  4. Use aggregate tables with aggregate-aware modeling
  5. Add indexes on FM-identified join columns and filter columns
  6. Avoid SELECT * — FM only requests columns used in the report
  7. Use parameterized filters (prompts) to push predicates to the database
```

### Caching

```
Report output caching:
  - Administration Console > Configuration > Report Service
  - Cache size: depends on available memory (default 1GB)
  - Cache life: 60 minutes default, set per report in properties

Query caching:
  - Content Manager caches query metadata
  - Data source query results cached per session
  - Set cache duration in data source properties

Disable caching during development/testing:
  Report Properties > Run Options > Prompt for values every time
```

### Capacity Planning

```
Sizing guidelines (approximate, varies by workload):
  Component        | CPU Cores | RAM    | Notes
  Content Manager  | 4         | 16 GB  | + content store DB resources
  Dispatcher       | 4-8       | 16-32 GB | Per dispatcher node
  Gateway          | 2         | 8 GB   | Scales horizontally
  Content Store DB | 4         | 16 GB  | PostgreSQL/DB2/SQL Server

Concurrent user ratios:
  Named users → Concurrent: typically 10-15% during peak
  100 concurrent interactive users: 2-3 dispatcher nodes
  Heavy batch window: dedicate dispatcher node(s) for batch only
```

### Log Analysis

```bash
# Main service log
/opt/ibm/cognos/analytics/logs/cogserver.log

# HTTP access log (gateway)
/opt/ibm/cognos/analytics/logs/cogaccess.log

# Audit log (who ran what, when)
/opt/ibm/cognos/analytics/logs/cogaudit.log

# IPF request log (detailed per-request tracing)
/opt/ibm/cognos/analytics/logs/ipf/

# Enable verbose logging for troubleshooting (cogstartup.xml or Admin Console)
# Administration > Configuration > Dispatchers > [server] > Logging
# Set component log levels: ERROR, WARN, INFO, DEBUG, TRACE

# Find slow reports in audit log
grep "reportService" /opt/ibm/cognos/analytics/logs/cogaudit.log \
  | awk -F',' '{if ($NF > 30000) print $0}' | head -20

# Monitor active requests
curl -s "https://cognos-server/api/v1/disp/activities" \
  -b cookies.txt | jq '.activities[] | {user, report, duration, status}'
```

### JVM Tuning

```bash
# Edit startup parameters
# /opt/ibm/cognos/analytics/configuration/cogstartup.xml

# JVM heap settings for dispatchers (set via Cognos Configuration):
# Initial heap: 2048 MB
# Max heap: 4096 MB (increase for large concurrent workloads)
# Use G1GC for Cognos 12.x (default on Java 11+)

# Monitor JVM health
jcmd $(pgrep -f "cognos") GC.heap_info
jcmd $(pgrep -f "cognos") VM.flags
```

---

## 11. Cloud Pak for Data

### Cognos Analytics Cartridge on CP4D

Cognos Analytics is available as an add-on service (cartridge) on IBM Cloud Pak for Data (OpenShift-based).

### Deployment via OLM / Operators

```bash
# Prerequisites: CP4D 4.8+ installed on OpenShift 4.12+

# Install the Cognos Analytics operator via OLM
oc apply -f - <<'EOF'
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: ibm-ca-operator
  namespace: ibm-common-services
spec:
  channel: v23.0
  installPlanApproval: Automatic
  name: ibm-ca-operator
  source: ibm-operator-catalog
  sourceNamespace: openshift-marketplace
EOF

# Verify operator pod is running
oc get pods -n ibm-common-services | grep ca-operator

# Create Cognos Analytics service instance (CR)
oc apply -f - <<'EOF'
apiVersion: ca.cpd.ibm.com/v1
kind: CAService
metadata:
  name: ca-service
  namespace: cpd-instance
spec:
  version: "12.0.3"
  license:
    accept: true
    license: Enterprise
  storage_class: ocs-storagecluster-cephfs
  content_store:
    storage_class: ocs-storagecluster-ceph-rbd
    size: 50Gi
  replicas:
    gateway: 2
    cm: 1
    dispatcher: 3
EOF

# Monitor provisioning
oc get caservice ca-service -n cpd-instance -w

# Access URL (via CP4D route)
oc get route cpd -n cpd-instance -o jsonpath='{.spec.host}'
# Navigate to: https://<cpd-route>/cognosanalytics
```

### CP4D Integration

```
CP4D-specific features:
  - Single sign-on via CP4D IAM (automatic, no separate namespace config)
  - Data sources from CP4D catalog (Watson Knowledge Catalog)
  - Shared storage via OpenShift persistent volumes
  - Horizontal scaling via replica count in CR spec
  - Monitoring via CP4D platform monitoring (Prometheus/Grafana)
  - Backup via CP4D backup/restore (cpd-cli backup)

# Scale dispatchers
oc patch caservice ca-service -n cpd-instance --type merge \
  -p '{"spec":{"replicas":{"dispatcher":5}}}'

# Check Cognos service status
oc exec -it $(oc get pod -l app=ca-cm -n cpd-instance -o name | head -1) \
  -n cpd-instance -- /opt/ibm/cognos/analytics/bin64/cogserver.sh -status
```

### Backup on CP4D

```bash
# Use cpd-cli for platform-level backup (includes Cognos content store)
cpd-cli backup create \
  --namespace cpd-instance \
  --include-services ca \
  --backup-name cognos-backup-$(date +%Y%m%d)

# Content store backup (direct, if needed)
oc exec -it $(oc get pod -l app=ca-cs-db -n cpd-instance -o name | head -1) \
  -n cpd-instance -- pg_dump -U cognos cognoscs > /backup/cognos-cs-$(date +%Y%m%d).sql
```

---

## Security — XML / XHTML parsing

<HARD-RULE>
When parsing any XML or XHTML payload from a remote API, untrusted file, or user-supplied source, NEVER use stdlib `xml.etree.ElementTree`, `xml.dom.minidom`, or `lxml.etree.fromstring` without XXE protection. Use `defusedxml` (`pip install defusedxml`) and replace `xml.etree.ElementTree` → `defusedxml.ElementTree`, `lxml.etree` → `defusedxml.lxml`. Stdlib XML parsers expand external entities by default and are vulnerable to billion-laughs / XXE / DTD-retrieval / SSRF-via-entity attacks (CWE-611). Local skill applicability:
- API payloads that may legitimately be XML (storage format, error responses)
- Imported / exported workflow files
- Bulk import / migration paths
</HARD-RULE>

For HTML/XHTML rendering of downstream output (storage format → display), sanitise with `bleach` or `nh3` BEFORE inserting into a browser context — never raw-render API-returned XHTML. See `llm-security` SKILL.md §4.4 for context-appropriate escaping rules.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Granting Everyone access to folders instead of using Cognos groups | Impossible to audit who has access; violates segregation of duties in regulated environments | Create Cognos groups mapped to LDAP/AD groups; assign permissions to groups, never individuals or Everyone |
| Running RUNSTATS-heavy reports during business hours | Long-running reports exhaust dispatcher threads and block interactive users | Schedule heavy reports for off-hours; use burst keys and delivery to distribute output |
| Skipping Framework Manager model governance | Report authors create query subjects that bypass business rules, produce incorrect numbers | Enforce a governed data model with determinants, filters, and security at the FM layer; restrict ad-hoc query access |
| Not monitoring content store growth | Content store bloats with orphaned reports, old outputs, and unused content until performance degrades | Schedule monthly content store audits; archive or delete reports unused for 6+ months; monitor DB size |
| Using REST API without session cleanup | Leaked sessions exhaust the Cognos session pool, causing authentication failures for all users | Always call DELETE /session in a finally block; set session timeouts as a safety net |

---

## Related Skills

| Domain | Skill |
|---|---|
| Enterprise database connectors (DB2, Oracle, SQL Server) | `python-enterprise-connectors` |
| PostgreSQL / MySQL / Redis administration | `rhel-databases`, `ubuntu-databases` |
| Docker / container deployment | `docker-admin`, `rhel-docker-host` |
| LDAP / AD / SSO authentication | `windows-sso`, `linux-centrify` |
| REST API integration patterns | `python-flask-developer` |
| Monitoring and logging | `rhel-monitoring`, `ubuntu-monitoring` |
