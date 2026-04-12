# XHTML Storage Format and Core Macros

Reference file for the `confluence-content-creator` skill. Covers XHTML storage format basics, core macros (TOC, code blocks, panels, status badges, expand, children, info/warning/note).

## Overview

This skill covers **what to write and how to format it** in Confluence XHTML storage format. For the REST API mechanics of creating, updating, and managing pages, see the `confluence-rest-api` skill. For project-specific documentation workflows and repo-to-Confluence sync, see the `confluence-documentation` skill.

<HARD-RULE>
Always validate XHTML before posting. Malformed storage format causes silent failures or broken pages. Use an XML linter or `python3 -c "from xml.etree.ElementTree import fromstring; fromstring('<div>YOUR_CONTENT</div>')"` to validate before any API call.
</HARD-RULE>

<HARD-RULE>
Escape user content in templates. Any dynamic text injected into XHTML templates must be XML-escaped (`&amp;` `&lt;` `&gt;` `&quot;`). Use `xml.sax.saxutils.escape()` in Python or equivalent in your language. Unescaped content breaks pages and can introduce XSS in Confluence.
</HARD-RULE>

<HARD-RULE>
Test macros in a draft space first. Create a sandbox space (e.g., key `SANDBOX`) and validate all macro combinations there before publishing to production spaces. Some macro interactions produce unexpected rendering.
</HARD-RULE>

---

## 1. XHTML Storage Format Basics

Confluence stores page content as XHTML with Atlassian-specific `ac:` namespace extensions. Every piece of content must be valid XML.

### Paragraphs and Headings

```xml
<h1>Heading 1</h1>
<h2>Heading 2</h2>
<h3>Heading 3</h3>
<h4>Heading 4</h4>
<h5>Heading 5</h5>
<h6>Heading 6</h6>

<p>A regular paragraph. All text must be inside block elements.</p>
<p>Another paragraph with <strong>bold</strong>, <em>italic</em>,
<code>inline code</code>, and <u>underlined</u> text.</p>
```

### Text Formatting

```xml
<!-- Bold and italic -->
<p><strong>Bold text</strong> and <em>italic text</em> and <strong><em>bold italic</em></strong></p>

<!-- Strikethrough and underline -->
<p><span style="text-decoration: line-through;">strikethrough</span> and <u>underline</u></p>

<!-- Colored text -->
<p><span style="color: rgb(255,0,0);">Red text</span></p>
<p><span style="color: rgb(0,128,0);">Green text</span></p>
<p><span style="color: rgb(0,0,255);">Blue text</span></p>

<!-- Subscript and superscript -->
<p>H<sub>2</sub>O and E=mc<sup>2</sup></p>

<!-- Monospace / code -->
<p>Use <code>git commit -m "message"</code> to commit.</p>

<!-- Block quote -->
<blockquote><p>This is a block quote with important context.</p></blockquote>

<!-- Horizontal rule -->
<hr />
```

### Lists

```xml
<!-- Unordered list -->
<ul>
  <li>First item</li>
  <li>Second item
    <ul>
      <li>Nested item</li>
      <li>Another nested item</li>
    </ul>
  </li>
  <li>Third item</li>
</ul>

<!-- Ordered list -->
<ol>
  <li>Step one</li>
  <li>Step two</li>
  <li>Step three</li>
</ol>

<!-- Task list (Confluence-specific) -->
<ac:task-list>
  <ac:task>
    <ac:task-id>1</ac:task-id>
    <ac:task-status>incomplete</ac:task-status>
    <ac:task-body>Review the architecture document</ac:task-body>
  </ac:task>
  <ac:task>
    <ac:task-id>2</ac:task-id>
    <ac:task-status>complete</ac:task-status>
    <ac:task-body>Update deployment guide</ac:task-body>
  </ac:task>
</ac:task-list>
```

### Tables

```xml
<table>
  <colgroup>
    <col style="width: 200px;" />
    <col style="width: 400px;" />
    <col style="width: 100px;" />
  </colgroup>
  <thead>
    <tr>
      <th>Component</th>
      <th>Description</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>API Gateway</td>
      <td>Routes requests to backend services</td>
      <td>Active</td>
    </tr>
    <tr>
      <td>Auth Service</td>
      <td>Handles JWT authentication</td>
      <td>Active</td>
    </tr>
  </tbody>
</table>
```

### Links

