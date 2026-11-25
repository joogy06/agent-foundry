# Forge reference — agy analyst and convergence

Checklist step 6 — previous: step 5b, the hard rules checkpoint; next: step 7, present design.
When this file is read, return to the SKILL.md checklist.

Convergence reads the Codex seats' output files and cites "the Quota wait bullet above": both are in `references/03-codex-seats.md`. "Stage 1.5" is the verification pass in `references/08-spec-review.md`.

## Contents

- Spawning Antigravity (agy) Analyst: the stdin rule, the sandbox rule and flag order, the model rule, the call cap, the three call shapes
- When to use agy vs Codex
- Converging Triple-Model Findings

#### Spawning Antigravity (agy) Analyst (MEDIUM+ — in parallel with Claude and Codex agents)

Check `agy` availability first: `command -v agy`. If unavailable, skip and note the gap.

`agy -p` returns **plain text on stdout** — the lead parses the text reply, not JSON fields.
Raise `--print-timeout` above the 5m default for long analyses. Append a `served_by` probe
line to the prompt and capture it — self-reported model identity is unreliable.

**STDIN RULE (root-caused 2026-06-05, #135):** headless `agy` MUST have stdin closed —
`< /dev/null` on every call. agy waits on non-TTY stdin until EOF *before* the model call, and piped
text never reaches the model (2026-11-01, 1.4.12, rc 0); in
background/harness shells stdin never EOFs, so agy hangs forever producing 0 bytes and
`--print-timeout` never fires (it only guards the print phase). Also wrap in a shell `timeout`.

Prompt size is NOT a factor (verified: 30-char prompt hung; 11KB prompt with `< /dev/null`
answered in 9s).

**SANDBOX RULE (S052 rogue-commit incident, #157; #366):** the agy analyst is a READ-ONLY role, so
it is Pattern 1: `--sandbox --mode plan` from an empty cwd, content inline in `-p` (at most 100 KB per call), no `--add-dir`.
In S052 an un-sandboxed "analyst" auto-authored and git-committed broken code mid-design (HARD-GATE
violation). Codex is unaffected (it already runs `-s read-only`). FLAG ORDER (root-caused 2026-07-02):
`--sandbox` and every other flag BEFORE `-p`, prompt LAST — `agy -p --sandbox "X"` silently runs
UN-sandboxed with the literal prompt `--sandbox` and discards "X" (agy then improvises from implicit
memory — the "does work instead of consulting" failure mode). Measured 2026-11-01 on 1.4.12:
`--sandbox` restricts only the shell, `--mode plan` removes native writes and the shell, and the cwd
is the workspace, so a call from a repo can read that repo. Open the prompt with "Advisory only — do
not modify any files; answer on stdout". The table is in the `antigravity-cli` skill.

**MODEL RULE:** the model comes from the seat registry, never the account default (an older Gemini model of a family the roster no longer allows). `seat_model.py argv --role consultant_main --provider agy` prints `--model gemini-<newest>-<family>-high` (rev 6: `gemini-4-argon-high`). It enforces the agy family rule (`model_roster.AGY_FAMILY`) in code, and on failure it exits non-zero with empty output, so the `&&` never runs agy unpinned. `$AGY_MODEL` goes before `-p` like every other flag.

**CALL CAP:** agy has no machine-readable quota, so a forge round makes at most **3** agy calls. The first capacity error (for example "at capacity" or a 429) stops further agy calls for that round. Record it as a provider gap rather than retrying into the same wall.

```bash
# Antigravity (agy) Analyst — independent third-model analysis (consultant_main: TOP-argon -high)
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "You are an analyst for [TASK].
Project context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Analyze: 1. Architecture trade-offs  2. Scalability limits  3. Security surface
4. What approaches work best at scale for this pattern?
Be specific and cite real-world precedents where possible.
At the very end print one line: SERVED_BY=<model-id-you-are-running-as>." < /dev/null)

# For codebase context, inline the relevant files, read first (the agy analyst has no workspace):
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && C="$(tail -n +1 [FILES])" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "Advisory only — do not modify any files; answer on stdout.
Review these files for [TASK].
Focus on: cross-cutting concerns, hidden coupling, N+1 patterns, missing error boundaries.
$C" < /dev/null)

# For multi-methodology brainstorming (frame the methodology in the prompt itself):
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "Brainstorm approaches for [TASK] using the Six Thinking Hats methodology —
work through White (facts), Red (intuition), Black (caution), Yellow (benefits),
Green (alternatives), and Blue (process) in turn, then summarise." < /dev/null)
```

**When to use agy vs Codex**: `agy` is a useful independent third model for architecture analysis, codebase review (inline the files), and multi-methodology brainstorming. Codex excels at focused code review, devil's advocate challenger work, and prototype exploration.

#### Converging Triple-Model Findings

When collecting results, the lead MUST:
1. Read Claude challenger output AND Codex challenger output (`$CODEX_WORK/challenger.md`) AND agy analyst output
2. Read Codex approach exploration (`$CODEX_WORK/approach.md`)
3. Identify where models **agree** (high confidence) vs **disagree** (needs deeper analysis)
4. Flag disagreements to the user: "Claude, Codex, and agy disagree on X — here are all perspectives"
5. Weight all model findings equally — each has different blind spots and strengths
6. agy findings that cite real-world precedents — flag these as evidence (and verify per Stage 1.5)
7. A `CODEX_SUBSTITUTE:` first line in a codex output file is a **substitution**, not a gap: that seat ran as a fresh Claude main-tier agent on the same brief. Attribute its findings to `<model from that line> (substituting codex: <reason>)`, weight them like any other seat's, and call the round a **Claude + Google round (provider gap: OpenAI)** in the convergence and in the design presentation — the Claude challenger and the substitute are two Claude contexts, so agreement between them is weaker evidence than cross-provider agreement. A `CODEX_QUOTA_WAIT:` line is neither yet: wait, re-admit or stand in as the Quota wait bullet above says, then attribute whatever served. A `CODEX_GAP:` line or a stopped agy call is a **provider gap**. Name the seat and the reason in the convergence and in the design presentation. Neither a gap nor a substitution is consent.
8. Where the round ends in ONE design direction chosen from rival approaches, choose it under **CONV-1** (`~/.claude/skills/_meta/convergence-rule.md`). Run its applicability test first and follow its exclusion table when the test fails; the rule is defined there and is not restated here. Record the winning approach and each borrowed part by name, with the approach it came from, in the design presentation.
