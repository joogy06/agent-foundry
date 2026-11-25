---
name: cross-cli-deliberation
description: Use when consulting one or more external CLIs (Codex, Antigravity (agy), Copilot) for second opinions, challenger reviews, design ratification, or any decision where sycophancy / "I-was-asked-so-I-produced-something" is a real failure mode. Implements a two-gate protocol — null-hypothesis ballot before any deliberation, then burden-of-falsification on every CHANGE_NEEDED claim — that converts cross-CLI consultation from echo-chamber into genuine deliberation. Trigger on - "ask Codex / agy what they think", "second opinion", "tiebreak between models", forge design ratification, alf review hand-offs, bob's arbiter gates.
---

# Cross-CLI Deliberation

A protocol for getting genuine deliberation — not theatre — from multi-CLI consultation. Solves the "AI assistants produce something useful when asked, even when 'this is fine, change nothing' is the right answer" failure mode.

Designed and ratified through self-application: see `references/origin-trace.md` for the deliberation that produced this skill.

## When to use

- **forge** design phase: ratifying a synthesis with one or more external CLIs before locking
- **alf** review cycles: getting independent verdicts on staleness / drift findings before recommending changes
- **bob** arbiter gates (verification-arbiter, design-drift-arbiter, visual-arbiter): when a build fails verification and you need an independent verdict on whether the failure is real or noise
- Any moment where the orchestrator wants a second opinion AND has skin in the answer (you wrote the design, you don't trust your own evaluation of it)
- Tiebreak rounds when consultants disagree

## When NOT to use

- Pure information lookup ("how does X work in library Y?") — no deliberation needed, just route to the relevant CLI
- TRIVIAL or SIMPLE tasks (single-file edit, clear output) — overkill
- One-off creative tasks where divergence is the goal, not convergence (use `adversarial-team-brainstorm` instead)
- When you do NOT have skin in the answer — sycophancy is only a risk when the orchestrator's framing biases the consultant

## The two gates (overview)

```
[Artifact + decision context]
       │
       ▼
┌─────────────────────────────────────────┐
│  Gate 1: Null-hypothesis ballot          │
│  Each consulted CLI files a private      │
│  structured ballot BEFORE seeing peers   │
│  or orchestrator opinion.                │
│                                          │
│  All ACCEPT_AS_IS → ship as-is.          │
│  Any CHANGE_NEEDED → enter Gate 2.       │
└─────────────────────────────────────────┘
       │
       ▼ (only if any CHANGE_NEEDED above threshold)
┌─────────────────────────────────────────┐
│  Gate 2: Burden of falsification         │
│  Each dissenting consultant must ship    │
│  admissible evidence. Orchestrator       │
│  verifies/executes. No evidence →        │
│  Null Verdict (= validation).            │
└─────────────────────────────────────────┘
       │
       ▼
[Synthesis: ship-as-is OR adopt verified patch]
```

## Gate 1 — Null-hypothesis ballot

**The principle:** "no change needed" is the default incumbent that any proposed change must defeat. Pushback must be structural, not theatrical.

Send to each consulted CLI:
- The artifact under review
- Decision context, constraints, success criteria
- **NEVER** the orchestrator's opinion or preferred outcome

Require this ballot back:

```
Verdict:    ACCEPT_AS_IS / REJECT_PREMISE / CHANGE_NEEDED
Confidence: 0–100
Burden met? — what evidence would justify changing this?
              has that evidence been provided in the artifact itself?
Expected loss:
  - if we adopt and shouldn't have:
  - if we don't adopt and should have:
Minimum acceptable action: no-op / clarifying question / test only / patch / redesign
```

Plus a self-check section declaring on at least these failure modes:
- **Ego**: defending a prior position as inviolate
- **Capture**: caving to the synthesis because it elevates the consultant's prior contribution
- **Capture by capability**: caving to a higher-tier peer model
- **Sycophancy of dissent**: producing CHANGE_NEEDED to satisfy "produce something useful," even with no admissible evidence

Full ballot template + spawn-prompt examples: `references/ballot-template.md`.

**Threshold for entering proposal mode:** ≥1 model votes `CHANGE_NEEDED` at confidence ≥ 60. Tunable per caller.

## Gate 2 — Burden of falsification

**The principle:** a `CHANGE_NEEDED` ballot must ship verifiable evidence under at least one admissible class. No admissible evidence → **Null Verdict** (failed falsification = strongest validation).

Three admissible evidence classes:

1. **Reproduction** (any of three sub-forms):
   - (a) executable test — fails on current state, passes on proposed change
   - (b) procedural trace through the protocol/system on a representative artifact, showing observable failure mechanics
   - (c) failure-mechanics trace with minimal remedy (concrete steps + concrete patch)
2. **Constraint violation** — direct quote from MEMORY.md / CLAUDE.md / project rules / declared constraints
3. **Efficiency regression** — measurable complexity / token cost / latency increase not offset by gain

**Orchestrator verification:** the orchestrator MUST execute or check the evidence before accepting it. Run the test. Check the quote. Validate the regression. If the evidence does not reproduce as claimed, flag the consultant for "hallucinatory helpfulness" and nullify its ballot.

Full evidence taxonomy + verification protocol: `references/evidence-taxonomy.md`.

## Quorum rule

A Claude main-tier consultant substituting for codex (see "Call budget" below) is PRESENT, not absent: count its ballot, label it, and name the OpenAI provider gap.

If a consultant is unreachable after the retry budget (typical CLI auto-retry: 10× backoff for capacity errors):
- **Declare absence explicitly** in the synthesis output. Never silently treat absence as ACCEPT_AS_IS.
- Then choose one path:
  - **Defer**: wait for capacity, retry later
  - **Single-ballot mode**: proceed with available consultants, mark synthesis as low-quorum, escalate to user if verdict is non-trivial
  - **Escalate to user**: surface the absence and the available verdict, let user adjudicate

## Served-by capture

Model identity from `-m <model>` flag and from the model's free-text self-identification are both **unreliable**. Always:

- Append a structured probe line to the consultation prompt:
  > `At the very end of your response, append a single line: served_by=<your model id>`
- Parse the trailing `served_by=` from the response
- Log it alongside the verdict — capability tier affects verdict quality

See `antigravity-cli` and `codex-orchestration` skills for CLI-specific quirks. Self-reported model identity is unreliable across CLIs — always capture `served_by` observationally rather than trusting a requested model.

## Sycophancy measurement

To detect protocol erosion over time, periodically run seeded test cases:

| Probe | What it measures |
|---|---|
| Clean artifact, no needed change | Intervention false-positive rate (consultant should ACCEPT_AS_IS) |
| Bad orchestrator premise | Premise-rejection rate (consultant should REJECT_PREMISE) |
| Suggestive prompt wording | Agreement-with-framing rate (consultant should hold its ground) |
| Post-reveal: show orchestrator's opinion after ballot lock | Drift rate (verdict should NOT change just because orchestrator's view is now visible) |
| Weak evidence ballot | Proposal-inflation rate (severity should match evidence strength) |

