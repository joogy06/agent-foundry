---
name: jira-rest-api
description: Use when interacting with Jira programmatically via REST API — API v2 and v3 endpoints, authentication (API tokens, OAuth, PAT), issue CRUD (search via JQL — /rest/api/3/search/jql on Cloud, /rest/api/2/search on Data Center), status category mapping, sprint/board queries (Agile API), comments, attachments, labels, pagination (nextPageToken cursor on Cloud, startAt + maxResults on Data Center), rate limiting, error handling, and webhooks. Works with both Jira Cloud and Data Center.
---

# Jira REST API

<HARD-RULE>
NEVER hardcode credentials. Store API tokens, passwords, and OAuth secrets in environment variables or a secrets manager. Never embed them in source code or command history.
</HARD-RULE>

<HARD-RULE>
Respect rate limits. Jira Cloud enforces per-user rate limits. Implement exponential backoff with retry logic. Check `Retry-After` and `X-RateLimit-*` headers. Never tight-loop API calls.
</HARD-RULE>

<HARD-RULE>
Map statuses via `statusCategory.key` (new/indeterminate/done), NOT individual status names. Status names vary per project and workflow. statusCategory is universal.
</HARD-RULE>

## 1. Authentication

### API Tokens (Cloud) -- Basic Auth with email + token
```bash
export JIRA_BASE="https://yoursite.atlassian.net"
export JIRA_USER="you@company.com"
export JIRA_TOKEN="your-api-token"
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" "${JIRA_BASE}/rest/api/2/myself"
```
```python
import os, requests
BASE = os.environ["JIRA_BASE"]
AUTH = (os.environ["JIRA_USER"], os.environ["JIRA_TOKEN"])
resp = requests.get(f"{BASE}/rest/api/2/myself", auth=AUTH)
```

### Personal Access Tokens (Data Center 8.14+) -- Bearer token, no username
```bash
curl -s -H "Authorization: Bearer ${JIRA_PAT}" "${JIRA_BASE}/rest/api/2/myself"
```
```python
headers = {"Authorization": f"Bearer {os.environ['JIRA_PAT']}", "Accept": "application/json"}
resp = requests.get(f"{BASE}/rest/api/2/myself", headers=headers)
```

### OAuth 2.0 (Cloud 3LO) -- for Connect/Forge apps
```python
token_resp = requests.post("https://auth.atlassian.com/oauth/token", json={
    "grant_type": "authorization_code", "client_id": os.environ["OAUTH_CLIENT_ID"],
    "client_secret": os.environ["OAUTH_CLIENT_SECRET"], "code": auth_code,
    "redirect_uri": "https://yourapp.com/callback"})
access_token = token_resp.json()["access_token"]
# Get cloud_id, then: /ex/jira/{cloud_id}/rest/api/3/...
```

| Credential Storage | Use Case |
|---|---|
| Environment variables | Local dev, CI/CD |
| HashiCorp Vault / AWS Secrets Manager | Production |
| `.env` + python-dotenv (in `.gitignore`) | Local dev |

## 2. API Versions

**v2** (`/rest/api/2/`) -- Data Center's primary version. Most v2 endpoints also work on Cloud, with one critical exception: `/rest/api/2/search` (and `/rest/api/3/search`) were REMOVED from Cloud in 2025 — on Cloud use `/rest/api/2/search/jql` or `/rest/api/3/search/jql` instead (see §3).
**v3** (`/rest/api/3/`) -- Cloud-only, richer Atlassian Document Format (ADF) for descriptions/comments. Preferred for new Cloud integrations.

| Use v2 when | Use v3 when |
|---|---|
| Targeting Data Center | Cloud + need ADF rich text |
| Broadest compatibility | Building new Cloud integrations |
| Simple text descriptions | Structured document content |

## 3. Issues -- Search (JQL)

JQL (Jira Query Language) is the primary search mechanism. **The search endpoint differs by deployment:**

| Deployment | Endpoint | Pagination |
|---|---|---|
| **Cloud** | `GET/POST /rest/api/3/search/jql` (also `/rest/api/2/search/jql`) | `nextPageToken` cursor |
| **Data Center** | `GET/POST /rest/api/2/search` | `startAt` + `maxResults` offset |

