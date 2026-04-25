---
name: skeleton-extractor
description: "Use when transforming an HTML mockup into a draft design-skeleton.v1 YAML. Walks the DOM via puppeteer-core at 3 breakpoints, extracts bboxes + computed styles (resolved back to declared tokens) + wired interaction handlers, and emits one draft ready for visual-architect review. Runs the Node subprocess under trusted_runner discipline (CB3-compliant: trusted runner owns execution, skill only generates draft). Invoked by visual-architect at design-phase freeze; NEVER writes the frozen skeleton itself."
---

# skeleton-extractor

Transforms an HTML mockup into a pre-freeze draft `design-skeleton.v1` YAML. One skill, one operation (`extract`), one subprocess, one stdout JSON blob.

## When to invoke

Called by `visual-architect` at design-phase freeze (see design doc §2.5), after the user has approved an HTML mockup. The draft it emits is reviewed by the user, amended (binds_to URIs, bbox confirmations, unresolved-token decisions), then HMAC-signed and written to `.design-ledger/skeletons/<screen>.yaml`. Skeleton-extractor does NOT freeze — that is visual-architect's job.

## When NOT to invoke

- After the skeleton is frozen — verification is `visual-arbiter`'s job (pure-Python verdict on stdout, CB4).
- For micro-drift re-approval — that is `design-drift-arbiter`'s job.
- As a runtime live probe on the built product — subprocess targets only the approved mockup.

## Public API

A single op.

### `extract`

```bash
python3 skills/skeleton-extractor/scripts/extract.py \
  --mockup /abs/path/to/mockup.html \
  --out    /abs/path/out.draft.yaml \
  [--breakpoints 420,700,1280] \
  [--tokens-path /abs/path/to/index.yaml]
```

Arguments:

| Flag | Required | Default | Meaning |
|---|---|---|---|
| `--mockup` | yes | — | Absolute path to the HTML mockup (file read via `file://` URL) |
| `--out` | yes | — | Where the draft YAML is written (trusted_runner.atomic_write_bytes) |
| `--breakpoints` | no | `420,700,1280` | Comma-list of viewport widths; one extraction pass per width |
| `--tokens-path` | no | none | Optional path to `index.yaml` with declared `tokens:` block, used for `getComputedStyle` back-resolution |
| `--timeout` | no | `120` | Node subprocess timeout seconds |

### Output shape

Draft YAML conforming to `design-skeleton.v1` (§2.3):

```yaml
schema: design-skeleton.v1
draft: true
generated_by: skeleton-extractor@1.0.0
generated_at: "2026-04-24T00:00:00Z"
breakpoints: [420, 700, 1280]
fonts_loaded: true
fonts_ready_max_ms: 412
elements:
  - id: grid_card_nth_of_type_1
    selector: "#grid .card:nth-of-type(1)"
    role: article
    kind: element
    bbox:
      mobile:  {x:16, y:96,  w:388, h:260}
      tablet:  {x:24, y:116, w:320, h:240}
      desktop: {x:48, y:136, w:384, h:220}
    tokens_used:
      background_color: "token://color.paper"
      border_color:     "token://color.ink"
    tokens_raw_per_bp: { ... }           # preserved for the arbiter's audit trail
    interactions:
      - {event: click, binds_to: null}   # user fills during visual-architect freeze
    shadow_dom_opaque: false
unresolved_tokens_report:
  - {selector: ".banner", field: color, computed: "#ac3b3b", breakpoint: desktop}
concerns: []
```

## Flow (HTML mockup path → subprocess → draft YAML)