Full test cases + scoring: `references/sycophancy-tests.md`.

## Invocation pattern

```bash
# Canonical pattern for Antigravity (agy) consultant
# agy returns plain text on stdout (no env prefix — it authenticates itself). The MODEL comes from
# the seat registry (consultant_main = newest roster-family -high, rev 6 argon; the agy family rule enforced in code), placed
# before -p; the && means an unresolved pin never runs agy on the account default.
# --sandbox --mode plan from an empty cwd is MANDATORY: consultants advise only; un-sandboxed agy has
# live write/git tools and may act on the ballot instead of voting (antigravity-cli SANDBOX RULE, #157, #366).
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && PROMPT="$(cat ballot-prompt.md)" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "$PROMPT" < /dev/null) > /tmp/agy-ballot.md

# Canonical pattern for Codex consultant
# MODEL and EFFORT are pinned PER CALL by the seat registry — never inherit the config default,
# which is whatever the interactive TUI last persisted. consultant_main = the codex std tier @ xhigh
# (the astra reserve, roster rev 4), the FLOOR for ballot/challenger verdicts (codex-orchestration
# "Reasoning-Effort Tiers"); the registry CLI has no --effort flag, so do not append a raw effort
# override after $PIN.
# Codex seats run WITHOUT --ephemeral (only a non-ephemeral call meters quota; the ballot therefore
# persists in ~/.codex/sessions — no secrets). `seat_model.py argv --use ballot` admits and pins
# each ballot in one call: exit 0 runs codex; exit 3 = codex cannot serve it (budget spent, the
# limit reached, CLI missing, no eligible model) -> the block writes CODEX_SUBSTITUTE (line 2 of
# stdout = the Claude model) and runs no codex call; a QUOTA refusal (#322, no 70% threshold any
# more) writes CODEX_QUOTA_WAIT instead: notify-claim + notify / await-reset / re-admit once / stand in
# on exit 4, 6 or 3, per codex-orchestration "Seat Models"; anything else -> CONSULTANT_ABSENT. Never substitute a codex std or support model (same quota pool).
# Retries belong to `codex_quota.py classify`: a timeout or an empty ballot re-runs ONLY the codex
# exec line, once (same model, same admission); a quota/rate-limit stop, auth failure, missing CLI
# or second timeout substitutes; any other exit is an absence. "Selected model is at capacity" on a
# codex error line retries once, then substitutes (reason capacity_twice).
# "A timeout" here means the WATCHDOG's idle stop (exit 111): the ballot went silent for 300s. A
# ballot that ran to its runaway cap while still producing output (exit 112) is an ABSENCE on the
# first hit, never a retry and never a substitution -- it is not the retryable kind of stop (D24).

# codex_top_seat NAME ROLE USE SIZE KEY BRIEF_FILE OUT_FILE [codex exec flags...] -- one TOP codex seat:
# SIZE and KEY are each "" when the caller has none, and an empty one passes no flag.
# admit + pin (exit 0 run codex, 3 substitute, else absence), then classify any failed call (retry = re-run
# only the exec line, once; substitute = record it; gap = the absence line). Budget key's project:
# $PROJECT_DIR, else the working directory.
# RUN THE BASH TOOL CALL THAT DEFINES AND RUNS THIS IN THE BACKGROUND (run_in_background: true) and act on
# the completion notification. A FOREGROUND Bash tool call is capped at 600 s however large the seat's own
# cap is, and that cap -- not the model -- is what killed two healthy gpt-5.6-sol sessions mid-work (D24).
codex_top_seat() {
  local NAME="$1" ROLE="$2" USE="$3" SIZE="$4" KEY="$5" BRIEF="$6" DEST="$7" OUT RC ACT="" TRY TO MDL; shift 7
  local SEAT="$HOME/.claude/skills/_meta/seat_model.py" QUOTA="$HOME/.claude/skills/_meta/codex_quota.py"
  local WATCH="$HOME/.claude/skills/_meta/codex_watch.py" TRIES="1 2" SUBUSE="$USE" RETRY RRC RTO AID="" AKEY=""
  local L2 WA RIN UU UK UM
  # The receipt: `<admission id> <key>` of this seat's LIVE admission, written atomically by argv. DEST must be
  # unique per seat (the receipt is "$DEST.admit"). Read in a subshell, so this function's "$@" is untouched.
  rm -f "$DEST.admit"
  # SIZE and KEY are EMPTY when the caller has none, and an empty one passes NO FLAG AT ALL. Sizing is
  # opt-in: with no --size the registry reads no size file, so an unsized seat takes the TOP model even on
  # a small cycle -- and passing a literal size instead of nothing would record `size_source: routing`, a
  # routing decision nobody made. An empty KEY leaves the budget key the project derives; a caller that
  # mints its own passes it here, so its seats share ONE key and spend their OWN budget, not the round's.
  # #322: --await-quota -- a QUOTA refusal records no stand-in yet; it prints the reset lines and
  # `substitution=deferred`, and the seat's owner waits (see CODEX_QUOTA_WAIT below).
  OUT="$(python3 "$SEAT" argv --role "$ROLE" --provider codex --use "$USE" --receipt-file "$DEST.admit" \
           --await-quota ${SIZE:+--size "$SIZE"} ${KEY:+--cycle-id "$KEY"} \
           --project-root "${PROJECT_DIR:-$PWD}")"; RC=$?
  # The timeout is the seat registry's, asked only AFTER an admitted `argv --use` (asked first, a no-eligible
  # substitution would become a gap) and never as a second `argv` stdout line: $OUT is word-split into
  # `codex exec $OUT`, so an extra line would become a prompt. No timeout -> the gap line; codex never runs.
  if [ "$RC" -eq 0 ]; then
    TO="$(python3 "$SEAT" timeout --role "$ROLE" --provider codex)" || { ACT="seat_model timeout exit $?"; RC=1; }
    MDL="$(set -- $OUT; echo "$2")"     # the pinned model, named once: progress line and substitution record
    AID="$(set -- $(cat "$DEST.admit" 2>/dev/null); echo "${1-}")"
    AKEY="$(set -- $(cat "$DEST.admit" 2>/dev/null); echo "${2-}")"; AKEY="${AKEY:-$KEY}"
  fi
  if [ "$RC" -eq 0 ]; then
    while [ -n "$TRIES" ]; do
      for TRY in $TRIES; do
        # D24: the watchdog stops the call on INACTIVITY -- no stdout, no stderr and no session-rollout write
        # for the idle window -- so "thinking hard" is no longer killed as "hung". The registry timeout is
        # passed as the RUNAWAY cap only, never as the normal stop, and the watchdog prints a progress line to
        # this call's stderr while it waits. Its exits: 111 went silent (the retryable stop, classified as a
        # timeout), 112 ran away while still active (a gap on the FIRST hit, never a substitution), anything
        # else is codex's own status passed straight through.
        python3 "$WATCH" --mode codex --hard-cap "$TO" --model "$MDL" \
          --stdout-file "$DEST.stdout" --stderr-file "$DEST.stderr" \
          -- codex exec "$@" $OUT -o "$DEST" "$(cat "$BRIEF")"; RC=$?
        ACT="$(python3 "$QUOTA" classify --exit-code "$RC" --attempt "$TRY" $([ "$RC" -eq 111 ] && echo --timed-out) \
                 --stderr-file "$DEST.stderr" --output-file "$DEST" --prompt-file "$BRIEF")" || ACT=classify_error
        [ "${ACT%% *}" = retry ] || break
      done
      TRIES=""
      # U2, the astra reserve: a seat that failed on CAPABILITY (capacity or a malformed answer, twice) gets ONE
      # attempt on the codex TOP. seat_model decides whether that is a retry at all -- it proves the failed
      # attempt from its receipt (an admitted std row of this role, use and key), wants a DIFFERENT pin that
      # bills the TOP class, and admits it as `top_retry` on the FORGE CYCLE (1 per cycle) -- and records the
      # event row. The TOP timeout is asked FIRST, so a failed lookup spends no retry slot. Exit 0: run it ONCE,
      # classified as attempt 2 so it has no inner retry, and SUBUSE stops a second entry; the receipt now names
      # the retry's own admission and key. Exit 3: the D6 line, already recorded. Anything else: the original
      # failure is substituted below. Quota, auth, budget, timeout and gap outcomes never reach this branch.
      case "$SUBUSE:$ACT" in
        "$USE:substitute capacity_twice"|"$USE:substitute malformed_twice")
          RRC=1
          if RTO="$(python3 "$SEAT" timeout --role "$ROLE" --provider codex --top-retry)"; then
            rm -f "$DEST.admit"   # only the retry's own receipt may follow
            RETRY="$(python3 "$SEAT" argv --role "$ROLE" --provider codex --use "$USE" --top-retry \
                       --failed-admission-id "$AID" --failed-reason "${ACT#substitute }" \
                       --receipt-file "$DEST.admit" --await-quota ${AKEY:+--cycle-id "$AKEY"} \
                       --project-root "${PROJECT_DIR:-$PWD}")"; RRC=$?
          fi
          if [ "$RRC" -eq 0 ]; then
            OUT="$RETRY"; MDL="$(set -- $OUT; echo "$2")"; SUBUSE=top_retry; TRIES=2; TO="$RTO"
            AKEY="$(set -- $(cat "$DEST.admit" 2>/dev/null); echo "${2-}")"; AKEY="${AKEY:-$KEY}"
          elif [ "$RRC" -eq 3 ]; then
            OUT="$RETRY"; ACT=top_retry_substituted
          fi ;;
      esac
    done
    case "$ACT" in
      "ok -") ;;
      top_retry_substituted) RC=3 ;;
      # the substitution names the key its admission was billed to (the receipt's, else the caller's KEY): a
      # failed TOP retry keeps its forge-cycle key, a tournament or ballot seat its own
      "substitute "*) OUT="$(python3 "$SEAT" substitute --role "$ROLE" --use "$SUBUSE" --reason "${ACT#substitute }" \
                               --requested-model "$MDL" ${AKEY:+--cycle-id "$AKEY"} \
                               --project-root "${PROJECT_DIR:-$PWD}")"; RC=$? ;;
      # classify itself failed: after a codex exit 0 keep codex's output in $DEST; after a failed call, a gap
      classify_error) if [ "$RC" -eq 0 ]; then
                        echo "CODEX_CLASSIFY_ERROR: $NAME: classify failed after codex exit 0; $DEST keeps its output" >&2
                      else RC=1; fi ;;
      *) RC=1 ;;
    esac
  fi
  # Exit 3 prints the reason on LINE 1 and the Claude model on LINE 2; a quota refusal (#322) appends
  # key=value lines after them, so the model is read as line 2, never as the last line.
  L2="${OUT#*$'\n'}"; L2="${L2%%$'\n'*}"
  case "$RC:$OUT" in
    0:*) ;;  # codex answered: $DEST holds its output
    3:*$'\n'substitution=deferred*)
       WA="${OUT##*$'\n'wait_advice=}"; WA="${WA%%$'\n'*}"
       RIN="unknown"; case "$OUT" in *$'\n'resets_in_s=*) RIN="${OUT##*$'\n'resets_in_s=}"; RIN="${RIN%%$'\n'*}" ;; esac
       # #322 fix round 1: the use, key and codex model a later `substitute` must name (a TOP retry's own)
       UU="${OUT##*$'\n'use=}"; UU="${UU%%$'\n'*}"; UK="${OUT##*$'\n'key=}"; UK="${UK%%$'\n'*}"
       UM="-"; case "$OUT" in *$'\n'requested_model=*) UM="${OUT##*$'\n'requested_model=}"; UM="${UM%%$'\n'*}" ;; esac
       printf 'CODEX_QUOTA_WAIT: %s (reason %s; wait_advice %s; resets_in_s %s; stand-in %s; use %s; key %s; requested %s)\nbrief: %s\n' \
         "$NAME" "${OUT%%$'\n'*}" "$WA" "$RIN" "$L2" "$UU" "$UK" "$UM" "$BRIEF" > "$DEST" ;;
    3:*) printf 'CODEX_SUBSTITUTE: %s -> %s (reason %s; provider gap: openai)\nbrief: %s\n' \
         "$NAME" "$L2" "${OUT%%$'\n'*}" "$BRIEF" > "$DEST" ;;
    *) echo "CONSULTANT_ABSENT: $NAME (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;
  esac
}

# ONE key per ballot, minted beside the prompt it votes on, so a ballot spends the `ballot` budget
# instead of the round's single `challenger` admission. That sharing is why a tiebreak, or any ballot
# after forge's own challenger had run, used to find codex refused before it ever asked a question.
BID="$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || true)"
# SHAPE-CHECKED BEFORE USE, never just concatenated: an empty mint would leave the bare prefix `ballot-`,
# which SATISFIES codex_quota.CYCLE_ID_PATTERN -- a malformed key that passes validation and that every
# ballot on the host would then share, quietly recreating the starvation this mint exists to end.
case "$BID" in
  ????????-????-????-????-????????????) BALLOT_KEY="ballot-$BID" ;;
  *) BALLOT_KEY="" ;;
esac
# A RATIFICATION ballot is `complex`: ratifying a design is deliberative work whatever the size of the
# change under review. A non-ratification ballot passes its own declared size here instead.
BALLOT_SIZE=complex
# NO KEY -> NO CALL. A failed mint is an ABSENCE under the quorum rule, never an unkeyed codex call
# that would silently fall back to the round's budget key.
if [ -n "$BALLOT_KEY" ]; then
  codex_top_seat codex consultant_main ballot "$BALLOT_SIZE" "$BALLOT_KEY" \
    ballot-prompt.md /tmp/codex-ballot.md -s read-only
else
  echo "CONSULTANT_ABSENT: codex (ballot key mint failed; no unkeyed codex call)" > /tmp/codex-ballot.md
fi

# Run them in parallel via background tasks; collect both before synthesizing
```

