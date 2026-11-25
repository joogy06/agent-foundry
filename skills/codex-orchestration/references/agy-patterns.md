# Codex Orchestration — the Antigravity CLI (`agy`)

Read this file before any headless `agy` call. When it is read, return to SKILL.md.

"Seat Models", which this file names for the `codex_top_seat` preamble, is a section of SKILL.md.

## Antigravity CLI (`agy`) — Primary Interface

The **Antigravity CLI** (`agy`) is this host's Google arm: a third MAIN deliberation provider alongside Claude and Codex (not a fallback), and a second-opinion / challenger / research delegate. It authenticates itself via the Antigravity account — no API key or env prefix needed. There is no MCP server: call `agy` directly via Bash. See the `antigravity-cli` skill for the full reference.

**Headless single-prompt mode**:

```bash
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "<prompt>" < /dev/null)
```

- **STDIN RULE (mandatory, #135):** `< /dev/null` on every headless agy call — agy waits on
  non-TTY stdin until EOF before the model call; background/harness shells never EOF → infinite
  hang at 0 bytes (`--print-timeout` does not protect; it guards only the print phase). Piped
  input never reaches the model (2026-11-01, 1.4.12, rc 0): read content into a variable before the
  subshell and inline it, at most 100 KB per call (one argument cannot pass 128 KB). Always wrap in shell `timeout`. Same
  behavior class as `codex exec`'s stdin-block.
- **FLAG ORDER RULE (mandatory, root-caused 2026-07-02):** every flag BEFORE `-p`, prompt LAST.
  `-p` is a string flag and consumes the next token — `agy -p --sandbox "X"` runs UN-sandboxed
  with the literal prompt `--sandbox` and discards "X", after which agy improvises from its
  implicit memory (the "does work instead of consulting" failure mode) and can fork-bomb
  re-testing the broken command. Correct: `agy --sandbox --mode plan [--print-timeout 15m] --model <slug> -p "…"`.
- **SANDBOX RULE (mandatory for analyst/read-only delegation, #157, #366):** every call that
  should only READ is Pattern 1: `--sandbox --mode plan` from an empty cwd, content inline in `-p`,
  no `--add-dir`. Un-sandboxed, agy has write/shell/git tools and an "analyst" can author and
  git-commit code (S052 rogue auto-commit incident). Measured 2026-11-01 on 1.4.12: `--sandbox`
  restricts only the shell, so native writes and reads work under it; `--mode plan` removes native
  writes and the shell; the cwd is the workspace, so a call from a repo can read that repo. Open the
  prompt with "Advisory only — do not modify any files; answer on stdout". The table and its limits
  are in the `antigravity-cli` skill.
- **PATTERN 2 (`--dangerously-skip-permissions`) has no containment:** full shell and git, reads home
  and repos. For work that needs tools, never a way to give a reviewer context. Throwaway directory only, never a live repo as cwd or `--add-dir`; afterwards run
  `git status --short` and compare `git log -1 --oneline` with the start, since status cannot see a
  commit.
- Output is **plain text on stdout** — there are no structured response fields. Callers must parse text, not JSON.
- **MODEL RULE — pin it through `seat_model`; never ride the account default.** `agy` (current **1.4.3**) has a `--model` flag and an `agy models` subcommand; there is no short `-m` alias. `python3 ~/.claude/skills/_meta/seat_model.py argv --role <role> --provider agy` prints `--model <slug>`; place it before `-p` like every other flag. The resolver takes the newest listed version of the roster family (`model_roster.AGY_FAMILY`) and the role supplies the level: `consultant_main` and `arbiter` get `-high`, `consultant_support` gets `-medium` (`gemini-4-argon-high` / `gemini-4-argon-medium` on the 2026-10-20 roster); with `--size light|medium|complex` every role gets `-low` / `-medium` / `-high` instead (roster rev 7, `model_roster.AGY_LEVEL_BY_SIZE`). EVERY agy call pins it — deliberative seats `consultant_main`, research and operational calls `consultant_support`; the `model-eval-pack` skill alone passes `--model` literally, because choosing the model under test is its purpose. A home-tier freeze in `~/.claude/state/seat-model-pins.json` can hold the version; `seat_model.py emit --json` shows what actually resolves. The account default was self-reported as an older Gemini model (2026-09-09, indicative rather than verified) of a family the roster now forbids: omitting `--model` silently seats the call on a forbidden line.
- **AGY FAMILY:** agy serves the one Gemini family named by `model_roster.AGY_FAMILY` (rev 6: Gemini 4 Argon; flash is now forbidden). The hard rule, with the forbidden models and its reasons, is in SKILL.md with the opening hard rules; it binds every call in this file.
- For long-running prompts raise the wait timeout: `(d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan --model <slug> --print-timeout 15m -p "<prompt>" < /dev/null)` (default `5m0s`). Keep `< /dev/null` even here — `--print-timeout` only guards the print phase, NOT the stdin read, so omitting it still hangs to the shell `timeout` (#135).
- Append a `served_by` probe line to the prompt if you need provenance — self-reported model identity is unreliable, so capture it at the call layer.

**Use cases** (all via a single `agy -p` call): research, analysis, code review, large-file analysis, and brainstorming (frame the methodology — SCAMPER, Design Thinking, Divergent, Convergent, Lateral — directly inside the prompt text, since there is no dedicated brainstorm tool).

### `agy -p` invocation patterns

```bash
# Resolve the seat once per block; every call below places $AGY_MODEL before -p.
# Unquoted $AGY_MODEL / $PIN is deliberate (bash word-splitting; zsh needs ${=AGY_MODEL}).
SEAT=~/.claude/skills/_meta/seat_model.py
# Script context: stop on failure — an empty $AGY_MODEL would run every call below unpinned.
AGY_MODEL="$(python3 "$SEAT" argv --role consultant_main --provider agy)" || exit 1

# Basic headless mode (plain-text stdout — no JSON output mode)
(d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "Review this code for security issues" < /dev/null)

# With file content: read it first, then inline it. Piped stdin never reaches the model.
C="$(cat src/main.py)" && (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "Find N+1 query problems:
$C" < /dev/null)

# A project review: inline its files, at most 100 KB per call. Never --add-dir or cd into a live repo.
C="$(cd "$PROJECT_DIR" && git ls-files -z '*.py' | xargs -0 tail -n +1)" && (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "Advisory only — do not modify any files; answer on stdout. Review these files for security issues:
$C" < /dev/null)

# Structured brainstorming — frame the methodology inside the prompt
(d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "Use SCAMPER to generate ideas for reducing checkout abandonment. List each lens separately." < /dev/null)

# Parallel with Codex (triple-model validation)
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX) || exit 1
AGY_WORK=$(mktemp -d /tmp/agy-XXXXXXXXXX) || exit 1

# Codex seat: consultant_main is the codex std tier (the astra reserve), metered, so no --ephemeral.
# A repo-exploring -C call is a budgeted `consult`. codex_top_seat is the function in "Seat Models": paste its preamble into this
# same Bash call (shell functions do not survive between calls). Its exit-3 path writes a
# CODEX_SUBSTITUTE line into review.md -> serve the seat with a fresh Claude main-tier agent on the same brief.
declare -F codex_top_seat > /dev/null || { echo "define codex_top_seat (Seat Models) in this Bash call first" >&2; exit 2; }
printf '%s\n' "Review for security issues" > "$CODEX_WORK/brief-review.md"
codex_top_seat review consultant_main consult "" "" \
  "$CODEX_WORK/brief-review.md" "$CODEX_WORK/review.md" -C "$PROJECT_DIR" -s read-only &
C="$(cd "$PROJECT_DIR" && git ls-files -z '*.py' | xargs -0 tail -n +1)"
(cd "$AGY_WORK" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "Review these files for security issues:
$C" > review.txt < /dev/null) &
wait
```

### `agy` Availability Check

```bash
AGY_AVAILABLE=$(agy --version 2>/dev/null && echo "yes" || echo "no")
```

Cache for the session like the Codex check. Both can be checked in parallel at session start.
