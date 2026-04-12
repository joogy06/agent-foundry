# Advanced Macros and Documentation Templates

Reference file for the `confluence-content-creator` skill. Covers advanced macros, documentation templates (technical specs, runbooks, meeting notes, decision records, ADRs).

## 4. Documentation Templates

### Architecture Decision Record (ADR)

```xml
<ac:structured-macro ac:name="details">
  <ac:rich-text-body>
    <table>
      <tr><th>Status</th><td><ac:structured-macro ac:name="status">
        <ac:parameter ac:name="colour">Yellow</ac:parameter>
        <ac:parameter ac:name="title">PROPOSED</ac:parameter>
      </ac:structured-macro></td></tr>
      <tr><th>Decision Date</th><td>2026-03-24</td></tr>
      <tr><th>Deciders</th><td>@engineering-leads</td></tr>
      <tr><th>Category</th><td>Architecture</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">2</ac:parameter>
</ac:structured-macro>

<h2>Context</h2>
<p>Describe the forces at play, including technical, political, social, and project-specific constraints.</p>

<h2>Decision</h2>
<p>State the architecture decision clearly and concisely.</p>

<h2>Options Considered</h2>
<table>
  <tr><th>Option</th><th>Pros</th><th>Cons</th><th>Effort</th></tr>
  <tr><td>Option A</td><td>Fast, simple</td><td>Limited scale</td><td>Small</td></tr>
  <tr><td>Option B</td><td>Scalable</td><td>Complex setup</td><td>Medium</td></tr>
  <tr><td>Option C</td><td>Industry standard</td><td>Expensive</td><td>Large</td></tr>
</table>

<h2>Consequences</h2>
<p>What becomes easier or harder as a result of this decision.</p>

<h2>References</h2>
<ul>
  <li><a href="https://example.com/rfc">Related RFC</a></li>
</ul>
```

### Runbook Template

```xml
<ac:structured-macro ac:name="details">
  <ac:rich-text-body>
    <table>
      <tr><th>Service</th><td>payment-service</td></tr>
      <tr><th>Owner</th><td>Payments Team</td></tr>
      <tr><th>Severity</th><td>SEV-2</td></tr>
      <tr><th>Last Tested</th><td>2026-03-01</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="warning">
  <ac:parameter ac:name="title">On-Call Required</ac:parameter>
  <ac:rich-text-body>
    <p>This runbook should only be executed by on-call engineers with production access.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">2</ac:parameter>
</ac:structured-macro>

<h2>Symptoms</h2>
<ul>
  <li>Alert: <code>PaymentProcessingLatencyHigh</code> fires in PagerDuty</li>
  <li>Dashboard: Payment success rate drops below 99.5%</li>
  <li>Logs: <code>TimeoutException</code> in payment-service pods</li>
</ul>

<h2>Diagnosis Steps</h2>
<ol>
  <li>Check service health:
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">bash</ac:parameter>
      <ac:plain-text-body><![CDATA[kubectl get pods -n payments -l app=payment-service
kubectl logs -n payments -l app=payment-service --tail=100]]></ac:plain-text-body>
    </ac:structured-macro>
  </li>
  <li>Check downstream dependencies:
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">bash</ac:parameter>
      <ac:plain-text-body><![CDATA[curl -s https://payment-gateway.internal/health | jq .]]></ac:plain-text-body>
    </ac:structured-macro>
  </li>
  <li>Review metrics in Grafana: <a href="https://grafana.internal/d/payments">Payment Dashboard</a></li>
</ol>

<h2>Remediation</h2>
<h3>Option A: Restart Pods</h3>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">bash</ac:parameter>
  <ac:plain-text-body><![CDATA[kubectl rollout restart deployment/payment-service -n payments
kubectl rollout status deployment/payment-service -n payments]]></ac:plain-text-body>
</ac:structured-macro>

<h3>Option B: Scale Up</h3>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">bash</ac:parameter>
  <ac:plain-text-body><![CDATA[kubectl scale deployment/payment-service -n payments --replicas=6]]></ac:plain-text-body>
</ac:structured-macro>

<h3>Option C: Failover to Secondary Region</h3>
<ac:structured-macro ac:name="note">
  <ac:parameter ac:name="title">Requires VP Approval</ac:parameter>
  <ac:rich-text-body><p>Regional failover must be approved by VP of Engineering.</p></ac:rich-text-body>
</ac:structured-macro>

<h2>Escalation</h2>
<table>
  <tr><th>Level</th><th>Contact</th><th>When</th></tr>
  <tr><td>L1</td><td>On-call engineer</td><td>Immediately</td></tr>
  <tr><td>L2</td><td>Payments team lead</td><td>If unresolved after 15 min</td></tr>
  <tr><td>L3</td><td>VP Engineering</td><td>If customer-facing impact &gt; 30 min</td></tr>
</table>

<h2>Post-Incident</h2>
<ul>
  <li>Create incident postmortem page (use Incident Postmortem template)</li>
  <li>Update this runbook with any new findings</li>
</ul>
```

