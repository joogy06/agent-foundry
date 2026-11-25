---
name: adversarial-team-brainstorm
description: >
  Use when a question needs structured-contention exploration across multiple parallel founding / design
  / analysis lenses with cross-fire critique, not a single-agent monologue. Runs a reusable multi-team
  tournament: diverge (N teams generate independently) → cross-fire (teams attack each other) → refine
  (teams revise) → arbiter (synthesizes winners, attaches kill criteria). Reusable by forge (design
  exploration), alf (review cycles), agent-teams (tournament mode), founder-ideation, and any caller
  that needs adversarially-validated outputs with explicit kill criteria. Trigger on: "generate N ideas
  for X", "tournament", "cross-fire review", "four teams on this problem", "adversarial brainstorm",
  "kill-criteria ranked outputs".
---

# Adversarial Team Brainstorm

Multi-team tournament primitive. Spawns N parallel teams with distinct lenses, runs them through a
structured four-round process, and returns ranked outputs with attached kill criteria, first experiments,
and cross-fire attack histories. Reusable by any caller — not tied to a specific domain.

**Scope:** Pure prompt-orchestration primitive. Does NOT own the question, the data feeds, or the
output storage. The caller owns those.

**Callers:**
- `forge` — design exploration tournaments (alternative to the current single-team exploration)
- `agent-teams` — "tournament" mode exposing this primitive for generic orchestration
- `founder-ideation` — generates business ideas with adversarial team quad
- `alf` — adversarial review of skills/code/products
- Any caller that passes a question + team angles + optional context

---

<HARD-RULE>
**Parallel diverge is mandatory.** Round 1 teams MUST run in parallel, not sequentially. Sequential
execution defeats the entire point of divergence — the later team sees the earlier team's output and
anchors to it. Always spawn all teams simultaneously via `Agent` tool (Claude) / `codex exec` (Codex) /
`agy --sandbox --mode plan $AGY_MODEL -p` (Antigravity) calls batched in a single message, every seat's model resolved
through `seat_model` (see "Seat model selection").
</HARD-RULE>

<HARD-RULE>
**Cross-fire must attack.** In Round 2, every attacking team MUST produce ≥1 flaw per output from every
team it reviews. A "looks good" verdict is a failure mode — the attacker is punting. If a team cannot
find a flaw, it must either (a) propose a sharper test that would surface one, or (b) explicitly mark
the output as "attack-resistant under {constraint}" and name the constraint that makes it so. Generic
"this is solid" verdicts are rejected by the arbiter.
</HARD-RULE>

<HARD-RULE>
**Kill criteria are mandatory, not optional.** The arbiter refuses to output a ranked list without
≥2 kill criteria per output. The primitive exists to defeat "polished guru" failure mode — without
kill criteria, every output is equally defendable and equally useless. If the caller passes
`kill_criteria_required: false`, this primitive refuses to run.
</HARD-RULE>

<HARD-RULE>
**Refine round must show before/after.** Round 3 (refine) must produce explicit before/after for each
revised output. No silent rewrites — the attack history must be traceable into the revised version
so the arbiter can judge whether the critique was absorbed or dismissed.
</HARD-RULE>

<HARD-RULE>
**Grounding requirement for high-confidence promotion.** The arbiter cannot promote an output above
`speculative` confidence without ≥1 piece of external data grounding (from `context` feeds — Reddit,
GDELT, user-supplied data, prior wiki entries, etc.). Without grounding, max confidence is
`speculative`. This is the primary mechanism against LLM-vs-LLM hallucination.
</HARD-RULE>

---

## Invocation Contract

### Input

```yaml
question: string                # "Generate 20 SaaS ideas for accountants"
team_angles: list[string]       # lens names, see references/team-angles.md
rounds: int                     # default 4 (diverge, cross-fire, refine, arbiter)
n_per_team: int                 # outputs each team should produce in Round 1
context: map                    # optional data feeds keyed by name
                                # e.g. { reddit_pain_data: ..., gdelt_inflection_data: ..., user_assets: ... }
kill_criteria_required: bool    # default true; false rejected (see HARD-RULE)
team_model_override: map        # optional: { contrarian: "codex", trend_first: "agy" }
                                # default all teams run on Claude
max_total_outputs: int          # optional cap after arbiter synthesis (default = n_per_team * len(team_angles))
output_class: string            # "ideas" (default) | "signals" | "proposals" | "designs"
                                # affects which hard rules apply downstream — ideas require kill_criteria
                                # and first_experiment; signals require only data citation
```

