---
name: confluence-rest-api
description: Use when interacting with Confluence programmatically via REST API — API v1 and v2 endpoints, authentication (API tokens, OAuth, PAT), CRUD operations on pages/spaces/attachments, CQL (Confluence Query Language), content properties, labels, comments, user/group management, bulk operations, pagination, rate limiting, and error handling. Works with both Confluence Cloud and Data Center.
---

# Confluence REST API

Companion skill: `confluence-content-creator` — higher-level page authoring workflows built on these API primitives.

<HARD-RULE>
NEVER hardcode credentials. Store API tokens, passwords, and OAuth secrets in environment variables or a secrets manager. Never embed them in source code or command history.
</HARD-RULE>

<HARD-RULE>
ALWAYS increment the version number on page updates. Every PUT must include `version.number` set to `current_version + 1`. Omitting this causes `409 Conflict`. Always GET the page first to read its current version.
</HARD-RULE>

<HARD-RULE>
Respect rate limits. Confluence Cloud enforces per-user rate limits. Implement exponential backoff with retry logic. Check `Retry-After` and `X-RateLimit-*` headers. Never tight-loop API calls.
</HARD-RULE>

## 1. Authentication

### API Tokens (Cloud) — Basic Auth with email + token
```bash
export CONFLUENCE_BASE="https://yoursite.atlassian.net/wiki"
export CONFLUENCE_USER="you@company.com"
export CONFLUENCE_TOKEN="your-api-token"
curl -s -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" "${CONFLUENCE_BASE}/rest/api/content?limit=5"
```
```python
import os, requests
BASE = os.environ["CONFLUENCE_BASE"]
AUTH = (os.environ["CONFLUENCE_USER"], os.environ["CONFLUENCE_TOKEN"])
resp = requests.get(f"{BASE}/rest/api/content", params={"limit": 5}, auth=AUTH)
```

### Personal Access Tokens (Data Center 7.14+) — Bearer token, no username
```bash
curl -s -H "Authorization: Bearer ${CONFLUENCE_PAT}" "${CONFLUENCE_BASE}/rest/api/content?limit=5"
```

### OAuth 2.0 (Cloud 3LO) — for Connect/Forge apps
```python
# Exchange authorization code for token
token_resp = requests.post("https://auth.atlassian.com/oauth/token", json={
    "grant_type": "authorization_code", "client_id": os.environ["OAUTH_CLIENT_ID"],
    "client_secret": os.environ["OAUTH_CLIENT_SECRET"], "code": auth_code,
    "redirect_uri": "https://yourapp.com/callback"})
access_token = token_resp.json()["access_token"]
# Get cloud_id, then call: /ex/confluence/{cloud_id}/wiki/rest/api/content
```

| Credential Storage | Use Case |
|---|---|
| Environment variables | Local dev, CI/CD |
| HashiCorp Vault / AWS Secrets Manager | Production |
| `.env` + python-dotenv (in `.gitignore`) | Local dev |

## 2. API Versions

**v1** (`/rest/api/content`) — fully supported on Cloud + Data Center. Offset pagination (`start`+`limit`).
**v2** (`/api/v2/pages`) — Cloud-primary, cleaner responses, cursor pagination. Data Center support growing.

| Use v1 when | Use v2 when |
|---|---|
| Targeting Data Center | Cloud + need cursor pagination |
| CQL search, content properties, macros | Building new Cloud integrations |
| Need broadest compatibility | Endpoint exists in v2 |

Key v2 endpoints: `GET/POST/PUT/DELETE /api/v2/pages`, `GET /api/v2/spaces`, `GET /api/v2/pages/{id}/children`.

## 3. Pages CRUD

### Create
```python
# v1 — Cloud + Data Center
payload = {"type": "page", "title": "New Page", "space": {"key": "DEV"},
           "body": {"storage": {"value": "<p>Content here.</p>", "representation": "storage"}}}
resp = requests.post(f"{BASE}/rest/api/content", json=payload, auth=AUTH)

# Child page — add ancestors
payload["ancestors"] = [{"id": "123456"}]  # parent page ID
```

### Get by ID / Title
```bash
# By ID with expanded fields
curl -s -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" \
  "${CONFLUENCE_BASE}/rest/api/content/123456?expand=body.storage,version,ancestors"
# By title in a space
curl -s -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" \
  "${CONFLUENCE_BASE}/rest/api/content?title=Meeting+Notes&spaceKey=DEV&expand=version"
```

### Update (MUST increment version)
```python
page = requests.get(f"{BASE}/rest/api/content/{page_id}",
                    params={"expand": "body.storage,version"}, auth=AUTH).json()
update = {"version": {"number": page["version"]["number"] + 1}, "title": page["title"],
          "type": "page", "body": {"storage": {"value": "<p>Updated.</p>", "representation": "storage"}}}
resp = requests.put(f"{BASE}/rest/api/content/{page_id}", json=update, auth=AUTH)
```