Where `ballot-prompt.md` follows the template at `references/ballot-template.md`.

**Call budget.** Both consultants resolve through `skills/_meta/seat_model.py`, so what serves right now is `python3 ~/.claude/skills/_meta/seat_model.py emit --json`. Codex is admitted as a **`ballot`** against **the ballot's OWN minted key** (`ballot-<uuid>`, minted beside `ballot-prompt.md`), which allows **1 TOP call and 2 std** per ballot (the codex consultant is `consultant_main`, the codex std tier @ `xhigh` since the astra reserve, so a ballot spends std; a capability failure gets the one Sol → TOP retry before the substitute). Until S081 revision 4 a ballot was admitted as a `challenger` against the *forge cycle id*, which allows exactly one — so a tiebreak round, or any ballot after forge's own codex challenger had already run, usually found codex refused before it could vote, and the deliberation silently lost its OpenAI arm to a budget collision rather than to a real quota limit. A refused or failed ballot still substitutes exactly as before: `/tmp/codex-ballot.md` starts with `CODEX_SUBSTITUTE:` and the orchestrator spawns a fresh-context Claude main-tier consultant, `Agent(subagent_type="general-purpose", model="<model from that line>")`, with the SAME `ballot-prompt.md` and no view of the other ballot or of the orchestrator's opinion. That substitute is PRESENT for the quorum rule. Its ballot is labelled `<model from that line> (substituting codex: <reason>)`, and the deliberation is recorded as Claude + Google with the OpenAI provider gap named. The two-gate protocol is unchanged: the substitute's ballot passes Gate 1 and Gate 2 exactly like any consultant's. A substitute does not spend the astra budget; it is recorded in `~/.claude/projects/<slug>/astra-budget.jsonl` for the 2026-09-28 plan review, and it is never a codex std or support model — every codex model draws the same plan quota. Only a `CONSULTANT_ABSENT:` line (a broken seat registry, or a codex failure the classifier calls a gap) is an absence under the quorum rule, never a silent pass. Inside a forge round agy gets at most 3 calls, and a capacity error stops further agy calls for that round; agy is never substituted.

