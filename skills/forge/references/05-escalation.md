# Forge reference — codex escalation

Any checklist step where Claude is stuck (the Codex Escalation hard rule) — previous: two failed Claude attempts; next: the step you were on, or the user when the escalation also fails.
When this file is read, return to the SKILL.md checklist.

The watchdog, classify, substitution and Quota wait rules this file cites as "above" are in `references/03-codex-seats.md`, under "Spawning Codex Agents".

## Contents

- Codex Escalation (When Claude Is Stuck): the escalation seat, its own role and budget use, the bash block and the brief
- Escalation Termination

#### Codex Escalation (When Claude Is Stuck)

When Claude agents fail to solve a problem after 2+ attempts or enter circular reasoning:

**The escalation seat runs only through the guarded `codex_top_seat` block below (#282 R7).** `/codex:rescue` is an ungated convenience — no seat pin, no admit gate, never for a protected seat; plugin not installed on this host (S080 D11) — so it is never the escalation chain's Codex attempt.

Same watchdog, classify and substitution rules as the design-exploration calls above, on its OWN role and budget (the astra reserve, F2): the `escalation` role — codex TOP @ `max` at EVERY size (3600s runaway cap from `seat_model.py timeout`, no `--ephemeral`) — admitted as the budget use `escalation` (TOP, 1 per cycle), so it never competes with the approach explorer's `consult`. It is started with `run_in_background` like every codex call. When the cycle's escalation slot is already spent, or TOP is unavailable, `argv --use escalation` exits 3 and the block writes a `CODEX_SUBSTITUTE:` line. The lead then runs the escalation brief on a fresh-context, read-only Claude main-tier agent (`Agent(subagent_type="general-purpose", model="<model from that line>")`; the brief forbids edits). That substituted attempt IS the Codex attempt of the escalation chain: do not also retry codex, and never re-seat the call on a codex std or support model. A `CODEX_QUOTA_WAIT:` line (codex out of quota) follows the Quota wait bullet above before any stand-in.

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX) || exit 1

# codex_top_seat NAME ROLE USE SIZE KEY BRIEF_FILE OUT_FILE [codex exec flags...] -- one TOP codex seat:
# SIZE and KEY are each "" when the caller has none, and an empty one passes no flag.
# admit + pin (exit 0 run codex, 3 substitute, else gap), then classify any failed call (retry = re-run
# only the exec line, once; substitute = record it; gap = the gap line). Budget key's project:
# $PROJECT_DIR, else the working directory.
# RUN THE BASH TOOL CALL THAT SOURCES AND RUNS THIS IN THE BACKGROUND (run_in_background: true) and act on
# the completion notification. A FOREGROUND Bash tool call is capped at 600 s however large the seat's own
# cap is, and that cap -- not the model -- is what killed two healthy gpt-5.6-sol sessions mid-work (D24).
. "$HOME/.claude/skills/_meta/codex_top_seat.sh" 2>/dev/null
if ! declare -F codex_top_seat >/dev/null; then
  echo "CODEX_GAP: codex_top_seat.sh missing or unreadable; no codex seat was started" >&2
  exit 1
fi

cat > "$CODEX_WORK/escalation-brief.md" << 'BRIEF'
# Escalation: Claude agents are stuck on [PROBLEM]

## What was tried
[LIST APPROACHES THAT FAILED AND WHY]

## The specific blocker
[DESCRIBE THE EXACT ISSUE]

## Project context
[KEY FILES, ARCHITECTURE]

## What we need
A fresh approach to solve this. Don't repeat what was already tried.
Think differently — challenge the assumptions that led to the dead end.
Read-only: diagnose and propose; do not modify any file.
Provide a fresh solution.
BRIEF

# escalation (codex TOP @ max at every size: the astra reserve), no --ephemeral, admitted as its own
# `escalation` use (F2). SIZE is EMPTY: the escalation role is not sized, so a size would move nothing -- an
# escalation takes codex TOP on a light cycle too, which is what the reserve is for.
codex_top_seat escalation escalation escalation "" "" \
  "$CODEX_WORK/escalation-brief.md" "$CODEX_WORK/escalation-result.md" -C "$PROJECT_DIR" -s read-only
```

### Escalation Termination

Max escalation chain: Claude 2 attempts -> Codex 1 attempt (or the Claude main-tier agent substituting for it) -> user.

**A missing seat script is a gap too.** When the Bash call exits non-zero with the stderr line `CODEX_GAP: codex_top_seat.sh missing or unreadable; no codex seat was started`, the guard stopped it before the escalation seat ran and no seat output file was written: every seat of that call is a gap, so the Codex attempt has failed and the steps below apply.

If the Codex attempt fails — codex or its Claude main-tier substitute returns no usable answer, or the block writes a `CODEX_GAP:` (a broken seat registry, or a codex failure the classifier calls a gap):
1. Present the problem to the user with ALL attempted approaches
2. Include what Claude tried, what Codex (or the Claude main-tier agent substituting for it, with the substitution reason) tried, and why both failed
3. Ask the user for direction
4. Do NOT retry automatically. Do NOT loop back to Claude.
