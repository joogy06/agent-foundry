# Tasks

## Completed (2026-07-02)

- [x] Root-cause agy "does work instead of consulting" — flag-order parsing bug (`-p` swallows `--sandbox`; prompt discarded, sandbox off) + verified `--sandbox` does not gate native file writes (agy 1.0.15).
- [x] Propagate FLAG ORDER + corrected SANDBOX rules across both trees (`~/.claude` + repo, ~15 files); replace repo CLAUDE.md's stale Gemini directive with the agy directive.
- [x] Add ADVISE-ONLY default to `~/.gemini/agy.md`.
- [x] Correct smart-analyst memory `agy-sandbox-write-leak.md` with the root cause.
- [x] Verify + adopt the rogue-agy script's repo fixes; correct the two inverted "HANGS" notes; clean agy scratch; preserve evidence in session scratchpad.

## Open

- [ ] Commit the 15 modified repo files (usual "Update skills and agents" flow) — left uncommitted deliberately.
- [ ] Report the `-p` string-flag parsing bug upstream to the Antigravity CLI team (flags after `-p` are silently swallowed as the prompt; no warning, no error).
- [ ] Re-probe `agy --sandbox -p` (correct order) from Workflow stages — the "unreachable from stages" guidance in `workflows/README.md` + `env-adoption/references/context-detection.md` is conservative pending this.
- [ ] Version sweep follow-ups (`bash ~/.claude/skills/_meta/alf_sweep_launcher.sh version`): antigravity-cli skill description still says "Covers 1.0.5"; several files still phrase gemini as "available fallback until 2026-06-18" (date has passed); session-start digest also flags a gates 3-tree MISMATCH.
- [ ] Consider whether agy's implicit cross-call memory (`~/.gemini/antigravity-cli/brain/`, `jetski_state.pbtxt`) can/should be reset or disabled for consultancy calls — it is what turned a degenerate prompt into unsolicited repo edits.
