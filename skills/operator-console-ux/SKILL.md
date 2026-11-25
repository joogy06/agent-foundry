---
name: operator-console-ux
description: "Operator console and control-plane UX: needs-you-now queues, approval cards, kanban task boards, destructive-action guards, freshness, keyboard-first layouts. Use when designing or building an admin or ops dashboard."
license: MIT
metadata:
  version: "1.0.0"
  family: "frontend"
---

# Operator Console UX

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: wcag-22-operation-criteria
    source_url: https://www.w3.org/TR/WCAG22/
    verified_on: 2026-10-26
    review_by: 2027-04-26
    claim: "WCAG 2.2 is the current Recommendation. SC 2.5.7 Dragging Movements (AA) needs a single-pointer alternative to any drag; SC 2.4.11 Focus Not Obscured (Minimum) (AA); SC 2.5.8 Target Size (Minimum) (AA) 24x24 CSS px; SC 2.1.4 Character Key Shortcuts (A); SC 2.2.1 Timing Adjustable (A); SC 4.1.3 Status Messages (AA)."
  - kind: external_fact
    subject: dnd-kit-packages
    source_url: https://www.npmjs.com/package/@dnd-kit/react
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "@dnd-kit/react 0.5.1 (2026-10-15, pre-1.0, Accessibility plugin with announcements and screenReaderInstructions); @dnd-kit/core 6.3.1 and @dnd-kit/sortable 10.0.0 last published 2024-12; react-beautiful-dnd deprecated on npm; @atlaskit/pragmatic-drag-and-drop 4.0.0."
-->

## Overview

An operator console is the screen where a person supervises a system that mostly runs by itself:
it shows what needs a human, lets them approve, pause, retry or disable things, and must never let
them act on a picture of the system that is old or wrong. This skill owns the **generic
control-plane interaction contracts**, framework-neutral, with React examples in the references.

**Form follows function.** Every element answers one of three questions: *what needs me now*, *is
what I am looking at current*, *what will this action do and can I take it back*. Decoration that
answers none of them is cut.

**Seams (route, do not duplicate):**

| Concern | Owner |
|---|---|
| Who the audience is, journey, information architecture, the design brief | `audience-experience-design` (upstream; this skill implements its brief for consoles) |
| Reviewing the built console against measured evidence | `ux-reviewer` |
| Order tickets, blotters, market-data freshness, emergency flatten | `trading-dashboard-ux` (adds trading contracts on top of this skill and wins on conflict for trading surfaces) |
| Charts, KPI tiles, sparklines | `dataviz` |
| SPA mechanics, TanStack Query, live data over SSE, forms | `modern-frontend` (see its SSE reference for the live-data plumbing) |
| Passkey login and step-up re-authentication behind an approve button | `spa-auth-webauthn` |
| Which signals and alert classes exist at all | `observability` |
| React render behaviour, `useOptimistic` | `react-developer` |

## When to Use

- Building an admin, ops, back-office or automation-supervision dashboard (a "control plane").
- Designing a work queue, inbox, approval flow, task board, or a page of enable / disable / archive
  controls.
- Symptoms: operators approve the wrong item; a stale table is read as live; a drag-only board fails
  keyboard users; a confirm dialog is clicked through by habit; a blank screen on empty or error;
  a shortcut fires while typing in a field.
- **Not for:** marketing sites, consumer apps, trading order entry (use `trading-dashboard-ux`),
  chart construction (use `dataviz`).

## Ask before generating (ambiguity gate)

When asked to produce a console layout, component spec or code and any of these is missing and
would change the result, ask ONE compact question covering them, then build:

1. **The action inventory and its blast radius** - which actions exist, and for each: reversible,
   recoverable by an admin, or irreversible; and whether it needs step-up re-authentication.
2. **Who acts** - one owner, a small team (claims, assignment, concurrent edits), or many roles.
3. **How live the data is** - push (SSE or WebSocket), polling interval, or on-demand; and how old
   data may be before it is unsafe to act on.
4. **Input mode and device** - desktop keyboard-first, touch, or both.

If the user says "just draft it", state the assumptions you made in one line at the top.

## Binding rules

<HARD-RULE>
No optimistic success for privileged or consequential actions. Approve, grant, revoke, disable,
delete, deploy and anything with external effect render `requested → pending → {done | failed |
unknown}` from the server's answer. Optimistic UI is allowed only for low-stakes, reversible,
local edits (card order, a label, a draft) and must roll back visibly on failure.
</HARD-RULE>

