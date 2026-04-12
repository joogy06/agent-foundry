# Dashboards, Alerts, and Data Inputs

Reference file for the `splunk-developer` skill. Covers knowledge objects, dashboard XML (Simple XML and Dashboard Studio), alerts/scheduled searches, and data inputs configuration.

## 6. Dashboards

### Simple XML — Basic Dashboard

```xml
<dashboard version="1.1">
  <label>Web Operations Dashboard</label>
  <description>Real-time web traffic and error monitoring</description>

  <row>
    <panel>
      <title>Total Requests (Last 1h)</title>
      <single>
        <search>
          <query>index=web_logs sourcetype=access_combined earliest=-1h | stats count</query>
          <earliest>-1h</earliest>
          <latest>now</latest>
        </search>
        <option name="colorMode">block</option>
        <option name="rangeColors">["0x53a051","0xf8be34","0xf1813f","0xdc4e41"]</option>
        <option name="rangeValues">[0,1000,5000]</option>
        <option name="useColors">true</option>
      </single>
    </panel>
    <panel>
      <title>Error Rate (%)</title>
      <single>
        <search>
          <query>
            index=web_logs sourcetype=access_combined earliest=-1h
            | stats count AS total, count(eval(status>=500)) AS errors
            | eval error_rate=round((errors/total)*100, 2)
            | fields error_rate
          </query>
        </search>
        <option name="rangeColors">["0x53a051","0xf8be34","0xdc4e41"]</option>
        <option name="rangeValues">[2,5]</option>
        <option name="useColors">true</option>
        <option name="unit">%</option>
      </single>
    </panel>
  </row>

  <row>
    <panel>
      <title>Requests Over Time by Status</title>
      <chart>
        <search>
          <query>
            index=web_logs sourcetype=access_combined earliest=-24h
            | timechart span=5m count by status limit=5
          </query>
        </search>
        <option name="charting.chart">area</option>
        <option name="charting.chart.stackMode">stacked</option>
        <option name="charting.legend.placement">bottom</option>
      </chart>
    </panel>
  </row>

  <row>
    <panel>
      <title>Top Error URIs</title>
      <table>
        <search>
          <query>
            index=web_logs sourcetype=access_combined earliest=-1h status>=500
            | stats count, avg(response_time) AS avg_rt by uri_path, status
            | sort - count
            | head 20
          </query>
        </search>
        <option name="drilldown">row</option>
        <drilldown>
          <link target="_blank">
            /app/search/search?q=index%3Dweb_logs%20sourcetype%3Daccess_combined%20uri_path%3D$row.uri_path$%20status%3D$row.status$&amp;earliest=-1h&amp;latest=now
          </link>
        </drilldown>
      </table>
    </panel>
  </row>
</dashboard>
```

### Form Inputs & Tokens

```xml
<form version="1.1">
  <label>Web Log Explorer</label>

  <fieldset submitButton="true" autoRun="false">
    <input type="time" token="time_range">
      <label>Time Range</label>
      <default>
        <earliest>-4h@m</earliest>
        <latest>now</latest>
      </default>
    </input>

    <input type="dropdown" token="selected_index">
      <label>Index</label>
      <choice value="web_logs">Web Logs</choice>
      <choice value="app_logs">Application Logs</choice>
      <choice value="*">All</choice>
      <default>web_logs</default>
    </input>

    <input type="multiselect" token="selected_hosts">
      <label>Hosts</label>
      <search>
        <query>| tstats count WHERE index=web_logs by host | sort host</query>
      </search>
      <fieldForLabel>host</fieldForLabel>
      <fieldForValue>host</fieldForValue>
      <delimiter>,</delimiter>
      <prefix>(</prefix>
      <suffix>)</suffix>
      <valuePrefix>host="</valuePrefix>
      <valueSuffix>"</valueSuffix>
      <default>*</default>
    </input>

    <input type="text" token="search_term">
      <label>Search Term</label>
      <default>*</default>
    </input>
  </fieldset>

  <row>
    <panel>
      <chart>
        <search>
          <query>
            index=$selected_index$ sourcetype=access_combined $selected_hosts$ $search_term$
            | timechart span=5m count by status
          </query>
          <earliest>$time_range.earliest$</earliest>
          <latest>$time_range.latest$</latest>
        </search>
      </chart>
    </panel>
  </row>
</form>
```

### Base Search Pattern (Performance)

