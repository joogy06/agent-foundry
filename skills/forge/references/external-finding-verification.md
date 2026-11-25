# External-Finding Verification Protocol

Reference doc for forge Step 8b (Spec Review, Stage 1.5). S030-quickwins #37.

## Contents

- Why this exists
- When to run
- Protocol: find the cited artifact, confirm the claim, classify the finding, route by classification, rule goal-fit
- Worked example: a Codex hallucination (S030-init WP-0)
- Worked example: a real bug (illustrative)
- Worked example: an owner statement widened into a rule (`constraint-question`)
- Worked example: a genuine trade-off (`works-against`, illustrative)
- Anti-patterns

## Why this exists

Codex and agy, when asked to adversarially review a forge design doc,
hallucinate findings at a meaningfully high rate. Two cases of record:

- **DLP pilot (2026-04-09)**: Codex flagged 11 critical issues in a forge
  design. Independent verification by reading the cited spec text showed
  7 of the 11 were FALSE-POSITIVES — the model had misread the spec and
  fabricated contradictions that did not exist (~64% FP rate).
- **S030-init WP-0 (2026-04-28)**: Codex flagged a `TS-PSV-04` "spec
  contradiction" in the tester-split design as CRITICAL. Reading the
  spec text in question, the cited line said the OPPOSITE of what Codex
  claimed. Treated as classic Codex hallucination; design unchanged.

If forge merges these findings into the consolidated review report without
verification, it propagates the hallucination into the design doc, wastes
user review attention, and (worst case) drives a real revision to fix a
problem that does not exist.

The verification pass is the firewall.

## When to run

Run BEFORE merging external-model findings into the consolidated review
report. Applies to ALL findings produced by external models, regardless of
which model produced them:

- Codex (`/codex:review`, `/codex:adversarial-review`, `codex exec` direct)
- agy (`AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "..." < /dev/null)` direct Bash call, bridge-mode agy analyst)
- Any future model added to the forge multi-model pipeline

Steps 1-4 do NOT apply to Claude-internal findings — those run in the same
context as the design author and are reviewable by reading the immediate
prompt history; they have a lower (but non-zero) hallucination rate and a
separate review surface. Step 5 is the exception: it applies to Claude findings too.

## Protocol

### 1. For each external-model finding that cites a specific artifact

A "specific citation" is any reference to:
- A file path
- A line number range
- A function / class / type name
- A spec section header
- A YAML / JSON key
- A specific test / fixture