### Delete / Archive / Move / Copy
```bash
curl -X DELETE "${CONFLUENCE_BASE}/rest/api/content/123456"           # trash
curl -X DELETE "${CONFLUENCE_BASE}/rest/api/content/123456?status=trashed"  # purge
```
```python
# Move page under new parent
requests.put(f"{BASE}/rest/api/content/{page_id}/move/append/{target_parent_id}", auth=AUTH)
# Copy page
requests.post(f"{BASE}/rest/api/content/{page_id}/copy", auth=AUTH, json={
    "copyAttachments": True, "copyLabels": True,
    "destination": {"type": "parent_page", "value": "789012"}})
# Page version history
resp = requests.get(f"{BASE}/rest/api/content/{page_id}/version", params={"limit": 10}, auth=AUTH)
```

## 4. Content Body — Storage Format

Confluence uses XHTML-based storage format. Key macros:

```xml
<!-- Code block -->
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">python</ac:parameter>
  <ac:plain-text-body><![CDATA[print("hello")]]></ac:plain-text-body>
</ac:structured-macro>

<!-- Info/Warning panels -->
<ac:structured-macro ac:name="info">
  <ac:rich-text-body><p>Info text.</p></ac:rich-text-body>
</ac:structured-macro>

<!-- TOC, Status lozenge, Expand -->
<ac:structured-macro ac:name="toc"><ac:parameter ac:name="maxLevel">3</ac:parameter></ac:structured-macro>
<ac:structured-macro ac:name="status">
  <ac:parameter ac:name="title">DONE</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter>
</ac:structured-macro>
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">Details</ac:parameter>
  <ac:rich-text-body><p>Hidden content.</p></ac:rich-text-body>
</ac:structured-macro>

<!-- Link to page, mention user -->
<ac:link><ri:page ri:content-title="Target Page" ri:space-key="DEV" /></ac:link>
<ac:link><ri:user ri:account-id="5a1234bc567890def" /></ac:link>
```

```python
# Convert wiki markup to storage format
resp = requests.post(f"{BASE}/rest/api/contentbody/convert/storage",
    json={"value": "h2. Heading\nText here.", "representation": "wiki"}, auth=AUTH)
storage_html = resp.json()["value"]
```

## 5. Spaces

```python
# List spaces
resp = requests.get(f"{BASE}/rest/api/space", params={"limit": 25, "type": "global"}, auth=AUTH)

# Create space
requests.post(f"{BASE}/rest/api/space", auth=AUTH, json={
    "key": "NEW", "name": "New Space", "type": "global",
    "description": {"plain": {"value": "Description.", "representation": "plain"}}})

# Get space with homepage
resp = requests.get(f"{BASE}/rest/api/space/DEV", params={"expand": "homepage"}, auth=AUTH)
homepage_id = resp.json()["homepage"]["id"]

# Space permissions (Cloud)
requests.post(f"{BASE}/rest/api/space/DEV/permission", auth=AUTH, json={
    "subject": {"type": "group", "identifier": "developers"},
    "operation": {"key": "read", "targetType": "space"}})
```

## 6. CQL (Confluence Query Language)

Syntax: `field operator value [AND|OR ...] [ORDER BY field ASC|DESC]`

```python
def cql_search(cql, limit=25):
    resp = requests.get(f"{BASE}/rest/api/search", params={"cql": cql, "limit": limit}, auth=AUTH)
    resp.raise_for_status()
    return resp.json()["results"]

cql_search('space = "DEV" AND type = "page"')                          # pages in space
cql_search('text ~ "deployment guide"')                                 # full-text search
cql_search('label = "architecture" AND type = "page"')                  # by label
cql_search('creator = "john.doe" AND type = "page"')                    # by creator
cql_search('lastModified >= now("-7d") AND space = "DEV"')              # recent changes
cql_search('title ~ "Sprint*" AND type = "page" ORDER BY lastModified DESC')  # title match
cql_search('ancestor = 123456 AND type = "page"')                      # children of page
cql_search('type = "blogpost" AND space = "ENG" ORDER BY created DESC') # blog posts
```

```bash
curl -s -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" --get "${CONFLUENCE_BASE}/rest/api/search" \
  --data-urlencode 'cql=space = "DEV" AND type = "page"' --data-urlencode 'limit=10'
```