### Output

```yaml
ranked_outputs:
  - content: string              # the idea / proposal / design
    rank: int                    # 1..N
    source_team: string          # which lens produced it, or "hybrid(A+B)" if merged
    kill_criteria: list[string]  # what would invalidate this (min 2)
    first_experiment: string     # smallest test of viability (1-2 sentences)
    attack_history:
      - from_team: string
        severity: enum           # critical | moderate | minor
        issue: string
        fix_proposed: string
    revisions:
      before: string             # the Round 1 version
      after: string               # the Round 3 refined version
      critique_absorbed: list[string]  # which attacks led to which edits
    confidence: enum             # high | medium | low | speculative
    grounding_sources: list[string]  # keys from input.context that supported this
arbiter_notes: string            # synthesis rationale, patterns observed, surviving minority reports
meta:
  rounds_run: int
  teams_used: list[string]
  total_raw_outputs: int         # n_per_team * len(team_angles) before trim
  total_final_outputs: int
  duration_seconds: int
  model_mix: map                 # which model ran which team
```

---

## The Four Rounds

### Round 1: Diverge

Each team generates `n_per_team` outputs **in parallel** and **without seeing the others' work**.

**Per-team spawn prompt template** (the brief block: `skills/_meta/spawn-brief.md`):

<!-- spawn-brief.v1 id=adversarial-team-brainstorm.team -->
```
You are Team {NAME}, running the {LENS} lens.
Your lens definition: {READ references/team-angles.md for {LENS}}

Question: {QUESTION}
Goal: {N} committed proposals answering the question through the {LENS} lens.
Non-goals: other lenses; option lists; files or code changes.
Open questions: none may be returned — decide, note the assumption in the output, proceed.
Done when: exactly {N} outputs, each with the four fields below.
Stop when: the {N} outputs are written, or you are blocked (state the blocker). One round only.

{IF context[team_data_key] exists for this lens:}
Data grounding (you MUST cite at least one source from this feed in each output):
{INLINE THE DATA FEED, e.g. Reddit pain posts, GDELT events, user assets}
{END IF}

Produce exactly {N} outputs. For each output:
1. content: the idea/proposal/design
2. initial_kill_criteria: 2 things that would invalidate it (draft — arbiter will refine)
3. first_experiment: smallest test of viability
4. data_sources: list of grounding cites (reddit:sub/id, gdelt:event_id, user_asset:key, or "unfounded")

CRITICAL:
- Do NOT hedge. Commit to specific proposals, not option lists.
- Do NOT copy the question into the output.
- Do NOT use the other teams' work — you haven't seen it and that's intentional.
- If data grounding is required and you cannot find a cite for an output, mark it "unfounded"
  and the arbiter will filter it.
```

Spawn all teams simultaneously in one message (Claude via `Agent`, Codex via `codex exec`, Antigravity
via `AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_support --provider agy)" && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "..." < /dev/null)` as a background Bash task — `--sandbox` is
mandatory for these advise-only calls, per the `antigravity-cli` SANDBOX RULE; the model of every seat
comes from `seat_model`, below).

### Seat model selection (user directive 2026-09-09; seat registry since S081)

Brainstorming is DELIBERATIVE work, so main seats take each vendor's top model **regardless of how
small the question is**. Seat models resolve through the seat registry
`~/.claude/skills/_meta/seat_model.py`. It reads only home-tier inputs, never the working directory,
a project policy or smart-config, and it is never hardcoded here: TOP selectors follow the vendor's
roster, so `python3 ~/.claude/skills/_meta/seat_model.py emit --json` shows what serves right now.