### API Documentation Template

```xml
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">3</ac:parameter>
</ac:structured-macro>

<ac:structured-macro ac:name="panel">
  <ac:parameter ac:name="title">API Overview</ac:parameter>
  <ac:parameter ac:name="bgColor">#f4f5f7</ac:parameter>
  <ac:rich-text-body>
    <table>
      <tr><th>Base URL</th><td><code>https://api.example.com/v2</code></td></tr>
      <tr><th>Auth</th><td>Bearer token (OAuth 2.0)</td></tr>
      <tr><th>Rate Limit</th><td>1000 req/min per API key</td></tr>
      <tr><th>Content-Type</th><td><code>application/json</code></td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Authentication</h2>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">bash</ac:parameter>
  <ac:parameter ac:name="title">Get Access Token</ac:parameter>
  <ac:plain-text-body><![CDATA[curl -X POST https://api.example.com/oauth/token \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_SECRET"]]></ac:plain-text-body>
</ac:structured-macro>

<h2>Endpoints</h2>
<h3>GET /users</h3>
<p>Retrieve a paginated list of users.</p>
<table>
  <tr><th>Parameter</th><th>Type</th><th>Required</th><th>Description</th></tr>
  <tr><td><code>page</code></td><td>integer</td><td>No</td><td>Page number (default: 1)</td></tr>
  <tr><td><code>limit</code></td><td>integer</td><td>No</td><td>Items per page (max: 100)</td></tr>
  <tr><td><code>status</code></td><td>string</td><td>No</td><td>Filter by status: active, inactive</td></tr>
</table>

<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">Example Response</ac:parameter>
  <ac:rich-text-body>
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">json</ac:parameter>
      <ac:plain-text-body><![CDATA[{
  "data": [
    {"id": 1, "name": "Alice", "status": "active"},
    {"id": 2, "name": "Bob", "status": "inactive"}
  ],
  "pagination": {"page": 1, "limit": 20, "total": 142}
}]]></ac:plain-text-body>
    </ac:structured-macro>
  </ac:rich-text-body>
</ac:structured-macro>

<h3>POST /users</h3>
<p>Create a new user.</p>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">json</ac:parameter>
  <ac:parameter ac:name="title">Request Body</ac:parameter>
  <ac:plain-text-body><![CDATA[{
  "name": "Charlie",
  "email": "charlie@example.com",
  "role": "editor"
}]]></ac:plain-text-body>
</ac:structured-macro>

<h2>Error Codes</h2>
<table>
  <tr><th>Code</th><th>Meaning</th><th>Resolution</th></tr>
  <tr><td>401</td><td>Unauthorized</td><td>Check your bearer token</td></tr>
  <tr><td>403</td><td>Forbidden</td><td>Insufficient permissions for this resource</td></tr>
  <tr><td>429</td><td>Rate Limited</td><td>Wait and retry with exponential backoff</td></tr>
</table>
```

### Meeting Notes Template

