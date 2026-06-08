---
name: career-application-writer
description: "Use when the user wants to write, draft, tailor, or review a CV, resume, cover letter, or job-application package — generates truthful, human-voiced application documents from the user's verified achievements, tailored to a specific posting, with semantic-ATS alignment (2026), a humanization pass against AI-slop patterns, and cross-document consistency checks (CV, cover letter, LinkedIn must agree). Trigger on - write my CV, tailor my resume, cover letter, application package, adapt my CV for this job, resume bullets, ATS check. Part of the career-* skill family; positioning strategy lives in career-positioning; raw achievement stories live in career-storytelling."
---

# Career Application Writer

Generates tailored, truthful, human-voiced application documents — CVs/résumés and cover letters — from the user's verified achievements, aligned to a specific posting and to semantic ATS (2026), via a six-stage gated pipeline.

**Family position.** `career-storytelling` owns achievement CONTENT (the raw quantified stories, the STAR bank). This skill owns document FORM (assembling those stories into a tailored CV and letter). `career-positioning` owns STRATEGY (what to emphasize, how you're seen). This skill is downstream of both.

---

## When NOT to Use

| The user actually wants… | Route to |
|---|---|
| Positioning strategy / what to emphasize / how am I seen | `career-positioning` |
| Raw STAR stories / quantifying an achievement / the achievement bank | `career-storytelling` |
| Online presence — website, GitHub, social, AI findability | `career-online-presence` |
| Humanize an existing non-career text (essay, blog, bio they own) | `human-voice-writing` |
| Salary negotiation / evaluating an offer | `career-transition` |

---

## HARD RULES

1. **Read the user profile first.** Read `~/.claude/skills/career-coach/references/user-profile.md` for stage, industry, specialization, and format defaults before drafting. If it doesn't match, ask before proceeding.
2. **NEVER fabricate.** Content comes ONLY from the user's verified achievement bank / confirmed facts. Gaps are flagged honestly as open questions — never filled with plausible invention. This is rule #1 of the writer for a reason.
3. **No detector-gaming.** Detectors are unreliable and biased (see `market-snapshot-2026-06.md`). Never optimize against a detector score; never frame output as "beating", "passing", or "fooling" any screen. The target is a truthful, specific, human-edited document that parses cleanly in ATS and reads as credible to a human reviewer.
4. **Voice belongs to the human.** Capture and render the user's actual register (`ai-tells-catalog.md` §Voice-Capture). Never impose a generic "human-sounding" template. **Preserve non-native-English register** — never force idioms, slang, or fake quirks onto a clean, slightly-formal authentic voice.
5. **One tailored document per application.** No single CV sprayed everywhere. Each output is fitted to one posting.
6. **Quantification bar.** Aim for ~70% of bullets quantified; lead with the outcome, then the tool ("cut break-investigation to <30 min by automating reconciliation", not "used Python to automate reconciliation").
7. **Cross-document consistency before output.** CV, cover letter, and LinkedIn must agree on titles, dates, and metrics — screening tools now machine-check this. Reconcile before emitting.
8. **Cold-start rule.** If no voice profile/sample exists: run the minimum capture, or label output "neutral register — not yet voiced". Never emit silent generic output as if it were the user's voice.
9. **Terminology.** "Professional development / competency / capability / fluency" — never "skill(s)" for the user's growth. Industry terms of art ("skills-based hiring", LinkedIn "Skills" section) are permitted only as quoted proper nouns. *(Implementer note: those two are quoted terms of art, not the family's competency usage.)*

---

## THE GENERATION WORKFLOW

Six gated stages. Each stage names its gate; do not advance past a gate that fails.

### Stage 0 — Intake
Gather three inputs:
- **Target posting** — pasted or described. (Required; without it you can only build a base CV, not a tailored one.)
- **Achievement source** — the `career-storytelling` STAR bank. If absent, run a *minimal* capture here (don't duplicate storytelling's full machinery — pull the 3–5 stories this posting needs and point the user to `career-storytelling` for the full bank).
- **Voice profile** — load it, or build it per `ai-tells-catalog.md` §Voice-Capture. **Cold-start rule applies** (HARD RULE 8).
- **Format target** — US résumé / UK–EU CV / banking-vertical CV (see `references/cv-format-variants.md`).

**Gate:** posting present (or user explicitly wants a base CV) AND a voice decision made (profiled, or cold-start-flagged).

### Stage 1 — Semantic-fit analysis (evidence ledger)
From the posting, extract: scorecard criteria, must-haves, implied business problems behind the requirements, and any knockout gates (eligibility, work authorization, hard requirements). Build a claim→evidence→strength→gap coverage matrix from the bank (template in `references/semantic-fit-worksheet.md`). **Expose gaps honestly as questions, not assumptions.**

**Gate:** every must-have is mapped to either real evidence or an explicit open gap. No gap silently filled.

### Stage 2 — Draft in captured voice
Select and order achievements by fit to the scorecard. Render bullets in SOAR form (Situation-Opportunity-Action-Result) in the user's register. Assemble per the chosen format variant.

**Gate:** every bullet traces to a bank item; ordering reflects the scorecard, not chronology-by-default.

