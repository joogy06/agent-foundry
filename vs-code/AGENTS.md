# foundry-lab — always-on instructions for VS Code / Copilot

<!-- Template → copy to <workspace>/AGENTS.md, or merge into an existing one.
     VS Code collects AGENTS.md, .github/copilot-instructions.md and CLAUDE.md into every
     request. This is the layer that is ALWAYS PRESENT — and it is convention, not
     enforcement: the model can ignore it. See vs-code/docs/startup.md. -->

## Session start

**Before doing work, prime the session.** VS Code has no SessionStart hook, so this is the
contract that substitutes for one:

1. Read `.foundry/session-state.json`. The `foundry: session prime` task writes it on folder open.
2. **If it is missing or not from today, say so** and run
   `python3 vs-code/scripts/session_prime.py`. Do not proceed as though primed.
3. Read the project context that exists: `PROJECT.md`, `history.md`, `tasks.md`,
   `session_control.md`, `.project-profile.json`.
4. State what you loaded, and the grade: `primed (task)` · `primed (manual)` · `unprimed`.

**Never imply a primed session from a stale file.** Reporting the grade honestly is the whole
mechanism — a confident summary drawn from yesterday's state is the failure this replaces.

## Skills

Agent Skills are **native** here — VS Code and Copilot auto-discover `~/.claude/skills/`. Every
foundry-lab skill is already available.

- **Invoke the skill; do not paraphrase it.** If a skill covers the task, follow it.
- **Say which skill you are using** before acting.
- Do not copy skill content into this workspace — it is already reachable and would fork.

## Models

Copilot exposes several vendors. foundry-lab depends on reaching more than one, because a second
opinion from the same family is not a second opinion.

- **Detect, never assume**: `python3 vs-code/scripts/detect_models.py`. A remembered model id fails
  silently as a permissions error.
- Route by task weight — cheap tier for mechanical work, strong tier for design and review, a
  **different vendor** when the point is disagreement. See `vs-code/docs/model-routing.md`.
- **Cost is a real constraint.** Do not spend a premium model on mechanical edits.

## Honesty rules that carry over

- **Report what you did not do.** A skipped check is stated, never silent.
- **Verify rather than assume** — run the command, read the output, quote the result.
- **Say when something is unavailable** in this environment instead of approximating it.
- Windows and macOS differ in shell, paths and interpreters. Do not assume bash.
