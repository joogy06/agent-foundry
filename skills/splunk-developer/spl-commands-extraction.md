# SPL Fundamentals, Transforming Commands, and Data Extraction

Reference file for the `splunk-developer` skill. Covers SPL query basics, transforming commands (stats, chart, timechart, eval, rex), data extraction patterns, and lookups.

## 1. SPL Fundamentals

### Search Syntax

```spl
# Basic search — always specify index and sourcetype
index=web_logs sourcetype=access_combined status=500

# Boolean operators (AND is implicit between terms)
index=web_logs sourcetype=access_combined (status=500 OR status=503) NOT uri="/healthcheck"

# Wildcards
index=app_logs sourcetype=application host=web-prod-* error*

# Field existence
index=app_logs sourcetype=application user=* NOT user=""

# Quoted strings for exact match
index=app_logs sourcetype=application "connection refused"
```

### Time Modifiers

```spl
# Relative time (earliest/latest)
index=web_logs sourcetype=access_combined earliest=-24h latest=now

# Snap-to time (@ snaps to beginning of unit)
index=web_logs sourcetype=access_combined earliest=-7d@d latest=@d

# Absolute time
index=web_logs sourcetype=access_combined earliest="03/25/2026:00:00:00" latest="03/26/2026:00:00:00"

# Relative time modifiers
# -15m  = 15 minutes ago
# -4h   = 4 hours ago
# -7d   = 7 days ago
# -1mon = 1 month ago
# @d    = snap to beginning of today
# @w0   = snap to beginning of this week (Sunday)
# @mon  = snap to beginning of this month
```

### Subsearches

```spl
# Subsearch returns results used by outer search
index=web_logs sourcetype=access_combined
  [search index=threat_intel sourcetype=ip_blocklist earliest=-1h
   | fields src_ip
   | rename src_ip AS clientip]

# Subsearch with format (returns OR'd values)
index=app_logs sourcetype=application
  [search index=incidents sourcetype=tickets status=open
   | fields affected_host
   | rename affected_host AS host
   | format]
```

### Search Modes & Optimization

```
Fast mode:   Field discovery off, only returns fields in search. Best for dashboards.
Smart mode:  Field discovery for transforming searches, full for raw events.
Verbose mode: Full field discovery, all event data. Use only for investigation.
```

Optimization checklist:
1. Specify `index=` and `sourcetype=` (narrows data to scan).
2. Narrow time range as much as possible.
3. Place restrictive terms early in the search (before pipes).
4. Use `fields` command to limit fields passed through the pipeline.
5. Avoid `NOT` on high-cardinality fields — use inclusion instead.
6. Use `TERM()` for searching indexed tokens: `index=web_logs TERM(error_code=E5012)`.

---

## 2. Transforming Commands

### stats

```spl
# Count by status code
index=web_logs sourcetype=access_combined earliest=-1h
| stats count by status

# Multiple aggregations
index=web_logs sourcetype=access_combined earliest=-24h
| stats count, avg(response_time) AS avg_rt, max(response_time) AS max_rt,
        dc(clientip) AS unique_clients, values(uri_path) AS paths by host

# Nested stats — percentile calculations
index=web_logs sourcetype=access_combined earliest=-1h
| stats count AS requests, avg(response_time) AS avg_rt,
        perc95(response_time) AS p95_rt, perc99(response_time) AS p99_rt by uri_path
| sort - p95_rt

# list vs values — list preserves duplicates, values deduplicates
index=app_logs sourcetype=application earliest=-1h
| stats list(action) AS all_actions, values(action) AS unique_actions by session_id
```

### chart / timechart

```spl
# Timechart — events over time with automatic bucketing
index=web_logs sourcetype=access_combined earliest=-24h
| timechart span=5m count by status limit=10

# Timechart — average response time by host
index=web_logs sourcetype=access_combined earliest=-7d
| timechart span=1h avg(response_time) AS avg_rt by host

# Chart — two-dimensional table
index=web_logs sourcetype=access_combined earliest=-24h
| chart count over uri_path by status limit=5

# Timechart with where clause and null handling
index=app_logs sourcetype=application earliest=-24h
| timechart span=15m count AS total, count(eval(log_level="ERROR")) AS errors
| eval error_rate=round((errors/total)*100, 2)
| where error_rate > 5
```

