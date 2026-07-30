---
name: career-online-presence
description: "Use when building or auditing an individual professional's online presence and findability — personal website (Person schema, canonical bio), GitHub portfolio, multi-platform social strategy (LinkedIn content cadence, X, Bluesky, Threads), newsletters (Substack), YouTube, AI people-search visibility (how ChatGPT, Perplexity, Gemini answer 'who is <name>'), and digital-footprint hygiene under employer screening. Includes a mandatory regulated-employee publishing check (finance/FINRA/MNPI). Trigger on - personal website, GitHub profile, online presence, personal brand online, be found by AI, Bluesky, Threads, Substack, newsletter strategy, digital footprint, what does ChatGPT say about me. Part of the career-* skill family; business/brand E-E-A-T lives in seo-authority-builder; e-commerce AI visibility lives in ai-search-optimizer."
family: career
disambiguation: The public artefacts and their findability — personal site, Person schema, GitHub profile, what search returns. What message those artefacts should carry is career-positioning.
---

# Career Online Presence

Builds the **person-as-findable-entity**: how a specific professional shows up across their own site, GitHub, social platforms, newsletters, video, and AI people-search — and how their public footprint reads to an employer screening them.

**The discoverability stack:**
- **Canonical layer** — your personal website: the one source you control, schema-marked, that everything else points back to.
- **Distribution layer** — the platforms (LinkedIn, GitHub, Bluesky/Threads/X, Substack, YouTube) where you actually show up.
- **Authority-earned-off-site principle** — most of the signals that make AI engines and recruiters trust you live *off* your own domain (mentions, third-party corroboration). You build the canonical home, then earn the off-site signal.

---

## When NOT to Use

| The user actually wants… | Route to |
|---|---|
| Business / brand entity E-E-A-T, Knowledge Panel, company reputation | `seo-authority-builder` |
| Product / page / e-commerce AI-answer visibility (AEO) | `ai-search-optimizer` |
| LinkedIn *profile copy* and content *strategy* | `career-positioning` |
| Long-form drafting voice (the actual writing of a post/article) | `content-writer` + `human-voice-writing` |
| Application documents (CV, cover letter) | `career-application-writer` |

---

## HARD RULES

1. **Read the user profile first.** Read `~/.claude/skills/career-coach/references/user-profile.md` before any presence plan.
2. **Regulated-employee publishing check BEFORE any posting plan.** Before recommending *any* public posting, confirm the user's situation against the employer/regulatory surface: employer social-media / external-comms policy; FINRA Rule 2210 + SEC personal-communications rules if the user is a registered person; MNPI (material non-public information). Never advise posting client names, internal systems, proprietary architecture, performance/return claims, or investment advice; always disclose relevant affiliations. **When in doubt → compliance pre-clearance.** Full checklist in `references/finance-confidentiality.md`. This gate runs first and gates every later step.
3. **No fabricated credentials or projects.** Presence amplifies real work; it never invents a project, a title, or a contribution.
4. **Cross-platform consistency.** The footprint is screened — titles, dates, and claims across site / LinkedIn / GitHub / CV must agree (cross-check with `career-application-writer`).
5. **Privacy floor.** Deliberately separate personal and professional surfaces; be aware of doxxing surface (home address, family, schedule); remember "publish once, findable forever" — assume nothing is truly deletable.
6. **Terminology.** "Professional development / competency / capability / fluency", never "skill(s)" for the user's growth. *(Implementer note: GitHub/LinkedIn UI labels like the "Skills" section are quoted terms of art, not the family's competency usage.)*

---

## 1. Personal Website — the Canonical Entity Home

Your site is the one node you fully control. Make it the canonical entity:
- **Schema-marked** with JSON-LD `Person` + `sameAs` linking every profile you own (worked example in `references/person-schema.md`). This is what AI engines and search read to resolve "who is <name>".
- **Canonical bio** — one authoritative bio, reused verbatim across platforms (consistency is itself a trust signal).
- **Page model:** home/bio, portfolio/work, selected case studies, contact.
- **Freshness discipline** — stale pages lose AI citations over time (fresh content is cited more often — see `market-snapshot-2026-06.md`). Update on a realistic cadence rather than building once and abandoning.

## 2. GitHub Portfolio (technical roles)

