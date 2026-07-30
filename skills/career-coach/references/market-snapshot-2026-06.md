# Hiring-Market Snapshot — captured 2026-06

REVIEW-BY: 2027-01 (purge/refresh point — re-verify or delete every row)
Tags per row: [AS_OF] [CONFIDENCE: VERIFIED|LIKELY|CONTESTED] [SOURCE_TYPE: survey|platform|academic|vendor|press]

> **The single home for ALL volatile statistics cited by the `career-*` family.** SKILL.md bodies carry the qualitative claim plus a pointer here; the numbers live in this file. One purge point for the 2027 refresh. Inline exceptions in SKILL.md bodies are evergreen craft norms only (e.g., "150–200 words", "pin 6 repos", "~70% of bullets quantified").

---

## ATS & Screening

- **ATS 2.0 — semantic matching.** Mainstream ATS moved to LLM vector-embedding semantic matching in late 2025; keyword density now *lowers* match scores rather than raising them. Market consolidating around a few suites (Workday, Paradox-style conversational screeners). [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: vendor]
- **The "75% auto-reject" myth.** The claim that ATS auto-rejects ~75% of resumes is a debunked 2012-era marketing figure. Real automatic knockouts are eligibility gates (work authorization, hard requirements), not content scoring. Content-based auto-reject is small — on the order of ~8%. [AS_OF: 2026-06] [CONFIDENCE: VERIFIED] [SOURCE_TYPE: press]
- **Recruiter AI-perception.** Recruiters report *perceiving* AI authorship in roughly 76–91% of applications, via human heuristics (not detector tools); ~88% say they "can tell"; the "decides in ~20 seconds" claim recurs in surveys. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]
- **Regulated-industry auto-reject of obvious AI.** ~20% of employers (concentrated in regulated industries) auto-reject applications that read as obviously AI-generated. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]
- **AI-assisted acceptance.** ~63% of employers accept AI-assisted-but-customized applications; ~80% reject *obvious* unedited AI output. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]
- **Detector accuracy / false positives.** No public AI-text detector reliably scores ≥90% on real-world CVs; false-positive rates on genuine human writing run ~5–15%, rising to ~61% for non-native-English writers in academic settings. [AS_OF: 2026-06] [CONFIDENCE: VERIFIED] [SOURCE_TYPE: academic] (Liang et al., arXiv 2304.02819)
- **Footprint screening.** ~86% of employers review candidates' public online footprint; dedicated screening tools exist (e.g., Fama, Checkr, Phyllo) and the social-screening industry is sizeable. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]

## Interviews & Assessment

- **AI interviews tripled.** Share of processes using AI / one-way video interviews rose from ~10% (2023) to ~34% (Aug-2025). [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]
- **Agentic screening.** ~68% of organizations report using some agentic/automated screening step in the funnel. [AS_OF: 2026-06] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: survey]
- **Performance-review cadence.** Most large organisations now run mid-year or quarterly conversations alongside or instead of a single annual appraisal; Gartner-attributed figures put HR leaders supplementing/replacing annual reviews at >70%. [AS_OF: 2026-07] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]
- **Internal talent marketplaces.** Eightfold-class platforms match employees to internal roles, gigs and mentoring by semantic/potential-based fit scoring rather than keywords; a vendor-reported deployment cites internal application rates up ~40% in the first quarter after launch. [AS_OF: 2026-07] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: vendor]
- **AI-leadership talent pool.** Search-firm estimates put the global pool who have led VP+ AI organisations, built teams of 50+, shipped production AI at scale AND operated at board level at fewer than ~2,000, mostly not actively looking. [AS_OF: 2026-07] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: vendor]
- **EU AI Act high-risk employment timing — CONTESTED.** Recruitment AI is high-risk under Annex III (CV screening, interview scoring, candidate assessment). Obligations were widely briefed for **2026-08-02** and have been reported as **deferred to 2027-12-02**; prohibited-practices provisions have applied since **2025-02-02** with no grace period. GDPR Art. 22 rights are in force regardless. **Re-verify before citing a date.** [AS_OF: 2026-07] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: press]
- **Skills-based hiring + work samples.** ~85% of employers report using skills-based hiring; live proctored work-samples are increasingly replacing unsupervised take-homes. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey] *(Implementer note: "skills-based hiring" is an industry term of art — quoted as a proper noun, not the family's "skill(s)" usage.)*

## Documents

- **Cover-letter read rates (CONTESTED).** Whether recruiters read cover letters is genuinely contested across surveys (ranges from "most skip them" to "majority still read for senior roles"); separately, ~81% report having rejected a candidate based on the cover letter. The asymmetry — low upside, real downside — is the durable takeaway. [AS_OF: 2026-06] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: survey]
- **CV format norms.** PDF is the safe default again (the mid-2020s "ATS can't read PDF" caution has largely reversed for semantic ATS); single-column, standard headers. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: vendor]