### eval

```spl
# Conditional logic with if/case
index=web_logs sourcetype=access_combined earliest=-1h
| eval status_group=case(
    status>=200 AND status<300, "2xx_success",
    status>=300 AND status<400, "3xx_redirect",
    status>=400 AND status<500, "4xx_client_error",
    status>=500, "5xx_server_error",
    1=1, "unknown")
| stats count by status_group

# String manipulation
index=app_logs sourcetype=application earliest=-1h
| eval short_host=mvindex(split(host, "."), 0)
| eval message_upper=upper(message)
| eval uri_len=len(uri_path)

# Time functions
index=web_logs sourcetype=access_combined earliest=-24h
| eval hour=strftime(_time, "%H")
| eval day_of_week=strftime(_time, "%A")
| eval epoch_time=_time
| eval formatted=strftime(_time, "%Y-%m-%d %H:%M:%S")

# Parse time strings into epoch
index=app_logs sourcetype=application earliest=-1h
| eval parsed_time=strptime(timestamp_field, "%Y-%m-%dT%H:%M:%S.%3N%z")

# Coalesce — first non-null value
index=app_logs sourcetype=application earliest=-1h
| eval user=coalesce(authenticated_user, session_user, "anonymous")

# Multivalue functions
index=app_logs sourcetype=application earliest=-1h
| eval tag_list=split(tags, ",")
| eval first_tag=mvindex(tag_list, 0)
| eval has_critical=if(mvfind(tag_list, "critical") >= 0, "yes", "no")
| eval filtered=mvfilter(match(tag_list, "^prod-"))

# Type conversions
index=app_logs sourcetype=application earliest=-1h
| eval bytes_num=tonumber(bytes)
| eval status_str=tostring(status)
| eval size_mb=round(tonumber(bytes)/1048576, 2)
```

### where vs search

```spl
# where — evaluates expressions (supports functions, comparisons, math)
index=web_logs sourcetype=access_combined earliest=-1h
| stats avg(response_time) AS avg_rt by uri_path
| where avg_rt > 2000

# where with functions (cidrmatch, like, match)
index=web_logs sourcetype=access_combined earliest=-1h
| where cidrmatch("10.0.0.0/8", clientip) AND like(uri_path, "/api/%")

# search — filters using Splunk search syntax (simpler, uses wildcards)
index=web_logs sourcetype=access_combined earliest=-1h
| stats count by uri_path, status
| search uri_path="/api/*" status=5*
```

Use `where` for computed/numeric comparisons; use `search` for wildcard/keyword filtering.

### Other Essential Commands

```spl
# table — select and order columns
index=web_logs sourcetype=access_combined earliest=-1h status=500
| table _time, host, clientip, uri_path, status, response_time

# rename
| rename clientip AS "Client IP", response_time AS "Response Time (ms)"

# sort — descending with minus prefix
| sort - count limit=20

# dedup — remove duplicate combinations
index=app_logs sourcetype=application earliest=-24h
| dedup host, error_code sortby -_time
| table _time, host, error_code, message

# top / rare
index=web_logs sourcetype=access_combined earliest=-1h
| top limit=10 uri_path by host showperc=true

index=app_logs sourcetype=application earliest=-24h
| rare limit=10 error_code

# transaction — group events into transactions (use sparingly, resource-intensive)
index=web_logs sourcetype=access_combined earliest=-1h
| transaction clientip maxspan=30m maxpause=5m
| where duration > 60
| table clientip, duration, eventcount
```

---

## 3. Data Extraction

### rex — Regex Field Extraction

