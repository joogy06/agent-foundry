# avengers v2 — Deferred Backlog (nothing deferred silently)

**Purpose.** The v2 redesign (design `docs/plans/2026-07-13-avengers-v2-team-composition-design.md`)
shipped the *smallest* useful team-composition change and DEFERRED the rest. This file
records **every** deferred item explicitly — what it is, why it was deferred, the
precondition that unblocks it, and where it will land. A deferred item is a scheduled
decision, never a silent omission. Callers (alf, forge, the user) read this to know what
is intentionally-not-built vs. actually-missing.

Cross-references: design §7 (Scope), §11 (Out of scope for v2), and the WP-5 acceptance
criteria in `progress/work-packages.yaml`.

---

## What v2 SHIPPED (the baseline this backlog is measured against)

- **D1** — constraint-based diversified staffing: `capability-priors.yaml` (DATA), seat
  affinity, ordered-constraint resolver, per-seat `provider:` override still wins, plus the
  **effort-layer refactor** to seat-class semantics (the prerequisite — most of D1's work).
- **D2** — personalities as divergence overlays + overlay lint + position-artifact carry.
- **The arbiter fix** — the EXTERNAL, SEATLESS, cold-context arbiter (clean/fallback paths,
  `fallback_arbiter_residual`, all-adversarial fail-closed).
- **The steward** — principal-proxy seat grounded in a durable/provisional `intent.md`
  (push / judge / flag; **no decide-authority** — that is deferred; see item 6).
- **`evidence_run`** — the sandboxed, read-only, time-boxed evidence primitive.
- **Memory provider-stamping** — inherited entries render third-person at prompt assembly.
- **Instrumentation** — `run-record.json` (§6a) on every run. Non-optional. This is the
  anti-superstition insurance that unblocks most items below.
- **ONE rebuilt profile** — `coding-ratification` (skeptic + architect + operator + steward
  = 4 deliberation seats + external arbiter; `max_seat_calls: 13`, no phase truncated).

---

## Deferred items

### 1. Seat rotation (off-by-default flag)
- **What.** Rotate providers/seats across runs to spread family exposure and reduce
  entrenched self-preference, instead of the fixed affinity resolution v2 ships.
- **Why deferred.** Rotation without evidence is superstition — it would randomize
  staffing before we can measure whether it helps or hurts. It is a knob that needs data.
- **Unblocked by.** The §6a `run-record.json` instrumentation (SHIPPED in v2). Once several
  runs have accumulated records (dissent margin, outcome grade, fallback residual), rotation
  becomes a measurable experiment.
- **Lands as.** An **off-by-default** flag gated on the instrumentation record. Never
  on-by-default in v2 (design §11 explicitly excludes rotation-on-by-default).

### 2. The 4 remaining profile rebuilds
- **What.** Rebuild `website-ux`, `writing-cv`, `research-synthesis`, and `business-ideation`
  to the v2 composition surface (external arbiter, overlays + lint, steward where the family
  warrants a principal-proxy, seat-class effort, run-record instrumentation).
- **Why deferred.** v2's scope decision was ONE rebuilt profile — `coding-ratification`, the
  measured family. The other four are not yet convened this cycle; rebuilding them now would
  be speculative work on unvalidated composition assumptions.
- **Unblocked by.** Convening the family. **Rebuild each the week it is next convened**, from
  a documented migration template.
- **Lands as.** A **documented template + migration note** (derived from the
  `coding-ratification` rebuild) applied per-profile on first v2 convene. The four profiles
  remain valid v1-surface DATA until then (v1 schema stays on disk unmutated, so they keep
  validating).

### 3. New roster cards: PM / domain-specialist / research-scout
- **What.** Additional seat archetypes — a project-manager lens, a domain-specialist lens,
  and a research-scout lens — to widen the composition vocabulary beyond the current roster.
- **Why deferred.** Not needed by the one rebuilt profile; adding cards nobody convenes is
  dead DATA. **research-scout additionally requires a duplication check** against the
  existing `web-research` / `deep-research` skill family before it is built — a scout that
  re-implements those skills would be redundant surface.
- **Unblocked by.** (a) a profile that needs the archetype, and (b) for research-scout, the
  dedup check vs `web-research`/`deep-research` coming back "genuinely distinct".
- **Lands as.** New `roster/<archetype>.yaml` cards, each with the v2 core/overlay split.

### 4. Agreement-modulation + verbosity-pruning knobs
- **What.** Tunable controls over how strongly seats are pushed to converge (agreement
  modulation) and how aggressively verbose turns are pruned (verbosity pruning).
- **Why deferred.** Both need telemetry to tune sensibly — set blind, they degrade either
  contention quality (over-pruned) or cost (under-pruned).
- **Unblocked by.** The §6a instrumentation accumulating enough runs to tune against
  (same dependency as rotation).
- **Lands as.** Profile-level knobs, defaults chosen from measured run-records.

### 5. `effort_on_codex: max` vs the 2026-07-11 sol-benchmark re-derivation
- **What.** Re-derive the ratification-arbiter `max`/1200 codex effort pin against the
  2026-07-11 sol effort benchmark (which measured medium ≈ high, xhigh = quality ceiling,
  max/ultra = waste on bounded reviews).
- **Why deferred.** It is **moot for `coding-ratification`**, whose arbiter is claude on the
  fallback path — codex is the excluded adversary and never resolves as arbiter here. The
  `max` pin only fires if some *other* profile resolves a **codex** arbiter, which none of
  the shipped families do. Re-deriving a value nothing currently uses is premature.
- **Unblocked by.** A profile whose arbiter can genuinely resolve to codex (i.e. codex is
  NOT a deliberation seat in that family, so it is a clean-path arbiter candidate).
- **Lands as.** A revised `effort_on_codex` default (likely `xhigh`, per the benchmark
  ceiling) with a recorded rationale, applied when a codex-arbiter-capable profile exists.
  `convene.py` already reads `effort_on_codex` from the profile, so this is a DATA change.

### 6. The autonomy layer (intent.md → delegation charter)
- **What.** Upgrade `intent.md` from an intent artifact into an intent **+ delegation
  charter** by ADDING `may-decide` / `acceptable-tradeoffs` / `must-escalate` sections,
  granting the steward (or the run) bounded decide-authority.
- **Why deferred.** v2's steward deliberately has **no decide-authority** — it pushes,
  judges, and flags, but never decides or arbitrates (it has skin in the outcome). Granting
  decide-authority is a trust escalation that belongs to a separate, deliberate layer, and
  **never in an interactive convene where the user is present**.
- **Unblocked by.** A user decision to build the autonomy layer. The parsing is **already
  forward-compatible**: `intent.md` ignores unknown headings (kept in `additional_sections`,
  never rejected), so a charter-carrying `intent.md` parses cleanly today — v2 simply does
  not act on the charter sections. The extension is genuinely additive (design §5,
  `references/intent-artifact.md`).
- **Lands as.** Charter-section handling in the `intent.md` reader + a gated decide path.

### 7. The autonomy scheduler + inbox-triage + dependency-zone gate
- **What.** A scheduler that CONSUMES the v2 roster to run unattended deliberations, with
  inbox triage and a dependency-zone gate.
- **Why deferred.** Correctly sequenced AFTER v2: the scheduler consumes this roster, so the
  roster/composition surface had to stabilize first (design §11). Separate backlog items.
- **Unblocked by.** A stable v2 composition surface (now shipped) + a decision to build the
  scheduler.
- **Lands as.** A separate scheduler subsystem, out of the avengers skill's v2 tree.

---

## Rejected (NOT deferred — decided against, design §11)

These are recorded so they are not re-proposed as "missing":

- **Build-capable avengers** — REJECTED. avengers is a deliberation surface; it NEVER spawns
  bob, signs a contract map, or marks anything bob-ready. Build-flavored outcomes exit ONLY
  as an `avengers_brief` into forge's gate machinery. (HARD-RULE, `SKILL.md`.)
- **Rotation-on-by-default** — REJECTED for v2 (rotation itself is deferred off-by-default;
  see item 1).
- **Measured / learned routing (v3)** — the run-record is the seed DATA; the learned router
  that consumes it is v3, not v2.

---

## v1 out-of-scope still standing (design §14 — do NOT flag as "missing")

Global member-memory tier (no loader branch by design); `vindicated/refuted` calibration;
mid-phase interjections; repo-local config overrides; roster-editing UX; provider SDK/MCP
abstraction; embeddings/vector retrieval. Design-for-not-build; intentional, not drift.
