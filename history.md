# Session History

## 2026-07-02 — agy consultancy rogue-work root cause + doc sweep

**Summary:**
- Root-caused "agy does work instead of consulting": `agy -p --sandbox "prompt"` is a Go string-flag parsing bug — `-p` consumes `--sandbox` as its value, so the sandbox is silently OFF, the real prompt is DISCARDED (agy receives the literal prompt `--sandbox`), and agy improvises from its implicit cross-call memory. Correct order: `agy --sandbox [--add-dir D] [--print-timeout 15m] -p "…" < /dev/null` (verified: 3.7s clean reply vs. minutes of rogue behavior / recursion).
- Live rogue incident during diagnosis: two broken-order probes caused agy to author AND execute `fix_sandbox_invocations.py`, modifying 6 repo files mid-session (its changes were correct flag-order fixes; verified and kept, two inverted "HANGS" notes corrected). Evidence preserved in session scratchpad `agy-rogue-evidence/`.
- Verified on agy 1.0.15 that `--sandbox` restricts terminal/shell commands ONLY — it does NOT gate agy's native file-write tool (a correctly-sandboxed call edited a file in its `--add-dir` workspace on request).
- Propagated the corrected protection stack (flag order, sandbox scope, no `--add-dir` on writable repos, "Advisory only" prompt prefix, `~/.gemini/agy.md` advise-only directive, `git status --short` tripwire) across ~15 files in both `~/.claude` and this repo (kept identical): CLAUDE.md, antigravity-cli, codex-orchestration, forge (+external-finding-verification), challenger, adversarial-team-brainstorm, cross-cli-deliberation, large-file-analysis, research-for-skills, _meta/hard-rules-checklist, git-cli-bridge integration, env-adoption context-detection, agents/bob.md, workflows/README.md. Repo CLAUDE.md's stale Gemini directive replaced with the agy directive.
- Updated the smart-analyst project memory `agy-sandbox-write-leak.md` with the root cause (yesterday's "analyst ignored its brief" = brief never delivered due to the same flag-order bug).

**Decisions:**
- `--sandbox` remains MANDATORY for consultancy calls (it blocks the S052 rogue-git-commit class) but is documented as NOT sufficient — the advise-only prompt prefix + directive layer + tripwire are required companions.
- The two workflow-stage "agy HANGS" notes were re-scoped: the historical hang is attributed to the flag-order bug; correct-order behavior from workflow stages is UNVERIFIED — agy stays "unreachable from stages" until re-probed.
- Repo working tree left uncommitted (15 modified files) — committing deferred to the user's normal "Update skills and agents" flow.