> Atlassian deprecated `GET/POST /rest/api/2|3/search` on **Cloud** (announced 2024) and removed it (progressive shutdown Aug 1 – Oct 31, 2025) — calls now return `410 Gone`. **Data Center keeps the classic `/rest/api/2/search` endpoint.**

### Cloud: `/rest/api/3/search/jql`

```python
def jql_search(jql, fields="summary,status,priority,assignee,updated",
               max_results=50, next_page_token=None):
    """Jira CLOUD search. The classic /rest/api/2|3/search was removed from Cloud in 2025."""
    params = {"jql": jql, "fields": fields, "maxResults": max_results}
    if next_page_token:
        params["nextPageToken"] = next_page_token
    resp = requests.get(f"{BASE}/rest/api/3/search/jql", auth=AUTH, params=params)
    resp.raise_for_status()
    return resp.json()  # {"issues": [...], "nextPageToken": "..."} -- NO "total" field

# Assigned to current user
jql_search("assignee = currentUser() ORDER BY updated DESC")
# By project and status
jql_search('project = "DEV" AND status = "In Progress"')
# Recently updated
jql_search("updated >= -7d ORDER BY updated DESC")
# By sprint
jql_search('sprint in openSprints() AND project = "DEV"')
# By label
jql_search('labels = "backend" AND status != Done')
# Children of an epic (Cloud: use `parent` -- the legacy "Epic Link" field is retired on Cloud)
jql_search('parent = DEV-100')
# Complex filter
jql_search('project = "DEV" AND priority in (Critical, High) AND status != Done AND assignee = currentUser()')
```

```bash
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" --get "${JIRA_BASE}/rest/api/3/search/jql" \
  --data-urlencode 'jql=assignee = currentUser() ORDER BY updated DESC' \
  --data-urlencode 'maxResults=10' --data-urlencode 'fields=summary,status,priority'
```

Cloud response semantics (changed vs the removed endpoint):
- **`total` is NOT returned.** If you need a count, use `POST /rest/api/3/search/approximate-count` with body `{"jql": "..."}` (see §10).
- **`maxResults` is a hint, not a guarantee** — the API may return fewer items per page than requested (≤100/page when fields are requested; up to 5000/page when requesting only `id`). Never infer "last page" from result count — rely on `nextPageToken` absence (or `isLast: true`).
- For long JQL strings, use `POST /rest/api/3/search/jql` with a JSON body to avoid URL length limits.

### Data Center: `/rest/api/2/search` (Data-Center-only)

```python
def jql_search_dc(jql, fields="summary,status,priority,assignee,updated", max_results=50, start_at=0):
    """Jira DATA CENTER search -- classic offset pagination. REMOVED on Cloud (410 Gone)."""
    resp = requests.get(f"{BASE}/rest/api/2/search", auth=AUTH, params={
        "jql": jql, "fields": fields, "maxResults": max_results, "startAt": start_at})
    resp.raise_for_status()
    return resp.json()  # {"issues": [...], "startAt": 0, "maxResults": 50, "total": 1234}
```

```bash
# Data Center only
curl -s -H "Authorization: Bearer ${JIRA_PAT}" --get "${JIRA_BASE}/rest/api/2/search" \
  --data-urlencode 'jql=assignee = currentUser() ORDER BY updated DESC' \
  --data-urlencode 'maxResults=10' --data-urlencode 'fields=summary,status,priority'
```

On Data Center, `'"Epic Link" = DEV-100'` still works for epic children; `parent` is the Cloud replacement.

### JQL Operators and Fields

| Field | Operators | Example |
|---|---|---|
| `project` | `=`, `!=`, `IN` | `project IN ("DEV","OPS")` |
| `status` | `=`, `!=`, `IN`, `WAS`, `CHANGED` | `status WAS "In Progress"` |
| `statusCategory` | `=`, `!=`, `IN` | `statusCategory = "In Progress"` |
| `assignee` | `=`, `!=`, `IS`, `WAS` | `assignee = currentUser()` |
| `reporter` | `=`, `!=` | `reporter = "john.doe"` |
| `priority` | `=`, `!=`, `IN` | `priority IN (Critical, High)` |
| `labels` | `=`, `!=`, `IN` | `labels = "backend"` |
| `sprint` | `IN` | `sprint in openSprints()` |
| `parent` | `=`, `IN` | `parent = DEV-100` (Cloud epic children; DC uses `"Epic Link"`) |
| `updated`/`created`/`resolved` | `>=`, `<=`, `>`, `<` | `updated >= -30d` |
| `text` | `~` | `text ~ "deployment"` |
| `summary` | `~` | `summary ~ "API"` |
| `type` | `=`, `IN` | `type = Bug` |