```spl
# Extract fields with named capture groups
index=app_logs sourcetype=application earliest=-1h
| rex field=_raw "user=(?<username>\w+)\s+action=(?<action>\w+)\s+result=(?<result>\w+)"
| stats count by username, action, result

# Extract multiple values (max_match=0 for all matches)
index=app_logs sourcetype=application earliest=-1h "SQL query"
| rex field=_raw max_match=0 "table\s+(?<table_name>\w+)"
| stats values(table_name) AS tables by host

# rex mode=sed — inline substitution
index=app_logs sourcetype=application earliest=-1h
| rex field=message mode=sed "s/password=[^\s&]+/password=REDACTED/g"

# Extract from structured log (key=value pairs)
index=app_logs sourcetype=application earliest=-1h
| rex field=_raw "latency=(?<latency_ms>\d+)ms"
| eval latency_ms=tonumber(latency_ms)
| where latency_ms > 500
```

### spath — JSON/XML Extraction

```spl
# Auto-extract all JSON fields
index=app_logs sourcetype=json_events earliest=-1h
| spath

# Extract specific JSON path
index=app_logs sourcetype=json_events earliest=-1h
| spath path=response.status output=resp_status
| spath path=response.headers.content-type output=content_type
| stats count by resp_status, content_type

# Nested arrays
index=app_logs sourcetype=json_events earliest=-1h
| spath path=items{} output=items
| mvexpand items
| spath input=items path=name output=item_name
| stats count by item_name

# XML extraction
index=app_logs sourcetype=xml_events earliest=-1h
| spath path=envelope.body.response.code output=resp_code
```

### props.conf / transforms.conf — Persistent Extractions

**Search-time extraction** (`$SPLUNK_HOME/etc/apps/<app>/local/props.conf`):

```ini
[my_custom_sourcetype]
# Inline regex extraction (search-time)
EXTRACT-username = user=(?<username>\w+)
EXTRACT-latency = latency=(?<latency_ms>\d+)ms

# Reference transforms.conf for complex extractions
REPORT-error_fields = extract_error_code, extract_error_msg

# Calculated fields (eval at search time)
EVAL-latency_sec = latency_ms / 1000
EVAL-status_group = case(status>=200 AND status<300, "success", status>=400, "error", 1=1, "other")

# Field aliases
FIELDALIAS-src = clientip AS src_ip
FIELDALIAS-dest = server AS dest_ip
```

**transforms.conf:**

```ini
[extract_error_code]
REGEX = error_code=(\d+)
FORMAT = error_code::$1

[extract_error_msg]
REGEX = error_msg="([^"]+)"
FORMAT = error_msg::$1
```

Index-time extractions go in `props.conf` with `TRANSFORMS-` prefix and matching `transforms.conf` entry with `WRITE_META = true`. Use index-time extraction only when the field is needed for routing or when search-time cost is prohibitive.

---

## 4. Lookups

### CSV Lookup

Create file `$SPLUNK_HOME/etc/apps/<app>/lookups/asset_inventory.csv`:

```csv
ip_address,hostname,department,criticality,owner
10.0.1.10,web-prod-01,Engineering,high,teamA
10.0.1.11,web-prod-02,Engineering,high,teamA
10.0.2.20,db-prod-01,DBA,critical,teamB
```

**transforms.conf:**

```ini
[asset_lookup]
filename = asset_inventory.csv
```

**props.conf** (automatic lookup):

```ini
[access_combined]
LOOKUP-asset_enrich = asset_lookup ip_address AS clientip OUTPUT hostname, department, criticality, owner
```

### Using Lookups in SPL

```spl
# Manual lookup
index=web_logs sourcetype=access_combined earliest=-1h
| lookup asset_inventory.csv ip_address AS clientip OUTPUT hostname, department, criticality
| stats count by department, criticality

# Input lookup — use lookup as a data source
| inputlookup asset_inventory.csv
| search criticality="critical"
| table ip_address, hostname, owner

# Output lookup — write search results to a lookup table
index=web_logs sourcetype=access_combined earliest=-24h
| stats count AS request_count, dc(uri_path) AS unique_pages by clientip
| where request_count > 10000
| outputlookup high_traffic_ips.csv
```

### KV Store Lookup