```xml
<!-- External link -->
<p><a href="https://example.com">External Link Text</a></p>

<!-- Link to another Confluence page (by page title) -->
<ac:link>
  <ri:page ri:content-title="Target Page Title" ri:space-key="MYSPACE" />
  <ac:plain-text-link-body><![CDATA[Display Text]]></ac:plain-text-link-body>
</ac:link>

<!-- Link to a page in the same space (omit space-key) -->
<ac:link>
  <ri:page ri:content-title="Target Page Title" />
</ac:link>

<!-- Link to an anchor on a page -->
<ac:link ac:anchor="section-name">
  <ri:page ri:content-title="Target Page Title" />
  <ac:plain-text-link-body><![CDATA[Jump to section]]></ac:plain-text-link-body>
</ac:link>

<!-- Link to an anchor on the same page -->
<ac:link ac:anchor="my-anchor">
  <ac:plain-text-link-body><![CDATA[Jump to anchor]]></ac:plain-text-link-body>
</ac:link>

<!-- Anchor definition (place where links can target) -->
<ac:structured-macro ac:name="anchor">
  <ac:parameter ac:name="">my-anchor</ac:parameter>
</ac:structured-macro>
```

### Images

```xml
<!-- Attached image -->
<ac:image ac:width="600">
  <ri:attachment ri:filename="architecture-diagram.png" />
</ac:image>

<!-- Image with alt text and border -->
<ac:image ac:alt="System Architecture" ac:border="true" ac:width="800">
  <ri:attachment ri:filename="architecture-diagram.png" />
</ac:image>

<!-- Image from another page -->
<ac:image ac:width="400">
  <ri:attachment ri:filename="logo.png">
    <ri:page ri:content-title="Brand Assets" ri:space-key="BRAND" />
  </ri:attachment>
</ac:image>

<!-- External image (URL) -->
<ac:image ac:width="500">
  <ri:url ri:value="https://example.com/image.png" />
</ac:image>
```

---

## 2. Core Macros

### Table of Contents

```xml
<!-- Basic TOC -->
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">3</ac:parameter>
  <ac:parameter ac:name="type">list</ac:parameter>
</ac:structured-macro>

<!-- Flat TOC (horizontal) -->
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="type">flat</ac:parameter>
  <ac:parameter ac:name="separator">pipe</ac:parameter>
  <ac:parameter ac:name="maxLevel">2</ac:parameter>
</ac:structured-macro>

<!-- TOC with specific heading range -->
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="minLevel">2</ac:parameter>
  <ac:parameter ac:name="maxLevel">4</ac:parameter>
  <ac:parameter ac:name="type">list</ac:parameter>
  <ac:parameter ac:name="outline">true</ac:parameter>
</ac:structured-macro>
```

### Code Block

```xml
<!-- Basic code block -->
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">python</ac:parameter>
  <ac:parameter ac:name="title">Example Script</ac:parameter>
  <ac:parameter ac:name="linenumbers">true</ac:parameter>
  <ac:parameter ac:name="collapse">false</ac:parameter>
  <ac:plain-text-body><![CDATA[def create_page(title, content):
    """Create a new Confluence page."""
    payload = {
        "type": "page",
        "title": title,
        "body": {"storage": {"value": content, "representation": "storage"}}
    }
    return requests.post(url, json=payload, auth=auth)
]]></ac:plain-text-body>
</ac:structured-macro>

<!-- Collapsed code block (click to expand) -->
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">json</ac:parameter>
  <ac:parameter ac:name="title">Full API Response (click to expand)</ac:parameter>
  <ac:parameter ac:name="collapse">true</ac:parameter>
  <ac:plain-text-body><![CDATA[{
  "id": "12345",
  "type": "page",
  "title": "My Page",
  "status": "current",
  "version": {"number": 3}
}]]></ac:plain-text-body>
</ac:structured-macro>
```

Supported language values: `actionscript3`, `bash`, `csharp`, `css`, `delphi`, `diff`, `erlang`, `go`, `groovy`, `html`, `java`, `javascript`, `json`, `perl`, `php`, `powershell`, `python`, `ruby`, `scala`, `sql`, `text`, `xml`, `yaml`.

### Info / Note / Warning / Tip Boxes

