---
name: confluence-documentation
description: Use when project-documentation preferences indicate Confluence export is needed, or when creating Confluence-formatted documentation pages. Covers XHTML storage format, macros (TOC, children, search, panels, code blocks, status badges), REST API page creation, and keeping repo markdown in sync with Confluence.
family: confluence
disambiguation: The project-documentation EXPORT path — when and how project docs become Confluence pages. General page authoring syntax and macros is confluence-content-creator.
---

# Confluence Documentation

## Overview

Confluence pages use XHTML storage format with `ac:` namespace macros. Files are stored as `.xml` in `docs/confluence/` and can be pushed directly to Confluence via REST API. **The repo markdown is always the source of truth** — Confluence files are the export format.

## Directory Structure

```
docs/confluence/
├── INDEX.xml              # Master index with TOC, children, search
├── architecture.xml       # System architecture
├── setup-guide.xml        # Dev environment setup
├── deployment.xml         # Deployment procedures
└── [feature-name].xml     # One page per major feature/component
```

## INDEX.xml Template

```xml
<h1>Project Documentation</h1>

<ac:structured-macro ac:name="info">
  <ac:parameter ac:name="title">About This Documentation</ac:parameter>
  <ac:rich-text-body>
    <p>Auto-generated documentation index. Source of truth is the code repository.
    Last updated: [DATE]</p>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Table of Contents</h2>
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">2</ac:parameter>
  <ac:parameter ac:name="type">list</ac:parameter>
</ac:structured-macro>

<h2>All Documentation Pages</h2>
<ac:structured-macro ac:name="children">
  <ac:parameter ac:name="depth">2</ac:parameter>
  <ac:parameter ac:name="sort">title</ac:parameter>
  <ac:parameter ac:name="style">h4</ac:parameter>
</ac:structured-macro>

<h2>Search Documentation</h2>
<ac:structured-macro ac:name="contentbylabel">
  <ac:parameter ac:name="cql">label = "project-docs" AND type = "page"</ac:parameter>
  <ac:parameter ac:name="max">50</ac:parameter>
  <ac:parameter ac:name="sort">modified</ac:parameter>
  <ac:parameter ac:name="showLabels">true</ac:parameter>
</ac:structured-macro>

<ac:structured-macro ac:name="livesearch">
  <ac:parameter ac:name="spaceKey">PROJECTSPACE</ac:parameter>
  <ac:parameter ac:name="placeholder">Search project documentation...</ac:parameter>
</ac:structured-macro>
```

**Search:** The `contentbylabel` macro uses CQL to filter pages by the `project-docs` label. The `livesearch` macro adds an interactive search box scoped to the project space. Label ALL documentation pages with `project-docs` when uploading.

## Feature/Component Page Template

```xml
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">3</ac:parameter>
</ac:structured-macro>

<h1>[Feature Name]</h1>

<ac:structured-macro ac:name="panel">
  <ac:parameter ac:name="title">Quick Reference</ac:parameter>
  <ac:rich-text-body>
    <table>
      <tr><th>Status</th><td><ac:structured-macro ac:name="status">
        <ac:parameter ac:name="colour">Green</ac:parameter>
        <ac:parameter ac:name="title">ACTIVE</ac:parameter>
      </ac:structured-macro></td></tr>
      <tr><th>Owner</th><td>[Team/Person]</td></tr>
      <tr><th>Last Updated</th><td>[Date]</td></tr>
      <tr><th>Source</th><td>[repo path]</td></tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Overview</h2>
<p>[What this feature does and why it exists]</p>

<h2>Architecture</h2>
<p>[Architecture description — include diagram if enabled in preferences]</p>

<h2>Configuration</h2>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">bash</ac:parameter>
  <ac:parameter ac:name="title">Environment Variables</ac:parameter>
  <ac:plain-text-body><![CDATA[
DATABASE_URL=postgresql://...
SECRET_KEY=...
  ]]></ac:plain-text-body>
</ac:structured-macro>

<h2>API Reference</h2>
<table>
  <tr><th>Endpoint</th><th>Method</th><th>Description</th></tr>
  <tr><td>/api/resource</td><td>GET</td><td>List resources</td></tr>
</table>

<h2>Change Log</h2>
<table>
  <tr><th>Date</th><th>Change</th><th>Author</th></tr>
  <tr><td>[Date]</td><td>[Description]</td><td>[Who]</td></tr>
</table>
```

