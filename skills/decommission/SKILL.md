---
name: decommission
description: Use when retiring, deleting, replacing, or superseding anything a repo or skill library depends on — a skill, agent, tool, CLI, dependency, API, endpoint, config key, or a whole version. Maps the impact zone BEFORE removal, classifies every reference (usage / pointer / prohibition / history / exemption / lookalike), decides per reference, detects capabilities orphaned by the removal, files the relink and backfill work, and verifies no dangling or contradicting references survive. Trigger on - retire X, remove X, deprecate X, delete this skill, migrate off X, X is dead, clean up after the upgrade, decommission, sunset, replace X with Y, evergreen cleanup.
---

# Decommission

Removing something is not deleting it. **Deleting is one step of seven**, and the six around it are
where the damage happens.

> **Boundary.** *Evergreening* keeps a thing current — that is `alf` / the freshness sweep.
> **Decommission removes a thing and repairs everything that leaned on it.** If the answer is "bump
> the version", you are evergreening. If the answer is "this no longer exists here", you are here.

<HARD-RULE>
MAP BEFORE YOU DELETE. Produce the impact zone and classify every reference BEFORE removing
anything. A removal executed ahead of its map is not reversible by knowledge — you no longer know
what pointed at it.
</HARD-RULE>

<HARD-RULE>
NEVER DELETE ON A NAME MATCH. Classify every hit first (§3). Names collide, and the lookalike class
is where real damage happens: retiring a *CLI* does not retire the *API* that shares its name, and a
config directory named after the retired tool may belong to its replacement.
</HARD-RULE>

<HARD-RULE>
PROVE RECOVERABILITY, THEN ARCHIVE, THEN DELETE — in that order, before P4 touches anything.

Answer explicitly: **is this tree version-controlled?** A live skill/config tree often is NOT
(`~/.claude/skills` is a working directory, not a repo), so `rm -rf` there is final. Check every
copy — source repo, published mirror, remote — and state where recovery would come from.

Then archive regardless of the answer:
`cp -a <target> ~/.claude/.agent-foundry-archive/decommission-<name>-<UTC>/`

Record the archive path in the decommission record (§8). "It's in git" is a claim to VERIFY with
`git ls-files`, never to assume — the first real run of this skill deleted a 40-file skill from an
untracked tree, and only found it was recoverable because someone checked by hand.
</HARD-RULE>

<HARD-RULE>
IF THIS REMOVAL CONTRADICTS A RECORDED DECISION, RECORD THE SUPERSESSION — never resolve it silently.

Exemptions and keep-it directives get written down (see below). When a newer instruction reverses
one, the old entry must be marked superseded with BOTH dates and the new authority — not deleted, not
quietly ignored. A reader finding a removal that contradicts a standing directive, with no record of
the reversal, cannot tell whether it was decided or overlooked.
</HARD-RULE>

<HARD-RULE>
EXEMPTIONS ARE RECORDED, NOT REMEMBERED. Any component deliberately excluded from the removal MUST
be written into the decommission record with its reason and who granted it. An exemption that lives
only in a chat message will be silently "cleaned up" by the next person who runs this skill.
</HARD-RULE>

<HARD-RULE>
A REMOVAL THAT ORPHANS A CAPABILITY MUST FILE THE GAP. If anything depended on what you removed and
now has no owner, that is new work — file it explicitly (§6). Deleting the provider and leaving the
consumer pointing at nothing converts a live capability into a silent hole.
</HARD-RULE>

<HARD-RULE>
FINISH THE SWEEP IN ONE PASS. A half-done retirement is worse than none: the repo now contains BOTH
"X is gone" and "X is available", and a reader cannot tell which is current. Verify to grep-zero
(§7) before declaring done.
</HARD-RULE>

---

## 1. The phases

```
P0 DECLARE → P1 MAP → P2 CLASSIFY → P3 DECIDE → P4 EXECUTE → P5 VERIFY → P6 BACKFILL
```

---

## 2. P0/P1 — Declare and map the impact zone

