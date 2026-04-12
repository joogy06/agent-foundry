# Page Hierarchy, Conversion, Bulk Generation, Migration, and Best Practices

Reference file for the `confluence-content-creator` skill. Covers page hierarchy patterns, Markdown-to-Confluence conversion, bulk page generation, content migration, and best practices.

## 6. Markdown to Confluence Conversion

### Element Mapping

| Markdown | Confluence XHTML Storage Format |
|----------|---------------------------------|
| `# H1` | `<h1>H1</h1>` |
| `**bold**` | `<strong>bold</strong>` |
| `*italic*` | `<em>italic</em>` |
| `` `code` `` | `<code>code</code>` |
| `[text](url)` | `<a href="url">text</a>` |
| `![alt](img.png)` | `<ac:image><ri:url ri:value="img.png" /></ac:image>` |
| `> blockquote` | `<blockquote><p>blockquote</p></blockquote>` |
| `---` | `<hr />` |
| `- item` | `<ul><li>item</li></ul>` |
| `1. item` | `<ol><li>item</li></ol>` |
| ` ```lang ` | `<ac:structured-macro ac:name="code">` ... (see code block macro) |
| `| table |` | `<table><tr><th>table</th></tr></table>` |

### Tools for Conversion

**mark** (recommended for CLI workflows):

```bash
# Install
go install github.com/kovetskiy/mark@latest

# Convert and publish a single file
mark -f document.md \
  --base-url https://confluence.example.com \
  --username user@example.com \
  --password API_TOKEN \
  --space MYSPACE

# Markdown file requires frontmatter:
# <!-- Space: MYSPACE -->
# <!-- Title: My Document -->
# <!-- Parent: Parent Page Title -->
```

**Python conversion function** (for custom pipelines):

```python
import re
from xml.sax.saxutils import escape

def md_to_confluence(md_text: str) -> str:
    """Convert basic Markdown to Confluence XHTML storage format."""
    lines = md_text.split('\n')
    html_lines = []
    in_code_block = False
    code_lang = ''
    code_content = []
    in_list = False
    list_type = None

    for line in lines:
        # Code blocks
        if line.startswith('```'):
            if in_code_block:
                html_lines.append(
                    f'<ac:structured-macro ac:name="code">'
                    f'<ac:parameter ac:name="language">{code_lang}</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{"chr(10)".join(code_content)}]]>'
                    f'</ac:plain-text-body></ac:structured-macro>'
                )
                in_code_block = False
                code_content = []
            else:
                in_code_block = True
                code_lang = line[3:].strip() or 'text'
            continue

        if in_code_block:
            code_content.append(line)
            continue

        # Headings
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = escape(heading_match.group(2))
            html_lines.append(f'<h{level}>{text}</h{level}>')
            continue

        # Bold and italic inline
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
        line = re.sub(r'`(.+?)`', r'<code>\1</code>', line)

        # Links
        line = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', line)

        if line.strip():
            html_lines.append(f'<p>{line.strip()}</p>')

    return '\n'.join(html_lines)
```

---

## 7. Bulk Page Generation

### Python Script: Generate Pages from a Template

```python
"""Bulk-create Confluence pages from a CSV manifest."""
import csv
import json
import requests
from xml.sax.saxutils import escape

CONFLUENCE_URL = "https://confluence.example.com"
AUTH = ("user@example.com", "API_TOKEN")
SPACE_KEY = "DOCS"

def load_template(path: str) -> str:
    with open(path) as f:
        return f.read()

