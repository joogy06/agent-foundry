# Tasks

## Completed (2026-07-02)

- [x] Root-cause agy "does work instead of consulting" — flag-order parsing bug (`-p` swallows `--sandbox`; prompt discarded, sandbox off) + verified `--sandbox` does not gate native file writes (agy 1.0.15).
- [x] Propagate FLAG ORDER + corrected SANDBOX rules across both trees (`~/.claude` + repo, ~15 files); replace repo CLAUDE.md's stale Gemini directive with the agy directive.
- [x] Add ADVISE-ONLY default to `~/.gemini/agy.md`.
- [x] Correct smart-analyst memory `agy-sandbox-write-leak.md` with the root cause.
- [x] Verify + adopt the rogue-agy script's repo fixes; correct the two inverted "HANGS" notes; clean agy scratch; preserve evidence in session scratchpad.

## Completed (2026-07-10, branch overhaul/agent-skills)

- [x] Commit the 15 modified repo files — landed as 30c1ff5 (2026-06-24).
- [x] Version sweep follow-ups: antigravity-cli bumped to "Covers 1.1.0" (verified 2026-07-10); gemini phrasing updated everywhere to "remains an available fallback — kept per user direction 2026-07-10" (gemini v0.50.0 verified working; agy stays PRIMARY); skill counts fixed (119 → 184).
- [x] Workflow scripts unbroken: 7 of 8 used an `export default` wrapper the runtime REJECTS at load (verified by live probe 2026-07-10) plus concatenated meta descriptions; all converted to the bare-body shape.

## Completed (2026-07-11, branch feat/codex-effort-policy)

- [x] Benchmark gpt-5.6-sol reasoning-effort tiers (14 scored runs, 3 rounds incl. delta-seeking challenger round) — full results in project memory `codex-sol-effort-benchmark.md`. Verdict: `high` never beat `medium`; `xhigh` = tail-find floor for challenger/ballot roles; `max` alone reached design-altitude findings; `ultra` = orchestrated deep-dives only.
- [x] Implement effort policy into skills (both trees, byte-identical): codex-orchestration SKILL.md (new "Reasoning-Effort Tiers" section, per-call pin HARD-RULE, delta-seeking challenger prompt template, capacity retry, Current State refreshed to codex 0.144.1 / gpt-5.6-sol / agy 1.1.1) + patterns.md (EFFORT PIN note, xhigh exemplar) + cross-cli-deliberation SKILL.md (canonical codex ballot call gained full guard set: --ephemeral, -s read-only, effort pin, stdin close, timeout).

## Open

- [ ] Report the `-p` string-flag parsing bug upstream to the Antigravity CLI team (flags after `-p` are silently swallowed as the prompt; no warning, no error).
- [ ] Re-probe `agy --sandbox -p` (correct order) from Workflow stages — workflow anchors now say "UNVERIFIED under corrected flag order"; `workflows/README.md` + `env-adoption/references/context-detection.md` stay conservative pending this.
- [x] Gates 3-tree MISMATCH: S059 files (audit_spawn.py, verification_arbiter_spawn.py, freshness_nudge.py + hard-rules-checklist.md) byte-copied into /mnt/data/dev04/skill_factory and STAGED (user approval 2026-07-11: stage-but-don't-commit — commit remains with the user); strict `G_IDENTITY --pair prod-shadow` added to its pre-push hook via both installers (.sh + .py), block path verified live (drifted file → exit 1 BLOCKED; gate runs before secrets scan). Forbidden-pattern scrub check clean on all four files.
- [x] Merge overhaul/agent-skills into main — fast-forwarded to 0674a82 (2026-07-11).
- [ ] Byte-sync repo → live trees (`~/.claude/{agents,workflows,skills,CLAUDE-adjacent files}`) so the mirror-identity invariant holds; then re-run `identity_check.py`. Deferred per user 2026-07-11 ("merge only, no sync yet"). Current 3-tree state: prod == shadow; single mismatch is gates.py where the repo is AHEAD of the live tree (overhaul commit ff6dc77) — resolved by this sync.
- [ ] Consider whether agy's implicit cross-call memory (`~/.gemini/antigravity-cli/brain/`, `jetski_state.pbtxt`) can/should be reset or disabled for consultancy calls — it is what turned a degenerate prompt into unsolicited repo edits.
- [ ] Pre-existing `_meta` test failure: `test_phase5b_static_exit_discipline_allowlist` fails on the base commit too (verified 2026-07-10 via stash test) — diagnose separately; not a regression of overhaul/agent-skills.
- [ ] P3 review leftovers (from the 2026-07-06 four-surface review): bob.md length reduction (746 lines, 2.5x the 300-line agent threshold; compress duplicated VERIFIED-conjunction prose into a _meta reference), 44 skill descriptions lacking "Use when…" trigger phrasing, publish-flow completeness check (live-vs-staging skill-name diff in publish_prep.py so a skill can't silently vanish from the mirror again), nonce-fenced transcript interpolation in workflows.
- [ ] BLOCKED (permission): skill_factory S059 backport commit + strict `G_IDENTITY --pair prod-shadow` pre-push gate — denied by the auto-mode classifier as outside the named repo scope (2026-07-10); needs explicit user go-ahead. Files ready to byte-copy from `~/.claude/skills/_meta`.