Findings that are purely abstract ("the architecture should be more
modular", "consider adding rate limiting") do not need verification — they
are opinions, not factual claims, and should be evaluated on merit alone.

### 2. Open the cited artifact and confirm the claim

Use Read or Grep to look up the cited line/symbol and read it directly.
Compare what the model SAID is there to what is ACTUALLY there.

### 3. Classify the finding

- **VERIFIED**: The citation matches and the claim is consistent with the
  artifact. The model identified a real issue.
- **FALSE-POSITIVE**: The citation does NOT match the claim. The artifact
  contradicts the model's interpretation, or the cited line says something
  different, or the cited symbol does not exist.
- **NEEDS-FOLLOWUP**: The citation is real but the interpretation is
  ambiguous and depends on context the model may not have. Flag for the
  user.

### 4. Route by classification

- VERIFIED → into the consolidated review report under "External findings".
- FALSE-POSITIVE → into a separate section "False positives, with grep
  evidence" so the user can audit the verification pass itself.
- NEEDS-FOLLOWUP → into a third section "External findings needing user
  adjudication" with the verbatim model claim, the verbatim cited text,
  and a one-line note on why the verification was inconclusive.

### 5. Rule goal-fit on every verified finding

This step is not limited to external models. It covers every verified finding from every reviewer (Claude, Codex, agy), at every severity, owner-decision items included, and it runs in the main loop, after `ratify-design` returns when that workflow ran.

Steps 1-4 ask whether the citation is real. This step asks whether acting on the finding serves the design doc's Purpose. It judges the **fix**, never the existence of the defect. With `Purpose: none stated` it is skipped and the report says so. Reviewers flag; the lead rules, because the lead holds the owner's words.

1. **First branch, before any ruling: `constraint-question`.** A finding that exists only because of a `lead-inferred` constraint is not ruled. Record it as `constraint-question` and put it to the owner as a question about the constraint, with no fix proposed. If the owner confirms the constraint, relabel it `owner-stated: "<quote>"` and rule the finding normally. If the owner rejects it, the finding closes with their words quoted. This branch comes before the must-resolve list, except for security, data loss and payment findings.
2. **Otherwise rule the proposed fix:** `serves`, `neutral` or `works-against`. `serves` and `neutral` take the existing path.
3. **`works-against`, for a real defect.** Look for a fix that resolves the defect without harming the Purpose. If one exists and the finding is critical or major, it is the fix, with no approval step, and the swap is recorded. For a minor or an owner-decision item it is offered, not applied. If none exists, the finding goes to the user labelled `works-against` with both sides, and no default fix, unless it is on the must-resolve list.
4. **Record** one word per verified finding, a sentence only for `works-against`. The report header carries `goal-fit: n ruled, m works-against, k constraint-question`.

The ruler is the actor who erred in the retro this step comes from, so the ruling has limits: it must quote the Purpose and name the concrete outcome harmed, some grounds are never accepted, some defects must be resolved whatever the ruling (their remedies still get the question and the search for a fix that keeps the Purpose), and the user rules on any open critical or major. They are in `references/10-close-out.md`, step 1a, with the D21 mechanics.

## Worked example: S030-init WP-0 CRITICAL classified as Codex hallucination

**Codex finding (CRITICAL):**

> TS-PSV-04 in the tester-split design contradicts §5.6's outer gate by
> requiring the arbiter to override audit_spawn whenever they disagree.
> This violates the design's stated "Either failing → stay at INTEGRATED"
> rule. Recommend retracting TS-PSV-04 or rewriting §5.6 to match.

**Verification step:**

`docs/plans/2026-04-21-tester-split-design.md` §5.6 reads (verbatim):

> Both arms VERIFIED + arbiter accepted → apply transition.
> Either arm REJECTED → stay at INTEGRATED, freeze dependents, escalate.

`docs/plans/2026-04-21-tester-split-design.md` TS-PSV-04 reads:

> The arbiter MUST NOT override audit_spawn's REJECTED verdict. If
> audit_spawn says fail, the WP stays at INTEGRATED regardless of arbiter
> verdict.

**Classification: FALSE-POSITIVE.**

The spec is internally consistent — both §5.6 and TS-PSV-04 say "either
fails → stay at INTEGRATED". Codex misread one of the two and fabricated
a contradiction. Filing under "False positives" with the two verbatim
quotes attached is sufficient evidence; no design change required.

## Worked example: a real bug (illustrative)

**agy finding (HIGH):**

> The `claims.issue_claim()` function in `_meta/claims.py` calls
> `purge_claims_for_wp()` BEFORE checking that all dependencies are at
> the required minimum stage. If the WP fails the dep check, the previous
> claim has already been purged — the user must reissue manually.

**Verification step:**

`_meta/claims.py:issue_claim` lines 275-294 read:

```python
with _bob_claim_lock(project_root):
    purge_claims_for_wp(claims_dir, wp_id)            # line 277
    ledger = read_ledger(ledger_path)
    row = ledger.row(wp_id)
    if row is None:
        raise RuntimeError(...)
    required_min = REQUIRED_STAGES_BY_SKILL.get(...)
    for dep in row.deps:
        dep_row = ledger.row(dep)
        if dep_row is None:
            raise RuntimeError(...)                    # line 290
        if stage_order(dep_row.stage) < stage_order(required_min):
            raise RuntimeError(...)                    # line 293
```

The purge IS at line 277, the dep check IS at line 290+. The model's
finding matches the code.

**Classification: VERIFIED.** Real bug. Forge should propagate it into the
consolidated review. Step 5 then rules the fix; the user decides only where that step says so.

## Worked example: an owner statement widened into a rule (`constraint-question`)

The retro behind step 5, replayed with its real inputs. A consumer project's forge cycle existed to improve local SEO.

- **Owner:** "we allow local collection but no show room."
- **Constraint as the lead wrote it:** never write "visit", "shop", "store", "showroom" or shop opening hours. Labelled, it splits: the showroom wording is `owner-stated: "we allow local collection but no show room."`; the opening-hours clause adds to what the owner said, so it is `lead-inferred`.
- **Finding:** a **minor** from a fresh **Claude** reviewer, marked **owner decision**: the `LocalBusiness` JSON-LD is `ComputerStore` with `openingHoursSpecification` Mon-Fri 09:00-17:00.

**What happened:** the citation was real, so every check passed, and the lead relayed the finding with "I'd remove", in the sign-off for a release whose purpose was local search. The owner caught it with one question.

**Replay:**

1. Steps 1-4: the citation matches. **VERIFIED.**
2. Step 5 still applies: being a minor, from a Claude reviewer, on an owner-decision item exempts it from nothing.
3. Without the `lead-inferred` clause the hours contradict nothing, so the finding exists only because of that clause. **`constraint-question`.** It is not ruled and no fix is proposed.
4. It reaches the owner as a question about the constraint: "The brief says no shop opening hours. That clause is mine, not yours: you said no show room. Did you mean the hours too? Effect on the Purpose: not evaluated." No recommendation goes with it.
5. Report header: `goal-fit: 0 ruled, 0 works-against, 1 constraint-question`.

If the owner rejects the clause, the finding closes with their words quoted and the hours stay. If they confirm it, it becomes `owner-stated: "<quote>"` and the finding is ruled normally. While the hours are true, removing them harms the Purpose, so the fix is `works-against` and takes the route in step 5. If the owner says the hours are false, the markup is a claim false on owner-stated facts, which is on the must-resolve list: the defect must be resolved, but the remedy still gets the question. Removing the hours works against the Purpose and correcting them to the true hours does not, so correcting them is the fix. The same holds if the markup fails a schema gate: repair the markup so the gate passes and the accurate hours stay; deleting them is the remedy only if no such repair exists, and the harm is then reported beside the fix.

## Worked example: a genuine trade-off (`works-against`, illustrative)

**Purpose:** `owner-stated: "the status page must load instantly on a bad connection"`.

**Finding (major, Codex, VERIFIED):** the page serves a snapshot up to five minutes old with no age shown, so a reader can take a resolved incident for a live one. Proposed fix: drop the snapshot and fetch live on every view.

**Ruling:** no `lead-inferred` constraint is involved, and the finding is not on the must-resolve list. The defect is real and the fix is `works-against`: "the status page must load instantly on a bad connection", and a live fetch puts a round trip on the bad connection before anything renders.

**Route, when another fix exists:** keep the snapshot, show its age and refresh it in the background. That resolves the defect without harming the Purpose. The finding is a major, so this is the fix, with no approval step, and the swap is recorded.

**If it were on the must-resolve list:** suppose the stale page were failing a DW. The remedy gets the same question and the same search, and the snapshot-with-age fix is still the one applied. Only if no such fix existed would the live fetch go in, with the harm reported beside it. The defect is not left open.

**Route, when none exists:** suppose instead the finding were that readers need per-region detail the snapshot cannot hold, so every fix adds the round trip. It goes to the user labelled `works-against`, with both sides and no default fix. If it is the last blocker the round is recorded `awaiting-user`; otherwise the round stays `fixing`, or `exhausted` at the bound. The finding is carried in `--raised` and `--verified` on every later row. The user says fix (a `--user-directed` round) or leave it (`unfixable: contradicts a standing user decision`, quoting the ruling).

## Anti-patterns

- **Trusting the model on its own citation accuracy** (the whole point is
  that it lies)
- **Skipping verification because Codex sounds confident** (it always sounds
  confident; that's a stylistic feature, not evidence)
- **Treating agy findings as more authoritative than Codex** (both
  hallucinate at similar rates; neither has earned a free pass)
- **Discarding the model's findings entirely on first false positive** (the
  ~35% verified findings are still worth surfacing)
- **Running the verification pass in the same context as the design author**
  (you read the spec yesterday and your priors will bias the verification;
  if you see a Stage 1 design where you have strong priors, hand the
  verification pass to a fresh subagent)