**Declare precisely.** *What* is being removed, *why*, *what replaces it* (or explicitly: nothing),
and the **effective date**. Vagueness here produces the half-states in §7.

**The impact zone is wider than a grep for the name.** Sweep all of:

| Layer | What to look for |
|---|---|
| **Direct references** | The name, its aliases, old names, command invocations, import paths, URLs |
| **Transitive dependants** | Things that used the *capability*, not the name — they may never mention it |
| **Routing / fallbacks** | "if X unavailable, use Y" chains, retry paths, provider lists |
| **Config & environment** | Env vars, settings keys, credentials, paths, symlinks |
| **Data contracts** | **Schemas, manifests, enums, event payloads that carry a FIELD for it.** Removing a field is a BREAKING change — bump the schema version and update every reader |
| **Tests & gates** | Tests asserting it exists; gates that check for it |
| **Backlog** | Open tasks whose **premise** dies with it — these become invalid, not just stale |
| **Docs & history** | Architecture maps, session history, READMEs, changelogs |
| **Installers / publishers** | Anything that *places* the thing on a new machine |

**Scan EVERY tree it lives in, not just the authoritative one** — source repo, live/installed tree,
published mirror, and any symlink farm (e.g. a second CLI's skill directory). `impact_scan.py` accepts
repeatable `--root`. A removal that clears the live tree but leaves the repo mirror and the publish
manifest intact will be silently reinstalled by the next install or publish run.

Run `scripts/impact_scan.py` for the mechanical half; the transitive, data-contract and premise
layers need reading.

---

## 3. P2 — Classify every reference

**This is the step that prevents the damage.** Every hit is exactly one of:

| Class | Meaning | Default action |
|---|---|---|
| **USAGE** | Actually invokes or depends on the thing | **Remove or rewrite** to the replacement |
| **POINTER** | Routes the reader to it | **Repoint** to the replacement, or delete if nothing replaces it |
| **PROHIBITION** | "Do NOT use X" — a guard rail | **Keep.** Deleting it invites reintroduction |
| **HISTORY** | A dated record of what happened | **Keep.** History is not stale — it is *dated* |
| **EXEMPTION** | Deliberately excluded from the removal | **Keep + record in the decommission record** |
| **LOOKALIKE** | Shares the name, is a different thing | **Keep.** Verify before deciding |

> **The lookalike class exists because of a near-miss.** In a 2026-07 CLI retirement, 27 files matched
> the retired tool's name. Most were **not** the retired tool: some referenced a live API that shares
> the vendor name, some referenced the *replacement's* config directory (named after the old tool),
> and some were model identifiers still in daily use. A name-match deletion would have broken working
> capability while claiming to be cleanup. **Classify, then delete.**

**PROHIBITION vs USAGE is easy to get wrong.** A line reading `` do not reintroduce `gemini -p` ``
matches a search for `gemini -p` but is the opposite of a usage. Removing guard rails during cleanup
is how a retired thing comes back.

---

## 4. P3 — Decide, and be explicit about "nothing replaces it"

For each USAGE, the replacement is either a named substitute or **nothing**. If nothing:

- Say so in the record. "Removed with no replacement" is a legitimate outcome and a **capability
  reduction that must be visible** — never dressed up as an equivalence.
- Every consumer of that capability becomes a §6 gap.
- Resist substituting a *same-family* stand-in to keep a count intact. If a provider slot is now
  empty, an honest record of the gap beats a substitute that shares the failure modes of the arm it
  was meant to cross-check.

---

## 5. P4 — Execute

Order matters:

1. **Remove USAGE first** (highest risk of breakage), then repoint POINTERs, then delete the thing.
2. **Delete the artifact itself** — the directory, the symlink, the config, the installer entry.
   Removing references while leaving the artifact installed produces a thing nobody routes to but
   everyone can still invoke by accident.
3. **Symlinks and mirrors last** — and check every tree the thing was published to, not just the
   authoritative one.
4. Keep PROHIBITION, HISTORY, EXEMPTION and LOOKALIKE untouched.

---

## 6. P6 — Backfill: what the removal broke

**A decommission that files no follow-up work is usually incomplete.** Check and file:

| Trigger | Work to file |
|---|---|
| A capability now has **no owner** | New skill / new provider, or an explicit accepted-loss decision |
| A **pointer had nowhere to go** | Relink target, or delete the promise the pointer made |
| A backlog item's **premise died** | Close it as invalidated — say *why*, do not silently drop it |
| Tests or gates asserted its existence | Update them; a test still asserting a removed thing will be "fixed" by re-adding it |
| A **fallback chain lost a link** | Decide: shorten the chain, or accept reduced redundancy **in writing** |
| Docs describe an architecture that no longer exists | Update the map |

---

## 7. P5/P7 — Verify to grep-zero

A retirement is done when **the repo can no longer contradict itself about whether the thing exists.**

```bash
# 1. No USAGE-class references survive (expect only PROHIBITION / HISTORY / EXEMPTION / LOOKALIKE)
python3 ~/.claude/skills/decommission/scripts/impact_scan.py --term <name> --root <root>

# 2. No skill now contradicts another about its status
python3 ~/.claude/skills/_meta/gates.py G_CLAIM_FRESHNESS --claim-mode strict

# 3. Tests still pass, and no test asserts the removed thing exists
python3 -m pytest <suite> -q
```

**The half-state is the failure mode to hunt.** A repo saying both *"X was retired, do not use it"*
and *"X is alive at v0.52.0"* is worse than one that never removed X, because a reader cannot tell
which sentence is current. That exact state existed for a day after a 2026-07 CLI retirement: the
authoritative directive said retired-and-deleted while the tool's own skill still said *"that
retirement did NOT happen"* — and the contradiction was found by a linter, not by review.

---

## 8. The decommission record

Write one per retirement, alongside the change:

```markdown
## Decommissioned: <thing> — <effective date>
**Reason:** …            **Replacement:** <name> | NONE (capability reduced)
**Recoverability:** version-controlled? <yes/no + which trees> · **Archive:** <path>
**Supersedes:** <prior directive + its date> — reversed by <new authority + date> | none
**Impact zone:** N files across <areas>
**Classified:** usage N · pointer N · prohibition N · history N · exemption N · lookalike N
**Exemptions:** <component> — <reason> — granted by <who>, <when>
**Gaps filed:** #… (orphaned capability) · #… (relink) · #… (invalidated premise)
**Schema changes:** <manifest/enum> v<N> → v<N+1>, fields removed: … | none
**Verified:** impact_scan --strict ✅ · claim-drift gate ✅ · tests ✅ · consumer smoke-run ✅
```

The **exemptions** and **lookalike** lines are the ones a future reader needs most — they are the two
classes that look exactly like unfinished work to someone who was not there.

---

## 9. Anti-Patterns

| Don't | Why it hurts |
|-------|-------------|
| Delete on a name match | Lookalikes break live capability while looking like tidiness |
| Delete before mapping | You lose the knowledge of what pointed at it |
| Remove "do not use X" guard rails | That is the guard against reintroduction |
| Delete dated history because it mentions the thing | History is dated, not stale |
| Leave an exemption undocumented | The next cleanup silently deletes it |
| Stop at references and leave the artifact installed | Invocable by accident, routed to by nobody |
| Substitute a same-family stand-in to preserve a count | Converts a recorded gap into a hidden one |
| Leave the backlog untouched | Tasks whose premise died read as real work forever |
| Declare done without grep-zero | The half-state is worse than not starting |
| Treat "no replacement" as too embarrassing to write | An invisible capability loss is the expensive kind |
| Delete before proving recoverability | Live trees are often NOT repos — `rm -rf` there is final |
| Assume "it's in git" without `git ls-files` | The belief is free; the verification is one command |
| Remove a schema field without bumping the version | Silently breaks every reader that still parses it |
| Silently override a recorded keep-it directive | A reader cannot tell decided-and-reversed from overlooked |
| Clean the live tree but not the repo mirror / publish manifest | The next install or publish restores it |
