#!/usr/bin/env python3
"""seat_model.py - the role table: which model serves which seat, and why.

S081 design s4.2 (role table), s4.3 (auto-follow and the safety that replaces "never
auto-apply"), s4.4 (protected roles); plan interpretations I4, I5, I6, I13, I17, I21.
Amendment 1 D6 item 2 (revision 2b; J10, J11, J12): astra unavailable -> a Claude substitute.

WHY THIS EXISTS. Model choice for review, consultancy and escalation seats was spread
over smart-config (which merges a REPO-LOCAL policy file, so any clone could downgrade
the reviewer reviewing it - design L1), unvalidated env variables (L2), hardcoded slugs
and silent inheritance of whatever the codex TUI or the agy account last selected.
This module is the one place those seats are resolved. It is a git-tracked Python
literal, installed with the harness, and it reads ONLY home-tier inputs.

THE SURFACE
  ROLE_TABLE          role x provider -> selector (design s4.2, exactly)
  resolve()           -> SeatPin{model, effort, timeout, argv_fragment, provenance}
  emit()              every pin with provenance (workflow `args.models`, the digest)
  substitute()        serve a budgeted codex seat (ADMITTED_ROLES) with its Claude row and record the
                      substitution
  role_table_violations()
                      the astra-reserve invariant (roster rev 4): ROLE_TABLE against
                      model_roster.CODEX_TOP_ROLES, checked at import (fail closed)
  NoEligibleModelError
                      the fail-closed "no eligible codex TOP" error (a SeatModelError)
  is_top()            is this seat a TOP selector? (I6 as amended by #302 JC-3: --ephemeral no
                      longer depends on it - every codex call that resolves a seat here, TOP
                      and support alike, runs WITHOUT --ephemeral so it leaves a rollout)
  pin_model_class()   which budget class a resolved codex pin spends (#302: by row and tier)
  is_agy_family()     the agy family rule (model_roster.AGY_FAMILY), in code
  CLI                 `argv --role R --provider codex|agy`, `model --role R --provider
                      claude`, `effort --role R --provider claude` (#311: the Claude seat's
                      reasoning effort, one word), `emit --json`, `timeout --role R --provider
                      codex`. Fail-closed:
                      ANY failure -> non-zero exit AND EMPTY stdout, so `PIN="$(...)" && codex
                      exec $PIN ...` never runs unpinned.
                      An INVALID codex roster is such a failure (#282 R4): `argv --provider
                      codex`, `timeout` and `emit --json` exit 1 with empty stdout where they
                      printed the harness literal before; `model` is Claude-only and reads no roster.
                      `timeout` (#282 r12) prints ONE integer, the resolved codex pin's timeout in
                      seconds (codex_model.timeout_for owns the number): the same fail-closed
                      resolution as `argv` without --use, so any failure, no eligible TOP
                      included, is exit 1 (never a substitution: it admits nothing); a seat
                      without a codex row, or --provider agy|claude, is exit 2. It is a
                      subcommand of its own and never a second `argv` stdout line, because a
                      caller word-splits `$PIN` into `codex exec $PIN` and an extra line would
                      become a prompt positional. The codex_top_seat blocks call it only after
                      `argv --use` exited 0.
                      Plus the astra pair below (ASTRA UNAVAILABLE).
                      `check [--home] [--root DIR]` (#291 design s3.3) validates the roster
                      and everything that resolves through it WITHOUT a model call - see
                      THE CHECK below. It is the one subcommand whose stdout is a report.

THE CHECK (#291 design s3.3). `seat_model.py check [--home] [--root DIR]` validates the roster
and everything that resolves through it - roster invariants, `emit --json` at every size, every
shipped avengers profile's --dry-run, the smart-config tiers, a benched-literal lint, and with
--home the installed copy plus drift - each item in a fresh subprocess under a temporary HOME,
with no model call. The machinery lives in seat_model_check.py, because validation spawns and
THIS module never does (it imports no process or network library). Exit 0 all pass / 1 any
failure (each named on a FAIL line) / 2 usage.

ASTRA UNAVAILABLE (amendment 1 D6; J10). A budgeted codex seat (ADMITTED_ROLES: code_reviewer,
consultant_main, arbiter, escalation - gated on the ROLE, never on the row kind, since the astra reserve
made consultant_main and arbiter Sol literals, F1) that codex cannot serve is served by a FRESH-context
Claude agent on the role's Claude row (the roster's Claude main tier), never by a codex std/support model
or any other codex model (every codex model draws the same plan quota). On a Sol literal "cannot serve"
includes a valid roster that does not list Sol at the seat's effort (no_eligible_model). Two CLI forms,
one output shape (plus the TOP retry below):
  argv --role R --provider codex --use U [--project-root P] [--cycle-id C] [--task-key K]
      admit-and-pin in one call. In order: (1) resolve the codex pin fail-closed - no
      eligible TOP -> substitute `no_eligible_model`, any other failure -> exit 1 with
      NOTHING recorded; (2) the codex binary on PATH (shutil.which, J12) - absent ->
      substitute `cli_missing`, no admit; (3) codex_quota.admit(U) - admitted -> exit 0
      and the pin; refused -> substitute with admit's reason. An admitted audit that
      carries `unavailable` is substituted too, as audit_spawn does (J13), and its
      substitution row names that admission's `admission_id` (#282 r10: the audit is then
      netted out of the TOP-call counts; only when the admit row was written). A refusal
      and a plan-time substitution name none.
  substitute --role R --use U --reason REASON [--project-root P] [--cycle-id C]
             [--requested-model M]
      the call-time form (after codex_quota.classify says substitute): records one row,
      which names no admission (a prose call site cannot learn one; #282 K12).
  Exit codes: 0 = admitted, stdout the pin (the `argv` shape, unchanged);
              3 = substitute (EXIT_SUBSTITUTE): stdout line 1 the reason token, line 2 the
                  Claude alias to spawn - never a pin, so `&&` never runs codex. #322: a QUOTA
                  refusal (rate_limit_reached / quota_exhausted) appends key=value lines AFTER
                  those two, byte-identical lines: binding_window=, resets_at=, resets_in_s= (each
                  only when known) and wait_advice=wait|notify. Read the model as LINE 2, never
                  as the last line. With --await-quota such a refusal records NO substitution
                  row and ends with use=, key=, requested_model= and `substitution=deferred`
                  (#322 fix round 1; a --top-retry refusal too): the caller waits
                  (codex_quota.py await-reset), re-admits once, and when the wait ends without
                  codex records the stand-in with `substitute --use <use> --cycle-id <key>
                  --requested-model <requested_model> --reason quota_exhausted_timeout` (exit 4),
                  `quota_probe_error` (exit 6) or `cli_missing` (exit 3);
              10 = the seat is skipped (EXIT_SKIPPED): the astra trial or the exhausted-loop
                  review (SKIPPED_USES) refused or unavailable, EMPTY stdout, never substituted
                  (an admit refusal row is still recorded);
              1 = broken resolver (an invalid freeze pin is NOT "unavailable"), empty stdout;
              2 = usage: --use on an agy seat or on consultant_support (the support tier, not
                  astra), an unknown use, --use escalation / exhausted_review off the escalation
                  role, --task-key off diagnosis / exhausted_review (which REQUIRES it), --use
                  top_retry without --top-retry, blank values, empty stdout.
  argv --role R --provider codex --use U --await-quota
      #322: see exit 3 above - a quota refusal defers its substitution row to the wait's outcome.
  argv --role R --provider codex --use U --receipt-file F
      on an admission (exit 0) also writes `<admission_id> <key>` to F: the seat's receipt.
  argv --role R --provider codex --use U --top-retry --failed-admission-id ID
       --failed-reason capacity_twice|malformed_twice [--cycle-id ORIGIN_KEY] [--receipt-file F]
      THE ASTRA RESERVE U2/F3: the ONE TOP attempt for a seat that failed on CAPABILITY. ID must be an
      ADMITTED std-class row of R and U on the originating key (without --cycle-id: the row's OWN key) and
      the same --task-key, not already named by a top_retry event (read under the store lock: one failed
      attempt, one retry, ever; a `pending` event permits ONE resumption, and a `top_retry` stand-in on its
      key and role closes it), else exit 2 with NOTHING written in the store. The attempt is then RESERVED
      (codex_quota.claim_top_retry: the replay check and the reservation in one locked step, so two
      concurrent resumers cannot both pass); the failed model is read from it, and
      the seat is judged by it (a failed model the roster now ranks TOP is no retry). A TOP admission
      whose --receipt-file cannot be written is a failure (exit 1); the receipt is written atomically. A seat whose own pin bills TOP, a TOP pin equal to the failed one, one
      that bills std, or a FREEZE onto a model the roster does not rank TOP is no retry -> exit 3 D6 for
      the ORIGINAL failure on U. Otherwise it is admitted as use `top_retry` on the FORGE CYCLE key (top 1
      per cycle, whatever U or its key) and one `top_retry` EVENT row names both keys and ID (never a
      substitution row, never netted). Quota, auth, budget, timeout and gap reasons are a usage error
      (exit 2): account problems, not capability. The trial and the exhausted-loop review are never an
      origin. `timeout --role R --provider codex --top-retry` prints that TOP pin's timeout (the recipe
      asks it BEFORE the retry, so a failed lookup spends no slot).
  Every printed token passes _shell_safe. A budget-store failure never blocks the
  substitute: exit 3 still prints both lines and stderr says the row was not recorded.

SIZE (D16, D22; S081 revision 4; narrowed by the astra reserve, roster rev 4). `argv`, `emit` and
`timeout` take `--size light|medium|complex [--user-request]`. The ONE sized seat is code_reviewer
(SIZED_ROLES): light/medium serve the std tier (model_roster.CODEX_STD), complex and --user-request
serve TOP. THE EFFORT NEVER MOVES with the size: a size chooses WHICH MODEL serves the seat, never how
hard it thinks. consultant_main and arbiter are the CODEX_STD literal @ xhigh at every size (an explicit
--user-request still promotes consultant_main to TOP: USER_PROMOTED_ROLES, F7), escalation is TOP @ max
at every size (the reserve's purpose), and consultant_support is the support tier - all ACCEPT a size
and ignore it, and `model` (Claude-only) takes no --size at all.

  AGY (#367 WP-C, roster rev 7). `argv --provider agy` and `emit` take the same flags. A sized agy
  call serves the level model_roster.AGY_LEVEL_BY_SIZE maps its size to (light -> low, medium ->
  medium, complex -> high) on EVERY agy role, and --user-request serves high; unsized, the row's level
  stands (consultant_main / arbiter high, consultant_support medium). The agy level is part of the
  model slug (gemini-<v>-<fam>-<level>), so the size still chooses WHICH MODEL serves, never an effort.
  A sized agy pin records size / size_source (+ requested_by) like a sized codex seat, and every emit
  carries the map as its top-level `agy_level_by_size`.

  WHERE THE SIZE COMES FROM (L7), resolved ONCE in resolve_size() and nowhere else:
    1. an explicit --size argument, or the routing class the main loop passes  -> routing
    2. inside a forge cycle, <root>/.forge/size, first line, light|medium|complex -> forge
       Forge's size WINS over the caller's, and a genuine conflict between the two
       resolves to the LARGER of them. Junk, a missing file or an unreadable one is
       treated as ABSENT, never as a failure.
    3. --user-request: serve TOP whatever the size            -> user, requested_by: user
    4. review_risk promotion of a risky change set to complex -> risk
       Upward only, and `risk` only when the size actually moved. The contract lives in
       review_risk.assess and is NOT reimplemented here.
    5. nothing supplied -> complex                            -> default
  The LAST source to speak wins, and the list is written in that order: default is the
  floor, routing/forge set it, then user and risk can only raise what serves the seat.

  BACK-COMPAT, and why `emit --json` is pinned. A call that passes no size input at all
  resolves EXACTLY as it did before D16 - same model, same provenance keys - so every
  un-migrated call site keeps working. SIZING IS OPT-IN on every subcommand: without
  --size or --user-request, `argv`, `timeout`, `emit` and `substitute` read NO `.forge/size`
  at all. With one, `.forge/size` joins the order above, read from --project-root when the
  call has one (`argv --use` and `substitute`, where that root also keys the budget and
  names the store - S081 rev 4 D21 f6) and from the WORKING DIRECTORY otherwise. `emit` is
  the REGISTRY DUMP and stays size-blind unless a size is asked for, which is what keeps
  the default document byte-identical. A SIZED emit gains exactly one top-level pair,
  `size` / `size_source`, and the sized seats' provenance gains `size`, `size_source` and
  (for --user-request) `requested_by`.

THE ROLE TABLE (timeouts: claude / codex / agy; codex column since the astra reserve, roster rev 4)
  code_reviewer       MAIN @ xhigh     TOP @ xhigh (complex;   -                600 / floor / -
                                       CODEX_STD light/medium)
  consultant_main     MAIN @ xhigh     CODEX_STD @ xhigh       TOP-<fam>-high   600 / floor / 600
  consultant_support  SUPPORT @ medium CODEX_SUPPORT @ medium  TOP-<fam>-medium 600 / floor / 600
  arbiter             MAIN @ xhigh     CODEX_STD @ xhigh       TOP-<fam>-high   1200 / floor / 600
  escalation          MAIN @ xhigh     TOP @ max               -                1200 / floor / -
<fam> is model_roster.AGY_FAMILY (roster rev 6: argon), so the agy cells read TOP-argon-high / -medium.
Those are the UNSIZED levels; a sized call serves model_roster.AGY_LEVEL_BY_SIZE[size] (rev 7, see SIZE).
The codex TOP rows are exactly model_roster.CODEX_TOP_ROLES ("code_reviewer@complex", "escalation"): the
astra reserve. role_table_violations() checks the table against that field at import, so a reserve change
is a roster revision (docs/model-roster-swap.md, "Reserving a codex model"). A home-tier FREEZE reaches the
TOP rows only (F8): the Sol literals never read it.
The Claude effort (#311, U3) is the level the seat is DISPATCHED at: passed explicitly as
workflow `agent({effort})` or headless `--effort`, never left to agent frontmatter.
The Claude column, CODEX_STD (the sized light/medium main seats) and CODEX_SUPPORT are TIERS
(#291, #302). Their current values live in model_roster.py (CLAUDE_MAIN, CLAUDE_SUPPORT,
CODEX_STD, CODEX_SUPPORT; REVISION and HISTORY record every
swap) - read that file, or `emit --json`, for what serves now. A swap edits the roster only
(docs/model-roster-swap.md). Execution is NOT a role: it stays smart-config tiers. A
missing row RAISES; every lookup is strict. Codex timeouts have ONE owner,
codex_model.timeout_for().

THE ROSTER INVARIANTS (#291 design s3.1) are checked when this module is imported:
CLAUDE_MAIN != CLAUDE_SUPPORT, both Claude vendor aliases, CLAUDE_MAIN in
CLAUDE_MAIN_ELIGIBLE, neither benched, CODEX_STD and CODEX_SUPPORT safe slugs, HISTORY[-1] equal
to the live values (a row without `codex_support` reads as its `codex_std`) and REVISION ==
HISTORY[-1]["rev"]. CODEX_STD != CODEX_SUPPORT is NOT an invariant (#302 JC-1): a revert to a
rev-1/2-shaped row must stay legal, so `check` warns instead. A violation raises SeatModelError
at import, so EVERY importer fails closed - audit_spawn and verification_arbiter_spawn included. That is
deliberate: falling open would serve the model the invariant forbids. is_benched() is the one
normaliser for benched families; a benched env value is refused on every Claude seat and the
row value served.

SELECTION (design s4.3, mechanical)
  codex TOP        codex_model.select_top(effort, incumbent=...): lowest-priority entry that is
                   listed, supported_in_api and supports the effort; a populated `upgrade` is
                   followed. Legality stays in the codex adapter. `priority` is the vendor's
                   PICKER ORDER and is NOT stable - gpt-5.6-sol has been observed at priority 4
                   (2026-09-15T14:38:49Z), 1 (20:45:50Z, tied with gpt-6-astra), 4 again
                   (22:25:15Z) and 1 again (22:38:08Z) - so no dated snapshot of it stays true
                   and the tie rules below, not the number, are what hold the seat: whenever the
                   two tie, gpt-6-astra stays TOP by generation. That guard does NOT cover
                   gpt-6-sol (#302): it is astra's own generation, so a tie between those two
                   falls to the incumbent, then slug, and a strict inversion is followed - either
                   way a TOP resolution onto a roster tier model records top_resolved_to_std.
                   A PRIORITY TIE (#282 R16,
                   plan K25-K27) breaks by the higher model generation, then the incumbent,
                   then slug: the incumbent comes from seat-model-tops.json read BEFORE this
                   resolution rewrites it, passed as select_top(incumbent=). It is the record's
                   `priority_winner` when one is written and its `top` otherwise (#282 fix
                   round 1 F10, plan K44) — a FOLLOWED upgrade puts a slug from outside the tie
                   into `top`, so `top` alone would not be found in the next tied set and the
                   tie would fall to slug, silently downgrading off the superseded winner. The
                   record is self-stabilising (a tie decided by incumbent or slug records its
                   winner, the next resolution's incumbent), so no pre-tie key is stored.
  agy TOP-<fam>    the highest numeric version v such that gemini-<v>-<fam>-<level> is in
                   ~/.claude/state/agy-models.json (4.10 > 4.9), <fam> = model_roster.AGY_FAMILY.
                   Only AGY_FAMILY_PATTERN is ever eligible, on EVERY agy output path: roster, freeze, env and
                   harness literal. There is no path around the final check.
  claude           the vendor alias, and the row's effort (#311). The Claude adapter reads no
                   roster and writes nothing.

PRECEDENCE for a TOP selector
  1. freeze   ~/.claude/state/seat-model-pins.json (home-tier only - never env, never a
              project). Wins over the roster for TOP selectors only; the consultant_support
              literal never reads it. An agy freeze fixes the family VERSION and the
              role supplies the level. An INVALID freeze (malformed file or entry, fails
              the agy family rule, not a safe shell word, a codex slug not eligible or an agy slug
              not listed while that roster is readable) takes the call site's failure path.
              A freeze is never silently ignored: ignoring one would silently unfreeze.
  2. roster   fresh -> the selection above. fetched_at older than ROSTER_STALE_AFTER_S (or
              missing / unparseable) -> keep the last TOP recorded in seat-model-tops.json
              when the stale roster still lists it as eligible, else the stale roster's own
              top; both flagged roster_stale.
  3. harness_literal
              codex: NO roster file (absent) -> gpt-6-astra, or the consultant_support literal.
              agy: no usable cache (absent, unreadable, malformed) -> gemini-<AGY_HARNESS_VERSION>-<AGY_FAMILY>-<level>
              (both model_roster values; rev 6: gemini-4-argon-<level>).
              This is a sanctioned path, not a failure (probe.sh is model-invoked, so the agy
              cache can be absent at first use).
  THE CODEX ROSTER HAS THREE STATES (#282 R4, plan K14; codex_model's THREE ROSTER STATES):
    absent       no models_cache.json -> the sanctioned harness literal above, both modes.
    invalid      the file exists but is unreadable, not JSON, or has the wrong shape or field
                 types -> a resolution failure, on TOP and literal codex rows alike: fail_open ->
                 harness literal with `fallback_reason` and the event key `roster_invalid: true`;
                 fail-closed -> SeatModelError naming roster_invalid (never NoEligibleModelError),
                 so the CLI exits 1.
                 THE FREEZE EXCEPTION (#282 fix round 1 F15, plan K47; behaviour UNCHANGED, the
                 accepted K14 rule — this states it). A freeze pin is honoured UNVALIDATED with an
                 invalid roster, exactly as with an absent one, and records `roster_invalid: true`.
                 There is nothing to validate the slug against, and refusing would disarm the
                 freeze at the one moment it matters: it is the operator's EMERGENCY OVERRIDE, and
                 it is what restored gpt-6-astra during the 2026-09-15 vendor priority tie. The
                 exception is the freeze and nothing else — every non-frozen codex path still
                 fails on an invalid roster. convene PERSISTS the `roster_invalid` key on such a
                 seat (the one event key it persists), so a plan frozen against a BROKEN roster
                 stays distinguishable from one frozen against an ABSENT one: both stamp
                 `roster_fetched_at: null`, only one had a file that failed to parse.
    no_eligible  a valid roster that lists NO eligible model -> the failure below.
  A roster that lists NO eligible model is a failure: fail_open -> harness literal with
  `fallback_reason`; fail-closed -> SeatModelError. For a codex TOP that failure is "astra
  unavailable", not a broken resolver: fail-closed raises NoEligibleModelError (a
  SeatModelError subclass) and fail-open provenance adds `unavailable_reason:
  "no_eligible_model"`. Neither happens for "no roster" (sanctioned), an invalid roster or an
  invalid freeze. agy caches keep one "no usable cache" state (unchanged).

ENV (design s4.1.3, s4.4, m1). `env_var=None` skips the layer; an unset or blank value
skips it too. PROTECTED roles accept an override only when it EQUALS the resolved model -
they declare no env fallback, so env can never change a protected seat; operators and the
trial use freeze pins instead. consultant_support accepts a roster-valid codex slug, a
agy slug of the roster's family, or a Claude vendor alias. A refusal is recorded in
provenance.env_override_refused; an acceptance sets source "env".
  SUPPORT CODEX CEILING (#282 r13): for the non-protected codex seat an env slug EQUAL to the
  seat's own base is accepted first (source env). Any other slug must pass the safe-word /
  roster / effort checks and is then REFUSED when it ranks above the consultant_support literal
  (CODEX_SUPPORT, the ceiling) among listed roster entries: visibility "list" with a numeric
  priority strictly lower than the ceiling's ("ranks above <ceiling> among listed roster entries").
  A tie is accepted by the rank rule; a hidden entry is not refused by this rule; when the ceiling
  is not itself a listed, ranked entry every non-base slug is refused; an unreadable roster refuses
  as before. D21 fix round 1 (F1a) adds a TIER refusal independent of priority, so a tie or an
  unranked entry cannot slip through: a non-base slug that is the CURRENT codex TOP resolution
  (freeze included), or is CODEX_STD while the seat's base is not, is refused ("is the current
  codex TOP resolution" / "is CODEX_STD"); an undeterminable TOP refuses. A std == support revert
  stays legal (the base is accepted first).
  Env must not buy an unmetered astra-class model for a seat the budget never counts.

PROVENANCE = {requested_selector, resolved_model (before env), source in SOURCES,
roster_fetched_at, quota_state (codex_quota.snapshot state for codex seats: fresh, stale,
uncertain or unknown; None otherwise)}, plus roster_rev (#291: model_roster.REVISION) on every
Claude resolution and every codex tier resolution (a codex literal row whose slug is CODEX_STD or
CODEX_SUPPORT), plus, only when the event happened: top_resolved_to_std (#302, challenger #4: a
codex TOP selector resolved onto CODEX_STD or CODEX_SUPPORT - a vendor priority inversion or a
freeze onto a tier model; OPTIONAL on read everywhere provenance is projected), roster_stale,
env_override_refused,
fallback_reason, upgrade_followed, upgrade_ignored_reason, unavailable_reason, roster_invalid
(#282 R4: the codex roster file was invalid), roster_entries_skipped (#282 fix round 1 F13: the
sorted slugs codex_model DROPPED from an otherwise valid roster for a field-type fault on an entry
that could never be selected - codex seats only, present only when non-empty, and on every codex
path that read the document: TOP, literal, freeze and the fail-open literal alike, because it
describes the DOCUMENT, not the selection), frozen_slug (#282 r14: the pins-file `top` as written -
for agy the version family or slug the file holds, not the level-resolved model - present exactly
when the FINAL source is "freeze": an accepted env override or a fail-open harness literal is not a
freeze; codex and agy alike), tie_break and tied_with (#282 R16, K25/K27: codex TOP only, present
exactly when the model came from a codex_model.select_top call whose lowest eligible priority was
TIED - tie_break is the rule that decided, "generation" | "incumbent" | "slug", and tied_with the
sorted list of the OTHER tied slugs, which excludes the SERVED model as well as the priority winner
(#282 fix round 1 F14) and so may be EMPTY while a tie happened - tie_break is what says one did;
a freeze, a harness literal and a stale roster's kept TOP call
no tie-break and carry neither; like upgrade_followed they describe the selection, so a protected
env override equal to that model keeps them). convene persists {requested_selector, resolved_model, source,
roster_fetched_at}, frozen_slug and - the ONE event key it persists - roster_invalid (#282 fix round 1
F15, plan K47: in a fail-closed convene only a FROZEN codex seat can carry it, so it marks a freeze
honoured against a roster that never loaded, which a null roster_fetched_at alone cannot distinguish
from an ABSENT roster) into its session plan and run record - NOT roster_entries_skipped,
and audit_spawn's verdict provenance does not carry it either (K30, unchanged by F13). Both
also carry roster_rev (#291) when the pin has it, and both treat it as OPTIONAL on read, so a
plan or record written before #291 still loads. The SERVED
model is the caller's to capture (codex stderr banner); resolved and served are different
facts. substitute() returns the Claude pin's provenance plus {substitute_for,
substitution_reason, requested_model, row_written} (+ row_error when not written).

WRITES. resolve() and emit() write exactly one file, ~/.claude/state/seat-model-tops.json,
atomically (temp + os.replace) and best-effort: a write failure never changes a
resolution. It records, per provider, the last model a TOP selector resolved to (freeze or
roster; a harness literal is not evidence and is not recorded) as
{top, previous, changed_at, resolved_at, roster_fetched_at}, so the digest can announce a
change. A codex record ADDITIONALLY carries tie_break and tied_with (#282 R16) exactly when the
recorded TOP came from a tied selection; a record written for any other resolution omits them, so
stale tie keys are dropped (the digest announces a recorded tie once). It carries priority_winner
(#282 fix round 1 F10, K44) exactly when the slug the priority rules chose DIFFERS from the served
`top`, i.e. an upgrade was followed: that slug, not `top`, is the incumbent the next tie-break
consults. A rewrite leaving `top` unchanged (a freeze, a stale-kept TOP, a repeated resolution)
carries it forward; a rewrite moving `top` without one drops it. For agy `top` is the version family `gemini-<v>-<fam>`: the level belongs to the
role, and recording it would flap between -high and -medium seats. On a STALE roster the
record is never replaced: a seat whose effort/level the kept TOP cannot serve is given the
stale roster's own top, unrecorded, so the next seat still keeps the last TOP.
The astra paths ADDITIONALLY append to ~/.claude/projects/<slug>/astra-budget.jsonl and
create its `.lock` sidecar, through codex_quota and under its lock: `argv --use` writes one
admit row (none when the pin is no-eligible or the CLI is missing) and, on a substitution,
one substitution row; `substitute` and substitute() write one substitution row and
resolve no codex pin, so they never touch the tops record. Nothing else is written.

NO NETWORK, NO SUBPROCESS, NO SMART-CONFIG POLICY, AND AN UNSIZED RESOLUTION NEVER READS
THE WORKING DIRECTORY. Every MODEL input is a home-tier file read: ~/.codex/models_cache.json
(through codex_model), ~/.claude/state/{agy-models,seat-model-pins,seat-model-tops}.json
and the codex sessions tree (through codex_quota). Every path comes from `_paths()`,
which reads Path.home() at CALL time so tests can redirect it. resolve() and emit() load
no smart-config module at all. The astra paths (J11) read a PROJECT ROOT - --project-root,
else the working directory - to derive the budget key (codex_quota.cycle_id_for reads
its .forge/cycle-id / cycle-base) and the budget store path; codex_quota derives the store
slug with smart-config's path-to-slug function (a pure string rule; no policy file is
read). A planted .forge/cycle-id, .claude/model-policy.yaml or roster in that directory can
change the budget key and nothing else: the pin and the substitute model are home-tier.
The ONE project file a resolution reads is `.forge/size`, and only for a call that opted
into sizing (SIZE above: from that same project root, else the working directory); there
it moves a sized main seat between TOP and the std tier, which is that file's whole contract.
The codex binary check is shutil.which (an in-process PATH lookup, J12), not a process.

HONEST LIMITS
  * The tops record is read-modify-write without a lock (a lock file would be a second
    written file). Two concurrent resolutions can lose one update; the next resolution
    rewrites it, so the cost is at most a repeated or late announcement.
  * The tops record keeps one codex TOP per provider. If two efforts ever select different
    codex TOPs (a top model lacking `max`), alternating seats will alternate the record.
    No listed model today lacks an effort another top has. The same holds for the tie keys: a
    tie at one effort that is no tie at another (one tied entry lacking `max`) alternates them.
  * Same-user control of the environment (HOME, PATH) is out of scope, as in design s4.1.3.
  * `argv --use` records the admit refusal and the substitution as two appends under two
    acquisitions of the store lock. A crash between them leaves a refusal row with no
    substitution row: the evidence under-counts substitutions, it never invents one.
  * The CLI check is presence on PATH only. A codex binary that is present but cannot run
    is caught at call time by codex_quota.classify_codex_failure (exit 127 -> cli_missing).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
import codex_model  # noqa: E402
import codex_quota  # noqa: E402
import model_ids  # noqa: E402  (#291: the one pure benched-family normaliser)
import model_roster  # noqa: E402  (#291: the tier values - data only, checked below at import)
import review_risk  # noqa: E402

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
CLAUDE, CODEX, AGY = "claude", "codex", "agy"
PROVIDERS: Tuple[str, ...] = (CLAUDE, CODEX, AGY)

CODE_REVIEWER = "code_reviewer"
CONSULTANT_MAIN = "consultant_main"
CONSULTANT_SUPPORT = "consultant_support"
ARBITER = "arbiter"
ESCALATION = "escalation"   # I21: in the table now; no consumer until revision 3
ROLES: Tuple[str, ...] = (CODE_REVIEWER, CONSULTANT_MAIN, CONSULTANT_SUPPORT, ARBITER, ESCALATION)

#: Resolved only here; env may never change them (design s4.4).
PROTECTED: FrozenSet[str] = frozenset({CODE_REVIEWER, CONSULTANT_MAIN, ARBITER, ESCALATION})

#: S081 revision 4 D16, narrowed by the astra reserve (roster rev 4, design 2026-09-27 s3/s4.1): the
#: codex seats a review size may move. Only code_reviewer is left: complex (or a user request) serves
#: TOP, light/medium the std tier. consultant_main and arbiter are CODEX_STD literals at every size,
#: escalation is TOP at every size (the reserve's purpose, and it is rare), and consultant_support is the
#: support tier. They all ACCEPT `--size` and ignore it. model_roster.CODEX_TOP_ROLES is the policy this
#: set is checked against at import ("code_reviewer@complex" = sized; a bare role = TOP at every size).
SIZED_ROLES: FrozenSet[str] = frozenset({CODE_REVIEWER})

#: The astra reserve F7: a literal CODEX_STD seat that an explicit USER REQUEST still moves to TOP
#: (`--user-request`). The arbiter is deliberately not here: the seat that arbitrates follows the table.
USER_PROMOTED_ROLES: FrozenSet[str] = frozenset({CONSULTANT_MAIN})

#: The astra reserve F1: the protected, BUDGETED codex seats. `argv --use`, the `substitute` CLI and
#: substitute() gate on this ROLE set, never on the row kind - consultant_main and arbiter are CODEX_STD
#: literals since roster rev 4 and are still admitted against the budget and served by the Claude main
#: tier (D6) when codex cannot serve them. consultant_support (the support tier) is not admitted: a
#: failure there is a gap or a recorded skip, never a substitution.
ADMITTED_ROLES: FrozenSet[str] = frozenset({CODE_REVIEWER, CONSULTANT_MAIN, ARBITER, ESCALATION})

#: The astra reserve U2/F3: the ONE capability-failure retry on the TOP tier. Only these classify reasons
#: buy it - capacity twice and a malformed answer twice. A timeout twice goes straight to D6 (an
#: oversized brief times out on TOP too), and quota, auth, budget and gap outcomes are account problems,
#: never capability problems.
TOP_RETRY_REASONS: FrozenSet[str] = frozenset({"capacity_twice", "malformed_twice"})
#: The budget use every TOP retry is admitted under (top 1 per cycle, whatever the originating use).
TOP_RETRY_USE = "top_retry"
#: The originating uses a TOP retry may follow - codex_quota's set: every budgeted use but the SKIPPED ones
#: (the trial and the exhausted-loop review are never substituted), the audit (audit_spawn owns its arm) and a
#: retry itself (no re-entry). Fix round 1 item 6: an exhausted_review origin used to crash after writing.
TOP_RETRY_ORIGIN_USES: FrozenSet[str] = frozenset(codex_quota.TOP_RETRY_ORIGIN_USES)
#: A TOP retry that cannot serve a different, TOP-billed model goes to D6 with one of these reasons.
REASON_TOP_RETRY_SAME_PIN = "top_retry_same_pin"
REASON_TOP_RETRY_NOT_TOP = "top_retry_not_top"
REASON_TOP_RETRY_SEAT_IS_TOP = "top_retry_seat_is_top"
#: The astra reserve F2/F5: the budget uses that belong to ONE role. The escalation seat has its own use
#: (it never competes with the explorer's consult), and the exhausted-loop review runs on escalation.
USE_ROLES: Mapping[str, str] = MappingProxyType({"escalation": ESCALATION, "exhausted_review": ESCALATION})
#: The uses budgeted per (key, task_key): a diagnosis per task, an exhausted-loop review per review id.
TASK_KEY_USES: FrozenSet[str] = frozenset(codex_quota.TASK_KEY_USES)

#: light|medium|complex, borrowed from review_risk so the vocabulary has ONE definition.
SIZES: Tuple[str, ...] = review_risk.SIZES
#: The sizes that serve the std model; `complex` and --user-request serve TOP.
STD_SIZES: FrozenSet[str] = frozenset(review_risk.PROMOTABLE)
#: Borrowed from codex_quota, which owns the budget-ROW contract these values are written
#: into (design §2.1). One definition, so the resolver and the row can never disagree about
#: what a legal source is - the same reason SIZES comes from review_risk.
SIZE_SOURCES: FrozenSet[str] = frozenset(codex_quota.SIZE_SOURCES)

#: The std codex model: the light/medium sized main seats serve it. #291: the value lives in
#: model_roster (CODEX_STD), the one source codex_model.DEFAULT_MODEL reads too.
CODEX_STD_MODEL = model_roster.CODEX_STD
#: #302: the codex SUPPORT model, the consultant_support codex row (model_roster.CODEX_SUPPORT). A
#: separate tier from std since roster rev 3; the two MAY be equal (a rev-1/2-shaped revert) and no
#: code depends on them differing (`check` warns when they are equal).
#: A roster module WITHOUT the attribute (a rev-1/2 file, e.g. a runbook revert or a pre-#302 home
#: copy) reads it as its CODEX_STD - the same rule as a HISTORY row without `codex_support` - so the
#: rev-2 shape stays a legal roster (JC-1). A value that IS present must be a safe word (invariant).
CODEX_SUPPORT_MODEL = getattr(model_roster, "CODEX_SUPPORT", model_roster.CODEX_STD)
#: #302: the roster's non-TOP codex tiers. A codex model in this set spends the std class; a TOP
#: selector that resolves onto one records TOP_RESOLVED_TO_STD.
CODEX_NON_TOP_TIERS: FrozenSet[str] = frozenset({CODEX_STD_MODEL, CODEX_SUPPORT_MODEL})
#: #302 (challenger #4): the provenance event key, present (True) only when a codex TOP selector
#: resolved onto a roster non-TOP tier - a vendor priority inversion, or a freeze onto a tier model.
TOP_RESOLVED_TO_STD = "top_resolved_to_std"

#: #291: the roster revision every Claude and codex tier resolution (std or support) records as `roster_rev`.
ROSTER_REVISION = model_roster.REVISION
#: #291: the provenance key (and emit --json top-level key) naming the roster revision.
ROSTER_REV = "roster_rev"
#: #367 WP-C: every emit carries the agy size -> level map (model_roster.AGY_LEVEL_BY_SIZE), sized or not.
AGY_LEVEL_BY_SIZE_KEY = "agy_level_by_size"

#: Written by forge Step 4, deleted at close-out with `.forge/cycle-id`. READ here and by
#: nothing else; no bob stage writes it.
FORGE_SIZE_FILE = "size"

SOURCES: FrozenSet[str] = frozenset({"freeze", "env", "roster", "harness_literal"})

KIND_ALIAS = "alias"          # claude vendor alias
KIND_TOP = "top"              # codex auto-follow TOP at an effort
KIND_LITERAL = "literal"      # codex fixed slug at an effort
KIND_TOP_AGY = "top_agy"      # agy newest version of the roster family at a level


@dataclass(frozen=True)
class RoleRow:
    """One cell of the role table. `timeout` is None for codex (codex_model owns it)."""

    kind: str
    value: Optional[str] = None
    effort: Optional[str] = None
    level: Optional[str] = None
    timeout: Optional[int] = None


# --------------------------------------------------------------------------- #
# THE ROLE TABLE - design s4.2, exactly. Change it only with the design.
#
# #291: the Claude cells name TIERS, not models. The four protected rows serve
# model_roster.CLAUDE_MAIN and consultant_support serves model_roster.CLAUDE_SUPPORT;
# a model swap edits model_roster.py (docs/model-roster-swap.md), never this table.
#
# #311 (design 2026-09-24 s3.3, U3): the Claude cells carry the reasoning EFFORT the seat runs
# at - medium on code_reviewer, consultant_main and arbiter, xhigh on escalation, medium on
# consultant_support (2026-10-29, user: Anthropic's Opus 5.5 guidance is to start at medium and
# reserve xhigh/max for measured gains; escalation stays xhigh: it is the seat a cheaper attempt already failed, user 2026-10-29). Like the model, it
# lives only here (home tier, fail-closed): no project file and no smart-config layer reaches
# it, and an env override is honoured on a protected seat only when it equals this literal.
# The dispatcher passes it EXPLICITLY (workflow `agent({effort})`, headless `--effort`): an
# agent file's frontmatter never governs a protected seat. `max` (the escalation seat's
# verified retry) is phase 2 and is not reachable from this table.
#
# TIMEOUTS, S081 revision 4 (D24). The `timeout=` literals BELOW are claude and
# agy only; the codex cells carry none, because codex_model.timeout_for owns
# every codex timeout and this table must never grow a second one. The D24 raise
# therefore lands entirely in codex_model._TIMEOUT_FLOOR_S and reaches the codex
# column here for free (code_reviewer/consultant_main 2400, consultant_support
# 1200, arbiter/escalation 3600).
#
# L13 - SETTLED 2026-09-16 (team lead), and the agy 600s are DELIBERATE:
# `seat_model.py timeout --provider agy` keeps returning the ROLE_TABLE literal
# 600 this revision. It does NOT return the agy hard cap. `codex_watch.
# AGY_HARD_CAP_S = 900` carries that cap as a WATCHDOG-only constant, exactly as
# the codex idle timeout already is - mechanism and policy do not move in the
# same change, and NO call site consumes the watchdog yet (migration is revision
# 5, stream E). CARRIED COST, stated rather than netted out: until then the
# registry says 600 while the watchdog caps at 900, so a caller that fed this
# number to the watchdog would cap early. No caller does, which is why deferring
# is safe - and why revision 5 must close it when it touches those call sites.
# --------------------------------------------------------------------------- #
ROLE_TABLE: Mapping[str, Mapping[str, RoleRow]] = MappingProxyType({
    CODE_REVIEWER: MappingProxyType({
        CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_MAIN, effort="medium", timeout=600),
        CODEX: RoleRow(KIND_TOP, effort="xhigh"),
    }),
    CONSULTANT_MAIN: MappingProxyType({
        CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_MAIN, effort="medium", timeout=600),
        # The astra reserve U1: Sol @ xhigh at every size (a user request still promotes it, F7).
        CODEX: RoleRow(KIND_LITERAL, value=CODEX_STD_MODEL, effort="xhigh"),
        AGY: RoleRow(KIND_TOP_AGY, level="high", timeout=600),
    }),
    CONSULTANT_SUPPORT: MappingProxyType({
        CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_SUPPORT, effort="medium", timeout=600),
        CODEX: RoleRow(KIND_LITERAL, value=CODEX_SUPPORT_MODEL, effort="medium"),
        AGY: RoleRow(KIND_TOP_AGY, level="medium", timeout=600),
    }),
    ARBITER: MappingProxyType({
        CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_MAIN, effort="medium", timeout=1200),
        # The astra reserve U4: Sol @ xhigh, the measured floor for arbiter verdicts (2026-07-11, on
        # gpt-5.6-sol). `max` stays with avengers' ratification_arbiter seat class, not this row.
        CODEX: RoleRow(KIND_LITERAL, value=CODEX_STD_MODEL, effort="xhigh"),
        AGY: RoleRow(KIND_TOP_AGY, level="high", timeout=600),
    }),
    ESCALATION: MappingProxyType({
        CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_MAIN, effort="xhigh", timeout=1200),
        CODEX: RoleRow(KIND_TOP, effort="max"),
    }),
})

#: The astra reserve (roster rev 4) F7: the CODEX_TOP_ROLES suffix that makes a TOP role SIZED.
TOP_ROLE_COMPLEX_SUFFIX = "@complex"


def codex_top_policy(roster: Any = None) -> Dict[str, str]:
    """model_roster.CODEX_TOP_ROLES as {role: "complex" | "every_size"}; raises SeatModelError when malformed."""
    r = model_roster if roster is None else roster
    entries = getattr(r, "CODEX_TOP_ROLES", None)
    if not isinstance(entries, tuple) or not all(isinstance(e, str) and e for e in entries):
        raise SeatModelError(f"CODEX_TOP_ROLES must be a tuple of non-empty strings, got {entries!r}")
    policy: Dict[str, str] = {}
    for entry in entries:
        role, sep, qualifier = entry.partition("@")
        if role not in ROLES or (sep and TOP_ROLE_COMPLEX_SUFFIX != sep + qualifier) or role in policy:
            raise SeatModelError(f"CODEX_TOP_ROLES entry {entry!r} is not '<role>' or '<role>@complex' for a "
                                 f"known role, once")
        policy[role] = "complex" if sep else "every_size"
    return policy


def role_table_violations(table: Any = None, *, sized: Any = None, roster: Any = None) -> List[str]:
    """Every way ROLE_TABLE disagrees with the roster's TOP reserve (astra reserve F7); [] when clean.

    The reserve is the roster TOP CLASS, not a model name: every codex TOP row must be named in
    CODEX_TOP_ROLES, a "@complex" role must be the ONLY sized role (and sized), a bare role must be TOP at
    every size (not sized), and every other protected codex row must be a CODEX_STD literal - so a table
    that quietly promotes or demotes a seat stops every importer, and a revert is a roster revision.
    """
    t = ROLE_TABLE if table is None else table
    size_set = SIZED_ROLES if sized is None else frozenset(sized)
    r = model_roster if roster is None else roster
    out: List[str] = []
    try:
        policy = codex_top_policy(r)
    except SeatModelError as exc:
        return [str(exc)]
    std = getattr(r, "CODEX_STD", None)
    for role in sorted(set(policy) - PROTECTED):
        out.append(f"CODEX_TOP_ROLES names {role}, which is not a protected, budgeted codex seat "
                   f"({', '.join(sorted(PROTECTED))}); only those can be reserved")
    # Both directions (fix round 1 item 5): EVERY codex TOP row in the table must be a declared reserve.
    for role in sorted(t):
        row = t[role].get(CODEX) if hasattr(t[role], "get") else None
        if row is not None and row.kind == KIND_TOP and role not in policy:
            out.append(f"{role}'s codex row is TOP but CODEX_TOP_ROLES does not reserve it")
    for role in sorted(PROTECTED):
        row = t.get(role, {}).get(CODEX)
        if row is None:
            out.append(f"CODEX_TOP_ROLES: {role} has no codex row")
            continue
        wanted = policy.get(role)
        if wanted is not None:
            if row.kind != KIND_TOP:
                out.append(f"CODEX_TOP_ROLES reserves {role} for the TOP tier, but its codex row is {row.kind!r}")
            if wanted == "complex" and role not in size_set:
                out.append(f"CODEX_TOP_ROLES names {role}@complex, but {role} is not in SIZED_ROLES")
            if wanted == "every_size" and role in size_set:
                out.append(f"CODEX_TOP_ROLES names {role} (TOP at every size), but {role} is in SIZED_ROLES")
        elif row.kind != KIND_LITERAL or row.value != std:
            out.append(f"CODEX_TOP_ROLES does not reserve {role}, so its codex row must be the CODEX_STD literal "
                       f"{std!r}, not {row.kind!r} {row.value!r}")
    for role in sorted(size_set - {role for role, how in policy.items() if how == "complex"}):
        out.append(f"SIZED_ROLES holds {role}, which CODEX_TOP_ROLES does not name as '{role}@complex'")
    return out


def codex_std_efforts() -> FrozenSet[str]:
    """Every effort the codex std tier must offer (astra reserve F6): the sized rows' efforts (their
    light/medium path), every literal CODEX_STD row's effort (consultant_main / arbiter), every std-pinned
    seat class's effort (codex_model._ROLE_PINS: `max` for avengers' ratification arbiter), and `medium`
    (codex_model's std fallbacks: the cheap-path row and the raw-tier convene seat classes)."""
    efforts = {str(ROLE_TABLE[role][CODEX].effort) for role in SIZED_ROLES if CODEX in ROLE_TABLE[role]}
    efforts |= {str(rows[CODEX].effort) for rows in ROLE_TABLE.values()
                if CODEX in rows and rows[CODEX].kind == KIND_LITERAL and rows[CODEX].value == CODEX_STD_MODEL}
    # Fix round 1 item 4: every std-backed SEAT CLASS too - codex_model's std-pinned role pins (the challenger
    # floor, the ratification arbiter @ max, the audit arm), which avengers seats resolve on the std literal.
    efforts |= {str(pin.effort) for pin in codex_model._ROLE_PINS.values() if pin.model == CODEX_STD_MODEL}
    return frozenset(efforts | {"medium"})


#: DOCUMENTATION of how the S080 codex_model role keys map onto this table.
#: codex_model.resolve() itself is unchanged and is not routed through here.
LEGACY_ROLE_MAP: Mapping[str, Tuple[str, str]] = MappingProxyType({
    codex_model.CHALLENGER_FLOOR: (CONSULTANT_MAIN, CODEX),
    codex_model.RATIFICATION_ARBITER: (ARBITER, CODEX),
    codex_model.AUDIT_CODEX_ARM: (CODE_REVIEWER, CODEX),
})

# --------------------------------------------------------------------------- #
# Harness literals, rules and file schemas
# --------------------------------------------------------------------------- #
CODEX_TOP_HARNESS_LITERAL = "gpt-6-astra"
#: #367: the agy family and the harness version are ROSTER DATA (model_roster rev 6). A value
#: that is not a plain string is read as "" here so the pattern below still compiles; the
#: import-time invariants (agy_roster_violations) then refuse it, fail closed.
AGY_FAMILY: str = model_roster.AGY_FAMILY if isinstance(getattr(model_roster, "AGY_FAMILY", None), str) else ""
AGY_HARNESS_VERSION: str = (model_roster.AGY_HARNESS_VERSION
                            if isinstance(getattr(model_roster, "AGY_HARNESS_VERSION", None), str) else "")
AGY_HARNESS_TEMPLATE = "gemini-" + AGY_HARNESS_VERSION + "-" + AGY_FAMILY + "-{level}"
#: The levels an agy seat may carry.
AGY_LEVELS: Tuple[str, ...] = ("high", "medium", "low")
#: #367 WP-C (roster rev 7): the agy level a SIZED call serves, {size: level}, read-only. A value
#: that is not a dict is read as {} here; the import-time invariants then refuse it, fail closed.
AGY_LEVEL_BY_SIZE: Mapping[str, str] = MappingProxyType(
    dict(model_roster.AGY_LEVEL_BY_SIZE)
    if isinstance(getattr(model_roster, "AGY_LEVEL_BY_SIZE", None), dict) else {})
#: The level a --user-request agy call serves: the top level, whatever the size (codex serves TOP).
AGY_USER_REQUEST_LEVEL = "high"
_AGY_FAMILY_WORD = re.compile(r"[a-z]{1,20}", re.ASCII)
_AGY_VERSION_WORD = re.compile(r"\d{1,9}(\.\d{1,9})*", re.ASCII)

#: The agy family rule (formerly FLASH-ONLY, #367); matched with fullmatch + re.ASCII, so a
#: trailing newline or a non-ASCII digit can never satisfy it. The family is re.escape'd so an
#: invalid roster value can never become regex syntax before the invariants refuse it.
#: #282 fix round 2 G7c (plan K59c): each digit group is BOUNDED at 9, the same bound F12 gave
#: codex_model._GENERATION and for the same reason. `_version_key` calls `int(part)` on every
#: dotted part, and `int()` on an unbounded run raises ValueError past CPython's 4300-digit
#: str->int limit — from inside `_agy_top`, i.e. past the fail-open boundary, since `_resolve_agy`
#: catches `_ResolutionFailure` and not ValueError. A longer run now simply does not MATCH, so the
#: slug is not of the agy family and the rejection paths this module already has handle it. Nine digits is
#: far past any real Gemini version and keeps the rule total. The pattern is interpolated into five
#: user-facing messages below, which now show the bound.
AGY_FAMILY_PATTERN = r"^gemini-\d{1,9}(\.\d{1,9})*-" + re.escape(AGY_FAMILY) + r"-(high|medium|low)$"
_AGY_FAMILY_RE = re.compile(AGY_FAMILY_PATTERN, re.ASCII)
#: The rule as a sentence, for every refusal message.
AGY_FAMILY_RULE = f"the agy family rule ({AGY_FAMILY_PATTERN}); agy serves Gemini {AGY_FAMILY} only"

#: #311: every reasoning effort Claude Code accepts, low to high. Held equal to
#: effort_policy.LEVELS by a parity test (restated, not imported: this module must not
#: depend on the execution-effort policy it sits above).
CLAUDE_EFFORTS: Tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

#: Claude vendor aliases a NON-protected Claude seat may be moved to by env.
CLAUDE_ALIASES: FrozenSet[str] = frozenset({"fable", "opus", "sonnet", "haiku"})

#: A codex slug or effort must be one plain shell word: `$PIN` is expanded unquoted.
_SAFE_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]*", re.ASCII)
#: What the CLI may print for `argv` / `model` (flags included).
_SAFE_ARGV_TOKEN = re.compile(r"-{0,2}[A-Za-z0-9][A-Za-z0-9._:=+-]*", re.ASCII)
#: The longest model name codex_quota records (its plain-word rule); a longer --requested-model is usage.
_MODEL_WORD_MAX = 128

