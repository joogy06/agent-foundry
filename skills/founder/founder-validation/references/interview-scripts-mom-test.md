# Interview Scripts — Mom Test Protocol

Reference for drafting customer discovery interviews. Based on Rob Fitzpatrick's "The Mom Test"
methodology: talk about their life, not your idea; ask about the past, not the future; listen
more than you talk.

---

## The Three Rules of the Mom Test

1. **Talk about their life, not your idea.** You are not pitching. You are extracting. If you
   mention your product, the conversation becomes about their politeness, not your market.

2. **Ask about specifics in the past, not generics or opinions about the future.** "Would you
   use a tool that does X?" is worthless. "Tell me about the last time you dealt with X" is gold.
   Past behavior predicts future behavior; stated intent does not.

3. **Talk less, listen more.** If you are talking more than 30% of the time, you are pitching,
   not interviewing. Let them fill the silence. The uncomfortable pauses are where the insights
   live.

---

## Question Templates by Assumption Category

### Problem Assumptions ("Does the pain exist?")

```
WARM-UP:
1. "Tell me about your typical [workflow / day / process for X]."
2. "What's the most annoying part of [relevant activity]?"

CORE:
3. "Tell me about the last time you dealt with [problem area]. Walk me through it."
   - Follow-up: "How long did that take?"
   - Follow-up: "How often does that happen?"
   - Red flag: Can't recall a specific instance (pain may not be real)
   - Green flag: Describes in vivid detail with frustration

4. "What do you currently do to solve [problem]?"
   - Follow-up: "How well does that work?"
   - Follow-up: "What's the biggest limitation?"
   - Red flag: "I don't really think about it" (low-priority pain)
   - Green flag: Describes a workaround they've built (strong behavioral signal)

5. "Have you tried any tools or services to address this?"
   - Follow-up: "What did you try? What happened?"
   - Follow-up: "Why did you stop using it?" (if applicable)
   - Red flag: "I haven't really looked" (low motivation)
   - Green flag: Has tried multiple things and is still unsatisfied

6. "If you could wave a magic wand and fix one thing about [process], what would it be?"
   - Follow-up: "Why that specifically?"
   - Red flag: Lists a different problem than the one you're testing
   - Green flag: Describes your problem area unprompted

7. "How much time/money do you spend dealing with this currently?"
   - Follow-up: "Is that a problem worth solving, or just an annoyance?"
   - Red flag: "A few minutes" / "not much" (low severity)
   - Green flag: Can quantify significant time/money cost

CLOSING:
8. "Is there anyone else who deals with this problem that I should talk to?"
   - Green flag: Enthusiastic referral (they care enough to help you find others)
   - Red flag: "Not really" (isolated problem or they don't care enough to help)

9. "If someone built a solution for this, what would have to be true for you to switch?"
   - Follow-up: "What would stop you from switching?"
   - THIS IS THE MONEY QUESTION — listen for switching costs and barriers
```

### Solution Assumptions ("Does my approach work?")

```
CORE:
1. "Currently, how do you handle [specific step in the workflow]?"
2. "If this step took 10 minutes instead of [current time], what would change for you?"
3. "What would you lose if this step was automated?" (tests for hidden value in manual process)
4. "Who else in your organization would need to be involved in adopting a new tool for this?"
   - Red flag: "I'd need to get IT/compliance/my boss to approve" (buying friction)
   - Green flag: "I can try new tools on my own" (low friction adoption)

5. "Can you show me how you do this right now?" (if possible — observe, don't just listen)
```

### Pricing Assumptions ("Will they pay?")

```
CORE:
1. "How much are you spending on [current solution/workaround] right now?"
2. "If a tool saved you [X hours/month], what would that be worth to your practice?"
3. "At what price would you say 'this is a no-brainer'?"
4. "At what price would you say 'too expensive, I'll stick with my current approach'?"
   - NEVER say "would you pay $X?" — they'll say yes to be polite
   - Red flag: Cannot articulate any willingness to pay
   - Green flag: Names a specific budget they have for tools in this category
```

---

## Red Flag Answers (Fake Validation Signals)

These answers feel positive but are NOT evidence (HR-V1):

| What they say | What it means | What to do |
|---|---|---|
| "That sounds great!" | They're being polite | Ask: "When was the last time you looked for a solution?" |
| "I would definitely use that" | Stated future intent, not behavior | Ask: "What have you done about this problem in the past?" |
| "Yeah, we need something like that" | Generic agreement | Ask: "What specifically have you tried?" |
| "Send me a link when it's ready" | Low-commitment interest | Ask: "Would you be willing to [pay/commit time] right now?" |
| "Everyone in my industry has this problem" | Projection, not evidence | Ask: "Tell me about YOUR specific situation" |
| "I'd pay $100/month for that, easy" | Hypothetical, not commitment | Ask: "Can you pre-order today at that price?" |

---

## Green Flag Answers (Real Validation Signals)

These answers indicate genuine pain and potential demand (HR-V1 compliant):

| What they say/do | Why it's real evidence |
|---|---|
| Describes a workaround they built | Invested time to solve the problem (behavioral) |
| Has tried and abandoned other solutions | Active searcher — the pain is real and unresolved |
| Can quantify time/money cost | The problem is measurable and salient |
| Offers to introduce you to others with the same problem | Invested social capital (behavioral) |
| Asks when they can try it / start using it | Pull, not push |
| Offers to pay in advance or pre-order | The strongest signal: money committed |
| Complains about specific details of existing solutions | Deep familiarity = active pain |
| Changed their process because of this problem | Behavioral adaptation = real pain |

---

## Interview Logistics

- **Duration:** 20-30 minutes (respect their time)
- **Setting:** Coffee/video call (casual, not formal)
- **Recording:** Ask permission. If no, take notes immediately after
- **Batch size:** Report evidence after every 3-5 interviews (don't wait for all 10)
- **Quota:** Minimum 5 interviews before drawing conclusions; 10 for high confidence
- **Persona matching:** Interview people who match venture-brief.intake target persona, not
  friends/family who will be polite

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Pitching your idea during the interview | Turns extraction into persuasion; you learn nothing | Never mention your product until the last 2 minutes (if at all) |
| Asking "would you use X?" | People say yes to be polite; stated intent != behavior | Ask about past behavior: "tell me about the last time..." |
| Interviewing friends/family | They will validate you, not your idea | Interview strangers in the target persona |
| Taking the first "yes" as validation | One positive signal is noise, not signal | Need 5+ consistent signals before marking even `low` confidence |
| Ignoring negative signals | Confirmation bias; you hear what you want | Record ALL objections; they are the most valuable data |
| Asking leading questions | "Don't you think X is a problem?" gets "yes" | Open-ended: "Tell me about X" |
| Running one interview and calling it done | Statistical noise | Minimum 5 interviews for any conclusion |