| Seat | seat_model role | Resolves to | Why |
|---|---|---|---|
| **MAIN seats** (the teams that carry the argument, and every adversarial/contrarian angle) | `consultant_main` | Claude main tier · codex std tier @ `xhigh` (the astra reserve, roster rev 4: codex TOP is kept for escalation and complex review) · agy newest roster-family model `-high` (rev 6: `gemini-4-argon-high`) | A weak challenger produces agreement, which is the exact failure this tournament exists to prevent |
| **Supporting / advisory seats** (breadth angles, large-context sweeps) | `consultant_support` | Claude support tier · codex support tier @ `medium` (no `--ephemeral`, not budgeted) · agy newest roster-family model `-medium` (rev 6: `gemini-4-argon-medium`) | Coverage without spending top tier on every seat |

The tiers are named, not their models: which model each Claude tier and the codex std tier are right
now is the "Currently" column of codex-orchestration "Seat Models" (the roster, `skills/_meta/model_roster.py`).

**agy is a THIRD MAIN provider here, not a fallback.** agy serves ONE Gemini family, the one the
roster names (`model_roster.AGY_FAMILY`; rev 6: Gemini 4 Argon, which replaced flash on eval evidence),
and `seat_model` enforces that family in code. The account default is still an older Gemini
model of a family the roster now forbids, so an agy call without `$AGY_MODEL` silently
seats a forbidden line.

```bash
# agy MAIN seat (consultant_main). A supporting agy seat uses --role consultant_support.
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL \
       -p "You are the <angle> team. Question: ... (content INLINE, this call has no workspace)" \
       < /dev/null)
```

Three providers on main seats is the point: Claude, OpenAI and Google have genuinely different
blind spots. Two providers is a weaker cross-check, and it should be RECORDED as such when one
arm no-shows rather than quietly back-filled by a same-vendor substitute. The one sanctioned
substitute is a codex team that codex cannot serve (refused by the budget gate, quota exhausted,
CLI missing, no eligible model, or two failed calls — after a capability failure, the one Sol → TOP retry
comes first): a Claude team in the same lens on the
Claude main tier serves it, labelled as a substitution, and the round is recorded as Claude + Google (provider gap:
OpenAI) — see "Codex teams".

Resolve the Claude seats through the registry, not smart-config. A main seat is a protected role,
and smart-config merges a project policy from the working directory that could downgrade it:

```bash
m=$(python3 ~/.claude/skills/_meta/seat_model.py model --role consultant_main --provider claude)     # main seat
m=$(python3 ~/.claude/skills/_meta/seat_model.py model --role consultant_support --provider claude)  # supporting seat
# Agent(subagent_type=..., model=m, ...) — a non-zero exit prints nothing: the registry is broken.
# Fix it; never spawn a seat on the inherited session model.
```

**Never staff a main adversarial seat below the top tier.** Seats that are genuinely mechanical
(extraction, cite-checking, scribes) are not consultancy roles. They may take smart-config `light`.

**Call budgets.** A codex MAIN seat is a std-tier call (Sol @ `xhigh`, since the astra reserve). It runs without `--ephemeral`, so quota is
metered, and it is admitted as a **`brainstorm`** call against **the tournament's OWN budget key**, not
the round's. The lead mints `tournament-<uuid>` once at tournament start and persists it at
`$WORK/tournament-id`, so the diverge lead and the final cross-fire share ONE key and together spend the
`brainstorm` budget (**2 TOP calls, 4 std**; a Sol team spends std). Until S081 revision 4 these seats were admitted as
`consult` against the *forge cycle id*, which allows exactly ONE: a brainstorm inside a forge round
either starved forge's own approach explorer or was itself refused, and the second codex team in a
tournament was always refused. Outside a forge round the key is still the tournament's, not
`adhoc-<UTC date>-<cycle base>`. A refused codex team is served by a Claude team in the same lens on
the substitute model (Failure Modes), never re-seated on a codex std or support model: every codex
model draws the same ChatGPT-plan quota. A substitute does not spend the astra budget; it is recorded in
`~/.claude/projects/<slug>/astra-budget.jsonl` for the 2026-09-28 plan review. Only a broken seat
registry or a codex failure the classifier calls a gap makes the codex team a **no-show**.
Inside a forge round, forge's agy cap applies: at most 3 agy calls per round, and a capacity error
stops further agy calls for that round.