## Fast path — `cross-cli-deliberation` workflow (S055, optional, main-loop only)

When the orchestrator is the main loop with `capabilities.workflow_tool` true
(`probe.sh get capabilities.workflow_tool` AND `probe.sh context == main-loop`
— the ONLY capability API; `capabilities.*` alone never authorizes), the two
gates MAY run as the `cross-cli-deliberation` saved workflow: parallel Gate-1
ballot wrapper stages (`ballot.v1`) → Gate-2 evidence wrappers (`evidence.v1`)
→ deterministic `assemble` (`deliberation-record.v1`). The schemas are at
`schemas/`; they are CONSUMED by `ratify-design` (never forked).

**WP-2 live-shape constraints (binding):**
- **agy is UNREACHABLE from workflow stages** and codex-from-stage is UNTESTED —
  so consultant transcripts are **PRE-LAUNCHED inline by the caller** (using the
  Invocation pattern above, with the full guard set) and passed via
  `args.consultant_transcripts`. A ballot wrapper stage only EXTRACTS the literal
  ballot from the supplied transcript; it NEVER makes a live external call.
- **Command custody is args-supplied** (`consultant_cmds`) — no command line is
  embedded in the workflow file.
- **Tests are NEVER executed in a stage** (trusted-runner is bob-only, CB3): an
  `executable_test` reproduction returns `needs_inline_verification`; the inline
  caller runs it under trusted-runner discipline.
