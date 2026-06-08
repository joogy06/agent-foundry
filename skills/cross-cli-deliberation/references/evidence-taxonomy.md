# Evidence Taxonomy and Verification

Full Gate-2 admissible evidence specification + orchestrator verification protocol.

## The principle

A `CHANGE_NEEDED` ballot must ship verifiable evidence under exactly one of three classes. No admissible evidence → **Null Verdict** (failed falsification = strongest validation of the artifact).

The taxonomy is intentionally narrow. The narrowness IS the anti-sycophancy mechanism: if you can't ground your objection, your objection probably isn't real.

The taxonomy is also intentionally not just for code. Class 1 (Reproduction) admits procedural traces, not only executable tests. This is the F1 patch — without it, valid structural / governance / design objections would be excluded purely for not being code.

## Class 1: Reproduction

Three admissible sub-forms, in increasing breadth:

### 1a. Executable test

A standalone script, test, or shell command that:
- Fails on the artifact's current state
- Passes on the proposed change

The orchestrator verifies by **running the test**. If the test does not fail on the current state, or does not pass on the proposed change, the evidence is bogus and the ballot is nullified.

Use when the artifact is code or a system whose behavior can be exercised programmatically.

### 1b. Procedural trace

A step-by-step trace through the protocol / system / decision flow on a representative artifact, showing observable failure mechanics.

Required structure:
1. **Artifact**: the input to the trace (a concrete proposal, a representative input, etc.)
2. **Trace**: numbered steps showing how the protocol/system processes it
3. **Failure mechanics**: the specific step where the failure becomes observable
4. **Expected vs actual**: what the protocol/system should produce vs what it actually produces
5. **Why this is structural**: why a different artifact in the same class would fail the same way

The orchestrator verifies by **walking the trace**: re-running the steps mentally or in writing, confirming each step follows from the protocol/system rules, and confirming the failure mechanics is observable at the named step.

Use when the artifact is itself a protocol, decision flow, governance rule, or any non-code system whose failure mode is logical rather than executable.

### 1c. Failure mechanics with minimal remedy

A trace as in 1b, plus an explicit minimal remedy:
- The smallest patch to the artifact that would fix the named failure
- The trace re-run against the patched artifact, showing the failure is resolved

The orchestrator verifies by **walking both traces** (pre-patch fails, post-patch passes) and confirming the patch is genuinely minimal (no smaller patch would also fix it).

Use when (a) the failure is structural enough that the consultant has thought about the fix, OR (b) when the consultant wants to defend the proposal stronger than just "there is a problem."

## Class 2: Constraint violation

A direct quote of a pre-existing constraint that the artifact violates.

Required structure:
1. **Source**: file path + line range, or doc title + section, or rule identifier. Must be locatable.
2. **Quote**: the exact text of the constraint (verbatim, in quotes).
3. **Violation**: how the artifact violates it (paraphrase + reference to specific clause/element of the artifact).

The orchestrator verifies by **reading the source**, confirming the quote is accurate, and confirming the artifact does in fact violate it. If the quote is paraphrased, fabricated, or misapplied, the ballot is nullified.

Use when the violation is a known rule (CLAUDE.md constraint, AGENTS.md directive, project policy, declared invariant, prior decision recorded in MEMORY.md, etc.).

## Class 3: Efficiency regression

A measurable degradation in some efficiency metric, not offset by a corresponding gain.

Required structure:
1. **Metric**: latency, tokens, complexity, memory, throughput, etc.
2. **Current**: the value of the metric on the current state (number with units).
3. **Proposed**: the value on the proposed state (number with units).
4. **Method**: how the values were measured. If estimated, the basis for the estimate.
5. **Not offset by**: explicit argument that no compensating gain (correctness, robustness, simplicity, etc.) justifies the regression.

The orchestrator verifies by **reproducing the measurement** (or sanity-checking the estimate) AND by considering the not-offset argument. If the measurement doesn't reproduce or the not-offset argument is weak, the ballot is nullified.

Use when the objection is "this is technically correct but worse on a measurable dimension."

## Verification protocol

For every `CHANGE_NEEDED` ballot, the orchestrator MUST:

1. **Identify the class** the consultant is claiming.
2. **Apply the class-specific verification** (run the test, walk the trace, read the source, reproduce the measurement).
3. **Decide one of three outcomes**:
   - **Verified**: evidence reproduces as claimed → enter synthesis with this verdict
   - **Borderline**: evidence is partially correct, partially weak → seek clarification or escalate to user
   - **Bogus**: evidence does not reproduce / fabricated quote / unverifiable → flag consultant for "hallucinatory helpfulness," nullify ballot, treat as if verdict were ACCEPT_AS_IS

4. **Log the outcome** alongside the verdict (consultant id, served_by, class, verification result).

## Anti-patterns in the evidence

| Don't | Why |
|---|---|
| Accept "in principle this could fail" without a concrete trace | The principle is, every objection must be groundable. Hypothetical failures with no concrete trace are exactly what the protocol is designed to reject. |
| Accept evidence that the orchestrator has not personally verified | Trusting the consultant's claim that the test fails / quote exists / metric regresses is the verification step the protocol exists to enforce. |
| Treat a procedural trace as "weaker" than an executable test | Both are admissible. The choice depends on the artifact, not on a hierarchy. A protocol artifact CANNOT have an executable test against it; that's the whole point of class 1b. |
| Reject evidence because it doesn't fit the class the consultant initially named | Re-classify if needed. A trace claimed as "reproduction" might actually be a constraint violation in disguise; that's fine, just record the actual class. |
| Skip verification because "the consultant is usually right" | Consultants drift, hallucinate, and produce-because-asked. The verification step is the protocol's only defense against that. |

## Edge cases

**Multiple classes claimed**: take the strongest one. The other classes can be cited as supporting context, but verification only needs to succeed for one.

**Evidence partly verifies**: if part of the trace passes verification but part fails, the ballot is borderline. Depending on stakes, either accept the verified portion as a partial verdict or escalate.

**Evidence requires running code in an unsafe context** (e.g., production system): substitute a representative test environment. If no representative environment is available, the orchestrator must declare this and either accept on inspection (less rigor) or block the verdict (more rigor).

**Evidence cites a constraint that is itself contested**: chase the contestation. If the cited constraint is invalid, the ballot is bogus. If valid, the ballot stands.