<HARD-RULE>
A confirmation binds to the exact object and version shown. The approve or destructive request
carries the item id and its version (or ETag); if the item changed since it was rendered, the
server rejects it and the UI re-renders the new version for a fresh decision. Never confirm
"the selected item" by position or by a list index.
</HARD-RULE>

<HARD-RULE>
Visibly stale beats silently wrong. Every live view shows its data age, and when data passes its
staleness budget or the live connection drops, the view degrades visibly and actions that depend on
current state are disabled or re-confirmed. Never freeze a last-good value as if it were live.
</HARD-RULE>

<HARD-RULE>
Every drag interaction has a keyboard path and a single-pointer (click or menu) alternative, and
every async region has explicit loading, empty, error and stale states. WCAG 2.2 SC 2.5.7 makes
the single-pointer alternative a conformance requirement, not a nicety.
</HARD-RULE>

## 1. Attention model: the needs-you-now queue

The home screen is a **queue of things waiting on a human**, not a wall of metrics.

- **One ranked queue**, ordered by consequence of delay, then age. Each row states *what*, *why it
  needs you*, *deadline or expiry*, and *the one primary action*.
- **Severity is a small closed set** (e.g. `blocking`, `needs decision`, `fyi`) with text labels
  and icons, never colour alone. Informational items never sit above a blocking one, and FYI items
  live in a separate, collapsible lane so they cannot drown the queue (alarm-fatigue rule: every
  item in the queue must call for an action; if nobody acts on a class, demote or delete it).
- **Expiry is shown and enforced.** An approval request that times out leaves the queue as
  `expired`, it is not silently auto-approved or silently dropped.
- **Counts are honest**: show "12 waiting, 3 blocking" from the server, not the count of rows the
  client happens to have loaded.
- **Claiming**: with more than one operator, a row shows who has claimed it; claiming is a server
  operation, and a second operator sees the claim before they open the item.

## 2. Approval cards

An approval card is a **decision document**. Present the server's canonical description of the
action, never a client-rebuilt summary:

| Part | Content |
|---|---|
| Header | Action verb + target ("Grant deploy access to runner-7"), requester, requested-at, expires-at |
| Scope | Exactly what changes: resources, permissions, duration, environment, reversibility |
| Evidence | Why it was requested, links to logs or diffs, risk flags from the policy owner (shown, never computed by the UI) |
| Decision | Approve and Reject as separate, labelled buttons; Reject asks for a reason; neither is the default focus |
| State | `pending → approving → approved | rejected | failed | expired | unknown` |

Explicit confirm: the Approve button opens a confirmation step that restates the scope in one
line, then requires a deliberate second action. For high-blast-radius approvals (granting
privileges, irreversible changes) the confirmation is a **step-up re-authentication** with the
action bound into the challenge (see `spa-auth-webauthn`), not an "Are you sure?" dialog. Detail
and a component sketch: `references/approvals-and-guards.md`.

## 3. Destructive-action ladder

Choose the guard by **reversibility**, not by how scary the verb sounds. Confirm dialogs on
everything train operators to click through them; undo is cheaper and safer when the action can
genuinely be reversed.

| Action class | Example | Guard |
|---|---|---|
| Reversible, low impact | archive a card, snooze, mute | Do it immediately; undo toast with an action button, at least 10 s, not dismissed by focus loss |
| Reversible by design (soft state) | disable a job, pause a runner | Prefer **disable over delete**; do it with one confirm that names the target; show a persistent "disabled" state with a one-click re-enable |
| Recoverable only by admin or restore | delete with retention, rotate a secret | Confirm dialog that names the target and the consequence; destructive button styled and labelled with the verb ("Delete runner-7"), not "OK" |
| Irreversible or high blast radius | purge data, revoke all sessions, grant owner rights | Typed confirmation of the target name **or** step-up re-authentication, plus a server-side idempotency key |

Undo windows are implemented server-side as a delayed commit or a reversible state, never as a
client timer that fires the real request when the toast closes (a closed tab then means the
action was or was not done, unknowably). Full rules and the toast accessibility contract:
`references/approvals-and-guards.md`.

## 4. Freshness and staleness

- **Every live surface shows an as-of time** using `<time datetime="…">` with a relative label
  ("updated 12 s ago") that ticks, and the absolute time on hover or focus.
- **Each view declares a staleness budget** (e.g. 30 s for a queue fed by push, 5 min for a
  report). Past the budget: a visible stale badge, muted values, and actions that need current
  state disabled with the reason, or re-confirmed against a fresh fetch.
- **Connection state is separate from data age.** "Live" means the push channel is connected
  *and* the last event is within budget. A connected channel with no events for longer than the
  heartbeat interval is stale, not live.