### Stage 3 — Humanization pass
Run the `ai-tells-catalog.md` checklist: restore burstiness, thin the focal-word cluster, break parallelism/tricolons, inject true lived specifics. **Edit toward the user's captured voice, NOT toward maximal anti-pattern compliance** (the over-humanization paradox — stilted "de-AI'd" text is its own tell; the cluster-not-blocklist caveat applies).

**Gate:** reads aloud as the author; no mechanical word-swapping; specifics are all true.

### Stage 4 — Consistency + integrity gate
CV ↔ cover letter ↔ LinkedIn agree on titles, dates, metrics. Every claim traces to the bank. Run the banned-phrase self-check — no detector-gaming or screen-defeating framing anywhere in the output or the rationale (the document parses cleanly in ATS and reads as credible because it is truthful and specific, not because it games a screen).

**Gate:** zero cross-document disagreements; zero unbacked claims; zero banned framing.

### Stage 5 — Output with rationale
Emit: the document(s), a short "why these choices" (which scorecard criteria each section targets), the unresolved evidence questions (so the user can close real gaps), and the tailoring rationale.

**Gate:** rationale and open-questions list accompany every deliverable.

---

## CV / Résumé Construction

- **Layout:** single-column, standard section headers (semantic ATS parses these reliably; creative multi-column layouts confuse extraction).
- **Format default:** PDF (the older "ATS can't read PDF" caution has largely reversed — see `market-snapshot-2026-06.md`); DOCX on request.
- **Length by tenure:** 1 page for 0–5 yr; 1–2 pages for 5–15 yr; 2–3 pages for 15 yr+.
- **Quantification:** ~70% of bullets carry a number or a concrete outcome; outcome before tool.
- **Competency section placed high** and mapped to the posting's scorecard criteria first — semantic ATS rewards concept/criterion alignment, not keyword repetition. *(Implementer note: the section is conventionally labelled "Skills" on a résumé — a quoted UI term of art, not the family's competency usage.)*
- **Links:** LinkedIn, GitHub, portfolio — include where relevant to the role (tech roles especially).

## Cover-Letter Construction

- **Length:** 150–200 words, ≤ half a page.
- **Four beats:** hook / fit / why-this-company / CTA (full template in `references/cover-letter-patterns.md`).
- **Minimum payload:** 1 specific current company detail + 1 quantified result + 1 lived anecdote.
- **Asymmetric-downside framing:** the letter is *never the deciding asset and never sloppy*. Read-rates are contested but rejection-on-the-letter is real (see `market-snapshot-2026-06.md`) — treat it as downside-protection, not a winning play.
- **When to skip:** explicitly-optional postings; internal moves where the narrative already lives elsewhere.

## Semantic ATS (ATS 2.0)

- **How matching works now:** LLM vector-embedding semantic matching, not keyword counting. The system scores conceptual fit between your document and the posting.
- **Stuffing is penalized:** repeating keywords *lowers* scores (see `market-snapshot-2026-06.md`). Express the concept and its natural synonyms once, in real sentences.
- **The 75% myth:** "ATS auto-rejects 75% of resumes" is a debunked 2012 figure (snapshot). The real automated filter is the *knockout gate* (eligibility / hard requirements), distinct from content scoring — and the real bottleneck is human time under the application flood.
- **Knockout vs content:** answer eligibility/knockout questions truthfully and completely (these are pass/fail); then write content for the human who reads the shortlist.

## Banking / Regulated Vertical — Worked Example

*(Vertical example — the family's first-class worked vertical. A generalist example sits beside it for contrast.)*

**Banking CV bullets (committee language — revenue / risk / controls / compliance):**
- "Owned the post-trade reconciliation platform across three trading desks; cut daily manual break-investigation from ~4 hrs to under 30 min and closed two repeat internal-audit findings."
- "Led the model-risk evidencing workstream for an automated surveillance control; passed second-line review with no remediation actions."

**Banking cover-letter excerpt:** "Your posting calls for someone who can make controls auditable, not just automated — that's the line I've worked. On the surveillance platform I rebuilt last year, I cut false-positive alerts by roughly a third while keeping a clean second-line review, which is the balance your team description keeps coming back to."

**Generalist CV bullet (for contrast):** "Got the support and engineering teams onto one weekly triage call; ticket reopen-rate fell by about a third over the quarter."

---

## Output Artefacts

- Tailored CV (PDF default) and/or cover letter in the user's voice.
- "Why these choices" rationale mapped to the scorecard.
- Unresolved evidence questions (real gaps to close).
- The coverage matrix (so the user can reuse it for the next application).

## Anti-Patterns

| Anti-Pattern | Why it fails | Correct approach |
|---|---|---|
| Submitting raw model output verbatim | Reads as generic slop; recruiters perceive it; integrity risk | Run Stages 3–4; edit to the user's voice; verify every fact |
| Keyword-stuffing for "ATS" | Stuffing *lowers* semantic-ATS scores | Express concepts naturally once; map to scorecard criteria |
| Same CV everywhere | Ignores the posting's scorecard; loses fit | One tailored document per application (HARD RULE 5) |
| Letter that restates the CV | Wastes the one beat that adds something | Letter carries the why-this-company + lived anecdote the CV can't |
| Filling a gap with a plausible claim | Fabrication — instant integrity failure | Flag the gap as an open question (HARD RULE 2) |
| Over-humanizing into stilted prose | The "de-AI'd" tell; new detectable pattern | Anchor to captured voice; cluster-not-blocklist (Stage 3) |
