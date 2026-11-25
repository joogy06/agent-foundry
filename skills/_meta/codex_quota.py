#!/usr/bin/env python3
"""codex_quota.py — the codex rate-limit meter and the per-cycle astra budget.

S081 design §4.7 (D4), §2.4, §11 Quota; plan interpretations I8 and I10.

WHY THIS EXISTS. TOP codex calls (astra today) spend a ChatGPT Plus quota that is
visible in exactly one place: the `rate_limits` object codex writes into its own
NON-ephemeral session rollouts (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`).
`codex exec --ephemeral` writes no rollout, and `--json` reports tokens only. Two
measured repo-exploring astra calls moved the 5-hour window by 15 and 7 points
(design §2.4), so a round of unmetered consults can exhaust the window that the
VERIFIED-gate audit also needs. This module reads that meter and rations the
discretionary uses against it.

THE SURFACE
  snapshot()        newest rate-limit reading: fresh | stale | uncertain | unknown. NEVER
                    raises.
  unavailable()     "rate_limit_reached" | "quota_exhausted" | None — can astra run at
                    all right now? NEVER raises (see ASTRA UNAVAILABLE).
  admit(use, key)   one decision for one intended codex call, recorded as one row
                    in ~/.claude/projects/<slug>/astra-budget.jsonl, admitted OR refused.
                    The limit is BUDGET_LIMITS[use][model_class] (D16, see THE BUDGET
                    TABLE). Every non-trial decision names its Claude `fallback` seat.
                    Every row and decision carries a fresh `admission_id` (see
                    CORRELATION) and records `size` / `size_source` / `model_class`.
                    `record=False` (#282 r15) is CHECK-ONLY: the same decision, nothing
                    written (see THE BUDGET STORE); the decision says `recorded` true/false.
  tripwire(seat_class)
                    the D20 ACCOUNT-WIDE pre-call check EVERY codex call runs, budgeted or
                    not: unavailable(), and nothing else (#322 retired the 70% threshold). CHECK-ONLY —
                    no row, no store, no lock, no slot. -> run | substitute | skip.
  record_skip()     one `kind: "skip"` row: a SUPPORTING seat the trip-wire stopped.
  classify_codex_failure()
                    the ONE call-time classifier: ok | retry | substitute | gap. Pure.
  corroboration_for()
                    the evidence a classification may use besides the exit status: the
                    codex-owned error lines and ONE post-call unavailable() reading (#282 R2).
  record_substitution()
                    one `kind: "substitution"` row when a Claude agent serves a codex seat.
  reset_advice()    #322: when a quota refusal ends and what to do meanwhile — {binding_window,
                    resets_at, resets_in_s, wait_advice: wait (<= 1200 s) | notify}. admit() adds it
                    to a decision that QUOTA decided (fix round 1: never to budget_spent /
                    class_not_budgeted, which are decided first).
  record_exhausted() / read_exhausted() / clear_exhausted() / active_exhausted() / retire_exhausted()
                    #322 fix round 1 (F1): the account-wide "exhausted until T" record
                    (~/.claude/state/codex-exhausted.json), written by a failed probe, the classify
                    CLI and admit()'s own refusal; admit() AND tripwire() (fix round 2) honour it until
                    T unless a newer reading shows EXPLICIT headroom on its binding window, and a
                    superseded record is retired, keeping a newer concurrent signal (fix round 2).
                    retry_at_from_text() reads T from codex's "try again at 1:50 AM". record_wave():
                    the record's wave, [exhausted_until, evidence_at] as it was opened.
  quota_wait_now()  the quota token + reset fields right now (meter or record), for the avengers
                    pre-spend review. Writes nothing but a superseded record's retirement.
  await_reset()     #322: wait until codex is usable again, PROBING it (one trivial non-ephemeral
                    `codex exec` through codex_watch); record_probe() writes each probe's row. One
                    per ACCOUNT (a second caller joins; fix round 2), and one full wait per exhausted
                    record (a later call for a timed-out record probes once, then exits 4
                    `timed_out_for_record`); notify_claim(): one notification per record's wave.
  cycle_id_for()    the budget key, from files only (see THE BUDGET KEY).
  cycle_id_and_source()
                    the same key plus where it came from and the cycle-id file's age.
  CLI               `snapshot [--json]`, `admit --use U --cycle-id C [--project-root P]
                    [--task-key K] [--size S --size-source SRC] [--model-class top|std]
                    [--requested-model M] [--user-request] [--record]`
                    (`--cycle-id` IS the budget key; `--size` and `--size-source` travel
                    together, and this CLI RECORDS a resolved size, it never resolves one
                    — L7 lives in seat_model), `cycle-id [--project-root P]`, `classify
                    --exit-code N --attempt K [--timed-out] [--stderr-file F]
                    [--output-file O] [--prompt-file P]`, `await-reset [--max-wait S] [--poll S]
                    [--margin S] [--project-root P] [--cycle-id K]` (#322; exit 0 available / 4
                    timeout / 5 auth / 6 probe errors / 3 environment), `notify-claim
                    [--project-root P]` (exit 0 notify / 10 skip). Prose call sites (forge,
                    cross-cli-deliberation, …) cannot import Python (I10).
                    `admit` is CHECK-ONLY unless --record (#282 r15): it prints the
                    decision and writes nothing, so running it before `seat_model.py argv
                    --use` (admit + pin, the recording path for a pinned call) can never
                    charge the budget twice. Exit codes are the same in both modes.

THE BUDGET KEY (amendment 1 D7; lead decision J3, J3a, J3b, J4)
  Precedence, first match wins:
    1. `.forge/cycle-id` — its first line, when it matches CYCLE_ID_PATTERN and the
       file is not aged out. forge writes a FRESH id there at Step 1 of every cycle
       and deletes it at close-out (Phase 2 "Step 6: Collect Results", after the
       results are presented, for every status). Source "cycle-id".
    2. `adhoc-<UTC YYYYMMDD>-<first 7 hex of .forge/cycle-base>`. Source "adhoc-base".
    3. `adhoc-<UTC YYYYMMDD>-nobase`. Source "adhoc-nobase".
  AGE-OUT. A cycle-id whose mtime is more than CYCLE_ID_MAX_AGE_S (24h) old counts as
  absent: abandoned sessions never reach close-out, and a leftover id would key later
  out-of-round codex work to a finished cycle whose budget is already spent. Exactly
  24h is still used. An mtime more than FUTURE_SKEW_S in the future, or an unreadable
  mtime, also counts as absent. Failure direction: a cycle longer than 24h gets a
  fresh budget mid-cycle (slightly more astra), never bogus refusals. 24h, not less,
  because long forge cycles (S081 ran ~9h) must not roll over mid-cycle.
  WHY NOT .forge/session-id. It is the contract-signing id: forge Step 8a.2 mints it
  once and never re-mints it, because gates.py G1 compares signed payloads against
  it. Keyed on it, the budget never rolled over, so every cycle after the first was
  refused `budget_spent` forever (proven at the S081 WP-A02 halt). It is never read.
  The key functions are READ-ONLY: they never create, modify, touch or delete a file,
  including an aged-out cycle-id. Only forge Step 1 and forge close-out change it.

NO NETWORK, NO SUBPROCESS, NO MODEL CALL — except `await-reset` (#322), whose probe is one
trivial `codex exec` started through codex_watch (this module still imports no process module;
the watchdog owns the spawn). Every other input is a local file read. The
snapshot walk is BOUNDED (day directories inside the ROLLOUT_WINDOW_DAYS window, at most
ROLLOUT_STAT_BUDGET stat calls and no content read to rank, ROLLOUT_FILE_LIMIT files
tail-read, TAIL_BYTES per file) because freshness_nudge (S081 WP-203) calls it inside a
<500ms SessionStart budget whose charter forbids corpus walks.

SNAPSHOT RULES (#282 R6: the meter reads the newest reading, else says so)
  * Window: the YYYY/MM/DD day directories dated no earlier than the UTC date of `now`
    minus (ROLLOUT_WINDOW_DAYS + 1) days, newest first. Seven days is the weekly window;
    the extra day is there because codex names its directories by LOCAL date.
  * Candidates: the `rollout-*.jsonl` entries of those directories, each STAT'ED (no
    content read), at most ROLLOUT_STAT_BUDGET stat calls per walk (newest directory
    first, names descending inside one). They are ranked by FILE MTIME, newest first
    (ties: name descending), NOT by name: an older-named session that is still running
    carries the newest reading. The ROLLOUT_FILE_LIMIT newest by mtime are tail-read;
    from each, the last USABLE `payload.rate_limits` in a bounded tail read. The reading
    with the newest event `timestamp` wins, not simply the newest file: concurrent codex
    sessions interleave (on 2026-09-14 a rollout named 14-09-12 carried a later reading
    than one named 14-11-28).
  * Usable = `primary` is an object with a finite, non-negative `used_percent`. A
    session's closing entry is `limit_id: "premium"` with `primary: null` in the live
    shape; it is not a reading and is skipped, never mistaken for "no quota data".
    The winning `limit_id` is reported so a second populated limit would be visible.
  * fresh  <=> observed at most FRESH_WINDOW_S ago (FUTURE_SKEW_S of clock skew
               tolerated) AND now < primary.resets_at AND, when a weekly window was
               observed, now < secondary.resets_at.
    stale  <=> a reading exists but is not fresh (too old, unparseable timestamp,
               window already reset, resets_at missing). The readings are still
               reported, for display only.
    uncertain <=> a reading exists, but a newer one may exist unread: a candidate that
               was stat'ed and NOT tail-read has an mtime later than the chosen
               reading's observation (reason newer_candidate_unread; an unparseable
               observation counts as older than every unread candidate), or the stat
               budget ran out with window entries left unstat'ed (reason
               stat_budget_exhausted). A candidate whose tail read FAILED counts as unread
               too (#282 F6): its content is unknown, not absent. Checked in that order,
               whatever the reading's own age. The readings are still reported, for display
               only. uncertain never trips the threshold rule, never admits a trial and never
               makes astra unavailable at all — neither quota_exhausted nor rate_limit_reached
               (#282 F5).
    unknown <=> no usable reading in the files that were read, or anything went wrong.

ADMISSION RULES (design §4.7 as amended by amendment 1 D6 and by #322)
  #322 (2026-09-27): THE 70% THRESHOLD NO LONGER REFUSES. The user: "use codex and let me know
  when is used 100% i will reset it". At 94% a threshold refusal put three Opus stand-ins in the
  Proxmox review seats; the real codex reviews, run later, found 6 critical and 23 major defects
  they had missed. A seat is now refused for quota ONLY on real exhaustion — an unavailable()
  token (rate_limit_reached, or quota_exhausted: a FRESH reading at >= 99% on either window) —
  and a call that hits the wall mid-run is classify_codex_failure()'s business. A refusal for
  quota carries reset_advice(); `seat_model.py argv --use` passes it on as key=value lines.
  THRESHOLD_PERCENT and the `threshold` reason token are KEPT so old rows still parse; nothing
  produces the token any more. The trial ceiling and the per-round budget are unchanged.
  #322 FIX ROUND 1 (2026-09-28). (F1) The quota token is unavailable()'s or, without one, an active
  exhausted-until record: a reading that went stale during a 30-minute wait, or that probe rollouts
  pushed out of the walk, no longer admits a seat while codex is exhausted. (F2) ORDER: a budgeted
  use's class and budget are decided BEFORE quota -- class_not_budgeted and budget_spent win, with no
  reset fields -- so only a seat that would otherwise run is told to wait for a reset.
  unavailable()    consulted for every use (J7), and for budgeted uses AFTER the budget (F2).
                   When it (or the exhausted-until record) gives a token, a use the budget would
                   admit, and the trial, is refused with that token as the reason.
  audit            NEVER refused — not by thresholds, not by budget, not by a broken
                   budget store, not by unavailable(). When unavailable() is set the
                   decision (and its row) carry `unavailable: <token>`, so audit_spawn
                   substitutes before spending a doomed call; a call-time failure is
                   classified by classify_codex_failure().
  trial            refused unless the snapshot is fresh AND primary < 40 AND weekly
                   < 40 (an unobserved weekly window cannot satisfy that). No
                   per-cycle budget here; trial pacing belongs to model_trial.
  every other use  (consult, challenger, advisory_review, review_std, brainstorm, ballot,
                   deliberation, diagnosis)
                   (until #322 also refused `threshold` at a fresh reading >= 70, or a
                   stale-by-age one whose window had not reset); refused `class_not_budgeted` when the table has no
                   budget for that (use, model_class) pair; otherwise refused when that
                   use's budget for that CLASS is spent (diagnosis counts per (key,
                   task_key), or per key when no task_key is given).

THE BUDGET TABLE (design §2.2, D16; BUDGET_LIMITS)
  The limit is chosen by `model_class`, so A COMPLEX CALL AND A LIGHT/MEDIUM CALL ON THE
  SAME KEY COUNT SEPARATELY — they spend different models out of the same account.
    use              key                                    top (astra)  std (std/support tiers)
    consult          forge cycle id                              1          2
    challenger       forge cycle id                              1          2
    advisory_review  forge cycle id, else review-<uuid>          1          -
    review_std       forge cycle id, else review-<uuid>          -          2
    brainstorm       tournament-<uuid>                           2          4
    ballot           ballot-<uuid>                               1          2
    deliberation     avengers session id                    1 seat/session  1 seat/session
    diagnosis        task key                                    1          2
    escalation       forge cycle id                              1          -
    top_retry        forge cycle id                              1          -
    exhausted_review forge cycle id + task_key = D21 review id   1          -
    audit            -                                      never budgeted
    trial            trial-<id>                             per pre-registration
  A "-" cell is REFUSED `class_not_budgeted`, never admitted unbudgeted: advisory_review IS
  the complex review and review_std IS the light/medium one, so the other pairing is a call
  the design does not define. Like every other refusal it is a SUBSTITUTION_REASONS member
  (D21 F7), so `seat_model.py argv --use` serves the seat with its Claude row (exit 3)
  rather than failing. `deliberation` is the AVENGERS codex member seat and the
  cross-cli use is `ballot` (L9) — a stage keying `deliberation` on a cross-cli id has
  followed a superseded document.
  A row written before D16 carries no `model_class` and counts as TOP, which is what it was.
  THE ASTRA RESERVE (roster rev 4, design 2026-09-27): `escalation` is the escalation seat's own use
  (it never competes with the explorer's `consult`), `top_retry` the ONE Sol -> TOP capability retry of
  a cycle (whatever use failed; seat_model.py argv --top-retry), and `exhausted_review` the one review a
  D21 loop gets when it exhausts its bound (per review id, so its task_key is REQUIRED). All three are
  TOP-only: a std pin on them is refused class_not_budgeted and served by the Claude main tier.
  record_top_retry() appends the retry's `kind: "top_retry"` EVENT row linking both attempts
  ({key: the FORGE CYCLE the retry is billed to, origin_use, origin_key: the key the failed seat was
  admitted on, failed_admission_id: that exact admission, failed_model, failed_reason, retry_model, outcome,
  reason, retry_admission_id}); it has no `admitted` key and is never a substitution, so it nets nothing.

THE ACCOUNT-WIDE TRIP-WIRE (design §2.2, D20; tripwire())
  The meter reads the ACCOUNT, so EVERY codex call checks it before running — including the
  `consultant_support` seats (the codex support tier) and research lookups, which are
  trip-wire-checked but NOT budgeted. The check is unavailable() (#322 retired the 70% threshold), CHECK-ONLY: no row,
  no store, no lock, no slot spent. On real exhaustion a DISCRETIONARY seat substitutes (a fresh
  Claude main-tier agent on the same brief, D6/D18) and a SUPPORTING seat takes a RECORDED SKIP
  (record_skip) — a support-tier seat is never substituted, because a Claude agent buys nothing the skip does
  not and another gpt model draws the same quota. Every seat class stops only on real
  exhaustion. An UNCERTAIN snapshot neither refuses nor
  silently passes (#282 F5): the call proceeds and the reading is reported.
  Only trial needs fresh.
  Refusals do not spend the budget. Refused → the caller runs the seat as a
  fresh-context Claude agent on the decision's `fallback` model (D6) and records it with
  record_substitution(); a codex std/support model is NEVER substituted for TOP (every codex
  model draws the same plan quota). The trial
  is the exception: refused → skipped, never substituted (its `fallback` is null).

ASTRA UNAVAILABLE (amendment 1 D6; plan interpretations J6-J9)
  unavailable() reads the same bounded rollout walk as snapshot():
    "rate_limit_reached"  some limit_id's NEWEST rate_limits object (primary may be
                          null, as on a session-closing entry) was observed within
                          FRESH_WINDOW_S (FUTURE_SKEW_S of skew tolerated) and carries a
                          rate_limit_reached_type that is not null / false / empty.
                          Newest PER limit_id: the "premium" entry that closes every live
                          session is a different limit and cannot clear a type set on the
                          "codex" limit a second earlier; a newer object of the SAME limit
                          does clear it. A non-null value has never been observed on this
                          host, so its type is unknown.
                          VOID AT ITS RESET (#282 R5): the type counts only BEFORE its void
                          time, taken from the SAME rate_limits object: "primary" ->
                          primary.resets_at, "secondary" -> secondary.resets_at, any other
                          or unrecognised value -> the EARLIEST of the two; a named reset
                          that is null falls back to the earliest non-null one; both null
                          -> the age bound alone. Evidence-safe: a limit that is still
                          reached after an early void produces one real refusal on the
                          call, which classifies as a true substitution, never a silent
                          refusal that outlives the window.
                          Only the rollouts that WERE read count, and only while the scan is
                          CERTAIN (#282 F5): an uncertain snapshot returns None, because the
                          candidate it did not read is exactly what would clear the flag. A
                          stale or unknown snapshot keeps them: there the flags that were read
                          are the newest evidence the walk can offer, bounded by the void time.
    "quota_exhausted"     the snapshot is fresh AND (primary >= 99 OR weekly >= 99): an
                          exhausted weekly window blocks calls as hard as the 5-hour one.
    None                  otherwise — including a stale, uncertain or unknown reading.
  fallback (J8). Every non-trial admit() decision, admitted AND refused, carries
  `fallback: {provider: "claude", role: USE_FALLBACK_ROLE[use], model}` where model is
  seat_model.resolve(role, "claude").model, imported LAZILY (seat_model imports this
  module at load). A failed import or resolution, or a resolved model that is not a
  plain Claude word (anything starting "gpt-" included), gives model null plus a
  top-level `fallback_error`; the decision itself is unaffected. Trial: `fallback: null`.
  classify_codex_failure(returncode, stderr, *, timed_out, output_ok, attempt, prompt,
  corroboration) -> (action, reason), in this order:
    gap         codex_error       exit 112 (codex_watch.EXIT_HARD_CAP) and not timed out: the
                                  watchdog's runaway cap stopped a call that stayed ACTIVE to it.
                                  Not the retryable kind of stop, so a GAP on EVERY attempt,
                                  decided FIRST, whatever stderr says (S081 rev 4 D21 F10: a codex
                                  error line in such a transcript used to buy a retry or a
                                  substitute from the rules below).
    ok          exit 0 with usable output (not timed out). A signal on stderr of such a
                run (a retried 429) did not stop the call and changes nothing.
    substitute  cli_missing       exit 127 (a spawn FileNotFoundError is passed as 127);
    substitute  quota_exhausted   an exhaustion signal (EXHAUSTION_PATTERNS) on a codex
                                  error line, OR on any stderr line while the meter agrees
                                  (unavailable_token rate_limit_reached / quota_exhausted);
    substitute  auth_failure      an auth signal (AUTH_PATTERNS) on a codex error line;
    retry       capacity          attempt 1: a capacity signal (CAPACITY_PATTERNS) on a
                                  codex error line — codex's own advice is to try again;
    substitute  capacity_twice    the same on attempt 2 or later;
    retry       timeout / malformed        attempt 1 (same model, same admission);
    substitute  timeout_twice / malformed_twice  attempt 2 or later;
    gap         codex_error       any other non-zero exit: a harness or usage fault,
                                  never laundered into a substitution.
  THE LINE RULE (#282 R2). `codex exec` copies tool output and the prompt onto the same
  stderr, so a reviewed file that merely contains "You've hit your usage limit" or "Please
  sign in again" used to read as a quota or auth stop and buy a same-provider substitute.
  A signal now counts only on a CODEX-OWNED ERROR LINE (CODEX_ERROR_LINE_PATTERNS), the
  two shapes codex itself prints, pinned by a quota-free probe fixture:
    error      `ERROR: <msg>`
    tracing    `<ISO-8601>Z ERROR codex_<module path>: <msg>` (fractional seconds allowed)
  METER AGREEMENT. An exhaustion phrase on any other line still counts when ONE post-call
  unavailable() reading says rate_limit_reached or quota_exhausted — the only tokens that
  exist, so auth and capacity signals always need an error line. A token with no stderr
  signal adds nothing: the meter alone never creates a substitution here (a pre-call token
  is admit()'s business). The reading travels in a corroboration object built ONCE per
  failed call by corroboration_for(); the classifier itself stays pure. Without one
  (corroboration=None) the error lines come from the passed stderr and there is no token.
  exhaustion_signal() and auth_signal() are line-agnostic pattern helpers, NOT a
  classification: no caller may decide a substitution from them.
  Every verbatim copy of the prompt (and of the prompt without its trailing newlines) is
  removed from stderr before the error lines are extracted and before matching: codex
  echoes the prompt, and evidence under review can contain "ERROR: 429" or "sign in again".
  record_substitution() appends {at, kind: "substitution", key, cycle_id, cycle_id_source,
  cycle_id_file_age_s, use, substitute_for: "codex", requested_model, served_model, role,
  reason, size, size_source, snapshot_state, primary, weekly, prior_admitted_in_cycle,
  admission_id} (+ requested_by for a user request). It has
  no `admitted` key, so it never spends a budget. prior_admitted_in_cycle counts admitted
  rows of ANY use in the same cycle, net of CORRELATION (0 = nothing from this project had
  run in the cycle, so the refusal was caused by other usage on the account). The use
  "trial", a use, reason or role outside SUBSTITUTION_USES / SUBSTITUTION_REASONS /
  SUBSTITUTION_ROLES, a served_model that is not a plain word or starts with "gpt-", and
  an admission_id that is neither None nor 32 lowercase hex are caller bugs (ValueError).
  A store failure never raises: row_written false plus `error`.

CORRELATION (#282 r10: a substituted audit is not an admitted TOP call)
  Every admit() row and decision, admitted AND refused, carries `admission_id`: a fresh
  uuid4 hex (32 lowercase hex characters). Every substitution row carries `admission_id`:
  the id of the admission it REPLACES, or null. The counts net them out: _count_admitted()
  collects the admission ids named by the substitution rows of the same store (any cycle:
  the id is unique, and an adhoc key can roll over between an admission and its
  substitution) and does not count an admitted row carrying one of them;
  prior_admitted_in_cycle inherits that, and also nets the admission its own row replaces.
  Rows without admission_id (history) count as before. Only a caller holding the decision
  in-process can name it: audit_spawn (a pre-call `unavailable` token and a call-time
  substitution after an admitted audit) and `seat_model.py argv --use` (an admitted
  decision carrying `unavailable`); both name it only when the admission row was written.
  A refusal is never named (it spent nothing), and the `substitute` CLI cannot learn an id,
  so budgeted uses (consult / challenger / advisory_review / diagnosis) are never netted:
  only audits are, and budget enforcement is unchanged.

THE BUDGET-ROW SCHEMA (design §2.2 — the contract the 2026-09-28 review, the digest and
the revision-5 trial read)
  admit() appends {at, key, cycle_id, use, size, size_source, requested_model, model_class,
  admitted, reason, admission_id, snapshot_state, primary, weekly} (+ role when the caller
  names the seat, + models / roles when ONE admission covers several seats (#302), + task_key for a diagnosis or an exhausted_review, + requested_by for a user request,
  + cycle_id_source / cycle_id_file_age_s with a project_root, + unavailable when the meter
  says so).
  `role` (L18 / WP-A5) is WHICH SEAT the call was for, drawn from ADMIT_ROLES — the same
  vocabulary record_skip() records, reaching a second row shape. The row bills what was
  SPENT, so a TOP seat frozen to sol is billed `std` and `requested_model` holds the
  RESOLVED model: for a SIZED role the pair `size: complex` + `model_class: std` is
  self-evidently contradictory and exposes the freeze, but for an UNSIZED seat (arbiter,
  consultant_support) nothing on the row told them apart. `role` is preferred over a
  `frozen` flag because it names the seat for EVERY cause of the ambiguity, where a flag
  would encode one and need extending at the next. ADDITIVE: a caller that names no role
  writes no key, and the 2026-09-28 review reads its absence as "seat not recorded".
  `key` IS the design's name for the budget key and `cycle_id` CARRIES THE SAME VALUE: the
  new name is ADDITIVE, because the live stores' existing rows have only `cycle_id` and
  freshness_nudge and _count_admitted read them. Every reader tolerates the absence of the
  new keys, and readers here take the key from either (_row_key).
  EVERY row records `size` and `size_source` (design §2.1), defaulting to the L7 rule-6
  back-compat pair (complex / "default") when the caller passes neither — so a row from an
  un-migrated call site is never read as a refused light call, and the review never meets a
  hole it has to guess at. This module RECORDS a resolved size; it never resolves one.
  record_probe() (#322) appends {at, kind: "probe", key, cycle_id, use: "probe", requested_model,
  outcome, exit_code, snapshot_state, primary, weekly, cycle_id_source, cycle_id_file_age_s} for
  each await-reset probe. No `admitted` key (never budgeted) and no `substitute_for`.
  record_skip() appends {at, kind: "skip", key, cycle_id, cycle_id_source,
  cycle_id_file_age_s, use, seat_class, role, requested_model, reason, size, size_source,
  snapshot_state, primary, weekly} (+ requested_by). No `admitted` key, so it never spends a
  budget; no `substitute_for` key, so it never inflates the substitution count.

THE BUDGET STORE. The count and the append happen under one `portable_lock` on a
sidecar `.lock` file, so two concurrent admits cannot both take the last slot. If the
store cannot be locked, read or appended, a DISCRETIONARY admission (anything but
audit) is refused as `budget_store_unavailable`: a budget that cannot be recorded
cannot be enforced. A refusal decided on its merits stays that refusal. The audit passes
with `row_written: false`.
CHECK-ONLY (#282 r15, `admit(..., record=False)`, the CLI without --record). The same
decision logic and keys, but nothing is written: no row, and the store, its directory
and its .lock are never created. A use that needs the budget reads the store WITHOUT
the lock (a check cannot wait on, or block, a recording writer); a store that exists but
cannot be read is `budget_store_unavailable`, a missing store counts zero. The decision
carries `recorded: false`, `admission_id: null` and `row_written: false` (a recording
decision carries `recorded: true`). A check sees only what it can read: a store that
would refuse the append, or a writer that takes the last slot a moment later, is not
visible to it, so a check-only admission is a forecast, never a spent slot.

HONEST LIMITS
  * CODEX_HOME is not honoured. The codex CLI can relocate its home with that
    variable; a host that does so reads as `unknown` here (safe: nothing is
    refused for quota, and trial is refused). codex_model.py makes the same choice.
  * The meter describes the ACCOUNT, not this cycle: other codex use on the same
    account moves it too (design §2.4 "concurrent use not excluded").
  * rate_limit_reached_type has been null in every rollout seen on this host (435
    occurrences at plan time), so the "rate_limit_reached" rule rests on the field's
    name, not on an observed value. The primary/weekly >= 99 rule and the call-time
    classifier are the observed paths.
  * The auth patterns are codex 0.154.0's own strings, read locally from the installed
    binary; the "Not logged in on stderr" form is an UNVERIFIED rendering (see
    AUTH_PATTERNS). A codex upgrade that rewords them degrades an auth failure to
    `gap codex_error` (a recorded provider gap), never to a false pass. The 401 renders
    live on both error-line shapes (the probe fixture, 2026-09-15).
  * THE USAGE-LIMIT LINE SHAPE IS UNOBSERVED (#282 spec Accepted limits). No live quota
    stop has been captured; its line is assumed to be one of the two error-line shapes. If
    codex prints it any other way, a real stop with an agreeing meter still substitutes
    (meter agreement); without one it degrades to `gap codex_error`, never a false pass.
    "Quota exceeded. Check your plan and billing details." and "Selected model is at
    capacity" are read from the binary (`strings`), not observed on stderr either.
  * THE LINE RULE NARROWS, IT DOES NOT CLOSE, THE FORGERY HOLE (#282 K8, a candidate
    Accepted limit). codex copies tool output to stderr verbatim, so a REVIEWED FILE whose
    own line begins "ERROR: " followed by a quota / auth / capacity phrase — or forges the
    tracing prefix — still reads as a codex-owned error line. The rule turns "anywhere in
    stderr" into "a line-start forgery"; nothing here tells a copied line from codex's own.
  * The capacity retry reuses the same admission and the same model, like a timeout.
  * FILE MTIME IS THE RANKING INPUT (#282 R6). A rollout whose mtime moved without new
    content (a copy, a restore, a `touch`) is ranked as new: it can push a genuinely newer
    rollout out of the ROLLOUT_FILE_LIMIT read, which reads as `uncertain` (never as a
    fresher reading than the files hold). A rollout whose mtime is OLDER than its own
    readings (clock skew, a restore that kept old times) can hide them silently: ranked
    low it is not read, and its old mtime does not make the snapshot uncertain either.
    codex itself appends to the rollout it reads from, so neither happens in normal use.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import stat as stat_module
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import ExitStack
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
import review_risk  # noqa: E402  (the size vocabulary's owner; pure, stdlib-only, no cycle)
import codex_watch  # noqa: E402  (the owner of the 112 hard-cap exit; imports no _meta module, so no cycle)
from portable_lock import file_lock  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
USES = frozenset({"audit", "advisory_review", "review_std", "consult", "challenger",
                  "brainstorm", "ballot", "deliberation", "diagnosis", "trial",
                  # The astra reserve (roster rev 4, design 2026-09-27 s4a): the escalation seat's own
                  # use (F2), the ONE Sol -> TOP capability retry (U2/F3) and the one review a D21
                  # loop gets when it exhausts its bound (U3/F5). All three are TOP-only.
                  "escalation", "top_retry", "exhausted_review"})
#: The uses budgeted per (key, task_key) rather than per key: a diagnosis per escalated task, an
#: exhausted-loop review per D21 review id (effort_policy.review_id_for). Both REQUIRE the task key.
TASK_KEY_USES = frozenset({"diagnosis", "exhausted_review"})

#: The two model classes a codex seat can serve (D16). TOP is astra; STD is every non-TOP codex
#: tier (model_roster CODEX_STD and, from roster rev 3, CODEX_SUPPORT — #302 adds no class).
MODEL_CLASS_TOP = "top"
MODEL_CLASS_STD = "std"
MODEL_CLASSES = frozenset({MODEL_CLASS_TOP, MODEL_CLASS_STD})

#: Admitted calls allowed per (key, use, model_class) — design §2.2, the table verbatim.
#: THE CLASS IS PART OF THE KEY (D16): a complex call and a light/medium call on the SAME
#: key count SEPARATELY, because they spend different models. `None` is the table's "—"
#: cell: that class has no budget for that use, and the pairing is REFUSED
#: (REASON_CLASS_NOT_BUDGETED) rather than admitted unbudgeted — advisory_review IS the
#: complex review and review_std IS the light/medium one, so the other pairing is a call
#: the design does not define. `audit` is never budgeted and `trial` is paced by its own
#: ceiling (TRIAL_CEILING_PERCENT), so neither has a row here.
BUDGET_LIMITS: Mapping[str, Mapping[str, Optional[int]]] = MappingProxyType({
    "consult":         MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: 2}),
    "challenger":      MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: 2}),
    "advisory_review": MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: None}),
    "review_std":      MappingProxyType({MODEL_CLASS_TOP: None, MODEL_CLASS_STD: 2}),
    "brainstorm":      MappingProxyType({MODEL_CLASS_TOP: 2,    MODEL_CLASS_STD: 4}),
    "ballot":          MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: 2}),
    "deliberation":    MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: 1}),
    "diagnosis":       MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: 2}),
    # The astra reserve: TOP-only. A std pin on these uses (a TOP freeze onto a tier model) is refused
    # class_not_budgeted and served by the Claude main tier - the reserve is never billed as std.
    "escalation":       MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: None}),
    "top_retry":        MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: None}),
    "exhausted_review": MappingProxyType({MODEL_CLASS_TOP: 1,    MODEL_CLASS_STD: None}),
})
#: A class the table does not budget for that use: refused, never silently admitted.
REASON_CLASS_NOT_BUDGETED = "class_not_budgeted"

#: The size vocabulary, taken from its OWNER (review_risk, WP-A1) rather than restated:
#: a second literal is a second thing to keep in step. L7's resolution ORDER stays in
#: seat_model — this module only records the size a caller already resolved.
SIZES: Tuple[str, ...] = review_risk.SIZES
DEFAULT_SIZE = review_risk.DEFAULT_SIZE
DEFAULT_SIZE_SOURCE = review_risk.DEFAULT_SIZE_SOURCE
#: design §2.1: `size_source ∈ {forge, routing, user, risk, default}`. seat_model reads
#: SIZE_SOURCES from here, so the row contract and the resolver cannot drift apart.
SIZE_SOURCES = frozenset({"forge", "routing", "user", "risk", "default"})
#: design §2.1: `requested_by: user` for `--user-request`. The only value there is.
REQUESTED_BY_USER = "user"

#: RETIRED AS A REFUSAL (#322, 2026-09-27): admit() and tripwire() no longer refuse at this
#: reading. Kept so the `threshold` reason token on old ledger rows still parses, and so tripwire()
#: can still REPORT `threshold_tripped` (informational only; it never changes the action).
THRESHOLD_PERCENT = 70.0
TRIAL_CEILING_PERCENT = 40.0
#: A fresh reading at or above this on EITHER window: codex will refuse the call (J6).
EXHAUSTED_PERCENT = 99.0

UNAVAILABLE_RATE_LIMIT_REACHED = "rate_limit_reached"
UNAVAILABLE_QUOTA_EXHAUSTED = "quota_exhausted"
#: The admit refusals that mean "codex is out of quota right now" (#322). Only these carry the
#: reset fields (binding_window / resets_at / resets_in_s / wait_advice).
QUOTA_REFUSAL_REASONS = frozenset({UNAVAILABLE_RATE_LIMIT_REACHED, UNAVAILABLE_QUOTA_EXHAUSTED})

#: #322 wait advice. A reset at most WAIT_ADVICE_MAX_S away (20 minutes, inclusive) -> `wait`:
#: sleep until it and re-admit, no notification. Further, or unknown -> `notify`: the seat's owner
#: tells the user (who may reset the plan by hand) and polls for up to AWAIT_MAX_WAIT_S.
WAIT_ADVICE_WAIT = "wait"
WAIT_ADVICE_NOTIFY = "notify"
WAIT_ADVICE_MAX_S = 1200
BINDING_PRIMARY = "primary"
BINDING_SECONDARY = "secondary"
#: A stand-in served because await-reset ran out of time (exit 4) while codex stayed exhausted.
REASON_QUOTA_EXHAUSTED_TIMEOUT = "quota_exhausted_timeout"

#: #322 await-reset defaults (seconds) and exit codes. 0 = codex usable again, 4 = still exhausted
#: when --max-wait ran out, 5 = an auth failure (never waited on: run `codex login`), 3 = usage or
#: environment (the codex CLI is missing, a bad option).
AWAIT_MAX_WAIT_S = 1800
AWAIT_POLL_S = 120
AWAIT_MARGIN_S = 60
EXIT_AWAIT_TIMEOUT = 4
EXIT_AWAIT_AUTH = 5
#: The probe: one trivial non-ephemeral `codex exec` on the codex support tier (the roster's
#: cheapest seat) at low effort, so its rollout's rate_limits refresh the meter. Recorded as a
#: `kind: "probe"` row with `use: "probe"`; it has no `admitted` key, so it never spends a budget.
PROBE_USE = "probe"
ROW_KIND_PROBE = "probe"
PROBE_EFFORT = "low"
PROBE_HARD_CAP_S = 300
PROBE_PROMPT = "Reply with the single word OK. Do not read any file or run any command."
PROBE_AVAILABLE, PROBE_EXHAUSTED, PROBE_AUTH, PROBE_CLI_MISSING, PROBE_ERROR = (
    "available", "exhausted", "auth", "cli_missing", "error")
PROBE_OUTCOMES = frozenset({PROBE_AVAILABLE, PROBE_EXHAUSTED, PROBE_AUTH, PROBE_CLI_MISSING, PROBE_ERROR})
AWAIT_SOURCE_RESET, AWAIT_SOURCE_USER_RESET, AWAIT_SOURCE_TIMEOUT = "reset", "user_reset", "timeout"
AWAIT_SOURCE_AUTH, AWAIT_SOURCE_CLI_MISSING = "auth_failure", "cli_missing"
#: #322 fix round 1 (minor 2): every probe erroring for a NON-quota reason is not a quota verdict. After
#: AWAIT_PROBE_ERROR_LIMIT consecutive errors (no exhausted result in between) await-reset exits
#: EXIT_AWAIT_PROBE_ERROR with source probe_error; the stand-in is recorded as REASON_QUOTA_PROBE_ERROR.
AWAIT_PROBE_ERROR_LIMIT = 3
EXIT_AWAIT_PROBE_ERROR = 6
AWAIT_SOURCE_PROBE_ERROR = "probe_error"
REASON_QUOTA_PROBE_ERROR = "quota_probe_error"
#: #322 fix round 2 (m3): a probe's runaway cap is min(PROBE_HARD_CAP_S, the time left) -- it never overruns
#: --max-wait. With less than PROBE_MIN_LEFT_S left the probe is SKIPPED and the wait times out. (Fix round 1
#: floored the cap at 30 s, so with 1 s left a probe could overrun by 29 s.) PROBE_MIN_CAP_S is kept for
#: readers of the old name; nothing uses it.
PROBE_MIN_LEFT_S = 5
PROBE_MIN_CAP_S = PROBE_MIN_LEFT_S
#: #322 fix round 2 (N3): a reading-less rollout that is one of OUR probes (its user message is exactly
#: PROBE_PROMPT) is skipped by the walk without spending ROLLOUT_EMPTY_READ_LIMIT, up to this many per walk.
#: User-scoped round (item 3): 512, and a probe NEVER spends a read slot (fix round 2 let the 65th and later
#: probes spend the ROLLOUT_EMPTY_READ_LIMIT slots). At the bound the walk stops; when the skipped probes hit
#: the usage limit the snapshot is REASON_PROBE_BOUND_EXHAUSTED, which unavailable() reads as quota_exhausted.
ROLLOUT_PROBE_READ_LIMIT = 512
REASON_PROBE_BOUND_EXHAUSTED = "probe_bound_exhausted"
#: User-scoped round (item 3): a rollout larger than this is never checked for being a probe (see _probe_sized).
PROBE_ROLLOUT_MAX_BYTES = 512 << 10
#: #322 fix round 2 (item 10): ONE await-reset per ACCOUNT (codex quota is account-wide). The lock, the last
#: result, the notification claim and the timed-out marker live in ~/.claude/state, next to the exhausted
#: record (fix round 1 put them beside each project's budget store). A second caller JOINS -- it waits for
#: the lock and returns the result the first caller wrote after it started waiting. One notification per
#: exhausted RECORD: notify_claim() is keyed on the record's wave (the exhausted_until and evidence_at it was
#: opened with), so a new record starts a new wave, and retiring the record removes the claim. With no
#: record at all, the old AWAIT_MAX_WAIT_S window applies.
AWAIT_LOCK_FILENAME = "codex-await-reset.lock"
AWAIT_RESULT_FILENAME = "codex-await-reset.json"
AWAIT_JOIN_POLL_S = 15
NOTIFY_WAVE_FILENAME = "codex-notify-wave.json"
#: #322 fix round 2 (item 5, N4): ONE full wait per exhausted record. When an await-reset for a record times
#: out, the record's wave is written here; a later await-reset for the same wave does not wait again -- one
#: immediate probe (a user reset is still seen), then exit 4 with source `timed_out_for_record`.
AWAIT_TIMEOUT_FILENAME = "codex-await-timeout.json"
AWAIT_SOURCE_TIMED_OUT_FOR_RECORD = "timed_out_for_record"
#: #322 fix round 1 (F1): the persisted "codex is exhausted until T" record. ACCOUNT-WIDE (the codex
#: meter is), so it lives in ~/.claude/state, not in a project's budget store. Written by a failed probe,
#: by the `classify` CLI on a quota stop and by admit()'s own exhausted refusal; honoured by admit() until
#: T unless a NEWER usable reading shows headroom. A signal whose reset time is unknown holds for
#: EXHAUSTED_UNKNOWN_HOLD_S and never extends a known one.
EXHAUSTED_FILENAME = "codex-exhausted.json"
EXHAUSTED_UNKNOWN_HOLD_S = 30 * 60
EXHAUSTED_SOURCES = frozenset({"probe", "classify", "admit"})

#: The Claude seat that serves a use when astra cannot (J8). The trial has none: skipped.
USE_FALLBACK_ROLE: Mapping[str, str] = MappingProxyType({
    "audit": "code_reviewer",
    "advisory_review": "code_reviewer",
    "review_std": "code_reviewer",
    "consult": "consultant_main",
    "challenger": "consultant_main",
    "brainstorm": "consultant_main",
    "ballot": "consultant_main",
    "deliberation": "consultant_main",
    "diagnosis": "escalation",
    "escalation": "escalation",
    "exhausted_review": "escalation",
    # A TOP retry stands in for the seat it retries; every protected Claude row is the Claude main tier,
    # so the decision's `fallback` names it, and seat_model.substitute serves the seat's OWN role row.
    "top_retry": "consultant_main",
})
FALLBACK_PROVIDER = "claude"

#: record_substitution() vocabulary: EVERY use but the trial, which is skipped and never
#: substituted. DERIVED, not restated — a use that joins USES joins this set in the same
#: edit, which is the whole point of "the vocabulary lands together" (design §2.2).
#: "deliberation" = an avengers codex member seat (J16); the cross-cli use is "ballot" (L9).
SUBSTITUTION_USES = frozenset(USES - {"trial"})
#: The seats with a codex TOP row in seat_model's role table (consultant_support is the codex support tier, not astra).
SUBSTITUTION_ROLES = frozenset({"code_reviewer", "consultant_main", "arbiter", "escalation"})

#: D20 seat classes. A DISCRETIONARY seat (a budgeted codex TOP call) substitutes above the
#: trip-wire; a SUPPORTING seat (consultant_support on the support tier, a research lookup — trip-wire
#: checked but NOT budgeted) takes a recorded skip; the AUDIT stops only on real exhaustion.
SEAT_CLASS_DISCRETIONARY = "discretionary"
SEAT_CLASS_SUPPORTING = "supporting"
SEAT_CLASS_AUDIT = "audit"
SEAT_CLASSES = frozenset({SEAT_CLASS_DISCRETIONARY, SEAT_CLASS_SUPPORTING, SEAT_CLASS_AUDIT})
#: tripwire() verdicts.
TRIPWIRE_RUN, TRIPWIRE_SUBSTITUTE, TRIPWIRE_SKIP = "run", "substitute", "skip"
REASON_BELOW_THRESHOLD = "below_threshold"
REASON_AUDIT_EXEMPT = "audit_exempt"
REASON_THRESHOLD = "threshold"
#: record_skip() vocabulary: the roles a skip can be recorded for (the TOP seats plus the
#: supporting consultant_support seat, which has no TOP row and so is absent from SUBSTITUTION_ROLES), and
#: the reasons tripwire() can actually produce for a skip. A reason outside this set means
#: the caller is recording something the trip-wire did not decide.
SKIP_ROLES = frozenset(SUBSTITUTION_ROLES | {"consultant_support"})
SKIP_REASONS = frozenset({REASON_THRESHOLD, UNAVAILABLE_RATE_LIMIT_REACHED,
                          UNAVAILABLE_QUOTA_EXHAUSTED})
#: admit() vocabulary: the seats that can make a codex call. SHARED WITH SKIP_ROLES BY
#: IDENTITY, not by a second literal — a role that can be skipped is exactly a role that
#: can be admitted, so the two can never drift apart (design §2.2, "the vocabulary lands
#: together"). The name exists because `SKIP_ROLES` reads wrong at an admission.
ADMIT_ROLES = SKIP_ROLES
ROW_KIND_SKIP = "skip"
#: Every way astra can be unavailable (amendment 1): a non-trial admit refusal, an
#: unavailable() token, a classify_codex_failure() substitute reason, or a plan-time check.
SUBSTITUTION_REASONS = frozenset({
    "threshold", "budget_spent", "budget_store_unavailable",
    UNAVAILABLE_RATE_LIMIT_REACHED, UNAVAILABLE_QUOTA_EXHAUSTED,
    "cli_missing", "auth_failure", "timeout_twice", "malformed_twice", "no_eligible_model",
    "capacity_twice",  # #282: the model was at capacity on the call AND on its one retry
    # S081 rev 4 D21 F7: a "-" cell refusal is an admit refusal like the others. Missing here, it
    # crashed `seat_model.py argv --use` (exit 1, empty stdout) instead of taking the D6 path.
    REASON_CLASS_NOT_BUDGETED,
    # #322: the seat waited for a quota reset (codex_quota.py await-reset) and the wait ran out (exit 4).
    REASON_QUOTA_EXHAUSTED_TIMEOUT,
    # #322 fix round 1: the wait could not tell -- every probe failed for a non-quota reason (exit 6).
    REASON_QUOTA_PROBE_ERROR,
    # The astra reserve F3: a TOP retry whose TOP pin is the model that just failed, or bills the std class
    # (a freeze onto a tier model), is not a retry at all - the seat goes to the Claude main tier instead.
    "top_retry_same_pin", "top_retry_not_top",
    # fix round 1: the seat's OWN pin bills TOP (e.g. the vendor ranks Sol TOP) - a TOP retry buys nothing new.
    "top_retry_seat_is_top",
})
#: The uses a TOP retry may follow (fix round 1, item 6): never the trial or the exhausted-loop review (both
#: SKIPPED, never substituted), the audit (audit_spawn's arm) or a retry itself (no re-entry).
TOP_RETRY_ORIGIN_USES = frozenset(USES - {"trial", "exhausted_review", "audit", "top_retry"})
ROW_KIND_TOP_RETRY = "top_retry"
#: record_top_retry() outcomes: the TOP attempt was admitted, or it was served by the Claude main tier, or
#: (#322 fix round 2, item 3) it was refused for QUOTA with --await-quota and waits for a reset: `pending`
#: permits exactly ONE resumption of the same failed admission (find_admission).
TOP_RETRY_PENDING = "pending"
TOP_RETRY_OUTCOMES = frozenset({"admitted", "substituted", TOP_RETRY_PENDING})
SUBSTITUTE_FOR = "codex"
ROW_KIND_SUBSTITUTION = "substitution"
#: User-scoped round (item 5): claim_top_retry()'s reservation file, `<budget stem>` + this, beside the store.
TOP_RETRY_CLAIMS_SUFFIX = ".top-retry-claims.jsonl"
#: #282 r10: an admission id is uuid4().hex, exactly 32 lowercase ASCII hex characters.
ADMISSION_ID_PATTERN = re.compile(r"[0-9a-f]{32}", re.ASCII)
#: A model name must be one plain word (it may reach a command line) of bounded length.
_MODEL_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}", re.ASCII)

#: classify_codex_failure() actions and the exit status a shell gives "command not found".
ACTION_OK, ACTION_RETRY, ACTION_SUBSTITUTE, ACTION_GAP = "ok", "retry", "substitute", "gap"
EXIT_COMMAND_NOT_FOUND = 127
#: codex_watch's runaway-cap exit (D24): the call stayed ACTIVE until the per-effort cap stopped it.
#: ONE definition - the watchdog owns the number and this module binds it (S081 rev 4 D21 F10).
EXIT_HARD_CAP = codex_watch.EXIT_HARD_CAP
#: Largest --stderr-file / --prompt-file the classify CLI reads; bigger is an environment
#: error, because a truncated prompt could no longer be removed from a truncated echo.
CLASSIFY_READ_BYTES = 16 << 20
#: How much of --output-file is inspected for non-blank content.
OUTPUT_PROBE_BYTES = 1 << 20

#: Exhaustion signals, in the forms codex renders them. Moved here from audit_spawn.py
#: (J9: one owner); every string below was re-read from the installed codex 0.154.0
#: binary (`strings`, a local read, no model call, 2026-09-14; quota_exceeded 2026-09-15):
#:   usage_limit              `You've hit your usage limit.` (+ plan-specific tails)
#:   http_429                 `exceeded retry limit, last status: ` + a 429 status /
#:                            `429 Too Many Requests` ("Too Many Requests" is the http crate's
#:                            reason phrase in the same binary)
#:   rate_limit_exceeded      `rate limit exceeded: `
#:   rate_limit_reached_type  the rate_limits field name carrying a non-null value
#:   quota_exceeded           `Quota exceeded. Check your plan and billing details.` (#282)
#: A match counts only on a codex-owned error line, or on any line while the meter agrees
#: (#282 R2, the module docstring's LINE RULE). The line shape of a live quota stop is
#: UNOBSERVED (HONEST LIMITS).
EXHAUSTION_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("usage_limit", re.compile("you(?:'|\u2019)ve hit your usage limit", re.IGNORECASE)),
    ("http_429", re.compile(
        r"(?:\bstatus(?:[ \t]+code)?[ \t]*[:=]?[ \t]*429\b|\b429[ \t]+too[ \t]+many[ \t]+requests\b)",
        re.IGNORECASE)),
    ("rate_limit_exceeded", re.compile(r"\brate limit exceeded\b", re.IGNORECASE)),
    ("rate_limit_reached_type", re.compile(
        r"rate_limit_reached_type[\"']?[ \t]*[:=][ \t]*[\"']?(?!null\b|none\b)[A-Za-z_]",
        re.IGNORECASE)),
    ("quota_exceeded", re.compile(r"\bquota exceeded\.[ \t]+check your plan and billing details\b",
                                  re.IGNORECASE)),
)

#: Capacity signals (#282 classifier vocabulary). Source: `strings` over the installed codex
#: 0.154.0 binary, 2026-09-15: `Selected model is at capacity. Please try a different model.`
#: Counts only on a codex-owned error line (no meter token exists for capacity). Attempt 1 ->
#: retry capacity (same model, same admission); attempt 2 or later -> substitute capacity_twice.
CAPACITY_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("model_at_capacity", re.compile(r"\bselected model is at capacity\b", re.IGNORECASE)),
)

#: The two stderr line shapes codex itself prints for an error (#282 R2). Pinned by
#: tests/fixtures/codex/exec-401-error-lines.txt, the quota-free probe `env -u OPENAI_API_KEY
#: CODEX_HOME=$(mktemp -d) codex exec --skip-git-repo-check -s read-only -m gpt-5.6-sol "OK"`
#: on codex 0.154.0, 2026-09-15, which printed its 401 on both. Anchored at the line start
#: and case-sensitive: an indented, lower-case or mid-line "error:" is tool output, not codex.
#: Each is applied to ONE line (split on "\n", a trailing "\r" dropped); group `message` is
#: the text the signal patterns are matched against.
CODEX_ERROR_LINE_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("error", re.compile(r"^ERROR: (?P<message>.*)$", re.MULTILINE | re.ASCII)),
    ("tracing", re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ERROR codex_[a-z_:]+: (?P<message>.*)$",
        re.MULTILINE | re.ASCII)),
)
#: The unavailable() tokens that corroborate an exhaustion phrase on a non-error line.
METER_EXHAUSTION_TOKENS = frozenset({UNAVAILABLE_RATE_LIMIT_REACHED, UNAVAILABLE_QUOTA_EXHAUSTED})

#: Auth failure signals (J9 "grounded in local evidence"). Source: `strings` over the
#: installed codex 0.154.0 binary (~/.codex/packages/standalone/releases/0.154.0-*/bin/codex),
#: a local read, no model call, 2026-09-14:
#:   refresh_failed  VERIFIED string: `Your access token could not be refreshed[ because your
#:                   refresh token has expired | was already used | was revoked | you have
#:                   since logged out or signed in to another account]. ...` and `Your
#:                   authentication session could not be refreshed automatically. ...`
#:   sign_in_again   VERIFIED string: `Please log out and sign in again.` (27 occurrences) /
#:                   `Please sign in again.` — the tail of every message above.
#:   not_logged_in   the string `Not logged in` is VERIFIED (codex's login status); that
#:                   `codex exec` prints it on stderr at the start of a line is UNVERIFIED.
#:                   Anchored to a line start so an MCP server's "... is not logged in"
#:                   cannot match.
#:   http_401        VERIFIED rendering (#282 probe fixture, 2026-09-15): `ERROR: unexpected
#:                   status 401 Unauthorized: ...` and the tracing line `... ERROR
#:                   codex_api::endpoint::responses_websocket: ... HTTP error: 401 Unauthorized`.
#: Deliberately NOT matched: `OAuth refresh token was rejected` (an MCP server's OAuth, not
#: the codex account) and `Failed to refresh token: ` (logged during recoverable refreshes).
#: Every auth signal counts ONLY on a codex-owned error line (#282 R2): no meter token can
#: corroborate an auth failure, and "Please sign in again." is ordinary text in a reviewed file.
AUTH_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("refresh_failed", re.compile(
        r"\byour (?:access token|authentication session) could not be refreshed\b", re.IGNORECASE)),
    ("sign_in_again", re.compile(r"\bplease (?:log out and )?sign in again\b", re.IGNORECASE)),
    ("not_logged_in", re.compile(r"^[ \t]*(?:error:[ \t]*)?not logged in\b", re.IGNORECASE | re.MULTILINE)),
    ("http_401", re.compile(r"(?:\bunexpected status[ \t]+401\b|\b401[ \t]+unauthorized\b)", re.IGNORECASE)),
)

FRESH_WINDOW_S = 30 * 60
FUTURE_SKEW_S = 120
#: A .forge/cycle-id older than this counts as absent (J3b). Exactly this old is still used.
CYCLE_ID_MAX_AGE_S = 24 * 3600
#: A usable cycle id: alphanumeric first, then [A-Za-z0-9._:-], at most 128 characters (J4).
CYCLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
#: Bytes read from .forge/cycle-id; a valid first line is far shorter.
CYCLE_ID_READ_BYTES = 1024
SOURCE_CYCLE_ID = "cycle-id"
SOURCE_ADHOC_BASE = "adhoc-base"
SOURCE_ADHOC_NOBASE = "adhoc-nobase"
#: admit() only: the caller passed an id that is not this project's derived key.
SOURCE_EXPLICIT = "explicit"
#: NOT the meter's walk bound any more (#282 R6 replaced it with ROLLOUT_WINDOW_DAYS and
#: ROLLOUT_STAT_BUDGET). Kept for its one other user: audit_spawn._codex_rollout_tokens looks
#: for ITS OWN call's rollout in the DAY_DIR_LIMIT newest day directories (_newest_day_dirs).
DAY_DIR_LIMIT = 3
#: #282 R6: the meter walks day directories dated no earlier than the UTC date of `now` minus
#: (ROLLOUT_WINDOW_DAYS + 1) days: the weekly window plus one day for codex's LOCAL-date names.
ROLLOUT_WINDOW_DAYS = 7
#: #282 R6: at most this many `rollout-*.jsonl` entries are stat'ed per walk (no content read).
ROLLOUT_STAT_BUDGET = 2000
#: The newest rollouts BY MTIME that are tail-read per walk AND carry a usable reading. #322 fix round 1
#: (F1): a rollout with NO usable rate_limits reading does not count toward this limit. A probe (or any
#: call) that hits the usage limit writes a rollout whose only rate_limits object is `limit_id: premium,
#: primary: null`; counted, four such probes pushed the real 100% reading out of the window and the meter
#: went `unknown (no_rate_limits)` while codex was exhausted, so admit() let seats through.
ROLLOUT_FILE_LIMIT = 4
#: #322 fix round 1 (F1): the walk tail-reads at most ROLLOUT_FILE_LIMIT + ROLLOUT_EMPTY_READ_LIMIT rollouts
#: in all, stopping as soon as ROLLOUT_FILE_LIMIT of them carried a usable reading -- so up to this many
#: reading-less (or unreadable) ones are read on top. It bounds the walk's I/O; a candidate beyond it is
#: unread (and makes an older reading `uncertain`, exactly as before). 0 is the walk before the fix.
ROLLOUT_EMPTY_READ_LIMIT = 32
TAIL_BYTES = 1 << 20
LOCK_TIMEOUT_S = 5.0

EXIT_ADMITTED = 0
EXIT_ERROR = 3
EXIT_REFUSED = 10

BUDGET_FILENAME = "astra-budget.jsonl"
STATE_FRESH, STATE_STALE, STATE_UNKNOWN = "fresh", "stale", "unknown"
#: #282 R6: a reading exists but a newer one may exist unread. Never trips a threshold.
STATE_UNCERTAIN = "uncertain"
REASON_OBSERVED_TOO_LONG_AGO = "observed_too_long_ago"
REASON_NEWER_CANDIDATE_UNREAD = "newer_candidate_unread"
REASON_STAT_BUDGET_EXHAUSTED = "stat_budget_exhausted"

_MODEL_POLICY_PATH = _META.parent / "smart-config" / "scripts" / "model_policy.py"
_model_policy_slug_fn = None
_model_policy_loaded = False

_RATE_LIMITS_MARKER = b'"rate_limits"'
_HEX7 = re.compile(r"^[0-9a-fA-F]{7}")
_DIGITS4 = re.compile(r"^\d{4}$")
_DIGITS2 = re.compile(r"^\d{2}$")


# --------------------------------------------------------------------------- #
# Paths — derived from Path.home() at CALL time, so tests redirect HOME.
# --------------------------------------------------------------------------- #
def default_sessions_dir() -> Path:
    return Path.home() / ".codex" / "sessions"


def _fallback_project_slug(project_root) -> str:
    """The documented slug rule (smart-config design §5): every character of the
    absolute path outside [A-Za-z0-9] becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.fspath(project_root)))


