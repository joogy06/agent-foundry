---
name: skill-intake
description: Use when a skill — or a whole second tree of them — arrives from outside the library and has to be assessed before it is adopted, including reconciling two repos that were forked from one and have since diverged — measuring whether it adds capability the library does not already have, deciding between adopt, merge, adapt and reject, analysing what the skill actually changes about model behaviour when loaded rather than what it claims, and adapting its shape for the target environment including sanitising the patterns that trip enterprise security scanners. Covers merging two overlapping skills without losing either's value, and recording provenance.
disambiguation: INGESTING skills from outside — assess, merge, adapt, sanitise, and reconcile two whole trees that drifted apart. Authoring a new skill from a identified gap is research-for-skills; retiring one is decommission; exporting the library to a public mirror is publish-to-github; measuring description collisions across the library is _meta/skill_overlap.py, which this skill calls.
---

# Skill intake

Skills arrive in different shapes — from another team, another harness, a public repo, a different
enterprise standard. This decides whether one earns a place, and what it must become first.

## 1. The four verdicts, and the honest default

| Verdict | When |
|---|---|
| **ADOPT** | Adds capability the library lacks, and its shape already fits |
| **ADAPT** | The capability is wanted; the shape is wrong for the target environment |
| **MERGE** | It overlaps an existing skill and each holds something the other lacks |
| **REJECT** | It adds nothing measurable, or its value is already covered |

**REJECT is the default, and it is not a failure.** A library's usefulness degrades as it grows:
every added skill dilutes selection, and two skills that both plausibly match a task make the
selector worse, not better (`_meta/skill_overlap.py` exists because that degradation is measurable).

**"It looks useful" is not a verdict.** §2 and §3 are how you get one.

## 2. Does it add capability? — measure, do not judge

Run the mechanical checks before forming an opinion:

```bash
python3 ~/.claude/skills/skill-intake/scripts/assess.py --skill /path/to/incoming/SKILL.md
```

It reports description overlap against every existing skill, security-scanner risks, portability
problems and structural conformance. **What it cannot tell you is whether the content is any good** —
that is §3.

Then answer, in writing:

1. **What can the library do with this that it could not before?** State it as a task the library
   currently handles badly. If you cannot name one, the answer is REJECT.
2. **Which existing skill is nearest?** If overlap is high, the question is MERGE, not ADOPT.
3. **Would a competent model already do this correctly without the skill?** If yes, it is restating
   general knowledge, and it costs selection quality for nothing.

## 3. Behavioural analysis — what does it actually DO when loaded?

**A skill's value is the behaviour change it causes, not the information it contains.** This is the
assessment people skip, and it is the one that separates a useful skill from a well-written document.

Ask what loading it changes:

| Effect | Signal it is real |
|---|---|
| **Constrains** — forbids a tempting wrong move | Names the failure and why it is tempting |
| **Sequences** — imposes an order that matters | The order has a stated consequence if broken |
| **Supplies facts** the model cannot know | Version-stamped, sourced, environment-specific |
| **Selects tools** — routes to the right one | Names concrete tools and the boundary between them |
| **Shapes output** — a required artifact form | The shape is checkable |

**Red flags that it changes nothing:**

- Restates what a competent model already does — "write clear code", "consider edge cases".
- **Asserts capability without supplying it** — "handles X robustly" with no procedure.
- Pure prose with no decision points, no failure modes, no commands.
- Facts with no version or source, which will rot invisibly.
- **Would produce identical behaviour if deleted.** This is the test. If you cannot describe a task
  whose outcome differs with and without it, it is documentation, not a skill.

**The cheapest empirical check:** take a task the skill claims to improve, and compare the response
with and without it loaded. A skill that earns its place changes the answer visibly.

## 4. Adapting for the target environment

The commonest reason a good skill cannot be adopted as-is: it was written for a **permissive
home-grown environment** and the target is **enterprise-constrained**.

| | Home-grown | Enterprise |
|---|---|---|
| Network | Live lookups, web fetches | **Often blocked** — facts must be in reference files |
| Tools | Assumes a rich local toolchain | Assumes almost nothing; degrade gracefully |
| Shell | Free use | Restricted, audited, sometimes absent |
| Paths | Absolute dev-host paths | Must be relative or configurable |
| Secrets | `~/.secrets` convention | Vault, managed identity, or injected env |
| Model | One known CLI | Several, with different tool vocabularies |

**The structural adaptation is to move volatile knowledge into reference files.** A skill that
fetches a rate, a version or an endpoint at runtime cannot work where egress is blocked. The same
skill with a version-stamped reference file and a `REVIEW_BY` date works everywhere, and degrades
honestly instead of failing.

### Sanitising what trips security scanners

Skills are read by scanners that do not know your intent. These patterns cause blocks and are almost
always avoidable:

- **Credential-shaped literals** in examples — use obvious placeholders, and keep any that must look
  real out of scannable paths (this library uses a detector-docs exemption for exactly that).
