# The machine-mediated hiring funnel

<!-- REVIEW-BY: 2027-01-31 -->
**Captured 2026-07-29.** Shared reference for the `career-*` family. **Qualitative mechanics here;
every volatile number lives in `market-snapshot-2026-06.md`** with its own `AS_OF` tag.

Written because the family's AI-hiring guidance was correct but spread across three skills — semantic
ATS in `career-application-writer`, one-way screens in `career-storytelling` Framework 7, statistics
in the snapshot — with nothing stating the through-line: **a candidate can now pass through several
automated stages before any human reads anything.**

## 1. The stages, and what each one actually scores

| Stage | What it is | What it scores |
|---|---|---|
| **Sourcing / matching** | Semantic search over CV and profile databases | Similarity to a role vector — including adjacent skills |
| **Application screening (ATS 2.0)** | LLM embedding-based matching, not keyword counting | Whether your experience *means* what the role needs |
| **Conversational / agentic pre-screen** | Chat or voice agent asking qualifying questions | Eligibility gates, availability, salary, must-haves |
| **One-way / AI-scored interview** | Recorded answers, no interviewer present | Structured content of the answer; sometimes delivery |
| **Footprint screening** | Automated review of public online presence | Risk signals, consistency with your claims |
| **Internal talent matching** | Eightfold-class marketplaces inside an employer | Your internal skills profile vs internal openings |

**The stage that eliminates most people is the earliest one**, and it is the one with the least
feedback. Nobody tells you which stage you failed at.

## 2. What changed, and what it invalidates

**Keyword stuffing is now counterproductive, not merely useless.** Semantic matching scores meaning;
an unnaturally dense keyword block reads as a poor semantic match *and* as inauthentic. Advice to
"mirror the job description's keywords" is pre-2025 advice, and following it lowers the score it was
meant to raise.

**Write so the meaning is unambiguous instead**: real responsibilities, real scope, real outcomes,
in the vocabulary of the field rather than the vocabulary of the advert.

**The "ATS auto-rejects 75% of CVs" figure is a debunked 2012-era marketing claim.** Real automatic
knockouts are eligibility gates — work authorisation, hard requirements, salary bands — not content
scoring. **Optimise for the eligibility gates, which genuinely do reject automatically**, and stop
optimising against a filter that does not work the way the myth describes.

## 3. Working with each stage

**Application screening.** Say what you did, at what scale, with what result. Titles vary between
companies and semantic matching handles that better than a human skim — so describe the work, not
just the label. Include the label too, since some gates are literal.

**Conversational pre-screen.** Answer the qualifying question directly and first. These agents are
extracting fields, not appreciating nuance; a hedged answer to "do you have the right to work in X"
is a failed field, not a thoughtful reply.

**One-way / AI-scored interview.** Covered in depth in `career-storytelling` Framework 7. The two
that matter most: **say your numbers out loud** — the system is not reading your CV alongside your
answer — and **make each answer self-contained in 60–90 seconds**, because there is no follow-up
question coming.

**Footprint screening.** Assume your public presence is reviewed and checked against your claims.
Inconsistency between CV dates and a public profile is a common, avoidable flag. See
`career-online-presence`.

**Internal matching.** Your internal skills profile is now an input to a matching model, not an HR
record — `career-internal-visibility` §6.

## 4. Integrity — the line, and why it is where it is

**Practising with AI is fine and encouraged. Reading model-generated answers in a live or one-way
interview is misrepresentation**, and the family's rule is unchanged: rehearse with AI, answer as
yourself.

**Never coach toward defeating a detector.** AI-writing detectors are unreliable and demonstrably
biased, and building a strategy on fooling one is both unsound and pointless — recruiters report
*perceiving* AI authorship through their own heuristics far more often than through tools. **The
counter to "this reads as AI-written" is specificity only.** Details that could only come from your
actual experience are the thing no detector-gaming produces and no model invents.

**Your claims must survive a human conversation.** Everything automated is a filter toward a person
who will ask follow-ups.

## 5. Candidate rights — real now, and expanding

**GDPR Article 22 has been in force since 2018** and already gives people in scope rights around
decisions based solely on automated processing: to be informed, to obtain human intervention, to
contest the decision. **This is a live right, not a forthcoming one.**

**The EU AI Act classifies recruitment AI as high-risk** — Annex III covers CV screening, interview
scoring and candidate assessment — bringing obligations on risk management, bias testing, logging,
human oversight and disclosure to affected candidates and workers.

**On timing, sources disagree and the disagreement matters.** The high-risk employment obligations
were widely briefed for **2 August 2026**, and have been reported as **deferred to 2 December 2027**.
The *prohibited-practices* provisions have applied since **February 2025** with no grace period.
**Verify the current position before relying on a date** — this is the single most contested fact in
this file, and it is contested in the sources themselves.

Jurisdiction-specific rules also exist and bite earlier in places — for example New York City's
automated-employment-decision-tool bias-audit rule and California's automated-decision-systems
employment regulations.

**Practically, for a candidate:** you may ask whether automated tools were used, and you may ask for
human review. Whether it is *wise* in a given process is a judgement call — but it is a right, not a
favour, and it exists today under data-protection law regardless of where the AI Act timetable lands.

## 6. What has not changed

**Referral still beats the funnel.** A referral enters at a later stage, often bypassing automated
screening entirely, and it remains the highest-yield route by a wide margin. The rise of automated
screening has *increased* that advantage, because the volume it processes has grown.

**Human judgement still decides.** Automation filters; it does not hire. Every stage above narrows
toward a conversation with a person who wants to know whether you can do the work.

## 7. Anti-patterns

- **Keyword-stuffing for a semantic matcher**, which lowers the score.
- **Optimising against the 75% auto-reject myth** while ignoring real eligibility gates.
- **Hedging on a qualifying question** an extraction agent is treating as a field.
- **Assuming a one-way interview will ask a follow-up.**
- **Leaving your public footprint inconsistent** with your CV.
- **Coaching toward beating a detector** instead of writing with specificity.
- **Reading generated answers** in a live or recorded interview.
- **Citing an AI Act date without re-verifying it.**
- **Treating the funnel as the main route in** when referral outperforms it.