## Macro Quick Reference

| Macro | Purpose | Syntax |
|-------|---------|--------|
| `toc` | Auto table of contents | `<ac:structured-macro ac:name="toc"><ac:parameter ac:name="maxLevel">3</ac:parameter></ac:structured-macro>` |
| `children` | List child pages | `<ac:structured-macro ac:name="children"><ac:parameter ac:name="depth">2</ac:parameter></ac:structured-macro>` |
| `contentbylabel` | CQL search by label/space | See INDEX.xml template |
| `livesearch` | Interactive search box | `<ac:structured-macro ac:name="livesearch"><ac:parameter ac:name="spaceKey">KEY</ac:parameter></ac:structured-macro>` |
| `info` / `note` / `warning` / `tip` | Callout panels | `<ac:structured-macro ac:name="info"><ac:rich-text-body><p>...</p></ac:rich-text-body></ac:structured-macro>` |
| `panel` | Custom styled box | See feature template |
| `code` | Syntax-highlighted code | `<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body><![CDATA[...]]></ac:plain-text-body></ac:structured-macro>` |
| `status` | Coloured badge | `<ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Green</ac:parameter><ac:parameter ac:name="title">DONE</ac:parameter></ac:structured-macro>` |

**Status colours:** Grey, Red, Yellow, Green, Blue, Purple

## CQL Search Examples

| Goal | CQL |
|------|-----|
| All docs in space | `space = "MYSPACE" AND type = page` |
| Pages with label | `label = "project-docs"` |
| Space + label | `space = "MYSPACE" AND label = "project-docs"` |
| Recent changes | `space = "MYSPACE" ORDER BY lastmodified DESC` |
| Exclude archived | `label = "project-docs" AND space != "ARCHIVE"` |

## REST API — Creating/Updating Pages

### Create Page

```
POST /rest/api/content/
Content-Type: application/json

{
  "type": "page",
  "title": "Page Title",
  "space": { "key": "PROJECTSPACE" },
  "ancestors": [{ "id": "PARENT_PAGE_ID" }],
  "body": {
    "storage": {
      "value": "<CONTENT FROM .xml FILE>",
      "representation": "storage"
    }
  },
  "metadata": {
    "labels": [{ "name": "project-docs" }]
  }
}
```

### Update Page

```
PUT /rest/api/content/{pageId}
Content-Type: application/json

{
  "version": { "number": CURRENT_VERSION + 1 },
  "title": "Page Title",
  "type": "page",
  "body": {
    "storage": {
      "value": "<UPDATED CONTENT>",
      "representation": "storage"
    }
  }
}
```

**Note:** Updates require the current version number incremented by 1. Get it with `GET /rest/api/content/{pageId}`.

## Keeping in Sync

When repo markdown docs are updated:
1. Update the corresponding `.xml` in `docs/confluence/`
2. Push via REST API if Confluence instance is configured
3. All pages get `project-docs` label for searchability
4. Update the Change Log table in each affected page

**Rule:** Repo markdown = source of truth. Never edit Confluence directly — always update the `.xml` files first.

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Edit Confluence pages directly | Out of sync with repo — always update .xml first |
| Skip the `project-docs` label | Search and contentbylabel macros depend on it |
| Use wiki markup in .xml files | Storage format (XHTML) is the standard — wiki markup is legacy |
| Forget version number on updates | API rejects updates without correct version increment |
| Store credentials in .xml files | These files are in the repo — use placeholders |
