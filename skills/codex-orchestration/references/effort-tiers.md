# Codex Orchestration — reasoning-effort tiers

Read this file when choosing or questioning a `model_reasoning_effort` tier. When it is read, return to SKILL.md.

The challenger call, the delta-seeking challenger prompt and the operational notes that followed this section are in SKILL.md, under "Reasoning-Effort Tiers".

## Reasoning-Effort Tiers (benchmarked 2026-07-11 on gpt-5.6-sol)

Measured on **gpt-5.6-sol / codex-cli 0.144.1** with planted-bug review fixtures (14 scored
runs, easy + hard rounds + a delta-seeking challenger round). Every tier found all planted
bugs with zero false positives; the only quality separations were (a) one subtle unplanted
defect caught only at `xhigh`/`max` under a plain review prompt, and (b) finding ALTITUDE
under a delta-seeking prompt — `medium` returned concrete-bug deltas, `xhigh` added
state-consistency reasoning, `max` alone produced a design-level finding. `ultra` matched
`max`'s findings at 2.3x the time on bounded tasks; it exists for orchestrated deep dives, not
verdicts.

**`high` — a POLICY finding scoped to one model, not a capability claim.** On gpt-5.6-sol,
`high` never beat `medium` in any of those 14 runs (2026-07-11), so sol calls skip it. Every
listed model supports `high`, and it has NOT been measured on any other model: do not carry the
finding over to `gpt-6-astra` or to a future TOP.

**Tier support** (live `~/.codex/models_cache.json`, fetched 2026-09-14, client 0.154.0; listed
models): `gpt-6-astra`, `gpt-5.6-sol` and `gpt-5.6-terra` support `low` through `ultra`;
`gpt-5.6-luna` lacks `ultra`; `gpt-5.5` lacks `max` and `ultra`; no model supports `minimal`.
On the 2026-09-24 roster (client 0.156.1) `gpt-6-sol`, the std tier since roster rev 3, also offers `low`
through `ultra`, so every effort a seat uses is available on both codex tiers.
Codex TOP selection skips a model that lacks the role's effort.

**Timeouts have ONE owner:** `codex_model._TIMEOUT_FLOOR_S`, read through
`codex_model.timeout_for(model, effort)` — minimal 120s · low 1200s · medium 1200s · high 2400s ·
xhigh 2400s · max 3600s · ultra 5400s, with no per-model overrides today. The column below restates it;
if the two ever disagree, the code wins. No other codex timeout table exists (avengers `convene.py`
calls the same function). A timeout is a ceiling, so a newly followed TOP inherits its tier's floor.
Every tier except `minimal` is also a row in `codex_watch.HARD_CAP_S`, and the two tables are pinned
EQUAL by `test_d24_seat_timeouts_match_the_watchdog_hard_caps`: the registry's number IS the watchdog's
runaway cap, so a caller can never ask the registry for a ceiling and then run under a smaller one.
`minimal` is deliberately absent from the watchdog table — `codex_watch.hard_cap_for("minimal")` RAISES
rather than inheriting another tier's cap — and no reachable codex seat resolves that tier.

| Tier | Use for | Typical wall-clock (sol) | Runaway cap |
|---|---|---|---|
| `medium` | Inner-loop delta passes, mechanical consults, smoke checks | ~25–40s | 1200s |
| `high` | Supported everywhere; skipped on gpt-5.6-sol (policy finding above); unmeasured on other models | — | 2400s |
| `xhigh` | Challenger, QC, devil's advocate, Gate-1 ballots, arbiter verdicts (FLOOR for these roles) | ~2–2.5 min | 2400s |
| `max` | Conceptual/direction reviews, design ratification, stuck-after-2-attempts escalation, post-incident analysis | ~5–7 min | 3600s |
| `ultra` | Deliberate orchestrated deep-dives ONLY (codex spawns its own agents; rewrite the prompt contract for fan-out) | 10–30 min | 5400s |

The last column is the RUNAWAY cap the watchdog is handed, not the time a call is expected to take — read
the "typical" column for that. A call that reaches its cap while still producing output is a `CODEX_GAP`
and is never retried or substituted; the ordinary stop is 300 s of silence, which retries once.
