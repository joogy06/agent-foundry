---
name: handoff
description: Use when the current session has spotted an out-of-scope task, opportunity, or prototype that needs its own focused context — compresses the current conversation into a markdown handoff document (saved to /tmp/) that a fresh agent session can pick up. Locally-customised fork of Matt Pocock's `handoff` skill — adds ecosystem awareness (PROJECT.md / history.md / tasks.md / .bob-checkpoint.md / .forge/ / .ledger/ pointers), complexity-aware routing (TRIVIAL/SIMPLE/MEDIUM/COMPLEX classification), suggests local skills (forge / pa / cpmail / domain skills) in the handoff doc, and integrates with secrets-scan for redaction. Trigger phrases - "handoff this", "spin off into a fresh session", "create a handoff doc", "this needs its own session", "out of scope but worth doing", "/handoff".
---

# Handoff — Move Context Between Agent Sessions

## Overview

Mid-session, you notice something out of scope — a refactor opportunity, a prototype that needs a fresh 100k-token context window, a security issue, a parallel investigation. You don't want to dilute your current session by switching, and you don't want to lose the relevant context.

`/handoff` compresses the relevant slice of the current conversation into a markdown document saved to `/tmp/`. A fresh agent session (any tool — Claude Code, Codex CLI, Copilot CLI, Gemini CLI) can then pick it up and continue the work.

**This is a locally-forked version of Matt Pocock's [mattpocock/skills/handoff](https://github.com/mattpocock/skills/tree/main/skills/productivity/handoff).** The upstream is 6 directives, prompt-only, deliberately minimal. This fork adds ecosystem-aware behaviour for our forge/bob/alf/pa/evo/wiki workflow.

<HARD-RULE>
NEVER duplicate content that already lives in another artifact (PROJECT.md, history.md, tasks.md, .bob-checkpoint.md, .forge/, design docs, ledger entries, commits, diffs). Reference them by absolute path or URL. The handoff doc is a POINTER PACK, not a full restatement. Duplication bloats handoff docs and creates stale-state hazards; pointers stay fresh by following the link to the live artifact.
</HARD-RULE>

<HARD-RULE>
ALWAYS save handoff docs to the OS temp directory (`/tmp/<filename>` on Linux/macOS, `%TEMP%\<filename>` on Windows) — never to the workspace. Handoff docs are DISPOSABLE working documents, not committable artifacts. If the work merits durable tracking, file an entry in `tasks.md` instead (or both — handoff for context bundle, tasks.md for the durable item).
</HARD-RULE>

<HARD-RULE>
ALWAYS redact secrets/PII before writing the handoff doc. Run the handoff body through a regex catalog (mirroring `scripts/secrets-scan.sh` patterns: PEM/JWT/AWS/GitHub PAT/OpenAI sk-/Slack/Authorization Bearer/`password=` assignments) and replace any match with `[REDACTED-<type>]`. If the secret-scanning skill (gitleaks/trufflehog) is installed, pipe the handoff body through it before writing. Handoff docs in `/tmp/` are not encrypted; treat them as semi-public.
</HARD-RULE>

<HARD-RULE>
The handoff doc MUST suggest the appropriate next-session skill in its "Suggested skills" section based on the task's complexity classification. TRIVIAL → handle directly (no skill suggestion); SIMPLE → domain skill name; MEDIUM/COMPLEX → `forge`; tracked work → `pa`; cross-project ping → `cpmail`. Bare "suggested skills: claude does its best" defeats the routing purpose.
</HARD-RULE>

Companion skills:
- `forge` — invoke from the handoff if the work is MEDIUM/COMPLEX (design needed)
- `pa` — file the handoff as a tracked task if it needs persistent visibility
- `cross-project-mail` (`cpmail`) — alternative when the handoff target is another *project* on the same host (cross-project rather than cross-session)
- `secret-scanning` — defense-in-depth redaction layer for the handoff body
- `exit-with-docs` — sister skill that updates tasks.md/history.md at end-of-session (handoff is for mid-session, exit-with-docs is for end-of-session)

---

## 1. When to use vs alternatives

| Scenario | Tool |
|---|---|
| Mid-session, out-of-scope spotted; needs fresh session | **`/handoff`** (this skill) |
| Mid-bob-execution, out-of-scope spotted; current WP must continue | Bob's HARD-RULE — emit `/handoff` to `/tmp/`, log in `tasks.md`, keep going on WP |
| End-of-session wrap-up; multiple tasks completed | `exit-with-docs` |
| Cross-PROJECT context transfer (different sibling repo) | `cross-project-mail` (`cpmail send`) |
| Long-running task needs PERSISTENT tracking | `pa` task in `pa-server` |
| Prototype that needs its own 100k+ context | `/handoff` + dispatch to a fresh agent |
| Pure ad-hoc question; no continuity needed | Just ask; no handoff needed |
| Mid-design exploration in forge; spotted a sub-design | forge's decomposition pattern (sub-projects with depth limit) |

