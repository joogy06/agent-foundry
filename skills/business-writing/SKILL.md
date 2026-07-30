---
name: business-writing
description: "Use when writing anything at work that needs a reader to decide, approve, act or understand — emails, Teams and Slack messages, one-pagers, proposals, status updates, executive summaries, slide text and meeting requests. Covers leading with the outcome rather than the chronology, naming the ask, the so-what test, structure for skim-readers, subject and first lines, delivering bad news, register by audience, and cutting to length without losing the point."
disambiguation: "The WRITING itself, across every workplace surface — structure, order, concision, tone, the ask. Deck narrative and slide design are presentation-narrative and presentation-styling; blog and editorial content is content-writer; condensing something that already exists is summarize; removing AI-typical patterns from a draft you own is human-voice-writing; getting the finished thing in front of the decision-maker is career-advocacy."
---

# Business writing — outcome first

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.**

**Load the user's recorded preferences before drafting** — register, formatting and house style are
already captured per domain:

```bash
python3 ~/.claude/skills/user-preferences/scripts/prefs.py load email          # or presentations, tone
```

A live instruction always overrides a stored preference.

## 1. The one rule

**Lead with the outcome. Not the background, not the chronology, not the process.**

Most workplace writing is assembled in the order the work happened — context, then what we tried,
then what we found, then what it means. **Readers consume in the opposite order and most stop early.**
Senior readers skim, and they skim from the top.

```
✗  "Following the review we began in March, we assessed four vendors against
    the criteria agreed with the working group, and after testing..."

✓  "Recommend we go with Vendor B. £40k cheaper over three years and the only
    one that meets the retention requirement. Decision needed by 14 Aug.

    Detail below."
```

**BLUF — bottom line up front.** Answer first, then the reasoning that supports it, then the evidence
that supports *that*. Someone who stops after one paragraph should still have the thing you needed
them to know.

**The honest caveat: brevity can cut something load-bearing.** BLUF is not "make it short" — it is
"put the conclusion first". A risk, a caveat or a dependency the reader must act on belongs *above*
the fold, not sacrificed to it.

## 2. Decide what you want before you write a word

**Every piece of workplace writing has exactly one of four jobs.** Naming it first is what makes the
draft write itself:

| Job | The reader should finish and… |
|---|---|
| **Decide** | Know the options, your recommendation, and by when |
| **Approve** | Know the cost, the risk, and what they are signing |
| **Act** | Know exactly what to do, and by when |
| **Be informed** | Know what changed and whether it affects them |

**If you cannot name the job, do not send it yet** — that is the actual reason a draft feels wrong.

**Then write the ask as a sentence, not an implication.** "Let me know your thoughts" converts to
nothing, because nobody knows what agreeing looks like. "Can you approve the £12k by Friday so we
can order?" does.

**Where an ask is buried at the end, the reader who skims never reaches it** — and skimming is the
normal case, not the rude one.

## 3. Structure that survives a skim

Answer → because → evidence. Each layer supports the one above it, and each is optional to the reader.

- **First sentence carries the message.** Not a greeting, not context-setting. If someone reads only
  that line, what must they know?
- **One idea per paragraph**, with the point in the first sentence of each.
- **Bold the two or three things that must not be missed** — and no more, because bolding everything
  bolds nothing.
- **Bullets for parallel items, prose for reasoning.** A bulleted argument loses the connective
  tissue that made it an argument.
- **Put detail below a clear break** — "Detail follows", an appendix, a linked doc. That protects the
  skim-reader without starving the person who needs the specifics.
- **Assume a phone screen.** Long paragraphs are a wall; three lines is a paragraph.

## 4. Per surface — what changes, and what does not

The lead-with-the-outcome rule never changes. Length and formality do.