- This workflow is `MODE=bridge`-incompatible (family bridge rule): bridge hosts
  use the inline fallback for all external calls.

Stays inline: ballot-prompt authoring + the no-orchestrator-opinion self-check;
quorum fallback judgment; synthesis + escalation; consultant nullification.

## Context asymmetry (the framing-bug rule)

Consultants see ONLY the files passed to them. **An unstated constraint is a
non-existent one** from the consultant's vantage; a verdict that violates an
unstated constraint is a FRAMING BUG, not a model error — fix the context file
and re-ballot, do not penalize the consultant. Always pass the decision context,
constraints, and success criteria; NEVER pass the orchestrator's preferred
outcome (null-hypothesis discipline).

## Synthesis logic

After all ballots are collected (and any CHANGE_NEEDED evidence is verified):

```
all ACCEPT_AS_IS                    → ship as-is, no change
any CHANGE_NEEDED + verified evidence → adopt the patch
any CHANGE_NEEDED + bogus evidence    → flag consultant, nullify ballot, re-evaluate
all REJECT_PREMISE                   → escalate to user; the question itself is wrong
mixed verdicts at top tier           → tiebreak round (see "Worked example" — D4 in origin-trace)
quorum below threshold               → declare absence, fall back per quorum rule
```

The orchestrator does NOT vote. The orchestrator synthesizes. If the orchestrator wants to override the consultants' verdict, it must surface that to the user — never silently dismiss a consultant's ballot.