| Field | Operators | Example |
|---|---|---|
| `space` | `=`, `!=`, `IN` | `space IN ("DEV","OPS")` |
| `type` | `=` | `type = "page"` |
| `title` | `=`, `~` | `title ~ "API"` |
| `text` | `~` | `text ~ "keyword"` |
| `label` | `=`, `IN` | `label = "reviewed"` |
| `creator` | `=` | `creator = currentUser()` |
| `lastModified`/`created` | `>=`, `<=`, `>`, `<` | `lastModified >= now("-30d")` |
| `ancestor`/`parent` | `=` | `ancestor = 123456` |

## 7. Attachments

```python
# Upload
requests.put(f"{BASE}/rest/api/content/{page_id}/child/attachment", auth=AUTH,
    headers={"X-Atlassian-Token": "nocheck"},
    files={"file": ("report.pdf", open("report.pdf", "rb"), "application/pdf")},
    data={"comment": "Initial upload"})

# List attachments
resp = requests.get(f"{BASE}/rest/api/content/{page_id}/child/attachment",
                    params={"limit": 50}, auth=AUTH)

# Download
download_path = resp.json()["results"][0]["_links"]["download"]
content = requests.get(f"{BASE}{download_path}", auth=AUTH).content

# Update existing attachment
requests.post(f"{BASE}/rest/api/content/{page_id}/child/attachment/{att_id}/data", auth=AUTH,
    headers={"X-Atlassian-Token": "nocheck"},
    files={"file": ("report.pdf", open("report_v2.pdf", "rb"), "application/pdf")})
```

```bash
curl -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" -X PUT \
  "${CONFLUENCE_BASE}/rest/api/content/123456/child/attachment" \
  -H "X-Atlassian-Token: nocheck" -F "file=@report.pdf"
```

## 8. Labels

```python
# Add labels
requests.post(f"{BASE}/rest/api/content/{page_id}/label", auth=AUTH,
              json=[{"prefix": "global", "name": "api-docs"}, {"prefix": "global", "name": "v2"}])

# Get labels
labels = requests.get(f"{BASE}/rest/api/content/{page_id}/label", auth=AUTH).json()["results"]

# Remove label
requests.delete(f"{BASE}/rest/api/content/{page_id}/label/{label_name}", auth=AUTH)

# Search by label (via CQL)
cql_search('label = "architecture" AND space = "DEV"')
```

## 9. Comments

```python
# Get comments on a page
resp = requests.get(f"{BASE}/rest/api/content/{page_id}/child/comment",
                    params={"expand": "body.storage,version", "limit": 50}, auth=AUTH)

# Create page-level comment
requests.post(f"{BASE}/rest/api/content", auth=AUTH, json={
    "type": "comment", "container": {"id": page_id, "type": "page"},
    "body": {"storage": {"value": "<p>LGTM!</p>", "representation": "storage"}}})

# Inline comment (Cloud v2)
requests.post(f"{BASE}/api/v2/inline-comments", auth=AUTH, json={
    "pageId": page_id, "body": {"representation": "storage", "value": "<p>Typo here.</p>"},
    "inlineCommentProperties": {"textSelection": "exact text", "textSelectionMatchCount": 1,
                                 "textSelectionMatchIndex": 0}})

# Update comment (must increment version)
comment = requests.get(f"{BASE}/rest/api/content/{comment_id}",
                       params={"expand": "version"}, auth=AUTH).json()
requests.put(f"{BASE}/rest/api/content/{comment_id}", auth=AUTH, json={
    "version": {"number": comment["version"]["number"] + 1}, "type": "comment",
    "body": {"storage": {"value": "<p>Updated.</p>", "representation": "storage"}}})

# Delete comment
requests.delete(f"{BASE}/rest/api/content/{comment_id}", auth=AUTH)
```

## 10. Content Properties

Custom key-value metadata on pages — useful for sync state, build numbers, integration data.

```python
# Set property
requests.post(f"{BASE}/rest/api/content/{page_id}/property", auth=AUTH, json={
    "key": "deploy-status",
    "value": {"environment": "production", "build": "2026.3.42"}})

# Get property
prop = requests.get(f"{BASE}/rest/api/content/{page_id}/property/deploy-status", auth=AUTH).json()

# Update property (must increment version)
requests.put(f"{BASE}/rest/api/content/{page_id}/property/deploy-status", auth=AUTH, json={
    "key": "deploy-status", "value": {"environment": "production", "build": "2026.3.43"},
    "version": {"number": prop["version"]["number"] + 1}})

# Delete property
requests.delete(f"{BASE}/rest/api/content/{page_id}/property/deploy-status", auth=AUTH)
```

## 11. User and Group Management

```python
# Current user
user = requests.get(f"{BASE}/rest/api/user/current", auth=AUTH).json()

# User by account ID (Cloud) or key (Data Center)
requests.get(f"{BASE}/rest/api/user", params={"accountId": "5a1234..."}, auth=AUTH)

# List group members
resp = requests.get(f"{BASE}/rest/api/group/developers/member", params={"limit": 200}, auth=AUTH)

# Add/remove user from group (Data Center)
requests.post(f"{BASE}/rest/api/group/developers/member", json={"name": "john.doe"}, auth=AUTH)
requests.delete(f"{BASE}/rest/api/group/developers/member", params={"name": "john.doe"}, auth=AUTH)
```

