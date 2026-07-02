# External-Finding Verification Protocol

Reference doc for forge Step 8b (Spec Review, Stage 1.5). S030-quickwins #37.

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
- agy (`agy --sandbox -p "..."` direct Bash call, bridge-mode agy analyst)
- Any future model added to the forge multi-model pipeline

It does NOT apply to Claude-internal findings — those run in the same
context as the design author and are reviewable by reading the immediate
prompt history; they have a lower (but non-zero) hallucination rate and a
separate review surface.

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
consolidated review and let the user decide whether to fix.

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
