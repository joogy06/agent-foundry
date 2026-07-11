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

## Open

- [ ] Report the `-p` string-flag parsing bug upstream to the Antigravity CLI team (flags after `-p` are silently swallowed as the prompt; no warning, no error).
- [ ] Re-probe `agy --sandbox -p` (correct order) from Workflow stages — workflow anchors now say "UNVERIFIED under corrected flag order"; `workflows/README.md` + `env-adoption/references/context-detection.md` stay conservative pending this.
- [ ] Gates 3-tree MISMATCH: backport S059 files (audit_spawn.py, verification_arbiter_spawn.py, freshness_nudge.py + hard-rules-checklist.md) from ~/.claude/skills/_meta into /mnt/data/dev04/skill_factory and add a strict `G_IDENTITY --pair prod-shadow` to its pre-push hook (enforceable follow-up per 2026-07-10 cross-model ballot).
- [ ] After merging overhaul/agent-skills: byte-sync repo → live trees (`~/.claude/{agents,workflows,skills,CLAUDE-adjacent files}`) so the mirror-identity invariant holds; then re-run `identity_check.py`.
- [ ] Consider whether agy's implicit cross-call memory (`~/.gemini/antigravity-cli/brain/`, `jetski_state.pbtxt`) can/should be reset or disabled for consultancy calls — it is what turned a degenerate prompt into unsolicited repo edits.
- [ ] Pre-existing `_meta` test failure: `test_phase5b_static_exit_discipline_allowlist` fails on the base commit too (verified 2026-07-10 via stash test) — diagnose separately; not a regression of overhaul/agent-skills.
- [ ] P3 review leftovers (from the 2026-07-06 four-surface review): bob.md length reduction (746 lines, 2.5x the 300-line agent threshold; compress duplicated VERIFIED-conjunction prose into a _meta reference), 44 skill descriptions lacking "Use when…" trigger phrasing, publish-flow completeness check (live-vs-staging skill-name diff in publish_prep.py so a skill can't silently vanish from the mirror again), nonce-fenced transcript interpolation in workflows.
- [ ] BLOCKED (permission): skill_factory S059 backport commit + strict `G_IDENTITY --pair prod-shadow` pre-push gate — denied by the auto-mode classifier as outside the named repo scope (2026-07-10); needs explicit user go-ahead. Files ready to byte-copy from `~/.claude/skills/_meta`.