**Scope of the tournament key, stated so a reader does not expect more than exists.** The codex lead and
the final cross-fire exist ONLY on this SKILL.md inline path. `workflows/adversarial-tournament.js` has
**no codex stage at all** — verified by measurement, not assumed: the file contains zero occurrences of
`codex`, and no `models` argument either. So the workflow mints no key, needs none, and is untouched by
this change. A tournament run through the workflow is a Claude/agy tournament; only the inline path here
spends the `brainstorm` budget.

### Round 2: Cross-fire

Each team receives the other teams' Round 1 outputs and must attack them. See
`references/cross-fire-protocol.md` for the full protocol. Summary:

- Each team attacks **every other team's outputs** (N-1 targets)
- Minimum ≥1 attack per output (no "all good" verdicts — HARD-RULE)
- Attacks must include: severity (critical / moderate / minor), issue, fix_proposed
- Codex-powered teams are preferred for the `contrarian` / devil's-advocate role

Attacks MUST be structured — free-form commentary is rejected.

### Round 3: Refine

Each team receives the attacks on its own outputs and revises. See
`references/cross-fire-protocol.md#refine-rules` for rules.

- Every revised output must include `before` + `after` + `critique_absorbed` list
- A team may mark an attack as "rejected" with reasoning — not every critique is absorbed, but
  ignoring it silently is a failure mode
- Kill criteria are sharpened during refine (Round 1 drafts → Round 3 hardened versions)

### Round 4: Arbiter Synthesis

A single arbiter agent (Claude by default; caller may override) reads all Round 3 outputs + attack
histories and produces the final ranked list. See `references/arbiter-synthesis.md` for the full
protocol. Summary:

- Identify surviving outputs (did not receive critical attacks, or absorbed them in refine)
- Hybridize where cross-team ideas complement (mark `source_team: "hybrid(A+B)"`)
- Attach final kill criteria (minimum 2 per output — HARD-RULE)
- Assign confidence: `high` / `medium` / `low` / `speculative`
  - `speculative` is the max if there is no external data grounding
- Preserve minority reports: if one team strongly disagrees with the ranking, the arbiter notes
  it in `arbiter_notes` rather than hiding it
- Filter any outputs marked `unfounded` that cannot be hybridized with a grounded output

---

## Team Angles

See `references/team-angles.md` for the full library. Common angles:

| Angle | Typical use | Best model |
|---|---|---|
| `problem-first` | Ideation from user pain data | Claude |
| `asset-first` | Ideation from user's existing capabilities / distribution | Claude |
| `trend-first` | Ideation from macro event velocity (GDELT inflections) | Claude |
| `contrarian` | Attacks consensus, finds counter-positioning | Codex (default) |
| `first-principles` | Reasoning from physics / unit economics / constraints | Codex |
| `arbitrage` | Finds price / information / capability gaps | Codex |
| `blue-ocean` | Creates new demand categories | Antigravity (agy) |
| `constraint-inverted` | Starts from what's forbidden / impossible today | Claude |

Callers pass the list they want; the primitive does NOT prescribe which angles to use — that is
domain knowledge owned by the caller.

---

## Fast path — `adversarial-tournament` workflow (S055, optional, main-loop only)

When the orchestrator is the main loop with the orchestration surface available
(`probe.sh get capabilities.workflow_tool` true AND `probe.sh context ==
main-loop` — the ONLY capability API; `capabilities.*` alone never authorizes,
session files are shared with subagents), the four rounds MAY run as the
`adversarial-tournament` saved workflow: parallel `diverge` (one isolated agent
per team angle, `team-output.v1` with `initial_kill_criteria` minItems:2 — role
collapse mechanically prevented) → parallel `crossfire` (each attacker sees ONLY
other teams' outputs, `attack-set.v1` minItems:1 per target makes "all good"
schema-invalid; the script validates target coverage with a deterministic single
retry on a sycophantic miss) → `refine` → single `arbiter` (`tournament-result.v1`;
the script forces confidence to `speculative` when `grounding_sources` is empty —
DOWNGRADE only, never upgrade). Below the budget floor before `refine` ⇒ skip
refine, cap confidence `low`, `meta.degraded_to: "quick_tournament"` (documented
mode, not silent loss). The script REFUSES configs that would drop kill criteria.

