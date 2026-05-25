---
name: confluence-content-creator
description: Use when creating or generating Confluence pages and content — XHTML storage format syntax, macros (TOC, code blocks, panels, status badges, expand, children, info/warning/note, jira issues, drawio), page templates, structured documentation patterns (ADRs, runbooks, project docs), markdown to Confluence conversion, bulk page generation, and content migration strategies.
---

# Confluence Content Creator

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [advanced-macros-templates.md](advanced-macros-templates.md) | advanced macros, documentation templates (technical specs, runbooks, meeting notes, decision records, ADRs) |
| [hierarchy-conversion-migration.md](hierarchy-conversion-migration.md) | page hierarchy patterns, Markdown-to-Confluence conversion, bulk page generation, content migration, and best practices |
| [xhtml-core-macros.md](xhtml-core-macros.md) | XHTML storage format basics, core macros (TOC, code blocks, panels, status badges, expand, children, info/warning/note) |

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
| Using wiki markup syntax in storage format API calls | Confluence storage format is XHTML, not wiki markup — content renders as raw text | Always use XHTML storage format with proper macro XML syntax for programmatic page creation |
| Creating deeply nested page hierarchies (5+ levels) | Users cannot navigate; search becomes the only discovery method; maintenance burden increases exponentially | Keep hierarchy to 3 levels max; use labels and CQL macros for cross-cutting organization |
| Embedding large images without thumbnails or attachments | Pages load slowly; content store bloats; users on slow connections time out | Use ac:image with width/height attributes; attach images to the page rather than hotlinking external URLs |
| Writing content without structured macros (panels, info, warning) | Wall-of-text pages get skimmed and missed; critical information blends into background noise | Use info/warning/note panels for callouts; use expand macros for optional detail; use TOC for navigation |
| Not validating XHTML before API submission | Malformed XML causes silent failures or 500 errors that are difficult to debug | Wrap content in a div and parse with an XML parser before submission; catch and report validation errors |
