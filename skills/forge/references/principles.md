# Forge reference — principles

Checklist steps 6 and 7 — previous: step 5b, the hard rules checkpoint; next: step 8, write design doc.
When this file is read, return to the SKILL.md checklist.

## Contents

- UX Principles Reference
- Key Principles

## UX Principles Reference

For UI-facing work, apply these when evaluating designs:

| Principle | Application |
|-----------|-------------|
| **Fitts's Law** | Make primary CTAs big and centrally placed |
| **Hick's Law** | Limit options, don't overwhelm with choices |
| **Jakob's Law** | Follow conventions users already know |
| **Miller's Law** | Group info into categories, max ~7 items |
| **Von Restorff Effect** | Make primary CTA visually distinctive |
| **F-Pattern / Z-Pattern** | Place key info along natural scan paths |
| **Progressive Disclosure** | Show only what's needed, reveal on demand |

---

## Key Principles

- **One question at a time** — don't overwhelm the user
- **Multiple choice preferred** — easier to answer than open-ended
- **YAGNI ruthlessly** — remove unnecessary features from all designs
- **Users first, code second** — every decision starts with "how does the user experience this?"
- **Always triple challengers for MEDIUM+** — Claude + Codex + agy catch what one or two models miss
- **Always include UX for UI work** — technically perfect but confusing = failed
- **Codex and agy run in parallel, not after** — launch all external model tasks alongside Claude agents, never sequentially
- **Escalate to Codex when stuck** — if Claude agents fail 2+ times, delegate to Codex for a fresh perspective before asking the user
- **Flag model disagreements** — when Claude, Codex, and agy disagree, present all perspectives to the user
- **agy as an independent third model** — use `agy --sandbox --mode plan --model <slug> -p` (the slug from `seat_model.py argv --role consultant_main --provider agy`, at most 3 calls per round) for architecture analysis, codebase review (inline the files), and multi-methodology brainstorming; `--sandbox` is mandatory for these advise-only calls (#157 — without it agy may edit/commit the reviewed project instead of reporting)
- **Forge owns design, bob owns execution** — after design approval, spawn bob and let him handle everything
- **Teammates don't inherit context** — include ALL relevant info in spawn prompts
- **Use the guarded seat_model call for every budgeted codex seat** (`codex_top_seat`: `seat_model.py argv --use`, `seat_model.py timeout`, `codex_quota.py classify`); plugin commands (`/codex:adversarial-review`, `/codex:rescue`, `/codex:review`) are an ungated, non-protected convenience — no seat pin, no admit gate, never for a protected seat; plugin not installed on this host (S080 D11)
- **Refer to `codex-orchestration` skill** for the seat registry, the admit gate and raw Codex CLI patterns (parallel batches, custom briefs, skill injection)