```xml
<dashboard version="1.1">
  <label>Efficient Dashboard</label>

  <!-- Base search runs once, panels reference its results -->
  <search id="base_web_search">
    <query>
      index=web_logs sourcetype=access_combined earliest=-1h
      | stats count AS requests, count(eval(status>=500)) AS errors,
              avg(response_time) AS avg_rt, dc(clientip) AS unique_clients
              by host, uri_path, status
    </query>
    <earliest>-1h</earliest>
    <latest>now</latest>
  </search>

  <row>
    <panel>
      <single>
        <search base="base_web_search">
          <query>| stats sum(requests) AS total_requests</query>
        </search>
      </single>
    </panel>
    <panel>
      <chart>
        <search base="base_web_search">
          <query>| stats sum(requests) by host</query>
        </search>
        <option name="charting.chart">pie</option>
      </chart>
    </panel>
  </row>
</dashboard>
```

### Dashboard Studio (JSON-Based)

Dashboard Studio uses a JSON definition and supports absolute positioning, trellis layouts, and chained searches. Create in Splunk Web via Dashboards > Create New Dashboard > Dashboard Studio.

Key concepts:
- **dataSources**: define SPL searches (primary and chained).
- **visualizations**: map data sources to chart/table/single-value/map components.
- **layout**: absolute positioning with `x`, `y`, `width`, `height`.
- **inputs**: tokens with `type` (dropdown, text, time).
- **defaults**: pre-set token values.

```json
{
  "dataSources": {
    "ds_requests": {
      "type": "ds.search",
      "options": {
        "query": "index=web_logs sourcetype=access_combined | timechart span=5m count by status",
        "queryParameters": {
          "earliest": "-4h@m",
          "latest": "now"
        }
      }
    },
    "ds_error_detail": {
      "type": "ds.search",
      "options": {
        "query": "index=web_logs sourcetype=access_combined status>=500 | stats count by uri_path, status | sort - count | head 10"
      }
    }
  },
  "visualizations": {
    "viz_timechart": {
      "type": "splunk.area",
      "dataSources": { "primary": "ds_requests" },
      "options": { "stackMode": "stacked" },
      "title": "Requests Over Time"
    },
    "viz_error_table": {
      "type": "splunk.table",
      "dataSources": { "primary": "ds_error_detail" },
      "title": "Top Errors"
    }
  },
  "layout": {
    "type": "absolute",
    "options": { "width": 1440, "height": 900 },
    "structure": [
      { "item": "viz_timechart", "position": { "x": 20, "y": 20, "w": 1400, "h": 400 } },
      { "item": "viz_error_table", "position": { "x": 20, "y": 440, "w": 1400, "h": 400 } }
    ]
  }
}
```

---

## 7. Alerts & Scheduled Searches

### Alert Types

```spl
# Per-result alert — fires once for EACH result row
index=auth_logs sourcetype=linux_secure "Failed password" earliest=-5m
| stats count by src_ip, user
| where count > 10

# Number of results alert — fires when result count exceeds threshold
index=web_logs sourcetype=access_combined status>=500 earliest=-5m
| stats count
| where count > 100

# Rolling window — compare current vs historical baseline
index=web_logs sourcetype=access_combined earliest=-1h
| stats count AS current_count
| appendcols
  [search index=web_logs sourcetype=access_combined earliest=-8d@d latest=-7d@d
   | stats count AS baseline_count]
| eval deviation=round(((current_count - baseline_count) / baseline_count) * 100, 1)
| where deviation > 50 OR deviation < -50
```

### savedsearches.conf

```ini
[High Error Rate Alert]
search = index=web_logs sourcetype=access_combined earliest=-5m \
| stats count AS total, count(eval(status>=500)) AS errors \
| eval error_rate=round((errors/total)*100,2) \
| where error_rate > 5
cron_schedule = */5 * * * *
dispatch.earliest_time = -5m
dispatch.latest_time = now
is_scheduled = 1
alert_type = number of events
alert_comparator = greater than
alert_threshold = 0
alert.suppress = 1
alert.suppress.period = 15m
alert.suppress.fields = *

# Actions
action.email = 1
action.email.to = ops-team@example.com
action.email.subject = High Error Rate Alert: $result.error_rate$%
action.email.message.alert = Error rate is $result.error_rate$% (threshold: 5%). Total requests: $result.total$, errors: $result.errors$.

action.webhook = 1
action.webhook.param.url = https://hooks.slack.com/services/T00/B00/xxx

# Throttling
alert.suppress = 1
alert.suppress.period = 30m
alert.suppress.fields = error_rate
```

