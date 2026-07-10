# Session History

## 2026-07-10 — overhaul/agent-skills branch: four-surface review fixes

**Summary:**
- Executed the 2026-07-06 four-surface review (workflows/agents/skills/gates) as 7 commits on branch `overhaul/agent-skills`, ratified via cross-CLI Gate-1 ballots (Codex gpt-5.6-sol: CHANGE_NEEDED@94 — both evidence-backed changes adopted: HEAD+status tripwire, enforceable skill_factory follow-up; agy/gemini-3.5-flash: single finding nullified — misread Batch 7 "add" as "delete").
- **Workflows unbroken (the big one):** the current Workflow runtime REJECTS `export default` at load (SyntaxError, verified by zero-agent live probe) and rejects non-literal meta blocks (concatenated descriptions). 7 of 8 workflows had both defects — only bob-serial-exec had been adapted (2026-06-11). All converted to bare-body + flattened meta; alf-sweep verified end-to-end (loads, runs, early-exits).
- alf-sweep's verify arm was doubly broken (verifier returned a bare array where synthesize expected `{output, verifications}` → all findings silently dropped; join key unconstructable by the verifier → everything UNVERIFIED). adversarial-tournament discarded its refine round and fed the arbiter attacks-only. Both joins fixed.
- agy sandbox stack backfilled into pa.md/alf.md (4 sites); tripwire upgraded to pre/post `git rev-parse HEAD` + `git status --short` (a committing consultant leaves a clean worktree). S055 backfilled: pa.md spawn-request fallback; bob.md pre-S055 body text (specialist spawns, wait-for-agent-teams, Step 8.7 forge spawn) rewritten; evo.md Task→agent-spawn-facility + classify_emit added.
- Staleness sweep: counts 119→184, agy pins→1.1.0, README 9→8 workflows, FRESHNESS anchors re-verified (claude 2.1.201 / codex 0.144.1 / agy 1.1.0), "agy UNREACHABLE from stages" re-scoped to UNVERIFIED-under-corrected-flag-order. **Gemini CLI (v0.50.0, /usr/bin/gemini) is installed and working — kept as available fallback per user direction 2026-07-10; the announced 2026-06-18 retirement never landed. agy stays PRIMARY.** entrepreneur-webstore added to the mirror (never published; publish flow lacks a completeness check).
- Gates mechanized: gates.py `--help` + unknown-flag rejection (the `--help/` junk-dir class), G1 refuses `--no-ledger-binding` once the ledger exists, probe.sh inventory write is tmp+mv, inventory-history append takes the #126 feeds.lock flock, session.key generated under umask 077. Data-not-instructions HARD-RULE added to all 5 agents. Live `_meta` litter removed (`--help/`, empty archive/, stale backup).

**Open / deferred:**
- skill_factory S059 backport + strict prod-shadow pre-push gate: prepared but the commit into that separate repo was permission-denied (out of named scope) — see tasks.md.
- Post-merge: byte-sync repo → live trees, then re-run identity_check.
- Pre-existing `_meta` test failure: `test_phase5b_static_exit_discipline_allowlist` fails on the base commit too (not a regression).
- Agent .md length reduction (bob 746 lines), 44 skill-description trigger rewrites, publish completeness check — not started.

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
