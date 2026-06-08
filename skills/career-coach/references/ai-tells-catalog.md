# AI-Tells Catalog — Voice Capture & Anti-Slop Humanization

Single canonical home of the anti-AI-pattern knowledge and voice-capture protocol for the `career-*` family. Consumed by `career-application-writer` (Stage 3), `career-storytelling`, `career-positioning`, and the `human-voice-writing` alias.

> **Implementer note:** This file is read by children of `career-coach` and by the `human-voice-writing` alias. It is the ONE place anti-slop and voice-capture knowledge lives — do not duplicate this content into the consuming skills; have them point here.

---

## 1. Integrity Boundary + Detector Reality

**Why we never target detectors.** AI-text detectors are unreliable and biased. No public detector scores reliably high on real-world CVs and professional prose; false-positive rates on genuine human writing run meaningfully high, and they run dramatically higher for non-native-English writers (see `market-snapshot-2026-06.md` for current figures and the Liang et al. arXiv 2304.02819 citation). Optimizing text against a detector therefore (a) chases an unstable target, (b) can make honest human writing read as "machine-cleaned", and (c) crosses the integrity line.

**The goal is human-quality writing, not a detector score.** Everything in this catalog exists to help true content read as the specific, lived, credible work of an actual person — because that is what a human reviewer responds to, and human review (not detector tooling) is what decides outcomes. We improve HOW true content is told; we never invent WHAT is claimed.

- **No detector-gaming** (HARD-RULE wherever this catalog is consumed): never optimize against a detector score; never frame guidance as "beating", "passing", "fooling", or "bypassing" any screen. Frame as truthful, specific, human-edited documents that read as credible.
- **No fabrication:** humanization operates on phrasing and structure, never on facts. Gaps stay gaps.
- **Voice belongs to the human** (see §5–§6): capture and restore the author's actual register; never impose a generic "human-sounding" template — that just manufactures a new detectable pattern.

---

## 2. Focal-Word Catalog (Kobak et al. 2025)

Large-model prose over-uses a small cluster of words far above the human baseline. Frequencies below are illustrative multipliers vs. a pre-LLM human corpus (Kobak et al. 2025 excess-usage study):

| Word / phrase | Approx. excess vs. human baseline |
|---|---|
| delve / delving | ~28× |
| underscore(s) / underscoring | ~13.8× |
| showcasing | ~10.7× |
| leverage (as a verb) | strongly elevated |
| seamless / seamlessly | strongly elevated |
| spearheaded | elevated |
| robust | elevated |
| holistic | elevated |
| tapestry, realm, navigate (figurative), foster, intricate, pivotal, multifaceted, testament, garner, boast, elevate, crucial, vital, harness, embark | the 21-focal-word cluster — all elevated |

**Cluster-not-blocklist caveat (load-bearing).** Each of these words alone is roughly chance — humans use "robust" and "leverage" all the time. The signal is the *cluster*: many focal words + uniform structure + formulaic openers all at once. Do NOT treat this as a find-and-replace blocklist (mechanical word-swapping is itself an anti-pattern, §Anti-Patterns). Use it as a sweep to notice over-density, then edit toward the author's real register.

---

## 3. Structural Tells → Fixes

| Structural tell | Why it reads as machine | Fix |
|---|---|---|
| Em-dash density (a dash every other sentence) | Markdown-training fingerprint (cf. arXiv 2603.27006) | Keep dashes the author actually uses; convert the rest to commas, periods, or parentheses |
| "Not only X but (also) Y" | Over-represented LLM connective | Say the two things plainly, or pick the one that matters |
| "It's not X, it's Y" / "X isn't just Y" | Formulaic antithesis | State the point directly without the inversion |
| Tricolons (rule-of-three everywhere) | Rhythmic default of generated prose | Vary list length; sometimes two, sometimes four |
| Uniform sentence length | Low burstiness — humans vary wildly | Restore burstiness: short. Then a longer, winding sentence that carries a real clause. Then short again. |
| Formulaic opener ("In today's fast-paced world…") / closer ("In conclusion, …") | Template scaffolding | Cut the scaffold; open on a specific fact, close on a concrete next step |
| Bullet + bold overuse | Markdown-training fingerprint | Use prose where prose belongs; reserve bullets for genuine lists |
| Hedge-everything tone ("can help to potentially improve") | Generated caution | Commit to the claim the evidence supports |

---