### Summary Indexing & Accelerated Reports

```spl
# Collect command — write summary data to a summary index
index=web_logs sourcetype=access_combined earliest=-1h latest=now
| stats count AS requests, avg(response_time) AS avg_rt,
        perc95(response_time) AS p95_rt by host, uri_path
| eval _time=now()
| collect index=summary source="web_hourly_summary" marker="report=web_hourly"

# Search the summary index
index=summary source="web_hourly_summary" earliest=-7d
| timechart span=1h avg(avg_rt) by host
```

### tstats — Accelerated Data Model Queries

```spl
# 100x faster than raw search — uses TSIDX files from accelerated data model
| tstats count FROM datamodel=Web WHERE Web.status>=500
  BY Web.src, Web.dest, _time span=5m

# With additional filters
| tstats summariesonly=true count AS requests,
         avg(Web.response_time) AS avg_rt
  FROM datamodel=Web
  WHERE Web.status>=200 AND Web.dest="web-prod-*"
  BY Web.dest, Web.action, _time span=1h

# tstats against raw indexed data (no data model required)
| tstats count WHERE index=web_logs sourcetype=access_combined BY host, _time span=5m
```

Use `summariesonly=true` to search only accelerated data (faster, but misses non-accelerated events). Omit it or set `summariesonly=false` to fall back to raw data when acceleration gaps exist.

---

## 8. Data Inputs

### Universal / Heavy Forwarder

**inputs.conf (Universal Forwarder):**

```ini
[monitor:///var/log/httpd/access_log]
disabled = false
sourcetype = access_combined
index = web_logs

[monitor:///var/log/httpd/error_log]
disabled = false
sourcetype = apache_error
index = web_logs

[monitor:///var/log/application/*.log]
disabled = false
sourcetype = application
index = app_logs
# Whitelist/blacklist log files
whitelist = \.log$
blacklist = \.gz$

[monitor:///var/log/secure]
disabled = false
sourcetype = linux_secure
index = auth_logs
```

**outputs.conf (Universal Forwarder):**

```ini
[tcpout]
defaultGroup = primary_indexers

[tcpout:primary_indexers]
server = idx01.example.com:9997, idx02.example.com:9997
compressed = true
useACK = true

[tcpout:secondary_indexers]
server = idx03.example.com:9997
disabled = true
```

### HTTP Event Collector (HEC)

```bash
# Enable HEC on the indexer/heavy forwarder
# Settings > Data Inputs > HTTP Event Collector > Global Settings > Enabled

# Create a HEC token via REST API
curl -k -u admin:password \
  https://splunk.example.com:8089/servicesNS/admin/splunk_httpinput/data/inputs/http \
  -d name=app_events \
  -d index=app_logs \
  -d sourcetype=json_events \
  -d useACK=false
```

```bash
# Send event via HEC (event endpoint — Splunk extracts timestamp)
curl -k \
  https://splunk.example.com:8088/services/collector/event \
  -H "Authorization: Splunk <HEC_TOKEN>" \
  -d '{"event": {"action": "login", "user": "jsmith", "result": "success"}, "sourcetype": "json_events", "index": "app_logs"}'

# Send raw event (raw endpoint — relies on props.conf for parsing)
curl -k \
  https://splunk.example.com:8088/services/collector/raw \
  -H "Authorization: Splunk <HEC_TOKEN>" \
  -H "X-Splunk-Request-Channel: $(uuidgen)" \
  -d '2026-03-31 10:15:30 INFO user=jsmith action=login result=success'

# Batch events (newline-delimited JSON)
curl -k \
  https://splunk.example.com:8088/services/collector/event \
  -H "Authorization: Splunk <HEC_TOKEN>" \
  -d '{"event": {"msg": "event1"}, "sourcetype": "json_events", "index": "app_logs"}
{"event": {"msg": "event2"}, "sourcetype": "json_events", "index": "app_logs"}'
```

HEC with acknowledgement (`useACK=true`): POST returns `ackId`, query `/services/collector/ack` to confirm indexing.

### props.conf — Data Parsing

