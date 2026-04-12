---
name: jira-rest-api
description: Use when interacting with Jira programmatically via REST API — API v2 and v3 endpoints, authentication (API tokens, OAuth, PAT), issue CRUD (search via JQL, get/create/update/transition), status category mapping, sprint/board queries (Agile API), comments, attachments, labels, pagination (startAt + maxResults), rate limiting, error handling, and webhooks. Works with both Jira Cloud and Data Center.
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

**v2** (`/rest/api/2/`) -- fully supported on Cloud + Data Center. Primary version.
**v3** (`/rest/api/3/`) -- Cloud-only, richer Atlassian Document Format (ADF) for descriptions/comments.

| Use v2 when | Use v3 when |
|---|---|
| Targeting Data Center | Cloud + need ADF rich text |
| Broadest compatibility | Building new Cloud integrations |
| Simple text descriptions | Structured document content |

## 3. Issues -- Search (JQL)

JQL (Jira Query Language) is the primary search mechanism.

```python
def jql_search(jql, fields="summary,status,priority,assignee,updated", max_results=50, start_at=0):
    resp = requests.get(f"{BASE}/rest/api/2/search", auth=AUTH, params={
        "jql": jql, "fields": fields, "maxResults": max_results, "startAt": start_at})
    resp.raise_for_status()
    return resp.json()

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
# By epic
jql_search('"Epic Link" = DEV-100')
# Complex filter
jql_search('project = "DEV" AND priority in (Critical, High) AND status != Done AND assignee = currentUser()')
```

```bash
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" --get "${JIRA_BASE}/rest/api/2/search" \
  --data-urlencode 'jql=assignee = currentUser() ORDER BY updated DESC' \
  --data-urlencode 'maxResults=10' --data-urlencode 'fields=summary,status,priority'
```

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

Jira uses offset pagination: `startAt` + `maxResults`.

```python
def get_all_issues(jql, fields="summary,status,priority,updated"):
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
# Page 2 of results (items 50-99)
curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" --get "${JIRA_BASE}/rest/api/2/search" \
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
| Use `startAt` beyond 10000 | Jira caps offset at ~10000. Use `search/id` or JQL date ranges for larger sets. |