def _load_model_policy_slug():
    """`model_policy._project_slug`, imported once and FAIL-OPEN (None on any error)."""
    global _model_policy_slug_fn, _model_policy_loaded
    if _model_policy_loaded:
        return _model_policy_slug_fn
    _model_policy_loaded = True
    try:
        spec = importlib.util.spec_from_file_location("_codex_quota_model_policy",
                                                      str(_MODEL_POLICY_PATH))
        if spec is None or spec.loader is None:
            raise ImportError(str(_MODEL_POLICY_PATH))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, "_project_slug", None)
        _model_policy_slug_fn = fn if callable(fn) else None
    except Exception:
        _model_policy_slug_fn = None
    return _model_policy_slug_fn


def project_slug(project_root) -> str:
    fn = _load_model_policy_slug()
    if fn is not None:
        try:
            slug = fn(os.fspath(project_root))
            if isinstance(slug, str) and slug:
                return slug
        except Exception:
            pass
    return _fallback_project_slug(project_root)


def budget_path_for(project_root) -> Path:
    return Path.home() / ".claude" / "projects" / project_slug(project_root) / BUDGET_FILENAME


def lock_path_for(budget_path) -> Path:
    budget_path = Path(budget_path)
    return budget_path.with_name(budget_path.name + ".lock")


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def _now_epoch(now) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.timestamp()
    if isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now):
        return float(now)
    raise ValueError(f"now must be None, a datetime or epoch seconds, got {now!r}")


