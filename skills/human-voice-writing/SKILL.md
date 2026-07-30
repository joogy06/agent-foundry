---
name: human-voice-writing
description: "Use when the user asks to humanize a draft they authored or own, make text sound less AI-generated, check whether writing reads as AI-written, or remove AI-typical patterns — for professional and personal writing such as CVs, posts, bios, emails, and articles. Improves HOW true content is told; never invents facts, never games AI detectors, never overrides an explicit persona. Routes deep catalog knowledge to career-coach/references/ai-tells-catalog.md and full CV/cover-letter generation to career-application-writer. Trigger on - humanize this, sounds like AI, make this sound human, remove AI tells, does this read as AI-written, AI slop check."
---

# Human-Voice Writing

A thin entry point for "humanize this / does this read as AI?" on writing the user authored or owns. It improves HOW true content is told — it is **not** persona-shaping (that's `content-writer`) and **not** detector-evasion (see HARD RULE 1). The deep knowledge lives in `~/.claude/skills/career-coach/references/ai-tells-catalog.md`; this skill carries the integrity guardrails and a fast 5-step pass.

## HARD RULES

1. **Integrity — operate on HOW, never WHAT.** Improve phrasing, rhythm, and specificity of *true* content the user authored or owns. **Refuse** requests to disguise authorship for academic-integrity evasion or deceptive provenance — e.g., "make my essay pass Turnitin" or "rewrite this so my professor can't tell I used AI" → refuse and explain why (this is academic-integrity evasion, not voice work). Refuse detector-evasion framing generally; offer honest voice improvement instead.
2. **No detector-gaming.** Detectors are unreliable and biased (see `market-snapshot-2026-06.md`); never optimize against a detector score or frame the work as "beating"/"passing"/"fooling" a screen. The goal is genuinely human-quality writing.
3. **Preserve the author's natural register (non-native fairness).** Never force idioms, slang, contractions, or fake quirks onto a clean, slightly-formal authentic voice. "Human" means *their* voice, not a borrowed casual one — and detectors already over-flag non-native writers, so this matters doubly.
4. **Voice belongs to the human.** When no voice sample exists, ask for one paragraph of the user's own writing, or apply the cold-start rule (`ai-tells-catalog.md` §Cold-start) and label output "neutral register — not yet voiced". Never emit silent generic output as the user's voice.

## The 5-Step Humanize Pass

1. **Read-aloud test** — read it out; mark anything that sounds like a brochure or makes you stumble.
2. **Focal-word sweep** — thin the over-used cluster (delve / leverage / seamless / robust / showcasing …); keep words the author would actually use. It's a cluster signal, not a blocklist.
3. **Burstiness restore** — break uniform sentence rhythm; mix short and long deliberately.
4. **Concrete-specifics injection** — replace generic claims with true, lived detail (the real number, the actual system). Specifics defeat generic-slop perception — and must be true.
5. **Register check** — compare against the author's own writing sample; does it sound like *them*?

Full focal-word table, structural-tell fixes, before/after examples, and the voice-capture protocol: `~/.claude/skills/career-coach/references/ai-tells-catalog.md`.

## Route-Outs

- Writing or tailoring a CV / cover letter / application package → `career-application-writer` (full gated pipeline).
- Editorial content with a deliberate brand persona → `content-writer` (this skill authenticates voice; it does not override an explicit persona).

## Anti-Patterns

| Anti-Pattern | Why it fails |
|---|---|
| Mechanical word-swapping (find/replace the "AI words") | Creates a new stilted pattern; misses the cluster nature of the signal |
| Over-humanization (forcing quirks, slang, choppiness) | The "de-AI'd" tell; misrepresents the author; penalizes non-native voices |
| Treating the tells list as a blocklist | Each word alone is ~chance; the list is a sweep, not a ban |
| Humanizing to disguise authorship | Integrity failure (HARD RULE 1) — refuse |

## See also

- `business-writing` — structure, order and the ask for workplace writing. This skill fixes HOW a
  draft reads; that one decides what it says and in what order.