- **`curl`/`wget` to arbitrary hosts**, especially piped into a shell. Name the URL as a reference
  and let a human fetch it.
- **`eval`, dynamic exec, base64 blobs.** Any of these in a skill will be flagged, and rightly.
- **Absolute paths to a developer machine** — they leak topology and break elsewhere.
- **Real hostnames, internal domains, account ids, personal names.**
- **Instructions to disable a safety control** — even as a workaround, even conditionally.

**Sanitise at source, not by exempting the scanner.** An exemption is a permanent hole; a placeholder
is a one-line fix. Exempt only where the content genuinely must contain the pattern — a redaction
test, a scanner's own source — and record why.

## 4b. Two whole trees that drifted apart

The commonest large version of this: **two repos were forked from one, both were worked on,
and now one has far more skills and scripts than the other.** Someone has to pick the
target, decide what comes across, and — the part that gets missed — find what changed on
*both* sides.

```bash
R=~/.claude/skills/skill-intake/scripts/reconcile.py
python3 $R --source <other-tree>/skills --target ./skills diff     # classify everything
python3 $R --source <other-tree>/skills --target ./skills gaps     # what target lacks
python3 $R --source <other-tree>/skills --target ./skills plan --out reconcile-plan.md
```

**Pick the target first, and pick it once.** The target is where work lands from now on;
everything else is a source. Choose on which tree the *team* actually uses and which has the
working gates and tests — **not on which has more skills**, since count is not capability.

Four categories come back, and their weights are not equal:

| Category | What it means |
|---|---|
| `identical` | Byte-identical. No action |
| `source_only` | Candidate to migrate — **one `assess.py` verdict each**, and REJECT is still the default |
| `target_only` | Target is ahead. Informational |
| **`divergent`** | **Same name, different content, both edited. Resolve these first** |

**`divergent` is the category that destroys work.** `source_only` is a shopping list and
everyone finds it; a skill edited on both sides gets resolved by whoever copies last, and
**the loss is silent** — nobody notices the other side's paragraph is gone. Merge those per
§5, one at a time.

**The tool classifies and never copies.** That separation is deliberate: enumeration is
mechanical and safe, migration is a decision, and a tool doing both would make the easy half
feel like the whole job.

**Do not trust modification times, and the tool says so where it prints them.** Copying a
tree rewrites mtimes, so a freshly-cloned stale repo looks newer than what it came from.
Line counts are scale, not quality.

### After any migration

1. **Re-run `_meta/skill_overlap.py`.** A migrated skill that collides with an existing one
   degrades selection for the whole library — add `disambiguation:` *before* re-pinning.
2. **Check every cross-reference the migrated skill makes.** A `See also` pointing at a skill
   that exists only in the source is a phantom reference, and it will not fail loudly.
3. **Re-point absolute paths and harness assumptions** (§4).
4. **Create the symlinks and mirrors the target expects.**
5. **Run the target's test suite** — migrated scripts are what breaks.
6. **Record provenance** (§6).

## 5. Merging two overlapping skills

When both hold value, merging is right, and the risk is losing the smaller one's contribution.

1. **List what each has that the other lacks** — concretely, section by section. Do this before
   deciding which is the base.
2. **Base on the better-structured one**, which is not always the larger.
3. **Port the unique content**, keeping its specifics — a worked example and a named failure mode are
   the parts that carry value, and they are what gets smoothed away in a rewrite.
4. **Reconcile contradictions explicitly.** Two skills disagreeing on a fact means one is wrong or
   they are scoped differently; say which, in the merged file.
5. **Write the `disambiguation:`** against the neighbours that remain.
6. **Retire the absorbed skill through `decommission`**, not by deleting it — its references need
   redirecting.
7. **Re-run the overlap scanner** and accept the pair into the baseline deliberately.

## 6. Provenance

Record, in the skill: **where it came from · its licence · what was changed and why · what was
removed.**

A skill adopted from outside and edited is neither theirs nor cleanly yours. Someone will later need
to know whether a claim came from the original author or from your adaptation — particularly if the
original is updated and you want to re-merge.

## 7. Anti-patterns

- **Adopting because it is well written.** Prose quality is not capability.
- **Skipping the behavioural test** — if deleting it changes nothing, it is documentation.
- **Adopting a near-duplicate** and degrading selection for the whole library.
- **Exempting the security scanner** instead of sanitising the source.
- **Porting a live-lookup skill** into an egress-blocked environment unchanged.
- **Merging by rewrite**, smoothing away the specifics that carried the value.
- **Losing provenance**, so nobody can re-merge upstream later.
- **Keeping facts without a version or `REVIEW_BY`** — they rot silently and confidently.
- **Choosing the migration target by skill count** rather than by which tree the team uses
  and which has the working gates and tests.
- **Migrating `source_only` first** and leaving `divergent` — the category that loses work.
- **Resolving a divergent skill by copying one side over the other**, silently discarding
  whatever the other side added.
- **Trusting mtimes** to decide which side is newer, when copying a tree rewrote them.
- **Skipping the overlap re-scan** after a bulk migration.