**collections.conf:**

```ini
[kv_app_config]
enforceTypes = true
field.key = string
field.value = string
field.updated_by = string
field.updated_at = number
```

**transforms.conf:**

```ini
[kv_app_config_lookup]
external_type = kvstore
collection = kv_app_config
fields_list = _key, key, value, updated_by, updated_at
```

```spl
# Read from KV Store
| inputlookup kv_app_config_lookup
| table key, value, updated_by

# Write to KV Store
| makeresults
| eval key="max_retries", value="5", updated_by="admin", updated_at=now()
| outputlookup kv_app_config_lookup append=true
```

### Lookup Performance

- CSV lookups load into memory — keep under 100 MB.
- KV Store lookups use MongoDB backend — better for frequent writes and >100K rows.
- Use `local=true` for lookups only needed on the search head.
- Automatic lookups run on every search matching the sourcetype — disable for rarely needed enrichment.
- Geospatial lookups (`.kmz`) enable `geom` command for choropleth maps.

---

## 5. Knowledge Objects

### Event Types & Tags

**eventtypes.conf:**

```ini
[web_error]
search = index=web_logs sourcetype=access_combined (status>=400)

[web_server_error]
search = index=web_logs sourcetype=access_combined (status>=500)

[failed_login]
search = index=auth_logs sourcetype=linux_secure "Failed password"
```

**tags.conf:**

```ini
[eventtype=web_error]
error = enabled
web = enabled

[eventtype=failed_login]
authentication = enabled
failure = enabled
```

```spl
# Search by tag
tag=authentication tag=failure earliest=-24h
| stats count by src_ip, user
| sort - count
```

### Macros

**macros.conf:**

```ini
[critical_hosts]
definition = (host="web-prod-*" OR host="db-prod-*" OR host="app-prod-*")
iseval = 0

[error_rate(2)]
args = index_name, threshold
definition = search index=$index_name$ sourcetype=access_combined earliest=-1h | timechart span=5m count AS total, count(eval(status>=500)) AS errors | eval error_rate=round((errors/total)*100,2) | where error_rate > $threshold$
iseval = 0

[relative_time_format(1)]
args = time_field
definition = eval formatted_time=strftime($time_field$, "%Y-%m-%d %H:%M:%S")
iseval = 0
```

```spl
# Use macros (backtick syntax)
index=web_logs sourcetype=access_combined `critical_hosts` earliest=-1h
| stats count by host, status

# Macro with arguments
`error_rate(web_logs, 5)`

# Nested macro usage
index=app_logs sourcetype=application earliest=-1h
| `relative_time_format(_time)`
| table formatted_time, host, message
```

### Data Models

**datamodels.conf (simplified):**

```ini
[Web]
acceleration = true
acceleration.earliest_time = -3mon
acceleration.cron_schedule = */5 * * * *
```

Data model hierarchy example (Web data model):

```
Web
├── Web (root dataset)
│   ├── constraint: (index=web_logs sourcetype=access_combined)
│   ├── fields: action, app, bytes, cached, category, ...
│   ├── Web.Successful (child)
│   │   └── constraint: (status>=200 AND status<400)
│   └── Web.Error (child)
│       └── constraint: (status>=400)
```

### CIM (Common Information Model) Compliance

Map your data to CIM field names for cross-source correlation and Splunk Enterprise Security:

| CIM Field | Your Field | Mapping |
|---|---|---|
| `src` | `clientip` | Field alias in props.conf |
| `dest` | `server_ip` | Field alias |
| `action` | `http_method` | Calculated field |
| `status` | `http_status` | Field alias |
| `user` | `authenticated_user` | Field alias |
| `bytes_in` | `request_size` | Field alias |
| `bytes_out` | `response_size` | Field alias |

```ini
# props.conf — CIM mapping
[access_combined]
FIELDALIAS-cim_src = clientip AS src
FIELDALIAS-cim_dest = server_ip AS dest
FIELDALIAS-cim_user = authenticated_user AS user
EVAL-action = lower(http_method)
```

---