- **Depth over count:** two deployed projects with live URLs and strong READMEs beat ten tutorial clones (recruiter weighting — see `market-snapshot-2026-06.md`).
- At least one **LLM-API project** is now an expected signal for many technical roles.
- **Pin 6 repos**; curate the profile README; keep commit history legible (a recruiter does a quick walkthrough, not a code review).
- The profile is read as a portfolio, not a code archive — front the work you want to be hired for.

## 3. Multi-Platform Social

- **No single X successor** — take a portfolio approach: Bluesky skews developer/journalist; Threads has mainstream scale; X retains residual reach (current standings shift fast — see `market-snapshot-2026-06.md`).
- **Pick 1–2 platforms by where your audience actually is; don't spray** across all of them.
- **Cadence realism:** a sustainable rhythm you'll keep beats an ambitious one you'll abandon (the abandoned-feed effect is its own negative signal).
- **LinkedIn content mechanics stay in `career-positioning`** (360Brew ranking, the 5 content pillars, Saves/Sends) — this skill covers *off-LinkedIn* presence; point there for LinkedIn strategy.

## 4. Long-Form & Video

- **Newsletter (e.g. Substack):** doubles as distribution *and* search-indexed long-form that builds entity authority. Route the actual drafting to `content-writer` (and `human-voice-writing` for the voice pass) — this skill decides whether/where, not how it's written.
- **YouTube / community platforms:** a large share of AI-engine citations trace to community platforms (see `market-snapshot-2026-06.md`), so video and community participation can disproportionately help findability — if sustainable for the user.

## 5. AI People-Search Findability

The new discoverability question is "what does ChatGPT/Perplexity/Gemini say when someone asks about me?"
- **Monthly self-query protocol:** query the major answer engines for "who is <name>" and "<name> + <your domain>"; record what they say and what they get wrong.
- **Entity-recognition tracking sheet:** track, per engine, whether you're recognized, what sources they cite, and any errors.
- **Corrections strategy:** fix misattribution by *strengthening canonical sources and third-party corroboration* (the Person schema, consistent bios, a few authoritative mentions) — **entity hygiene over volume posting**. You can't out-post a wrong entity graph; you correct the graph.

## 6. Digital-Footprint Hygiene & Screening

- Employers check public footprints, and dedicated screening tools exist (see `market-snapshot-2026-06.md`).
- **Audit-your-own-footprint protocol:** search yourself the way a screener would; review old public posts, tagged content, and forum history; reconcile anything that contradicts your CV/LinkedIn.
- **Cleanup + consistency** beat volume — a clean, coherent footprint is the goal, not maximal output.

## 7. The 90-Day Presence Build (tiered by ROI, compliance-gated)

Run **HARD RULE 2 first** — every step below is gated on the regulated-employee check.

| Phase | Focus | Why first |
|---|---|---|
| Days 1–30 | Canonical site + Person schema; reconcile cross-platform consistency; footprint self-audit | The canonical layer is the foundation everything points to |
| Days 31–60 | Pick 1–2 distribution platforms; GitHub portfolio cleanup (pin 6, READMEs); set a sustainable cadence | Distribution only pays off once the canonical home exists |
| Days 61–90 | Long-form / newsletter if sustainable; first AI people-search self-query baseline; corrections pass | Authority and findability compound after the base is set |

Every recommendation in the plan re-checks the compliance gate before it suggests publishing anything.

---

## Output Artefacts

- Canonical bio + Person/sameAs schema block.
- A 1–2 platform distribution plan with a realistic cadence.
- GitHub portfolio cleanup checklist (tech roles).
- AI people-search tracking sheet + corrections plan.
- A compliance-gated 90-day build.

## Anti-Patterns

| Anti-Pattern | Why it fails | Correct approach |
|---|---|---|
| Posting more as a substitute for entity hygiene | Volume can't fix a wrong entity graph | Strengthen canonical sources + corroboration (§5) |
| Ignoring the employer comms policy | Compliance breach risk; career-ending in regulated roles | Run HARD RULE 2 + `finance-confidentiality.md` first |
| Abandoned-blog / dead-feed effect | A stale presence is a negative signal | Pick a cadence you can actually sustain |
| Spraying across every platform | Thin, inconsistent presence everywhere | Pick 1–2 where your audience is |
| Fabricated or inflated projects | Screened against your real footprint; integrity failure | Amplify real work only (HARD RULE 3) |
| Footprint that contradicts the CV | Screening tools flag the mismatch | Cross-document consistency (HARD RULE 4) |