ROSTER_STALE_AFTER_S = 7 * 24 * 3600

PINS_SCHEMA = "seat-model-pins.v1"
TOPS_SCHEMA = "seat-model-tops.v1"
AGY_ROSTER_SCHEMA = "agy-models.v1"
EMIT_SCHEMA = "seat-model-emit.v1"

EXIT_OK = 0
EXIT_RESOLUTION_FAILED = 1
EXIT_USAGE = 2
#: `argv --use` / `substitute`: astra is unavailable; stdout line 1 = reason, line 2 = the Claude alias.
EXIT_SUBSTITUTE = 3
#: `argv --use trial` / `substitute --use trial`: the astra trial is skipped (never substituted); stdout empty.
EXIT_SKIPPED = 10

#: Plan-time "astra unavailable" reasons decided here (the rest come from codex_quota.admit()).
UNAVAILABLE_NO_ELIGIBLE = "no_eligible_model"
UNAVAILABLE_CLI_MISSING = "cli_missing"
#: #282 R4: the provenance event key (and the error-message token) for an INVALID codex roster.
ROSTER_INVALID = "roster_invalid"
#: #282 fix round 1 F13 (K43): the provenance event key naming the roster entries codex_model
#: DROPPED for a field-type fault they could never have been selected with. Present only when
#: non-empty, and codex-only. Per K30 it is added to neither audit_spawn's verdict provenance
#: nor convene's persisted provenance.
ROSTER_ENTRIES_SKIPPED = "roster_entries_skipped"
#: #282 r14: the provenance event key naming the pins-file `top` AS WRITTEN; only when source is "freeze".
FROZEN_SLUG = "frozen_slug"
#: #282 R16: the provenance and tops-record event keys of a priority tie at the codex TOP.
TIE_BREAK = "tie_break"
TIED_WITH = "tied_with"
#: #282 fix round 1 (F10, plan K44): the tops-record event key naming the slug the PRIORITY rules
#: chose, written only when it DIFFERS from the served `top` (i.e. an upgrade was followed). It is
#: the incumbent R16 consults; a record without it says "the priority winner is the recorded top",
#: which is every record written before this round and every selection that follows no upgrade.
PRIORITY_WINNER = "priority_winner"
#: The binary `argv --use` looks up on PATH (J12: in-process shutil.which, no subprocess).
CODEX_CLI = "codex"
TRIAL_USE = "trial"
#: The uses whose seat is SKIPPED, never substituted, when codex cannot serve it (exit 10): the trial, and the
#: astra reserve's exhausted-loop review (U3) - a Claude stand-in adds no independence to that review, so the
#: loop goes to the user without it (after the #322 reset-wait rule) rather than recording a stand-in.
SKIPPED_USES: FrozenSet[str] = frozenset({TRIAL_USE, "exhausted_review"})

_ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|z|[+-]\d{2}:\d{2})?", re.ASCII)


class SeatModelError(RuntimeError):
    """A seat could not be resolved. Fail-open callers get the harness literal instead,
    except for a caller bug (no such row, a malformed `effort=`), which always raises."""


class NoEligibleModelError(SeatModelError):
    """Fail-closed only: the codex roster is readable but lists NO eligible TOP for the effort.

    That is "astra unavailable" (a substitute may serve the seat), not a broken resolver.
    It is still a SeatModelError, so every existing fail-closed caller keeps working. An
    absent roster (the sanctioned harness literal) and an invalid freeze pin (a broken
    resolver) never raise this.
    """

    unavailable_reason = UNAVAILABLE_NO_ELIGIBLE


class _ResolutionFailure(SeatModelError):
    """Internal: the call-site failure path (fail_open decides what happens)."""


class _NoEligibleModel(_ResolutionFailure):
    """Internal: the loaded roster has no eligible TOP (becomes NoEligibleModelError fail-closed)."""


# --------------------------------------------------------------------------- #
# #291 - the model roster: benched families and the import-time invariants
# --------------------------------------------------------------------------- #
# The normaliser itself lives in model_ids.py (pure: no roster, no invariant check), so a
# roster edit that makes THIS module's import fail closed cannot also disable the benched
# refusal in smart-config, which imports model_ids directly (#291 fix round 1, finding A).
_id_tokens = model_ids.id_tokens


def is_benched(model_id: Any, benched: Any = None) -> bool:
    """True when `model_id` names a benched Claude family (#291 design s3.2).

    THE ONE NORMALISER: this delegates to model_ids.is_benched, whose docstring states the
    rule (every "[1m]"-style group removed wherever it sits, ASCII-lowercased, split on
    any run of characters outside ASCII [a-z0-9], family tokens as a contiguous run, a
    version glued on as digits allowed). So
    "fable", "fable[1m][1m]", "Fable 5.1", "claude_fable" and "claude-fable5-1" are all
    benched while fable is, and "opus" / "claude-opus-5-5" / "fablex" are not. `benched`
    defaults to model_roster.CLAUDE_BENCHED, read at CALL time so a test can monkeypatch
    the roster. Anything that is not a string is never benched.
    """
    families = model_roster.CLAUDE_BENCHED if benched is None else benched
    return model_ids.is_benched(model_id, families)


def roster_violations(roster: Any = None) -> List[str]:
    """Every violated roster invariant (design s3.1), as one message each; [] when clean.

    Checked at seat_model import (a violation raises SeatModelError, so every importer fails
    closed) and again by `check`. The list form is what lets `check` name each failure.
    """
    r = model_roster if roster is None else roster
    out: List[str] = []
    main = getattr(r, "CLAUDE_MAIN", None)
    support = getattr(r, "CLAUDE_SUPPORT", None)
    benched = getattr(r, "CLAUDE_BENCHED", None)
    eligible = getattr(r, "CLAUDE_MAIN_ELIGIBLE", None)
    std = getattr(r, "CODEX_STD", None)
    # #302: an absent CODEX_SUPPORT (a rev-1/2 roster file) reads as CODEX_STD, like a HISTORY row
    # without `codex_support`; a present one must be a safe word.
    codex_support = getattr(r, "CODEX_SUPPORT", std)
    revision = getattr(r, "REVISION", None)
    history = getattr(r, "HISTORY", None)

    if getattr(r, "SCHEMA", None) != "model-roster.v1":
        out.append(f"SCHEMA must be 'model-roster.v1', got {getattr(r, 'SCHEMA', None)!r}")
    if not isinstance(benched, frozenset) or not all(isinstance(b, str) and b for b in benched):
        out.append(f"CLAUDE_BENCHED must be a frozenset of non-empty strings, got {benched!r}")
        benched = frozenset()
    if not isinstance(eligible, frozenset) or not all(isinstance(e, str) and e for e in eligible):
        out.append(f"CLAUDE_MAIN_ELIGIBLE must be a frozenset of non-empty strings, got {eligible!r}")
        eligible = frozenset()
    if not isinstance(main, str) or not isinstance(support, str):
        out.append(f"CLAUDE_MAIN and CLAUDE_SUPPORT must be strings, got {main!r} / {support!r}")
    else:
        if main == support:
            out.append(f"CLAUDE_MAIN == CLAUDE_SUPPORT ({main!r}); the avengers arbiter must differ "
                       f"from its members (D23)")
        for name, value in (("CLAUDE_MAIN", main), ("CLAUDE_SUPPORT", support)):
            if value not in CLAUDE_ALIASES:
                out.append(f"{name} {value!r} is not a Claude vendor alias ({sorted(CLAUDE_ALIASES)})")
            if is_benched(value, benched):
                out.append(f"{name} {value!r} is benched ({sorted(benched)})")
        if main not in eligible:
            out.append(f"CLAUDE_MAIN {main!r} is not in CLAUDE_MAIN_ELIGIBLE ({sorted(eligible)})")
    if not isinstance(std, str) or _SAFE_WORD.fullmatch(std) is None:
        out.append(f"CODEX_STD must be one safe shell word, got {std!r}")
    # #302 JC-1: the support tier is a safe word too. CODEX_STD != CODEX_SUPPORT is deliberately NOT
    # an invariant (a revert to a rev-1/2-shaped row must stay legal); `check` warns instead.
    if not isinstance(codex_support, str) or _SAFE_WORD.fullmatch(codex_support) is None:
        out.append(f"CODEX_SUPPORT must be one safe shell word, got {codex_support!r}")
    # #302 final re-review NEW-1: a non-TOP tier must never be the TOP model. A tier equal to the
    # TOP harness literal would be billed std (pin_model_class's tier rule), and with a freeze on
    # that literal every protected TOP seat would be billed std too - astra on the std budget.
    for name, value in (("CODEX_STD", std), ("CODEX_SUPPORT", codex_support)):
        if value == CODEX_TOP_HARNESS_LITERAL:
            out.append(f"{name} must not be the codex TOP harness literal {CODEX_TOP_HARNESS_LITERAL!r}: "
                       f"a std/support tier equal to the TOP model would bill astra calls as std")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        out.append(f"REVISION must be a positive integer, got {revision!r}")
    if not isinstance(history, tuple) or not history or not all(isinstance(h, dict) for h in history):
        out.append("HISTORY must be a non-empty tuple of dicts")
        return out
    revs = [h.get("rev") for h in history]
    if revs != list(range(1, len(history) + 1)):
        out.append(f"HISTORY revs must run 1..{len(history)} in order, got {revs}")
    last = history[-1]
    if last.get("rev") != revision:
        out.append(f"REVISION {revision!r} != HISTORY[-1]['rev'] {last.get('rev')!r}")
    live = {"claude_main": main, "claude_support": support, "codex_std": std}
    for key, value in live.items():
        if last.get(key) != value:
            out.append(f"HISTORY[-1][{key!r}] {last.get(key)!r} != live value {value!r}")
    # #302: a row without codex_support (every row before rev 3) reads as its codex_std.
    last_support = last.get("codex_support", last.get("codex_std"))
    if last_support != codex_support:
        out.append(f"HISTORY[-1]['codex_support'] {last_support!r} (a missing key reads as codex_std) "
                   f"!= live CODEX_SUPPORT {codex_support!r}")
    # The astra reserve (rev 4): the live CODEX_TOP_ROLES is recorded on the last HISTORY row, so a
    # reserve change is a revision like a model swap. A roster without the field (rev 1-3) has none.
    live_top_roles = getattr(r, "CODEX_TOP_ROLES", None)
    if live_top_roles is not None and last.get("codex_top_roles") != live_top_roles:
        out.append(f"HISTORY[-1]['codex_top_roles'] {last.get('codex_top_roles')!r} != live CODEX_TOP_ROLES "
                   f"{live_top_roles!r}")
    hist_benched = last.get("benched")
    if not isinstance(hist_benched, tuple) or frozenset(hist_benched) != frozenset(benched):
        out.append(f"HISTORY[-1]['benched'] {hist_benched!r} != live CLAUDE_BENCHED {sorted(benched)}")
    for entry in history:
        for key in ("at", "claude_main", "claude_support", "codex_std", "reason"):
            if not isinstance(entry.get(key), str) or not entry.get(key):
                out.append(f"HISTORY rev {entry.get('rev')!r}: {key!r} must be a non-empty string")
        row_support = entry.get("codex_support")
        if "codex_support" in entry and (not isinstance(row_support, str) or not row_support):
            out.append(f"HISTORY rev {entry.get('rev')!r}: 'codex_support' must be a non-empty string "
                       f"when present")
    # #367: the agy family is roster data from rev 6. The live roster is always held to it; a
    # stand-in roster (a test double) only when it carries the agy fields.
    if roster is None or hasattr(r, "AGY_FAMILY") or hasattr(r, "AGY_HARNESS_VERSION"):
        out.extend(agy_roster_violations(r))
    return out