## Platforms & Findability

- **LinkedIn ranking.** LinkedIn feed/search is driven by an LLM ranking engine ("360Brew", LIKELY) over an Interest Graph; Saves and Sends are high-weight signals; carousels (documents) and newsletters are favored; AI-generated posts appear de-rewarded. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: platform]
- **AI-citation distribution.** Of citations in AI answer engines, a large share (~48%) trace to community platforms (Reddit, YouTube, forums); the majority of a person's authority signals (~85%) live off their own domain; fresh content is cited several times more often than stale (~3×). [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: vendor]
- **Platform landscape.** No single X successor: Bluesky skews developer/journalist; Threads has mainstream scale; X retains residual reach. Numbers shift fast — verify before relying. [AS_OF: 2026-06] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: platform]
- **GitHub recruiter signal.** Recruiters for technical roles weight deployed projects with live URLs and strong READMEs far above tutorial clones; an LLM-API project is increasingly expected. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]

## Macro Job Market

- **Application flood.** Total application volume is at record highs (the "~11,000 applications/minute" direction figure recurs in platform data); cold-application response rates are very low (~0.1–2%); the result is a "doom-loop" where flood drives more applications. Robert Half and similar series (Mar-2026) track the trend. [AS_OF: 2026-06] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: platform]
- **Referral math.** Referrals are ~7% of applications but convert to ~40% of hires; job-board share of hires has fallen (roughly 49% → ~24.6% over recent years); ~52% of successful applicants applied early in the posting window. [AS_OF: 2026-06] [CONFIDENCE: LIKELY] [SOURCE_TYPE: survey]
- **Entry-level (CONTESTED — both signals real).** Some series show entry-level hiring contracting (AI absorbing junior tasks); others show resilient demand in specific functions. Assess YOUR function's demand, not the headline. [AS_OF: 2026-06] [CONFIDENCE: CONTESTED] [SOURCE_TYPE: press]

## Compliance & Fairness

- **Automated-decision regulation.** California ADS (automated decision systems) employment rules took effect Oct-2025; documented screening-bias studies exist (Brookings; a University of Washington study found ~85.1% of cases favored certain name-associated groups; Stanford work on resume-screening bias). [AS_OF: 2026-06] [CONFIDENCE: VERIFIED] [SOURCE_TYPE: academic]
- **Regulated-employee public comms.** FINRA Rule 2210 (communications with the public), SEC personal-communications expectations for registered persons, MNPI/pre-clearance regimes, and firm social-media policies constrain what finance employees may post publicly. (Mechanism, not a statistic — see `career-online-presence/references/finance-confidentiality.md`.) [AS_OF: 2026-06] [CONFIDENCE: VERIFIED] [SOURCE_TYPE: press]

---

## How to cite this file from a SKILL.md

Qualitative claim + pointer. Example:

> "Referrals convert far better than cold applications — see `market-snapshot-2026-06.md` for current figures."

Do not copy the numerals into the SKILL.md body. When a row here is updated or deleted at the 2027-01 review, the pointing skills need no edit.