## 4. Issues -- CRUD

### Get Issue
```python
def get_issue(issue_key, expand="", fields=""):
    params = {}
    if expand: params["expand"] = expand
    if fields: params["fields"] = fields
    resp = requests.get(f"{BASE}/rest/api/2/issue/{issue_key}", auth=AUTH, params=params)
    resp.raise_for_status()
    return resp.json()

issue = get_issue("DEV-123", fields="summary,status,priority,description,assignee,labels,updated")
```

### Create Issue
```python
payload = {
    "fields": {
        "project": {"key": "DEV"},
        "summary": "Implement checkout flow",
        "description": "Full checkout with payment integration.",
        "issuetype": {"name": "Story"},
        "priority": {"name": "High"},
        "assignee": {"accountId": "5a1234bc567890def"},  # Cloud
        # "assignee": {"name": "john.doe"},               # Data Center
        "labels": ["backend", "checkout"],
    }
}
resp = requests.post(f"{BASE}/rest/api/2/issue", auth=AUTH, json=payload)
new_issue = resp.json()  # {"id": "10001", "key": "DEV-124", "self": "..."}
```

### Update Issue
```python
update = {
    "fields": {
        "summary": "Updated summary",
        "priority": {"name": "Critical"},
        "labels": ["backend", "checkout", "urgent"],
    }
}
requests.put(f"{BASE}/rest/api/2/issue/DEV-123", auth=AUTH, json=update)
```

### Transition Issue (change status)
```python
# 1. Get available transitions
transitions = requests.get(f"{BASE}/rest/api/2/issue/DEV-123/transitions", auth=AUTH).json()
# transitions["transitions"] = [{"id": "21", "name": "In Progress"}, {"id": "31", "name": "Done"}, ...]

# 2. Execute transition
requests.post(f"{BASE}/rest/api/2/issue/DEV-123/transitions", auth=AUTH, json={
    "transition": {"id": "31"},  # "Done" transition
    "fields": {"resolution": {"name": "Done"}},  # if required
    "update": {"comment": [{"add": {"body": "Completed implementation."}}]}  # optional
})
```

### Delete Issue
```bash
curl -X DELETE -u "${JIRA_USER}:${JIRA_TOKEN}" "${JIRA_BASE}/rest/api/2/issue/DEV-123"
# Add ?deleteSubtasks=true to also delete subtasks
```

## 5. Status Category Mapping

Jira statuses are project-specific, but `statusCategory` is universal:

| statusCategory.key | statusCategory.name | Meaning | PA Mapping |
|---|---|---|---|
| `new` | To Do | Not started | `new` |
| `indeterminate` | In Progress | Active work | `executing` |
| `done` | Done | Completed | `done` |

```python
def map_jira_status(issue):
    """Map Jira status to PA vocabulary via statusCategory."""
    cat_key = issue["fields"]["status"]["statusCategory"]["key"]
    return {"new": "new", "indeterminate": "executing", "done": "done"}.get(cat_key, "new")
```

Always use `statusCategory.key`, never individual status names like "In Review", "QA Testing", etc.

## 6. Sprint and Board Queries (Agile API)

The Agile API uses `/rest/agile/1.0/` prefix.

