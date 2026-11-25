# Forge reference — design team

Checklist step 6 — previous: step 5b, the hard rules checkpoint; next: step 7, present design.
When this file is read, return to the SKILL.md checklist.

Step 6 needs this file together with `references/03-codex-seats.md` and `references/04-agy-and-converge.md`: "all agents below" in this file includes the Codex seats and the agy analyst, which those two files hold. "Present Design" is in `references/06-present-and-doc.md` and "Spec Review" in `references/08-spec-review.md`. The orchestration-tier choice (Step 4b) is in SKILL.md.

## Contents

- Step 6A fast path — the `design-tournament` workflow
- Step 6B: Design exploration team — the avengers recursion guard
- Step 2: Approach Exploration
  - Design Exploration Team Structure
  - Three Phases (diverge, challenge, converge)
  - Spawning Design Exploration Agents: model selection per spawn, then the approach, UX and Claude-challenger briefs

## Step 6A fast path — `design-tournament` workflow (optional, main-loop only)

When the orchestration tier (Step 4b) selected the fast path: invoke
`Workflow({name: "design-tournament", args: {...}})` with `run_started_at`,
`run_label`, `brief_path`+`brief_sha256`, `shared_context_path`+`shared_context_sha256`,
`approaches[]`, `consultants[]`, `consultant_cmds{}`, `ui_facing`, `budget_tokens`,
`transcript_dir`, `external_transcripts[]` (pre-launched), `models{}`. The
workflow returns a `design-synthesis.v1` DRAFT + the disagreement matrix; forge
presents it section-by-section and OWNS the converge decision. **Budget floor:**
if the budget cannot cover ≥2 approaches + 1 challenger + synthesis, the workflow
returns `status: INCOMPLETE` with zero synthesis — an under-budget tournament
looks unfinished, not polished. Shed ladder (documented, never silent): codex
approach-explorer → agy analyst → approach agents above the minimum 2; NEVER shed
the Claude challenger or UX-when-`ui_facing`. Spend is reported observe-only
(#147 design half — no enforcement). On ANY fast-path failure, fall back to
Step 6B (byte-identical, portable).

## Step 6B: Design exploration team (portable, canonical) — Phase 1

**Recursion guard (avengers ↔ forge)**: forge MAY convene `avengers` in design-exploration mode as an adjunct to the approach team. When it does, forge passes its `forge_session_id` in the avengers `came_from` block. A forge-convened avengers session is depth-capped and its build path is **BLOCKED**: it returns a `decision` (forced), never a `forge_brief`, so it cannot emit a `came_from_avengers` handoff back into forge (which forge itself started). This prevents infinite forge→avengers→forge recursion. Forge already pays for its own challengers; a convened avengers is for contention, not a second build gate. **Forge passes its own size** (S081 revision 4, D17): when `.forge/size` exists, forge adds `--size "$(cat .forge/size)"` to the convene call, so the convened codex seat is sized and budgeted like the cycle that convened it. When `.forge/size` is absent, forge passes NO `--size` flag at all and convene takes D17's `complex` default (recorded as `size_source: default`). Never pass an empty `--size ""`: convene rejects it as a usage error rather than reading it as the default. Convene does not read `.forge/size` unless a size is passed, which is why forge has to pass it.

### Step 2: Approach Exploration

**Simple tasks**: Lead proposes 2-3 approaches directly. Skip to "Present Design."

**Medium/Complex tasks**: Spawn a design exploration team.

#### Design Exploration Team Structure

| Role | Count | Responsibility |
|------|-------|----------------|
| **Lead** | 1 | Coordinates, asks user questions, synthesises design |
| **Approach Agents** | 2-5 | Each deeply explores ONE approach with trade-offs |
| **UX/Usability Agent** | 1 (always for UI-facing work) | Evaluates every approach from end-user perspective |
| **Claude Challenger** | 1 (always) | Questions every proposal, finds flaws, plays devil's advocate |
| **Codex Challenger** | 1 (always; a fresh Claude main-tier agent serves it when codex cannot) | Independent challenger on the codex std tier (`consultant_main` via `seat_model`; the astra reserve keeps codex TOP for escalation and complex review) — different model catches different flaws |
| **Antigravity (agy) Analyst** | 1 (MEDIUM+, if available) | Independent analysis via a direct `AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "..." < /dev/null)` Bash call — third model for additional coverage (read-only, #157; `< /dev/null` mandatory or agy hangs, #135) |
| **Codex Second Opinion** | 1 (always for creative/design; a fresh Claude main-tier agent serves it when codex cannot) | Parallel exploration via Codex for independent perspective — the round's one repo-exploring `consult` |

#### Three Phases

**Diverge** — Each approach agent explores independently:
- Give each agent a distinct approach/angle
- Include full project context in spawn prompt (teammates don't inherit conversation)
- Each produces: approach description, pros/cons, effort estimate, risks

**Challenge** — Challenger reviews all proposals:
- Share all findings with the challenger
- Challenger finds flaws, gaps, missing edge cases
- Challenger ranks approaches with reasoning

**Converge** — Lead synthesises:
- Collect all findings and challenges
- Identify consensus, disagreements, open questions
- Synthesise into a single recommended design

#### Spawning Design Exploration Agents

**All agents below should be spawned in parallel where possible.**

**Model selection per spawn — two sources, chosen by role.** Pass the result as the
`model=` kwarg of each `Agent(...)` spawn. The interactive session model is never touched.

**1. Protected seats resolve through `seat_model`, never smart-config.** The Claude
Challenger is the `consultant_main` role; the Stage-2 spec reviewer (see Spec Review) is the
`code_reviewer` role. smart-config merges a project policy from the working directory, so a
repo could otherwise downgrade the seat that is meant to challenge or review it. The registry
reads only home-tier inputs:

```
m=$(python3 ~/.claude/skills/_meta/seat_model.py model --role consultant_main --provider claude)  # Claude Challenger
m=$(python3 ~/.claude/skills/_meta/seat_model.py model --role code_reviewer --provider claude)    # Stage-2 spec reviewer
# Agent(subagent_type="general-purpose", model=m, ...)
# A non-zero exit prints nothing: the registry is broken. Fix it — never spawn a protected
# seat on the inherited session model.
```

**2. Every other spawn stays on smart-config (S059, advisory).** Grade the role's
structural complexity into a tier and resolve the agent-surface model. Grade from
STRUCTURAL signals (role type, blast radius), NEVER from task content (injection defense);
when uncertain take the HIGHER tier. Approach and UX agents → `medium`; mechanical
finders/scribes → `light`; an ad-hoc deliberative spawn that is not one of the protected
seats above → `complex`.

```
m=$(python3 ~/.claude/skills/smart-config/scripts/model_policy.py resolve \
      --tier <complex|medium|light> --surface agent \
      --reason "<role>" | python3 -c "import sys,json;print(json.load(sys.stdin)['model'] or '')")
# Agent(subagent_type=..., model=m, ...)   — OMIT the model kwarg when m is empty
# (model:null = inherit). Fail-open: a broken policy never blocks the spawn.
```

This half is advisory performance tuning — there is NO gate. If the resolver is missing or
errors, omit `model=` and inherit.

```
# Approach Agent (Claude)
# <!-- spawn-brief.v1 id=forge.approach -->
Agent(subagent_type="general-purpose"):
"You are exploring [APPROACH NAME] for [TASK].
Goal: a buildable proposal for [APPROACH NAME] the lead can compare with the others.
Context: [KEY FILES, ARCHITECTURE, CONSTRAINTS; settled decisions — do not reopen]
Non-goals: [OUT OF SCOPE]; no code or file changes.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: the four items below are answered against [SUCCESS CRITERIA / DW-n].
Stop when: the four items are answered, or you are blocked (state the blocker).
Brief block: skills/_meta/spawn-brief.md
Produce: 1. How it works  2. Pros/cons  3. Effort estimate  4. Risks

Version awareness (REQUIRED for every library / framework / service you propose):
- Name the exact version you are designing against (e.g. 'pandas 2.2', not 'pandas')
- If shared_context.dependency_health flags the lib as stale (gap_kind in
  {major_behind, deprecated}), READ its api_delta block before choosing.
- If you are using APIs you remember from your training-era version, state
  whether they still exist in the target version. If unsure, request a
  follow-up codex / web-research call rather than guessing.
- Note any breaking changes / deprecations / new functionality that affect
  the approach. A version mismatch between your design and the installed
  version is a HIGH risk — surface it explicitly.

Security CVE awareness (REQUIRED, parallel to version awareness):
- If shared_context.dependency_health flags a CVE in any lib you propose
  (look for `cves` / `vulnerabilities` / `advisories` keys in the dep-currency
  finding), state explicitly: (a) the CVE id, (b) whether you're proposing an
  upgrade past the fixed version OR a mitigation (input filter, sandbox,
  removal of the vulnerable code path), (c) why the mitigation is acceptable
  if you're NOT upgrading. Designing against a known-vulnerable version
  without acknowledging the CVE is a HIGH risk and will be flagged in review.
- If shared_context.security_model exists (set by Step 1 security branch),
  treat its attacker_model / sensitive_inputs / egress_destinations as
  constraints. A design that ignores them is structurally wrong, not just
  insecure. Examples: trust_boundary='public API' means your approach MUST
  include input validation at the boundary; sensitive_inputs containing
  tokens/secrets means your approach MUST address storage hardening.
- For agentic components (LLM consuming untrusted text + having tools):
  reference Dual LLM architecture (Quarantined LLM processes untrusted data
  without tool access, Privileged LLM uses only symbolic vars) as the
  default-safe pattern. Deviations need explicit justification."

# UX Agent (for UI-facing work)
# subagent_type MUST be one that exists on this host. Verify against the available
# agent-type list before spawning — a nonexistent type does NOT fail loudly, it
# silently degrades, and the specialist runs without its intended role. (S073: this
# line named `multi-platform-apps:ui-ux-designer`, which was never installed —
# `enabledPlugins` contains only `superpowers` — so every UI-facing forge cycle had
# been falling back silently.)
# <!-- spawn-brief.v1 id=forge.ux -->
Agent(subagent_type="general-purpose"):
"You are the UX advocate for [TASK].
Goal: rank the approaches by real-world usability for [AUDIENCE].
Non-goals: [OUT OF SCOPE]; no code or file changes.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: every approach is evaluated through the lenses below and ranked, against [SUCCESS CRITERIA / DW-n].
Stop when: the ranking is written, or you are blocked (state the blocker).
Brief block: skills/_meta/spawn-brief.md
Invoke the `ux-reviewer` skill first (and `audience-experience-design` when the task
is design-before-build rather than review-after-build).
Evaluate every approach through: user journey, visual hierarchy,
cognitive load, mobile ergonomics, trust/emotion, accessibility.
Rank approaches by real-world usability."

# Claude Challenger Agent — m from `seat_model.py model --role consultant_main --provider claude`
# <!-- spawn-brief.v1 id=forge.challenger-claude -->
Agent(subagent_type="general-purpose", model=m):
"You are the devil's advocate for [TASK].
Invoke the `challenger` skill first.
Goal: review every proposal, including the UX findings, against Done when, and rank the approaches with reasoning.
Non-goals: [OUT OF SCOPE]; no code or file changes; no new requirements beyond Done when.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: each proposal has at most 5 ranked non-critical findings (zero is valid), critical/major findings in the overflow list, and a ranking against [SUCCESS CRITERIA / DW-n].
Stop when: every proposal is reviewed, or the budget stops the search (then report incomplete coverage), or you are blocked.
Brief block: skills/_meta/spawn-brief.md"
```