#: A HISTORY row before rev 6 carries no `agy_family`; what served agy then was flash.
AGY_FAMILY_BEFORE_REV6 = "flash"


def agy_roster_violations(roster: Any = None) -> List[str]:
    """The agy family invariants (#367), one message each; [] when clean. Strict: an absent field
    is a violation.

    AGY_FAMILY is one lower-case word (^[a-z]{1,20}$); AGY_HARNESS_VERSION is a dotted number
    (^\\d{1,9}(\\.\\d{1,9})*$); the harness literal at every level satisfies the family rule; and
    HISTORY[-1]'s `agy_family` (missing reads as "flash") equals AGY_FAMILY. The family rule is built
    from the roster passed in, so a stand-in roster is judged by its own family.
    """
    r = model_roster if roster is None else roster
    out: List[str] = []
    family = getattr(r, "AGY_FAMILY", None)
    version = getattr(r, "AGY_HARNESS_VERSION", None)
    family_ok = isinstance(family, str) and _AGY_FAMILY_WORD.fullmatch(family) is not None
    version_ok = isinstance(version, str) and _AGY_VERSION_WORD.fullmatch(version) is not None
    if not family_ok:
        out.append(f"AGY_FAMILY must match ^[a-z]{{1,20}}$ (one lower-case word), got {family!r}")
    if not version_ok:
        out.append(f"AGY_HARNESS_VERSION must match ^\\d{{1,9}}(\\.\\d{{1,9}})*$, got {version!r}")
    if family_ok and version_ok:
        rule = re.compile(r"^gemini-\d{1,9}(\.\d{1,9})*-" + re.escape(family) + r"-(high|medium|low)$",
                          re.ASCII)
        for level in AGY_LEVELS:
            literal = f"gemini-{version}-{family}-{level}"
            if rule.fullmatch(literal) is None:
                out.append(f"the agy harness literal {literal!r} does not satisfy the agy family rule")
    history = getattr(r, "HISTORY", None)
    if isinstance(history, tuple) and history and isinstance(history[-1], dict):
        last_family = history[-1].get("agy_family", AGY_FAMILY_BEFORE_REV6)
        if last_family != family:
            out.append(f"HISTORY[-1]['agy_family'] {last_family!r} (a missing key reads as "
                       f"{AGY_FAMILY_BEFORE_REV6!r}) != live AGY_FAMILY {family!r}")
    # #367 WP-C (rev 7): the size -> level map, checked when the roster or its last HISTORY row names one
    # (a roster older than rev 7 has neither; the golden test pins the committed roster's map).
    by_size = getattr(r, "AGY_LEVEL_BY_SIZE", None)
    last_row = history[-1] if isinstance(history, tuple) and history and isinstance(history[-1], dict) else {}
    if roster is None or by_size is not None or "agy_level_by_size" in last_row:
        out.extend(agy_level_violations(by_size, last_row))
    return out


def agy_level_violations(by_size: Any, last_row: Any) -> List[str]:
    """The agy size -> level invariants (#367 WP-C, rev 7), one message each; [] when clean.

    AGY_LEVEL_BY_SIZE is a dict whose keys are exactly the review sizes (light, medium, complex) and
    whose values are agy levels (high, medium, low); HISTORY[-1]['agy_level_by_size'] equals it.
    """
    out: List[str] = []
    if not isinstance(by_size, dict) or set(by_size) != set(SIZES) \
            or not all(isinstance(v, str) and v in AGY_LEVELS for v in by_size.values()):
        out.append(f"AGY_LEVEL_BY_SIZE must be a dict mapping exactly {', '.join(SIZES)} to one of "
                   f"{', '.join(AGY_LEVELS)}, got {by_size!r}")
    recorded = last_row.get("agy_level_by_size") if isinstance(last_row, dict) else None
    if recorded != by_size:
        out.append(f"HISTORY[-1]['agy_level_by_size'] {recorded!r} != live AGY_LEVEL_BY_SIZE {by_size!r}")
    return out


_ROSTER_VIOLATIONS = roster_violations()
if _ROSTER_VIOLATIONS:
    # FAIL CLOSED, deliberately (design s3.1 "Failure mode, decided"): falling open would serve
    # the very model an invariant forbids, and at the VERIFIED gate an import crash is a
    # fail-closed outcome. Reachable only through a bad roster commit.
    raise SeatModelError("model_roster.py violates its invariants: " + "; ".join(_ROSTER_VIOLATIONS))

_ROLE_TABLE_VIOLATIONS = role_table_violations()
if _ROLE_TABLE_VIOLATIONS:
    # FAIL CLOSED, like the roster invariants (the astra reserve F7): a table that disagrees with the
    # roster's TOP reserve would serve - and bill - a model class the roster forbids for that seat.
    raise SeatModelError("seat_model.ROLE_TABLE disagrees with model_roster.CODEX_TOP_ROLES: "
                         + "; ".join(_ROLE_TABLE_VIOLATIONS))


@dataclass(frozen=True)
class SeatPin:
    """A fully resolved seat. `argv_fragment` is the only sanctioned spelling on a command line."""

    model: str
    effort: Optional[str]
    timeout: int
    argv_fragment: Tuple[str, ...]
    provenance: Dict[str, Any]
    #: #302 (challenger #7): the kind of the ROW this pin resolved from (KIND_TOP / KIND_LITERAL / ...),
    #: after sizing. Read by pin_model_class(); None on a pin built by hand (a fake, a substitute), which
    #: then falls back to the slug. Not serialised, not compared: a resolution-path fact, not a pin value.
    row_kind: Optional[str] = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class _Paths:
    codex_roster: Path
    codex_sessions: Path
    agy_roster: Path
    pins: Path
    tops: Path


def _paths() -> _Paths:
    """Every input and the one output, from Path.home() read NOW (tests redirect HOME)."""
    home = Path.home()
    state = home / ".claude" / "state"
    return _Paths(
        codex_roster=home / ".codex" / "models_cache.json",
        codex_sessions=home / ".codex" / "sessions",
        agy_roster=state / "agy-models.json",
        pins=state / "seat-model-pins.json",
        tops=state / "seat-model-tops.json",
    )


def _now() -> float:
    return time.time()


def _iso_z(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Any) -> Optional[float]:
    """ISO-8601 -> epoch. Accepts the live codex nanosecond form; None when unusable."""
    if not isinstance(value, str):
        return None
    match = _ISO.fullmatch(value.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    try:
        micro = int((fraction or "0")[:6].ljust(6, "0"))
        tz = timezone.utc
        if zone and zone not in ("Z", "z"):
            sign = 1 if zone[0] == "+" else -1
            tz = timezone(sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6])))
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), micro, tzinfo=tz)
    except (ValueError, OverflowError):
        return None
    return dt.timestamp()


def _is_stale(fetched_at: Optional[str]) -> bool:
    epoch = _parse_iso(fetched_at)
    return epoch is None or (_now() - epoch) > ROSTER_STALE_AFTER_S


