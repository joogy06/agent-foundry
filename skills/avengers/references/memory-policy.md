# avengers — member-memory policy (v1)

The rules the memory subsystem enforces in code (`scripts/memory_writeback.py`,
`scripts/seat_prompt.py`, `schemas/memory-record.v1.schema.json`). Design §5/§6/§14.
Honest posture: this is an admissibility + provenance + approval discipline, not a
"secure" claim. See `trust-boundary.md` for the injection posture and residuals.

## Tiers

| Tier | Location | Injected? | Grows |
|---|---|---|---|
| Identity (role card) | `~/.claude/skills/avengers/roster/<seat-id>.yaml` | always | human-edited only |
| Standing memory | `~/.claude/projects/<slug>/avengers/members/<seat-id>/standing.json` | yes (filtered) | gated write-back |
| Episodic history | `~/.claude/projects/<slug>/avengers/members/<seat-id>/engagements/…` | **never (v1)** | per session |

**Home-tier only.** Member memory and all trusted text live under `~/.claude/`,
**never** repo-local. A repo-carried memory file is a pre-poisoned-clone vector
that bypasses the write-back gate (the gate covers writes, not pre-existing
files). The loader derives paths from `projects_root()` and `assert_home_tier_path`
refuses anything resolving outside `~/.claude/projects/<slug>/`.

**Out of scope for v1 (§14):** there is **no global-memory-tier loader branch**.
The project tier is the only memory tier. Global/cross-project memory is
designed-for, not built.

## Admissibility (standing memory)

A record is admissible **only** when both hold:

1. `provenance.source_type` is one of the four Codex-class sources:
   `user_confirmed_constraint`, `verified_project_artifact`,
   `user_selected_decision`, `observed_outcome`.
2. `kind` is **not** an episodic kind — `seat_opinion`, `refuted_position`, or
   `single_session_conclusion`. These anchor/tame contention and belong to
   episodic history, never standing memory.

The record shape is `memory-record.v1` (`id`, `topic_key`, `kind`, `statement`,
`applies_when`, `provenance{run_id, source_type, source_refs, sha256}`,
`approval{status, by, at}`, `sensitivity{pii}`, `status`, `expires_at`,
`supersedes`). Validation is the bundled stdlib mini-validator (no third-party
`jsonschema`), identical to `convene.py`.

## Injection protocol (`seat_prompt.py`)

- **Identity** always. **Standing** records filtered by `applies_when`/topic
  relevance (active only) under a **deterministic per-seat UTF-8 byte budget**
  (~1500-token equivalent ≈ 6000 bytes). Records are sorted deterministically
  (by `id`, then `topic_key`) then greedily packed to the budget; any
  **truncation is SURFACED** with a `[MEMORY BUDGET] N of M omitted` note.
- **Episodics never injected** (v1).
- **BLIND_DIVERGE** = identity + standing only; peer records are refused
  fail-closed at that phase.
- **Memory-hit visibility**: when a seat's turn cites an injected record by `id`,
  the digest prints `↳ <seat> cited <id>` (`format_memory_hit` / `scan_memory_hits`).
  Success criterion #3 (design §12) depends on this line being observable.

## Gated write-back (`memory_writeback.py`)

- The chair drafts **≤3** candidates per session (**≤1** for PII profiles). A
  candidate is `{member, source_turn, record}`.
- **Persist-for-later**: `persist_proposals` writes to the **home tier** at
  `~/.claude/projects/<slug>/avengers/proposals/<session-id>.json`. Unattended
  runs never block and never silently discard.
- **Default-reject, per-item**: persisted proposals carry `decision: rejected`;
  a later review (`avengers memory review`) flips specific items to approved.
- **A record with no traceable source turn is refused** — at draft time
  (`_candidate_eligible`) and re-checked at commit against the transcript turn set.
- **Commit discipline** (`commit_approved`, wiki §5.0/§5.9): per-project
  `fcntl.flock` → sha256 **hash-snapshot** → **backup** (`standing.json.bak`) →
  **re-check** (admissibility + source-turn traceability, TOCTOU) → **atomic
  rename**. Only explicitly-approved (`{id: true}`) records commit.

## PII profiles

`sensitivity.pii: true` profiles (e.g. `writing-cv`): write-back defaults OFF /
throttled to ≤1 candidate; external-egress packets redacted by default; retention
policy per profile (`retain: full | redacted | outcome-only`). Standing records
may carry `sensitivity.pii`.
