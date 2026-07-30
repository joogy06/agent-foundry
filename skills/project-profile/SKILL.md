---
name: project-profile
description: Use at the start of work in a project to establish or load what the project IS — its purpose, domain, tech stack, constraints, conventions and the decisions already taken with their reasons — and to determine what specialised capability it needs, whether that is an existing skill, a project-local skill that knows its API endpoints and file layout, a custom agent, or a script. Turns a universal harness into one narrowed to this project, and keeps that narrowing current as the project changes.
disambiguation: WHAT THE PROJECT IS and what capability it needs — purpose, stack, decisions with rationale, and the provisioning call. The architecture map and session history are project-documentation (PROJECT.md, history.md); a generated read-only comprehension front-door is code-comprehension; ledger projections are project-state; per-project model routing is smart-config.
---

# Project profile

The harness is universal. **This is how it becomes specific to one project** — and how it stops
re-deriving the same context every session.

## 1. What it is, and what it is not

| | |
|---|---|
| **Is** | What the project is *for*, its stack, its constraints, its conventions, the decisions taken **and why** |
| **Is** | The provisioning call: what specialised capability this project needs |
| **Is not** | Session history — that is `history.md` |
| **Is not** | The architecture map — that is `PROJECT.md` |
| **Is not** | A generated code summary — that is `code-comprehension` |
| **Is not** | The task list — that is `tasks.md` |

The distinction that matters: `PROJECT.md` says *what the system is built from*. The profile says
**what it is for, what was decided, and what this project needs that others do not.**

**Check before creating.** If a profile exists, load it. If `PROJECT.md`, `history.md` or a
`code-comprehension` front-door exist, read them first — the profile is built *from* analysis, not
instead of it.

## 2. What a profile holds

```yaml
purpose:        one paragraph — what this exists to do, and for whom
domain:         the subject matter, and the vocabulary that goes with it
stage:          exploration | build | operate | maintain | wind-down
stack:          languages, frameworks, datastores, infra, and the versions that matter
constraints:    air-gapped · regulated · single-operator · legacy interop · budget · latency
conventions:    how this project does things, where it differs from the default
decisions:      - what was decided, WHY, when, and what would reverse it
glossary:       terms this project uses in a non-obvious way
key_surfaces:   the endpoints, files and entry points that come up repeatedly
capability:     what specialised skills / agents / scripts this project needs (§4)
```

**`decisions` is the field that repays the effort.** A decision without its reason gets re-litigated
every few months, and re-litigated badly, because the constraint that drove it has been forgotten.
Record what would *reverse* it too — that is what makes it re-examinable rather than permanent.

**`constraints` is what makes the harness behave differently.** Air-gapped means reference files over
live lookups (`skill-intake` §4). Regulated means evidence and retention obligations. Single-operator
means no delegation assumptions.

## 3. Building one

**From analysis** when the project exists:

1. Read `PROJECT.md`, `history.md`, `tasks.md`, the README, and any design docs.
2. Look at the tree: languages, manifests, test layout, CI, deploy target.
3. **Infer, then confirm.** Present what you inferred and mark each item `confirmed` or `inferred`.
   An inferred stack is usually right; an inferred *purpose* is usually shallow.
4. Ask only what analysis cannot answer — purpose, audience, constraints, and the reasons behind
   decisions the code shows but cannot explain.

**From a goal** when the project is new: the purpose and constraints come from the user, and the
stack is a decision to record rather than a fact to observe.

**Mark provenance per field.** A profile of assumptions produces confident, wrong specialisation —
the same rule `business-edge` applies to an assumed margin and the accounting tracker applies to an
assumed accounting reference date.

## 4. The provisioning call — what does THIS project need?

This is the part that makes the harness adaptive rather than merely informed. For each recurring
need, decide in this order:

| Order | Option | When |
|---|---|---|
| 1 | **An existing skill** | Almost always. Check first; `_meta/skill_resolve.py` verifies it exists and is reachable |
| 2 | **An existing skill + a project reference** | The skill is right, the *specifics* are local — endpoints, file layout, house conventions |
| 3 | **A project-local skill** | The knowledge is real, substantial and genuinely only applies here |
| 4 | **A script** | The work is deterministic and repeated — no judgement needed |
| 5 | **A custom agent** | Only for genuinely autonomous multi-step work with its own boundaries |

**Option 2 is the one that is usually right and usually skipped.** A project needing "the skill for
our billing API" almost never needs a new skill — it needs `python-flask-developer` or
`financial-document-ingestion` **plus a reference file naming this project's endpoints, auth, quirks
and file locations**. That keeps the generalisable trait in the library and the specifics local,
which is the governing principle in PROJECT.md.

**Promote local → library only when a second project needs it.** One project's need is a reference;
two projects' need is a skill. Promoting early puts an example-bound skill in a universal library —
exactly what the traits principle forbids.

**A project-local skill still needs `disambiguation:`** against the library skill it sits beside, or
selection degrades in this project specifically.

## 5. Loading it

At session start, after the standing context checks: **load the profile before doing work.**

It should answer, without further reading: what is this · what is it built on · what has already
been decided and why · what specialised capability is available here · what is deliberately out of
scope.

**If the profile disagrees with the code, the code is the fact** — and the disagreement is a finding.
A profile that has drifted is worse than none, because it is trusted.

## 6. Keeping it current

Profiles rot. Re-check when:

- The stack changes — a framework major, a datastore swap, a new deploy target
- A recorded decision is reversed — **update it, do not delete it**; the reversal and its reason are
  more valuable than the original
- The stage changes — build to operate changes what matters entirely
- Constraints change — a project that becomes regulated changes every downstream default
- A provisioned capability stops being used, or a need recurs that has no home

**Record a `reviewed` date** and treat a stale profile the way this library treats a stale rates
reference: suspect until re-verified, and say so rather than using it silently.

## 7. Anti-patterns

- **Re-deriving the project every session** instead of writing it down once.
- **Recording decisions without reasons** — guarantees they are re-litigated.
- **A profile of inferences** presented as fact.
- **Creating a project-local skill** where an existing skill plus a reference file would do.
- **Promoting a local skill to the library** on one project's evidence.
- **Duplicating `PROJECT.md`** — the profile says what it is *for*, not what it is built from.
- **Letting it drift** and continuing to trust it.
- **Provisioning a custom agent** for work a script would do deterministically.
