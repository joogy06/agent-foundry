---
mode: agent
description: Prime this session from foundry-lab harness state — the explicit, deliberate startup trigger.
---

Prime this session.

1. Run `python3 ${workspaceFolder}/vs-code/scripts/session_prime.py` and read its output.
2. Read the project context files that exist: `PROJECT.md`, `history.md` (head ~50 + tail ~200 if
   long), `tasks.md`, `session_control.md`, `.project-profile.json`.
3. Report back in this exact shape, and do not soften any line:

```
PRIMED (manual) — <date>
  context:   <which files were found and read>
  profile:   <loaded | absent — say which>
  env:       <tools detected, or "probe unavailable">
  models:    <detected models, or "none detectable — check the picker">
  stale:     <anything past its review date>
  NOT read:  <anything expected and missing>
```

**State `NOT read` explicitly.** A missing file is a gap in the priming, not something to pass over —
absence reported as silence is the failure this whole harness is built against.

If anything is stale or missing, say what it would take to resolve it.