def create_page(title: str, body: str, parent_id: str, labels: list[str]) -> dict:
    """Create a single Confluence page. See confluence-rest-api skill for details."""
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": SPACE_KEY},
        "ancestors": [{"id": parent_id}],
        "body": {"storage": {"value": body, "representation": "storage"}},
        "metadata": {"labels": [{"name": lbl} for lbl in labels]},
    }
    resp = requests.post(
        f"{CONFLUENCE_URL}/rest/api/content",
        json=payload,
        auth=AUTH,
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()

def render_template(template: str, variables: dict[str, str]) -> str:
    """Replace placeholders, escaping user content for XHTML safety."""
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", escape(value))
    return rendered

def bulk_create_from_csv(csv_path: str, template_path: str, parent_id: str):
    template = load_template(template_path)
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.pop("title")
            labels = [l.strip() for l in row.pop("labels", "").split(",") if l.strip()]
            body = render_template(template, row)
            result = create_page(title, body, parent_id, labels)
            print(f"Created: {result['title']} (ID: {result['id']})")

# Example CSV (services.csv):
# title,service_name,owner,status,labels
# Auth Service,auth-service,Identity Team,ACTIVE,"service-docs,team-identity"
# Payment Service,payment-service,Payments Team,ACTIVE,"service-docs,team-payments"

if __name__ == "__main__":
    bulk_create_from_csv("services.csv", "templates/service.xml", "123456")
```

### Generate API Docs from OpenAPI Spec

```python
"""Generate Confluence pages from an OpenAPI 3.x spec."""
import json
from xml.sax.saxutils import escape

def openapi_to_confluence(spec_path: str) -> str:
    with open(spec_path) as f:
        spec = json.load(f)

    parts = [
        f"<h1>{escape(spec['info']['title'])}</h1>",
        f"<p>{escape(spec['info'].get('description', ''))}</p>",
    ]

    for path, methods in spec.get("paths", {}).items():
        for method, details in methods.items():
            summary = escape(details.get("summary", ""))
            parts.append(f"<h2>{method.upper()} {escape(path)}</h2>")
            parts.append(f"<p>{summary}</p>")

            # Parameters table
            params = details.get("parameters", [])
            if params:
                parts.append("<table><tr><th>Name</th><th>In</th>"
                             "<th>Required</th><th>Description</th></tr>")
                for p in params:
                    parts.append(
                        f"<tr><td><code>{escape(p['name'])}</code></td>"
                        f"<td>{escape(p['in'])}</td>"
                        f"<td>{p.get('required', False)}</td>"
                        f"<td>{escape(p.get('description', ''))}</td></tr>"
                    )
                parts.append("</table>")

    return "\n".join(parts)
```

---

## 8. Content Migration

### Migration Checklist

1. **Inventory** -- Export a full list of pages from the source wiki (title, hierarchy, attachments)
2. **Map hierarchy** -- Design the Confluence space structure before migrating
3. **Convert content** -- Transform source format (MediaWiki, Markdown, Google Docs) to XHTML storage format
4. **Handle attachments** -- Upload attachments to Confluence via REST API, update references in content
5. **Fix internal links** -- Rewrite links to use Confluence `ac:link` format
6. **Apply labels** -- Tag migrated pages for discoverability
7. **Validate** -- Check every page renders correctly in Confluence
8. **Redirect** -- Set up redirects from old wiki URLs if possible

### Python Migration Script Skeleton

```python
"""Migrate pages from a source directory to Confluence."""
import os
import re
import json
import requests
from xml.sax.saxutils import escape
from pathlib import Path

CONFLUENCE_URL = "https://confluence.example.com"
AUTH = ("user@example.com", "API_TOKEN")

def upload_attachment(page_id: str, file_path: str) -> dict:
    """Upload a file as an attachment to a Confluence page."""
    headers = {"X-Atlassian-Token": "nocheck"}
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment",
            auth=AUTH,
            headers=headers,
            files={"file": (os.path.basename(file_path), f)},
        )
    resp.raise_for_status()
    return resp.json()

def fix_internal_links(content: str, title_map: dict[str, str]) -> str:
    """Replace markdown-style links with Confluence ac:link elements."""
    def replace_link(match):
        text = match.group(1)
        target = match.group(2)
        if target in title_map:
            return (
                f'<ac:link><ri:page ri:content-title="{escape(title_map[target])}" />'
                f'<ac:plain-text-link-body><![CDATA[{text}]]>'
                f'</ac:plain-text-link-body></ac:link>'
            )
        return f'<a href="{escape(target)}">{escape(text)}</a>'

    return re.sub(r'\[(.+?)\]\((.+?)\)', replace_link, content)

def migrate_directory(source_dir: str, space_key: str, parent_id: str):
    """Walk a directory tree and create corresponding Confluence pages."""
    title_map = {}  # filename -> page title

    # First pass: build title map
    for md_file in sorted(Path(source_dir).rglob("*.md")):
        title = md_file.stem.replace("-", " ").title()
        title_map[md_file.name] = title

    # Second pass: create pages
    for md_file in sorted(Path(source_dir).rglob("*.md")):
        title = title_map[md_file.name]
        content = md_file.read_text()

        # Convert markdown to XHTML (use md_to_confluence from section 6)
        xhtml = md_to_confluence(content)
        xhtml = fix_internal_links(xhtml, title_map)

        result = create_page(title, xhtml, parent_id, ["migrated"])
        page_id = result["id"]

        # Upload images referenced in the same directory
        for img in md_file.parent.glob("*.png"):
            upload_attachment(page_id, str(img))
        for img in md_file.parent.glob("*.jpg"):
            upload_attachment(page_id, str(img))

        print(f"Migrated: {md_file} -> {title} (ID: {page_id})")