- **Per-object freshness** where it matters: a row that was updated by another operator since you
  opened it shows "changed since you opened this" before you act.

## 5. States every region must design

| State | Rule |
|---|---|
| Loading (first) | Skeleton that matches the final layout for waits over about 1 s; spinner only for short, unknown-shape waits; never a blank region |
| Loading (refresh) | Keep showing the current data with a subtle refreshing indicator; do not swap back to a skeleton |
| Empty | Say why it is empty (nothing waiting / filters hide everything / no permission) and offer the next action ("Clear filters") |
| Error | What failed, whether data shown is stale, a retry, and a correlation id the operator can paste into a ticket |
| Stale | As §4 |
| Partial | Some sources failed: show what loaded and name what did not; never present a partial total as complete |
| Forbidden | Distinguish "you lack permission" from "it does not exist" where policy allows |

## 6. Keyboard-first desktop layout and command palette

- **Layout:** a stable three-zone shell (navigation, list, detail) where the list keeps its scroll
  and selection while the detail pane changes; `j`/`k` or arrow keys move selection, `Enter`
  opens, `Esc` closes the innermost layer.
- **Command palette** on `Ctrl+K` / `Cmd+K`: searches navigation targets and actions; destructive
  actions appear in it but still go through the §3 ladder.
- **Single-key shortcuts** are scoped to the focused region, never fire inside text inputs, and can
  be turned off or remapped (WCAG 2.2 SC 2.1.4). Publish them in a `?` overlay.
- **Focus**: the focused element is never hidden behind sticky headers or toasts (SC 2.4.11);
  after an action removes a row, focus moves to the next row, not to `<body>`.

Patterns, the combobox contract for mention / `#tag` type-ahead, and library notes:
`references/keyboard-and-typeahead.md`.

## 7. Task boards (kanban)

A board is a projection of server state: columns are statuses, card order is a server-stored rank.

- Moving a card is a **request** (`PATCH status, rank, expected_version`); render the move
  optimistically only when the move is low-stakes and reversible, and roll back with an
  announcement on conflict. A move that triggers a consequential action (a status that deploys or
  notifies) is not optimistic and goes through the §3 ladder.
- **Three ways to move a card**: pointer drag, keyboard drag (pick up with `Space`, move with
  arrows, drop with `Space`, cancel with `Esc`) with screen-reader announcements, and a "Move
  to…" menu (the WCAG 2.5.7 single-pointer alternative).
- **Use fractional or lexicographic ranks** so one move writes one row, not a renumbering of the
  column.
- **WIP limits** and blocked flags are shown on the column header from server data.

Library choice (dated), sensors, announcements and a worked sortable board:
`references/task-boards.md`.

## Reference files

| File | Read when |
|---|---|
| `references/approvals-and-guards.md` | Building approval cards, confirm dialogs, typed confirmation, undo toasts and their accessibility |
| `references/task-boards.md` | Building a kanban board with drag and drop, keyboard and screen-reader dragging, rank storage |
| `references/keyboard-and-typeahead.md` | Shortcut maps, command palette, mention / `#tag` type-ahead (ARIA combobox), focus management |

## Anti-Patterns

| Don't | Why | Do instead |
|---|---|---|
| Optimistic "Approved" before the server confirms | The operator moves on believing a grant exists that failed or never ran | Render the server's state machine, `unknown` included |
| A confirm dialog on every action | Habituation: operators click through, so the dialog stops protecting the dangerous one | Undo for reversible actions; reserve confirm and step-up for the irreversible |
| "OK / Cancel" buttons on destructive dialogs | The verb and target are invisible at the moment of decision | Button says the verb and target: "Delete runner-7" |
| Client-timer undo that fires the request on toast close | Closing the tab leaves the action's fate unknown | Server-side delayed commit or reversible state |
| Approving by list position or "selected row" | A re-sort or push update changes which item is approved | Bind the decision to id + version; server rejects on mismatch |
| A green "connected" dot as the only freshness signal | Connected but silent reads as live | Show data age; stale after the heartbeat budget |
| Drag-only reordering | Fails keyboard, switch and screen-reader users, and WCAG 2.5.7 | Keyboard drag plus a "Move to…" menu |
| Metrics wall as the home screen | Nothing says what needs a human | A ranked needs-you-now queue; metrics go to a secondary view |
| Single-key shortcuts active inside inputs | Typing "d" in a comment deletes a row | Scope shortcuts; ignore keystrokes from editable targets |
| Blank region while loading or when empty | Operator cannot tell empty from broken | Skeleton, explicit empty state with reason, error with retry |