```xml
<ac:structured-macro ac:name="details">
  <ac:rich-text-body>
    <table>
      <tr><th>Date</th><td>2026-03-24</td></tr>
      <tr><th>Attendees</th><td>@alice, @bob, @charlie</td></tr>
      <tr><th>Facilitator</th><td>@alice</td></tr>
      <tr><th>Type</th><td>Sprint Planning</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Agenda</h2>
<ol>
  <li>Sprint retrospective review</li>
  <li>Backlog grooming results</li>
  <li>Sprint goal and commitments</li>
</ol>

<h2>Discussion Notes</h2>
<p>[Notes captured during the meeting]</p>

<h2>Decisions</h2>
<table>
  <tr><th>Decision</th><th>Owner</th><th>Deadline</th></tr>
  <tr><td>Adopt PostgreSQL for new service</td><td>@bob</td><td>2026-04-01</td></tr>
</table>

<h2>Action Items</h2>
<ac:task-list>
  <ac:task>
    <ac:task-id>101</ac:task-id>
    <ac:task-status>incomplete</ac:task-status>
    <ac:task-body>@bob: Create database migration plan by 2026-04-01</ac:task-body>
  </ac:task>
  <ac:task>
    <ac:task-id>102</ac:task-id>
    <ac:task-status>incomplete</ac:task-status>
    <ac:task-body>@charlie: Update CI pipeline for new service by 2026-03-31</ac:task-body>
  </ac:task>
</ac:task-list>
```

### Incident Postmortem Template

```xml
<ac:structured-macro ac:name="details">
  <ac:rich-text-body>
    <table>
      <tr><th>Incident ID</th><td>INC-2026-042</td></tr>
      <tr><th>Severity</th><td><ac:structured-macro ac:name="status">
        <ac:parameter ac:name="colour">Red</ac:parameter>
        <ac:parameter ac:name="title">SEV-1</ac:parameter>
      </ac:structured-macro></td></tr>
      <tr><th>Duration</th><td>2h 15m</td></tr>
      <tr><th>Impact</th><td>Payment processing unavailable for 12% of users</td></tr>
      <tr><th>Incident Commander</th><td>@alice</td></tr>
      <tr><th>Postmortem Owner</th><td>@bob</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Summary</h2>
<p>One-paragraph description of what happened, the impact, and how it was resolved.</p>

<h2>Timeline</h2>
<table>
  <tr><th>Time (UTC)</th><th>Event</th></tr>
  <tr><td>14:02</td><td>Monitoring alert fires: PaymentLatencyHigh</td></tr>
  <tr><td>14:05</td><td>On-call engineer acknowledges, begins investigation</td></tr>
  <tr><td>14:20</td><td>Root cause identified: connection pool exhaustion</td></tr>
  <tr><td>14:35</td><td>Fix deployed: increased pool size, restarted pods</td></tr>
  <tr><td>16:17</td><td>All metrics returned to normal, incident closed</td></tr>
</table>

<h2>Root Cause</h2>
<p>Detailed technical explanation of what caused the incident.</p>

<h2>Contributing Factors</h2>
<ul>
  <li>Factor 1 and why it mattered</li>
  <li>Factor 2 and why it mattered</li>
</ul>

<h2>What Went Well</h2>
<ul>
  <li>Alert fired within 2 minutes of threshold breach</li>
  <li>Runbook was accurate and up to date</li>
</ul>

<h2>What Went Poorly</h2>
<ul>
  <li>No automated scaling policy for connection pools</li>
  <li>Took 15 minutes to identify root cause</li>
</ul>

<h2>Action Items</h2>
<table>
  <tr><th>Action</th><th>Owner</th><th>Priority</th><th>Jira</th><th>Due</th></tr>
  <tr>
    <td>Implement auto-scaling for DB pools</td>
    <td>@charlie</td>
    <td><ac:structured-macro ac:name="status">
      <ac:parameter ac:name="colour">Red</ac:parameter>
      <ac:parameter ac:name="title">P1</ac:parameter>
    </ac:structured-macro></td>
    <td><ac:structured-macro ac:name="jira">
      <ac:parameter ac:name="key">INFRA-567</ac:parameter>
    </ac:structured-macro></td>
    <td>2026-04-07</td>
  </tr>
</table>
```

### How-To Guide Template