```python
AGILE = f"{BASE}/rest/agile/1.0"

# List boards
boards = requests.get(f"{AGILE}/board", auth=AUTH, params={"type": "scrum"}).json()

# Get board sprints
sprints = requests.get(f"{AGILE}/board/{board_id}/sprint", auth=AUTH,
                       params={"state": "active"}).json()

# Get sprint issues
issues = requests.get(f"{AGILE}/sprint/{sprint_id}/issue", auth=AUTH,
                       params={"fields": "summary,status,assignee"}).json()

# Get board backlog
backlog = requests.get(f"{AGILE}/board/{board_id}/backlog", auth=AUTH).json()

# Get board configuration (columns, estimation)
config = requests.get(f"{AGILE}/board/{board_id}/configuration", auth=AUTH).json()

# Move issues to sprint
requests.post(f"{AGILE}/sprint/{sprint_id}/issue", auth=AUTH, json={
    "issues": ["DEV-123", "DEV-124"]})

# Rank issues
requests.put(f"{AGILE}/issue/rank", auth=AUTH, json={
    "issues": ["DEV-124"], "rankBeforeIssue": "DEV-123"})
```

```bash
# Active sprint for a board
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
  "${JIRA_BASE}/rest/agile/1.0/board/${BOARD_ID}/sprint?state=active"
```

## 7. Comments

```python
# Get comments
comments = requests.get(f"{BASE}/rest/api/2/issue/DEV-123/comment",
                        auth=AUTH, params={"orderBy": "-created"}).json()

# Add comment (v2 -- plain text body)
requests.post(f"{BASE}/rest/api/2/issue/DEV-123/comment", auth=AUTH, json={
    "body": "Implementation complete. Ready for review."})

# Add comment (v3 Cloud -- ADF)
requests.post(f"{BASE}/rest/api/3/issue/DEV-123/comment", auth=AUTH, json={
    "body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Ready for review."}]}
    ]}})

# Update comment
requests.put(f"{BASE}/rest/api/2/issue/DEV-123/comment/{comment_id}", auth=AUTH, json={
    "body": "Updated comment text."})

# Delete comment
requests.delete(f"{BASE}/rest/api/2/issue/DEV-123/comment/{comment_id}", auth=AUTH)
```

## 8. Attachments

```python
# Add attachment
requests.post(f"{BASE}/rest/api/2/issue/DEV-123/attachments", auth=AUTH,
    headers={"X-Atlassian-Token": "no-check"},
    files={"file": ("report.pdf", open("report.pdf", "rb"), "application/pdf")})

# List attachments (via issue fields)
issue = get_issue("DEV-123", fields="attachment")
attachments = issue["fields"]["attachment"]

# Download attachment
content = requests.get(attachment["content"], auth=AUTH).content

# Delete attachment
requests.delete(f"{BASE}/rest/api/2/attachment/{attachment_id}", auth=AUTH)
```

## 9. Labels

```python
# Labels are a field on issues -- update via issue update
requests.put(f"{BASE}/rest/api/2/issue/DEV-123", auth=AUTH, json={
    "update": {"labels": [{"add": "new-label"}, {"remove": "old-label"}]}})

# Get all labels (for autocomplete)
labels = requests.get(f"{BASE}/rest/api/2/label", auth=AUTH).json()
```

## 10. Pagination

Pagination differs by deployment: **Cloud uses a `nextPageToken` cursor** (on `/search/jql`), **Data Center uses `startAt` offset**. (Non-search Cloud endpoints like `/project/search` still use `startAt`-style paging — this split applies to issue search.)

### Cloud: nextPageToken cursor (`/rest/api/3/search/jql`)

```python
def get_all_issues(jql, fields="summary,status,priority,updated"):
    """Jira CLOUD: loop on nextPageToken until it is absent. Responses carry NO 'total'."""
    all_issues, token = [], None
    while True:
        params = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            params["nextPageToken"] = token
        data = requests.get(f"{BASE}/rest/api/3/search/jql", auth=AUTH, params=params).json()
        all_issues.extend(data.get("issues", []))
        token = data.get("nextPageToken")
        if not token:  # token absent (or isLast true) == final page
            break
    return all_issues
```

```bash
# Cloud: first page
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" --get "${JIRA_BASE}/rest/api/3/search/jql" \
  --data-urlencode 'jql=project = DEV' --data-urlencode 'maxResults=100'
# Cloud: next page -- pass the nextPageToken from the previous response
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" --get "${JIRA_BASE}/rest/api/3/search/jql" \
  --data-urlencode 'jql=project = DEV' --data-urlencode 'maxResults=100' \
  --data-urlencode "nextPageToken=${NEXT_PAGE_TOKEN}"
```