Stays inline: question scoping, angle selection, grounding-feed acquisition
(reddit/gdelt run BEFORE and passed as `context_paths`), final selection, all
user decisions. External team overrides ride W-EXT wrappers with args-supplied
commands. The schemas live in `schemas/`; `design-tournament` does NOT wrap this
workflow (B's ruling — standalone callers are this skill's own inline
invocations). On any fast-path failure, fall back to the inline four rounds below.

## Implementation Notes

### Spawning Teams

**Claude teams** — use `Agent` tool with `subagent_type: "general-purpose"` and a spawn prompt that
includes:
1. The team lens definition (read from `references/team-angles.md`)
2. The question
3. Any data feeds from `context`
4. The Round 1 output format

**Codex teams** — use `codex exec` (preferred for `contrarian`, `first-principles`, `arbitrage`
angles). A codex team is a MAIN seat, `consultant_main` (the codex std tier @ `xhigh`, a 2400s runaway cap from
`seat_model.py timeout` — the call is stopped by 300s of silence, not by the clock, and its Bash tool
call runs with `run_in_background` because a foreground one is capped at 600s). Its model and
effort come from `seat_model.py argv`, and the call runs only when the pin resolved. It runs WITHOUT
`--ephemeral` so that quota is metered, which means its prompt persists in `~/.codex/sessions`: no
secrets. `seat_model.py argv --use brainstorm --cycle-id "$TOURNAMENT_KEY"` admits and pins it in one
call, against the tournament's own key rather than the round's. Exit 0 runs codex. Exit 3
means codex cannot serve the seat: stdout line 1 is the reason, line 2 the Claude model, and no codex call
runs. Anything else (1 = broken registry, 2 = usage error) is a no-show. A failed codex call goes
through `codex_quota.py classify`: a timeout or empty answer re-runs only the exec line once, a
model at capacity retries once and then substitutes (`capacity_twice`), a quota / rate-limit stop,
auth failure, missing CLI or second timeout substitutes, and any other exit is a no-show.