## Anti-patterns

| Don't | Why |
|---|---|
| Send the orchestrator's opinion / preferred outcome to consultants before they ballot | Defeats the entire point. Consultants will anchor to your framing. The ballot must precede the reveal. |
| Skip Gate 1 because "this is just a quick sanity check" | The "quick sanity check" framing is exactly when sycophancy hits hardest. The ballot is cheap. Always run it. |
| Accept a CHANGE_NEEDED ballot without verifying the evidence | This is how hallucinatory helpfulness wins. Run the repro. Check the quote. Or nullify the ballot. |
| Silently treat a consultant outage as ACCEPT_AS_IS | Absence is not consent. Declare it. |
| Trust the model's self-identification of which model it is | Verified unreliable. Capture `served_by` via probe; record at the call layer. |
| Apply a strict reading of evidence taxonomy that excludes procedural / structural critiques on non-code artifacts | This is the failure mode the F1 patch was designed to prevent. Reproduction admits procedural traces, not just executable tests. |
| Run more rounds than necessary | Two rounds (independent ballots + tiebreak) is usually plenty. Three+ rounds risks infinite recursion of meta-deliberation. |
| Bypass the protocol for "obvious" cases | "Obvious" is exactly when framing bias is invisible. The protocol's overhead is the price of catching the cases you'd otherwise miss. |