---

## 2. Output format

The handoff doc is markdown saved to `/tmp/handoff-<topic>-<YYYY-MM-DD>-<short-uuid>.md` (or `%TEMP%\handoff-...` on Windows). Structure:

```markdown
# Handoff: <one-line topic>

**Source session:** <best-effort identifier — claude-code-session-id if available, else "current session 2026-MM-DD">
**Created:** 2026-MM-DD HH:MM:SS<tz>
**Complexity classification:** TRIVIAL | SIMPLE | MEDIUM | COMPLEX
**Suggested skills:** <comma-separated list of skills the next session should invoke>
**Target tool:** any (Claude Code | Codex | Gemini | Copilot) | <specific if appropriate>

---

## 1. Purpose

<one paragraph: what the next session needs to accomplish, expressed in terms of OUTCOME not steps>

## 2. Relevant context from this session

<pointer pack — NO duplication. Reference each artifact by absolute path with one-line "what's in it">

- **PROJECT.md** — `/path/to/PROJECT.md` (architecture map; read first if unfamiliar with project)
- **history.md** — `/path/to/history.md` (recent session entries 2026-MM-DD..)
- **tasks.md** — `/path/to/tasks.md` (task #N relevant; section "Active Tasks")
- **Design docs** — `/path/to/docs/plans/2026-MM-DD-<topic>-design.md` (if forge cycle ran)
- **Ledger entries** — `/path/to/.ledger/...` (if contract-driven work)
- **Bob checkpoint** — `/path/to/.bob-checkpoint.md` (if mid-execution)
- **Recent commits** — `git log --oneline -5` output (or specific SHA references)

## 3. What this session has already established

<2-5 bullets: facts that the next session shouldn't re-derive>

- Fact 1 with evidence pointer
- Fact 2 with evidence pointer
- ...

## 4. Open question(s) for the next session

<the actual work — what does the next session need to figure out / build / decide?>

## 5. Suggested approach

<2-4 sentences. Includes which skill to invoke first per the complexity classification.>

For MEDIUM/COMPLEX: "Invoke `forge` first."
For SIMPLE: "Invoke `<domain-skill-name>` directly."
For TRIVIAL: "Handle directly; no skill needed."

## 6. Constraints / non-goals

<bulleted list — what's OUT of scope for the next session>

## 7. How to verify success

<1-3 bullets — what the next session's done-condition looks like, with evidence>

---

_Generated by the `handoff` skill v1.0 (local fork). This doc is disposable; if the work merits permanent tracking, file `tasks.md` entry #N or commit the design doc._
```

---

## 3. Complexity classification (drives the Suggested skills section)

Inherit from CLAUDE.md routing rules:

| Class | Signals | Suggested first skill in handoff |
|---|---|---|
| **TRIVIAL** | Config change, typo, single known edit | none — handle directly |
| **SIMPLE** | Single-file change, clear output, one domain | `<domain-skill-name>` directly (e.g. `python-flask-developer`, `wordpress-developer`) |
| **MEDIUM** | 2-3 files, some decisions, clear approach | `forge` (Simple complexity mode) |
| **COMPLEX** | Architecture decision, multiple approaches, cross-layer | `forge` (full cycle) |
| **Cross-project ping** | Action belongs in another sibling project | `cpmail send <project> ...` |
| **Tracked-work** | Needs persistent visibility | `pa` task entry + handoff doc cross-link |

Default if uncertain: MEDIUM (matches CLAUDE.md default).

---

## 4. Ecosystem-aware pointer pack

When generating the "Relevant context" section, check for each of these and include if present:

```bash
# Project context files
[ -f "$PWD/PROJECT.md" ]            && include
[ -f "$PWD/history.md" ]            && include   # head + tail if >400 lines
[ -f "$PWD/tasks.md" ]              && include   # specific task IDs if relevant
[ -f "$PWD/session_control.md" ]    && include
[ -f "$PWD/index.md" ]              && include

# Forge/bob state
[ -d "$PWD/.forge/" ]               && include   # forge-session-id, signed contract map sig
[ -f "$PWD/.bob-checkpoint.md" ]    && include   # mid-execution state
[ -d "$PWD/.ledger/" ]              && include   # contract-driven artifacts
[ -d "$PWD/.design-ledger/" ]       && include   # design skeletons
[ -d "$PWD/.process-observations/" ] && include   # observability friction signals

# Design docs
ls "$PWD/docs/plans/" | tail -3     && include   # most recent design docs

# Wiki bindings (if .wiki-link exists)
[ -f "$PWD/.wiki-link" ]            && include   # bound wiki(s) for prior knowledge

# Recent git history
git -C "$PWD" log --oneline -5      && include   # last 5 commits
```

