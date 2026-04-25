---
name: founder
description: >
  Use when the user asks about starting a venture, generating business ideas, validating an idea,
  building a business model, going to market, running a sprint, or any pre-execution founder /
  innovator / inventor / entrepreneur intent. Trigger on: business idea, founder, entrepreneur,
  startup, venture, pre-seed, seed, market discovery, niche, pain point, validation, MVP, pitch,
  "should I build X", "what should I build", "unit economics", "what should I charge",
  "run a sprint", "what stage am I at".
---

# Founder (Parent)

Parent skill for the `founder-*` family. Thin router, venture-state owner, hard-rules enforcer.
Designed to defeat the "LLM as polished startup guru" failure mode by grounding every response in
real data, explicit kill criteria, and adversarial cross-fire — via the subskills and the
`adversarial-team-brainstorm` primitive.

**Scope:** Pre-execution founder journey. Ideation → validation → business model → go-to-market.
Does NOT own execution (that's `forge` + `bob`). Does NOT give legal, tax, valuation, or
securities-law advice.

**Family (Phase 1 + Phase 2 shipped, Phase 3 planned):**
- `founder-ideation` — Phase 1 flagship — adversarial team brainstorm + Reddit/GDELT grounding
- `founder-validation` — Phase 2 — experiment design, Mom Test interview scripts, evidence capture, browser MCP analytics (Envelope D)
- `founder-business-model` — Phase 2 — contribution margin, pricing sensitivity, payback intuition, scenario tables (calculator mode)
- `founder-sprint` — Phase 2 — Diagnose -> Evidence -> Decision -> Handoff stage machine, forge handoff
- `founder-gtm` — Phase 3 (deferred) — positioning, distribution-first, channel selection

---

<HARD-RULE id="HR-1">
**No valuation, cap table, term sheet, SAFE, or securities law advice.** LLMs are dangerously
wrong on jurisdiction-specific finance and can cause real harm if followed. REFUSE with:
> "I can't advise on valuation / cap table / term sheets / SAFEs / securities law. These are
> jurisdiction-specific, legally binding, and outside my scope. Hand off to a venture lawyer or
> CFO in [geography]. I can help you prepare the questions to ask them."
Then offer to route to `founder/references/fundraising-literacy.md` for question lists and
pointer-to-counsel material.
</HARD-RULE>

<HARD-RULE id="HR-2">
**No legal / tax / incorporation / employment-classification / regulated-industry advice.** Same
reasoning — LLMs are dangerously wrong on jurisdiction-specific law and cause real damage. REFUSE
with:
> "I can't advise on [legal / tax / incorporation / employment classification / regulatory
> compliance]. These are jurisdiction-specific and require a human professional in [geography].
> I can help you prepare the questions to ask them."
Then offer to route to `founder/references/legal-questions.md`.
</HARD-RULE>

<HARD-RULE id="HR-3">
**TAM, SAM, SOM only in calculator mode with user-supplied inputs.** LLMs hallucinate market
sizes at scale. REFUSE LLM-generated market sizes. If a user asks "what's my TAM", respond:
> "I don't generate TAM numbers — LLMs hallucinate market sizes and you can't build a business on
> fabricated data. What I CAN do: walk through a TAM/SAM/SOM calculation with YOUR inputs. Tell me
> (1) average revenue per customer, (2) number of reachable customers in a named segment, (3)
> penetration assumption and why. I'll show the arithmetic and the assumption table so you can
> defend it later."
Then run the calculator with the user's numbers. Never invent the numbers.
</HARD-RULE>

<HARD-RULE id="HR-4">
**Every generated idea MUST carry kill criteria + first experiment.** The
`adversarial-team-brainstorm` primitive enforces this in `founder-ideation`. The parent does not
accept any subskill output that lacks them. Refuse to route an idea forward (to validation, GTM,
etc.) until both fields are populated.
</HARD-RULE>

<HARD-RULE id="HR-5">
**Every idea MUST cite a real data source.** Reddit (subreddit + post date), GDELT (event id),
or user-supplied input. No LLM-vs-LLM ungrounded speculation. `founder-ideation` enforces this
in its output validator; the parent enforces it on forward routing.
</HARD-RULE>