1. Python wrapper (`scripts/extract.py`) parses args, loads declared tokens, checks that `/bin/google-chrome` and the Node binary exist.
2. Wrapper spawns `node skills/_meta/skeleton_extractor.mjs` with a sanitized env (mirrors `trusted_runner._run_pytest`), a 120s timeout, and a single JSON stdin payload `{mockupHtml, breakpoints, tokens}`.
3. Node subprocess (`_meta/skeleton_extractor.mjs`, ~300 LOC) launches puppeteer-core pointed at `/bin/google-chrome`. For each breakpoint: `setViewport` before `page.goto(file://mockup, {waitUntil: "networkidle0"})`, then `await document.fonts.ready` + 300ms settle (font-race guard, §2.10). Walks visible elements with role/data-*/event-handler, emits per-element `{selector, role, bbox, tokens_raw, interactions, shadow_dom_opaque}`.
4. Node resolves computed `tokens_raw` back to declared tokens (§2.4 step 4). `var(--accent-sun)` chains resolve through `:root`. First exact match wins; unresolved values are surfaced in `unresolved_tokens_report` — **never** auto-added to `index.yaml` (D2 strict).
5. Node merges per-breakpoint elements by stable selector into one record with a `bbox: {mobile, tablet, desktop}` map.
6. Node emits ONE JSON blob on stdout; exit 0 on success.
7. Python wrapper parses the JSON, serializes to YAML, and writes via `trusted_runner.atomic_write_bytes`. No partial writes, no stream output, no ledger writes from inside the subprocess.

## CB3 compliance

The subprocess is CB3-compliant: `trusted_runner` (invoked from the Python wrapper) owns subprocess execution and captures stdout; the skill/subprocess only generates a draft. The final persisted file goes through `atomic_write_bytes` (same helper bob uses for bundles and claims).

## Edge cases (§2.10)

| Edge case | Handling |
|---|---|
| Font-loading race | `fonts.ready + 300ms` settle; >2s = warning concern; >5s = blocker concern + `fonts_loaded: false` |
| Viewport-unit CSS (vw/vh) | `setViewport` always called BEFORE `goto()` — deterministic per breakpoint |
| Pseudo-elements | Walked by DOM iteration; current version records host element tokens only; `::before/::after` explicit slots are v2 |
| Shadow DOM | Open roots recursed; closed roots → `shadow_dom_opaque: true` marker on host (arbiter treats as black box) |
| Responsive accident vs intent | bbox deltas between neighboring breakpoints are recorded but NOT auto-flagged; visual-architect reviews |
| Animations / transitions | Static after-settle state only; `must_satisfy.known_deferred: [animations]` is visual-architect's concern |

## Failure surface

| Condition | Exit | Observation emitted (category, fingerprint) |
|---|---|---|
| `/bin/google-chrome` missing | 3 | `external_tool_fail`, `chrome_absent` |
| node binary missing | 2 | `external_tool_fail`, `node_absent` |
| Subprocess non-zero exit | 2 | `external_tool_fail`, `exit-<N>` |
| Subprocess exceeds 120s | 2 | `external_tool_slow`, `timeout-120s` |
| Malformed stdout JSON | 2 | `external_tool_fail`, `malformed_output` |

All observations are fail-open: `claude_observe` import errors, runtime errors inside the observation writer, or env-adoption gaps never block the caller. The Python exception still propagates so bob/visual-architect sees the authoritative failure.

## Determinism / caveats

- The extractor output is **deterministic given identical inputs** (same mockup bytes, same Chrome version, same declared tokens). Networked mockups are out of scope — `waitUntil: "networkidle0"` is for same-origin static assets only.
- The draft is **unsigned**. Only visual-architect signs after user review.
- Token resolution uses **first-match-wins** on the flattened token index; declared aliases that collide are a user error surfaced at freeze time, not extraction time.

## References

- Design doc: `/path/to/project/docs/plans/2026-04-23-ecosystem-keystone-design.md` (§2.3, §2.4, §2.10)
- Contract map: `progress/contract-map.yaml` `skeleton-extractor` component (TS-SE-01..04)
- Precedent: `/path/to/projects/test_flow/test-driver.mjs` (puppeteer-core invocation pattern)
- Subprocess: `~/.claude/skills/_meta/skeleton_extractor.mjs`
- Tests: `~/.claude/skills/skeleton-extractor/tests/`