| Surface | Shape |
|---|---|
| **Email** | Subject carries the message. Ask in the first two lines. Detail beneath a break |
| **Teams / Slack** | One message, not five. Ask up front. Thread the detail rather than the channel |
| **Status update** | What changed · what it means · what you need. Never a task list |
| **One-pager** | Problem · recommendation · options considered · cost and risk · the ask · timeline |
| **Proposal** | As above plus what happens if we do nothing, which is the question that gets asked |
| **Exec summary** | Standalone. Must work for someone who reads nothing else — and many will not |
| **Slide text** | Headline states the *finding*, not the topic. "Costs rose 12% in Q3", not "Q3 costs" |
| **Meeting request** | Purpose, decision required, pre-read, who must attend and why |

**The subject line is the only text guaranteed to be read.** Make it the message:
`Approval needed: Vendor B, £12k, by Fri 14th` beats `Vendor update`. Front-load it — mobile
notifications truncate at around forty characters.

**On chat: the "hello, are you free?" opener wastes a round-trip.** Ask in the first message.

## 5. The so-what test

**Every paragraph must answer: so what, for this reader?** Anything that fails is your interest, not
theirs — process detail, how hard the work was, who was in which meeting.

- **Numbers, not adjectives.** "Significantly improved" is unquotable; "cut from 6 days to 2" travels
  and survives being repeated by someone else.
- **Translate into their currency.** Engineers hear latency, finance hears cost, risk hears exposure,
  executives hear revenue and reputation. **The same fact needs different units per audience.**
- **Cut hedging.** "It may be worth potentially considering whether we might" is one word: "Should".
  Hedging reads as either lack of confidence or lack of a view — neither is what you meant.
- **Say the thing.** If the project is late, "the project is late" outperforms every softer phrasing,
  and the softer phrasings are transparent anyway.

## 6. Bad news and risk

**Lead with it. Burying bad news is the single most damaging habit in workplace writing**, because
the reader discovers it later, usually from someone else, and now the concealment is the story.

Order: **what happened · impact · what you are doing · what you need · when you will next update.**

- **Own it without over-apologising.** One sentence of accountability, then the plan. Extended
  apology shifts the reader's attention to managing your feelings.
- **Do not stack qualifiers around a risk.** A risk hedged into vagueness is a risk you have
  technically disclosed and functionally hidden — and that distinction gets tested afterwards.
- **Give a date for the next update**, even when there is nothing to report yet. Silence is read as
  deterioration.

## 7. Register

**Match the reader, not the org chart.** Peers, senior stakeholders and external clients need
different formality; none of them need jargon.

- **Plain English wins at every level**, and most reliably at the top. Dense internal jargon is
  invisible to precisely the audience that decides things.
- **Expand an acronym on first use**, always. The cost is four words; the cost of not doing it is a
  reader who quietly disengages.
- **Warmth is not padding.** One human line is worth keeping; three paragraphs of preamble are not.
- **Read it aloud.** If you would not say it, do not send it — that single check removes most of what
  makes business writing bad.

**If a draft reads as AI-written, the fix is specificity, not vocabulary** — details only you could
know. See `human-voice-writing`.

## 8. Cutting

**Write it, then cut a third.** Nearly every first draft carries a third it does not need.

Cut first, in this order: throat-clearing openings · restating the question · process narration ·
anything the reader already knows · adverbs · sentences that only introduce the next sentence.

**If it will not fit, the problem is usually that you have not decided what you are asking for** (§2).
Length is a symptom.

## 9. Anti-patterns

- **Chronology before conclusion** — the default failure.
- **Not naming the job** the writing has to do.
- **An implied ask** — "let me know your thoughts".
- **The ask at the bottom**, where a skim-reader never reaches it.
- **Confusing BLUF with brevity**, and cutting a load-bearing risk.
- **Subject lines that name a topic** instead of carrying the message.
- **"Hi, are you free?"** as a standalone chat message.
- **Status updates that are task lists** with no "so what".
- **Adjectives where numbers exist.**
- **Hedging stacked around a real risk.**
- **Burying bad news**, then being asked why it was buried.
- **Bolding everything.**
- **Bulleted arguments** that lose the reasoning between the points.
- **Unexpanded acronyms.**
- **Sending the first draft** without cutting a third.
