---
name: user-preferences
description: "Use to RECORD or APPLY durable, cross-project user preferences — how the user likes their code, presentations, emails, and language tone — so the agent moulds to them over time ('oh, he prefers pytest / em-dashes / short emails'). Capture is EXPLICIT only: record a preference when the user states one ('remember I prefer X', 'always do Y', 'I don't like Z'); NEVER auto-infer. Before domain work (writing/refactoring code, building a deck, drafting an email, choosing tone/voice) LOAD the matching profile and honor it. Also documents the two-tier file-memory model (global + per-project). Trigger on: 'remember I prefer', 'always do X', 'I like/don't like', 'from now on', 'set my preference', 'what are my preferences', 'apply my coding/email/presentation/tone style'."
---

# user-preferences — durable, learnable user preferences (explicit capture)

The system that lets this agentic setup **mould to the end user** — it records what the
user explicitly prefers and re-applies it across sessions and projects, so outputs drift
toward "what the user would have done." Pure-stdlib, file-based, no inference.

## Two-tier memory model (the foundation)

| Tier | Path | Holds | Loaded |
|---|---|---|---|
| **Global** | `~/.claude/memory/` (`MEMORY.md` + files) | who the user is, cross-project feedback, **preference profiles** | **every** session (in-project or outside) |
| **Project** | `~/.claude/projects/<slug>/memory/` | project-specific facts/decisions | only when working **inside** that project |

Precedence: project memory **layers on top of** global; on a direct conflict the project
fact wins for that project, and the conflict is surfaced (never silently merged). User
preferences are GLOBAL by design (they describe the person, not the project).

## Preference profiles

One markdown profile per domain under `~/.claude/memory/preferences/`:
`coding.md`, `presentations.md`, `email.md`, `tone.md` (custom domains allowed). Each has
a flat `key: value` frontmatter (the structured prefs loaded as constraints) + a dated
free-form body (nuance + history). Managed ONLY through `scripts/prefs.py` (stdlib):

```bash
python3 scripts/prefs.py list                              # domains + key counts
python3 scripts/prefs.py show  <domain>                    # full profile
python3 scripts/prefs.py load  <domain>                    # prefs as constraints (before domain work)
python3 scripts/prefs.py set   <domain> <key> <value...>   # record/update a structured pref
python3 scripts/prefs.py note  <domain> <free text...>     # record a nuance that has no clean key
```

## HARD-RULE — capture is EXPLICIT only

Record a preference ONLY when the user states one — "remember I prefer X", "always do Y",
"I don't like Z", "from now on …". **Never infer a durable preference from a single
choice or correction silently.** (If you notice a likely pattern you may *ask* "want me to
remember that?", but you do not write it unless they say yes.) This keeps the store
trustworthy — every entry is something the user actually asked for.

When recording: pick the domain (coding/presentations/email/tone/custom), map it to a
structured `set <domain> <key> <value>` when it fits a clean key, else `note`. Confirm
back ("recorded: coding.test_framework = pytest").

## APPLY — load before domain work

Before producing domain output, load the matching profile and treat it as constraints:

| Doing… | Load |
|---|---|
| writing / refactoring / reviewing code | `prefs.py load coding` |
| building slides / a deck | `prefs.py load presentations` |
| drafting an email | `prefs.py load email` |
| any user-facing prose (always) | `prefs.py load tone` |

Honor the loaded prefs unless the user's current request overrides them (the live request
always wins). This is also wired as a directive in CLAUDE.md so it applies even when this
SKILL.md is not in front of you.

## Session-start awareness

The `_meta/memory_primer.py` SessionStart hook prints, every session, which memory tiers
loaded (global always; project when in-project) and the live `N skills · M agents · K
gates` so the agent starts **fully aware** of both its capabilities and the user's
recorded preferences.

## Install / seed

`installer/bootstrap-environment.py` seeds `~/.claude/memory/preferences/` from this
skill's `profiles/` (idempotent — never overwrites a populated profile) and wires the
memory_primer hook, so a fresh machine starts with the schema + the standing behavior.

## Composition

- `presentation-builder` / `content-writer` / `career-application-writer` / email work →
  load the relevant profile first.
- `human-voice-writing` → reads the `tone` profile.
- The global `MEMORY.md` index links to user/feedback/reference memories; preference
  profiles are the structured subset of the `user` memory type.