<HARD-RULE id="HR-6">
**Contract boundary: founder is pre-execution; forge is execution.** Never recurse. If the user
says "build it now", hand off to forge via the Scope→Launch gate with a structured `forge_brief`
(see `references/forge-handshake.md`). Do NOT design architecture in founder. Do NOT write code.
Forge owns execution; founder owns the pre-execution journey.
</HARD-RULE>

<HARD-RULE id="HR-7">
**Venture state lives in `.founder/venture-brief.yaml`. All subskills read on entry, write on
exit.** Schema documented in `references/venture-brief-schema.md`. Readers validate structurally
on load (required keys present, enums in valid set, schema_version matches). No external validator
binary required in Phase 1. Phase 2 may add a `yq`-based helper if drift becomes a real issue.
Readers that find a schema mismatch must emit a clear error and refuse to proceed, not silently
migrate.
</HARD-RULE>

<HARD-RULE id="HR-8">
**Intake required before routing.** Parent refuses to route without biz_type + stage + motion +
geography captured. Even for "quick" requests. A "quick ideas for accountants" request requires
at minimum: biz_type, geography, and the user's assets (if asset-first team is going to run).
See Minimum-Viable Intake below.
</HARD-RULE>

<HARD-RULE id="HR-9">
**Physical-world bridge preferred over simulation when available.** For Phase 1, the "physical-world
bridge" IS the Reddit + GDELT data grounding in `founder-ideation`. Browser MCP outreach
(draft + send + read analytics) is Phase 2 `founder-validation` territory. Do NOT attempt to wire
browser MCP into Phase 1 ideation. Phase 2 will add it when `founder-validation` ships.
</HARD-RULE>

<HARD-RULE id="HR-10">
**"I don't know" and "needs human review" are first-class outputs.** All subskills preserve these.
Arbiter synthesis doesn't hide uncertainty. Never fabricate confidence the data doesn't support.
</HARD-RULE>

<HARD-RULE id="HR-11">
**Reddit `example_quotes` must be paraphrased or truncated for privacy.** Enforced upstream in
`reddit-signal-mining/references/ethics-and-ratelimits.md`. The parent re-enforces by refusing to
display raw verbatim Reddit content with identifying details when presenting ideation output to
the user.
</HARD-RULE>

---

## Routing Table

| User intent | Route to |
|---|---|
| "Generate N ideas for X" / "business ideas generator" / "what should I build" / brainstorm | `founder-ideation` with `generate_ideas` mode |
| "I have this idea, attack it" / "is my idea good" / "validate this" | `founder-ideation` with `evaluate_idea` mode (Phase 1) or `founder-validation` (Phase 2) |
| "What underserved niches in X" / niche discovery | `founder-ideation` with `find_niches` mode |
| "What's hot in Y right now" | `founder-ideation` with `heat_check` mode |
| Deep-tech / hardware / invention / patent / "I built a thing in my garage" | `founder-ideation` with `deep_tech_mode: true` flag |
| Unit economics, pricing, revenue model, "what should I charge", contribution margin | `founder-business-model` with appropriate mode (unit_economics, pricing_explorer, what_must_be_true, scenario_table) |
| Validate my idea, design experiment, interview script, capture evidence, assumption review | `founder-validation` with appropriate mode (design_experiment, draft_interview, capture_evidence, read_analytics, evidence_review) |
| "Run a sprint", "what stage am I at", "what's next", "am I ready to build", stage check | `founder-sprint` — manages Diagnose -> Evidence -> Decision -> Handoff gates |
| Positioning, channels, go-to-market | `founder-gtm` — Phase 3 — soft fail with clear explanation + offer to prepare inputs |
| "Build me an MVP" / "Design the architecture" | Hand off to `forge` via Scope→Launch artifact (see `references/forge-handshake.md`) |
| Pitch deck | Hand off to `presentation-builder` with `yc-pitch` or `sequoia-pitch` flow, pass `venture-brief.yaml` |
| Landing copy / conversion | Hand off to `content-writer` + `conversion-psychology` |
| SEO / organic distribution | Hand off to `seo-*` family |
| Webstore operator (separate venture) | Hand off to `entrepreneur-webstore` |
| "Should I leave my job to start this" | Hand off to `career-transition` |
| Legal / tax / incorporation / valuation / securities | **REFUSE** (HR-1, HR-2) |
| "What's my TAM" without user inputs | **REFUSE** (HR-3) — offer calculator mode with explicit inputs |