**When the output file starts with `CODEX_SUBSTITUTE:`,** run a Claude team in the SAME lens on the
model named in that line: `Agent(subagent_type="general-purpose", model="<that model>")` with the
Claude-team spawn prompt above (same lens, question, data feeds and Round 1 format), in a fresh
context. Spawn it as soon as the line appears, still in Round 1: it is the one sanctioned spawn after
the parallel batch, and like every Round 1 team it is given no other team's output. Label its outputs
`<that model> (substituting codex: <reason>)` and keep the `CODEX_SUBSTITUTE:` line in `arbiter_notes`, so
the round is recorded as Claude + Google (provider gap: OpenAI).
**When it starts with `CODEX_QUOTA_WAIT:`** (#322: codex is out of quota and nothing is recorded yet), the
tournament lead follows the codex-orchestration "Seat Models" steps: on `wait_advice notify`, `codex_quota.py
notify-claim` and notify on its exit 0 (one notification per refusal wave); run `codex_quota.py await-reset
--cycle-id <key>` in a background call (one per account; parallel teams join it; a record whose wait already timed out exits 4 at once); re-run the same codex team
once on exit 0; on exit 4 / 6 / 3 record `seat_model.py substitute --use <use> --cycle-id <key>
--requested-model <requested> --reason quota_exhausted_timeout|quota_probe_error|cli_missing` (the values on
the line) and run the Claude team above.

```bash
# codex_top_seat NAME ROLE USE SIZE KEY BRIEF_FILE OUT_FILE [codex exec flags...] -- one TOP codex seat:
# SIZE and KEY are each "" when the caller has none, and an empty one passes no flag.
# admit + pin (exit 0 run codex, 3 substitute, else no-show), then classify any failed call (retry = re-run
# only the exec line, once; substitute = record it; gap = the no-show line). Budget key's project:
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
    *) echo "NO_SHOW: $NAME codex team (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;
  esac
}

# ONE key for the WHOLE tournament, minted once at tournament start and PERSISTED, because the diverge
# lead and the final cross-fire are separate Bash calls and shell state does not survive between them.
# Sharing one key is what makes them spend the tournament's own `brainstorm` budget (top 2 / std 4)
# instead of the round's single `consult` -- which is why a brainstorm inside a forge round used to
# starve forge's explorer, or be refused by it. Re-running this is safe: an existing id is read back.
if [ ! -s "$WORK/tournament-id" ]; then
  TID="$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || true)"
  # SHAPE-CHECKED BEFORE USE, never just concatenated. An empty mint would make the key the bare prefix
  # `tournament-`, which SATISFIES codex_quota.CYCLE_ID_PATTERN -- a malformed key that passes validation
  # and that every tournament on the host would then SHARE, silently recreating the starvation above.
  case "$TID" in
    ????????-????-????-????-????????????) printf 'tournament-%s\n' "$TID" > "$WORK/tournament-id" ;;
    *) echo "tournament key mint failed (no uuidgen, no python3)" >&2 ;;
  esac
fi
TOURNAMENT_KEY="$(cat "$WORK/tournament-id" 2>/dev/null || true)"

# <!-- spawn-brief.v1 id=adversarial-team-brainstorm.codex-team -->
cat > "$WORK/team-contrarian-round1.brief.md" << BRIEF
You are the contrarian team. Question: $QUESTION. Data: see $CONTEXT_FILE.
   Produce $N outputs per the format in $OUTPUT_SPEC.
Goal: $N committed contrarian proposals answering the question.
Non-goals: other lenses; option lists; file changes.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: exactly $N outputs in the $OUTPUT_SPEC format.
Stop when: the $N outputs are written, or you are blocked (state the blocker).
BRIEF
# Brainstorming is DELIBERATIVE, so the size is `complex` by this skill's own routing, not read from a cycle
# file (inside a forge round the registry takes the LARGER of forge's size and this one). Since the astra
# reserve a main seat is the codex std tier at every size; the size is recorded on the budget row.
# NO KEY -> NO CALL. A failed mint is a NO_SHOW, never an unkeyed codex call that would fall back to the
# round's budget key -- the exact sharing this block exists to stop.
if [ -n "$TOURNAMENT_KEY" ]; then
  codex_top_seat contrarian consultant_main brainstorm complex "$TOURNAMENT_KEY" \
    "$WORK/team-contrarian-round1.brief.md" "$WORK/team-contrarian-round1.md" --skip-git-repo-check -s read-only
else
  echo "NO_SHOW: contrarian codex team (tournament key mint failed; no unkeyed codex call)" \
    > "$WORK/team-contrarian-round1.md"
fi
```

**Antigravity (agy) teams** — use the agy CLI for large-context angles (`blue-ocean`, `trend-first`
with deep event history). Output is plain text on stdout — the orchestrator parses it (STDIN RULE:
stdin MUST be closed or agy hangs in background shells, #135; SANDBOX RULE: `--sandbox --mode plan`
from an empty cwd on every advise-only call or agy may write files/commit instead of answering, #157, #366).
The model comes from
`seat_model` (`consultant_main` for a main seat, `consultant_support` for a supporting one) and goes
before `-p`. The call runs from an empty directory, so the data and the output spec are passed
INLINE, never as a path for agy to open. Read them before the subshell, which changes directory:

```bash
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" \
  && DATA="$(cat "$CONTEXT_FILE")" && SPEC="$(cat "$OUTPUT_SPEC")" \
  && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "You are the blue-ocean team. Question: ... Data: $DATA Produce $N outputs per this format: $SPEC Advisory only — do not modify any files; answer on stdout." < /dev/null) > "$WORK/team-blue-ocean-round1.md"
```



### Bridge Mode

session mode. Codex is unaffected (it always runs locally).

### Batching the Spawns

All Round 1 team spawns MUST go in a single message with parallel tool calls. This is enforced by the
"parallel diverge is mandatory" hard rule. The primitive is incompatible with sequential spawning.

### Failure Modes

| Failure | Detection | Response |
|---|---|---|
| A team times out / returns empty | Round 1 aggregator sees no output for team X | Mark team X "no-show", continue with remaining teams, note in arbiter |
| Codex cannot serve a codex team (budget refused, quota exhausted, CLI missing, no eligible model, two failed calls — after the one Sol → TOP retry on a capability failure) | The team's output file starts with `CODEX_SUBSTITUTE:` | Run a Claude team in the same lens on the model named in that line (fresh context, same Round 1 prompt), label its outputs `<that model> (substituting codex: <reason>)`, record the round as Claude + Google (provider gap: OpenAI) in `arbiter_notes`. Never re-seat on a codex std or support model |
| A team refuses to attack in Round 2 | Round 2 aggregator sees "all good" verdicts or attacks without severity | Reject the attack output, re-spawn the team with sharper prompt; max 1 retry |
| Arbiter cannot produce 2+ kill criteria for an output | Arbiter validation fails | Drop the output from the final list rather than fake kill criteria |
| No output has external grounding | No `context` was passed, or all teams returned `unfounded` | Cap all confidence at `speculative`; emit warning in `arbiter_notes` |
| Cross-fire produces sycophantic attacks (common LLM failure) | Round 2 attacks are uniformly "minor" severity with trivial fixes | Re-spawn attackers with Codex model override and explicit "find CRITICAL flaws" prompt |

---

## Mode: `quick_tournament` (optional shortcut)

For callers who need fast outputs and accept reduced rigor, a `quick_tournament` mode runs:
- 2 teams instead of 4
- 2 rounds (diverge + arbiter, no cross-fire or refine)
- max confidence `low` (enforced)
- useful for low-stakes brainstorms where the full 4-round cost is excessive

Callers opt in via `rounds: 2`. The primitive warns that cross-fire was skipped.

**Do NOT use quick_tournament for founder-ideation, alf review, or any high-stakes decision.** It
exists only for exploration / discovery modes.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Spawning teams sequentially to save token budget | The second team anchors on the first team's output; divergence collapses into a single voice | Always batch all team spawns in one message with parallel tool calls |
| Allowing "all good" verdicts in cross-fire | The primitive's value is structural contention; passive review produces polished consensus, which is exactly the failure mode we're trying to avoid | Reject any Round 2 output that doesn't include ≥1 attack per target; re-spawn the attacker |
| Hiding attacks from the refining team | Teams can't absorb critique they don't see; refine becomes cosmetic | Pipe attack_history directly into each team's Round 3 prompt |
| Skipping the arbiter because the outputs "look good enough" | Without synthesis, hybrid insights are lost and confidence assignment is unreliable | Always run Round 4, even for small tournaments; the arbiter is the quality gate |
| Letting the arbiter promote to `high` confidence without data grounding | LLM-vs-LLM confidence is meaningless; external grounding is the anti-hallucination seatbelt | Enforce the grounding rule in arbiter code: no external cite = cap at `speculative` |
| Forcing a single model on all teams | Different models have different blind spots; homogeneous teams have correlated failures | Use model diversity (Claude + Codex + Antigravity mixed) especially for contrarian / devil's-advocate roles |
| Prescribing team angles the caller didn't request | Domain knowledge lives in the caller (founder-ideation, forge, etc.); the primitive is lens-agnostic | Accept `team_angles` as input, never hardcode a default set inside the primitive |

---

## Reference Files

Read these as needed during orchestration:

- `references/team-angles.md` — the founding-lens library (problem-first, asset-first, trend-first, contrarian, first-principles, arbitrage, blue-ocean, constraint-inverted) with spawn-prompt guidance per angle
- `references/cross-fire-protocol.md` — Round 2 attack protocol: target selection, severity rubric, fix-proposal format, rejected-attack fallback
- `references/arbiter-synthesis.md` — Round 4 synthesis protocol: survivor selection, the merge near-duplicates step, kill-criteria attachment, confidence scoring, minority-report preservation

---

## When NOT to Use This Skill

- **Single-agent question** — if one specialist can answer, use that specialist directly. The
  tournament overhead is wasted on simple lookups.
- **No cross-fire value** — if the caller's question has one correct answer (e.g., "what's the syntax
  for X"), adversarial brainstorm is noise.
- **No grounding and no exploratory intent** — if you have no data feeds AND you're not trying to
  explore, you're just asking LLMs to argue with each other. Use a single agent and save the cost.
- **Live production paths** — this primitive is slow (4 rounds × N teams). Don't put it on a
  user-facing latency budget.