```xml
<!-- Info box (blue) -->
<ac:structured-macro ac:name="info">
  <ac:parameter ac:name="title">Prerequisites</ac:parameter>
  <ac:rich-text-body>
    <p>You need Python 3.9+ and Docker installed before proceeding.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- Note box (yellow) -->
<ac:structured-macro ac:name="note">
  <ac:parameter ac:name="title">Important Note</ac:parameter>
  <ac:rich-text-body>
    <p>This process requires downtime. Schedule during a maintenance window.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- Warning box (red) -->
<ac:structured-macro ac:name="warning">
  <ac:parameter ac:name="title">Danger</ac:parameter>
  <ac:rich-text-body>
    <p>Running this command in production will <strong>delete all data</strong>. There is no undo.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- Tip box (green) -->
<ac:structured-macro ac:name="tip">
  <ac:parameter ac:name="title">Pro Tip</ac:parameter>
  <ac:rich-text-body>
    <p>Use <code>--dry-run</code> flag to preview changes without applying them.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- Box without title -->
<ac:structured-macro ac:name="info">
  <ac:rich-text-body>
    <p>A simple informational callout without a title bar.</p>
  </ac:rich-text-body>
</ac:structured-macro>
```

### Panel

```xml
<!-- Panel with custom background color -->
<ac:structured-macro ac:name="panel">
  <ac:parameter ac:name="title">Summary</ac:parameter>
  <ac:parameter ac:name="borderStyle">solid</ac:parameter>
  <ac:parameter ac:name="borderColor">#ccc</ac:parameter>
  <ac:parameter ac:name="bgColor">#f4f5f7</ac:parameter>
  <ac:parameter ac:name="titleBGColor">#deebff</ac:parameter>
  <ac:rich-text-body>
    <p>Key metrics for this sprint:</p>
    <ul>
      <li>Velocity: 42 points</li>
      <li>Completion: 91%</li>
      <li>Bugs found: 3</li>
    </ul>
  </ac:rich-text-body>
</ac:structured-macro>
```

### Expand (Collapsible Section)

```xml
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">Click to see detailed configuration</ac:parameter>
  <ac:rich-text-body>
    <p>Put long content here that readers can optionally expand:</p>
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">yaml</ac:parameter>
      <ac:plain-text-body><![CDATA[server:
  port: 8080
  host: 0.0.0.0
database:
  url: postgresql://localhost:5432/mydb
  pool_size: 20]]></ac:plain-text-body>
    </ac:structured-macro>
  </ac:rich-text-body>
</ac:structured-macro>
```

### Children Display

```xml
<!-- List child pages -->
<ac:structured-macro ac:name="children">
  <ac:parameter ac:name="depth">2</ac:parameter>
  <ac:parameter ac:name="sort">title</ac:parameter>
  <ac:parameter ac:name="style">h4</ac:parameter>
</ac:structured-macro>

<!-- Children with excerpts -->
<ac:structured-macro ac:name="children">
  <ac:parameter ac:name="depth">1</ac:parameter>
  <ac:parameter ac:name="sort">title</ac:parameter>
  <ac:parameter ac:name="excerptType">simple</ac:parameter>
  <ac:parameter ac:name="first">20</ac:parameter>
</ac:structured-macro>
```

### Recently Updated

```xml
<ac:structured-macro ac:name="recently-updated">
  <ac:parameter ac:name="spaceKeys">DEV,OPS</ac:parameter>
  <ac:parameter ac:name="max">10</ac:parameter>
  <ac:parameter ac:name="types">page</ac:parameter>
  <ac:parameter ac:name="labels">project-docs</ac:parameter>
</ac:structured-macro>
```

---

## 3. Advanced Macros

### Status Badges (Colored Lozenge)

```xml
<!-- Available colours: Grey, Red, Yellow, Green, Blue, Purple -->
<ac:structured-macro ac:name="status">
  <ac:parameter ac:name="colour">Green</ac:parameter>
  <ac:parameter ac:name="title">APPROVED</ac:parameter>
</ac:structured-macro>

<ac:structured-macro ac:name="status">
  <ac:parameter ac:name="colour">Yellow</ac:parameter>
  <ac:parameter ac:name="title">IN REVIEW</ac:parameter>
</ac:structured-macro>

<ac:structured-macro ac:name="status">
  <ac:parameter ac:name="colour">Red</ac:parameter>
  <ac:parameter ac:name="title">BLOCKED</ac:parameter>
</ac:structured-macro>

<!-- Status in a table row for tracking -->
<tr>
  <td>Authentication Redesign</td>
  <td><ac:structured-macro ac:name="status">
    <ac:parameter ac:name="colour">Blue</ac:parameter>
    <ac:parameter ac:name="title">IN PROGRESS</ac:parameter>
  </ac:structured-macro></td>
  <td>Q1 2026</td>
</tr>
```

### Jira Issues Macro