def _read_json(path: Path) -> Tuple[str, Any]:
    """-> ("absent", None) | ("invalid", None) | ("ok", value). Never raises."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "absent", None
    except (OSError, ValueError):
        return "invalid", None
    try:
        return "ok", json.loads(raw)
    except ValueError:
        return "invalid", None


def _ascii(text: Any) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


# --------------------------------------------------------------------------- #
# Table access
# --------------------------------------------------------------------------- #
def _row(role: Any, provider: Any) -> RoleRow:
    if role not in ROLE_TABLE:
        raise SeatModelError(
            f"unknown role {role!r}; the roles are exactly {list(ROLES)} (execution is not a role)")
    if provider not in PROVIDERS:
        raise SeatModelError(f"unknown provider {provider!r}; expected one of {list(PROVIDERS)}")
    rows = ROLE_TABLE[role]
    if provider not in rows:
        raise SeatModelError(f"the role table has no row for {role} x {provider} (design s4.2)")
    return rows[provider]


def is_top(role: str, provider: str) -> bool:
    """True for a TOP selector (codex TOP, agy TOP-<family>). Strict: a missing row raises."""
    return _row(role, provider).kind in (KIND_TOP, KIND_TOP_AGY)


def is_agy_family(slug: Any) -> bool:
    """The agy family rule: `gemini-<version>-<AGY_FAMILY>-(high|medium|low)` and nothing else."""
    return isinstance(slug, str) and _AGY_FAMILY_RE.fullmatch(slug) is not None


def _agy_version(slug: str) -> str:
    return slug[len("gemini-"):slug.rindex("-" + AGY_FAMILY + "-")]


def _version_key(version: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _selector_text(row: RoleRow, effort: Optional[str]) -> str:
    if row.kind == KIND_TOP:
        return f"TOP@{effort}"
    if row.kind == KIND_LITERAL:
        return f"{row.value}@{effort}"
    if row.kind == KIND_TOP_AGY:
        return f"TOP-{AGY_FAMILY}-{row.level}"
    return str(row.value)


# --------------------------------------------------------------------------- #
# SIZE (D16, D22) - the L7 resolution order, implemented ONCE
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SizeDecision:
    """The size a call resolved to, where it came from, and who asked for it."""

    size: str
    size_source: str
    requested_by: Optional[str] = None


def _check_size(value: Any, what: str) -> str:
    """A size is one of SIZES, exactly. Anything else is a CALLER BUG, never a silent default."""
    if not isinstance(value, str) or isinstance(value, bool) or value not in SIZES:
        raise SeatModelError(f"{what} must be one of {', '.join(SIZES)}, got {value!r}")
    return value


def _larger(a: str, b: str) -> str:
    return a if SIZES.index(a) >= SIZES.index(b) else b


def read_forge_size(project_root: Any) -> Optional[str]:
    """`<project_root>/.forge/size`, or None.

    FIRST LINE ONLY, and one of light|medium|complex; ANYTHING else - a missing file, junk, a
    directory, a permission error, a second line that disagrees - is treated as ABSENT rather
    than as a failure. A junk file must not break every seat in a cycle, and an unreadable one
    is exactly as informative as no file at all.
    """
    if project_root is None:
        return None
    try:
        path = Path(project_root) / ".forge" / FORGE_SIZE_FILE
        with open(path, encoding="utf-8") as handle:
            first = handle.readline()
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    first = first.strip()
    return first if first in SIZES else None


def resolve_size(explicit: Optional[str] = None, *, project_root: Any = None,
                 user_request: bool = False, paths: Any = (), symbols: Any = ()) -> SizeDecision:
    """L7, in one place. See the SIZE block of the module docstring for the rule in words.

    `explicit` is the caller's size (the `--size` flag, or the routing class the main loop
    passes). `project_root` names the forge cycle whose `.forge/size` applies; None means no
    forge root was supplied and no file is read. `paths`/`symbols` are the change set, handed
    STRAIGHT to review_risk.assess - the promotion contract lives there (WP-A1) and is not
    reimplemented here.
    """
    if explicit is not None:
        explicit = _check_size(explicit, "size")
    forge_size = read_forge_size(project_root)

    if forge_size is not None:
        # Inside forge, forge's size wins over the caller's; a genuine conflict takes the LARGER.
        declared: Optional[str] = _larger(forge_size, explicit) if explicit is not None else forge_size
        source: Optional[str] = "forge"
    elif explicit is not None:
        declared, source = explicit, "routing"
    else:
        declared, source = None, None       # review_risk.assess applies L7 rule 6

    requested_by = None
    if user_request:
        # Rule 4: the user asked for the top model. It outranks forge and routing alike, and it
        # suppresses risk promotion below, because TOP is already what promotion would buy.
        source, requested_by = "user", "user"

    try:
        assessment = review_risk.assess(paths, symbols, size=declared, size_source=source,
                                        user_request=user_request)
    except review_risk.ReviewRiskError as exc:
        raise SeatModelError(f"size: {exc}") from None
    return SizeDecision(assessment.size, str(assessment.size_source), requested_by)


def model_class_of(model: Any) -> str:
    """Which budget a codex model spends, from the SLUG alone (D16; #302): a roster non-TOP tier
    (CODEX_STD or CODEX_SUPPORT) spends the std budget, everything else the TOP one.

    The FALLBACK for a caller that has only a slug. A caller holding a resolved pin uses
    pin_model_class(), which also knows the ROW the pin came from. Never re-derived from the size:
    a seat outside SIZED_ROLES (arbiter, consultant_support) ignores the size, so a size-derived
    class would bill the wrong budget for exactly those seats.
    """
    return codex_quota.MODEL_CLASS_STD if model in CODEX_NON_TOP_TIERS else codex_quota.MODEL_CLASS_TOP


def pin_model_class(pin: "SeatPin") -> str:
    """Which budget a resolved codex pin spends (#302 design s3.2, challenger #7; main-loop ruling R1).

    STD when EITHER the resolving row is non-TOP (the consultant_support literal, a sized std row, an
    env slug that passed the support ceiling - all resolve from a KIND_LITERAL row) OR the model it
    serves is a roster non-TOP tier (a TOP seat FROZEN onto CODEX_STD / CODEX_SUPPORT spends no
    astra). TOP otherwise. A pin without a row kind (built by hand) falls back to the slug.

    D21 fix round 1 (F1b): FIRST, a pin whose served model is the current ROSTER TOP resolution (the
    roster document and tops record, the logic TOP seats use, at every TOP-row effort; the home-tier
    freeze excluded) is TOP regardless of row kind - so astra is never billed std, even from a literal
    row. Consequence: an UNFROZEN vendor inversion onto a tier bills that tier as TOP (it is what the
    TOP seats serve; `check` FAILs that state). When the TOP cannot be determined the row/tier rule
    decides. The served model can still LOWER a TOP row's class (R1), never make the TOP std.

    D21 fix round 2 (N1): the F1b set is FREEZE-PROOF - _codex_top_models(include_freeze=False)
    ignores a tops record the freeze wrote - and a TOP-row pin serving the active freeze skips F1b,
    so the frozen TOP seats are always billed by R1 (a freeze onto a tier is std). F1b still bills a
    LITERAL row serving the roster TOP (a support tier mis-set to astra) TOP, frozen or not.
    """
    # D21 fix round 1 (F1b, m5): the served model is the ROSTER TOP now -> TOP, whatever the row. A
    # literal row whose slug is the TOP (CODEX_SUPPORT mis-set to astra, a priority tie) would
    # otherwise bill astra as std. The freeze is deliberately NOT consulted here: a deliberate freeze
    # onto a tier model keeps R1's lowering. Undeterminable (invalid roster, unreadable tops) ->
    # the row/tier rule below, unchanged.
    paths = _paths()
    # D21 fix round 2 (N1): a TOP-row pin serving the ACTIVE FREEZE is a deliberate freeze - R1
    # decides (a freeze onto a tier is std, onto astra is TOP), even when the roster also ranks the
    # frozen slug first. Read defensively: an unreadable pins file is simply "no freeze" here.
    try:
        active_freeze = _freeze_pin(paths, CODEX)
    except (_ResolutionFailure, OSError, ValueError, TypeError):
        active_freeze = None
    skip_top_rule = pin.row_kind == KIND_TOP and active_freeze is not None and pin.model == active_freeze
    tops = None if skip_top_rule else _codex_top_models(paths, None, include_freeze=False)
    if tops is not None and pin.model in tops:
        return codex_quota.MODEL_CLASS_TOP
    if pin.row_kind is not None and pin.row_kind != KIND_TOP:
        return codex_quota.MODEL_CLASS_STD
    return model_class_of(pin.model)


def _sized_row(role: str, row: RoleRow, decision: Optional[SizeDecision], user_request: bool) -> RoleRow:
    """The row this CALL resolves against: a light/medium main seat serves the std model.

    The effort is the role's own, untouched - a size changes WHICH MODEL serves the seat, never
    how hard it thinks. Returning a KIND_LITERAL row means the std path reuses every existing
    rule (roster membership, effort support, timeout, env refusal) instead of growing a second.
    """
    if decision is None:
        return row
    if role in USER_PROMOTED_ROLES and row.kind == KIND_LITERAL and user_request:
        # The astra reserve F7: an explicit user request still buys TOP on consultant_main, at its effort.
        return RoleRow(KIND_TOP, effort=row.effort)
    if role not in SIZED_ROLES or row.kind != KIND_TOP:
        return row
    if user_request or decision.size not in STD_SIZES:
        return row
    return RoleRow(KIND_LITERAL, value=CODEX_STD_MODEL, effort=row.effort)


def _size_recorded(role: str, user_request: bool) -> bool:
    """Does this seat's provenance record the size decision? A sized seat always; a user-promoted seat only
    when the user asked (its size moved nothing otherwise, and provenance never claims a size it ignored)."""
    return role in SIZED_ROLES or (role in USER_PROMOTED_ROLES and user_request)


# --------------------------------------------------------------------------- #
# Home-tier inputs
# --------------------------------------------------------------------------- #
def _freeze_pin(paths: _Paths, provider: str) -> Optional[str]:
    """The provider's frozen TOP, None when not frozen. A malformed pins file or entry is
    a _ResolutionFailure - never 'no freeze'."""
    status, doc = _read_json(paths.pins)
    if status == "absent":
        return None
    if status != "ok" or not isinstance(doc, dict) or doc.get("schema") != PINS_SCHEMA \
            or not isinstance(doc.get("pins"), dict):
        raise _ResolutionFailure(
            f"freeze pins file {paths.pins} is not a valid {PINS_SCHEMA} document; a freeze "
            f"that cannot be read cannot be honoured, and ignoring it would silently unfreeze")
    pins = doc["pins"]
    if provider not in pins:
        return None
    pin = pins[provider]
    top = pin.get("top") if isinstance(pin, dict) else None
    if not isinstance(top, str) or not top:
        raise _ResolutionFailure(
            f"freeze pin for {provider} in {paths.pins} has no usable `top` slug: {pin!r}")
    if provider == CLAUDE and is_benched(top):
        # #291: no Claude path reads a freeze today; if one ever does, a benched pin is refused.
        raise _ResolutionFailure(
            f"freeze pin for {provider} in {paths.pins} names a benched model {top!r} "
            f"(model roster rev {ROSTER_REVISION})")
    return top


def _tops_record(paths: _Paths, provider: str) -> Dict[str, Any]:
    status, doc = _read_json(paths.tops)
    if status != "ok" or not isinstance(doc, dict) or not isinstance(doc.get("tops"), dict):
        return {}
    record = doc["tops"].get(provider)
    return record if isinstance(record, dict) else {}


def _str_key(record: Dict[str, Any], key: str) -> Optional[str]:
    value = record.get(key)
    return value if isinstance(value, str) and value else None


def _last_top(paths: _Paths, provider: str) -> Optional[str]:
    """The SERVED model of the last recorded resolution — what the stale-roster rule keeps."""
    return _str_key(_tops_record(paths, provider), "top")


def _last_priority_winner(paths: _Paths, provider: str) -> Optional[str]:
    """#282 fix round 1 (F10, K44): the incumbent R16 consults on a tie.

    `priority_winner` when the record carries it (a followed upgrade put a slug from OUTSIDE the
    tie into `top`, so `top` alone would not be found in the next tied set and the tie would fall
    to slug — silently downgrading off the superseded winner). Else `top`, which is every record
    written before this round and every selection that followed no upgrade.
    """
    record = _tops_record(paths, provider)
    return _str_key(record, PRIORITY_WINNER) or _str_key(record, "top")


def _record_top(paths: _Paths, provider: str, top: str, roster_fetched_at: Optional[str],
                tie: Optional[Tuple[str, Tuple[str, ...]]] = None,
                priority_winner: Optional[str] = None) -> bool:
    """Best-effort atomic update of seat-model-tops.json. Never raises.

    `tie` (#282 R16) = (tie_break, tied_with) when `top` came from a tied codex selection: the
    record then carries both keys. Without it the provider's record is written without them, so a
    tie that no longer holds leaves no stale keys behind.

    `priority_winner` (#282 fix round 1 F10, K44) is the slug the priority rules chose, and is
    written only when it DIFFERS from `top`. A rewrite that leaves `top` UNCHANGED and names none
    of its own CARRIES FORWARD the recorded one (a freeze, a stale-roster kept TOP, a repeated
    resolution), so a spell of staleness cannot erase the incumbent; a rewrite that MOVES `top`
    without naming one drops it, because it describes a selection that is over.
    """
    tmp: Optional[Path] = None
    try:
        now_iso = _iso_z(_now())
        status, doc = _read_json(paths.tops)
        tops: Dict[str, Any] = {}
        if status == "ok" and isinstance(doc, dict) and doc.get("schema") == TOPS_SCHEMA \
                and isinstance(doc.get("tops"), dict):
            tops = {k: v for k, v in doc["tops"].items() if k in (CODEX, AGY) and isinstance(v, dict)}
        prior = tops.get(provider, {})
        old = prior.get("top") if isinstance(prior.get("top"), str) else None
        if old == top:
            previous = prior.get("previous") if isinstance(prior.get("previous"), str) else None
            changed_at = prior.get("changed_at") if isinstance(prior.get("changed_at"), str) else None
        elif old is None:
            previous, changed_at = None, None
        else:
            previous, changed_at = old, now_iso
        tops[provider] = {
            "top": top,
            "previous": previous,
            "changed_at": changed_at,
            "resolved_at": now_iso,
            "roster_fetched_at": roster_fetched_at,
        }
        if tie is not None:
            tops[provider][TIE_BREAK] = tie[0]
            tops[provider][TIED_WITH] = list(tie[1])
        # #282 fix round 1 (F10, K44): an EVENT KEY. Carried forward only while `top` stands.
        winner = priority_winner if priority_winner is not None else (
            _str_key(prior, PRIORITY_WINNER) if old == top else None)
        if winner is not None and winner != top:
            tops[provider][PRIORITY_WINNER] = winner
        text = json.dumps({"schema": TOPS_SCHEMA, "tops": tops}, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        paths.tops.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.tops.with_name(f".{paths.tops.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp, paths.tops)
        tmp = None
        return True
    except Exception:
        return False
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def _quota_state(paths: _Paths) -> str:
    try:
        state = codex_quota.snapshot(sessions_dir=paths.codex_sessions).get("state")
    except Exception:
        return codex_quota.STATE_UNKNOWN
    # uncertain (#282 R6) passes through: a reading exists but a newer one may be unread.
    if state in (codex_quota.STATE_FRESH, codex_quota.STATE_STALE, codex_quota.STATE_UNCERTAIN,
                 codex_quota.STATE_UNKNOWN):
        return state
    return codex_quota.STATE_UNKNOWN


def _env_value(env_var: Optional[str]) -> str:
    if env_var is None:
        return ""
    return (os.environ.get(env_var) or "").strip()


def _env_refusal(env_var: str, value: str, reason: str) -> Dict[str, str]:
    return {"var": env_var, "value": value, "reason": reason}


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
def _resolve_claude(role: str, row: RoleRow, env_var: Optional[str],
                    effort_env_var: Optional[str] = None) -> SeatPin:
    """The vendor alias (the row's roster tier). Reads no codex/agy roster, no pins, no tops,
    no meter; writes nothing. #291: records `roster_rev`, and refuses a BENCHED env value on
    every seat - the row value is then served, never "omit and inherit".

    #311: the pin carries the row's EFFORT, recorded in provenance as `effort` and
    `effort_source`. An env effort (`effort_env_var`) follows the model rule: on a protected
    seat it is honoured only when it equals the row literal; on consultant_support any level
    Claude Code accepts; anything else is refused and recorded as `effort_override_refused`."""
    alias = str(row.value)
    model, source = alias, "harness_literal"
    provenance: Dict[str, Any] = {
        "requested_selector": _selector_text(row, None),
        "resolved_model": alias,
        "source": source,
        "roster_fetched_at": None,
        "quota_state": None,
        ROSTER_REV: ROSTER_REVISION,
    }
    raw = _env_value(env_var)
    if raw:
        if is_benched(raw):
            provenance["env_override_refused"] = _env_refusal(
                env_var, raw, f"{raw!r} is benched by the model roster (rev {ROSTER_REVISION}, "
                              f"benched {sorted(model_roster.CLAUDE_BENCHED)})")
        elif role in PROTECTED:
            if raw == alias:
                model, source = raw, "env"
            else:
                provenance["env_override_refused"] = _env_refusal(
                    env_var, raw, f"{role} is protected: env is honoured only when equal to {alias!r}")
        elif raw in CLAUDE_ALIASES:
            model, source = raw, "env"
        else:
            provenance["env_override_refused"] = _env_refusal(
                env_var, raw, f"not a Claude vendor alias ({sorted(CLAUDE_ALIASES)})")
    provenance["source"] = source

    literal = row.effort
    if literal is not None and literal not in CLAUDE_EFFORTS:
        raise SeatModelError(f"{role} x claude: the role table effort {literal!r} is not one of {list(CLAUDE_EFFORTS)}")
    if literal is None and role in PROTECTED:
        # #311 fix round 2 item 6: a protected seat without a pinned effort would inherit the
        # user's global level. A table bug, so it raises whatever fail_open says.
        raise SeatModelError(f"{role} x claude: a protected seat has no pinned effort in the role table")
    effort, effort_source = literal, "harness_literal"
    raw_effort = _env_value(effort_env_var)
    if raw_effort:
        if role in PROTECTED:
            if raw_effort == literal:
                effort_source = "env"
            else:
                provenance["effort_override_refused"] = _env_refusal(
                    effort_env_var, raw_effort,
                    f"{role} is protected: an env effort is honoured only when equal to {literal!r}")
        elif raw_effort in CLAUDE_EFFORTS:
            effort, effort_source = raw_effort, "env"
        else:
            provenance["effort_override_refused"] = _env_refusal(
                effort_env_var, raw_effort, f"not a Claude effort level ({list(CLAUDE_EFFORTS)})")
    provenance["effort"] = effort
    provenance["effort_source"] = effort_source
    return SeatPin(model=model, effort=effort, timeout=int(row.timeout or 0),
                   argv_fragment=_claude_argv(model, effort, protected=role in PROTECTED), provenance=provenance)


def _claude_argv(model: str, effort: Optional[str], *, protected: bool = False) -> Tuple[str, ...]:
    """#311 fix round 1 F1: a Claude pin spells its model AND its effort, so a launcher that
    splices the fragment runs the seat at the pinned effort, never the user's global level.
    Fix round 2 item 6: for a protected seat `--effort` is never silently dropped."""
    if effort is None:
        if protected:
            raise SeatModelError("a protected Claude seat's argv must carry --effort; no effort was pinned")
        return ("--model", model)
    return ("--model", model, "--effort", effort)


def _check_codex_word(slug: str, what: str) -> None:
    if not isinstance(slug, str) or _SAFE_WORD.fullmatch(slug) is None:
        raise _ResolutionFailure(f"{what} {slug!r} is not a safe shell word (the pin is expanded unquoted)")


def _lists_no_eligible_top(doc: codex_model.RosterDocument, effort: str) -> bool:
    """True when the LOADED roster has no entry select_top could rank for `effort` (the
    adapter's own rule: a numeric priority and no ineligibility). select_top re-reads the
    file, so a failure it raises for any other reason (the file vanished or broke between
    reads) is a broken resolver, never "no eligible model"."""
    return not any(entry.priority is not None and codex_model._ineligibility(entry, effort) is None
                   for entry in doc.entries.values())


def _codex_top_models(paths: _Paths, doc: Optional[codex_model.RosterDocument], *,
                      include_freeze: bool) -> Optional[FrozenSet[str]]:
    """The models the codex TOP seats resolve to NOW, at every TOP-row effort; None when that cannot
    be determined (D21 fix round 1, F1). SIDE-EFFECT FREE: the same roster-document / tops-record
    rules _resolve_codex applies to a TOP row (the stale "keep the last TOP" rule, then select_top
    with the recorded priority winner as incumbent), but nothing is recorded.

    include_freeze: a home-tier freeze pin, when set, is what every TOP seat serves (the env ceiling
    counts it; validated per effort, a slug that no longer resolves counts as the harness literal the
    seat falls open to); billing excludes it so R1's deliberate freeze onto a tier still lowers to
    std - and, excluded, a tops record whose `top` IS the active freeze is not trusted (N1).
    No roster -> the harness literal (what TOP seats fall open to); an invalid roster, a malformed
    pins file or tops record -> None.
    """
    try:
        # Every effort a TOP selector can be asked for: the TOP rows', plus every budgeted literal row's (a
        # user request or a TOP retry resolves TOP at that row's effort - the astra reserve F7 / F3).
        efforts = {str(rows[CODEX].effort) for role, rows in ROLE_TABLE.items()
                   if CODEX in rows and (rows[CODEX].kind == KIND_TOP or role in ADMITTED_ROLES)}
        if include_freeze:
            frozen = _freeze_pin(paths, CODEX)      # malformed -> _ResolutionFailure -> None (below)
        else:
            try:                                    # billing only reads it to distrust its record
                frozen = _freeze_pin(paths, CODEX)
            except _ResolutionFailure:
                frozen = None
        if include_freeze and frozen is not None:
            # D21 fix round 2 (N2): validate the freeze as _resolve_codex does. A frozen slug that
            # no longer resolves at an effort sends that TOP seat to the harness literal (fail-open),
            # so the set names what the TOP seats would ACTUALLY serve, not only the frozen slug.
            try:
                _check_codex_word(frozen, "codex freeze pin")
            except _ResolutionFailure:
                return frozenset({CODEX_TOP_HARNESS_LITERAL})
            if doc is None:
                doc, _why, _invalid = _load_codex_doc(paths)
            if doc is None:
                return frozenset({frozen})          # no roster to validate against: served as-is
            entry = doc.entries.get(frozen)
            return frozenset(frozen if entry is not None and codex_model._ineligibility(entry, eff) is None
                             else CODEX_TOP_HARNESS_LITERAL for eff in efforts)
        if doc is None:
            doc, _why, invalid = _load_codex_doc(paths)
            if invalid:
                return None
            if doc is None:
                return frozenset({CODEX_TOP_HARNESS_LITERAL})
        stale = _is_stale(doc.fetched_at)
        incumbent = _last_priority_winner(paths, CODEX)
        last = _last_top(paths, CODEX) if stale else None
        if not include_freeze and frozen is not None and _last_top(paths, CODEX) == frozen:
            # D21 fix round 2 (N1): while a freeze is active every TOP resolution records the FROZEN
            # slug as `top`, so that record says what the freeze served, not what the roster would.
            # Trusting it (the stale keep-last rule, the tie incumbent) made the freeze-excluded set
            # the freeze itself. Derive from the roster alone.
            incumbent, last = None, None
        out = set()
        for eff in efforts:
            if last is not None and last in doc.entries \
                    and codex_model._ineligibility(doc.entries[last], eff) is None:
                out.add(last)
                continue
            try:
                out.add(codex_model.select_top(eff, cache_path=paths.codex_roster, incumbent=incumbent).model)
            except (codex_model.CodexRosterAbsentError, codex_model.CodexRosterInvalidError):
                return None
            except codex_model.CodexModelError:
                out.add(CODEX_TOP_HARNESS_LITERAL)      # no eligible TOP: TOP seats fall open to it
        return frozenset(out)
    except (_ResolutionFailure, OSError, ValueError, TypeError):
        return None


def _support_env_ceiling_refusal(doc: codex_model.RosterDocument, raw: str, *, base: Optional[str] = None,
                                 paths: Optional[_Paths] = None) -> Optional[str]:
    """#282 r13: why a NON-protected codex seat must refuse env slug `raw`, else None.

    The ceiling is the consultant_support literal (model_roster.CODEX_SUPPORT; it ranks against the
    row's own value, so a tier swap rebases it with no code change). TWO independent refusals
    (#282 fix round 1 F7, plan K46 — which SUPERSEDES K21's literal reading):
      (a) VISIBILITY. An entry whose `visibility` is not exactly "list" is refused outright —
          hidden, field absent, or any other value, read fail-closed. K21 read the predicate
          literally, so a HIDDEN entry ranked above the ceiling passed; env could then buy an
          unmetered astra-class model for a support seat merely because the vendor hid it
          (the live roster's gpt-reserve is exactly that shape: priority 3, `hide`).
      (b) RANK, regardless of visibility. A numeric priority strictly lower than the ceiling's
          ranks above it — astra-class, whether or not it is today's selection winner.

    (c) TIER, regardless of priority (D21 fix round 1, F1a — a TIE with the ceiling, or an unranked
        entry, escaped (b)): a slug that is the CURRENT codex TOP resolution (freeze included) or is
        CODEX_STD while the seat's `base` is not CODEX_STD is refused, unless it equals `base`. An
        undeterminable TOP refuses (fail closed).

    Under (b) a TIE with the ceiling is accepted, and an entry with no numeric priority is not
    refused by this rule (an unranked entry cannot be ranked above anything); (c), checked after (b),
    is what closes those. When the ceiling itself is not
    a listed, ranked entry nothing can be ranked against it, so every slug reaching this check is
    refused (the seat's own base is accepted before it is called). (a) and (b) read only the loaded
    document; (c) also reads the home-tier freeze pins and tops record (never writes).
    """
    ceiling = str(ROLE_TABLE[CONSULTANT_SUPPORT][CODEX].value)
    top = doc.entries.get(ceiling)
    if top is None or top.visibility != "list" or top.priority is None:
        return (f"the ceiling {ceiling!r} is not a listed, ranked codex roster entry, so no env slug "
                f"can be ranked against it")
    entry = doc.entries[raw]
    if entry.visibility != "list":
        return (f"is not a listed codex roster entry (visibility {entry.visibility!r}); an unmetered "
                f"seat is never bought a hidden model")
    if entry.priority is not None and entry.priority < top.priority:
        return f"ranks above {ceiling} among listed roster entries (priority {entry.priority:g} < {top.priority:g})"
    # D21 fix round 1 (F1a): TIER refusals, independent of priority (priorities flap and tie). The
    # seat's own base is accepted before this is called, so a std == support revert stays legal.
    if raw != base:
        tops = _codex_top_models(paths if paths is not None else _paths(), doc, include_freeze=True)
        if tops is None:
            return ("the current codex TOP cannot be determined, so an env slug cannot be shown not "
                    "to be it")
        if raw in tops:
            return f"is the current codex TOP resolution ({sorted(tops)}); a support seat never serves it"
        if raw == CODEX_STD_MODEL and base != CODEX_STD_MODEL:
            return (f"is CODEX_STD ({CODEX_STD_MODEL}) while this seat's base {base!r} is not; env never "
                    f"lifts a support seat onto a higher tier")
    return None


def _load_codex_doc(paths: _Paths) -> Tuple[Optional[codex_model.RosterDocument], Optional[str], bool]:
    """-> (document, why it is unusable, invalid?). #282 R4: absent -> (None, why, False); invalid
    -> (None, why, True). codex_model raises only its own errors for any field type (K14)."""
    try:
        return codex_model.load_roster_entries(paths.codex_roster), None, False
    except codex_model.CodexRosterInvalidError as exc:
        return None, str(exc), True
    except codex_model.CodexModelError as exc:
        return None, str(exc), False


def _resolve_codex(role: str, row: RoleRow, paths: _Paths, *, env_var: Optional[str], fail_open: bool,
                   effort: Optional[str], decision: Optional["SizeDecision"] = None,
                   user_request: bool = False, top_retry: bool = False) -> SeatPin:
    # The astra reserve U2/F3: a TOP retry resolves the TOP selector at the role's OWN effort, whatever the
    # row or the size says - the one path back to the reserve for a std seat that failed on capability.
    row = RoleRow(KIND_TOP, effort=row.effort) if top_retry else _sized_row(role, row, decision, user_request)
    eff = effort if effort is not None else str(row.effort)
    doc, load_error, roster_invalid = _load_codex_doc(paths)
    fetched_at = doc.fetched_at if doc is not None else None
    stale = doc is not None and _is_stale(fetched_at)
    extras: Dict[str, Any] = {}
    record: Optional[str] = None
    frozen: Optional[str] = None
    tie: Optional[Tuple[str, Tuple[str, ...]]] = None
    winner: Optional[str] = None      # #282 fix round 1 (F10): select_top's priority_winner
    if roster_invalid:
        # #282 R4: an invalid roster is recorded on every path, the freeze included.
        extras[ROSTER_INVALID] = True
    # #282 fix round 1 F13 (K43): likewise a PARTIAL roster. This is a fact about the document
    # that was read, not about the selection, so it rides every codex path — TOP, literal and
    # freeze alike — and it survives the fail-open branch below exactly as roster_invalid does.
    skipped = list(doc.entries_skipped) if doc is not None else []
    if skipped:
        extras[ROSTER_ENTRIES_SKIPPED] = skipped

    try:
        if row.kind == KIND_TOP:
            pin = _freeze_pin(paths, CODEX)
            if pin is not None:
                frozen = pin
                _check_codex_word(pin, "codex freeze pin")
                if doc is not None:
                    entry = doc.entries.get(pin)
                    if entry is None:
                        raise _ResolutionFailure(
                            f"codex freeze pin {pin!r} is not in the codex roster {doc.path}")
                    why = codex_model._ineligibility(entry, eff)
                    if why is not None:
                        raise _ResolutionFailure(f"codex freeze pin rejected for effort {eff!r}: {why}")
                base, source, record = pin, "freeze", pin
            elif roster_invalid:
                raise _ResolutionFailure(f"{ROSTER_INVALID}: {load_error}")
            elif doc is None:
                base, source = CODEX_TOP_HARNESS_LITERAL, "harness_literal"
                extras["fallback_reason"] = f"no codex roster: {load_error}"
            else:
                base = None
                # #282 R16 (K26): the incumbent is the recorded TOP as it stands BEFORE this
                # resolution rewrites the record; select_top consults it only on a tie.
                # #282 fix round 1 (F10, K44): it is the recorded `priority_winner` when one was
                # written, so a followed upgrade does not take the incumbent out of the tied set.
                # The stale-roster "keep the last TOP" rule below still reads `top`: that rule is
                # about the model that was SERVED, not the one the priority rules chose.
                incumbent = _last_priority_winner(paths, CODEX)
                last = _last_top(paths, CODEX) if stale else None
                if last is not None and last in doc.entries \
                        and codex_model._ineligibility(doc.entries[last], eff) is None:
                    base = last
                if base is None:
                    try:
                        selection = codex_model.select_top(eff, cache_path=paths.codex_roster,
                                                           incumbent=incumbent)
                    except codex_model.CodexModelError as exc:
                        # The re-read found no roster or an invalid one (the file changed
                        # between the two reads): a broken resolver, never "no eligible".
                        reread_broke = isinstance(
                            exc, (codex_model.CodexRosterAbsentError, codex_model.CodexRosterInvalidError))
                        if not reread_broke and _lists_no_eligible_top(doc, eff):
                            raise _NoEligibleModel(str(exc)) from None
                        raise _ResolutionFailure(str(exc)) from None
                    base = selection.model
                    winner = selection.priority_winner
                    if selection.upgrade_followed:
                        extras["upgrade_followed"] = True
                    if selection.upgrade_ignored_reason is not None:
                        extras["upgrade_ignored_reason"] = selection.upgrade_ignored_reason
                    if selection.tie_break is not None:
                        # #282 R16 (K25): event keys, present only when the selection was tied.
                        tie = (selection.tie_break, tuple(selection.tied_with))
                        extras[TIE_BREAK] = tie[0]
                        extras[TIED_WITH] = list(tie[1])
                # A stale roster never REPLACES the kept TOP: a per-effort fallback (the kept
                # TOP lacks this effort) is served but not recorded, or the next seat would
                # lose the very TOP the stale rule exists to keep.
                source, record = "roster", (base if last is None or base == last else None)
        else:  # KIND_LITERAL
            base = str(row.value)
            if roster_invalid:
                raise _ResolutionFailure(f"{ROSTER_INVALID}: {load_error}")
            if doc is None:
                source = "harness_literal"
                extras["fallback_reason"] = f"no codex roster: {load_error}"
            else:
                entry = doc.entries.get(base)
                # The astra reserve F1: on a BUDGETED seat (a Sol literal) a valid roster that does not
                # serve the pinned model at this effort means codex cannot serve the seat - "no eligible
                # model", substitutable (D6) exactly like a TOP seat with no eligible TOP. The support
                # literal keeps its gap semantics: consultant_support is never substituted (#302).
                failure = _NoEligibleModel if role in ADMITTED_ROLES else _ResolutionFailure
                if entry is None:
                    raise failure(f"pinned codex model {base!r} is not in the codex roster {doc.path}")
                if role in ADMITTED_ROLES:
                    # Fix round 1 item 9: a budgeted Sol literal takes the TOP eligibility rule - listed,
                    # API-supported and offering the effort - so a hidden or non-API Sol is "no eligible".
                    why = codex_model._ineligibility(entry, eff)
                    if why is not None:
                        raise failure(f"pinned codex model not eligible: {why}")
                elif eff not in entry.efforts:
                    raise failure(
                        f"effort {eff!r} is not supported by {base!r} (roster: {sorted(entry.efforts)})")
                source = "roster"
        _check_codex_word(base, "codex model")
        try:
            timeout = codex_model.timeout_for(base, eff)
        except codex_model.CodexModelError as exc:
            raise _ResolutionFailure(str(exc)) from None
    except _ResolutionFailure as exc:
        no_eligible = isinstance(exc, _NoEligibleModel)
        if not fail_open:
            error_type = NoEligibleModelError if no_eligible else SeatModelError
            raise error_type(f"{role} x codex: {exc}") from None
        base = CODEX_TOP_HARNESS_LITERAL if row.kind == KIND_TOP else str(row.value)
        source, record, tie = "harness_literal", None, None
        extras = {"fallback_reason": str(exc)}
        if no_eligible:
            extras["unavailable_reason"] = UNAVAILABLE_NO_ELIGIBLE
        if roster_invalid:
            extras[ROSTER_INVALID] = True
        if skipped:
            extras[ROSTER_ENTRIES_SKIPPED] = skipped
        try:
            timeout = codex_model.timeout_for(base, eff)
        except codex_model.CodexModelError as inner:
            # The literal itself is untabulated: a harness inconsistency, not an environment
            # failure, so there is nothing safe to fall back to.
            raise SeatModelError(f"{role} x codex: {inner}") from None

    model, final_source, timeout_final = base, source, timeout
    provenance: Dict[str, Any] = {
        "requested_selector": _selector_text(row, eff),
        "resolved_model": base,
        "source": source,
        "roster_fetched_at": fetched_at,
        "quota_state": _quota_state(paths),
    }
    if row.kind == KIND_LITERAL and row.value in CODEX_NON_TOP_TIERS:
        # #291: a codex tier resolution (std, and since #302 support) names the model roster
        # revision its slug came from.
        provenance[ROSTER_REV] = ROSTER_REVISION
    if row.kind == KIND_TOP and base in CODEX_NON_TOP_TIERS:
        # #302 (challenger #4): a TOP selector landed on a roster non-TOP tier - a vendor priority
        # inversion (astra and gpt-6-sol are one generation, so a tie is no longer broken by it) or
        # a freeze onto a tier model. The seat still follows the roster/freeze; this makes it visible.
        provenance[TOP_RESOLVED_TO_STD] = True
    if stale:
        provenance["roster_stale"] = True
    provenance.update(extras)
    if top_retry:
        provenance[TOP_RETRY_USE] = True
    if decision is not None and _size_recorded(role, user_request) and not top_retry:
        # ONLY on a size-aware resolution of a SIZED seat (or a user-promoted one the user asked for). An unsized call, and every seat that
        # is not size-aware, keep their provenance key for key - that is the back-compat rule in
        # code, and it is what the DEFAULT `emit --json` is pinned on (plan L12).
        provenance["size"] = decision.size
        provenance["size_source"] = decision.size_source
        if decision.requested_by is not None:
            provenance["requested_by"] = decision.requested_by

    raw = _env_value(env_var)
    if raw:
        if role in PROTECTED:
            if raw == base:
                final_source = "env"
            else:
                provenance["env_override_refused"] = _env_refusal(
                    env_var, raw, f"{role} is protected: env is honoured only when equal to {base!r}")
        elif raw == base:
            # #282 r13: the seat's own base first, so no rule below can refuse it (a freeze onto
            # model X never refuses X). The served model does not change.
            final_source = "env"
        else:
            reason = None
            if _SAFE_WORD.fullmatch(raw) is None:
                reason = "not a safe shell word"
            elif doc is None:
                reason = "no readable codex roster to validate it against"
            elif raw not in doc.entries:
                reason = "not in the codex roster"
            elif eff not in doc.entries[raw].efforts:
                reason = f"does not support effort {eff!r}"
            else:
                reason = _support_env_ceiling_refusal(doc, raw, base=base, paths=paths)
            if reason is None:
                try:
                    timeout_final = codex_model.timeout_for(raw, eff)
                    model, final_source = raw, "env"
                except codex_model.CodexModelError as exc:
                    reason = str(exc)
            if reason is not None:
                provenance["env_override_refused"] = _env_refusal(env_var, raw, reason)
    provenance["source"] = final_source
    if final_source == "freeze" and frozen is not None:
        provenance[FROZEN_SLUG] = frozen          # #282 r14: the pins-file top as written

    if record is not None:
        _record_top(paths, CODEX, record, fetched_at, tie, winner)
    return SeatPin(model=model, effort=eff, timeout=timeout_final,
                   argv_fragment=tuple(codex_model.argv_fragment(model, eff)), provenance=provenance,
                   row_kind=row.kind)


def _load_agy_models(paths: _Paths) -> Tuple[Optional[FrozenSet[str]], Optional[str], Optional[str]]:
    """-> (listed slugs or None, fetched_at, why unusable)."""
    status, doc = _read_json(paths.agy_roster)
    if status == "absent":
        return None, None, f"no agy roster cache at {paths.agy_roster}"
    if status != "ok" or not isinstance(doc, dict) or doc.get("schema") != AGY_ROSTER_SCHEMA \
            or not isinstance(doc.get("models"), list):
        return None, None, f"agy roster cache {paths.agy_roster} is not a valid {AGY_ROSTER_SCHEMA} document"
    fetched_at = doc.get("fetched_at")
    models = frozenset(m for m in doc["models"] if isinstance(m, str))
    return models, fetched_at if isinstance(fetched_at, str) else None, None


def _agy_top(models: FrozenSet[str], level: str) -> Optional[str]:
    candidates = sorted(m for m in models if is_agy_family(m) and m.endswith(f"-{AGY_FAMILY}-{level}"))
    if not candidates:
        return None
    return max(candidates, key=lambda slug: _version_key(_agy_version(slug)))


def _assert_agy_family(model: str, role: str) -> None:
    if not is_agy_family(model):
        raise SeatModelError(f"{role} x agy: {model!r} violates {AGY_FAMILY_RULE}")


def _resolve_agy(role: str, row: RoleRow, paths: _Paths, *, env_var: Optional[str], fail_open: bool,
                 decision: Optional[SizeDecision] = None, user_request: bool = False) -> SeatPin:
    # #367 WP-C: a sized call serves the level its size maps to (the level is part of the slug, so the
    # size picks WHICH MODEL serves - never an effort). Unsized, the row's own level stands.
    level = agy_level_for(row, decision, user_request)
    if level != row.level:
        row = RoleRow(row.kind, value=row.value, effort=row.effort, level=level, timeout=row.timeout)
    models, fetched_at, load_error = _load_agy_models(paths)
    stale = models is not None and _is_stale(fetched_at)
    extras: Dict[str, Any] = {}
    record: Optional[str] = None
    frozen: Optional[str] = None

    try:
        pin = _freeze_pin(paths, AGY)
        if pin is not None:
            frozen = pin
            if not is_agy_family(pin):
                raise _ResolutionFailure(f"agy freeze pin {pin!r} violates {AGY_FAMILY_RULE}")
            version = _agy_version(pin)
            base = f"gemini-{version}-{AGY_FAMILY}-{level}"
            if models is not None and base not in models:
                raise _ResolutionFailure(
                    f"agy freeze pin {pin!r} gives {base!r} for level {level!r}, which is not listed in the "
                    f"agy roster cache {paths.agy_roster}")
            source, record = "freeze", f"gemini-{version}-{AGY_FAMILY}"
        elif models is None:
            base, source = AGY_HARNESS_TEMPLATE.format(level=level), "harness_literal"
            extras["fallback_reason"] = str(load_error)
        else:
            base = None
            last = _last_top(paths, AGY) if stale else None
            candidate = f"{last}-{level}" if last is not None else None
            # #367 (Sol C9): an incumbent from a family the roster no longer allows (a recorded
            # `gemini-3.8-flash` after the argon swap) is never kept. It is REPLACED and the new
            # family is recorded even on a stale cache, so the digest announces the change once.
            foreign = candidate is not None and not is_agy_family(candidate)
            if candidate is not None and not foreign and candidate in models:
                base = candidate
            if base is None:
                base = _agy_top(models, level)
                if base is None:
                    raise _ResolutionFailure(
                        f"no eligible agy model for level {level!r} in {paths.agy_roster}: nothing listed "
                        f"matches {AGY_FAMILY_RULE}")
            family = f"gemini-{_agy_version(base)}-{AGY_FAMILY}"
            source, record = "roster", (family if last is None or family == last or foreign else None)
        if not is_agy_family(base):
            raise _ResolutionFailure(f"{base!r} violates {AGY_FAMILY_RULE}")
    except _ResolutionFailure as exc:
        if not fail_open:
            raise SeatModelError(f"{role} x agy: {exc}") from None
        base = AGY_HARNESS_TEMPLATE.format(level=level)
        source, record = "harness_literal", None
        extras = {"fallback_reason": str(exc)}
    _assert_agy_family(base, role)   # every path, fail_open included; nothing gets past this

    model, final_source = base, source
    provenance: Dict[str, Any] = {
        "requested_selector": _selector_text(row, None),
        "resolved_model": base,
        "source": source,
        "roster_fetched_at": fetched_at,
        "quota_state": None,
    }
    if stale:
        provenance["roster_stale"] = True
    provenance.update(extras)

    raw = _env_value(env_var)
    if raw:
        if role in PROTECTED:
            if raw == base:
                final_source = "env"
            else:
                provenance["env_override_refused"] = _env_refusal(
                    env_var, raw, f"{role} is protected: env is honoured only when equal to {base!r}")
        elif is_agy_family(raw):
            model, final_source = raw, "env"
        else:
            provenance["env_override_refused"] = _env_refusal(env_var, raw, f"violates {AGY_FAMILY_RULE}")
    provenance["source"] = final_source
    if final_source == "freeze" and frozen is not None:
        provenance[FROZEN_SLUG] = frozen          # #282 r14: as written, not the level-resolved model
    if decision is not None:
        # #367 WP-C: a sized agy resolution records the size it served, as a sized codex seat does. An
        # unsized one keeps its provenance key for key (the back-compat rule).
        provenance["size"] = decision.size
        provenance["size_source"] = decision.size_source
        if decision.requested_by is not None:
            provenance["requested_by"] = decision.requested_by
    _assert_agy_family(model, role)

    if record is not None:
        _record_top(paths, AGY, record, fetched_at)
    return SeatPin(model=model, effort=None, timeout=int(row.timeout or 0),
                   argv_fragment=("--model", model), provenance=provenance)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def resolve(role: str, provider: str, *, env_var: Optional[str] = None, fail_open: bool = False,
            effort: Optional[str] = None, size: Optional[str] = None, user_request: bool = False,
            project_root: Any = None, changed_paths: Any = (), changed_symbols: Any = (),
            effort_env_var: Optional[str] = None, top_retry: bool = False) -> SeatPin:
    """Resolve one seat. See the module docstring for precedence, env and failure rules.

    `effort=` (I5) overrides the role's effort for CODEX seats only and is validated against
    the roster for the resolved model. A missing row, an unknown role/provider, or an
    `effort=` on a non-codex seat or that is not a plain word is a caller bug and raises
    regardless of `fail_open`.

    SIZE (D16). `size=` / `user_request=` / `project_root=` / `changed_paths=` /
    `changed_symbols=` make this a SIZE-AWARE resolution: the seat resolves through
    `resolve_size` and records `size` / `size_source` (+ `requested_by`) in its provenance.
    A call that passes NONE of them is the back-compat path and is byte-for-byte what it was
    before D16 - same model, same provenance keys - which is what keeps `emit --json` and
    every un-migrated call site unchanged. A size on a Claude seat is a caller bug; on an agy seat it
    picks the level (model_roster.AGY_LEVEL_BY_SIZE, #367 WP-C).

    TOP RETRY (the astra reserve U2/F3). `top_retry=True` resolves the codex TOP selector at the role's
    own effort for ANY protected codex seat (a std literal included) and marks provenance `top_retry`. It
    is codex-only; the caller (`argv --top-retry`) decides whether the result is a legal retry.

    EFFORT (#311). A Claude pin carries its row's effort (`pin.effort`, and `effort` /
    `effort_source` in provenance). `effort_env_var` names the env var that may override it
    under the model rule (protected: only when equal to the literal); it applies to Claude
    seats only, and passing it for another provider is a caller bug.
    """
    row = _row(role, provider)
    if effort_env_var is not None and provider != CLAUDE:
        raise SeatModelError(f"effort_env_var= applies to claude seats only, not {provider}")
    if effort is not None:
        if provider != CODEX:
            raise SeatModelError(f"effort= applies to codex only, not {provider}")
        if not isinstance(effort, str) or _SAFE_WORD.fullmatch(effort) is None:
            raise SeatModelError(f"effort must be a plain word, got {effort!r}")
    size_aware = (size is not None or user_request or project_root is not None
                  or bool(changed_paths) or bool(changed_symbols))
    if size_aware and provider == CLAUDE:
        raise SeatModelError(f"size applies to codex and agy seats only, not {provider}")
    if top_retry and (provider != CODEX or role not in ADMITTED_ROLES):
        raise SeatModelError(f"top_retry applies to the budgeted codex seats only, not {role} x {provider}")
    decision = resolve_size(size, project_root=project_root, user_request=user_request,
                            paths=changed_paths, symbols=changed_symbols) if size_aware else None
    if provider == CLAUDE:
        return _resolve_claude(role, row, env_var, effort_env_var)
    paths = _paths()
    if provider == CODEX:
        return _resolve_codex(role, row, paths, env_var=env_var, fail_open=fail_open, effort=effort,
                              decision=decision, user_request=user_request, top_retry=top_retry)
    return _resolve_agy(role, row, paths, env_var=env_var, fail_open=fail_open, decision=decision,
                        user_request=user_request)


def agy_level_for(row: RoleRow, decision: Optional[SizeDecision], user_request: bool = False) -> str:
    """The level an agy seat serves (#367 WP-C): the row's own level unsized; the
    model_roster.AGY_LEVEL_BY_SIZE level of the resolved size when sized; "high" on a user request."""
    if decision is None:
        return str(row.level)
    if user_request:
        return AGY_USER_REQUEST_LEVEL
    # A roster older than rev 7 has no map (an installed pre-WP-C copy, a test stand-in): the row's level.
    return AGY_LEVEL_BY_SIZE.get(decision.size, str(row.level))


def _pin_json(pin: SeatPin) -> Dict[str, Any]:
    return {
        "model": pin.model,
        "effort": pin.effort,
        "timeout": pin.timeout,
        "argv_fragment": list(pin.argv_fragment),
        "provenance": dict(pin.provenance),
    }


def emit(size: Optional[str] = None, *, user_request: bool = False,
         project_root: Any = None) -> Dict[str, Any]:
    """Every pin in the table, fail-closed (any SeatModelError propagates).

    WITHOUT a size this is the REGISTRY DUMP and its shape is frozen: the same keys and the
    same models as before D16, so every consumer of `emit --json` keeps working (plan L12).
    WITH one it is the SIZED view: the codex cells of the sized main seats resolve through
    `resolve_size`, and the document gains the top-level `size` / `size_source` pair naming
    the size it was rendered at. That pair is the ONLY key this WP may add.
    #291 adds `roster_rev` (model_roster.REVISION) at the top level of EVERY emit, sized or not.
    """
    sized = size is not None or user_request or project_root is not None
    decision = (resolve_size(size, project_root=project_root, user_request=user_request)
                if sized else None)
    pins: Dict[str, Dict[str, Any]] = {}
    for role in ROLES:
        pins[role] = {}
        for provider in PROVIDERS:
            if provider not in ROLE_TABLE[role]:
                continue
            extra: Dict[str, Any] = {}
            if sized and (provider == AGY or (provider == CODEX and _size_recorded(role, user_request))):
                # The ORIGINAL inputs, never the already-resolved size: each pin re-derives the
                # same decision deterministically, so the per-pin provenance and the top-level
                # pair below can never disagree about where the size came from.
                extra = {"size": size, "user_request": user_request, "project_root": project_root}
            pins[role][provider] = _pin_json(resolve(role, provider, fail_open=False, **extra))
    doc: Dict[str, Any] = {"schema": EMIT_SCHEMA, ROSTER_REV: ROSTER_REVISION,
                           AGY_LEVEL_BY_SIZE_KEY: dict(AGY_LEVEL_BY_SIZE), "pins": pins}
    if decision is not None:
        doc["size"], doc["size_source"] = decision.size, decision.size_source
    return doc


def substitute(role: str, use: str, reason: str, *, project_root, cycle_id: Optional[str] = None,
               requested_model: Optional[str] = None, admission_id: Optional[str] = None,
               size: Optional[str] = None, size_source: Optional[str] = None,
               requested_by: Optional[str] = None) -> SeatPin:
    """Serve a codex TOP seat that astra cannot run with its Claude row (amendment 1 D6).

    Returns resolve(role, "claude") - the Claude alias, ALWAYS, never a codex model - with
    provenance extended by {substitute_for: "codex", substitution_reason, requested_model,
    row_written} (+ `row_error` when the row could not be written), and records ONE
    substitution row through codex_quota.record_substitution. The row never spends a
    budget. The budget key is codex_quota.cycle_id_for(project_root) unless `cycle_id` is
    given. The caller runs the seat in a FRESH context with the same brief.
    `admission_id` (#282 r10) is passed through to the row unchanged: the codex_quota.admit()
    decision this substitution replaces, or None. Provenance keys are unchanged.

    Raises SeatModelError, recording nothing, for a caller bug: a role without a codex TOP
    row (consultant_support is the support tier, not astra), use "trial" (the trial is skipped, never
    substituted), half a size pair - `size` without `size_source` or the reverse (D21 f7) -,
    a use / reason / requested_model / admission_id codex_quota refuses, an empty cycle_id,
    or project_root None. A budget-store failure never raises: the seat is still served and
    `row_written` is False.
    """
    _row(role, CODEX)
    if role not in ADMITTED_ROLES:
        # The astra reserve F1: gated on the ROLE, not the row kind. consultant_main and arbiter are std
        # literals since roster rev 4 and are still substituted; consultant_support never is.
        raise SeatModelError(f"{role} is not a budgeted codex seat ({', '.join(sorted(ADMITTED_ROLES))}): "
                             f"only those are substituted")
    if use in SKIPPED_USES:
        raise SeatModelError(f"use {use!r} is skipped when codex cannot serve it, never substituted")
    # Validated BEFORE anything is recorded: a caller bug must not leave a row behind.
    if (size is None) != (size_source is None):
        # S081 rev 4 D21 f7: half a pair is a caller bug (codex_quota._checked_size says so too).
        # Filling the missing half with the back-compat default would record a provenance nobody
        # decided; the default is the truth only when NO size was decided at all.
        raise SeatModelError(f"size and size_source are a pair - pass both (one resolved SizeDecision) or "
                             f"neither (the back-compat default), got size={size!r}, size_source={size_source!r}")
    refused_size = _check_size(size, "substitute size") if size is not None else review_risk.DEFAULT_SIZE
    refused_source = size_source if size_source is not None else review_risk.DEFAULT_SIZE_SOURCE
    if refused_source not in SIZE_SOURCES:
        raise SeatModelError(f"size_source must be one of {', '.join(sorted(SIZE_SOURCES))}, "
                             f"got {size_source!r}")
    if project_root is None:
        raise SeatModelError("project_root is required: it names the budget store and the cycle id")
    pin = resolve(role, CLAUDE)
    model = pin.model
    if not isinstance(model, str) or model.lower().startswith("gpt-"):
        raise SeatModelError(f"refusing to substitute codex with {model!r}: a gpt model draws the same quota")
    cycle = cycle_id if cycle_id is not None else codex_quota.cycle_id_for(project_root)
    try:
        result = codex_quota.record_substitution(
            use, cycle, reason, project_root=project_root, role=role, served_model=model,
            requested_model=requested_model, sessions_dir=_paths().codex_sessions, admission_id=admission_id,
            # The ROW's own size fields (design s2.1: EVERY row records them). The validated
            # pair is passed, not the raw arguments, so the row and this pin's provenance
            # always agree - including on the back-compat default for an unsized caller.
            size=refused_size, size_source=refused_source, requested_by=requested_by)
    except ValueError as exc:
        raise SeatModelError(f"substitution not recorded ({role} x codex, use {use!r}): {exc}") from None
    provenance = dict(pin.provenance)
    provenance.update({
        "substitute_for": CODEX,
        "substitution_reason": reason,
        "requested_model": requested_model,
        "row_written": bool(result.get("row_written")),
        # WHICH SIZE was refused (D16). An unsized caller records the back-compat default, so a
        # row from an un-migrated call site is never read as a refused light call. The budget
        # ROW's own size fields are the design s2.2 schema, in codex_quota - not this WP's file.
        "size": refused_size,
        "size_source": refused_source,
    })
    if not provenance["row_written"]:
        provenance["row_error"] = str(result.get("error") or "the substitution row was not written")
    # #311: the substitute is a fresh Claude main-tier agent, so it runs at that row's effort.
    return SeatPin(model=model, effort=pin.effort, timeout=pin.timeout,
                   argv_fragment=_claude_argv(model, pin.effort, protected=role in PROTECTED),
                   provenance=provenance)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """argparse that never prints to stdout and never exits 0 outside a real answer.

    `--help` is not a pin: `PIN="$(seat_model.py argv --help)" && codex exec $PIN` must not run.
    """

    def print_help(self, file=None):  # noqa: D401
        super().print_help(sys.stderr)

    def print_usage(self, file=None):
        super().print_usage(sys.stderr)

    def exit(self, status=0, message=None):
        raise _UsageError(message.strip() if message else "no pin printed")

    def error(self, message):
        self.print_usage(sys.stderr)
        raise _UsageError(message)


def _add_size_flags(command: argparse.ArgumentParser) -> None:
    """D16, on `argv`, `emit` and `timeout`. NOT on `model`, which is Claude-only."""
    command.add_argument("--size", choices=SIZES,
                         help="the task size this call is (codex and agy seats): on code_reviewer x codex "
                              "light and medium serve " + CODEX_STD_MODEL + ", complex serves TOP; on agy the "
                              "size picks the level (model_roster.AGY_LEVEL_BY_SIZE)")
    command.add_argument("--user-request", action="store_true",
                         help="the user asked for the top model: serve TOP (agy: the high level) whatever the size")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="seat_model.py", description="Resolve review/consultancy/escalation seat models.")
    sub = parser.add_subparsers(dest="command")
    argv_cmd = sub.add_parser(
        "argv", help="print the pinned argv fragment for a codex or agy seat; with --use, admit-and-pin a codex "
                     "TOP seat in one call (exit 0 pin / 3 substitute / 10 trial skipped / 1 broken / 2 usage)")
    argv_cmd.add_argument("--role", required=True, choices=ROLES)
    argv_cmd.add_argument("--provider", required=True, choices=(CODEX, AGY))
    argv_cmd.add_argument("--use", choices=sorted(codex_quota.USES),
                          help="the intended codex call (codex TOP seats only); gates it through codex_quota.admit")
    argv_cmd.add_argument("--project-root", help="with --use: the project whose budget key and store apply "
                                                 "(default: the working directory)")
    argv_cmd.add_argument("--cycle-id", help="with --use: the budget key (default: codex_quota.cycle_id_for)")
    argv_cmd.add_argument("--task-key", help="with --use diagnosis (the per-task budget key) or --use "
                                             "exhausted_review (the D21 review id; required)")
    argv_cmd.add_argument("--top-retry", action="store_true",
                          help="with --use U: the ONE TOP retry of a std seat that failed on capability (the astra "
                               "reserve U2): resolve TOP for the role, admit it as `top_retry`, record the event")
    argv_cmd.add_argument("--failed-admission-id",
                          help="with --top-retry: the admission id of the EXACT failed attempt (its --receipt-file); "
                               "it must be an admitted std-class row of this role, use and key")
    argv_cmd.add_argument("--receipt-file",
                          help="with --use: on an admission (exit 0), write `<admission_id> <key>` to this file - "
                               "what a TOP retry and a later substitution name")
    argv_cmd.add_argument("--await-quota", action="store_true",
                          help="with --use: the caller will WAIT for a quota reset (#322). A quota refusal then "
                               "records no substitution yet and ends its output with `substitution=deferred`")
    argv_cmd.add_argument("--failed-reason", choices=sorted(TOP_RETRY_REASONS),
                          help="with --top-retry: the classify substitute reason (capacity_twice or malformed_twice "
                               "only; quota, auth, budget and timeout outcomes never buy a TOP retry)")
    _add_size_flags(argv_cmd)
    model_cmd = sub.add_parser("model", help="print the model alias for a Claude seat")
    model_cmd.add_argument("--role", required=True, choices=ROLES)
    model_cmd.add_argument("--provider", required=True, choices=(CLAUDE,))
    effort_cmd = sub.add_parser(
        "effort", help="print the reasoning effort for a Claude seat (#311), for workflow agent({effort}) or "
                       "headless --effort; pass it explicitly, never rely on agent frontmatter")
    effort_cmd.add_argument("--role", required=True, choices=ROLES)
    effort_cmd.add_argument("--provider", required=True, choices=(CLAUDE,))
    emit_cmd = sub.add_parser("emit", help="print every pin with provenance")
    emit_cmd.add_argument("--json", action="store_true", required=True)
    _add_size_flags(emit_cmd)
    timeout_cmd = sub.add_parser(
        "timeout", help="print a codex seat's timeout in seconds (one integer) from the same fail-closed resolution "
                        "as `argv` without --use (exit 0 / 1 broken or no eligible TOP / 2 usage)")
    timeout_cmd.add_argument("--role", required=True, choices=ROLES)
    timeout_cmd.add_argument("--provider", required=True, choices=PROVIDERS,
                             help="codex only (agy and claude timeouts are fixed in the role table)")
    timeout_cmd.add_argument("--top-retry", action="store_true",
                             help="the timeout of the seat's TOP retry pin (the astra reserve U2)")
    _add_size_flags(timeout_cmd)
    sub_cmd = sub.add_parser(
        "substitute", help="record a call-time substitution of an astra seat and print the same two lines as "
                           "`argv --use` exit 3 (exit 3; --use trial -> exit 10)")
    sub_cmd.add_argument("--role", required=True, choices=ROLES)
    sub_cmd.add_argument("--use", required=True, choices=sorted(codex_quota.SUBSTITUTION_USES | {TRIAL_USE}))
    sub_cmd.add_argument("--reason", required=True, choices=sorted(codex_quota.SUBSTITUTION_REASONS))
    sub_cmd.add_argument("--project-root", help="the project whose budget key and store apply (default: the "
                                                "working directory)")
    sub_cmd.add_argument("--cycle-id", help="the budget key (default: codex_quota.cycle_id_for)")
    sub_cmd.add_argument("--requested-model", help="the codex model the seat would have used")
    _add_size_flags(sub_cmd)
    check_cmd = sub.add_parser(
        "check", help="validate the model roster and everything that resolves through it, each item in a "
                      "fresh subprocess, no model calls (exit 0 all pass / 1 any failure / 2 usage)")
    check_cmd.add_argument("--home", action="store_true",
                           help="also check ~/.claude/skills/_meta and report drift from the checked tree")
    check_cmd.add_argument("--root", help="the tree to check (default: the one this file lives in)")
    return parser


def _shell_safe(tokens: List[str]) -> None:
    for token in tokens:
        if _SAFE_ARGV_TOKEN.fullmatch(token) is None:
            raise SeatModelError(f"refusing to print unsafe shell token {token!r}")


def _size_args(args: argparse.Namespace) -> Dict[str, Any]:
    """The size inputs for one CLI call - EMPTY unless the caller opted in.

    Sizing is OPT-IN, on every subcommand alike: with neither --size nor --user-request the
    call resolves exactly as it did before D16, reads no `.forge/size`, and gains no
    provenance key. That is what keeps `emit --json` byte-identical (plan L12) AND what keeps
    every un-migrated `argv`/`timeout` call site - and its no-cwd-read guarantee - unchanged.
    Once the caller DOES pass a size, `.forge/size` joins the L7 order, so forge's own size
    still wins over a caller's inside a cycle. It is read from --project-root when the call
    has one (`argv --use`, `substitute`) - the root that keys the budget and names the store,
    so a call never bills one cycle at another's size (S081 rev 4 D21 f6) - and from the
    working directory otherwise.
    """
    if getattr(args, "size", None) is None and not getattr(args, "user_request", False):
        return {}
    root = getattr(args, "project_root", None)
    return {"size": args.size, "user_request": args.user_request,
            "project_root": Path(root) if root is not None else Path.cwd()}


def _check_usage(args: argparse.Namespace) -> None:
    """Semantic usage rules the parser cannot express. Raises _UsageError; reads nothing."""
    if getattr(args, "size", None) is not None or getattr(args, "user_request", False):
        flag = "--size" if getattr(args, "size", None) is not None else "--user-request"
        if getattr(args, "provider", CODEX) not in (CODEX, AGY):
            raise _UsageError(f"{flag} applies to codex and agy seats only, not {args.provider} "
                              f"(codex chooses TOP or the std model, agy the level)")
    if args.command == "timeout":
        if getattr(args, "top_retry", False) and args.role not in ADMITTED_ROLES:
            raise _UsageError(f"--top-retry applies to the budgeted codex seats only, not {args.role}")
        if args.provider != CODEX:
            raise _UsageError(f"timeout applies to codex seats only, not {args.provider} (agy and claude "
                              f"timeouts are fixed in the role table; `emit --json` shows them)")
        if args.role not in ROLE_TABLE or CODEX not in ROLE_TABLE[args.role]:
            raise _UsageError(f"the role table has no codex row for {args.role}; timeout applies to codex seats only")
        return
    if args.command not in ("argv", "substitute"):
        return
    for flag in ("project_root", "cycle_id", "task_key"):
        value = getattr(args, flag, None)
        if value is not None and not value.strip():
            raise _UsageError(f"--{flag.replace('_', '-')} must not be blank")
    # Fix round 2 item 3(b): a budget key rides a receipt and a shell word, so it must be one safe word.
    if getattr(args, "cycle_id", None) is not None and _SAFE_WORD.fullmatch(args.cycle_id) is None:
        raise _UsageError(f"--cycle-id must be one plain word (letters, digits, . _ : + -), got {args.cycle_id!r}")
    if args.command == "argv":
        retry_given = [flag for flag, value in (("--failed-admission-id", args.failed_admission_id),
                                                ("--failed-reason", args.failed_reason)) if value is not None]
        if not args.top_retry and retry_given:
            raise _UsageError(f"{', '.join(retry_given)} apply only with --top-retry")
        if args.use is None:
            given = [f"--{flag.replace('_', '-')}" for flag in ("project_root", "cycle_id", "task_key")
                     if getattr(args, flag) is not None]
            if args.top_retry:
                given.append("--top-retry")
            if args.receipt_file is not None:
                given.append("--receipt-file")
            if args.await_quota:
                given.append("--await-quota")
            if given:
                raise _UsageError(f"{', '.join(given)} apply only with --use")
            return
        if args.provider != CODEX:
            raise _UsageError(f"--use applies to codex seats only, not {args.provider} (agy seats are not astra)")
        if args.role not in ADMITTED_ROLES:
            raise _UsageError(f"--use applies to the budgeted codex seats only ({', '.join(sorted(ADMITTED_ROLES))}); "
                              f"{args.role} x codex is never admit-gated or substituted")
        if args.use == TOP_RETRY_USE and not args.top_retry:
            raise _UsageError(f"--use {TOP_RETRY_USE} is admitted only through --top-retry: pass the ORIGINATING "
                              f"use with --top-retry --failed-admission-id ID --failed-reason R")
        if args.top_retry:
            if args.use not in TOP_RETRY_ORIGIN_USES:
                raise _UsageError(f"--top-retry cannot follow --use {args.use} (the trial is skipped, the audit arm is "
                                  f"audit_spawn's, and a retry is never retried)")
            missing = [flag for flag, value in (("--failed-admission-id", args.failed_admission_id),
                                                ("--failed-reason", args.failed_reason)) if value is None]
            if missing:
                raise _UsageError(f"--top-retry needs {' and '.join(missing)}")
            if not codex_quota.is_admission_id(args.failed_admission_id):
                raise _UsageError("--failed-admission-id must be 32 lowercase hex characters (an admission id)")
        owner = USE_ROLES.get(args.use)
        if owner is not None and args.role != owner:
            raise _UsageError(f"--use {args.use} belongs to the {owner} seat, not {args.role}")
        if args.task_key is not None and args.use not in TASK_KEY_USES:
            raise _UsageError(f"--task-key applies to --use {' / '.join(sorted(TASK_KEY_USES))} only")
        if args.use == "exhausted_review" and args.task_key is None:
            raise _UsageError("--use exhausted_review needs --task-key <the D21 review id> (one review per review id)")
        return
    if args.role not in ADMITTED_ROLES:
        raise _UsageError(f"{args.role} x codex is not a budgeted codex seat; nothing to substitute")
    if args.requested_model is not None and (
            _SAFE_WORD.fullmatch(args.requested_model) is None or len(args.requested_model) > _MODEL_WORD_MAX):
        raise _UsageError(f"--requested-model must be one plain word of at most {_MODEL_WORD_MAX} characters")


def _project_root(args: argparse.Namespace) -> Path:
    """--project-root, else the working directory. Only the budget key and store use it (J11)."""
    return Path(args.project_root) if args.project_root is not None else Path.cwd()


def _codex_cli_present() -> bool:
    return shutil.which(CODEX_CLI) is not None


def _substitution_output(role: str, use: str, reason: str, project_root: Path, cycle_id: Optional[str],
                         requested_model: Optional[str], admission_id: Optional[str] = None,
                         decision: Optional[SizeDecision] = None) -> str:
    pin = substitute(role, use, reason, project_root=project_root, cycle_id=cycle_id,
                     requested_model=requested_model, admission_id=admission_id,
                     size=None if decision is None else decision.size,
                     size_source=None if decision is None else decision.size_source,
                     requested_by=None if decision is None else decision.requested_by)
    lines = [reason, pin.model]
    _shell_safe(lines)
    recorded = ("recorded" if pin.provenance["row_written"]
                else f"not recorded: {pin.provenance.get('row_error')}")
    print(f"seat_model.py: astra unavailable ({reason}): serve {role} with claude/{pin.model} in a fresh "
          f"context with the same brief, never a gpt model; provider gap: openai; substitution {recorded}",
          file=sys.stderr)
    return "\n".join(lines)


#: #322: the reset fields a quota refusal carries, in the order `argv --use` appends them after its two
#: exit-3 lines. A field whose value is unknown (None) is left out; wait_advice is always there.
QUOTA_WAIT_FIELDS = ("binding_window", "resets_at", "resets_in_s", "wait_advice")
#: #322: the extra line `argv --use --await-quota` appends when it DEFERRED the substitution row.
SUBSTITUTION_DEFERRED_LINE = "substitution=deferred"


def _quota_wait_lines(decision: Dict[str, Any], refusal: str) -> List[str]:
    """The #322 key=value lines for a quota refusal (codex_quota.QUOTA_REFUSAL_REASONS), else none.
    They go AFTER the two exit-3 lines, so a consumer that reads line 1 and line 2 is unaffected."""
    if refusal not in codex_quota.QUOTA_REFUSAL_REASONS or "wait_advice" not in decision:
        return []
    return [f"{key}={decision[key]}" for key in QUOTA_WAIT_FIELDS if decision.get(key) is not None]


def _deferred_output(role: str, reason: str, wait_lines: List[str], use: str, key: str,
                     requested: Optional[str]) -> str:
    """`argv --use --await-quota` on a quota refusal (#322): the same two lines as a substitution, the
    wait lines, then (#322 fix round 1, item 5) `use=`, `key=` and `requested_model=` -- what a later
    `substitute` must name: the use and budget key the refusal was decided on (a TOP retry's are `top_retry`
    on the forge cycle, not the seat's own) and the codex model the seat would have run -- and
    `substitution=deferred`, with NO substitution row. The caller waits for the reset (codex_quota.py
    await-reset) and re-admits; only when the wait ends without codex does it record the stand-in
    (`substitute --reason quota_exhausted_timeout|quota_probe_error|cli_missing`). Recording now would count a
    stand-in that may never serve."""
    model = resolve(role, CLAUDE).model
    if not isinstance(model, str) or model.lower().startswith("gpt-"):
        raise SeatModelError(f"refusing to name {model!r} as a codex stand-in: a gpt model draws the same quota")
    target = [f"use={use}", f"key={key}"] + ([f"requested_model={requested}"] if requested else [])
    lines = [reason, model] + wait_lines + target + [SUBSTITUTION_DEFERRED_LINE]
    _shell_safe(lines)
    advice = next((line.split("=", 1)[1] for line in wait_lines if line.startswith("wait_advice=")), "notify")
    print(f"seat_model.py: codex out of quota ({reason}): {role} NOT substituted yet (wait_advice {advice}); "
          f"wait with `codex_quota.py await-reset` in a background call, then re-admit once; on its exit 4 "
          f"record the stand-in with `seat_model.py substitute --reason "
          f"{codex_quota.REASON_QUOTA_EXHAUSTED_TIMEOUT}`", file=sys.stderr)
    return "\n".join(lines)


def _skipped(reason: str) -> Tuple[int, Optional[str]]:
    print(f"seat_model.py: seat skipped ({reason}); the astra trial and the exhausted-loop review are never "
          f"substituted", file=sys.stderr)
    return EXIT_SKIPPED, None


def _argv_with_use(args: argparse.Namespace) -> Tuple[int, Optional[str]]:
    """J10, in order: resolve the codex pin fail-closed -> the codex binary -> admit(use).

    A broken resolver raises (exit 1) before anything is recorded, so it never spends a
    budget; "no eligible TOP" and a missing CLI substitute WITHOUT an admit.
    """
    role, use = args.role, args.use
    requested: Optional[str] = None
    requested_class: Optional[str] = None
    tokens: List[str] = []
    reason: Optional[str] = None
    size_args = _size_args(args)
    # NAMED size_decision, not `decision`: codex_quota.admit's result below is already called
    # `decision` in this function, and shadowing it here silently passed an admit DICT into the
    # substitution as if it were a size.
    size_decision = resolve_size(size_args.get("size"), project_root=size_args.get("project_root"),
                                 user_request=size_args.get("user_request", False)) if size_args else None
    try:
        pin = resolve(role, CODEX, fail_open=False, **size_args)
        tokens = list(pin.argv_fragment)
        _shell_safe(tokens)
        requested = pin.model
        requested_class = pin_model_class(pin)
    except NoEligibleModelError:
        reason = UNAVAILABLE_NO_ELIGIBLE
    if reason is None and not _codex_cli_present():
        reason = UNAVAILABLE_CLI_MISSING
    if reason is not None:
        if use in SKIPPED_USES:
            return _skipped(reason)
        project_root = _project_root(args)
        return EXIT_SUBSTITUTE, _substitution_output(role, use, reason, project_root, args.cycle_id,
                                                    requested, decision=size_decision)

    project_root = _project_root(args)
    cycle = args.cycle_id if args.cycle_id is not None else codex_quota.cycle_id_for(project_root)
    # D16: the budget this call spends is decided by the pin that RESOLVED above, so a
    # light/medium main seat counts against the std budget and a complex one against TOP -
    # separately, on the same key. #302: by the resolving ROW and the served tier (pin_model_class),
    # not by the slug alone. An unsized call passes no size and admit() records the
    # back-compat default, exactly as before D16.
    decision = codex_quota.admit(use, cycle, project_root=project_root, task_key=args.task_key,
                                 sessions_dir=_paths().codex_sessions,
                                 size=None if size_decision is None else size_decision.size,
                                 size_source=None if size_decision is None else size_decision.size_source,
                                 model_class=requested_class,
                                 requested_model=requested,
                                 # WP-A5: the row records WHICH SEAT spent the slot. `requested_model`
                                 # holds the RESOLVED model, so a TOP seat frozen onto a std/support tier
                                 # model is billed `std` (L18, R1) and an UNSIZED seat's row is told apart
                                 # from an ordinary std-class call. `role` is already in hand.
                                 role=role,
                                 requested_by=None if size_decision is None else size_decision.requested_by)
    token = decision.get("unavailable")
    admitted = decision.get("admitted") is True
    if admitted and not token:
        _write_receipt(args, decision)
        return EXIT_OK, " ".join(tokens)
    refusal = str(token if admitted else decision.get("reason"))
    if use in SKIPPED_USES:
        return _skipped(refusal)
    # An ADMITTED audit that carries `unavailable` would spend a doomed call: substitute it
    # before the call, exactly as audit_spawn does (J13). #282 r10: that substitution names
    # the admission it replaces, so the audit stops counting as a TOP call. A refusal spent
    # nothing and names none; neither does an admission whose row the store never took.
    replaced: Optional[str] = None
    if admitted and decision.get("row_written") is True \
            and codex_quota.is_admission_id(decision.get("admission_id")):
        replaced = decision["admission_id"]
    # #322: a quota refusal names WHEN codex can serve again. The lines go after the two exit-3 lines.
    wait_lines = _quota_wait_lines(decision, refusal)
    if wait_lines and getattr(args, "await_quota", False) and not admitted:
        return EXIT_SUBSTITUTE, _deferred_output(role, refusal, wait_lines, use, cycle, requested)
    out = _substitution_output(role, use, refusal, project_root, cycle, requested, replaced,
                               decision=size_decision)
    return EXIT_SUBSTITUTE, "\n".join([out] + wait_lines) if wait_lines else out


def _write_receipt(args: argparse.Namespace, decision: Dict[str, Any]) -> bool:
    """`--receipt-file`: record `<admission_id> <key>` of an admission whose row the store took, ATOMICALLY
    (a temp file in the same directory, then os.replace), so a reader sees the old receipt or the new one,
    never half of one. The path must be unique per seat (the recipe uses `$DEST.admit`). True when written or
    not asked for; False (and a stderr line) when it was asked for and could not be written - the caller
    decides whether that is fatal (it is for a TOP retry). Nothing is written for a refusal."""
    path = getattr(args, "receipt_file", None)
    if path is None:
        return True
    aid, key = decision.get("admission_id"), decision.get("key")
    if decision.get("row_written") is not True or not codex_quota.is_admission_id(aid):
        print("seat_model.py: no receipt: the admission row was not recorded", file=sys.stderr)
        return False
    if not isinstance(key, str) or _SAFE_WORD.fullmatch(key) is None:
        print(f"seat_model.py: no receipt: the key {key!r} is not one plain word", file=sys.stderr)
        return False
    target = Path(path)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(f"{aid} {key}\n", encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        print(f"seat_model.py: the receipt was not written: {_ascii(exc)}", file=sys.stderr)
        return False
    return True


def _argv_top_retry(args: argparse.Namespace) -> Tuple[int, Optional[str]]:
    """The astra reserve U2/F3: the ONE TOP attempt for a std seat that failed on capability.

    FIX ROUND 1. Nothing is written before the failed attempt is PROVEN: `--failed-admission-id` must name an
    ADMITTED, std-class row of this role and use on the ORIGINATING key (`--cycle-id`, else the project's
    cycle id) - anything else is a refusal, exit 2, nothing written (F2). The failed model is read from that
    row, never taken from the caller. Then, in order: the role's OWN pin must still be a std seat (a pin that
    now bills TOP gains nothing from a TOP retry: `top_retry_seat_is_top`); the role's TOP pin must differ
    from the failed model (`top_retry_same_pin`), bill the TOP class, and - when a freeze decides it - be the
    roster TOP itself (`top_retry_not_top`, F3 / opus 4); the codex CLI; then codex_quota.admit(use=
    "top_retry") in the TOP class on the FORGE CYCLE key (codex_quota.cycle_id_for), so a cycle gets ONE retry
    whatever tournament or ballot key its seats were admitted on (F1). Every outcome after the proof writes
    ONE `top_retry` event row naming both keys and the exact failed admission. "No retry at all" (the first
    three reasons) is D6 for the ORIGINAL failure on its original use and key; a retry TOP could not serve is
    D6 on `top_retry` on the cycle key. Exit 0 = the TOP pin, and `--receipt-file` holds the retry's
    admission and key (the caller makes exactly one attempt and names that key if it must substitute);
    exit 3 = the Claude main tier.
    """
    role, origin = args.role, args.use
    project_root = _project_root(args)
    retry_key = codex_quota.cycle_id_for(project_root)
    size_args = _size_args(args)
    size_decision = resolve_size(size_args.get("size"), project_root=size_args.get("project_root"),
                                 user_request=size_args.get("user_request", False)) if size_args else None
    failed, retried = codex_quota.find_admission(project_root, args.failed_admission_id)
    # Fix round 2 item 2: without --cycle-id the origin key is the PROVEN row's own, never re-derived (a cycle
    # id can age out or be rewritten while Sol spends up to two runaway caps failing).
    origin_key = args.cycle_id if args.cycle_id is not None else (
        (failed.get("key", failed.get("cycle_id")) if failed is not None else None) or retry_key)
    problem = None
    if failed is None:
        problem = "names no admission in this project's budget store"
    elif retried:
        # Fix round 2 item 5: one failed admission buys at most one TOP retry, in any cycle.
        problem = "already has a top_retry event: one failed attempt is retried at most once"
    elif failed.get("task_key") != args.task_key:
        problem = (f"names an admission for task {failed.get('task_key')!r}, not {args.task_key!r}")
    elif failed.get("admitted") is not True:
        problem = f"names a REFUSED admission ({failed.get('reason')})"
    elif (failed.get("use"), failed.get("role"), failed.get("key", failed.get("cycle_id"))) != (origin, role, origin_key):
        problem = (f"names an admission of use {failed.get('use')!r}, role {failed.get('role')!r} on key "
                   f"{failed.get('key', failed.get('cycle_id'))!r}, not {origin!r} / {role!r} on {origin_key!r}")
    elif failed.get("model_class") != codex_quota.MODEL_CLASS_STD:
        problem = f"names a {failed.get('model_class')!r}-class admission; only a std seat is retried on TOP"
    if problem is None:
        # User-scoped round (item 5): RESERVE the attempt -- the replay check again, and the reservation, in ONE
        # step under the store lock, keyed by the failed admission alone. find_admission() above only READ the
        # guard: two concurrent resumers of one pending event both passed it. Nothing else is written first.
        claimed, why = codex_quota.claim_top_retry(project_root, args.failed_admission_id)
        if not claimed:
            problem = ("already has a top_retry event: one failed attempt is retried at most once"
                       if why == "replay" else "could not be reserved in this project's budget store")
    if problem is not None:
        raise _UsageError(f"--failed-admission-id {problem}")
    failed_model = failed.get("requested_model")

    requested: Optional[str] = None
    tokens: List[str] = []
    reason: Optional[str] = None
    # Fix round 2 items 1 and 6: the seat is judged by its PROVEN failed row (billed std, above) and that model
    # under the roster NOW - never by re-resolving the role, which ignores the seat's size (a light review_std
    # would read as TOP) and fails when Sol has since left the roster.
    roster_tops = _codex_top_models(_paths(), None, include_freeze=False)
    try:
        pin = resolve(role, CODEX, fail_open=False, top_retry=True)
        tokens = list(pin.argv_fragment)
        _shell_safe(tokens)
        requested = pin.model
        if roster_tops is not None and failed_model in roster_tops:
            reason = REASON_TOP_RETRY_SEAT_IS_TOP
        elif pin.model == failed_model:
            reason = REASON_TOP_RETRY_SAME_PIN
        elif pin_model_class(pin) != codex_quota.MODEL_CLASS_TOP:
            reason = REASON_TOP_RETRY_NOT_TOP
        elif pin.provenance.get("source") == "freeze" and (roster_tops is None or pin.model not in roster_tops):
            reason = REASON_TOP_RETRY_NOT_TOP
    except NoEligibleModelError:
        reason = UNAVAILABLE_NO_ELIGIBLE
    if reason is None and not _codex_cli_present():
        reason = UNAVAILABLE_CLI_MISSING
    admission: Optional[str] = None
    wait_lines: List[str] = []
    if reason is None:
        decision = codex_quota.admit(TOP_RETRY_USE, retry_key, project_root=project_root,
                                     sessions_dir=_paths().codex_sessions,
                                     size=None if size_decision is None else size_decision.size,
                                     size_source=None if size_decision is None else size_decision.size_source,
                                     model_class=codex_quota.MODEL_CLASS_TOP, requested_model=requested, role=role,
                                     requested_by=None if size_decision is None else size_decision.requested_by)
        admitted = decision.get("admitted") is True and not decision.get("unavailable")
        if decision.get("row_written") is True and codex_quota.is_admission_id(decision.get("admission_id")):
            admission = decision["admission_id"]
        if not admitted:
            reason = str(decision.get("unavailable") or decision.get("reason"))
            if decision.get("admitted") is not True:
                # #322 fix round 1 (item 9): a QUOTA refusal of the retry carries its reset lines, and with
                # --await-quota it is DEFERRED like any seat's (the event row below still says what happened).
                wait_lines = _quota_wait_lines(decision, reason)
        elif not _write_receipt(args, decision):
            # Fix round 2 item 3(d): the receipt names the key a later substitution bills. A TOP admission
            # the caller cannot account for is a failure, recorded as such (the slot is spent).
            codex_quota.record_top_retry(
                retry_key, project_root=project_root, role=role, origin_use=origin, origin_key=origin_key,
                failed_admission_id=args.failed_admission_id, failed_model=failed_model,
                failed_reason=args.failed_reason, retry_model=requested, outcome="substituted",
                reason="budget_store_unavailable", retry_admission_id=admission, task_key=args.task_key,
                sessions_dir=_paths().codex_sessions)
            raise SeatModelError("the TOP retry was admitted but its receipt could not be written")
    deferred = bool(wait_lines) and getattr(args, "await_quota", False)
    # #322 fix round 2 (item 3): a quota refusal the caller WAITS on is `pending`, not `substituted` -- the
    # replay guard (codex_quota.find_admission) then permits exactly ONE resumption of this failed admission
    # after the reset. Written as `substituted` (fix round 1), the one allowed retry was refused after the wait.
    outcome = "admitted" if reason is None else (codex_quota.TOP_RETRY_PENDING if deferred else "substituted")
    event = codex_quota.record_top_retry(
        retry_key, project_root=project_root, role=role, origin_use=origin, origin_key=origin_key,
        failed_admission_id=args.failed_admission_id, failed_model=failed_model,
        failed_reason=args.failed_reason, retry_model=requested,
        outcome=outcome, reason=reason,
        retry_admission_id=admission, task_key=args.task_key, sessions_dir=_paths().codex_sessions)
    if not event.get("row_written"):
        print(f"seat_model.py: the top_retry event row was not recorded: {event.get('error')}", file=sys.stderr)
    if reason is None:
        return EXIT_OK, " ".join(tokens)
    if deferred:
        return EXIT_SUBSTITUTE, _deferred_output(role, reason, wait_lines, TOP_RETRY_USE, retry_key, requested)
    if reason in (REASON_TOP_RETRY_SAME_PIN, REASON_TOP_RETRY_NOT_TOP, REASON_TOP_RETRY_SEAT_IS_TOP):
        # Not a retry at all: the event row says why, and the seat goes to D6 for its ORIGINAL failure, on its
        # original use and key - nothing was admitted or spent.
        return EXIT_SUBSTITUTE, _substitution_output(role, origin, args.failed_reason, project_root, origin_key,
                                                    failed_model, decision=size_decision)
    # A retry that TOP could not serve (budget, quota, auth, CLI, no eligible TOP) is D6 on `top_retry`, on the
    # cycle key it was billed to. An admitted-but-unavailable retry spent a slot on a doomed call: its
    # substitution names the admission, exactly as `argv --use` does (J13), so it is netted.
    out = _substitution_output(role, TOP_RETRY_USE, reason, project_root, retry_key, requested,
                               admission, decision=size_decision)
    return EXIT_SUBSTITUTE, "\n".join([out] + wait_lines) if wait_lines else out


def _substitute_command(args: argparse.Namespace) -> Tuple[int, Optional[str]]:
    if args.use in SKIPPED_USES:
        return _skipped(f"substitute --use {args.use}, reason {args.reason}")
    size_args = _size_args(args)
    size_decision = resolve_size(size_args.get("size"), project_root=size_args.get("project_root"),
                                 user_request=size_args.get("user_request", False)) if size_args else None
    return EXIT_SUBSTITUTE, _substitution_output(args.role, args.use, args.reason, _project_root(args),
                                                 args.cycle_id, args.requested_model,
                                                 decision=size_decision)


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            raise _UsageError("a subcommand is required: argv | model | effort | emit | substitute | timeout | check")
        _check_usage(args)
        if args.command == "check" and args.root is not None and not Path(args.root).is_dir():
            raise _UsageError(f"--root {args.root!r} is not a directory")
    except _UsageError as exc:
        print(f"seat_model.py: error: {_ascii(exc)}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "check":
        # A REPORT, not a pin: failures are named on stdout and the exit code carries the verdict.
        try:
            import seat_model_check  # the spawning half lives apart: this module never spawns
            code, report = seat_model_check.run_check(None if args.root is None else Path(args.root),
                                                      home_too=args.home)
        except Exception as exc:  # noqa: BLE001 - the check machinery itself broke
            print(f"seat_model.py: error: check could not run: {_ascii(exc)}", file=sys.stderr)
            return EXIT_RESOLUTION_FAILED
        print(report)
        return code

    code = EXIT_OK
    try:
        if args.command == "argv" and args.top_retry:
            code, out = _argv_top_retry(args)
        elif args.command == "argv" and args.use is not None:
            code, out = _argv_with_use(args)
        elif args.command == "argv":
            tokens = list(resolve(args.role, args.provider, fail_open=False,
                                  **_size_args(args)).argv_fragment)
            _shell_safe(tokens)
            out = " ".join(tokens)
        elif args.command == "model":
            model = resolve(args.role, args.provider, fail_open=False).model
            _shell_safe([model])
            out = model
        elif args.command == "effort":
            level = resolve(args.role, args.provider, fail_open=False).effort
            if level not in CLAUDE_EFFORTS:
                raise SeatModelError(f"{args.role} x claude has no effort to print: {level!r}")
            out = level
        elif args.command == "substitute":
            code, out = _substitute_command(args)
        elif args.command == "timeout":
            # #282 r12: the codex pin's timeout, never a second `argv` line (`$PIN` is word-split).
            seconds = (resolve(args.role, CODEX, fail_open=False, top_retry=True).timeout if args.top_retry
                       else resolve(args.role, CODEX, fail_open=False, **_size_args(args)).timeout)
            if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
                raise SeatModelError(f"refusing to print a timeout that is not a positive integer: {seconds!r}")
            out = str(seconds)
        else:
            out = json.dumps(emit(**_size_args(args)), indent=2, ensure_ascii=True)
    except _UsageError as exc:  # a refusal decided on what the store holds (the TOP retry's proof): nothing written
        print(f"seat_model.py: error: {_ascii(exc)}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # ANY failure: non-zero and nothing on stdout
        print(f"seat_model.py: error: {_ascii(exc)}", file=sys.stderr)
        return EXIT_RESOLUTION_FAILED
    if out is not None:
        print(out)
    return code


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
