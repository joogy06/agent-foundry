---
name: roll
description: Manually rotate history.md (project-documentation skill). Flags - --dry-run preview, --keep N override session-count, --restore one-level undo, --force bypass single-session-over-cap floor.
---

# /roll -- Manual history.md rotation

Manually invoke the `project-documentation` skill's rotation engine on the
current project. Useful when:

- You want to preview what the rotation would do (`--dry-run`)
- You want to roll on a different threshold than the project's defaults (`--keep N`, `--cap N`)
- You need to undo the last rotation (`--restore`)
- You want to bypass the single-session-over-cap floor (`--force`)

## Behavior

This command resolves the project root (current working directory) and runs:

```
python ~/.claude/skills/project-documentation/scripts/rotate.py "$PROJECT_ROOT" $ARGUMENTS
```

`$ARGUMENTS` is forwarded verbatim, so any combination of `--dry-run`,
`--keep N`, `--cap N`, `--restore`, `--force`, `--actor <name>` works.

## Examples

```
/roll --dry-run               # preview only; no writes
/roll --keep 1                # archive aggressively until 1 session remains
/roll --restore               # undo last rotation (mv .pre-rotation-bak back; rm history/)
/roll --force                 # bypass single-session-over-cap floor
```

## Cross-tool

In Codex CLI: `Skill('project-documentation', args='roll [flags]')` invokes
the same script via the `~/.codex/skills/project-documentation` symlink.
The flag set is identical.

## Safety

The rotation engine takes an advisory `flock` on `<project>/.history.lock`
during read-modify-write. Concurrent invocations either serialize or abort
with a clear diagnostic. Every rotation makes a one-level-undo backup at
`history.md.pre-rotation-bak` -- use `/roll --restore` to recover.

## See Also

- `~/.claude/skills/project-documentation/SKILL.md` -- rotation policy section
- `~/.claude/skills/project-documentation/scripts/rotate.py` -- the engine
- `docs/plans/2026-04-29-history-md-rotation-design.md` -- design rationale