Counting on Cloud (`total` is gone from search responses):
```python
count = requests.post(f"{BASE}/rest/api/3/search/approximate-count", auth=AUTH,
                      json={"jql": "project = DEV"}).json()["count"]  # approximate, usually very close
```

### Data Center: startAt offset (`/rest/api/2/search`, Data-Center-only)

```python
def get_all_issues_dc(jql, fields="summary,status,priority,updated"):
    """Jira DATA CENTER only: classic offset pagination with 'total'."""
    all_issues, start_at, max_results = [], 0, 100
    while True:
        data = requests.get(f"{BASE}/rest/api/2/search", auth=AUTH, params={
            "jql": jql, "fields": fields, "maxResults": max_results, "startAt": start_at
        }).json()
        all_issues.extend(data["issues"])
        if start_at + max_results >= data["total"]:
            break
        start_at += max_results
    return all_issues
```

```bash
# Data Center: page 2 of results (items 50-99)
curl -s -H "Authorization: Bearer ${JIRA_PAT}" --get "${JIRA_BASE}/rest/api/2/search" \
  --data-urlencode 'jql=project = DEV' --data-urlencode 'startAt=50' --data-urlencode 'maxResults=50'
```

## 11. Rate Limiting and Error Handling

| Code | Meaning | Action |
|---|---|---|
| `400` | Bad Request | Check JQL syntax, field names, payload format |
| `401` | Unauthorized | Invalid/expired token. Prompt user to refresh. Never retry. |
| `403` | Forbidden | Insufficient permissions for project/issue |
| `404` | Not Found | Wrong issue key, or issue in trash |
| `409` | Conflict | Concurrent modification -- re-fetch and retry |
| `429` | Too Many Requests | Rate limited -- respect `Retry-After` header |
| `5xx` | Server Error | Retry with exponential backoff |

```python
import time

def safe_jira_call(method, url, max_retries=3, **kwargs):
    kwargs.setdefault("auth", AUTH)
    for attempt in range(max_retries):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** attempt * 10))
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            time.sleep(2 ** attempt * 5)
            continue
        if resp.status_code == 401:
            raise Exception("Authentication failed (401). Refresh your Jira token.")
        resp.raise_for_status()
        return resp
    raise Exception(f"Failed after {max_retries} retries: {method} {url}")
```

### Session with automatic retry
```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def jira_session():
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET","POST","PUT","DELETE"], respect_retry_after_header=True)))
    s.auth = AUTH
    return s
```

## 12. Webhooks

### Register (Data Center)
```python
requests.post(f"{BASE}/rest/webhooks/1.0/webhook", auth=AUTH, json={
    "name": "Issue Notifier",
    "url": "https://yourapp.com/webhooks/jira",
    "events": ["jira:issue_created", "jira:issue_updated", "jira:issue_deleted",
               "comment_created", "sprint_started", "sprint_closed"],
    "filters": {"issue-related-events-section": 'project = "DEV"'},
    "excludeBody": False})
```

### Event types
`jira:issue_created`, `jira:issue_updated`, `jira:issue_deleted`, `comment_created`, `comment_updated`, `comment_deleted`, `issuelink_created`, `issuelink_deleted`, `sprint_created`, `sprint_started`, `sprint_closed`, `board_created`, `board_updated`.

### Cloud webhooks
Registered via Atlassian Connect app descriptors (`atlassian-connect.json`) or Forge event triggers, not via REST.

### Payload structure
```json
{
  "timestamp": 1711267200000,
  "webhookEvent": "jira:issue_updated",
  "issue_event_type_name": "issue_generic",
  "user": {"accountId": "5a1234..."},
  "issue": {
    "id": "10001", "key": "DEV-123",
    "fields": {"summary": "Updated title", "status": {"name": "In Progress"}}
  },
  "changelog": {
    "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}]
  }
}
```

## 13. Projects and Issue Types