```xml
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">2</ac:parameter>
</ac:structured-macro>

<ac:structured-macro ac:name="excerpt">
  <ac:parameter ac:name="atlassian-macro-output-type">BLOCK</ac:parameter>
  <ac:rich-text-body>
    <p>Step-by-step guide for [task]. Estimated time: 15 minutes.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="info">
  <ac:parameter ac:name="title">Prerequisites</ac:parameter>
  <ac:rich-text-body>
    <ul>
      <li>Access to the production VPN</li>
      <li>kubectl configured for the target cluster</li>
      <li>Admin role in the target namespace</li>
    </ul>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Step 1: Prepare Your Environment</h2>
<p>Instructions for step 1.</p>

<h2>Step 2: Execute the Change</h2>
<p>Instructions for step 2.</p>

<h2>Step 3: Verify</h2>
<p>How to confirm the change was successful.</p>

<h2>Troubleshooting</h2>
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">Error: Connection refused</ac:parameter>
  <ac:rich-text-body>
    <p>Check that the VPN is connected and your kubeconfig points to the correct cluster.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Related Pages</h2>
<ul>
  <li><ac:link><ri:page ri:content-title="Related Runbook" /></ac:link></li>
</ul>
```

---

## 5. Page Hierarchy Patterns

### Space Homepage Structure

```
Space Home (overview, recently updated, children)
├── Getting Started (onboarding, prerequisites)
├── Architecture
│   ├── ADR-001: Use PostgreSQL
│   ├── ADR-002: Event-Driven Architecture
│   └── System Diagrams
├── Services
│   ├── Auth Service
│   ├── Payment Service
│   └── Notification Service
├── Runbooks
│   ├── [Service]-specific runbooks
│   └── General operational runbooks
├── How-To Guides
│   ├── Developer guides
│   └── Operational guides
├── Meeting Notes
│   └── [Date]-[Topic]
└── Templates
    └── Reusable page templates
```

### Documentation Hub Page

```xml
<h1>Engineering Documentation Hub</h1>

<ac:structured-macro ac:name="recently-updated">
  <ac:parameter ac:name="max">5</ac:parameter>
  <ac:parameter ac:name="types">page</ac:parameter>
  <ac:parameter ac:name="labels">engineering-docs</ac:parameter>
</ac:structured-macro>

<h2>By Category</h2>
<table>
  <tr>
    <td>
      <h3>Architecture</h3>
      <ac:structured-macro ac:name="contentbylabel">
        <ac:parameter ac:name="cql">label = "adr" AND ancestor = currentContent()</ac:parameter>
        <ac:parameter ac:name="max">10</ac:parameter>
        <ac:parameter ac:name="sort">title</ac:parameter>
      </ac:structured-macro>
    </td>
    <td>
      <h3>Runbooks</h3>
      <ac:structured-macro ac:name="contentbylabel">
        <ac:parameter ac:name="cql">label = "runbook" AND ancestor = currentContent()</ac:parameter>
        <ac:parameter ac:name="max">10</ac:parameter>
        <ac:parameter ac:name="sort">title</ac:parameter>
      </ac:structured-macro>
    </td>
  </tr>
</table>

<h2>All Pages</h2>
<ac:structured-macro ac:name="children">
  <ac:parameter ac:name="depth">3</ac:parameter>
  <ac:parameter ac:name="sort">title</ac:parameter>
</ac:structured-macro>
```

### Labeling Strategy

Use labels for cross-cutting concerns that span the hierarchy:

| Label | Purpose |
|-------|---------|
| `adr` | Architecture Decision Records |
| `runbook` | Operational runbooks |
| `api-docs` | API documentation |
| `onboarding` | New-hire relevant pages |
| `needs-review` | Pages requiring review |
| `deprecated` | Outdated content (pending removal) |
| `team-{name}` | Team ownership (e.g., `team-platform`) |
| `service-{name}` | Service-specific docs (e.g., `service-payments`) |

Apply labels via the REST API when creating pages:

```json
{
  "metadata": {
    "labels": [
      {"name": "runbook"},
      {"name": "service-payments"},
      {"name": "team-platform"}
    ]
  }
}
```

---

