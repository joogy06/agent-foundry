# Browser MCP Allow-List — Envelope D (Read-Only Analytics)

Canonical allow-list for browser MCP tool usage within `founder-validation`. Envelope D permits
read-only access to analytics dashboards and pages. Write actions are FORBIDDEN (HR-V3).

---

## Allowed Tools

| Tool | Status | Purpose | Notes |
|---|---|---|---|
| `tabs_context_mcp` | ALLOWED | Get context of open tabs | Tab management |
| `tabs_create_mcp` | ALLOWED | Create a new tab | Tab management |
| `navigate` | ALLOWED | Load URLs (GET only) | Navigate to analytics pages |
| `get_page_text` | ALLOWED | Extract body text from current page | Read page content |
| `read_page` | ALLOWED | Accessibility tree for DOM elements | Read DOM structure |
| `read_network_requests` | ALLOWED | XHR/Fetch responses | GA4 JSON, GSC JSON, API responses |
| `read_console_messages` | ALLOWED | JavaScript errors on pages | Debug landing pages |
| `find` | ALLOWED | Natural-language element search | Locate specific elements |

---

## Gated Tools (Conditional Access)

### `javascript_tool` — GATED

**Allowed expressions only.** The following regex allow-list defines what JavaScript can be
executed. Any expression not matching is BLOCKED.

```
Allowed patterns (regex):
  ^document\.querySelector\(.*\)$
  ^window\.dataLayer(\[.*\])?$
  ^document\.head\..*$
  ^JSON\.parse\(.*\)$
  ^document\.querySelectorAll\(.*\)\.length$
  ^document\.title$
  ^window\.location\.(href|hostname|pathname|search)$
  ^document\.getElementsBy(TagName|ClassName|Id)\(.*\)(\[.*\])?(\..*)?$
```

**Blocked patterns (explicit deny — even if they match an allow pattern):**
- Any expression containing `fetch(` or `XMLHttpRequest`
- Any expression containing `.click(` or `.submit(`
- Any expression containing `=` (assignment operator) unless inside `JSON.parse`
- Any expression containing `window.open`
- Any expression containing `eval(`
- Any expression containing `document.cookie`
- Any expression containing `localStorage` or `sessionStorage`

**Rationale:** `javascript_tool` is powerful enough to modify page state or exfiltrate data.
The allow-list restricts it to pure read operations: reading DOM elements, reading dataLayer
(for GA4), reading page metadata.

### `computer` — GATED

**Allowed actions only:**
- `screenshot` — ALLOWED (capture analytics dashboards for evidence)
- `scroll` — ALLOWED (navigate long pages)

**Blocked actions:**
- `left_click` — BLOCKED (would trigger navigation, form submission, etc.)
- `right_click` — BLOCKED
- `double_click` — BLOCKED
- `middle_click` — BLOCKED
- `type` — BLOCKED (would input text into forms)
- `key` — BLOCKED (would trigger keyboard shortcuts)
- `drag` — BLOCKED

---

## Blocked Tools (No Access)

| Tool | Status | Reason |
|---|---|---|
| `form_input` | BLOCKED | Write action — fills forms. FORBIDDEN in Envelope D. |
| `upload_image` | BLOCKED | Write action — uploads files. FORBIDDEN in Envelope D. |
| `gif_creator` | BLOCKED | Not relevant to analytics reading. |
| `shortcuts_execute` | BLOCKED | Executes browser shortcuts — could trigger any action. |

---

## Enforcement Protocol

When `founder-validation` encounters a browser MCP call:

1. **Check the tool name against this allow-list.**
2. **If ALLOWED:** proceed with the call.
3. **If GATED:** check the specific action/expression against the sub-allow-list.
   - If matches allow pattern AND does not match deny pattern: proceed.
   - If does not match or matches deny pattern: BLOCK with explanation.
4. **If BLOCKED:** refuse immediately with:
   > "Tool `{tool_name}` is not permitted in Envelope D (read-only analytics). Founder-validation
   > only reads analytics data — it does not interact with pages. See HR-V3."
5. **If tool name is UNKNOWN (not in any list):** BLOCK with:
   > "Tool `{tool_name}` is not on the Envelope D allow-list. Unknown tools are blocked by
   > default. If this tool is needed, it must be added to the allow-list in a future update."

---

## Version Notes

- **Envelope D** = read-only analytics. Current phase.
- **Envelope B/C** = write actions (form filling, outreach, etc.). Deferred to Phase 2.5.
  Requires clean UX for approval-per-message + ethical framework before enabling.
- **Envelope A** = full browser automation. Not planned. Out of scope for founder family.

Tool names are version-pinned to the `claude-in-chrome` MCP server interface as of 2026-04.
If the MCP server renames or adds tools, this allow-list must be updated explicitly.
