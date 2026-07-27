# Challenger Concerns

Issues raised by the Wave 1 challenger review of the cross-tool design that the original spec didn't fully address. Each is documented with the concern, the current state, and the mitigation (or open question).

## Concern 1: Skill name collisions across tools

**Concern**: A skill named `my-skill` could collide with a built-in skill of the same name on another tool, or a Copilot agent of the same name.

**Current state**:

- **Strict-loader built-in skills** (indicative of the convention): `skill-creator`, plus extension-bundled skills like `nanobanana`. None of the four new skills (`claude-code-cli`, `antigravity-cli`, `gh-copilot-cli`, `gcp-workstations`) collide.
- **Copilot built-in agents** (UNVERIFIED): unknown set. Default agent uses no specific name.
- **Codex built-in skills**: 7 native + 112 mirrored from Claude. Includes `codex-claude-bridge`, `brainstorming-ideas`, `challenger-review`. None collide with the new four.

**Mitigation**:

1. Document the rule in `common-mistakes.md`: pick names that don't collide with built-ins
2. Verify before publishing: list the target tool's skills and check the new name doesn't appear. TODO(agy): verify the agy command to list built-in/imported skills (`agy plugin list` lists plugins).
3. For Copilot, since there's no skills concept, name collisions don't apply at the skills level
4. The four new skills in this design are all clear

**Open question**: As tools ship more built-in skills in future versions, future cross-tool skills may need to be renamed. Add a quarterly check to alf to scan for new name collisions.

## Concern 2: Hook re-entrancy across CLIs