NEVER copy file contents into the handoff doc. ALWAYS reference by absolute path + one-line "what's in it".

---

## 5. Secret-scanning integration (HARD-RULE 3 implementation)

Before writing the handoff doc:

1. **Tier 1 (always):** apply the regex catalog from `scripts/secrets-scan.sh` to the handoff body. Replace matches with `[REDACTED-<type>]` (e.g. `[REDACTED-AWS-KEY]`, `[REDACTED-JWT]`).

2. **Tier 2 (defense-in-depth, if installed):** if `gitleaks` is on PATH (check `~/.claude/state/inventory.json`), write to a temp staging file first, run `gitleaks dir <staging-dir> --no-banner --redact --exit-code 1`, abort write on findings. Same for `trufflehog --only-verified`.

3. **Tier 3 (user trust check):** explicit reminder in the doc body — `<!-- This handoff doc lives in /tmp/ and is not encrypted. Treat as semi-public. -->`

A handoff that fails Tier 2 scan must NOT be written until the user explicitly waives. Bare "I checked and there's no secret" assertions don't qualify — the scan log must be in the chat.

---

## 6. Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Duplicating PROJECT.md / history.md content into the handoff doc | Stale-state hazard; bloats `/tmp/` | Reference by absolute path + 1-line description |
| Saving handoff to the workspace | Not disposable; pollutes the repo; risk of accidental commit | Save to `/tmp/` or `%TEMP%` |
| Bare "suggested skills: forge maybe" | Defeats the routing purpose | Pick the specific skill based on complexity classification |
| Bare assertion "I redacted secrets myself" | Trust-without-verification | Run the regex catalog AND gitleaks if installed; show scan output |
| Calling /handoff for trivial out-of-scope items | Manufactures ceremony; better to handle directly | TRIVIAL ⇒ handle directly; no handoff |
| Forgetting to include the "how to verify success" section | Next session can't tell when it's done | Always include §7 |
| Including the full chat transcript verbatim | The next session doesn't need the chat; it needs the synthesis | Synthesise; reference artifacts; the handoff is a POINTER PACK |
| Including secrets you "trust the next session not to misuse" | The handoff doc may be read by a different model / different operator / leaked to /tmp on a shared host | Redact unconditionally |
| Skipping the complexity classification | Routing fails downstream | One word: TRIVIAL / SIMPLE / MEDIUM / COMPLEX |

---

## 7. Selection Cheatsheet

- **Spotted a security issue mid-bob-WP** → emit `/handoff` to `/tmp/`, file tasks.md entry #N, continue WP (bob HARD-RULE)
- **Need to prototype something with fresh 100k context** → `/handoff` + dispatch Claude Code on the handoff path
- **Mid-design, found a sub-design** → `/handoff` for the sub-design; current forge keeps the parent design
- **Want to ask Codex / Gemini about an out-of-scope question** → `/handoff` + open the file in the other tool
- **End of session, multiple tasks done** → `exit-with-docs`, not `/handoff`
- **Cross-project ping** → `cpmail`, not `/handoff`
- **Tracked work item** → `pa` task entry + optional handoff doc for context

---

## 8. Update triggers (alf scans these)

- Pocock's upstream `handoff` skill releases an update (mattpocock/skills)
- A new ecosystem state file appears (e.g. `.something-ledger/`) and isn't yet in the pointer-pack inspection list
- Secret-scanning regex catalog updates (in-house, gitleaks, or trufflehog patterns)
- Annual review on 2027-05-25

---

## 9. See Also

| Need | Skill |
|---|---|
| End-of-session wrap-up | `exit-with-docs` |
| Cross-project messaging | `cross-project-mail` (`cpmail`) |
| Tracked task | `pa` |
| Design exploration (for MEDIUM/COMPLEX handoffs) | `forge` |
| Secret redaction defense-in-depth | `secret-scanning` |
| Project state pointers (PROJECT.md, etc.) | `project-documentation` |
| Upstream skill (Pocock's minimal version) | [mattpocock/skills/handoff](https://github.com/mattpocock/skills/tree/main/skills/productivity/handoff) |