**Routing discipline:** If multiple subskills could apply, ask one clarifying question before
routing. Do NOT default to ideation for every ambiguous request.

---

## Intake

### Minimum-Viable Intake (MVI) — required before ANY routing

For lightweight requests (user says "just give me ideas"), capture minimum:
1. **biz_type** — software / service / marketplace / hardware / deep-tech / physical-retail / other
2. **geography** — country or region (affects what we refuse to advise on, not what we advise)
3. **niche** — specific target market ("small accounting firms" not "businesses")

If ANY of these is missing, refuse to route with:
> "I need a bit more context before generating ideas. Quickly: (1) software / service / marketplace
> / hardware / deep-tech / retail? (2) what country or region? (3) what specific niche — not
> 'businesses' but 'small accounting firms in the UK' or similar?"

### Full Intake — for substantive work (validation, business model, sprint)

When the user is going deeper than one-off ideation, capture:
1. biz_type (above)
2. stage — pre-idea / idea-forming / validating / post-validation / building / scaling
3. motion — B2B / B2C / B2B2C / creator / community / gov-regulated
4. geography (above)
5. runway — solo-bootstrap / small-team / funded / enterprise-spinoff
6. intent — ideation / validation / business-model / gtm / "I don't know where I am"
7. user assets — existing skills, network, distribution, unique access (for asset-first team input)
8. stated constraints — time, capital, legal (jurisdiction), reputational

Intake results populate `.founder/venture-brief.yaml` immediately. See
`references/venture-brief-schema.md` for the schema.

### Intake fatigue guard (R10 risk mitigation)

Users get frustrated with intake. Three-strike guard:
- **First request:** full MVI. Refuse to proceed without it.
- **Second request (same session):** MVI loaded from `venture-brief.yaml`. Skip questions. Just
  confirm: "Using your earlier context: software / UK / accounting firms. Still right?"
- **Third request (same session):** silent load. No confirmation. Just run.

Never ask the same intake question twice in one session unless the user explicitly changes context
("actually, let me think B2C instead").

---

## Venture Brief (`.founder/venture-brief.yaml`)

The canonical venture state file. Persisted at project root by default (`<cwd>/.founder/`). All
subskills read it on entry, write on exit.

See `references/venture-brief-schema.md` for the complete schema with field-by-field semantics.

Schema version: `2` (Phase 2). Readers validate: required keys present, enums in valid set,
schema_version matches. On mismatch, readers emit a clear error and refuse to proceed. Phase 1
briefs (v1) are forward-compatible -- new fields default to null; Phase 1 `forge_brief` stub
fields (`constraints`, `ruled_out_approaches`) are superseded by Phase 2 fields
(`success_criteria`, `non_goals`, `complexity_hint`, `open_questions`).

**Location:** project root `.founder/` by default. Alternative: user home `~/.founder/` for
cross-project. Per-venture `ventures/<slug>/.founder/` is supported via explicit flag. Proposal
is project-root default; user may override in the intake.

---

## Gap Detection

Before routing to a child skill:
1. Verify the target subskill exists (check `~/.claude/skills/<path>`)
2. If missing AND it's a Phase 3 subskill (e.g., `founder-gtm`): soft-fail with a clear explanation:
   > "That request maps to `founder-gtm`, which is planned for Phase 3. For now, I can do
   > [X] — would that help? Or I can route to `content-writer` + `conversion-psychology` for
   > landing copy, or `seo-*` for distribution strategy."
3. If missing AND it's NOT a Phase 3 subskill (truly unknown): follow gap-detection protocol at
   `~/.claude/skills/research-for-skills/gap-detection.md`

---

## Forge Handshake

When the user is ready to build and wants execution:

1. Confirm all required fields in `venture-brief.yaml` are populated (specifically: `ideas_considered[]`
   has a `status: validated` entry, `forge_brief` has been drafted)
2. Set `forge_handoff_ready: true`
3. Invoke `forge` with the `forge_brief` field as the problem statement
4. Stop. Do NOT design the architecture or write code. Forge owns execution.

**Phase 1 constraint:** The forge side of the handshake (forge reading venture-brief.yaml on
session start and treating `forge_handoff_ready: true` as a trust signal) is PHASE 2, not Phase 1.
Phase 1 ships the founder side of the contract in prose only. See `references/forge-handshake.md`.

See also the text patch applied to `forge/SKILL.md` in WP-F6: forge now mentions "route to founder
first for pre-execution intent" in its clarifying-questions step and its Red Flags.