**Concern**: A hook in Claude that invokes another AI CLI (e.g. `agy`) could recurse if the called tool also runs hooks and that hook invokes `claude`. (agy's hooks support is unverified — TODO(agy): verify equivalent — but the guard is cheap insurance.)

**Current state**: Convention only — no tool enforces a recursion limit. The `AI_CLI_CALL_DEPTH` env var pattern (documented in `hooks-portability.md` and `claude-code-cli/references/cross-tool-integration.md`) requires hook authors to manually add the guard.

**Mitigation (convention-based)**:

```bash
#!/bin/bash
# At the top of every hook script that invokes another AI CLI
export AI_CLI_CALL_DEPTH="${AI_CLI_CALL_DEPTH:-0}"
if [ "$AI_CLI_CALL_DEPTH" -ge 2 ]; then
  echo "Refusing to recurse: AI_CLI_CALL_DEPTH=$AI_CLI_CALL_DEPTH" >&2
  exit 0
fi
export AI_CLI_CALL_DEPTH=$((AI_CLI_CALL_DEPTH + 1))
# ... call claude / codex / agy ...
```

**Why convention is fragile**:

1. Hook authors may forget the guard
2. Different processes don't share env vars by default — only child processes inherit
3. If a hook uses a wrapper (like `nohup` or background job) that strips the env, the guard is bypassed
4. There's no central registry of CLIs to coordinate the depth

**Future backlog item**: Tool-level enforcement. Each CLI checks `AI_CLI_CALL_DEPTH` on entry, refuses to start if ≥2, increments before any tool call. Until then, this is a documented convention.

## Concern 3: Multi-user auth on a shared workstation

**Concern**: If a workstation is used by multiple devs, each user needs separate auth state. The persistent disk is per-workstation; how do per-user credentials work?

**Current state**: **Out of scope.** The design explicitly assumes single-developer workstations (Section Q3 clarification in the design doc). Multi-user is a future expansion.

**Why deferred**:

1. The 4 AI CLIs all default to per-user credential storage (`~/<tool>/`)
2. Multi-user complicates everything: Secret Manager IAM, credential isolation, sudo rules, file ownership
3. GCP Workstations is itself designed primarily for one user per workstation
4. Adding multi-user support would multiply the design's complexity 3-5x

**If multi-user is needed in future**:

- Each user gets their own workstation (cheaper than dealing with auth isolation)
- Or: per-user `~/.claude/`, `~/.antigravity/`, `~/.copilot/` with strict file permissions (`chmod 700`)
- Or: per-user service accounts with separate IAM bindings
- Out of scope for this design.

## Concern 4: Symlink / import currency

**Concern**: The Codex symlink can be overwritten by a per-file install, and the agy import can go stale if agy copies rather than symlinks. The next edit to the canonical Claude source then doesn't propagate.

**Current state**:

- **Codex**: use a directory-level `ln -sfn ~/.claude/skills/<name> ~/.codex/skills/<name>` symlink — it tracks live edits. Never do per-file symlinks under the Codex path (see `common-mistakes.md` § Per-file symlinks).
- **agy**: `agy plugin import claude` is the verified bulk-import path. TODO(agy): verify equivalent — whether agy symlinks (live edits) or copies (needs re-import). Until verified, re-import after substantial canonical-source edits.

**Mitigation**:

1. Documented in `install-matrix.md`: canonical source is `~/.claude/skills/<name>/`; Codex symlinks to it; agy imports from it.
2. Verify the Codex symlink after every upgrade: `readlink ~/.codex/skills/<name>` should show the canonical path.
3. TODO(agy): verify the command to confirm an imported agy skill still points at / matches the canonical source.

**Future backlog item**: A periodic alf check that all cross-tool skill symlinks/imports still resolve to the canonical source.

## Concern 5: AGENTS.md not natively read by Claude Code

**Concern**: The cross-tool design recommends AGENTS.md as the canonical instruction file. But Claude Code 2.1.96's native AGENTS.md support is **UNVERIFIED**.

**Current state**: The user has `~/.claude/AGENTS.md -> ~/.claude/CLAUDE.md` symlink as a workaround. Whether Claude reads AGENTS.md natively (without the symlink) is the G2 first-boot test.

**Mitigation (until G2 confirms)**:

1. Set up the symlink as a workaround
2. Document the unverified status prominently in `agents-md-canonical.md` and `claude-code-cli/references/custom-ecosystem.md`
3. Make the design tolerant of either outcome — if Claude reads AGENTS.md natively, the symlink is just redundant; if not, the symlink is load-bearing

**G2 test**: Move CLAUDE.md aside, leave only AGENTS.md, run `claude -p "what are my global instructions?"`. If Claude reports the AGENTS.md content, native support is confirmed.

## Concern 6: First-boot verification depends on a tool that doesn't yet exist

**Concern**: WP1-4 specialists are supposed to enforce cross-tool portability rules from this design doc. But the validator script (`verify-skill-portability.sh`) is itself a deliverable of WP5, which runs after WP1-4. Chicken-and-egg.

**Current state**: Resolved during execution by the **temporal note** in design Section 3.4:

1. During WP1-4, specialists enforce the rules from the embedded context (Section 1.6 of the design doc — frontmatter strict, naming, body length, etc.)
2. WP5 produces the validator script
3. WP5's acceptance includes running the script against all of WP1-4's outputs
4. If any WP1-4 skill fails the script, that WP is re-opened for correction before WP6 proceeds

**Result**: All four new skills are validated retroactively as part of WP5 acceptance.

## Concern 7: Description budget

**Concern**: Descriptions have a hard 1024-char limit. The four new skills in this design have rich descriptions that may approach the limit.

**Current state**: Verified — all four descriptions are well under 1024 chars (longest is `gh-copilot-cli` at ~360 chars).

**Mitigation**: The validator checks description length. Authors will see warnings if they approach the limit.

## Open backlog items

| # | Item | Priority |
|---|---|---|
| 1 | Tool-level enforcement of `AI_CLI_CALL_DEPTH` (replace convention) | Medium |
| 2 | Quarterly alf check for new built-in skill name collisions across tools | Low |
| 3 | First-boot G2 test: confirm Claude AGENTS.md native support | Medium |
| 4 | Multi-user workstation auth design (future expansion) | Low |
| 5 | Periodic check that all cross-tool skill symlinks/imports resolve | Low |
| 6 | TODO(agy): verify agy's instruction-file, hooks, skill-list and import-currency contracts | Medium |
| 7 | Fractional L4 GPU availability on GCP Workstations | Low (separate from cross-tool concerns) |

## Anti-patterns

| Don't | Why |
|---|---|
| Trust the recursion convention without manual review | Convention is fragile; verify hook scripts have the guard |
| Pick a skill name without checking each tool's built-ins | Collision is silent — your skill loses |
| Do per-file symlinks under the Codex skill path | Overwrites content via self-referential links (see common-mistakes.md) |
| Assume Claude reads AGENTS.md natively | UNVERIFIED. Set up the symlink workaround until G2 confirms. |
| Skip the validator because "the rules are obvious" | They're not. The five hard rules are easy to break. |
