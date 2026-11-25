# Forge reference — codex seats

Checklist step 6 — previous: step 5b, the hard rules checkpoint; next: step 7, present design.
When this file is read, return to the SKILL.md checklist.

The same seat recipe serves the escalation seat (`references/05-escalation.md`) and the codex reviewer of the advisory code review (`references/10-close-out.md`); both cite this file's rules as "above". The agy stdin rule this file mentions is in `references/04-agy-and-converge.md`.

## Contents

- Spawning Codex Agents
  - The guarded seat call is the only path for a protected seat; plugin commands are an ungated convenience
  - Model, quota and call shape: admit and pin, call-time failures, the Sol to TOP retry (U2), substitution (D6), quota wait (#322), research, shape discipline
  - The bash block: size read, the `codex_top_seat` source-and-guard preamble, the challenger brief, the approach-explorer brief, the research lookup
  - Plugin vs guarded call

#### Spawning Codex Agents (ALWAYS — in parallel with Claude agents)

Check Codex availability first (step 4b). If unavailable, skip Codex agents and note the gap.

**The guarded seat call is the ONLY path for the challenger, the approach explorer and the escalation seat (#282 R7).** Each is a protected, budgeted codex seat — the challenger and explorer are `consultant_main` (the codex std tier @ `xhigh`, since the astra reserve), the escalation seat is `escalation` (codex TOP @ `max`) — so each runs through `codex_top_seat` below: `seat_model.py argv --use` admits the call against this cycle's budget and pins its model and effort, `seat_model.py timeout` gives its timeout, and `codex_quota.py classify` decides retry, substitution or gap. Nothing else pins, meters or substitutes those seats. The research lookup is `consultant_support`, the plain `seat_model.py argv` pin further below.

**Plugin commands (`/codex:adversarial-review`, `/codex:rescue`, `/codex:status`, `/codex:result`) are an ungated convenience — no seat pin, no admit gate, never for a protected seat; plugin not installed on this host (S080 D11).** They come from a Codex *plugin*, which is a separate thing from the `codex` CLI: having the CLI does not mean you have the commands (the plugin would be in `enabledPlugins` in `~/.claude/settings.json`; S073: on this host that list holds only `superpowers`). Where a host has the plugin, a command may serve an ad-hoc question outside the round's seats, and its answer never stands in for the challenger, approach-explorer or escalation seat.

**Raw `codex exec` through the seat registry** (every codex seat below). **STDIN RULE (#155):** the agy stdin rule applies to `codex exec` exactly the same — close stdin (`< /dev/null`) on every headless argv-prompt invocation or it hangs to timeout in background shells.

**Model, quota and call shape.** Every call pins its model AND effort through the seat registry `~/.claude/skills/_meta/seat_model.py` and runs only when the pin resolved. On any failure the registry exits non-zero and prints no pin, so a codex call never runs unpinned.
- The challenger and the approach explorer are `consultant_main`: the codex std tier (Sol) @ `xhigh` at every size (the astra reserve, roster rev 4; an explicit user request still promotes it to codex TOP), 2400s (the block reads the cap from `seat_model.py timeout`, never a literal, and hands it to `codex_watch.py` as the RUNAWAY cap — the normal stop is 300 s of silence, not the clock). They run WITHOUT `--ephemeral`, because only a non-ephemeral call writes the session rollout that meters quota — and that rollout is also one of the watchdog's heartbeats, so an `--ephemeral` call is watched on its two byte counters alone. Their prompts therefore persist in `~/.codex/sessions`, so never put a secret in a brief.
- **Admit and pin in one call:** `seat_model.py argv --role consultant_main --provider codex --use challenger|consult --project-root "$PROJECT_DIR"` records the call against this cycle's budget and prints the pin. The class comes from the pin, so a Sol call spends the std budget (2 per use per cycle; a user-requested TOP call, 1). Exit **0** = admitted, stdout is the pin. Exit **3** = codex cannot serve the seat (the budget for that use is spent, codex is really out of quota — a fresh 5-hour or weekly reading at 99% or more, the limit reached, or the persisted exhausted-until record from an earlier refusal or failed call that no newer reading has cleared — the codex CLI is missing, or no eligible model is listed — for a Sol seat, a roster that does not serve Sol at the seat's effort): stdout line 1 is the reason, line 2 the Claude model to substitute, and no codex call runs. There is no 70% refusal (#322); a quota refusal goes through the Quota wait bullet below before any stand-in. Exit **10** = the astra trial is skipped, never substituted (no forge call uses `--use trial`). Exit **1** = the seat registry is broken, exit **2** = a usage error: both are a gap to fix, never a reason to run codex unpinned.
- **Call-time failures** go through `codex_quota.py classify`. A timeout or an empty answer on the first attempt re-runs ONLY the exec line, once (same model, same admission). A quota or rate-limit stop, an auth failure, a missing CLI, or a second timeout or empty answer is a substitution, recorded by `seat_model.py substitute` (a stderr signal counts only on a codex error line, or for quota when the meter agrees; a model at capacity retries once, then substitutes `capacity_twice`; "Quota exceeded" is a quota stop). Any other non-zero exit is a gap: a harness or usage fault is never laundered into a substitution.
- **U2, the Sol → TOP retry (the astra reserve).** When the classify result is `capacity_twice` or `malformed_twice` — a CAPABILITY failure — the block asks `seat_model.py argv ... --top-retry --failed-admission-id <the seat's receipt>` for ONE attempt on codex TOP at the same effort, before the D6 stand-in. The failed attempt is proven from its receipt (an admitted std row of that role, use and key); it is a retry only when the TOP pin differs from the one that failed AND bills the TOP class (a freeze must name the roster TOP itself); it is admitted as the budget use `top_retry` on the FORGE CYCLE (1 per cycle, whatever seat or tournament/ballot key asked) and recorded as a `top_retry` event row linking both attempts. The TOP attempt runs once, with no inner retry, and is never retried again. `timeout_twice` goes straight to D6 (an oversized brief times out on TOP too), and quota, auth, budget and gap outcomes never buy it: they are account problems. TOP unavailable (budget, quota, auth, CLI) → the ordinary D6 line.
- **Substitution (amendment 1, D6).** A budgeted codex seat that codex cannot serve (Sol or TOP) is served by a fresh-context Claude main-tier agent with the SAME brief — never a codex std or support model or any other codex model, which draw the same ChatGPT-plan quota. The block writes `CODEX_SUBSTITUTE: <seat> -> <model> (reason <token>; provider gap: openai)` and `brief: <file>` into the seat's output file. **The lead then spawns** `Agent(subagent_type="general-purpose", model="<model from that line>")` with the brief file's content as the prompt, in a fresh context (no conversation history and no other seat's output), and replaces the output file's content with the agent's answer, keeping the `CODEX_SUBSTITUTE:` line as its first line. Every substitution is recorded in `~/.claude/projects/<slug>/astra-budget.jsonl` for the 2026-09-28 plan review. agy seats are unchanged: an agy no-show stays a gap.
- **Quota wait (#322).** There is no 70% threshold: codex runs to its real limit. When the admit refuses for QUOTA (a fresh reading ≥ 99%, or `rate_limit_reached`), the block records nothing yet and writes `CODEX_QUOTA_WAIT: <seat> (reason <token>; wait_advice <wait|notify>; resets_in_s <n>; stand-in <model>; use <U>; key <K>; requested <M>)`. The lead follows the codex-orchestration "Seat Models" steps for `CODEX_QUOTA_WAIT`: with `notify` it runs `codex_quota.py notify-claim` and sends the push notification "codex at 100% (<seat>) — reset please; waiting up to 30 min" only on its exit 0 (one notification per refusal wave, however many seats were refused together), then runs `codex_quota.py await-reset --cycle-id <K>` in a BACKGROUND call (one per account: a second seat's call joins the first; once a record's wait has timed out, a later seat's call exits 4 at once with `timed_out_for_record` and that seat notifies nobody); exit 0 → re-run the same seat once; exit 4 / 6 / 3 → `seat_model.py substitute --use <U> --cycle-id <K> --requested-model <M> --reason quota_exhausted_timeout|quota_probe_error|cli_missing` and the D6 stand-in above; exit 5 → auth, run `codex login`. A TOP retry (U2) refused for quota writes the same line, with use `top_retry` on the forge cycle.
- Research is a supporting lookup: `consultant_support` (the codex support tier @ `medium`) runs WITHOUT `--ephemeral` like every role-resolved codex call (#302: its rollout meters the quota, so its prompt persists in `~/.codex/sessions` — no secrets in the brief), is not budgeted and is never substituted; its failure stays a `CODEX_GAP:`.
- **Shape discipline.** Briefs are inline by default. The challenger gets its brief as the prompt and opens a file only to check a specific claim. The approach explorer is the round's one repo-exploring `-C` consult, and the only budgeted exploration. Each TOP brief is written to a file first, because `classify` needs the exact prompt to ignore codex's echo of it.

**A missing seat script is a gap for every seat of the call.** When the Bash call exits non-zero with the stderr line `CODEX_GAP: codex_top_seat.sh missing or unreadable; no codex seat was started`, the guard stopped it before any seat ran and no seat output file was written: every seat of that call is a gap, to be handled exactly as if each seat's file opened with `CODEX_GAP:`.

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX) || exit 1
SEAT=~/.claude/skills/_meta/seat_model.py
# Budget key (derived inside `argv --use` from --project-root): .forge/cycle-id (written fresh at Step 1),
# else adhoc-<UTC date>-<.forge/cycle-base short sha>
# THIS CYCLE'S REVIEW SIZE, read once for the seats below. Step 4 writes it and close-out deletes it, so
# it is READ here and never written -- the two lifecycle points stay the only two. ABSENT -> the variable
# is empty and the seats pass NO --size, which resolves complex with `size_source: default` (back-compat).
# Passing a literal `complex` instead would record `size_source: routing` and claim a decision nobody made.
# This read is the OPT-IN: with no --size the registry reads no size file, so an unsized explorer or
# challenger spends the scarce TOP model even on a light cycle. Forge's size then wins over any caller's.
FORGE_SIZE="$(cat .forge/size 2>/dev/null || true)"

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

# Codex Challenger (runs simultaneously with Claude challenger)
# <!-- spawn-brief.v1 id=forge.challenger-codex -->
cat > "$CODEX_WORK/brief-challenger.md" << 'BRIEF'
# Challenger Review Brief
## Context
[TASK DESCRIPTION + KEY CONSTRAINTS]
[THE APPROACHES UNDER REVIEW, INLINE]
Project files at: [PROJECT_DIR] (targeted reads only: open a file to check a specific claim; do not explore the repository)
## Your Role
You are a devil's advocate / challenger. Review every approach against Done when.
Goal: find what would stop each approach meeting Done when, and rank the design.
Non-goals: [OUT OF SCOPE]; no file changes; no requirements beyond Done when.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: [SUCCESS CRITERIA / DW-n] — each approach has at most 5 ranked non-critical findings (zero is valid) plus an overflow list of critical/major ones.
Stop when: every approach is reviewed, or your budget stops the search (then say coverage is incomplete).
Focus on: scalability, security, maintainability, edge cases, operational complexity.
For each issue: Severity (critical/major/minor/nit), What's wrong, Why it matters, How to fix.
Rank overall design: strong / acceptable / needs-rework / reject.
Brief block: skills/_meta/spawn-brief.md
BRIEF

# consultant_main (the codex std tier @ xhigh since the astra reserve), no --ephemeral, admitted as a `challenger`
codex_top_seat challenger consultant_main challenger "$FORGE_SIZE" "" \
  "$CODEX_WORK/brief-challenger.md" "$CODEX_WORK/challenger.md" -C "$PROJECT_DIR" -s read-only &

# Codex Second Opinion / Approach Explorer: consultant_main, the round's one repo-exploring `consult`
# <!-- spawn-brief.v1 id=forge.explorer-codex -->
cat > "$CODEX_WORK/brief-approach.md" << 'BRIEF'
You are exploring approaches for [TASK].
Goal: the top 2-3 approaches for [TASK], with one recommendation.
Context: [KEY FILES, ARCHITECTURE, CONSTRAINTS; settled decisions — do not reopen]
Non-goals: [OUT OF SCOPE]; no file changes.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: each approach answers the four items below against [SUCCESS CRITERIA / DW-n].
Stop when: the recommendation is written, or you are blocked (state the blocker).
Brief block: skills/_meta/spawn-brief.md
Produce your top 2-3 recommended approaches with:
1. How it works  2. Pros/cons  3. Effort estimate  4. Risks
Be opinionated — recommend the best approach and explain why.
BRIEF
codex_top_seat approach-explorer consultant_main consult "$FORGE_SIZE" "" \
  "$CODEX_WORK/brief-approach.md" "$CODEX_WORK/approach.md" -C "$PROJECT_DIR" -s read-only &

# Codex Research (when task needs up-to-date info; web search is automatic — no flag)
# consultant_support (the codex support tier @ medium): supporting lookup, not budgeted, and NO
# --ephemeral (#302): the rollout meters its quota, like every role-resolved codex call.
# Watched like every other codex call (D24): the seat's registry timeout is the runaway cap, the
# normal stop is silence, and codex_watch closes the child's stdin so no `< /dev/null` is needed.
if PIN="$(python3 "$SEAT" argv --role consultant_support --provider codex)" \
   && CAP="$(python3 "$SEAT" timeout --role consultant_support --provider codex)"; then
  python3 "$HOME/.claude/skills/_meta/codex_watch.py" --mode codex --hard-cap "$CAP" \
    --stdout-file "$CODEX_WORK/research.md.stdout" --stderr-file "$CODEX_WORK/research.md.stderr" \
    -- codex exec --skip-git-repo-check $PIN \
    -o "$CODEX_WORK/research.md" \
    "Research current best practices for [TECHNOLOGY/PATTERN] as of 2026.
Latest versions, known limitations, community adoption, alternatives." \
    || echo "CODEX_TIMEOUT: Codex research seat stopped (exit $?; 111 = went silent, 112 = hit its cap)" \
         > "$CODEX_WORK/research.md"
else
  echo "CODEX_GAP: research seat skipped (no seat pin or no timeout resolved)" > "$CODEX_WORK/research.md"
fi &

wait  # Wait for all Codex tasks to complete
# This `wait` is what makes the whole block ONE Bash tool call, so that tool call MUST be started with
# run_in_background (D24). A foreground one is capped at 600 s and would kill every seat above it,
# whatever cap each seat resolved — `&` parallelises the seats, it does not lift the harness limit.
```

**Plugin vs guarded call**: the challenger, approach-explorer and escalation seats run only through the guarded `codex_top_seat` block, and the research lookup only through its `seat_model.py argv` pin. Plugin commands are an ungated convenience — no seat pin, no admit gate, never for a protected seat; plugin not installed on this host (S080 D11) — so a plugin answer is never a seat's answer in the convergence.