---

## Reference Files

Read these as needed:

- `references/fundraising-literacy.md` — pointers to human counsel, questions to ask venture
  lawyers / CFOs, NO actual advice (HR-1)
- `references/legal-questions.md` — trigger list for legal / tax / regulatory questions,
  handoff protocol to human professionals (HR-2)
- `references/venture-brief-schema.md` — complete YAML schema with field semantics, version
  migration notes, validation rules
- `references/forge-handshake.md` — the Scope→Launch handoff contract between founder and forge,
  with the Phase 1 vs Phase 2 split

---

## Cross-Cutting Principles

These apply to ALL founder family interactions regardless of subskill:

### Grounded, not guru
Every idea, every validation claim, every market observation must cite a real source. If you can't
cite, you can't claim. Default: "I don't know, let me mine some data."

### Kill criteria or bust
Every idea carries kill criteria + first experiment. An idea without an exit condition is a prayer.
`adversarial-team-brainstorm` enforces this in `founder-ideation`, and the parent refuses to route
forward without them.

### Adversarial by construction
Generic startup advice is the enemy. The adversarial team primitive exists because LLM-vs-LLM
design produces polished consensus — the one failure mode we're specifically trying to avoid.
Every major output goes through cross-fire.

### Epistemic honesty as first-class output
"I don't know" and "this needs human review" are valid — and preferred — over false confidence.
HR-10 preserves these in arbiter synthesis.

### Handoff, don't duplicate
Execution goes to forge. Pitch decks go to presentation-builder. Landing copy goes to
content-writer + conversion-psychology. Founder is a router, not a universal replacement.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Answering a valuation / cap-table / legal question "just this once" | Creates liability exposure, propagates dangerous misinformation, trains user to rely on LLMs for high-stakes legal decisions | Refuse (HR-1, HR-2). Offer question-prep lists and pointer to human counsel. Never hedge with "I'm not a lawyer but..." — that's the same failure with a fig leaf. |
| Generating TAM numbers from LLM knowledge | All LLM TAM estimates are ungrounded; they look specific but are fabrications | Refuse LLM-generated TAM (HR-3). Calculator mode only — user supplies inputs, skill shows the arithmetic + assumption table. |
| Running `generate_ideas` without MVI captured | Generic-guru output; ideas don't match user's actual context | Enforce MVI at the parent level; refuse to route without biz_type + geography + niche |
| Skipping `adversarial-team-brainstorm` for "simple" ideation | The primitive exists to defeat the polished-guru failure mode; skipping it defeats the founder family's reason for existing | Always use `adversarial-team-brainstorm` via `founder-ideation` for any `generate_ideas` / `evaluate_idea` / `find_niches` request |
| Designing the MVP inside founder | Duplicates forge's job, causes recursion when handoff happens | Stop at Scope→Launch. Hand off to forge. Founder owns PRE-execution, forge owns execution. |
| Ignoring `.founder/venture-brief.yaml` on subskill re-entry | Silently re-derives the company, loses decisions, confuses the user | Every subskill reads on entry, writes on exit (HR-7). Parent verifies the file exists after any subskill call. |
| Returning verbatim Reddit quotes with identifying details | Privacy violation, HR-11 breach, ToS breach | Enforce paraphrase-first at `reddit-signal-mining` level; parent re-filters before displaying to user |
| Hand-waving the forge handshake ("just tell forge to build it") | Loses the structured `forge_brief`, forge has to re-derive context, wastes user time | Populate `forge_brief` fully, set `forge_handoff_ready: true`, invoke forge with the brief as problem statement |

---

## When NOT to Use This Skill

- **Career questions** — "should I leave my job" → `career-transition`, `career-assessment`
- **Implementation / coding** — → `forge` directly (after founder has produced a validated idea)
- **A separate webstore venture** — → `entrepreneur-webstore`
- **Legal / tax / regulatory / securities** — REFUSED; human counsel only
- **Pure writing tasks** (blog posts, landing copy) without founder context → `content-writer`,
  `conversion-psychology`, `seo-*` directly
- **Pitch deck assembly when venture-brief is already validated** — → `presentation-builder`
  directly with the yc-pitch or sequoia-pitch flow (the founder family stubbed these in WP-F8)
- **"How do I build this feature" after execution has started** — → `forge`