```xml
<!-- Single Jira issue -->
<ac:structured-macro ac:name="jira">
  <ac:parameter ac:name="key">PROJ-1234</ac:parameter>
</ac:structured-macro>

<!-- JQL query results table -->
<ac:structured-macro ac:name="jira">
  <ac:parameter ac:name="jqlQuery">project = PROJ AND status = "In Progress" ORDER BY priority DESC</ac:parameter>
  <ac:parameter ac:name="columns">key,summary,assignee,status,priority</ac:parameter>
  <ac:parameter ac:name="maximumIssues">20</ac:parameter>
</ac:structured-macro>

<!-- Count only -->
<ac:structured-macro ac:name="jira">
  <ac:parameter ac:name="jqlQuery">project = PROJ AND type = Bug AND status != Done</ac:parameter>
  <ac:parameter ac:name="count">true</ac:parameter>
</ac:structured-macro>
```

### Page Properties / Page Properties Report

```xml
<!-- Page Properties (define structured metadata on a page) -->
<ac:structured-macro ac:name="details">
  <ac:rich-text-body>
    <table>
      <tr><th>Owner</th><td>Platform Team</td></tr>
      <tr><th>Status</th><td><ac:structured-macro ac:name="status">
        <ac:parameter ac:name="colour">Green</ac:parameter>
        <ac:parameter ac:name="title">ACTIVE</ac:parameter>
      </ac:structured-macro></td></tr>
      <tr><th>Last Review</th><td>2026-03-15</td></tr>
      <tr><th>Next Review</th><td>2026-06-15</td></tr>
      <tr><th>Category</th><td>Infrastructure</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- Page Properties Report (aggregate properties from child pages) -->
<ac:structured-macro ac:name="detailssummary">
  <ac:parameter ac:name="cql">label = "adr" AND ancestor = currentContent()</ac:parameter>
  <ac:parameter ac:name="headings">Owner,Status,Last Review,Category</ac:parameter>
  <ac:parameter ac:name="sortBy">Last Review</ac:parameter>
  <ac:parameter ac:name="reverseSort">true</ac:parameter>
</ac:structured-macro>
```

### Include Page / Excerpt

```xml
<!-- Include entire page content inline -->
<ac:structured-macro ac:name="include">
  <ac:parameter ac:name=""><ac:link>
    <ri:page ri:content-title="Shared Header" ri:space-key="TEMPLATES" />
  </ac:link></ac:parameter>
</ac:structured-macro>

<!-- Define an excerpt on a page -->
<ac:structured-macro ac:name="excerpt">
  <ac:parameter ac:name="atlassian-macro-output-type">BLOCK</ac:parameter>
  <ac:rich-text-body>
    <p>This service handles user authentication via OAuth 2.0 and issues JWT tokens
    for downstream API authorization.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- Include an excerpt from another page -->
<ac:structured-macro ac:name="excerpt-include">
  <ac:parameter ac:name=""><ac:link>
    <ri:page ri:content-title="Auth Service" ri:space-key="SERVICES" />
  </ac:link></ac:parameter>
  <ac:parameter ac:name="nopanel">true</ac:parameter>
</ac:structured-macro>
```

### Draw.io Diagrams

```xml
<!-- Embed a draw.io diagram stored as an attachment -->
<ac:structured-macro ac:name="drawio">
  <ac:parameter ac:name="diagramName">architecture-overview</ac:parameter>
  <ac:parameter ac:name="width">800</ac:parameter>
  <ac:parameter ac:name="border">true</ac:parameter>
  <ac:parameter ac:name="simpleViewer">false</ac:parameter>
</ac:structured-macro>
```

### Content by Label

```xml
<!-- Display pages matching a label query -->
<ac:structured-macro ac:name="contentbylabel">
  <ac:parameter ac:name="cql">label = "runbook" AND space = "OPS"</ac:parameter>
  <ac:parameter ac:name="max">25</ac:parameter>
  <ac:parameter ac:name="sort">title</ac:parameter>
  <ac:parameter ac:name="showLabels">true</ac:parameter>
  <ac:parameter ac:name="showSpace">false</ac:parameter>
  <ac:parameter ac:name="excerptType">simple</ac:parameter>
</ac:structured-macro>
```

### Table Filter (requires Table Filter app)

```xml
<ac:structured-macro ac:name="table-filter">
  <ac:rich-text-body>
    <table>
      <tr><th>Service</th><th>Environment</th><th>Status</th><th>Owner</th></tr>
      <tr><td>API Gateway</td><td>Production</td><td>Healthy</td><td>Platform</td></tr>
      <tr><td>Auth Service</td><td>Production</td><td>Degraded</td><td>Identity</td></tr>
      <tr><td>API Gateway</td><td>Staging</td><td>Healthy</td><td>Platform</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>
```

---