```

### Handling Attachments in Content

After uploading attachments, update image references in the XHTML content:

```python
def rewrite_image_refs(content: str) -> str:
    """Convert markdown image references to Confluence attachment references."""
    def replace_img(match):
        alt = match.group(1)
        filename = os.path.basename(match.group(2))
        return (
            f'<ac:image ac:alt="{escape(alt)}">'
            f'<ri:attachment ri:filename="{escape(filename)}" />'
            f'</ac:image>'
        )
    return re.sub(r'!\[(.+?)\]\((.+?)\)', replace_img, content)
```

---

## 9. Best Practices

### Page Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| ADR | `ADR-NNN: Title` | `ADR-007: Use Event Sourcing` |
| Runbook | `Runbook: Service - Scenario` | `Runbook: Payment Service - High Latency` |
| How-to | `How to [Verb] [Object]` | `How to Deploy to Production` |
| Meeting | `YYYY-MM-DD Meeting Topic` | `2026-03-24 Sprint Planning` |
| API docs | `[Service] API Reference` | `Payment Service API Reference` |
| Postmortem | `INC-YYYY-NNN: Title` | `INC-2026-042: Payment Outage` |

### Template Reuse Pattern

Create template pages in a `Templates` space and include them:

```xml
<!-- On a page that acts as a template, define reusable sections as excerpts -->
<ac:structured-macro ac:name="excerpt">
  <ac:parameter ac:name="atlassian-macro-output-type">BLOCK</ac:parameter>
  <ac:parameter ac:name="name">standard-footer</ac:parameter>
  <ac:rich-text-body>
    <hr />
    <p><em>This page is maintained by the Platform team. For questions, reach out in #platform-support.
    Last reviewed: see page properties above.</em></p>
  </ac:rich-text-body>
</ac:structured-macro>

<!-- On consuming pages, pull in the excerpt -->
<ac:structured-macro ac:name="excerpt-include">
  <ac:parameter ac:name=""><ac:link>
    <ri:page ri:content-title="Standard Footer" ri:space-key="TEMPLATES" />
  </ac:link></ac:parameter>
  <ac:parameter ac:name="nopanel">true</ac:parameter>
</ac:structured-macro>
```

### Content Maintenance Rules

- **Limit nesting to 3 levels deep.** Deeper hierarchies make pages hard to find. Use labels and `contentbylabel` macros for cross-cutting navigation instead.
- **Add a `details` macro (Page Properties) to every structured page.** This enables Page Properties Report rollups on parent pages for dashboards.
- **Use the `excerpt` macro on every page.** The first paragraph summary shows up in search results and `children` macro listings when `excerptType` is set.
- **Label every page consistently.** Labels power `contentbylabel`, search, and reporting. Define a labeling taxonomy and enforce it.
- **Include a "Last Reviewed" date** in Page Properties. Set up quarterly review reminders. Pages older than 6 months without review should be flagged with the `needs-review` label.
- **Prefer structured tables over free-form text** for metadata, status tracking, and comparisons. Tables are scannable and work with Page Properties Report.

### XHTML Validation Helper

Always validate before posting. A quick Python validator:

```python
from xml.etree.ElementTree import fromstring

def validate_confluence_xhtml(content: str) -> bool:
    """Validate that content is well-formed XML. Wrap in a div for fragment parsing."""
    try:
        fromstring(f"<div>{content}</div>")
        return True
    except Exception as e:
        print(f"XHTML validation failed: {e}")
        return False
```

### Common Pitfalls

| Pitfall | Consequence | Fix |
|---------|-------------|-----|
| Unescaped `&` in text | XML parse error, page won't save | Use `&amp;` or escape function |
| Missing `<![CDATA[...]]>` in code blocks | Code with `<` or `>` breaks XML | Always wrap code in CDATA |
| Unclosed tags (`<br>` instead of `<br />`) | XHTML validation failure | Use self-closing tags |
| Nested `<![CDATA[` sections | XML parser error | Escape inner CDATA end markers as `]]]]><![CDATA[>` |
| Wrong macro name spelling | Macro renders as raw text | Verify against Confluence macro documentation |
| Using wiki markup syntax | Not recognized in storage format | Always use XHTML storage format |
| Forgetting version number on update | 409 Conflict error | GET current version first, increment by 1 |