## 12. Bulk Operations and Pagination

### v1 offset pagination (`start` + `limit`)
```python
def get_all_pages_v1(space_key):
    all_pages, start, limit = [], 0, 100
    while True:
        data = requests.get(f"{BASE}/rest/api/content", auth=AUTH,
            params={"spaceKey": space_key, "type": "page", "limit": limit, "start": start}).json()
        all_pages.extend(data["results"])
        if data["size"] < limit or "next" not in data.get("_links", {}):
            break
        start += limit
    return all_pages
```

### v2 cursor pagination (Cloud)
```python
def get_all_pages_v2(space_id):
    all_pages, url = [], f"{BASE}/api/v2/pages"
    params = {"space-id": space_id, "limit": 250}
    while url:
        data = requests.get(url, params=params, auth=AUTH).json()
        all_pages.extend(data["results"])
        url = data.get("_links", {}).get("next")
        params = {}  # cursor URL includes params
    return all_pages
```

### Rate-limit-aware bulk creation
```python
import time
def bulk_create_pages(pages_data, space_key, delay=0.5):
    created = []
    for page_data in pages_data:
        payload = {"type": "page", "title": page_data["title"], "space": {"key": space_key},
                   "body": {"storage": {"value": page_data["body"], "representation": "storage"}}}
        resp = requests.post(f"{BASE}/rest/api/content", json=payload, auth=AUTH)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", 60)))
            resp = requests.post(f"{BASE}/rest/api/content", json=payload, auth=AUTH)
        resp.raise_for_status()
        created.append(resp.json()["id"])
        time.sleep(delay)
    return created
```

### Session with automatic retry
```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def confluence_session():
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET","POST","PUT","DELETE"], respect_retry_after_header=True)))
    s.auth = AUTH
    return s
```

## 13. Webhooks

### Register (Data Center)
```python
requests.post(f"{BASE}/rest/webhooks/1.0/webhook", auth=AUTH, json={
    "name": "Page Notifier", "url": "https://yourapp.com/webhooks/confluence",
    "events": ["page_created", "page_updated", "page_removed", "comment_created"],
    "active": True})
```

### Event types
`page_created`, `page_updated`, `page_removed`, `page_restored`, `comment_created`, `comment_updated`, `comment_removed`, `attachment_created`, `space_created`, `space_removed`, `label_added`, `label_removed`.

### Payload structure
```json
{"timestamp": 1711267200000, "event": "page_updated",
 "userAccountId": "5a1234...",
 "page": {"id": 123456, "title": "API Guide", "spaceKey": "DEV", "version": 5}}
```

Cloud webhooks are registered via Atlassian Connect app descriptors (`atlassian-connect.json`) or Forge event triggers, not via REST.

## 14. Error Handling

| Code | Meaning | Cause |
|---|---|---|
| `400` | Bad Request | Malformed JSON, invalid fields |
| `401` | Unauthorized | Invalid/expired credentials |
| `403` | Forbidden | Insufficient permissions |
| `404` | Not Found | Wrong ID or content trashed |
| `409` | Conflict | Stale version number on update |
| `413` | Payload Too Large | Attachment exceeds limit |
| `429` | Too Many Requests | Rate limited — check `Retry-After` |
| `5xx` | Server Error | Retry with backoff |

```python
def safe_api_call(method, url, max_retries=3, **kwargs):
    kwargs.setdefault("auth", AUTH)
    for attempt in range(max_retries):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", 2 ** attempt * 10)))
            continue
        if resp.status_code >= 500:
            time.sleep(2 ** attempt * 5)
            continue
        if resp.status_code == 409:
            raise Exception(f"Version conflict: {resp.json().get('message')}")
        resp.raise_for_status()
        return resp
    raise Exception(f"Failed after {max_retries} retries: {method} {url}")
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

| Don't | Why |
|---|---|
| Hardcode API tokens in scripts | Credential leak via source control |
| Skip version number on updates | `409 Conflict` every time |
| Tight-loop API calls without delay | Rate limited and potentially blocked |
| Use `DELETE` without confirming page ID | No undo for purged pages |
| Ignore `expand` parameter on GETs | Response bodies are minimal by default |
| Assume v2 endpoints exist on Data Center | Many v2 endpoints are Cloud-only |
| Send raw HTML instead of storage format | Use `<ac:structured-macro>` for macros |
| Use offset pagination for large Cloud datasets | Cursor-based (v2) is more reliable |