```python
# List projects
projects = requests.get(f"{BASE}/rest/api/2/project", auth=AUTH).json()

# Get project details
project = requests.get(f"{BASE}/rest/api/2/project/DEV", auth=AUTH).json()

# Get issue types for project
types = requests.get(f"{BASE}/rest/api/2/project/DEV/statuses", auth=AUTH).json()

# Get create metadata (required fields per issue type)
meta = requests.get(f"{BASE}/rest/api/2/issue/createmeta", auth=AUTH, params={
    "projectKeys": "DEV", "expand": "projects.issuetypes.fields"}).json()
```

## 14. Filters (Saved Searches)

```python
# Get filter by ID
filter_data = requests.get(f"{BASE}/rest/api/2/filter/{filter_id}", auth=AUTH).json()
jql = filter_data["jql"]

# Get favourite filters
favourites = requests.get(f"{BASE}/rest/api/2/filter/favourite", auth=AUTH).json()

# Create filter
requests.post(f"{BASE}/rest/api/2/filter", auth=AUTH, json={
    "name": "My Open Bugs", "jql": 'project = DEV AND type = Bug AND status != Done',
    "favourite": True})

# Search using filter
jql_search(f"filter = {filter_id}")
```

## Security — XML / XHTML parsing

<HARD-RULE>
When parsing any XML or XHTML payload from a remote API, untrusted file, or user-supplied source, NEVER use stdlib `xml.etree.ElementTree`, `xml.dom.minidom`, or `lxml.etree.fromstring` without XXE protection. Use `defusedxml` (`pip install defusedxml`) and replace `xml.etree.ElementTree` → `defusedxml.ElementTree`, `lxml.etree` → `defusedxml.lxml`. Stdlib XML parsers expand external entities by default and are vulnerable to billion-laughs / XXE / DTD-retrieval / SSRF-via-entity attacks (CWE-611). Local skill applicability:
- API payloads that may legitimately be XML (storage format, error responses)
- Imported / exported workflow files
- Bulk import / migration paths
</HARD-RULE>

For HTML/XHTML rendering of downstream output (storage format → display), sanitise with `bleach` or `nh3` BEFORE inserting into a browser context — never raw-render API-returned XHTML. See `llm-security` SKILL.md §4.4 for context-appropriate escaping rules.

## Anti-Patterns

| Do NOT | Why |
|---|---|
| Hardcode API tokens in scripts | Credential leak via source control |
| Map individual status names | Status names vary per workflow. Use `statusCategory.key`. |
| Tight-loop API calls without delay | Rate limited and potentially blocked |
| Use DELETE without confirming issue key | Deletion may be permanent depending on permissions |
| Ignore `fields` parameter on search | Fetching all fields is slow and wasteful |
| Assume v3 endpoints on Data Center | v3 is Cloud-only |
| Retry 401 errors | Auth failures need user action, not retry |
| Parse HTML descriptions on Cloud v3 | Cloud v3 uses ADF (Atlassian Document Format), not HTML |
| Call `/rest/api/2|3/search` on Cloud | Removed (shutdown completed Oct 2025) -- returns `410 Gone`. Use `/rest/api/3/search/jql` + `nextPageToken`. |
| Expect `total` in Cloud search responses | `/search/jql` does not return it. Use `POST /rest/api/3/search/approximate-count`. |
| Detect the last Cloud page via `len(issues) < maxResults` | `maxResults` is a hint; pages may come back short mid-stream. Stop only when `nextPageToken` is absent. |
| Use `"Epic Link"` in Cloud JQL | Retired on Cloud -- use `parent = KEY-1`. (`"Epic Link"` still valid on Data Center.) |
| Use `startAt` beyond 10000 (Data Center) | DC caps offset at ~10000. Use JQL date/key ranges to slice larger sets. (Cloud's `nextPageToken` cursor has no such offset cap.) |

<!-- FRESHNESS:v1
anchors:
  - kind: status_snapshot
    subject: jira-cloud-search-api
    verified_against: "Cloud GET/POST /rest/api/2|3/search deprecated 2024, removed Aug-Oct 2025 (410 Gone); replacement /rest/api/2|3/search/jql with nextPageToken cursor, no total (use POST /rest/api/3/search/approximate-count); maxResults is a hint (<=100/page with fields, 5000 id-only); Data Center keeps /rest/api/2/search + startAt"
    verified_on: "2026-06-10"
volatility: medium
-->