## Worked example

This skill was designed and ratified by applying itself to its own synthesis — a 4-round arc with Codex (gpt-5.5) and a second external CLI consultant. (At the time of the original arc the second consultant was the Gemini CLI; on this host that role is now primarily filled by the Antigravity CLI (`agy`), with gemini remaining an available fallback (kept per user direction 2026-07-10). The model-tier specifics below are preserved only as historical record of that original arc — see `references/origin-trace.md`.) Key findings:

- Round 1 (open): each CLI proposed an independent mechanism (Codex → null-hypothesis gate; the second consultant → burden of falsification). Result: stacked synthesis.
- Round 2 (ratification under self): both voted CHANGE_NEEDED on the synthesis with a 4th evidence class.
- Round 2 (rerun): the SAME ballot produced opposite verdicts depending on which model actually served the request — a CHANGE_NEEDED 85 and an ACCEPT_AS_IS 95. Real protocol-design data point: the model that served a request, not the one requested, drives the verdict — capture `served_by` observationally.
- Round 3 (tiebreak): Codex re-ratified CHANGE_NEEDED at confidence 84, reframing its evidence as a procedural reproduction trace under category 1 — making the F1 patch a clarification of what "reproduction" admits, not an addition.

Full transcript: `references/origin-trace.md`.

## See also

- `forge` — design phase consultations should use this skill for ratification rounds
- `alf` — staleness/drift reviews should use this skill before recommending changes
- `bob` — verification-arbiter, design-drift-arbiter, visual-arbiter gates should use this skill when verdicts are contested
- `adversarial-team-brainstorm` — for divergent ideation (different problem); use this skill for convergent ratification
- `challenger` — for one-side critique (different problem); use this skill for two-sided deliberation
- `codex-orchestration` — Codex CLI invocation patterns
- `antigravity-cli` — Antigravity CLI (`agy`) invocation patterns + host-specific directives