```ini
[my_custom_sourcetype]
# Timestamp extraction
TIME_FORMAT = %Y-%m-%dT%H:%M:%S.%3N%z
TIME_PREFIX = ^
MAX_TIMESTAMP_LOOKAHEAD = 35

# Line breaking
SHOULD_LINEMERGE = false
LINE_BREAKER = ([\r\n]+)

# Truncation (default 10000 bytes)
TRUNCATE = 50000

# Character encoding
CHARSET = UTF-8

# Event breaking for multiline (e.g., Java stack traces)
# SHOULD_LINEMERGE = true
# BREAK_ONLY_BEFORE = ^\d{4}-\d{2}-\d{2}
# MAX_EVENTS = 1000
```

### Syslog Input (TCP/UDP)

```ini
# inputs.conf
[udp://514]
disabled = false
sourcetype = syslog
index = os_logs
connection_host = dns

[tcp://1514]
disabled = false
sourcetype = syslog
index = os_logs
connection_host = dns
```

---

## 9. Advanced SPL

### eventstats / streamstats

```spl
# eventstats — adds aggregation as a new field to every event (no reduction)
index=web_logs sourcetype=access_combined earliest=-1h
| eventstats avg(response_time) AS global_avg_rt, stdev(response_time) AS stdev_rt
| eval is_slow=if(response_time > (global_avg_rt + 2*stdev_rt), "yes", "no")
| where is_slow="yes"
| table _time, host, uri_path, response_time, global_avg_rt

# streamstats — running/cumulative calculations (row by row, ordered)
index=web_logs sourcetype=access_combined earliest=-24h
| sort _time
| streamstats count AS running_count,
               avg(response_time) AS running_avg_rt,
               window=100
| eval drift=response_time - running_avg_rt

# streamstats — running count per host (reset on new host)
index=app_logs sourcetype=application earliest=-1h log_level=ERROR
| sort host, _time
| streamstats count AS error_sequence by host reset_after="\"log_level\"!=\"ERROR\""
```

### append / appendpipe / appendcols

```spl
# append — combine results of two independent searches
index=web_logs sourcetype=access_combined earliest=-1h
| stats count AS web_requests by host
| append
  [search index=app_logs sourcetype=application earliest=-1h
   | stats count AS app_events by host]
| stats values(web_requests) AS web_requests, values(app_events) AS app_events by host

# appendpipe — add summary row to existing results
index=web_logs sourcetype=access_combined earliest=-1h
| stats count by host
| appendpipe [stats sum(count) AS count | eval host="TOTAL"]
| sort - count

# appendcols — side-by-side results from different searches
index=web_logs sourcetype=access_combined earliest=-1h
| stats count AS current_requests
| appendcols
  [search index=web_logs sourcetype=access_combined earliest=-25h latest=-24h
   | stats count AS previous_requests]
| eval change_pct=round(((current_requests - previous_requests) / previous_requests) * 100, 1)
```

### map — Iterative Subsearch

```spl
# Run a search for each result of a prior search
index=auth_logs sourcetype=linux_secure "Failed password" earliest=-1h
| stats count by src_ip
| where count > 5
| head 10
| map maxsearches=10 search="search index=web_logs sourcetype=access_combined clientip=\"$src_ip$\" earliest=-1h
  | stats count AS web_hits, values(uri_path) AS pages by clientip"
```

### predict / anomalydetection

```spl
# Time series forecasting
index=web_logs sourcetype=access_combined earliest=-30d
| timechart span=1h count AS requests
| predict requests as predicted_requests algorithm=LLP5 future_timespan=24 holdback=0
| eval lower=predicted_requests - 2*sqrt(predicted_requests)
| eval upper=predicted_requests + 2*sqrt(predicted_requests)

# Anomaly detection
index=web_logs sourcetype=access_combined earliest=-7d
| timechart span=1h count by host
| anomalydetection method=histogram action=annotate
| where isOutlier > 0
```

### multisearch

```spl
# Run independent searches in parallel and combine
| multisearch
  [search index=web_logs sourcetype=access_combined earliest=-1h | stats count AS web_count]
  [search index=app_logs sourcetype=application earliest=-1h | stats count AS app_count]
  [search index=auth_logs sourcetype=linux_secure earliest=-1h | stats count AS auth_count]
```

### cluster / kmeans

```spl
# Cluster similar events (log deduplication/pattern recognition)
index=app_logs sourcetype=application earliest=-1h log_level=ERROR
| cluster showcount=true
| sort - cluster_count
| dedup _raw
| table cluster_count, _raw

# kmeans clustering on numeric fields
index=web_logs sourcetype=access_combined earliest=-24h
| stats count, avg(response_time) AS avg_rt by clientip
| kmeans k=4 count avg_rt
| stats count by cluster_label
```

---