def _iso_z(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _finite_number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _resets_at(value):
    number = _finite_number(value)
    if number is None:
        return None
    return int(value) if isinstance(value, int) else number


# --------------------------------------------------------------------------- #
# snapshot()
# --------------------------------------------------------------------------- #
def _empty_snapshot(reason: str) -> Dict[str, Any]:
    return {
        "state": STATE_UNKNOWN,
        "primary_used_percent": None,
        "primary_resets_at": None,
        "secondary_used_percent": None,
        "secondary_resets_at": None,
        "observed_at": None,
        "source": None,
        "limit_id": None,
        "reason": reason,
    }


def _sorted_dirs(parent: Path, pattern) -> List[Path]:
    try:
        with os.scandir(parent) as it:
            names = [e.name for e in it if pattern.match(e.name) and e.is_dir()]
    except OSError:
        return []
    return [parent / n for n in sorted(names, reverse=True)]


def _newest_day_dirs(root: Path, limit: int) -> List[Path]:
    """The `limit` newest YYYY/MM/DD directories by name. Not the meter's walk (#282 R6):
    audit_spawn uses it to find its own call's rollout."""
    days: List[Path] = []
    for year in _sorted_dirs(root, _DIGITS4):
        for month in _sorted_dirs(year, _DIGITS2):
            for day in _sorted_dirs(month, _DIGITS2):
                days.append(day)
                if len(days) >= limit:
                    return days
    return days


def _window_day_dirs(root: Path, now_epoch: float) -> List[Path]:
    """The YYYY/MM/DD directories dated no earlier than the UTC date of `now` minus
    (ROLLOUT_WINDOW_DAYS + 1) days, newest first (#282 R6). Dates compare as (year, month,
    day) integer triples, so an impossible name such as 2026/02/31 never raises."""
    first = datetime.fromtimestamp(now_epoch, timezone.utc).date() - timedelta(days=ROLLOUT_WINDOW_DAYS + 1)
    cutoff = (first.year, first.month, first.day)
    days: List[Path] = []
    for year in _sorted_dirs(root, _DIGITS4):  # names descending == dates descending
        y = int(year.name)
        if y < cutoff[0]:
            break
        for month in _sorted_dirs(year, _DIGITS2):
            m = int(month.name)
            if (y, m) < cutoff[:2]:
                break
            for day in _sorted_dirs(month, _DIGITS2):
                if (y, m, int(day.name)) < cutoff:
                    break
                days.append(day)
    return days


#: One stat'ed rollout: (st_mtime_ns, name, path, st_mtime).
_Candidate = Tuple[int, str, Path, float]


def _window_rollouts(day_dirs: List[Path]) -> Tuple[List[_Candidate], bool]:
    """(stat'ed `rollout-*.jsonl` regular files, stat budget exhausted) (#282 R6).

    Stats at most ROLLOUT_STAT_BUDGET entries, newest directory first and names descending
    inside one; reads no content. `exhausted` is True only when an entry of the window was
    left unstat'ed. An entry whose stat fails, or that is not a regular file, still spent
    its stat call and is not a candidate."""
    candidates: List[_Candidate] = []
    stat_calls = 0
    for day in day_dirs:
        try:
            with os.scandir(day) as it:
                entries = [e for e in it if e.name.startswith("rollout-") and e.name.endswith(".jsonl")]
        except OSError:
            continue
        for entry in sorted(entries, key=lambda e: e.name, reverse=True):
            if stat_calls >= ROLLOUT_STAT_BUDGET:
                return candidates, True
            stat_calls += 1
            try:
                st = entry.stat()  # follows a symlink, as the name-ranked walk's is_file() did
            except OSError:
                continue
            if stat_module.S_ISREG(st.st_mode):
                candidates.append((st.st_mtime_ns, entry.name, day / entry.name, st.st_mtime))
    return candidates, False


def _tail_lines(path: Path, limit: int) -> List[bytes]:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start = max(0, size - limit)
        fh.seek(start)
        data = fh.read(limit)
    if start > 0:
        newline = data.find(b"\n")
        data = data[newline + 1:] if newline >= 0 else b""
    return data.split(b"\n")


def _rate_limits_from_line(line: bytes) -> Optional[Tuple[Optional[float], Dict[str, Any]]]:
    """(observed epoch or None, the rate_limits object) for ANY rollout line carrying one —
    including a session-closing entry whose primary is null."""
    if _RATE_LIMITS_MARKER not in line:
        return None
    try:
        obj = json.loads(line.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    payload = obj.get("payload")
    rate_limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(rate_limits, dict):
        return None
    return _parse_timestamp(obj.get("timestamp")), rate_limits


def _reading_from_line(line: bytes) -> Optional[Dict[str, Any]]:
    parsed = _rate_limits_from_line(line)
    return None if parsed is None else _reading_from_rate_limits(*parsed)


def _reading_from_rate_limits(observed: Optional[float], rate_limits: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A usable reading (primary with a finite, non-negative used_percent), else None."""
    primary = rate_limits.get("primary")
    if not isinstance(primary, dict):
        return None
    used = _finite_number(primary.get("used_percent"))
    if used is None or used < 0:
        return None
    secondary = rate_limits.get("secondary")
    weekly = weekly_resets = None
    if isinstance(secondary, dict):
        weekly = _finite_number(secondary.get("used_percent"))
        if weekly is not None and weekly < 0:
            weekly = None
        if weekly is not None:
            weekly_resets = _resets_at(secondary.get("resets_at"))
    limit_id = rate_limits.get("limit_id")
    return {
        "observed_epoch": observed,
        "primary_used_percent": used,
        "primary_resets_at": _resets_at(primary.get("resets_at")),
        "secondary_used_percent": weekly,
        "secondary_resets_at": weekly_resets,
        "limit_id": limit_id if isinstance(limit_id, str) else None,
    }


#: limit_id (None when absent or not a string) -> (observed epoch, rate_limit_reached_type,
#: primary resets_at, secondary resets_at), all four from ONE rate_limits object (#282 R5).
_LimitStates = Dict[Optional[str], Tuple[float, Any, Any, Any]]


def _window_resets_at(window: Any):
    """A rate_limits window's resets_at (finite number) or None; the window may be null."""
    return _resets_at(window.get("resets_at")) if isinstance(window, dict) else None


def _scan_rollout(path: Path) -> Tuple[Optional[Dict[str, Any]], _LimitStates, bool]:
    """One bounded tail read: (the last usable reading, the last timestamped rate_limits
    object per limit_id as its _LimitStates tuple, whether the READ ITSELF FAILED). File order
    is chronological within one rollout.

    The third value is #282 F6: a read that fails and a read that finds nothing both yield no
    reading, but only the first leaves the file's content UNKNOWN. _scan treats a failed read
    as an unread candidate; without the flag an older reading was reported `fresh`."""
    try:
        lines = _tail_lines(path, TAIL_BYTES)
    except OSError:
        return None, {}, True
    last, limits = _scan_lines(lines)
    return last, limits, False


def _scan_lines(lines: List[bytes]) -> Tuple[Optional[Dict[str, Any]], _LimitStates]:
    """_scan_rollout's parse of lines already read."""
    last = None
    limits: _LimitStates = {}
    for line in lines:
        parsed = _rate_limits_from_line(line)
        if parsed is None:
            continue
        observed, rate_limits = parsed
        reading = _reading_from_rate_limits(observed, rate_limits)
        if reading is not None:
            last = reading
        if observed is not None:
            limit_id = rate_limits.get("limit_id")
            key = limit_id if isinstance(limit_id, str) else None
            limits[key] = (observed, rate_limits.get("rate_limit_reached_type"),
                           _window_resets_at(rate_limits.get("primary")),
                           _window_resets_at(rate_limits.get("secondary")))
    return last, limits


def _last_reading(path: Path) -> Optional[Dict[str, Any]]:
    return _scan_rollout(path)[0]


def _user_message_text(payload: Dict[str, Any]) -> Optional[str]:
    """The WHOLE text of a user message payload (every part, in order), or None when the payload is not a
    user message or carries a part with no text (an image: never a probe)."""
    if payload.get("type") == "user_message":
        message = payload.get("message")
        return message if isinstance(message, str) else None
    if payload.get("type") == "message" and payload.get("role") == "user":
        content = payload.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list) or not content:
            return None
        texts = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else None
            if not isinstance(text, str):
                return None
            texts.append(text)
        return "".join(texts)
    return None


#: #322 final verification (codex item 2): the ONLY other user messages a probe rollout may hold are codex's
#: own injected context blocks, named -- an arbitrary `<request>` message makes it a real session.
_PROBE_CONTEXT_TAGS = ("<environment_context>", "<user_instructions>")


def _lines_are_own_probe(lines: List[bytes]) -> bool:
    """_is_own_probe() on lines already read."""
    found = False
    for line in lines:
        if b'"user' not in line:          # cheap: every user message line names role/type "user..."
            continue
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        payload = obj.get("payload") if isinstance(obj, dict) else None
        if not isinstance(payload, dict) or payload.get("type") not in ("user_message", "message") \
                or (payload.get("type") == "message" and payload.get("role") != "user"):
            continue
        text = _user_message_text(payload)
        if text is not None and text.strip() == PROBE_PROMPT:
            found = True
        elif text is None or not text.lstrip().startswith(_PROBE_CONTEXT_TAGS):
            # User-scoped round (item 2): any OTHER user message -- the prompt plus another instruction, a
            # second turn, an image -- makes this a real session, never a probe. Only codex's own injected
            # context blocks (`<environment_context>`, `<user_instructions>`) sit beside a probe's request.
            return False
    return found


def _probe_sized(path: Path) -> bool:
    """User-scoped round (item 3): the cheap first check -- a probe's rollout is small (about 94 KB live on
    2026-09-28, the request and its limit error after codex's own instructions), so a file larger than
    PROBE_ROLLOUT_MAX_BYTES is never read a second time to ask whether it is one. Never raises."""
    try:
        return path.stat().st_size <= PROBE_ROLLOUT_MAX_BYTES
    except OSError:
        return False


def _is_own_probe(path: Path) -> bool:
    """#322 fix round 2 (N3): is this rollout one of await-reset's own probes? True only when a USER message in
    it is EXACTLY PROBE_PROMPT -- its whole text, every part (`response_item` message with role user, or an
    `event_msg` user_message) -- and no other user message is in it but codex's own `<...>` context blocks.
    User-scoped round (item 2): fix round 2 matched a message with ANY part equal to the prompt, so a real
    message holding the prompt plus another instruction was skipped as a probe. A rollout that merely QUOTES
    the prompt (a review reading this file) is not a probe. Never raises."""
    try:
        lines = _tail_lines(path, TAIL_BYTES)
    except OSError:
        return False
    return _lines_are_own_probe(lines)


def _classify(reading: Dict[str, Any], now: float) -> Tuple[str, Optional[str]]:
    observed = reading["observed_epoch"]
    if observed is None:
        return STATE_STALE, "observed_at_unparseable"
    age = now - observed
    if age > FRESH_WINDOW_S:
        return STATE_STALE, REASON_OBSERVED_TOO_LONG_AGO
    if age < -FUTURE_SKEW_S:
        return STATE_STALE, "observed_in_the_future"
    primary_resets = reading["primary_resets_at"]
    if primary_resets is None:
        return STATE_STALE, "primary_resets_at_missing"
    if now >= primary_resets:
        return STATE_STALE, "primary_window_reset"
    if reading["secondary_used_percent"] is not None:
        weekly_resets = reading["secondary_resets_at"]
        if weekly_resets is None:
            return STATE_STALE, "secondary_resets_at_missing"
        if now >= weekly_resets:
            return STATE_STALE, "secondary_window_reset"
    return STATE_FRESH, None


def _scan(sessions_dir, now_epoch: float) -> Tuple[Dict[str, Any], _LimitStates]:
    """(snapshot, newest rate_limits object per limit_id) from ONE bounded walk. Never raises."""
    limits: _LimitStates = {}
    try:
        root = Path(sessions_dir) if sessions_dir is not None else default_sessions_dir()
        if not root.is_dir():
            return _empty_snapshot("no_sessions_dir"), {}
        candidates, stat_budget_exhausted = _window_rollouts(_window_day_dirs(root, now_epoch))
        if not candidates:
            return _empty_snapshot("no_rollouts"), {}
        ranked = sorted(candidates, key=lambda c: (c[0], c[1]), reverse=True)  # mtime, then name
        unread: List[_Candidate] = []
        usable = 0
        reads = 0          # rollouts that spent a slot of the ROLLOUT_FILE_LIMIT + ROLLOUT_EMPTY_READ_LIMIT bound
        probes_skipped = 0
        beyond_bound = False  # the walk stopped with candidates left unread (not just failed reads)
        best: Optional[Tuple[Dict[str, Any], Path]] = None
        probe_bound = False     # the walk stopped at ROLLOUT_PROBE_READ_LIMIT skipped probes
        exhausted_probe = False  # a skipped probe carried a rate_limits object: the usage-limit signature
        for position, candidate in enumerate(ranked):  # newest mtime first; ties keep the newer file
            if usable >= ROLLOUT_FILE_LIMIT or reads >= ROLLOUT_FILE_LIMIT + ROLLOUT_EMPTY_READ_LIMIT \
                    or probes_skipped >= ROLLOUT_PROBE_READ_LIMIT:
                probe_bound = probes_skipped >= ROLLOUT_PROBE_READ_LIMIT
                unread.extend(ranked[position:])
                beyond_bound = True
                break
            _mtime_ns, _name, path, _mtime = candidate
            reading, file_limits, read_failed = _scan_rollout(path)
            if reading is None and not read_failed and _probe_sized(path) and _is_own_probe(path):
                # #322 fix round 2 (N3): an await-reset probe that hit the usage limit carries no reading.
                # It is skipped: it spends no read slot. (A probe that ANSWERED has a reading and is walked
                # like any rollout: it is how a reset is seen.) User-scoped round (item 3): probes NEVER spend
                # a read slot -- fix round 2 let every probe past the 64th spend one, so 100 newer probes
                # hid an older 100% reading. The walk skips at most ROLLOUT_PROBE_READ_LIMIT of them (each a
                # small file: _probe_sized gates the second read), then stops. (Item 2, Opus N3): its
                # rate_limits objects are still MERGED -- a set rate_limit_reached_type is evidence.
                probes_skipped += 1
                exhausted_probe = exhausted_probe or bool(file_limits)
                for key, state in file_limits.items():
                    current_limit = limits.get(key)
                    if current_limit is None or state[0] > current_limit[0]:
                        limits[key] = state
                continue
            reads += 1
            if read_failed:
                # #282 F6: the file's content is UNKNOWN, not absent. It joins the unread
                # candidates, so a failed read newer than the chosen reading says `uncertain`
                # instead of letting an older reading pass as the newest one.
                unread.append(candidate)
            for key, state in file_limits.items():
                current_limit = limits.get(key)
                if current_limit is None or state[0] > current_limit[0]:
                    limits[key] = state
            if reading is None:
                # #322 fix round 1 (F1): no usable reading (a usage-limit probe's `primary: null`, a
                # killed call) -- it does not spend one of the ROLLOUT_FILE_LIMIT slots.
                continue
            usable += 1
            if best is None:
                best = (reading, path)
                continue
            current = best[0]["observed_epoch"]
            candidate = reading["observed_epoch"]
            if candidate is not None and (current is None or candidate > current):
                best = (reading, path)
        if best is None:
            if probe_bound and exhausted_probe:
                # User-scoped round (item 3): the walk stopped at the probe bound with nothing usable read, and
                # the newest evidence is our own probes hitting the usage limit (a probe only runs while codex
                # is refused). The last usable reading is out of reach, not absent: this is still EXHAUSTED,
                # never an `uncertain` that lets an expired record admit a seat.
                snap = _empty_snapshot(REASON_PROBE_BOUND_EXHAUSTED)
                snap["state"] = STATE_UNCERTAIN
                return snap, limits
            if beyond_bound:
                # #322 fix round 2 (N3): nothing usable was read, but the walk hit its read bound with
                # candidates left unread -- one of them may hold the newest reading (an exhausted one). That is
                # `uncertain`, never `unknown` (which reads as "no evidence at all"). Failed reads alone keep
                # the K42 rule: with nothing read at all the snapshot stays `unknown`.
                snap = _empty_snapshot(REASON_NEWER_CANDIDATE_UNREAD)
                snap["state"] = STATE_UNCERTAIN
                return snap, limits
            return _empty_snapshot("no_rate_limits"), limits
        reading, path = best
        observed = reading["observed_epoch"]
        if any(observed is None or mtime > observed for _ns, _n, _p, mtime in unread):
            state, reason = STATE_UNCERTAIN, REASON_NEWER_CANDIDATE_UNREAD
        elif stat_budget_exhausted:
            state, reason = STATE_UNCERTAIN, REASON_STAT_BUDGET_EXHAUSTED
        else:
            state, reason = _classify(reading, now_epoch)
        return {
            "state": state,
            "primary_used_percent": reading["primary_used_percent"],
            "primary_resets_at": reading["primary_resets_at"],
            "secondary_used_percent": reading["secondary_used_percent"],
            "secondary_resets_at": reading["secondary_resets_at"],
            "observed_at": _iso_z(observed) if observed is not None else None,
            "source": str(path),
            "limit_id": reading["limit_id"],
            "reason": reason,
        }, limits
    except Exception as exc:  # the never-raises contract
        return _empty_snapshot(f"error:{type(exc).__name__}"), {}


def snapshot(*, sessions_dir=None, now=None) -> Dict[str, Any]:
    """The newest codex rate-limit reading. Never raises; no model call, socket or process."""
    try:
        now_epoch = _now_epoch(now)
    except Exception:
        return _empty_snapshot("bad_now")
    return _scan(sessions_dir, now_epoch)[0]


# --------------------------------------------------------------------------- #
# unavailable()
# --------------------------------------------------------------------------- #
def _reached_type_set(value: Any) -> bool:
    """rate_limit_reached_type counts only when it is not null / false / empty (J6)."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _reached_void_at(reached_type: Any, primary_resets: Any, secondary_resets: Any):
    """When a set rate_limit_reached_type stops counting (#282 R5), or None (age bound only).

    "primary" -> primary_resets, "secondary" -> secondary_resets; any other or unrecognised
    value, and a named reset that is null, -> the EARLIEST non-null reset of the same object."""
    earliest = min((r for r in (primary_resets, secondary_resets) if r is not None), default=None)
    if isinstance(reached_type, str):
        if reached_type == "primary" and primary_resets is not None:
            return primary_resets
        if reached_type == "secondary" and secondary_resets is not None:
            return secondary_resets
    return earliest


def _unavailable_from(snap: Dict[str, Any], limits: _LimitStates, now_epoch: float) -> Optional[str]:
    # #282 F5: an UNCERTAIN scan admits it may have missed a newer rollout, and a newer object
    # of the same limit is exactly what clears a reached flag. Only a certain scan may stop a
    # call before it is made. `stale` and `unknown` keep the reached-flag rule (K41): there the
    # flags that WERE read are still the newest evidence the walk can offer.
    if snap.get("reason") == REASON_PROBE_BOUND_EXHAUSTED:
        # User-scoped round (item 3): the walk's probe bound, reached through probes that hit the usage limit.
        return UNAVAILABLE_QUOTA_EXHAUSTED
    if snap.get("state") == STATE_UNCERTAIN:
        return None
    for observed, reached_type, primary_resets, secondary_resets in limits.values():
        age = now_epoch - observed
        if not (-FUTURE_SKEW_S <= age <= FRESH_WINDOW_S) or not _reached_type_set(reached_type):
            continue
        void_at = _reached_void_at(reached_type, primary_resets, secondary_resets)
        if void_at is None or now_epoch < void_at:
            return UNAVAILABLE_RATE_LIMIT_REACHED
    if snap.get("state") == STATE_FRESH:
        primary = snap.get("primary_used_percent")
        weekly = snap.get("secondary_used_percent")
        if (primary is not None and primary >= EXHAUSTED_PERCENT) or (
                weekly is not None and weekly >= EXHAUSTED_PERCENT):
            return UNAVAILABLE_QUOTA_EXHAUSTED
    return None


def _window_for(snap: Dict[str, Any], limits: _LimitStates, token: Optional[str],
                now_epoch: float) -> Tuple[Optional[str], Optional[float]]:
    """(binding_window, resets_at) for an unavailable() token (#322), or (None, None).

    quota_exhausted: the window(s) at EXHAUSTED_PERCENT or more on the fresh reading; when both
    are, the one that resets LATER binds (codex stays refused until it does). rate_limit_reached:
    the limit whose set rate_limit_reached_type made the token, its window named by the type
    ("primary" / "secondary"), else the window whose reset is its void time (_reached_void_at).
    A window with no resets_at is (name, None): the reset time is unknown."""
    if token == UNAVAILABLE_QUOTA_EXHAUSTED:
        hits = []
        for name, used_key, resets_key in ((BINDING_PRIMARY, "primary_used_percent", "primary_resets_at"),
                                           (BINDING_SECONDARY, "secondary_used_percent", "secondary_resets_at")):
            used = snap.get(used_key)
            if used is not None and used >= EXHAUSTED_PERCENT:
                hits.append((name, _finite_number(snap.get(resets_key))))
        if not hits:
            return None, None
        known = [h for h in hits if h[1] is not None]
        return max(known, key=lambda h: h[1]) if known else hits[0]
    if token == UNAVAILABLE_RATE_LIMIT_REACHED:
        for observed, reached_type, primary_resets, secondary_resets in limits.values():
            age = now_epoch - observed
            if not (-FUTURE_SKEW_S <= age <= FRESH_WINDOW_S) or not _reached_type_set(reached_type):
                continue
            void_at = _reached_void_at(reached_type, primary_resets, secondary_resets)
            if void_at is not None and now_epoch >= void_at:
                continue
            if reached_type == BINDING_PRIMARY:
                return BINDING_PRIMARY, primary_resets
            if reached_type == BINDING_SECONDARY:
                return BINDING_SECONDARY, secondary_resets
            if void_at is None:
                return None, None
            return (BINDING_PRIMARY if void_at == primary_resets else BINDING_SECONDARY), void_at
    return None, None


def wait_advice_for(resets_in_s: Optional[int]) -> str:
    """`wait` when the reset is at most WAIT_ADVICE_MAX_S away (inclusive), else `notify` (#322).
    An unknown reset time is `notify`: nobody can promise the wait is short."""
    if resets_in_s is not None and resets_in_s <= WAIT_ADVICE_MAX_S:
        return WAIT_ADVICE_WAIT
    return WAIT_ADVICE_NOTIFY


def reset_advice(snap: Dict[str, Any], limits: _LimitStates, token: Optional[str],
                 now_epoch: float) -> Dict[str, Any]:
    """The #322 reset fields for a quota refusal: {binding_window, resets_at, resets_in_s, wait_advice}.

    resets_at is an epoch (int), resets_in_s the whole seconds until it (never negative); both are
    None when the reading names no reset time, and wait_advice is then `notify`."""
    window, resets_at = _window_for(snap, limits, token, now_epoch)
    resets_in: Optional[int] = None
    if resets_at is not None:
        resets_in = max(0, int(math.ceil(resets_at - now_epoch)))
        resets_at = int(math.ceil(resets_at))
    return {"binding_window": window, "resets_at": resets_at, "resets_in_s": resets_in,
            "wait_advice": wait_advice_for(resets_in)}


def evidence_at_for(snap: Dict[str, Any], limits: _LimitStates, token: Optional[str],
                    now_epoch: float) -> Optional[float]:
    """WHEN the evidence behind a meter token was observed (#322 fix round 2, N1). quota_exhausted: the fresh
    reading's own time. rate_limit_reached: the observed time of the rate_limits OBJECT whose set
    rate_limit_reached_type made the token (the newest such, when several) -- not the newest usable reading,
    which may be older and show headroom, and would then supersede the record at once. None: unknown."""
    if token == UNAVAILABLE_RATE_LIMIT_REACHED:
        times = []
        for observed, reached_type, primary_resets, secondary_resets in limits.values():
            age = now_epoch - observed
            if not (-FUTURE_SKEW_S <= age <= FRESH_WINDOW_S) or not _reached_type_set(reached_type):
                continue
            void_at = _reached_void_at(reached_type, primary_resets, secondary_resets)
            if void_at is None or now_epoch < void_at:
                times.append(observed)
        if times:
            return max(times)
    return _parse_timestamp(snap.get("observed_at"))


def unavailable(*, sessions_dir=None, now=None) -> Optional[str]:
    """Can astra run at all right now? "rate_limit_reached", "quota_exhausted" or None.

    Rules in the module docstring (ASTRA UNAVAILABLE). Bounded exactly like snapshot()
    (it is the same walk); never raises; no model call, socket or process. A stale,
    uncertain or unknown reading is None for the THRESHOLD half: only a fresh reading may
    yield quota_exhausted. An UNCERTAIN scan is None outright (#282 F5) — it may have missed
    the very rollout that clears the flag, so it may not stop a call. A stale or unknown scan
    still returns rate_limit_reached on a set rate_limit_reached_type from a file that WAS
    read, inside the age bound and before its void time: that is the best evidence there is.
    """
    try:
        now_epoch = _now_epoch(now)
        snap, limits = _scan(sessions_dir, now_epoch)
        return _unavailable_from(snap, limits, now_epoch)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# #322 fix round 1 (F1): the persisted exhausted-until record
# --------------------------------------------------------------------------- #
#: codex's usage-limit text names the reset as a LOCAL wall-clock time: "... or try again at 1:50 AM."
#: (observed 2026-09-28 on codex 0.154.0, in the task_complete error of a probe's rollout and on stderr).
#: The dated form ("try again at Oct 3rd, 2026 2:15 PM" / "on Oct 3rd 2:15 PM") is UNOBSERVED and parsed
#: best-effort; anything else yields None (the hold then applies).
_RETRY_AT = re.compile(
    r"\btry again (?:at|on)[ \t]+"
    r"(?:(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[ \t]+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?"
    r"(?:[ \t]+(?P<year>\d{4}))?,?[ \t]+(?:at[ \t]+)?)?"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})[ \t]*(?P<ampm>[ap]\.?m\.?)?",
    re.IGNORECASE)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


#: #322 fix round 2 (N2): the furthest reset codex's text may name -- the weekly window. A parsed target further
#: ahead is a misparse, never a hold of weeks. User-scoped round (item 6): exactly seven days (fix round 2 added
#: an hour).
RETRY_AT_MAX_AHEAD_S = 7 * 24 * 3600
#: #322 fix round 2 (N2): a time-of-day that passed LESS than this long ago was read late (the reset has just
#: happened), not tomorrow's: None, so the 30-minute hold and the probe decide.
RETRY_AT_LATE_READ_S = 12 * 3600


def retry_at_from_text(text: Any, now=None) -> Optional[int]:
    """The reset epoch named by codex's usage-limit text ("try again at 1:50 AM"), or None. Pure but for
    the host's local timezone.

    #322 fix round 2 (N2): a time-of-day with no date is today's when it is still ahead (60 s of slack),
    None when it passed less than RETRY_AT_LATE_READ_S ago (the text was read late: fix round 1 made that a
    +24 h hold), and tomorrow's otherwise. A DATED form ("Oct 3rd, 2026 2:15 PM") that is already in the past
    is None -- no roll to next year (fix round 1: +365 days). Any target more than RETRY_AT_MAX_AHEAD_S ahead
    is None. None falls back to the meter's reset time or to the EXHAUSTED_UNKNOWN_HOLD_S hold."""
    match = _RETRY_AT.search(_as_text(text))
    if match is None:
        return None
    try:
        now_epoch = _now_epoch(now)
        hour, minute = int(match.group("hour")), int(match.group("minute"))
        ampm = (match.group("ampm") or "").lower().replace(".", "")
        if ampm:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if ampm == "pm" else 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        local_now = datetime.fromtimestamp(now_epoch).astimezone()
        if match.group("mon"):
            month = _MONTHS.index(match.group("mon").lower()[:3]) + 1
            year = int(match.group("year")) if match.group("year") else local_now.year
            target = local_now.replace(year=year, month=month, day=int(match.group("day")), hour=hour,
                                       minute=minute, second=0, microsecond=0)
            if target.timestamp() < now_epoch - 60:
                return None
        else:
            target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target.timestamp() < now_epoch - 60:
                if now_epoch - target.timestamp() < RETRY_AT_LATE_READ_S:
                    return None
                target = target + timedelta(days=1)
        if target.timestamp() - now_epoch > RETRY_AT_MAX_AHEAD_S:
            return None
        return int(math.ceil(target.timestamp()))
    except (ValueError, OverflowError, OSError):
        return None


def exhausted_path_for() -> Path:
    """~/.claude/state/codex-exhausted.json, from Path.home() at CALL time (tests redirect HOME)."""
    return Path.home() / ".claude" / "state" / EXHAUSTED_FILENAME


def read_exhausted(*, path=None) -> Optional[Dict[str, Any]]:
    """The exhausted-until record, or None when there is none or it is unreadable. Never raises."""
    target = Path(path) if path is not None else exhausted_path_for()
    try:
        with open(target, "r", encoding="utf-8") as fh:
            record = json.loads(fh.read(64 * 1024))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    until = _finite_number(record.get("exhausted_until"))
    recorded = _finite_number(record.get("recorded_at"))
    if until is None or recorded is None:
        return None
    window = record.get("binding_window")
    evidence = _finite_number(record.get("evidence_at"))
    evidence = recorded if evidence is None else evidence
    wave_until = _finite_number(record.get("wave_until"))
    wave_evidence = _finite_number(record.get("wave_evidence_at"))
    reset_known = record.get("reset_known") is not False
    if wave_until is None or wave_evidence is None:  # a fix-round-1 record: its wave is itself
        wave_until, wave_evidence = until, evidence
    wave_known = record.get("wave_reset_known")
    if not isinstance(wave_known, bool):  # a record from before the user-scoped round
        wave_known = reset_known and wave_until == until
    return {"exhausted_until": until, "recorded_at": recorded, "evidence_at": evidence,
            "binding_window": window if window in (BINDING_PRIMARY, BINDING_SECONDARY) else None,
            "reset_known": reset_known, "source": record.get("source"),
            "wave_until": wave_until, "wave_evidence_at": wave_evidence, "wave_reset_known": wave_known}


def record_wave(record: Optional[Dict[str, Any]]) -> Optional[List[float]]:
    """#322 fix round 2 (items 5, 10): the record's WAVE -- [exhausted_until, evidence_at] as the record was
    OPENED (no active record before it). Updates to an active record keep it, so a probe that re-confirms the
    exhaustion does not start a new wave; a record opened after the last one expired or was retired does.
    None for no record."""
    if record is None:
        return None
    return [float(record["wave_until"]), float(record["wave_evidence_at"])]


def _atomic_json(target: Path, payload: Dict[str, Any]) -> None:
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def record_exhausted(resets_at, *, source, binding_window=None, now=None, path=None,
                     evidence_at=None) -> Dict[str, Any]:
    """Persist "codex is exhausted until resets_at" (#322 fix round 1, F1). `evidence_at` is WHEN the
    evidence was observed (a meter reading's timestamp; default `now`): only a reading observed at or after
    it can supersede the record. Returns the record written, or
    {"written": False, "error": ...}; never raises for an environment fault. A known resets_at replaces the
    record's time (the newest evidence names the reset); an unknown one (None) keeps a still-active known
    time and otherwise holds for EXHAUSTED_UNKNOWN_HOLD_S. A resets_at already in the past records nothing.
    Raises ValueError for an unknown `source` (a caller bug)."""
    if source not in EXHAUSTED_SOURCES:
        raise ValueError(f"unknown exhausted source {source!r}; expected one of {sorted(EXHAUSTED_SOURCES)}")
    now_epoch = _now_epoch(now)
    target = Path(path) if path is not None else exhausted_path_for()
    reset = _finite_number(resets_at)
    if reset is not None and reset <= now_epoch:
        return {"written": False, "error": None, "reason": "reset_in_the_past"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(target.with_name(target.name + ".lock"), timeout=LOCK_TIMEOUT_S):
            current = read_exhausted(path=target)
            active = current is not None and current["exhausted_until"] > now_epoch
            if reset is not None:
                until, known, window = reset, True, binding_window
            elif active and current["reset_known"]:
                until, known = current["exhausted_until"], True
                window = binding_window or current["binding_window"]
            else:
                until, known, window = now_epoch + EXHAUSTED_UNKNOWN_HOLD_S, False, binding_window
            evidence = _finite_number(evidence_at)
            evidence = now_epoch if evidence is None else evidence
            until = int(math.ceil(until))
            # User-scoped round (item 7, Opus N1): a KNOWN reset that names a different reset window than the
            # wave's own known `until` (more than AWAIT_MARGIN_S apart) is a NEW exhaustion -- codex was reset
            # unseen and used up again -- so it opens a new wave (its own notification and full wait) instead
            # of inheriting the old, possibly timed-out, one. A wave opened on the unknown-reset hold has no
            # reset window to differ from: learning the real time keeps it.
            new_window = (active and reset is not None and current["wave_reset_known"]
                          and abs(until - current["wave_until"]) > AWAIT_MARGIN_S)
            if active:
                # #322 fix round 2: the SAME exhaustion, re-confirmed. The evidence never moves back (a newer
                # signal already on disk stays the bar a reading must clear), and the wave stays the one the
                # record was opened with (one notification and one full wait per wave).
                evidence = max(evidence, current["evidence_at"])
            if active and not new_window:
                wave_until, wave_evidence = current["wave_until"], current["wave_evidence_at"]
                wave_known = current["wave_reset_known"]
            else:
                wave_until, wave_evidence, wave_known = until, evidence, known
            record = {"exhausted_until": until, "recorded_at": now_epoch, "evidence_at": evidence,
                      "binding_window": window, "reset_known": known, "source": source,
                      "wave_until": wave_until, "wave_evidence_at": wave_evidence,
                      "wave_reset_known": wave_known}
            _atomic_json(target, record)
        return dict(record, written=True)
    except Exception as exc:  # noqa: BLE001 - a store fault never raises into a seat
        return {"written": False, "error": f"{type(exc).__name__}: {exc}"}


def _state_dir(exhausted_path=None) -> Path:
    """The account-wide state directory: the exhausted record's own (~/.claude/state by default)."""
    return (Path(exhausted_path) if exhausted_path is not None else exhausted_path_for()).parent


def _drop_wave_files(state_dir: Path) -> None:
    """The notification claim and the timed-out marker belong to the record's wave: gone with it."""
    for name in (NOTIFY_WAVE_FILENAME, AWAIT_TIMEOUT_FILENAME):
        try:
            (state_dir / name).unlink()
        except OSError:
            pass


def retire_exhausted(observed_at, *, path=None) -> bool:
    """#322 fix round 2 (item 1): remove the exhausted-until record because codex was seen with headroom at
    `observed_at` (epoch). Under the record's lock it is re-read, and a record whose evidence is NEWER than
    `observed_at` -- a concurrent exhaustion signal written after that reading -- is KEPT. Retiring also drops
    the wave's notification claim and timed-out marker. True when no superseded record remains; never
    raises."""
    observed = _finite_number(observed_at)
    if observed is None:
        return False
    target = Path(path) if path is not None else exhausted_path_for()
    try:
        with file_lock(target.with_name(target.name + ".lock"), timeout=LOCK_TIMEOUT_S):
            current = read_exhausted(path=target)
            # Whole seconds: a snapshot's observed_at is second-resolution (_iso_z), the evidence is not.
            if current is not None and math.floor(current["evidence_at"]) > math.floor(observed):
                return False
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            _drop_wave_files(target.parent)
        return True
    except Exception:  # noqa: BLE001
        return False


def clear_exhausted(*, path=None) -> bool:
    """Remove the exhausted-until record unconditionally (and its wave files). Never raises."""
    target = Path(path) if path is not None else exhausted_path_for()
    try:
        with file_lock(target.with_name(target.name + ".lock"), timeout=LOCK_TIMEOUT_S):
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            _drop_wave_files(target.parent)
        return True
    except Exception:  # noqa: BLE001
        return False


def _reading_headroom_since(snap: Dict[str, Any], since: float, window: Optional[str] = None) -> Optional[bool]:
    """Does the snapshot's reading show headroom, observed at or after `since`? (#322 fix round 2, item 2.)

    False: observed then, and a window it READS is at or over EXHAUSTED_PERCENT. True: observed then, and the
    binding `window` has an EXPLICIT reading below it -- `primary`: the primary; `secondary`: the weekly;
    None (unknown): both. None: no reading that new, or the window that matters is missing from it -- a
    reading with no weekly value is no evidence about a weekly exhaustion (fix round 1 read it as headroom)."""
    observed = _parse_timestamp(snap.get("observed_at"))
    # Whole seconds: the snapshot's observed_at is second-resolution (_iso_z); the evidence time may carry a
    # fraction (fix round 2, N1, takes it from the rate_limits object itself).
    if observed is None or math.floor(observed) < math.floor(since):
        return None
    primary = snap.get("primary_used_percent")
    weekly = snap.get("secondary_used_percent")
    if any(v is not None and v >= EXHAUSTED_PERCENT for v in (primary, weekly)):
        return False
    needed = {BINDING_PRIMARY: (primary,), BINDING_SECONDARY: (weekly,)}.get(window, (primary, weekly))
    if any(v is None for v in needed):
        return None
    return True


#: User-scoped round (item 1): how many times active_exhausted() re-reads the record after a REFUSED retirement.
ACTIVE_EXHAUSTED_REREADS = 2


def active_exhausted(snap: Dict[str, Any], now_epoch: float, *, path=None, retire=True) -> Optional[Dict[str, Any]]:
    """The exhausted-until record while it binds: before its time AND not superseded by a reading observed
    at or after its evidence that shows headroom on its binding window (explicitly). Else None. Never raises.

    #322 fix round 2 (item 1): a SUPERSEDED record is retired (retire_exhausted, under its lock, keeping a
    concurrent newer signal) -- left on disk it bound again once the headroom reading aged out or left the
    walk. `retire=False` (a check-only admit) reads without writing."""
    for _attempt in range(ACTIVE_EXHAUSTED_REREADS + 1):
        record = read_exhausted(path=path)
        if record is None or record["exhausted_until"] <= now_epoch:
            return None
        if _reading_headroom_since(snap, record["evidence_at"], record["binding_window"]) is not True:
            return record
        if not retire or retire_exhausted(_parse_timestamp(snap.get("observed_at")), path=path):
            return None
        # User-scoped round (item 1): the retirement was REFUSED -- a newer exhaustion signal landed between
        # the read above and the retire's own locked re-read (or the store could not be locked). Admitting
        # now would ignore that signal: re-read the record and judge the CURRENT one.
    # Still refused after the re-reads: something newer keeps landing (or the store cannot be locked).
    # Fail closed: a record still on disk and before its time binds (#322 final verification, codex item 1).
    record = read_exhausted(path=path)
    if record is None or record["exhausted_until"] <= now_epoch:
        return None
    return record


def _advice_from_record(record: Dict[str, Any], now_epoch: float) -> Dict[str, Any]:
    """reset_advice()'s four fields from an exhausted-until record (a held, unknown time is `notify`)."""
    if not record.get("reset_known", True):
        return {"binding_window": record.get("binding_window"), "resets_at": None, "resets_in_s": None,
                "wait_advice": WAIT_ADVICE_NOTIFY}
    until = record["exhausted_until"]
    resets_in = max(0, int(math.ceil(until - now_epoch)))
    return {"binding_window": record.get("binding_window"), "resets_at": int(math.ceil(until)),
            "resets_in_s": resets_in, "wait_advice": wait_advice_for(resets_in)}


def _quota_state(snap: Dict[str, Any], limits: _LimitStates, now_epoch: float, *,
                 exhausted_path=None, retire=True) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """(token, where it came from: "meter" | "exhausted_record" | None, reset advice or None).

    The meter's unavailable() token first; without one, an active exhausted-until record is
    quota_exhausted. A meter token whose reading names no reset time borrows a known one from the record."""
    token = _unavailable_from(snap, limits, now_epoch)
    if token is not None:
        advice = reset_advice(snap, limits, token, now_epoch)
        if advice["resets_at"] is None:
            record = active_exhausted(snap, now_epoch, path=exhausted_path, retire=retire)
            if record is not None and record.get("reset_known", True):
                advice = _advice_from_record(record, now_epoch)
        return token, "meter", advice
    record = active_exhausted(snap, now_epoch, path=exhausted_path, retire=retire)
    if record is not None:
        return UNAVAILABLE_QUOTA_EXHAUSTED, "exhausted_record", _advice_from_record(record, now_epoch)
    return None, None, None


def quota_wait_now(*, sessions_dir=None, now=None, exhausted_path=None) -> Optional[Dict[str, Any]]:
    """Is codex out of quota right now, and when does it come back? {unavailable, unavailable_source,
    binding_window, resets_at, resets_in_s, wait_advice} or None. Reads the meter and the exhausted-until
    record; writes nothing but the retirement of a SUPERSEDED record (fix round 2, item 1); never raises. The
    avengers pre-spend review reads it (#322 fix round 1)."""
    try:
        now_epoch = _now_epoch(now)
        snap, limits = _scan(sessions_dir, now_epoch)
        token, where, advice = _quota_state(snap, limits, now_epoch, exhausted_path=exhausted_path)
    except Exception:  # noqa: BLE001
        return None
    if token is None:
        return None
    return dict(advice, unavailable=token, unavailable_source=where)


# --------------------------------------------------------------------------- #
# admit()
# --------------------------------------------------------------------------- #
def is_admission_id(value: Any) -> bool:
    """True for an admission id (#282 r10): a str of exactly 32 lowercase ASCII hex characters."""
    return isinstance(value, str) and ADMISSION_ID_PATTERN.fullmatch(value) is not None


def _count_admitted(path: Path, key: str, use: Optional[str], task_key: Optional[str], *,
                    model_class: Optional[str] = None, also_netted: Optional[str] = None) -> int:
    """Admitted rows for (key, use[, task_key][, model_class]); `use=None` counts every use
    and `model_class=None` every class. Rows without `admitted: true` (refusals, substitution
    rows, skip rows) are never counted.

    D16: the class is part of the count, so a complex call and a light/medium call on the
    SAME key do not spend each other's budget. A row written before D16 carries no class and
    counts as TOP (_row_model_class), which is what it was.

    #282 r10 CORRELATION: an admitted row whose admission_id is named by a substitution row
    anywhere in the store (or equals `also_netted`, the admission a substitution row about to
    be written replaces) is netted out. Rows without an admission id count as before."""
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    counted: List[Optional[str]] = []
    netted = {also_netted} if is_admission_id(also_netted) else set()
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("kind") == ROW_KIND_SUBSTITUTION and is_admission_id(row.get("admission_id")):
                netted.add(row["admission_id"])
            if row.get("admitted") is not True:
                continue
            if _row_key(row) != key:
                continue
            if use is not None and row.get("use") != use:
                continue
            if model_class is not None and _row_model_class(row) != model_class:
                continue
            if use in TASK_KEY_USES and row.get("task_key") != task_key:
                continue
            admission_id = row.get("admission_id")
            counted.append(admission_id if is_admission_id(admission_id) else None)
    return sum(1 for admission_id in counted if admission_id is None or admission_id not in netted)


def _append_row(path: Path, row: Dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass


def _threshold_tripped(snap: Dict[str, Any], now_epoch: float) -> bool:
    """Is the reading at THRESHOLD_PERCENT or more? INFORMATIONAL since #322: tripwire() reports it
    as `threshold_tripped` and nothing refuses on it (it was the 70% trip-wire for the budgeted uses).

    fresh: either arm >= THRESHOLD_PERCENT. stale with reason exactly observed_too_long_ago
    (#282 r9, a LOWER BOUND): primary >= THRESHOLD_PERCENT while primary_resets_at > now, or
    weekly >= THRESHOLD_PERCENT while secondary_resets_at > now. Every other state never."""
    primary = snap["primary_used_percent"]
    weekly = snap["secondary_used_percent"]
    if snap["state"] == STATE_FRESH:
        return (primary is not None and primary >= THRESHOLD_PERCENT) or (
            weekly is not None and weekly >= THRESHOLD_PERCENT)
    if snap["state"] != STATE_STALE or snap.get("reason") != REASON_OBSERVED_TOO_LONG_AGO:
        return False
    primary_resets = snap["primary_resets_at"]
    weekly_resets = snap["secondary_resets_at"]
    primary_live = (primary is not None and primary >= THRESHOLD_PERCENT
                    and primary_resets is not None and primary_resets > now_epoch)
    weekly_live = (weekly is not None and weekly >= THRESHOLD_PERCENT
                   and weekly_resets is not None and weekly_resets > now_epoch)
    return primary_live or weekly_live


def _trial_verdict(snap: Dict[str, Any]) -> Tuple[bool, str]:
    if snap["state"] != STATE_FRESH:
        return False, "trial_requires_fresh_snapshot"
    primary = snap["primary_used_percent"]
    weekly = snap["secondary_used_percent"]
    if primary is None or weekly is None or primary >= TRIAL_CEILING_PERCENT \
            or weekly >= TRIAL_CEILING_PERCENT:
        return False, "trial_threshold"
    return True, "within_trial_ceiling"


def _cycle_provenance(project_root, cycle_id: str, now_epoch: float) -> Dict[str, Any]:
    """{cycle_id_source, cycle_id_file_age_s} for a row (J3 (2)): derived from the project
    when the passed id IS its key, otherwise "explicit" with a null age (never guessed).

    D14 keys (`review-<uuid>`, `ballot-<uuid>`, `tournament-<uuid>`, an avengers session id)
    are minted by their caller, so they are "explicit" here — correctly: they did not come
    from `.forge/cycle-id` and have no file age to report."""
    derived_id, derived_source, derived_age = cycle_id_and_source(project_root, now=now_epoch)
    if derived_id == cycle_id:
        return {"cycle_id_source": derived_source, "cycle_id_file_age_s": derived_age}
    return {"cycle_id_source": SOURCE_EXPLICIT, "cycle_id_file_age_s": None}


def _fallback_for(use: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(fallback, fallback_error) for an admit decision (J8). Never raises."""
    role = USE_FALLBACK_ROLE.get(use)
    if role is None:  # trial: skipped, never substituted
        return None, None
    fallback: Dict[str, Any] = {"provider": FALLBACK_PROVIDER, "role": role, "model": None}
    try:
        # LAZY on purpose: seat_model imports this module at load, so an eager import
        # would be circular. seat_model resolves a Claude seat from its role table alone
        # (no roster, pins, env or file), so this adds no input to the decision.
        import seat_model  # noqa: E402

        model = seat_model.resolve(role, FALLBACK_PROVIDER).model
        if not _is_claude_model_word(model):
            raise ValueError(f"resolved fallback model {model!r} is not a plain Claude model word")
        fallback["model"] = model
        return fallback, None
    except Exception as exc:  # noqa: BLE001 — the decision must survive a broken resolver
        return fallback, f"{type(exc).__name__}: {exc}"


def _is_claude_model_word(model: Any) -> bool:
    """A plain word of bounded length that is not a codex (gpt-) model."""
    return (isinstance(model, str) and _MODEL_WORD.fullmatch(model) is not None
            and not model.lower().startswith("gpt-"))


def _checked_size(size: Any, size_source: Any) -> Tuple[str, str]:
    """(size, size_source) for a row — design §2.1: EVERY row records both, unconditionally.

    Neither given: L7 rule 6, the back-compat default (complex / "default"), so a row from an
    un-migrated call site is never read as a refused light call and the 2026-09-28 review
    never meets a hole it has to guess at. One without the other is a CALLER BUG: this module
    does not resolve a size (that is seat_model's job, L7) and so cannot invent the missing
    half — guessing `routing` for an unsourced size would fabricate provenance.
    """
    if size is None and size_source is None:
        return DEFAULT_SIZE, DEFAULT_SIZE_SOURCE
    if size is None or size_source is None:
        raise ValueError("size and size_source travel together: pass both or neither "
                         f"(got size={size!r}, size_source={size_source!r})")
    if not isinstance(size, str) or size not in SIZES:
        raise ValueError(f"size must be one of {', '.join(SIZES)}, got {size!r}")
    if not isinstance(size_source, str) or size_source not in SIZE_SOURCES:
        raise ValueError(f"size_source must be one of {', '.join(sorted(SIZE_SOURCES))}, "
                         f"got {size_source!r}")
    return size, size_source


def _checked_model_class(model_class: Any) -> str:
    """The class this call's model belongs to. None is the BACK-COMPAT default: before D16
    every budgeted codex call was astra, so an un-classed caller is a TOP call."""
    if model_class is None:
        return MODEL_CLASS_TOP
    if model_class not in MODEL_CLASSES:
        raise ValueError(f"model_class must be one of {sorted(MODEL_CLASSES)}, got {model_class!r}")
    return str(model_class)


def _checked_requested_by(requested_by: Any) -> Optional[str]:
    if requested_by is not None and requested_by != REQUESTED_BY_USER:
        raise ValueError(f"requested_by must be {REQUESTED_BY_USER!r} or None, got {requested_by!r}")
    return requested_by


def _checked_role(role: Any) -> Optional[str]:
    """The seat this call is for. None is the back-compat default: a call site that has
    not been given a role records none, exactly as it did before, and every reader
    tolerates the absence (the row simply does not carry the key)."""
    if role is not None and role not in ADMIT_ROLES:
        raise ValueError(f"role {role!r} has no codex seat; expected one of {sorted(ADMIT_ROLES)}")
    return role


def _checked_requested_model(requested_model: Any) -> Optional[str]:
    if requested_model is not None and (not isinstance(requested_model, str)
                                        or _MODEL_WORD.fullmatch(requested_model) is None):
        raise ValueError(f"requested_model {requested_model!r} must be a plain word or None")
    return requested_model


def _checked_models(models: Any, requested_model: Optional[str]) -> Optional[List[str]]:
    """#302 (design §3.5): EVERY seat model a shared admission covers. None is the back-compat
    default (no key written). Otherwise a non-empty list of distinct plain model words; when the
    caller also names `requested_model` it must be one of them (the row cannot name a model its
    own list omits)."""
    if models is None:
        return None
    if not isinstance(models, (list, tuple)) or not models:
        raise ValueError(f"models must be a non-empty list of model words or None, got {models!r}")
    checked = [_checked_requested_model(model) for model in models]
    if any(model is None for model in checked):
        raise ValueError(f"models {models!r} must hold plain model words only")
    if len(set(checked)) != len(checked):
        raise ValueError(f"models {models!r} must not repeat a model")
    if requested_model is not None and requested_model not in checked:
        raise ValueError(f"requested_model {requested_model!r} is not in models {checked!r}")
    return list(checked)


def _checked_roles(roles: Any) -> Optional[List[str]]:
    """#302: the seat roles a shared admission covers, each from ADMIT_ROLES (a role may repeat:
    two seats can share one role). None writes no key."""
    if roles is None:
        return None
    if not isinstance(roles, (list, tuple)) or not roles:
        raise ValueError(f"roles must be a non-empty list of roles or None, got {roles!r}")
    for role in roles:
        if role not in ADMIT_ROLES:
            raise ValueError(f"role {role!r} has no codex seat; expected one of {sorted(ADMIT_ROLES)}")
    return list(roles)


def _row_key(row: Dict[str, Any]) -> Any:
    """A row's budget key. New rows carry `key`; rows written before D16 carry only
    `cycle_id`, and reading BOTH is what lets the 15 live rows keep counting."""
    value = row.get("key")
    return value if isinstance(value, str) else row.get("cycle_id")


def _row_model_class(row: Dict[str, Any]) -> str:
    """A row's model class. Absent (or unrecognised) means a row written before D16, when
    every budgeted call was astra: it counts against the TOP budget."""
    value = row.get("model_class")
    return str(value) if value in MODEL_CLASSES else MODEL_CLASS_TOP


def admit(use, key, *, project_root, size=None, size_source=None, model_class=None,
          requested_model=None, requested_by=None, role=None, now=None, sessions_dir=None,
          budget_path=None, task_key=None, record=True, models=None, roles=None,
          exhausted_path=None) -> Dict[str, Any]:
    """Decide one intended codex call and record the decision (admitted OR refused).

    #322 fix round 1 (F2, F1). ORDER: the use's class and budget are decided FIRST (a "-" cell is
    class_not_budgeted, a spent budget budget_spent) and only a seat that would otherwise be admitted is
    refused for QUOTA and carries the reset fields -- a seat that can never run is never told to wait for a
    reset. The quota token is the meter's unavailable() token or, without one, an active exhausted-until
    record (read_exhausted / `exhausted_path`, default ~/.claude/state/codex-exhausted.json); the decision
    says which in `unavailable_source`. A RECORDED decision whose meter shows exhaustion also persists the
    record (record_exhausted, source "admit"), so a reading that goes stale or is pushed out of the walk
    keeps refusing until the reset.

    D16: the limit comes from BUDGET_LIMITS[use][model_class], so a complex call and a
    light/medium call on the SAME key count SEPARATELY. `key` is that use's budget key
    (design §2.2: a forge cycle id, `review-<uuid>`, `ballot-<uuid>`, `tournament-<uuid>`, an
    avengers session id, a diagnosis task key's cycle). A class the table does not budget for
    that use is REFUSED `class_not_budgeted`, never admitted unbudgeted.

    Design §2.1: the row and the decision record `size` and `size_source` UNCONDITIONALLY —
    an un-migrated caller records the back-compat default (complex / "default"), never a hole
    — plus `requested_by: "user"` for a `--user-request` call. This module RECORDS a size; it
    never resolves one (L7 lives in seat_model).

    #282 r15: `record=False` is CHECK-ONLY (module docstring, THE BUDGET STORE): the same
    decision and keys, but no row, no store / directory / .lock created, the budget read
    without the lock, `admission_id` None and `recorded` False. The default still records
    (seat_model, audit_spawn); the CLI `admit` is the one caller that checks by default.

    Raises ValueError only for a caller bug (unknown use, empty key, a task_key on a use
    other than diagnosis, a size without its source, an unknown size / size_source /
    model_class / requested_by / requested_model, a malformed `now`). Environment failures
    never raise, and a caller bug is raised BEFORE anything is written.

    When `project_root` is given, the row and the decision also carry `cycle_id_source`
    and `cycle_id_file_age_s` (J3 (2)): taken from cycle_id_and_source(project_root) when
    the passed cycle_id equals that derived key, otherwise "explicit" with a null age
    (never guessed). Without a project_root both keys are omitted.

    unavailable() is consulted first (J7): its token refuses every use but audit, and
    when set the row and the decision carry `unavailable`. Every decision carries
    `fallback` (null for trial) and, when the fallback model could not be resolved,
    `fallback_error` (J8). Budget rows never carry the fallback.

    #282 r10: the row and the decision carry one fresh `admission_id` (uuid4 hex), refusals
    and an unwritten row included; a substitution that replaces this admission names it.
    A check-only decision has no row to name, so its id is None.

    L18 / WP-A5: `role` names the SEAT the call is for, so the budget row says which seat
    it was. It matters because the row records what was SPENT, not what was asked for: a
    TOP seat frozen to sol is billed `std` (correct — the budget rations real spend), and
    `requested_model` holds the RESOLVED model, so without a role an `arbiter` frozen to
    sol is indistinguishable from an ordinary `consultant_support` std-class call. A sized role
    exposes the freeze through `size` + `model_class` already; the unsized seats cannot.
    Optional and ADDITIVE: a caller that names none writes no key, and an unknown role is
    a caller bug (ValueError) like every other vocabulary.

    #302 (design §3.5): `models` / `roles` name EVERY seat model and role ONE admission covers.
    avengers admits once per model class per session, and from roster rev 3 a single std
    admission can cover a sized std main seat and a supporting seat on the support tier — two
    different models. Both lists are OPTIONAL and ADDITIVE (no key written when absent), so a
    row without them loads and counts exactly as before. They change NOTHING about the decision:
    MODEL_CLASSES, BUDGET_LIMITS and the count are per class, so a row naming two models still
    spends one slot. A malformed list, or a `requested_model` missing from `models`, is a caller
    bug (ValueError).
    """
    if use not in USES:
        raise ValueError(f"unknown use {use!r}; expected one of {sorted(USES)}")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key must be a non-empty string")
    if task_key is not None:
        if use not in TASK_KEY_USES:
            raise ValueError(f"task_key applies to uses {sorted(TASK_KEY_USES)} only")
        if not isinstance(task_key, str) or not task_key.strip():
            raise ValueError("task_key must be a non-empty string when given")
    elif use == "exhausted_review":
        # U3/F5: one review per review id, so the key is REQUIRED - without it every loop would share one slot.
        raise ValueError("use 'exhausted_review' needs task_key: the D21 review id it is keyed on")
    size, size_source = _checked_size(size, size_source)
    model_class = _checked_model_class(model_class)
    requested_by = _checked_requested_by(requested_by)
    requested_model = _checked_requested_model(requested_model)
    role = _checked_role(role)
    models = _checked_models(models, requested_model)
    roles = _checked_roles(roles)
    if budget_path is None and project_root is None:
        raise ValueError("project_root is required unless budget_path is given")
    now_epoch = _now_epoch(now)
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    provenance: Optional[Dict[str, Any]] = None
    if project_root is not None:
        provenance = _cycle_provenance(project_root, key, now_epoch)
    recorded = bool(record)
    admission_id: Optional[str] = uuid.uuid4().hex if recorded else None

    snap, limits = _scan(sessions_dir, now_epoch)
    unavailable_token, unavailable_source, quota_advice = _quota_state(snap, limits, now_epoch,
                                                                       exhausted_path=exhausted_path,
                                                                       retire=recorded)
    use_limits = BUDGET_LIMITS.get(use)
    limit = None if use_limits is None else use_limits.get(model_class)
    needs_budget = False
    if use == "audit":
        admitted, reason = True, "audit_exempt"
    elif use == "trial":
        admitted, reason = (False, unavailable_token) if unavailable_token is not None else _trial_verdict(snap)
    # #322 (2026-09-27): no `threshold` refusal any more. A seat is refused for quota ONLY on real
    # exhaustion (the token above); a high reading runs, and a call that then hits the wall is
    # classified by classify_codex_failure(). The trial ceiling and the budget are unchanged.
    elif limit is None:
        # A "—" cell: this use has no budget for this class, so there is no slot to take.
        # Refused and RECORDED, never admitted unbudgeted (design §2.2). #322 fix round 1 (F2): decided
        # BEFORE quota, so a seat that can never run is not sent to wait for a reset.
        admitted, reason = False, REASON_CLASS_NOT_BUDGETED
    else:
        admitted, reason, needs_budget = False, "budget_pending", True

    def _budget_verdict(count: int) -> Tuple[bool, str]:
        # #322 fix round 1 (F2): the budget first, then quota -- only a seat the budget would admit is
        # refused for quota (and so told when codex comes back).
        if count >= limit:
            return False, "budget_spent"
        if unavailable_token is not None:
            return False, unavailable_token
        return True, "within_budget"

    used: Optional[int] = None
    row_written = False
    error: Optional[str] = None
    try:
        if not recorded:
            # #282 r15 CHECK-ONLY: the same count, read WITHOUT the lock; nothing is created,
            # so a missing store counts zero and an unreadable one raises into the except below.
            if needs_budget:
                used = _count_admitted(path, key, use, task_key, model_class=model_class)
                admitted, reason = _budget_verdict(used)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
                if needs_budget:
                    used = _count_admitted(path, key, use, task_key, model_class=model_class)
                    admitted, reason = _budget_verdict(used)
                row = {
                    "at": _iso_z(now_epoch),
                    "key": key,
                    # RETAINED, not replaced: `key` is the design §2.2 name, `cycle_id` is what
                    # the 15 live rows and every existing reader use. Both carry the same value,
                    # so a new row is readable by an old reader and an old row by a new one.
                    "cycle_id": key,
                    "use": use,
                    "size": size,
                    "size_source": size_source,
                    "requested_model": requested_model,
                    "model_class": model_class,
                    "admitted": admitted,
                    "reason": reason,
                    "snapshot_state": snap["state"],
                    "primary": snap["primary_used_percent"],
                    "weekly": snap["secondary_used_percent"],
                    "admission_id": admission_id,
                }
                if role is not None:
                    row["role"] = role
                if models is not None:
                    row["models"] = list(models)
                if roles is not None:
                    row["roles"] = list(roles)
                if task_key is not None:
                    row["task_key"] = task_key
                if requested_by is not None:
                    row["requested_by"] = requested_by
                if provenance is not None:
                    row.update(provenance)
                if unavailable_token is not None:
                    row["unavailable"] = unavailable_token
                    row["unavailable_source"] = unavailable_source
                _append_row(path, row)
                row_written = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if use != "audit" and needs_budget and used is None and unavailable_token is not None:
            # #322 fix round 1: a budget that could not be counted cannot say budget_spent, but codex is
            # out of quota either way -- the quota refusal stands on its merits (and names its reset).
            admitted, reason = False, unavailable_token
        elif use != "audit" and (admitted or (needs_budget and used is None)):
            # A discretionary admission that cannot be recorded cannot be enforced, and a
            # budget that could not be counted cannot be checked. A refusal already
            # decided on its merits (a quota token, budget_spent, trial) stays as it is.
            admitted, reason = False, "budget_store_unavailable"

    decision: Dict[str, Any] = {
        "admitted": admitted,
        "use": use,
        "key": key,
        "cycle_id": key,
        "size": size,
        "size_source": size_source,
        "requested_model": requested_model,
        "model_class": model_class,
        "reason": reason,
        "snapshot_state": snap["state"],
        "primary": snap["primary_used_percent"],
        "weekly": snap["secondary_used_percent"],
        "budget_limit": limit,
        "budget_used": used,
        "row_written": row_written,
        "recorded": recorded,
        "budget_path": str(path),
        "admission_id": admission_id,
    }
    if role is not None:
        decision["role"] = role
    if models is not None:
        decision["models"] = list(models)
    if roles is not None:
        decision["roles"] = list(roles)
    if task_key is not None:
        decision["task_key"] = task_key
    if requested_by is not None:
        decision["requested_by"] = requested_by
    if provenance is not None:
        decision.update(provenance)
    if unavailable_token is not None:
        decision["unavailable"] = unavailable_token
        decision["unavailable_source"] = unavailable_source
        # #322: WHEN codex can serve again, and whether to wait for it or tell the user. Fix round 1 (F2):
        # only on a decision quota actually decided (a quota refusal, or an audit admitted onto an exhausted
        # meter) -- never on a budget_spent / class_not_budgeted / store refusal, which no reset can change.
        if reason in QUOTA_REFUSAL_REASONS or (use == "audit" and admitted):
            decision.update(quota_advice)
        if recorded and unavailable_source == "meter":
            # F1: persist it, so a stale or walked-out reading keeps refusing until the reset.
            written = record_exhausted(quota_advice.get("resets_at"), source="admit",
                                       binding_window=quota_advice.get("binding_window"), now=now_epoch,
                                       path=exhausted_path,
                                       evidence_at=evidence_at_for(snap, limits, unavailable_token,
                                                                   now_epoch) or now_epoch)
            decision["exhausted_recorded"] = bool(written.get("written"))
    fallback, fallback_error = _fallback_for(use)
    decision["fallback"] = fallback
    if fallback_error is not None:
        decision["fallback_error"] = fallback_error
    if error is not None:
        decision["error"] = error
    return decision


# --------------------------------------------------------------------------- #
# tripwire() — the D20 account-wide check EVERY codex call runs
# --------------------------------------------------------------------------- #
def tripwire(seat_class, *, sessions_dir=None, now=None, exhausted_path=None) -> Dict[str, Any]:
    """Can a codex call of this seat class run right now? (design §2.2, D20.)

    THE METER IS ACCOUNT-WIDE, so every codex call checks it — not only the budgeted ones.
    `consultant_support` seats (the codex support tier) and research lookups are trip-wire-checked but
    NOT budgeted, which is exactly what this function is for: it consults unavailable() and
    NOTHING else. #322 (2026-09-27): the 70% threshold no longer stops a seat; `threshold_tripped`
    is still reported, for display only.

    CHECK-ONLY, NO BUDGET: it reads the meter and writes nothing at all — no row, no budget
    store, no directory, no .lock, and it never counts or spends a slot. Recording a skip is
    record_skip()'s job, the way recording a substitution is record_substitution()'s.

    The verdict by seat class:
      audit          runs (`audit_exempt`, the same rule admit() gives it) and stops only on
                     REAL exhaustion — an unavailable() token, which is
                     a call that would fail, not a call that is merely expensive.
      discretionary  on real exhaustion it SUBSTITUTES: a fresh Claude main-tier agent on the same
                     brief (D6/D18).
      supporting     on real exhaustion it SKIPS, recorded. A support-tier seat is not substituted —
                     substituting it with a Claude agent would buy nothing the skip does not, and
                     substituting it with another gpt model would draw the same quota.

    #282 F5, INHERITED EXACTLY: unavailable() returns None for an UNCERTAIN snapshot, so an
    uncertain meter neither refuses
    nor silently passes — the call proceeds and the reading it proceeded on is reported in
    `snapshot_state` / `primary` / `weekly`, so the caller can see it was uncertain.

    #322 fix round 2 (item 4): the ACTIVE EXHAUSTED-UNTIL RECORD is real exhaustion too, exactly as admit()
    reads it (_quota_state): with a stale, reading-less or uncertain meter and an active record, a supporting
    seat SKIPS and a discretionary one substitutes -- fix round 1 consulted the meter alone and ran them.
    `unavailable_source` says which ("meter" | "exhausted_record"). The only write is the retirement of a
    record a newer reading has superseded (item 1).

    Raises ValueError only for a caller bug (an unknown seat_class, a malformed `now`).
    """
    if seat_class not in SEAT_CLASSES:
        raise ValueError(f"unknown seat_class {seat_class!r}; expected one of {sorted(SEAT_CLASSES)}")
    now_epoch = _now_epoch(now)
    snap, limits = _scan(sessions_dir, now_epoch)
    token, token_source, _advice = _quota_state(snap, limits, now_epoch, exhausted_path=exhausted_path)
    tripped = _threshold_tripped(snap, now_epoch)

    if seat_class == SEAT_CLASS_AUDIT:
        action = TRIPWIRE_SUBSTITUTE if token is not None else TRIPWIRE_RUN
        reason = token if token is not None else REASON_AUDIT_EXEMPT
    elif token is not None:
        # #322: only REAL exhaustion stops a seat. `tripped` (a reading >= THRESHOLD_PERCENT) is
        # still reported below, for display, and never changes the action.
        action = TRIPWIRE_SKIP if seat_class == SEAT_CLASS_SUPPORTING else TRIPWIRE_SUBSTITUTE
        reason = token
    else:
        action, reason = TRIPWIRE_RUN, REASON_BELOW_THRESHOLD

    return {
        "seat_class": seat_class,
        "action": action,
        "proceed": action == TRIPWIRE_RUN,
        "reason": reason,
        "unavailable": token,
        "unavailable_source": token_source,
        "threshold_tripped": tripped,
        "threshold_percent": THRESHOLD_PERCENT,
        "snapshot_state": snap["state"],
        "snapshot_reason": snap.get("reason"),
        "primary": snap["primary_used_percent"],
        "weekly": snap["secondary_used_percent"],
        "recorded": False,
    }


# --------------------------------------------------------------------------- #
# record_skip() — the RECORDED half of a supporting seat's trip-wire skip
# --------------------------------------------------------------------------- #
def record_skip(use, key, reason, *, project_root, role, seat_class, requested_model=None,
                size=None, size_source=None, requested_by=None, now=None, budget_path=None,
                sessions_dir=None) -> Dict[str, Any]:
    """Record that a codex seat was SKIPPED because the account-wide trip-wire was up (D20).

    Appends one `kind: "skip"` row under the same lock as admit(). The row has no `admitted`
    key, so a skip never spends a budget, and no `substitute_for` key, so it never inflates
    the substitution count the 2026-09-28 review reads. Returns the row plus `row_written`,
    `budget_path` and, on a store failure, `error` — a store failure never raises.

    `use` may be None: an ephemeral research call has no use in the budget table, and
    recording one would be inventing a fact. Design §2.1: the row records `size` and
    `size_source` unconditionally, defaulting to complex / "default" like every other row.

    Raises ValueError for a caller bug: seat_class `audit` (the VERIFIED-gate audit is
    substituted, never skipped), a use / role / reason / seat_class outside USES / SKIP_ROLES
    / SKIP_REASONS / SEAT_CLASSES, an empty key, a malformed size pair or requested_model, or
    neither project_root nor budget_path. A caller bug leaves no row behind.
    """
    if seat_class == SEAT_CLASS_AUDIT:
        raise ValueError("the VERIFIED-gate audit is substituted, never skipped "
                         "(seat_class 'audit' has no skip)")
    if seat_class not in SEAT_CLASSES:
        raise ValueError(f"unknown seat_class {seat_class!r}; expected one of {sorted(SEAT_CLASSES)}")
    if use is not None and use not in USES:
        raise ValueError(f"unknown use {use!r}; expected None or one of {sorted(USES)}")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key must be a non-empty string")
    if reason not in SKIP_REASONS:
        raise ValueError(f"unknown skip reason {reason!r}; expected one of {sorted(SKIP_REASONS)} "
                         f"(the reasons tripwire() decides a skip on)")
    if role not in SKIP_ROLES:
        raise ValueError(f"role {role!r} has no codex seat; expected one of {sorted(SKIP_ROLES)}")
    size, size_source = _checked_size(size, size_source)
    requested_by = _checked_requested_by(requested_by)
    requested_model = _checked_requested_model(requested_model)
    if budget_path is None and project_root is None:
        raise ValueError("project_root is required unless budget_path is given")
    now_epoch = _now_epoch(now)
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    if project_root is not None:
        provenance = _cycle_provenance(project_root, key, now_epoch)
    else:
        provenance = {"cycle_id_source": SOURCE_EXPLICIT, "cycle_id_file_age_s": None}
    snap, _limits = _scan(sessions_dir, now_epoch)

    row: Dict[str, Any] = {
        "at": _iso_z(now_epoch),
        "kind": ROW_KIND_SKIP,
        "key": key,
        "cycle_id": key,
        "cycle_id_source": provenance["cycle_id_source"],
        "cycle_id_file_age_s": provenance["cycle_id_file_age_s"],
        "use": use,
        "seat_class": seat_class,
        "role": role,
        "requested_model": requested_model,
        "reason": reason,
        "size": size,
        "size_source": size_source,
        "snapshot_state": snap["state"],
        "primary": snap["primary_used_percent"],
        "weekly": snap["secondary_used_percent"],
    }
    if requested_by is not None:
        row["requested_by"] = requested_by

    row_written = False
    error: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            _append_row(path, row)
            row_written = True
    except Exception as exc:  # noqa: BLE001 — a store failure never raises
        error = f"{type(exc).__name__}: {exc}"

    result: Dict[str, Any] = dict(row)
    result["row_written"] = row_written
    result["budget_path"] = str(path)
    if error is not None:
        result["error"] = error
    return result


# --------------------------------------------------------------------------- #
# record_substitution()
# --------------------------------------------------------------------------- #
def record_substitution(use, cycle_id, reason, *, project_root, role, served_model, requested_model=None,
                        size=None, size_source=None, requested_by=None,
                        now=None, budget_path=None, sessions_dir=None, admission_id=None) -> Dict[str, Any]:
    """Record that a fresh Claude agent served a codex TOP seat (amendment 1 D6).

    Appends one `kind: "substitution"` row (keys in the module docstring) under the same
    lock as admit(). The row has no `admitted` key, so a substitution never spends a
    budget. Returns the row plus `row_written`, `budget_path` and, on a store failure,
    `error` — a store failure never raises.

    #282 r10: `admission_id` is the id of the admit() decision this substitution REPLACES
    (None when it replaces none: a refusal, a plan-time check, a prose call site). The row
    always carries it, and a named admission stops counting (module docstring CORRELATION).

    Design §2.1 (S081 revision 4): the row records `size` and `size_source` unconditionally —
    WHICH SIZE of call was refused — and `requested_by: "user"` for a user request. An
    un-migrated caller records complex / "default", so a row from one is never read as a
    refused light call. `key` mirrors `cycle_id` for the same reason it does on a budget row.

    Raises ValueError for a caller bug: use "trial" (the trial is skipped, never
    substituted), a use / reason / role outside SUBSTITUTION_USES / SUBSTITUTION_REASONS /
    SUBSTITUTION_ROLES, an empty cycle_id, a served_model that is not a plain word or is a
    codex (gpt-) model, a requested_model that is not a plain word, an admission_id that is
    neither None nor 32 lowercase hex, neither project_root nor budget_path, or a malformed
    `now`.
    """
    if use == "trial":
        raise ValueError("the astra trial is skipped, never substituted")
    if use not in SUBSTITUTION_USES:
        raise ValueError(f"unknown substitution use {use!r}; expected one of {sorted(SUBSTITUTION_USES)}")
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError("cycle_id must be a non-empty string")
    if reason not in SUBSTITUTION_REASONS:
        raise ValueError(f"unknown substitution reason {reason!r}; expected one of {sorted(SUBSTITUTION_REASONS)}")
    if role not in SUBSTITUTION_ROLES:
        raise ValueError(f"role {role!r} has no codex TOP seat; expected one of {sorted(SUBSTITUTION_ROLES)}")
    if not _is_claude_model_word(served_model):
        raise ValueError(f"served_model {served_model!r} must be a plain Claude model word, never a gpt- model")
    requested_model = _checked_requested_model(requested_model)
    size, size_source = _checked_size(size, size_source)
    requested_by = _checked_requested_by(requested_by)
    if admission_id is not None and not is_admission_id(admission_id):
        raise ValueError(f"admission_id {admission_id!r} must be None or 32 lowercase hex characters")
    if budget_path is None and project_root is None:
        raise ValueError("project_root is required unless budget_path is given")
    now_epoch = _now_epoch(now)
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    if project_root is not None:
        provenance = _cycle_provenance(project_root, cycle_id, now_epoch)
    else:
        provenance = {"cycle_id_source": SOURCE_EXPLICIT, "cycle_id_file_age_s": None}
    snap, _limits = _scan(sessions_dir, now_epoch)

    row: Dict[str, Any] = {
        "at": _iso_z(now_epoch),
        "kind": ROW_KIND_SUBSTITUTION,
        "key": cycle_id,
        "cycle_id": cycle_id,
        "cycle_id_source": provenance["cycle_id_source"],
        "cycle_id_file_age_s": provenance["cycle_id_file_age_s"],
        "use": use,
        "substitute_for": SUBSTITUTE_FOR,
        "requested_model": requested_model,
        "served_model": served_model,
        "role": role,
        "reason": reason,
        "size": size,
        "size_source": size_source,
        "snapshot_state": snap["state"],
        "primary": snap["primary_used_percent"],
        "weekly": snap["secondary_used_percent"],
        "prior_admitted_in_cycle": None,
        "admission_id": admission_id,
    }
    if requested_by is not None:
        row["requested_by"] = requested_by
    row_written = False
    error: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            row["prior_admitted_in_cycle"] = _count_admitted(path, cycle_id, None, None, also_netted=admission_id)
            _append_row(path, row)
            row_written = True
    except Exception as exc:  # noqa: BLE001 — a store failure never raises
        error = f"{type(exc).__name__}: {exc}"
        if not row_written:
            row["prior_admitted_in_cycle"] = None

    result: Dict[str, Any] = dict(row)
    result["row_written"] = row_written
    result["budget_path"] = str(path)
    if error is not None:
        result["error"] = error
    return result


def _top_retry_state(path: Path, admission_id: str) -> Tuple[Optional[Dict[str, Any]], bool, int]:
    """(the admit row carrying `admission_id`, whether a `top_retry` event SPENT it, how many `pending` events
    are still open) from the budget store. The CALLER holds the store lock. Raises OSError.

    User-scoped round (item 9, Opus N4): a pending event is CLOSED by a later substitution row of use
    `top_retry` on the event's own key and role -- the wait ended without codex and the seat was served by its
    stand-in (codex-orchestration step 4). A closed pending event is a spent retry: its one resumption is gone."""
    found: Optional[Dict[str, Any]] = None
    retried = False
    open_pending: List[Tuple[Any, Any]] = []
    closed = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if "admitted" in row and row.get("admission_id") == admission_id and found is None:
                found = row
            kind = row.get("kind")
            if kind == ROW_KIND_TOP_RETRY and row.get("failed_admission_id") == admission_id:
                if row.get("outcome") == TOP_RETRY_PENDING:
                    open_pending.append((row.get("key"), row.get("role")))
                else:
                    retried = True
            elif kind == ROW_KIND_SUBSTITUTION and row.get("use") == "top_retry" and open_pending:
                target = (row.get("key"), row.get("role"))
                for index in range(len(open_pending) - 1, -1, -1):
                    if open_pending[index] == target:
                        del open_pending[index]
                        closed += 1
                        break
    if closed:
        retried = True
    return found, retried, len(open_pending) + closed


def find_admission(project_root, admission_id, *, budget_path=None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the admit row carrying `admission_id` or None, whether a `top_retry` event already names it), read
    UNDER THE STORE LOCK (fix round 2, item 5). A malformed id, no store or an unreadable one is (None, False).
    A caller that must TRUST the row (seat_model's TOP retry) checks what it names; the second value is the
    replay guard: one failed admission buys at most one TOP retry, in any cycle.

    #322 fix round 2 (item 3): a `pending` event (the retry was refused for QUOTA with --await-quota, and the
    caller waits for a reset) is not a spent retry: ONE pending event permits exactly one resumption. Any
    admitted / substituted event, or a second pending one (the resumption was refused for quota again), is the
    replay guard as before. User-scoped round (item 9): so is a pending event a later `top_retry` stand-in
    closed (_top_retry_state). This is a READ; the retry itself reserves its attempt with claim_top_retry()."""
    if not is_admission_id(admission_id):
        return None, False
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    if not path.exists():
        return None, False
    try:
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            found, retried, pending = _top_retry_state(path, admission_id)
    except Exception:  # noqa: BLE001 - an unreadable store proves nothing
        return None, False
    return found, retried or pending >= 2


def top_retry_claims_path_for(budget_path) -> Path:
    """User-scoped round (item 5): the TOP-retry attempt reservations, beside the budget store (never in it: a
    reservation is not a budget row). Keyed by the failed admission id alone -- never by a cycle key."""
    path = Path(budget_path)
    return path.with_name(path.stem + TOP_RETRY_CLAIMS_SUFFIX)


def claim_top_retry(project_root, admission_id, *, budget_path=None, now=None) -> Tuple[bool, str]:
    """RESERVE one TOP-retry attempt of the failed admission `admission_id` (user-scoped round, item 5).
    (True, "claimed") or (False, reason): "replay" (the retry is spent -- the replay guard) or "error" (the
    store could not be read or the reservation written: no attempt is made). Never raises.

    The replay check and the reservation are ONE step under the budget store's lock: fix round 2 checked with
    find_admission() and only then admitted and appended the event, in separate lock acquisitions, so two
    concurrent resumers of one pending event both passed the guard (and, with a cycle key changing between the
    calls, each could spend a different TOP slot). The rule: the attempts ever reserved for an admission may
    not exceed 1 + its open pending events -- the first attempt, plus the one resumption a pending event
    permits -- and a spent retry (_top_retry_state) permits none. Each reservation records its attempt number. A reservation whose attempt then crashed
    before writing its event stays spent: one failed admission buys at most one TOP retry."""
    if not is_admission_id(admission_id):
        return False, "error"
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    claims = top_retry_claims_path_for(path)
    try:
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            found, retried, pending = _top_retry_state(path, admission_id)
            if found is None:
                return False, "error"
            if retried or pending >= 2:
                return False, "replay"
            # Attempts so far: the highest reserved attempt number, or -- for a retry that began before
            # reservations existed -- the pending events it wrote (each attempt writes one event).
            attempts = pending
            try:
                with open(claims, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row, dict) and row.get("failed_admission_id") == admission_id:
                            number = row.get("attempt")
                            attempts = max(attempts, number if isinstance(number, int) and number > 0 else 1)
            except FileNotFoundError:
                pass
            if attempts >= 1 + pending:
                return False, "replay"
            _append_row(claims, {"at": _iso_z(_now_epoch(now)), "failed_admission_id": admission_id,
                                 "attempt": attempts + 1})
        return True, "claimed"
    except Exception:  # noqa: BLE001 - a store fault never raises; no attempt without a reservation
        return False, "error"


def record_top_retry(cycle_id, *, project_root, role, origin_use, origin_key, failed_admission_id, failed_model,
                     failed_reason, retry_model, outcome, reason=None, retry_admission_id=None, task_key=None,
                     now=None, budget_path=None, sessions_dir=None) -> Dict[str, Any]:
    """Record one Sol -> TOP retry (the astra reserve U2/F3) as a `kind: "top_retry"` EVENT row.

    `cycle_id` is the retry's own budget key - the FORGE CYCLE (top_retry is 1 per cycle) - and `origin_key`
    the key the failed seat was admitted on (a tournament, a ballot, the cycle itself). It links both attempts
    EXACTLY: the failed seat (`origin_use`, `origin_key`, `failed_admission_id` - the admission the caller
    proved, never a lookup - `failed_model`, `failed_reason`) and the retry (`retry_model`, `outcome`,
    `reason`, `retry_admission_id`). It is NOT a substitution row and has no `admitted` key: it spends nothing
    and nets nothing, because the failed Sol call DID consume quota and the retry's own admit row already
    counts against `top_retry`. Returns the row plus `row_written` / `budget_path` (and `error`); a store
    failure never raises. ValueError for a caller bug.
    """
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError("cycle_id must be a non-empty string")
    if role not in SUBSTITUTION_ROLES:
        raise ValueError(f"role {role!r} is not a budgeted codex seat; expected one of {sorted(SUBSTITUTION_ROLES)}")
    if origin_use not in TOP_RETRY_ORIGIN_USES:
        raise ValueError(f"origin_use {origin_use!r} cannot be retried on TOP")
    if not isinstance(origin_key, str) or not origin_key.strip():
        raise ValueError("origin_key must be a non-empty string")
    if failed_admission_id is not None and not is_admission_id(failed_admission_id):
        raise ValueError(f"failed_admission_id {failed_admission_id!r} must be None or 32 lowercase hex characters")
    if failed_reason not in ("capacity_twice", "malformed_twice"):
        raise ValueError(f"failed_reason {failed_reason!r} is not a capability failure (capacity_twice, "
                         f"malformed_twice)")
    if outcome not in TOP_RETRY_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(TOP_RETRY_OUTCOMES)}, got {outcome!r}")
    if outcome == "substituted" and reason not in SUBSTITUTION_REASONS:
        raise ValueError(f"a substituted TOP retry needs a SUBSTITUTION_REASONS reason, got {reason!r}")
    if outcome == TOP_RETRY_PENDING and reason not in QUOTA_REFUSAL_REASONS:
        raise ValueError(f"a pending TOP retry waits for a QUOTA reset; reason must be one of "
                         f"{sorted(QUOTA_REFUSAL_REASONS)}, got {reason!r}")
    failed_model = _checked_requested_model(failed_model)
    retry_model = _checked_requested_model(retry_model)
    if retry_admission_id is not None and not is_admission_id(retry_admission_id):
        raise ValueError(f"retry_admission_id {retry_admission_id!r} must be None or 32 lowercase hex characters")
    if budget_path is None and project_root is None:
        raise ValueError("project_root is required unless budget_path is given")
    now_epoch = _now_epoch(now)
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    if project_root is not None:
        provenance = _cycle_provenance(project_root, cycle_id, now_epoch)
    else:
        provenance = {"cycle_id_source": SOURCE_EXPLICIT, "cycle_id_file_age_s": None}
    row: Dict[str, Any] = {
        "at": _iso_z(now_epoch), "kind": ROW_KIND_TOP_RETRY, "key": cycle_id, "cycle_id": cycle_id,
        "cycle_id_source": provenance["cycle_id_source"],
        "cycle_id_file_age_s": provenance["cycle_id_file_age_s"],
        "role": role, "origin_use": origin_use, "origin_key": origin_key, "failed_model": failed_model,
        "failed_reason": failed_reason, "failed_admission_id": failed_admission_id, "retry_model": retry_model,
        "outcome": outcome, "reason": reason, "task_key": task_key,
        "retry_admission_id": retry_admission_id,
    }
    row_written = False
    error: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            _append_row(path, row)
            row_written = True
    except Exception as exc:  # noqa: BLE001 - a store failure never raises
        error = f"{type(exc).__name__}: {exc}"
    result: Dict[str, Any] = dict(row)
    result["row_written"] = row_written
    result["budget_path"] = str(path)
    if error is not None:
        result["error"] = error
    return result


# --------------------------------------------------------------------------- #
# classify_codex_failure()
# --------------------------------------------------------------------------- #
def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def _without_prompt_echo(stderr: Any, prompt: Any) -> str:
    """stderr with every verbatim copy of the prompt removed (also the prompt without its
    trailing newlines, the shape `$(cat prompt-file)` gives)."""
    text = _as_text(stderr)
    prompt_text = _as_text(prompt)
    for candidate in (prompt_text, prompt_text.rstrip("\r\n")):
        if candidate:
            text = text.replace(candidate, "")
    return text


def _first_signal(patterns, text: str) -> Optional[str]:
    for name, pattern in patterns:
        if pattern.search(text):
            return name
    return None


def exhaustion_signal(stderr: Any, prompt: Any = None) -> Optional[str]:
    """The name of the first EXHAUSTION_PATTERNS match outside the prompt echo, else None. Pure.

    LINE-AGNOSTIC and NOT a classification (#282 R2): it matches anywhere in stderr, tool
    output included. Deciding a quota stop belongs to classify_codex_failure alone."""
    return _first_signal(EXHAUSTION_PATTERNS, _without_prompt_echo(stderr, prompt))


def auth_signal(stderr: Any, prompt: Any = None) -> Optional[str]:
    """The name of the first AUTH_PATTERNS match outside the prompt echo, else None. Pure.

    LINE-AGNOSTIC and NOT a classification (#282 R2), like exhaustion_signal()."""
    return _first_signal(AUTH_PATTERNS, _without_prompt_echo(stderr, prompt))


def _stderr_lines(text: str) -> List[str]:
    """`text` split on "\\n" only, each line's trailing "\\r" dropped. Splitting on "\\n" alone
    (not str.splitlines) keeps a form feed or U+2028 inside tool output from starting a line."""
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def _error_line_message(line: str) -> Optional[str]:
    """The message of a codex-owned error line (CODEX_ERROR_LINE_PATTERNS), else None."""
    for _name, pattern in CODEX_ERROR_LINE_PATTERNS:
        match = pattern.match(line)
        if match is not None and match.end() == len(line):
            return match.group("message")
    return None


def codex_error_lines(stderr: Any, prompt: Any = None) -> List[str]:
    """The stderr lines in a codex-owned error shape, in order, after every verbatim copy of
    the prompt is removed (#282 R2). Pure: no I/O."""
    return [line for line in _stderr_lines(_without_prompt_echo(stderr, prompt))
            if _error_line_message(line) is not None]


def corroboration_for(stderr: Any, prompt: Any = None, *, sessions_dir=None, now=None) -> Dict[str, Any]:
    """ONE corroboration object for ONE finished codex call (#282 R2).

    -> {"codex_error_lines": codex_error_lines(stderr, prompt), "unavailable_token":
    unavailable(...)}. Its ONLY I/O is that one unavailable() read (the bounded rollout walk;
    never raises), so build it AFTER the call and at most once per failed call, then pass it
    to classify_codex_failure(). A caller that has no failed call builds none.
    """
    return {
        "codex_error_lines": codex_error_lines(stderr, prompt),
        "unavailable_token": unavailable(sessions_dir=sessions_dir, now=now),
    }


def _corroborated_evidence(stderr: Any, prompt: Any, corroboration: Any) -> Tuple[str, Optional[str]]:
    """(the joined messages of the codex error lines, the meter token) for the classifier.

    corroboration None -> the error lines come from `stderr` and there is no token. Otherwise
    its lines are RE-CHECKED against the error-line shapes (a line that is not one adds
    nothing) and its token counts only when it is one of METER_EXHAUSTION_TOKENS. A
    corroboration of the wrong shape is a caller bug (ValueError)."""
    if corroboration is None:
        lines: List[str] = codex_error_lines(stderr, prompt)
        meter_reason = None
    else:
        if not isinstance(corroboration, Mapping) or "codex_error_lines" not in corroboration \
                or "unavailable_token" not in corroboration:
            raise ValueError("corroboration must be a mapping with codex_error_lines and unavailable_token "
                             f"(build it with corroboration_for), got {corroboration!r}")
        raw_lines = corroboration["codex_error_lines"]
        if isinstance(raw_lines, (str, bytes)) or not isinstance(raw_lines, (list, tuple)) \
                or not all(isinstance(line, str) for line in raw_lines):
            raise ValueError(f"corroboration codex_error_lines must be a list of str, got {raw_lines!r}")
        meter_reason = corroboration["unavailable_token"]
        if meter_reason is not None and not isinstance(meter_reason, str):
            raise ValueError(f"corroboration unavailable_token must be a str or None, got {meter_reason!r}")
        lines = list(raw_lines)
    messages = [message for message in (_error_line_message(line) for line in lines) if message is not None]
    return "\n".join(messages), (meter_reason if meter_reason in METER_EXHAUSTION_TOKENS else None)


def classify_codex_failure(returncode, stderr, *, timed_out, output_ok, attempt,
                           prompt=None, corroboration=None) -> Tuple[str, Optional[str]]:
    """The ONE call-time classifier for a TOP codex call (J9). PURE: no I/O of any kind.

    -> (action, reason), action in {"ok", "retry", "substitute", "gap"}; reason is None for
    ok. Order and reasons in the module docstring (ASTRA UNAVAILABLE). `returncode` is the
    exit status or None when the process never completed (a timeout); a spawn-time
    FileNotFoundError is passed as 127, and codex_watch's runaway cap as EXIT_HARD_CAP (112)
    with timed_out False - a GAP on every attempt, decided FIRST, whatever stderr says (D21
    F10). `attempt` counts from 1; the same-model retry is attempt 2.

    #282 R2: a quota / auth / capacity signal counts only on a codex-owned error line; an
    exhaustion signal on any other line counts when `corroboration`'s unavailable_token is
    rate_limit_reached or quota_exhausted. `corroboration` is corroboration_for()'s object,
    built by the caller (the only place a meter is read); None -> the error lines are taken
    from `stderr` and no token exists. Raises ValueError only for a caller bug (attempt not an
    int >= 1, a returncode that is neither an int nor None, a malformed corroboration).
    """
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError(f"attempt must be an int >= 1, got {attempt!r}")
    if returncode is not None and (isinstance(returncode, bool) or not isinstance(returncode, int)):
        raise ValueError(f"returncode must be an int or None, got {returncode!r}")
    timed_out = bool(timed_out)
    error_text, token = _corroborated_evidence(stderr, prompt, corroboration)
    if not timed_out and returncode == EXIT_HARD_CAP:
        # S081 rev 4 D21 F10: the FIRST decision. A call that stayed active to its runaway cap is not
        # the retryable kind of stop, and a codex error line in its transcript does not make it one:
        # checked after the signals, it bought a retry (capacity) or a substitute (quota / auth).
        return ACTION_GAP, "codex_error"
    if not timed_out and returncode == 0 and output_ok:
        return ACTION_OK, None
    if not timed_out and returncode == EXIT_COMMAND_NOT_FOUND:
        return ACTION_SUBSTITUTE, "cli_missing"
    if _first_signal(EXHAUSTION_PATTERNS, error_text) is not None:
        return ACTION_SUBSTITUTE, UNAVAILABLE_QUOTA_EXHAUSTED
    if token is not None and _first_signal(EXHAUSTION_PATTERNS, _without_prompt_echo(stderr, prompt)) is not None:
        return ACTION_SUBSTITUTE, UNAVAILABLE_QUOTA_EXHAUSTED  # meter agreement
    if _first_signal(AUTH_PATTERNS, error_text) is not None:
        return ACTION_SUBSTITUTE, "auth_failure"
    if _first_signal(CAPACITY_PATTERNS, error_text) is not None:
        return (ACTION_RETRY, "capacity") if attempt == 1 else (ACTION_SUBSTITUTE, "capacity_twice")
    if timed_out:
        return (ACTION_RETRY, "timeout") if attempt == 1 else (ACTION_SUBSTITUTE, "timeout_twice")
    if returncode == 0:
        return (ACTION_RETRY, "malformed") if attempt == 1 else (ACTION_SUBSTITUTE, "malformed_twice")
    return ACTION_GAP, "codex_error"


# --------------------------------------------------------------------------- #
# cycle_id_for()
# --------------------------------------------------------------------------- #
def _first_line(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def _cycle_id_first_line(path: Path) -> Optional[str]:
    """The stripped first line of a cycle-id file, bounded; None when unreadable or when
    the first line does not end within CYCLE_ID_READ_BYTES."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(CYCLE_ID_READ_BYTES + 1)
    except (OSError, ValueError):
        return None
    newline = data.find(b"\n")
    if newline < 0 and len(data) > CYCLE_ID_READ_BYTES:
        return None
    first = data if newline < 0 else data[:newline]
    return first.decode("utf-8", errors="replace").strip()


def _cycle_id_file(forge: Path, now_epoch: float) -> Tuple[Optional[str], Optional[int]]:
    """(usable id or None, file age in whole seconds or None). Read-only (J3b, J4)."""
    path = forge / "cycle-id"
    try:
        mtime = os.stat(path).st_mtime
    except (OSError, ValueError):
        return None, None  # absent, or its mtime is unreadable: counts as absent
    if not math.isfinite(mtime):
        return None, None
    age = now_epoch - mtime
    age_s = int(math.floor(age))
    if age > CYCLE_ID_MAX_AGE_S or age < -FUTURE_SKEW_S:
        return None, age_s  # aged out, or planted/skewed into the future
    line = _cycle_id_first_line(path)
    if line is None or not CYCLE_ID_PATTERN.match(line):
        return None, age_s
    return line, age_s


def cycle_id_and_source(project_root, *, now=None) -> Tuple[str, str, Optional[int]]:
    """(cycle_id, source, file_age_s) — the per-cycle budget key with its provenance.

    source is "cycle-id", "adhoc-base" or "adhoc-nobase" (precedence in the module
    docstring, THE BUDGET KEY). file_age_s is the .forge/cycle-id file's age in whole
    seconds (rounded down; negative for a future mtime) whenever that file exists and
    its mtime is readable — including when it was aged out or its content rejected —
    else None. Read-only and never raises.
    """
    try:
        now_epoch = _now_epoch(now)
    except Exception:
        now_epoch = time.time()
    day = datetime.fromtimestamp(now_epoch, timezone.utc).strftime("%Y%m%d")
    age_s: Optional[int] = None
    try:
        forge = Path(project_root) / ".forge"
        cycle, age_s = _cycle_id_file(forge, now_epoch)
        if cycle is not None:
            return cycle, SOURCE_CYCLE_ID, age_s
        base = _first_line(forge / "cycle-base")
        match = _HEX7.match(base)
        if match:
            return f"adhoc-{day}-{match.group(0).lower()}", SOURCE_ADHOC_BASE, age_s
    except Exception:
        pass
    return f"adhoc-{day}-nobase", SOURCE_ADHOC_NOBASE, age_s


def cycle_id_for(project_root, *, now=None) -> str:
    """The per-cycle astra budget key (D7), from files only. The date is UTC.

    Precedence: the first line of .forge/cycle-id (written FRESH by forge Step 1 every
    cycle, deleted at forge close-out) when it matches CYCLE_ID_PATTERN and its mtime is
    at most CYCLE_ID_MAX_AGE_S (24h) old and not more than FUTURE_SKEW_S in the future;
    else adhoc-<YYYYMMDD>-<first 7 hex of .forge/cycle-base>; else adhoc-<YYYYMMDD>-nobase.
    A cycle-base that does not start with 7 hex digits (an empty or error-text redirect)
    counts as absent. The 24h age-out catches abandoned sessions that never reached
    close-out; its failure direction is a fresh budget mid-cycle for a cycle longer
    than 24h (slightly more astra), never bogus refusals.

    .forge/session-id is NEVER read: it is the contract-signing id, minted once at forge
    Step 8a.2 and never re-minted (gates.py G1 compares signed payloads against it), so
    a budget keyed on it never rolled over. Read-only: no file is created, modified,
    touched or deleted, including an aged-out cycle-id.
    """
    return cycle_id_and_source(project_root, now=now)[0]


# --------------------------------------------------------------------------- #
# #322 await-reset: wait for codex to be usable again, probing it
# --------------------------------------------------------------------------- #
def record_probe(outcome, *, project_root, model=None, exit_code=None, key=None, now=None,
                 budget_path=None, sessions_dir=None) -> Dict[str, Any]:
    """Append one `kind: "probe"` row ({at, kind, key, cycle_id, use: "probe", requested_model, outcome,
    exit_code, snapshot_state, primary, weekly} + cycle provenance) for one await-reset probe (#322).

    The row has NO `admitted` key, so _count_admitted() never counts it: a probe is exempt from every
    per-round budget. It has no `substitute_for` either, so it never inflates the substitution count.
    A store failure never raises (row_written false plus `error`). Raises ValueError for an outcome
    outside PROBE_OUTCOMES or neither project_root nor budget_path."""
    if outcome not in PROBE_OUTCOMES:
        raise ValueError(f"unknown probe outcome {outcome!r}; expected one of {sorted(PROBE_OUTCOMES)}")
    if budget_path is None and project_root is None:
        raise ValueError("project_root is required unless budget_path is given")
    now_epoch = _now_epoch(now)
    path = Path(budget_path) if budget_path is not None else budget_path_for(project_root)
    if key is None:
        key = cycle_id_for(project_root, now=now_epoch) if project_root is not None else "probe"
    provenance = (_cycle_provenance(project_root, key, now_epoch) if project_root is not None
                  else {"cycle_id_source": SOURCE_EXPLICIT, "cycle_id_file_age_s": None})
    snap, _limits = _scan(sessions_dir, now_epoch)
    row: Dict[str, Any] = {
        "at": _iso_z(now_epoch),
        "kind": ROW_KIND_PROBE,
        "key": key,
        "cycle_id": key,
        "use": PROBE_USE,
        "requested_model": model,
        "outcome": outcome,
        "exit_code": exit_code,
        "snapshot_state": snap["state"],
        "primary": snap["primary_used_percent"],
        "weekly": snap["secondary_used_percent"],
    }
    row.update(provenance)
    result: Dict[str, Any] = dict(row)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(lock_path_for(path), timeout=LOCK_TIMEOUT_S):
            _append_row(path, row)
        result["row_written"] = True
    except Exception as exc:  # noqa: BLE001 - a store failure never raises
        result["row_written"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["budget_path"] = str(path)
    return result


def probe_model() -> str:
    """The probe's model: the codex support tier (model_roster.CODEX_SUPPORT), the roster's cheapest
    seat. Imported lazily: model_roster is a data file, but this module stays import-light."""
    import model_roster  # noqa: E402  (a pure data module, no cycle)
    return model_roster.CODEX_SUPPORT


def probe_argv(model: str, output_path) -> List[str]:
    """The probe's `codex exec` argv. NEVER `--ephemeral`: its rollout's rate_limits must refresh the
    meter. Read-only sandbox, no git-repo check, the output to `output_path`, the prompt last."""
    return ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-m", model,
            "-c", f"model_reasoning_effort={PROBE_EFFORT}", "-o", str(output_path), PROBE_PROMPT]


def run_probe(*, model=None, sessions_dir=None, hard_cap_s=PROBE_HARD_CAP_S,
              exhausted_path=None) -> Tuple[str, Optional[int]]:
    """Run ONE real probe through codex_watch (the one way harness code runs `codex exec`) and classify
    it: (outcome, exit code). ok -> available; substitute quota_exhausted -> exhausted; substitute
    auth_failure -> auth; substitute cli_missing -> cli_missing; anything else -> error (kept polling).
    This is the ONLY place this module starts a process, and only `await-reset` calls it.

    #322 fix round 1: `hard_cap_s` is the watchdog's runaway cap (await-reset passes the time left, so the
    last probe cannot overrun --max-wait by PROBE_HARD_CAP_S). An exhausted probe persists the
    exhausted-until record with the reset time codex's own text names ("try again at 1:50 AM"), when it
    names one -- the probe's rollout carries no usable reading, so the text is the only reset time it has."""
    import tempfile
    if not model:
        try:
            model = probe_model()
        except Exception:  # noqa: BLE001 - no model to probe with is an environment fault, not a verdict
            return PROBE_ERROR, None
    with tempfile.TemporaryDirectory(prefix="codex-probe-") as tmp:
        out, err, stdout = Path(tmp) / "out.txt", Path(tmp) / "stderr.txt", Path(tmp) / "stdout.txt"
        try:
            result = codex_watch.codex_watch(probe_argv(model, out), effort=PROBE_EFFORT, stdout_path=stdout,
                                             stderr_path=err, model=model, hard_cap_s=hard_cap_s,
                                             record_telemetry=False)
            returncode, timed_out = result.exit_code, result.timed_out
        except FileNotFoundError:
            returncode, timed_out = EXIT_COMMAND_NOT_FOUND, False
        except Exception:  # noqa: BLE001 - the watchdog itself failed: not a codex verdict
            return PROBE_ERROR, None
        try:
            stderr = _read_capped(err, CLASSIFY_READ_BYTES) if err.exists() else ""
        except (OSError, _FileTooLarge):
            stderr = ""
        output_ok = _output_is_usable(out)
        succeeded = not timed_out and returncode == 0 and output_ok
        corroboration = None if succeeded else corroboration_for(stderr, PROBE_PROMPT, sessions_dir=sessions_dir)
        action, reason = classify_codex_failure(returncode, stderr, timed_out=timed_out, output_ok=output_ok,
                                                attempt=2, prompt=PROBE_PROMPT, corroboration=corroboration)
    if action == ACTION_OK:
        return PROBE_AVAILABLE, returncode
    if action == ACTION_SUBSTITUTE and reason == UNAVAILABLE_QUOTA_EXHAUSTED:
        retry_at = retry_at_from_text(_without_prompt_echo(stderr, PROBE_PROMPT))
        if retry_at is not None:
            record_exhausted(retry_at, source="probe", path=exhausted_path)
        return PROBE_EXHAUSTED, returncode
    if action == ACTION_SUBSTITUTE and reason == "auth_failure":
        return PROBE_AUTH, returncode
    if action == ACTION_SUBSTITUTE and reason == "cli_missing":
        return PROBE_CLI_MISSING, returncode
    return PROBE_ERROR, returncode


def notify_claim(*, project_root=None, budget_path=None, now=None, window_s=AWAIT_MAX_WAIT_S,
                 exhausted_path=None) -> bool:
    """One notification per refusal WAVE (#322 fix round 1, minor 4; ACCOUNT-WIDE since fix round 2, item 10).
    True: this caller sends the push notification (and the claim is recorded); False: another seat of the same
    wave already did. Fail-OPEN: a store that cannot be read or written returns True -- a duplicate
    notification beats a missing one.

    The claim lives in ~/.claude/state (NOTIFY_WAVE_FILENAME, beside the exhausted record), because codex quota
    is account-wide: two projects refused together are one wave. It is keyed on the ACTIVE exhausted record's
    wave (record_wave: its exhausted_until and evidence_at as opened), so it holds for the record's whole life
    -- a far reset notifies once, not once per 30 minutes -- and a NEW record starts a new wave. Retiring or
    clearing the record removes the claim. With no active record the claim holds `window_s` from when it was
    made. `project_root` and `budget_path` are accepted and ignored (the claim is no longer per project)."""
    now_epoch = _now_epoch(now)
    record_path = Path(exhausted_path) if exhausted_path is not None else exhausted_path_for()
    target = record_path.parent / NOTIFY_WAVE_FILENAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        record = read_exhausted(path=record_path)
        wave = record_wave(record) if record is not None and record["exhausted_until"] > now_epoch else None
        with file_lock(target.with_name(target.name + ".lock"), timeout=LOCK_TIMEOUT_S):
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                claimed = _finite_number(data.get("claimed_at"))
                claimed_wave = data.get("wave")
            except (OSError, ValueError, AttributeError):
                claimed, claimed_wave = None, None
            if wave is not None:
                if claimed_wave == wave:
                    return False
            elif claimed_wave is None and claimed is not None and claimed <= now_epoch < claimed + window_s:
                return False
            _atomic_json(target, {"claimed_at": now_epoch, "wave": wave})
        return True
    except Exception:  # noqa: BLE001 - fail open
        return True


def _clear_notify_wave(state_dir: Path) -> None:
    try:
        (state_dir / NOTIFY_WAVE_FILENAME).unlink()
    except OSError:
        pass


def _timed_out_wave(state_dir: Path) -> Optional[List[float]]:
    """The wave whose full await-reset already timed out (AWAIT_TIMEOUT_FILENAME), else None."""
    try:
        wave = json.loads((state_dir / AWAIT_TIMEOUT_FILENAME).read_text(encoding="utf-8")).get("wave")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(wave, list) and len(wave) == 2 and all(_finite_number(v) is not None for v in wave):
        return [float(v) for v in wave]
    return None


def _mark_timed_out(state_dir: Path, wave: Optional[List[float]], now_epoch: float) -> None:
    if wave is None:
        return
    try:
        _atomic_json(state_dir / AWAIT_TIMEOUT_FILENAME, {"wave": wave, "at": now_epoch})
    except Exception:  # noqa: BLE001 - without the marker the next seat simply waits once more
        pass


def _read_await_result(path: Path, since: float) -> Optional[Tuple[int, Dict[str, Any]]]:
    """The (exit code, result) another await-reset wrote at or after `since`, else None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        finished = _finite_number(data.get("finished_at"))
        code, result = data.get("code"), data.get("result")
    except (OSError, ValueError, AttributeError):
        return None
    if finished is None or finished < since or not isinstance(code, int) or not isinstance(result, dict):
        return None
    return code, result


def await_reset(*, project_root, max_wait=AWAIT_MAX_WAIT_S, poll=AWAIT_POLL_S, margin=AWAIT_MARGIN_S,
                clock=None, sleep=None, probe=None, sessions_dir=None, budget_path=None,
                key=None, exhausted_path=None) -> Tuple[int, Dict[str, Any]]:
    """Wait until codex is usable again (#322). Returns (exit code, the final JSON line's dict).

    The dict is {available, waited_s, probes, source} (+ wait_advice, resets_at, resets_in_s,
    binding_window from the meter -- or the exhausted-until record -- at the start, and `joined: true` when
    it is another caller's result). source: `reset` (codex answered and the meter does not prove a manual
    reset), `user_reset` (a reading NEWER than the answering probe is below EXHAUSTED_PERCENT, before
    resets_at: the user reset the plan by hand), `timeout`, `auth_failure`, `cli_missing`, `probe_error`.

    ONE PER ACCOUNT (fix round 1, minor 4; fix round 2, item 10): the wait holds AWAIT_LOCK_FILENAME in
    ~/.claude/state (the exhausted record's directory -- codex quota is account-wide). A caller that finds it
    held JOINS: it waits (polling every AWAIT_JOIN_POLL_S, up to its own max_wait) and returns the result the
    holder wrote after the joiner started, with `joined: true` and no probe of its own. A lock that cannot be
    taken for an environment reason is not a reason to skip the wait: it runs unlocked. The probe rows still
    go to the project's budget store.

    ONE FULL WAIT PER EXHAUSTED RECORD (fix round 2, item 5): a FULL wait that times out marks the wave it
    waited on (user-scoped round, items 4 and 8: only with max_wait >= AWAIT_MAX_WAIT_S, after at least one
    poll cycle, and only while that same wave is still active). A later await-reset for the SAME wave does not wait or sleep: it probes ONCE (so a reset the user made
    since is still seen, exit 0) and otherwise exits 4 at once with source `timed_out_for_record`.

    1. Read the meter once for the reset time and the advice.
    2. Probe AT ONCE: an auth failure exits 5 without waiting ("run codex login"), a missing CLI
       exits 3, and a codex that already answers (and whose meter clears) exits 0.
    3. `wait` (the reset is at most WAIT_ADVICE_MAX_S away): sleep until resets_at + margin (never
       past the deadline), then confirm with one probe.
    4. Then (and for `notify` from the start) probe every `poll` seconds until `max_wait` has passed
       since the start, the last probe landing on the deadline. Still exhausted -> exit 4.

    Fix round 1: an ANSWERING probe returns 0 only when the meter clears -- a reading newer than the probe
    that is still at or over EXHAUSTED_PERCENT keeps polling (minor 1); AWAIT_PROBE_ERROR_LIMIT consecutive
    non-quota probe errors exit EXIT_AWAIT_PROBE_ERROR (6) instead of timing out as if exhausted (minor 2);
    each probe's runaway cap is min(PROBE_HARD_CAP_S, the time left), and with less than PROBE_MIN_LEFT_S
    left the probe is skipped and the wait times out (fix round 2, m3: it never overruns --max-wait).
    An exhausted probe persists the exhausted-until record; a cleared one removes it and ends the
    notification wave.

    Every probe is recorded by record_probe() (`use: probe`, never budgeted) under `key` (the seat's budget
    key; default the project's cycle id). `clock` (epoch seconds), `sleep` and `probe` (-> (outcome, exit
    code)) are injected by tests, so no test sleeps or calls codex. Raises ValueError for a caller bug (a
    non-positive max_wait or poll, a negative margin)."""
    for name, value, floor_ok in (("max_wait", max_wait, False), ("poll", poll, False), ("margin", margin, True)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                or value < 0 or (value == 0 and not floor_ok):
            raise ValueError(f"{name} must be a finite number {'>= 0' if floor_ok else '> 0'}, got {value!r}")
    clock = clock or time.time
    sleep = sleep or time.sleep
    start = clock()
    deadline = start + max_wait
    lock_dir = _state_dir(exhausted_path)
    result_path = lock_dir / AWAIT_RESULT_FILENAME
    stack = ExitStack()
    with stack:
        locked = False
        try:
            lock_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        while True:
            try:
                stack.enter_context(file_lock(lock_dir / AWAIT_LOCK_FILENAME, blocking=False))
                locked = True
            except BlockingIOError:
                # Another await-reset of this project is waiting: join it.
                remaining = deadline - clock()
                if remaining <= 0:
                    joined = _read_await_result(result_path, start)
                    if joined is not None:
                        return _joined(joined, start, clock)
                    out = {"available": False, "waited_s": int(round(max(0.0, clock() - start))), "probes": 0,
                           "source": AWAIT_SOURCE_TIMEOUT, "joined": True}
                    return EXIT_AWAIT_TIMEOUT, out
                sleep(min(AWAIT_JOIN_POLL_S, remaining))
                continue
            except Exception:  # noqa: BLE001 - no lock possible: wait unlocked rather than not at all
                pass
            break
        if locked:
            joined = _read_await_result(result_path, start)
            if joined is not None:
                return _joined(joined, start, clock)
        trace: Dict[str, Any] = {"wave": None, "polled": False}
        code, out = _await_reset_locked(project_root=project_root, start=start, deadline=deadline, poll=poll,
                                        margin=margin, clock=clock, sleep=sleep, probe=probe,
                                        sessions_dir=sessions_dir, budget_path=budget_path, key=key,
                                        exhausted_path=exhausted_path, state_dir=lock_dir, trace=trace)
        if code == EXIT_ADMITTED:
            _clear_notify_wave(lock_dir)
        elif code == EXIT_AWAIT_TIMEOUT and out.get("source") == AWAIT_SOURCE_TIMEOUT \
                and max_wait >= AWAIT_MAX_WAIT_S and trace["polled"] and trace["wave"] is not None \
                and _active_wave(exhausted_path, clock()) == trace["wave"]:
            # Fix round 2 (item 5): a FULL wait timed out -- mark the wave, so no later seat waits for it again.
            # User-scoped round (item 4): the wave marked is the one this wait WAITED ON (captured at its start,
            # or opened by its first probe), and only while that same wave is still active -- fix round 2 read
            # the active wave after the wait and could mark a NEW record's, taking its full wait away.
            # (Item 8, Opus N2): only a FULL wait marks -- max_wait at least AWAIT_MAX_WAIT_S and at least one
            # poll cycle run; a short --max-wait, or a first probe that ran to the deadline, marks nothing.
            _mark_timed_out(lock_dir, trace["wave"], clock())
        if locked:
            try:
                _atomic_json(result_path, {"finished_at": clock(), "code": code, "result": out})
            except Exception:  # noqa: BLE001 - a joiner then runs its own wait
                pass
        return code, out


def _joined(joined: Tuple[int, Dict[str, Any]], start: float, clock) -> Tuple[int, Dict[str, Any]]:
    code, result = joined
    out = dict(result)
    out.update(joined=True, probes=0, waited_s=int(round(max(0.0, clock() - start))))
    return code, out


def _active_wave(exhausted_path, now_epoch: float) -> Optional[List[float]]:
    record = read_exhausted(path=exhausted_path)
    if record is None or record["exhausted_until"] <= now_epoch:
        return None
    return record_wave(record)


def _await_reset_locked(*, project_root, start, deadline, poll, margin, clock, sleep, probe, sessions_dir,
                        budget_path, key, exhausted_path, state_dir,
                        trace=None) -> Tuple[int, Dict[str, Any]]:
    """await_reset()'s wait itself, once the account's await lock is held (or could not be taken).

    `trace` (user-scoped round, items 4 and 8) is filled for the caller: `wave`, the exhausted record's wave
    this wait waited on (the active one at the start, else the one its first probe opened), and `polled`,
    whether a probe ran after the immediate first one (a poll cycle)."""
    if trace is None:
        trace = {}
    trace.setdefault("wave", None)
    trace.setdefault("polled", False)
    try:
        model: Optional[str] = probe_model()
    except Exception:  # noqa: BLE001 - the row then names no model; the probe itself reports the failure
        model = None
    cap = [PROBE_HARD_CAP_S]
    if probe is None:
        def probe():
            return run_probe(model=model, sessions_dir=sessions_dir, hard_cap_s=cap[0],
                             exhausted_path=exhausted_path)
    snap, limits = _scan(sessions_dir, start)
    token, _where, advice = _quota_state(snap, limits, start, exhausted_path=exhausted_path)
    if advice is None:
        advice = reset_advice(snap, limits, UNAVAILABLE_QUOTA_EXHAUSTED, start)
    resets_at = advice["resets_at"]
    probes = 0
    errors = 0
    wave = _active_wave(exhausted_path, start)
    trace["wave"] = wave
    already_timed_out = wave is not None and _timed_out_wave(state_dir) == wave

    def done(code: int, available: bool, source: str) -> Tuple[int, Dict[str, Any]]:
        out = {"available": available, "waited_s": int(round(max(0.0, clock() - start))), "probes": probes,
               "source": source}
        out.update(advice)
        return code, out

    def one_probe() -> Optional[Tuple[int, Dict[str, Any]]]:
        nonlocal probes, errors
        left = deadline - clock()
        if left < PROBE_MIN_LEFT_S:
            # Fix round 2 (m3): too little time for a probe: time out rather than overrun --max-wait.
            return done(EXIT_AWAIT_TIMEOUT, False, AWAIT_SOURCE_TIMEOUT)
        probes += 1
        trace["polled"] = probes >= 2          # a probe after the immediate one: a poll cycle ran
        cap[0] = min(PROBE_HARD_CAP_S, int(math.floor(left)))
        started = clock()
        outcome, exit_code = probe()
        if outcome not in PROBE_OUTCOMES:
            outcome = PROBE_ERROR
        try:
            record_probe(outcome, project_root=project_root, model=model,
                         exit_code=exit_code, key=key, now=clock(), budget_path=budget_path,
                         sessions_dir=sessions_dir)
        except ValueError:
            pass
        if outcome == PROBE_AUTH:
            return done(EXIT_AWAIT_AUTH, False, AWAIT_SOURCE_AUTH)
        if outcome == PROBE_CLI_MISSING:
            return done(EXIT_ERROR, False, AWAIT_SOURCE_CLI_MISSING)
        if outcome == PROBE_ERROR:
            errors += 1
            if errors >= AWAIT_PROBE_ERROR_LIMIT:
                return done(EXIT_AWAIT_PROBE_ERROR, False, AWAIT_SOURCE_PROBE_ERROR)
            return None
        errors = 0
        now_epoch = clock()
        if outcome == PROBE_EXHAUSTED:
            fresh, fresh_limits = _scan(sessions_dir, now_epoch)
            meter = _unavailable_from(fresh, fresh_limits, now_epoch)
            reset = reset_advice(fresh, fresh_limits, meter, now_epoch)["resets_at"] if meter else None
            record_exhausted(reset, source="probe", binding_window=advice.get("binding_window"), now=now_epoch,
                             path=exhausted_path)
            return None
        # available: codex answered. Minor 1 -- it counts only when the meter clears: a reading NEWER than
        # this probe that is still at or over EXHAUSTED_PERCENT keeps polling.
        fresh, _fresh_limits = _scan(sessions_dir, now_epoch)
        headroom = _reading_headroom_since(fresh, started - 1, advice.get("binding_window"))
        if headroom is False:
            return None
        # Fix round 2 (item 1): retire, never blindly clear -- a signal newer than this probe survives.
        retire_exhausted(started, path=exhausted_path)
        early = headroom is True and resets_at is not None and now_epoch < resets_at
        return done(EXIT_ADMITTED, True, AWAIT_SOURCE_USER_RESET if early else AWAIT_SOURCE_RESET)

    finished = one_probe()
    if trace["wave"] is None:
        trace["wave"] = _active_wave(exhausted_path, clock())    # the record the first probe opened
    if finished is not None:
        return finished
    if already_timed_out:
        # Fix round 2 (item 5, N4): this record's full wait already timed out. The one probe above would have
        # seen a reset; the seat goes straight to its stand-in, with no second 30-minute wait.
        return done(EXIT_AWAIT_TIMEOUT, False, AWAIT_SOURCE_TIMED_OUT_FOR_RECORD)
    if advice["wait_advice"] == WAIT_ADVICE_WAIT and resets_at is not None:
        target = min(resets_at + margin, deadline)
        pause = target - clock()
        if pause > 0:
            sleep(pause)
        finished = one_probe()
        if finished is not None:
            return finished
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            finished = done(EXIT_AWAIT_TIMEOUT, False, AWAIT_SOURCE_TIMEOUT)
        else:
            sleep(min(poll, remaining))
            finished = one_probe()
        if finished is not None:
            return finished


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # exit 3, not argparse's 2 (plan WP-R03 CLI contract)
        self.print_usage(sys.stderr)
        raise _UsageError(message)


def _format_percent(value) -> str:
    return f"{value:g}%" if value is not None else "?"


def _human_snapshot(snap: Dict[str, Any]) -> str:
    if snap["state"] == STATE_UNKNOWN:
        return f"codex-quota: unknown ({snap.get('reason')})"
    return (f"codex-quota: 5h {_format_percent(snap['primary_used_percent'])} / weekly "
            f"{_format_percent(snap['secondary_used_percent'])} ({snap['state']})")


#: ASCII only: argparse prints this to consoles that may be cp1252.
_CYCLE_ID_HELP = """\
Print the per-cycle astra budget key for a project (the id only).

Precedence, first match wins:
  1. .forge/cycle-id - forge writes a fresh id there at Step 1 of every cycle and
     deletes it at close-out (Step 6: Collect Results, after the results are
     presented). Used only when it is a valid id and at most 24h old.
  2. adhoc-<UTC YYYYMMDD>-<first 7 hex of .forge/cycle-base>
  3. adhoc-<UTC YYYYMMDD>-nobase

A cycle-id older than 24h counts as absent (an abandoned session never reached
close-out). Failure direction: a cycle longer than 24h gets a fresh budget
mid-cycle (slightly more astra), never refusals from a finished cycle's budget.

.forge/session-id is NOT used: it is the contract-signing id, minted once and
never re-minted (gates.py G1 compares signed payloads against it), so a budget
keyed on it never rolled over. This command only reads files.
"""


#: ASCII only, like _CYCLE_ID_HELP (#282 r15).
_ADMIT_HELP = """\
Decide one intended codex call against the astra budget and print the decision as
JSON.

CHECK-ONLY BY DEFAULT: without --record this command writes nothing - no row, no
budget store, no store directory, no .lock - and reads the budget without the lock.
Running it before `seat_model.py argv --use` therefore can never charge the budget
twice. The decision says "recorded": false and carries admission_id null.

The recording path for a pinned codex call is
  seat_model.py argv --role R --provider codex --use U [--project-root P]
(admit + pin, ONE row). Pass --record only when this command IS the gate for the
call (the low-level form): it appends one row, admitted OR refused.

Exit codes, identical in both modes: 0 admitted, 10 refused (the decision's reason
says why), 3 usage or environment error - budget_store_unavailable included (a budget
that cannot be read or recorded cannot be enforced).
"""


#: ASCII only, like _CYCLE_ID_HELP.
_CLASSIFY_HELP = """\
Classify one finished TOP codex call. Prints "<action> <reason>" ("-" when there is
no reason) and exits 0; exit 3 is a usage or environment error (nothing printed).

Actions, first match wins:
  gap codex_error              exit 112 (codex_watch's runaway cap), not timed out: a gap on
                               every attempt, whatever stderr says
  ok -                         exit 0, usable output, not timed out
  substitute cli_missing       exit 127 (command not found)
  substitute quota_exhausted   429 / usage limit / rate limit exceeded / Quota exceeded /
                               rate_limit_reached_type on a codex error line, or on any
                               line while the meter says rate_limit_reached or
                               quota_exhausted
  substitute auth_failure      an auth failure on a codex error line
  retry capacity               attempt 1: "Selected model is at capacity" on a codex
                               error line
  substitute capacity_twice    the same on attempt 2 or later
  retry timeout|malformed      attempt 1 timed out, or exit 0 with empty output
  substitute timeout_twice|malformed_twice   the same on attempt 2 or later
  gap codex_error              any other non-zero exit (a harness or usage fault)

A codex error line starts "ERROR: " or "<ISO-8601>Z ERROR codex_<module>: ". codex copies
tool output and the prompt onto the same stderr, so the same words on any other line are
not proof. The meter is read ONCE, after the call (codex_quota unavailable()), and only
corroborates a quota phrase. A reviewed file whose own line starts "ERROR: " can still
forge a codex error line (a recorded limit). The usage-limit line shape is unobserved.

retry  = re-run ONLY the codex exec line, same model, same admission.
substitute = run the seat as a fresh-context Claude agent (seat_model.py substitute).
gap    = the existing CODEX_GAP / NO_SHOW line.

--timed-out    pass it when the call was killed by a timeout (GNU timeout exits 124).
--output-file  the call's output; missing or blank means empty output. Without it
               the output is not judged.
--prompt-file  the prompt as passed to codex: codex echoes it on stderr, and anything
               inside that echo (evidence mentioning 429, say) is ignored. Pass it.
"""


#: ASCII only, like _CYCLE_ID_HELP (#322).
_AWAIT_RESET_HELP = """\
Wait until codex can serve a seat again after a quota refusal (seat_model.py argv --use exit 3
with a wait_advice line), probing it. Prints ONE final JSON line:
  {"available": bool, "waited_s": n, "probes": k, "source": "reset|user_reset|timeout|..."}

  1. Probe at once: an auth failure exits 5 without waiting (run `codex login`), a codex that
     already answers exits 0.
  2. wait_advice wait (the reset is at most 20 minutes away): sleep until the reset time plus
     --margin, then probe once.
  3. Otherwise (notify: the user was told and may reset the plan by hand), probe every --poll
     seconds until --max-wait has passed.

The probe is one trivial `codex exec` on the codex support tier at low effort, NOT --ephemeral,
so its rollout refreshes the meter. Each probe is recorded as a budget-store row with
use "probe"; it spends no budget. source user_reset = codex answered before its reset time.

A probe that answers counts only when the meter clears: a newer reading still at 99% or more keeps
polling, and user_reset needs a newer reading below 99% before the reset time. Each probe's runaway
cap is the time left (at most 300 s); with under 5 s left no probe runs and the wait times out.
ONE await-reset per account (codex quota is account-wide; the lock is in ~/.claude/state): a
second caller joins the running one and prints its result with "joined": true. ONE full wait per
exhausted record: once a wait for a record has timed out, a later await-reset for the same record
probes once (a reset by hand is still seen) and otherwise exits 4 at once with source
timed_out_for_record -- stand in, do not notify again. --cycle-id puts the seat's budget key on
the probe rows.

RUN IT IN A BACKGROUND Bash call: the default wait is 30 minutes, far past the 600 s cap of a
foreground call. Exit codes: 0 available, 4 still exhausted at --max-wait (serve the seat with
the Claude stand-in: seat_model.py substitute --reason quota_exhausted_timeout), 5 auth failure,
6 three probes in a row failed for a non-quota reason (stand in with --reason quota_probe_error),
3 usage or environment (the codex CLI is missing: stand in with --reason cli_missing).
"""


#: ASCII only, like _CYCLE_ID_HELP (#322 fix round 1, minor 4).
_NOTIFY_CLAIM_HELP = """\
Claim the ONE push notification of a quota-refusal wave. Parallel seats refused together each
see wait_advice=notify; only the first should tell the user. Prints "notify" and exits 0 when
this caller sends the notification, or "skip" and exits 10 when another seat of the same wave
already claimed it. The claim is ACCOUNT-WIDE (~/.claude/state, beside the exhausted record) and
keyed on the active exhausted record: it holds for that record's whole life, and a new record
starts a new wave. It ends when the record clears (codex answers again with headroom). With no
record it holds 30 minutes. A store that cannot be read or written prints "notify" (a duplicate
beats a miss). --project-root is accepted and ignored.
"""


class _FileTooLarge(Exception):
    pass


def _read_capped(path, limit: int) -> str:
    """The whole file as text (utf-8, replacement), or _FileTooLarge beyond `limit` bytes."""
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise _FileTooLarge(f"{path} is larger than {limit} bytes")
    return data.decode("utf-8", errors="replace")


def _output_is_usable(path) -> bool:
    """Non-blank content within the first OUTPUT_PROBE_BYTES; a missing or unreadable file is empty."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(OUTPUT_PROBE_BYTES)
    except OSError:
        return False
    return bool(data.strip())


def _cli_classify(args) -> int:
    if args.attempt < 1:
        print("codex_quota.py: error: --attempt must be >= 1", file=sys.stderr)
        return EXIT_ERROR
    try:
        stderr = _read_capped(args.stderr_file, CLASSIFY_READ_BYTES) if args.stderr_file is not None else None
        prompt = _read_capped(args.prompt_file, CLASSIFY_READ_BYTES) if args.prompt_file is not None else None
    except (OSError, _FileTooLarge) as exc:
        print(f"codex_quota.py: error: cannot classify: {_ascii(exc)}", file=sys.stderr)
        return EXIT_ERROR
    output_ok = _output_is_usable(args.output_file) if args.output_file is not None else True
    # #282 R2: ONE corroboration, built after the files are read (the call has finished) and
    # only for a call that did not succeed — a successful call reads nothing extra.
    succeeded = not args.timed_out and args.exit_code == 0 and output_ok
    corroboration = None if succeeded else corroboration_for(stderr, prompt)
    action, reason = classify_codex_failure(args.exit_code, stderr, timed_out=args.timed_out,
                                            output_ok=output_ok, attempt=args.attempt, prompt=prompt,
                                            corroboration=corroboration)
    if action == ACTION_SUBSTITUTE and reason == UNAVAILABLE_QUOTA_EXHAUSTED:
        # #322 fix round 1 (F1): a quota stop persists the exhausted-until record. The reset time is the
        # meter's when it names one, else the one codex's own text names ("try again at 1:50 AM").
        try:
            now_epoch = time.time()
            snap, limits = _scan(None, now_epoch)
            meter = _unavailable_from(snap, limits, now_epoch)
            advice = reset_advice(snap, limits, meter, now_epoch) if meter else {}
            reset = advice.get("resets_at") or retry_at_from_text(_without_prompt_echo(stderr, prompt), now_epoch)
            record_exhausted(reset, source="classify", binding_window=advice.get("binding_window"), now=now_epoch)
        except Exception:  # noqa: BLE001 - the verdict line is the contract; the record is best effort
            pass
    print(f"{action} {reason or '-'}")
    return 0


def _ascii(value: Any) -> str:
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="codex_quota.py", description="Codex rate-limit meter and astra budget.")
    sub = parser.add_subparsers(dest="command")
    snap = sub.add_parser("snapshot", help="print the newest rate-limit reading")
    snap.add_argument("--json", action="store_true", help="print the snapshot as JSON")
    adm = sub.add_parser("admit", help="decide one intended codex call; check-only unless --record",
                         description=_ADMIT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    adm.add_argument("--use", required=True, choices=sorted(USES))
    #: THE BUDGET KEY. Kept as --cycle-id (the design calls the field `key`) because the
    #: prose call sites that cannot import Python already pass this flag by name.
    adm.add_argument("--cycle-id", required=True, help="the budget key for this use")
    adm.add_argument("--project-root", default=None)
    adm.add_argument("--task-key", default=None,
                     help="diagnosis (per escalated WP) and exhausted_review (per D21 review id, required) only")
    adm.add_argument("--size", default=None, choices=list(SIZES),
                     help="the size this call RESOLVED to (seat_model resolves it; this records it)")
    adm.add_argument("--size-source", default=None, choices=sorted(SIZE_SOURCES),
                     help="where that size came from; required with --size, refused without it")
    adm.add_argument("--model-class", default=None, choices=sorted(MODEL_CLASSES),
                     help="top (astra) or std (the std/support tiers): which budget this call spends (default: top)")
    adm.add_argument("--requested-model", default=None, help="the codex model this call would run")
    adm.add_argument("--user-request", action="store_true",
                     help="the user asked for the top model: records requested_by user")
    adm.add_argument("--record", action="store_true",
                     help="append the decision to the budget store as one row (default: check-only, writes nothing)")
    cyc = sub.add_parser("cycle-id", help="print the budget key for a project",
                         description=_CYCLE_ID_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    cyc.add_argument("--project-root", default=None, help="project root (default: the working directory)")
    cls = sub.add_parser("classify", help="classify one finished TOP codex call",
                         description=_CLASSIFY_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    cls.add_argument("--exit-code", required=True, type=int, help="the codex call's exit status")
    cls.add_argument("--attempt", required=True, type=int, help="1 for the first call, 2 for the retry")
    cls.add_argument("--timed-out", action="store_true", help="the call was killed by a timeout")
    cls.add_argument("--stderr-file", default=None, help="the call's captured stderr")
    cls.add_argument("--output-file", default=None, help="the call's output (-o file)")
    cls.add_argument("--prompt-file", default=None, help="the prompt passed to codex")
    aw = sub.add_parser("await-reset", help="wait until codex is usable again after a quota refusal (#322)",
                        description=_AWAIT_RESET_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    aw.add_argument("--max-wait", type=float, default=float(AWAIT_MAX_WAIT_S),
                    help=f"seconds to wait in all (default {AWAIT_MAX_WAIT_S})")
    aw.add_argument("--poll", type=float, default=float(AWAIT_POLL_S),
                    help=f"seconds between probes while waiting for a far reset (default {AWAIT_POLL_S})")
    aw.add_argument("--margin", type=float, default=float(AWAIT_MARGIN_S),
                    help=f"seconds past a near reset before the confirming probe (default {AWAIT_MARGIN_S})")
    aw.add_argument("--project-root", default=None, help="the project whose budget store records the probes "
                                                         "(default: the working directory)")
    aw.add_argument("--cycle-id", default=None,
                    help="the seat's budget key: the probe rows carry it (default: the project's cycle id)")
    nc = sub.add_parser("notify-claim", help="one push notification per quota-refusal wave (#322)",
                        description=_NOTIFY_CLAIM_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    nc.add_argument("--project-root", default=None, help="the project whose budget store holds the wave "
                                                         "(default: the working directory)")
    return parser


def _cli_await_reset(args, project_root) -> int:
    try:
        if args.cycle_id is not None and not CYCLE_ID_PATTERN.fullmatch(args.cycle_id):
            raise ValueError(f"--cycle-id {args.cycle_id!r} is not a usable budget key")
        code, result = await_reset(project_root=project_root, max_wait=args.max_wait, poll=args.poll,
                                   margin=args.margin, key=args.cycle_id)
    except ValueError as exc:
        print(f"codex_quota.py: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if code == EXIT_AWAIT_AUTH:
        print("codex_quota.py: codex auth failure, not quota: run `codex login` (nothing was waited for)",
              file=sys.stderr)
    elif code == EXIT_ERROR:
        print("codex_quota.py: the codex CLI is missing; nothing to wait for", file=sys.stderr)
    elif code == EXIT_AWAIT_PROBE_ERROR:
        print(f"codex_quota.py: {AWAIT_PROBE_ERROR_LIMIT} probes in a row failed for a non-quota reason; "
              f"stand in with --reason {REASON_QUOTA_PROBE_ERROR}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=True))
    return code


def main(argv=None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            parser.print_usage(sys.stderr)
            raise _UsageError("a subcommand is required")
    except _UsageError as exc:
        print(f"codex_quota.py: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.command == "snapshot":
        snap = snapshot()
        print(json.dumps(snap, ensure_ascii=True) if args.json else _human_snapshot(snap))
        return 0
    if args.command == "classify":
        return _cli_classify(args)

    project_root = args.project_root if args.project_root is not None else os.getcwd()
    if args.command == "await-reset":
        return _cli_await_reset(args, project_root)
    if args.command == "notify-claim":
        first = notify_claim(project_root=project_root)
        print("notify" if first else "skip")
        return EXIT_ADMITTED if first else EXIT_REFUSED
    if args.command == "cycle-id":
        print(cycle_id_for(project_root))
        return 0

    try:
        decision = admit(args.use, args.cycle_id, project_root=project_root, task_key=args.task_key,
                         size=args.size, size_source=args.size_source,
                         model_class=args.model_class, requested_model=args.requested_model,
                         requested_by=REQUESTED_BY_USER if args.user_request else None,
                         record=args.record)
    except ValueError as exc:
        print(f"codex_quota.py: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(decision, ensure_ascii=True))
    if decision["admitted"]:
        return EXIT_ADMITTED
    if decision["reason"] == "budget_store_unavailable":
        print(f"codex_quota.py: budget store unavailable: {decision.get('error')}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_REFUSED


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