## 4. The Humanization Pass (ordered checklist)

Run in order. Stop when the text reads as the author's own.

1. **Read-aloud test** — read it out loud (or sub-vocalize). Anywhere you stumble or sound like a brochure, mark it.
2. **Focal-word sweep** — scan for §2 over-density. Thin the cluster; keep words the author would genuinely use.
3. **Burstiness restore** — break the uniform rhythm (§3). Mix short and long sentences deliberately.
4. **Concrete-specifics injection** — replace generic claims with lived, verifiable detail: the actual system, the real number, the specific constraint. (Specifics are the single strongest antidote to generic-slop perception — and they must be true.)
5. **Register check** — compare against the author's captured voice sample (§5). Does it sound like *them*, not like a generically "human-sounding" template?

### Before / after — banking bullet

- **Before (slop):** "Spearheaded a robust, holistic initiative that seamlessly leveraged cutting-edge automation to drive significant value across multiple business lines."
- **After (voiced, specific):** "Built the reconciliation-automation pipeline for three trading desks — cut the daily manual break-investigation from ~4 hours to under 30 minutes and closed two repeat audit findings."

### Before / after — generalist bullet

- **Before (slop):** "Leveraged a multifaceted approach to foster seamless collaboration and showcase impactful results."
- **After (voiced, specific):** "Got the support and engineering teams onto one weekly triage call. Ticket reopen-rate dropped by about a third over the next quarter."

---

## 5. Voice-Capture Protocol

Run this once per user; store the result as a reusable voice profile. The goal is to capture the user's *actual* idiolect, not to invent a charming one.

**6–8 question interview:**
1. How would you describe this project to a colleague in a hallway, in two sentences?
2. What are you actually proud of here — and what was genuinely hard?
3. Do you write in long sentences or short, punchy ones?
4. Do you use contractions in professional writing (don't / I've), or keep it formal?
5. Any words or phrases you reach for a lot? Any you actively avoid?
6. Do you use em-dashes, or are you a comma/period person?
7. (Harvest) Paste one or two paragraphs of writing that already sound like you (an email, a Slack post, an old cover letter).
8. (Optional) Anything that makes writing sound "not like you" when you read it back?

**Extract idiolect markers** from answers + samples:
- typical sentence length and variance
- hedge words and signature verbs
- contractions: yes / no
- em-dash habit: yes / no
- formality register; any recurring metaphors or domain shorthand

### Reusable voice-profile template

```
## Voice Profile — <name>
captured: <date>
sentence_rhythm:   <short-punchy | long-winding | mixed; note variance>
contractions:      <yes | no>
em_dash_habit:     <yes | no | sparingly>
signature_verbs:   <e.g. built, shipped, ran, fixed>
avoid_words:       <words the user dislikes>
hedge_level:       <commits | moderate | cautious>
register:          <formal | conversational-professional | direct>
domain_shorthand:  <terms the user uses naturally>
samples:           <1-2 pasted paragraphs of the user's own writing>
```

### Cold-start degraded mode

If no profile and no sample exist and the user can't provide one right now:
- Run the **minimum 2-question capture** (Q1 + Q3 above), OR
- Produce output explicitly labelled **"neutral register — not yet voiced"** and tell the user it should be passed through a voice edit before sending.
- **Never** emit silent generic output as if it were the user's voice.

---

## 6. Non-Native Register Preservation

Preserve the candidate's natural register. Do NOT force idioms, slang, contractions, or fake quirks onto a writer whose authentic professional English is clean and slightly formal. "Sounding human" does not mean "sounding like a native casual speaker." Forcing artificial colloquialism (a) misrepresents the person, (b) reads as off, and (c) penalizes exactly the writers whom detectors already over-flag. The target is *their* clear voice, not a borrowed one.

---

## 7. Update Triggers

- Re-validate the §2 focal-word list when a newer corpus study lands (the cluster shifts as models change).
- Move any numeral that creeps in here into `market-snapshot-2026-06.md` instead.
- **alf sweep note:** treat this file as a freshness-sensitive reference. On a sweep, check §2 against the latest published excess-usage study and confirm the no-detector-gaming framing has not drifted into evasion language anywhere it is consumed.

**Citations** (year-tagged): Kobak et al. 2025 (focal-word excess-usage); arXiv 2603.27006 (Markdown structural fingerprint); arXiv 2304.02819 / Liang et al. (detector false-positive and non-native bias).
