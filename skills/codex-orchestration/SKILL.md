---
name: codex-orchestration
description: "Codex CLI and Antigravity CLI (agy) delegation from Claude Code: research tasks, challenger or devil's advocate reviews, prototyping, idea generation, code review, second-opinion analysis. Covers codex exec with a per-role model and reasoning-effort pin (seat_model), the codex_quota admit gate and agy -p headless mode. Use when a task goes to a second or third model."
metadata:
  disambiguation: "Delegation STRATEGY across external CLIs — when to ask a second model, how to frame the task, how to weigh the answer. The `agy` binary's own flags and failure modes are antigravity-cli."
---

# Cross-Model Orchestration — Claude + Codex + Antigravity (agy)

Delegate tasks to the **Codex CLI** (model pinned per role — see "Seat Models" below) and the **Antigravity CLI (`agy`)** from Claude Code for second opinions, parallel research, challenger reviews, and idea generation. Each model runs as an independent agent with its own context, tools, and reasoning — different models catch different things.

<HARD-RULE>
Pin the MODEL and the reasoning EFFORT per call on every `codex exec` delegation, through the seat registry: `PIN="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role <role> --provider codex)" && timeout <T> codex exec … $PIN …`, where `$PIN` is `-m <slug> -c model_reasoning_effort=<tier>` (see "Seat Models" and "Reasoning-Effort Tiers" below). Never rely on the config default for either axis — the interactive `/model` picker rewrites both `model` and `model_reasoning_effort` in `~/.codex/config.toml`, and headless `codex exec` inherits whatever it last wrote, so an unpinned call can silently run on any model at any effort. The `&&` is load-bearing: `seat_model.py` exits non-zero with EMPTY stdout on any failure, so an unresolved pin never runs unpinned. A budgeted codex seat (`code_reviewer`, `consultant_main`, `arbiter`, `escalation`) adds `--use <use>` to that call, which also admits it against the budget; its exit 3 means "codex cannot serve the seat: serve it with a fresh Claude main-tier agent", never "run codex" (see "Seat Models").
</HARD-RULE>

<HARD-RULE>
Always check Codex availability before delegating. Read `tools.codex.installed` from `~/.claude/state/inventory.json` (written by `env-adoption` skill). If the inventory is missing, run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check --inventory-only --silent` first. If `tools.codex.installed` is false, fall back to Claude Code agents.
</HARD-RULE>

<HARD-RULE>
Never pass secrets, API keys, or credentials in Codex prompts. Prompts may be logged in `~/.codex/sessions/` and `~/.codex/history.jsonl`. Use environment variables or file references instead.
</HARD-RULE>

<HARD-RULE>
No role-resolved codex call runs `--ephemeral` (#302). Every call that resolves a `seat_model` codex role — the protected roles (`code_reviewer`, `consultant_main`, `arbiter`, `escalation`; TOP or the std tier since the astra reserve) AND `consultant_support` — runs WITHOUT `--ephemeral`: only a non-ephemeral call writes the session rollout that carries `rate_limits`, the one place codex quota is visible (`codex_quota.py snapshot`), and every codex model — TOP, the std tier and the support tier — draws the same plan quota. This holds even while a freeze pin keeps a TOP role on an older model. `consultant_support` is metered, not gated: it still takes no budget admit and is trip-wire checked as before. Consequence: every role-bound prompt persists in `~/.codex/sessions/`, which is exactly why the no-secrets rule above is binding — put no secret in any brief. Generic, role-less codex examples (`patterns.md`, `templates.md`) resolve no seat and are outside this rule.
</HARD-RULE>

<HARD-RULE>
</HARD-RULE>

<HARD-RULE>
Always create a unique session directory before any Codex delegation. Multiple Claude sessions
may run in parallel across different projects — hardcoded /tmp/ paths cause cross-session
collisions where one session overwrites another's Codex results.
</HARD-RULE>

<HARD-RULE>
Never use `--dangerously-bypass-approvals-and-sandbox` or `danger-full-access` unless the environment is externally sandboxed (container, VM). These modes give Codex unrestricted system access.
</HARD-RULE>

- **AGY FAMILY HARD-RULE (user directive; roster rev 6, 2026-10-21): agy serves ONE Gemini family, the one named by `model_roster.AGY_FAMILY` — enforced in code as well as stated.** Currently **Gemini 4 Argon**: `gemini-4-argon-{high,medium,low}` (listed 2026-10-20 in `~/.claude/state/agy-models.json`, agy 1.4.3). It replaced flash 3.8 on eval evidence (#365: argon 63/63, flash 3.8 53/63, its losses all tool-reaching no-shows), and with it the FLASH-ONLY rule of 2026-07-24. `seat_model` accepts only `seat_model.AGY_FAMILY_PATTERN`, `^gemini-\d{1,9}(\.\d{1,9})*-<family>-(high|medium|low)$`, the family read from the roster, on every agy path (roster, freeze pin, env, harness literal); a family swap is a roster revision (`docs/model-roster-swap.md`). ❌ FORBIDDEN with no role-based carve-out, although agy lists them: every other family — flash and any pro line included — and every non-Google slug (`claude-*`, `gpt-oss-120b-medium`). Reasons: (1) **provider diversity**, fully binding — agy holds the third-model slot because it is neither Anthropic nor OpenAI; repointing it at a `claude-*` model (the tempting "fix" for an agy no-show) collapses the cross-check into an echo, and `gpt-oss-*` collapses into the Codex arm; (2) **one family, the strongest Google line the account serves, chosen on evidence** — reaching for an older or different line buys nothing. Every agy call pins `--model` through `seat_model.py argv --role <role> --provider agy` (research and operational calls use `consultant_support`); the account default may still be flash, so an unpinned call rides a forbidden line. The one exception is measurement: the `model-eval-pack` skill may name any model agy lists, literally, only to measure it — never for a seat or delegated work. On a no-show: retry under the STDIN/FLAG-ORDER/Pattern-2 rules, then record the provider gap honestly — there is no gemini fallback (retired 2026-07-25). Escalate to another arm rather than repointing agy.

---

## Codex Plugin Commands — DEAD PATH (plugin not installed)

**Verified 2026-09-14:** the Codex plugin (`codex@openai-codex`) is **not installed** on this host. `~/.claude/plugins/installed_plugins.json` lists only `superpowers@claude-plugins-official`. Every `/codex:*` command below is a **dead path** here: it does not run. Do not route reviews, challenges or delegation through these commands, and do not present them as preferred. The working interface is raw `codex exec` with a seat pin (see "Seat Models" and "Core Integration"). The table stays only as a reference for a host that installs the plugin.

| Command | Purpose if the plugin were installed | Working path on this host |
|---------|---------|----------|
| `/codex:review` — DEAD PATH | Code review against git diffs | `codex exec` with a `code_reviewer` pin |
| `/codex:adversarial-review` — DEAD PATH | Challenge review (design, tradeoffs) | `codex exec` with a `consultant_main` pin from `seat_model.py argv --use challenger` (exit 3 → a fresh Claude main-tier agent) |
| `/codex:rescue` — DEAD PATH | Delegate investigation/fix to Codex | `codex exec` task delegation |
| `/codex:setup` — DEAD PATH | Check readiness, toggle review gate | `tools.codex.installed` in `~/.claude/state/inventory.json`, then `codex --version` |
| `/codex:status` / `/codex:result` / `/codex:cancel` — DEAD PATH | Background job lifecycle | `codex exec … -o "$OUT" &`, `wait`, read the `-o` file |

Raw `codex exec` therefore carries everything on this host: reviews, challenges, delegation, parallel batches with `&` and `wait`, custom brief files, `--output-schema`, `--json` event streams, and `codex mcp-server`.

---

## Antigravity CLI (`agy`)

Read `references/agy-patterns.md` before any headless `agy` call: the stdin, flag-order, sandbox and model rules, the `agy -p` invocation patterns and the availability check. The AGY FAMILY hard rule is above, with the opening hard rules.

---

## Never run a codex call in a foreground Bash tool call (S081 rev 4, D24)

**Every `codex exec` runs under `skills/_meta/codex_watch.py`, and the Bash tool call that starts it runs
with `run_in_background`.** Act on the completion notification rather than waiting.

Two separate limits, and confusing them is what broke live work:

* **The Bash tool call itself is capped at 600 s.** Nothing inside the command can raise that — not the
  seat's cap, not `--hard-cap`, not GNU `timeout`. A foreground call therefore dies at 600 s no matter how
  patient its arguments are, which is why the cap has to be escaped by BACKGROUNDING the tool call, not by
  choosing a bigger number. Shell `&` inside a foreground call does not help: the tool still waits.
* **The watchdog's own stops** are inactivity (300 s with no stdout, no stderr and no session-rollout
  write — exit 111, retried once) and the per-tier runaway cap (exit 112, a gap, never retried or
  substituted). A wall clock cannot tell "thinking hard" from "hung"; inactivity can, which is the whole
  reason the normal stop is no longer a clock.

The evidence, from the 2026-09-14/15 rollouts: completed `gpt-6-astra` calls ran 172–521 s against a 600 s
floor, and two `gpt-5.6-sol` sessions (896 s and 538 s) were killed while still emitting reasoning events
to their last second — longest silences 183 s and 19 s. They were not stuck. The idle timeout is 1.6× that
longest healthy silence.

While a watched call runs it prints one progress line per 60 s to the caller's stderr, so a long call is
visibly healthy rather than indistinguishable from a hang, and each call appends a `codex_watch` row to the
`process-observation` sidecar carrying `elapsed_s`, `max_silence_s` and `stop_reason`.

This applies to every prose codex call site — the `codex_top_seat` block below, the script it sources and its two pasted copies,
the `consultant_support` research pin, `forge`, `adversarial-team-brainstorm`, `cross-cli-deliberation`,
`alf` and the escalation diagnosis. **The agy rules are untouched by this**: `agy` keeps its own
`timeout … agy --sandbox --mode plan … -p … < /dev/null` pattern, its mandatory closed stdin, its flag order and the
agy family rule exactly as the host directive states them.

---

## Seat Models — the model is pinned per ROLE, never inherited

`skills/_meta/seat_model.py` is the single registry for which model a review, consultancy or arbiter call runs on. It reads only home-tier inputs (the codex roster `~/.codex/models_cache.json`, the agy roster cache `~/.claude/state/agy-models.json`, freeze pins) and never the working directory, a project file or smart-config.

```bash
# consultant_support (the codex SUPPORT tier, not astra): the plain pin, no budget gate, and NO
# --ephemeral (#302): the rollout is what meters its quota, like every role-resolved codex call.
# Run this Bash tool call with run_in_background (D24): the cap below is larger than the 600 s
# foreground limit, so in the foreground the harness would kill the call, not the cap.
PIN="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_support --provider codex)" \
  && CAP="$(python3 ~/.claude/skills/_meta/seat_model.py timeout --role consultant_support --provider codex)" \
  && python3 ~/.claude/skills/_meta/codex_watch.py --mode codex --hard-cap "$CAP" \
       --stdout-file "$OUT.stdout" --stderr-file "$OUT.stderr" \
       -- codex exec -s read-only $PIN -o "$OUT" "…"
# $PIN = "-m <slug> -c model_reasoning_effort=<tier>". Unquoted on purpose (bash word-splitting).
# Any resolver failure -> non-zero exit AND empty stdout, so the && never runs an unpinned or uncapped call.
# codex_watch closes the child's stdin itself, so the `< /dev/null` the bare form needed is now built in.
# TOP seats add --use (admit + pin in one call, exit 3 = substitute): codex_top_seat, below.
# Claude seats: python3 ~/.claude/skills/_meta/seat_model.py model --role <role> --provider claude
#   and their reasoning effort (#311): seat_model.py effort --role <role> --provider claude
#   (medium on code_reviewer, consultant_main, arbiter and consultant_support; xhigh on escalation). Pass it EXPLICITLY as
#   workflow agent({effort}) or headless `claude -p --effort`; agent frontmatter never governs a seat.
# Everything that resolves right now, with provenance: python3 ~/.claude/skills/_meta/seat_model.py emit --json
```

| Role | Codex (model @ effort) | agy | Claude tier | Currently (roster rev 8) | Codex timeout | `--ephemeral` | Budget gate (`seat_model.py argv --use`) · when codex cannot serve it |
|---|---|---|---|---|---|---|---|
| `code_reviewer` | TOP @ `xhigh` (complex / risk-promoted); std @ `xhigh` (light/medium) | — | main | claude `opus` | 2400s | no | `advisory_review` (TOP) / `review_std` (std); `audit` on the VERIFIED gate: recorded, never refused by thresholds or budget · `audit_spawn` runs a second cold-context Claude main-tier auditor in the codex slot |
| `consultant_main` | std @ `xhigh` at every size (TOP only on `--user-request`) | TOP-argon `-high`; sized: light `-low`, medium `-medium`, complex `-high` | main | claude `opus` · codex std `gpt-6.1-sol` | 2400s | no | `consult` (the round's repo-exploring `-C` call) · `challenger` — std budget 2 per cycle each · the ONE Sol → TOP retry on a capability failure (`top_retry`), then a fresh Claude main-tier agent with the same brief |
| `consultant_support` | support @ `medium` | TOP-argon `-medium`; sized: light `-low`, medium `-medium`, complex `-high` | support | claude `sonnet` · codex support `gpt-6.1-terra` | 1200s | no | none (not astra) · never substituted: a failure is a gap |
| `arbiter` | std @ `xhigh` at every size | TOP-argon `-high`; sized: light `-low`, medium `-medium`, complex `-high` | main | claude `opus` · codex std `gpt-6.1-sol` | 2400s | no | `ballot` / `deliberation` (std) · the ONE Sol → TOP retry (recipe seats), then the Claude main tier; avengers `convene` seats a codex member on the Claude main tier at plan time and recomputes the arbiter without codex. Avengers' `ratification_arbiter` seat class keeps `max` |
| `escalation` | TOP @ `max` at every size (read-only diagnosis) | — | main | claude `opus` | 3600s | no | `escalation` (TOP 1 per cycle; forge's escalation seat), `diagnosis` (per task key), `exhausted_review` (TOP 1 per D21 review; skipped, never substituted) · a read-only Claude main-tier diagnosis |

**The astra reserve (roster rev 4, `model_roster.CODEX_TOP_ROLES = ("code_reviewer@complex", "escalation")`).**
Codex TOP (astra today) serves only the escalation seat and the complex / risk-promoted code review; every other
protected codex seat is the std tier (Sol, about a fifth of astra's price). Two bounded paths lead back to TOP: the
**Sol → TOP retry** (U2) — a Sol seat whose call fails on CAPABILITY (`capacity_twice` / `malformed_twice`) gets ONE
attempt on TOP through `seat_model.py argv --top-retry --failed-admission-id <the failed seat's receipt>` before the
Claude stand-in (the admission must be an admitted std row of that role, use and key), admitted as `top_retry` (1 per forge
cycle) and recorded as a `top_retry` event row; quota, auth, budget and timeout outcomes never buy it — and the
**exhausted-loop review** (U3): one `escalation`-seat review when a D21 loop hits its 2-round bound with verified
majors open. A home-tier freeze reaches only the TOP rows. The evidence gap is recorded, not hidden: Sol has never
been measured head-to-head as a reviewer, which is why complex review keeps TOP.

**Codex std tier** — codex std `gpt-6.1-sol` (roster rev 8). It serves `consultant_main` and `arbiter` at every size,
the SIZED `code_reviewer` at `--size light|medium`, and `codex_model`'s std fallbacks (the challenger floor, the
ratification arbiter, the audit codex arm). The std tier and the support tier both bill the `std` quota class; a
TOP seat bills `top`. The class follows the ROW that resolved the pin, not the slug.

**Tiers, not models.** The Claude column names the TIER a seat is served by. The models behind the tiers — the
Claude main tier, the Claude support tier, the codex std tier and the codex support tier — live in ONE place, `skills/_meta/model_roster.py`,
and the **Currently** column above is the one table that maps each tier to its model
(`skills/codex-orchestration/tests/test_seat_models_table.py` fails when it disagrees with the roster). Codex TOP and agy are not roster tiers: they auto-follow the vendor's top
listed model, so their served model is read from `emit --json`, never from this table. agy's FAMILY is roster data
(`model_roster.AGY_FAMILY`, rev 6: `argon`, so the agy column reads TOP-argon); within it the VERSION auto-follows, and the LEVEL follows the task size (`model_roster.AGY_LEVEL_BY_SIZE`, rev 7: `argv --provider agy --size light|medium|complex` serves `-low` / `-medium` / `-high`; no size keeps the role's level). To change which model
serves a tier, follow the runbook, `docs/model-roster-swap.md`: it edits the roster, this column and the golden
test in one commit.

**The Codex timeout column is a RUNAWAY CAP, not a deadline (S081 rev 4, D24).** It is what
`codex_watch.py` is given as `--hard-cap`; the stop that actually fires on a healthy-but-slow call is
**inactivity** — 300 s with no stdout, no stderr and no session-rollout write. The caps were raised from
600/1200 in this revision because the old wall clock was killing live work: measured on the 2026-09-14/15
rollouts, completed `gpt-6-astra` calls ran 172–521 s against a 600 s xhigh floor, and two `gpt-5.6-sol`
sessions (896 s and 538 s) were cut off while still emitting reasoning events to their last second.

- **Codex TOP** is resolved in production by `seat_model.py`, through `codex_model.select_top(effort, incumbent=…)`: the lowest-`priority` model with `visibility == "list"`, `supported_in_api`, and the role's effort supported; a priority tie among those breaks by the higher model generation in the slug, then the `incumbent` seat_model passes (the last recorded TOP), then slug (#282 R16; `tie_break` / `tied_with` in provenance and the tops record). Generation only separates models of DIFFERENT generations: `gpt-6-astra` and the std tier `gpt-6-sol` are both generation 6, so a tie between them is decided by the incumbent, then by slug. `codex_model.top_listed(effort)` is the incumbent-less convenience form — it has **no production caller** and cannot break a tie by incumbent. A populated `upgrade` field is followed only to another eligible listed model. **Roster fact — `priority` is the vendor's PICKER ORDER and is NOT stable.** `gpt-5.6-sol` was observed at priority 4 (2026-09-15T14:38:49Z), 1 (20:45:50Z, tied with `gpt-6-astra`), 4 again (22:25:15Z) and 1 again (22:38:08Z): it flaps, so no dated snapshot of it stays true. In those 2026-09-15 ties `gpt-6-astra` held TOP by generation (6 over 5.6). That guard does NOT cover the std tier: a tie between astra and `gpt-6-sol` (same generation) is decided by the incumbent, then by slug, and a strict inversion (the std or support model listed at a lower priority than astra) serves it on TOP seats — provenance then records `top_resolved_to_std: true` and the digest's TOP-change line says so (#302). On the 2026-09-24 roster: `gpt-6-astra` (1), `gpt-6-sol` (2), `gpt-6-luna` (3), `gpt-5.6-sol` (4), `gpt-5.6-terra` (7), `gpt-5.6-luna` (8), `gpt-5.5` (12, retires 2026-10-14); the hidden `gpt-reserve` and `codex-auto-review` are never selected. Examples here use the argv substitution, never a literal TOP slug: TOP roles follow the roster.
- **Auto-follow, with provenance.** A TOP role follows the vendor's top listed model at call time, and the last resolved TOP per provider is recorded in `~/.claude/state/seat-model-tops.json`. A roster older than 7 days keeps the last recorded TOP (flagged stale). With no roster at all the resolver falls back to a harness literal (`gpt-6-astra` / `gemini-<AGY_HARNESS_VERSION>-<AGY_FAMILY>-<level>`, today `gemini-4-argon-<level>`), recorded as such.
- **Freeze pins.** `~/.claude/state/seat-model-pins.json` (home-tier only — never env, never a project file) can hold a provider's TOP on a literal slug. It reaches the TOP rows only (since the astra reserve, the std literals `consultant_main` and `arbiter` never read it; restoring astra on them is a roster revision, `docs/model-roster-swap.md`). A freeze may be active at any time, so read `emit --json` rather than inferring the served model from this table.
- **Protected roles** (`code_reviewer`, `consultant_main`, `arbiter`, `escalation`) resolve ONLY through `seat_model`. An env override for them is honoured only when it equals the resolved model.
- **The admit gate — recommended call: `seat_model.py argv --role R --provider codex --use U [--project-root P]`.** It resolves the pin, checks the codex CLI and admits the call against the per-cycle budget (key: `codex_quota.py cycle-id`, the forge `.forge/cycle-id` inside a round) in ONE call. Exit **0** = admitted, stdout the pin. Exit **3** = astra is unavailable — the admit refused it (`budget_spent`; `budget_store_unavailable`; `class_not_budgeted`: the resolved model's class has no budget for that use — `advisory_review` served by sol, or `review_std` served by TOP), a fresh reading shows `rate_limit_reached` or `quota_exhausted`, the CLI is missing (`cli_missing`), or no eligible TOP model is listed (`no_eligible_model`): stdout line 1 is that reason, line 2 the Claude model; serve the seat with a **fresh-context Claude main-tier agent on the same brief**. **There is no 70% threshold any more (#322, 2026-09-27):** codex runs until its real limit, and a quota refusal is only `quota_exhausted` (a fresh reading ≥ 99%) or `rate_limit_reached`. Such a refusal appends `key=value` lines AFTER the two lines — `binding_window=`, `resets_at=`, `resets_in_s=` (each only when known) and `wait_advice=wait|notify` (`wait` when the reset is ≤ 1200 s away) — so read the model as **line 2**, never the last line; with `--await-quota` it records no substitution yet and ends with `substitution=deferred`, and the block writes `CODEX_QUOTA_WAIT` (see below). Exit **10** = the astra trial is skipped (never substituted), empty stdout. Exit **1** = broken resolver (an invalid freeze pin is not "unavailable"), exit **2** = usage (`--use` on an agy seat, on `consultant_support`, or an unknown use): fix it, never bypass the gate. Do **not** substitute a codex std or support model for TOP — every codex model draws the same ChatGPT-plan quota. **Call-time failures:** `codex_quota.py classify --exit-code N --attempt K [--timed-out] --stderr-file F --output-file O --prompt-file P` prints `<action> <reason>` (a stderr signal counts only on a codex error line — `ERROR: …` or codex's own tracing line — or, for quota, when the meter agrees; a model at capacity retries once, then substitutes `capacity_twice`; "Quota exceeded" is a quota stop): `retry` re-runs only the exec line once (a first timeout or empty answer), `substitute` → `seat_model.py substitute --role R --use U --reason <reason> [--requested-model M]` (exit 3, the same two lines, one row), `gap` → record a provider gap (an unclassified codex failure is never a substitution). The low-level form `codex_quota.py admit --record --use U --cycle-id C` records the decision as one row: exit 10 (refusal) → substitute a fresh Claude main-tier agent, except `trial`, which is skipped; exit 3 with reason `budget_store_unavailable` → substitute; any other exit 3 → a usage error to fix. A bare `codex_quota.py admit` (no `--record`) is check-only: the same decision and exit codes, and it writes nothing, so it spends no budget — running it before the recommended call cannot double-charge, and it is never the gate for a call. Admissions and substitutions are appended to `~/.claude/projects/<slug>/astra-budget.jsonl`, which the 2026-09-28 plan review reads.

The budgeted-seat shape every consultancy site uses. The function lives in ONE script, `~/.claude/skills/_meta/codex_top_seat.sh`, which this skill and forge source behind a guard (adversarial-team-brainstorm and cross-cli-deliberation each still carry a pasted copy with their own gap line; the copies are identical to the script apart from that line, and `skills/forge/tests/test_codex_top_seat_block.py` holds them to it). The name is historical: since the astra reserve it serves the std-tier seats too, and it carries the ONE Sol → TOP capability retry (U2) between the classify loop and the substitution. Its cap comes from `seat_model.py timeout --role R --provider codex` (the table's Codex timeout column: 2400s at `xhigh`, 3600s at `max`), asked only after the admit, and never from a literal — and it reaches `codex exec` as `codex_watch.py --hard-cap`, so the call is stopped by silence rather than by the clock. Source it in the same Bash call that runs the seat, because shell functions do not survive between calls — the guard stops the call before any seat starts when the script is missing — **and run that Bash call in the background** (see "Never run a codex call in a foreground Bash tool call" below):

```bash
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

# consultant_main (the codex std tier @ xhigh), admitted as a `consult`; the brief is a file so classify can ignore its echo
# SIZE and KEY empty: this generic seat takes the round's budget key and today's default size. A caller
# that mints its own key (a tournament, a ballot) passes it in the KEY slot so it spends its own budget.
codex_top_seat consult consultant_main consult "" "" "$BRIEF_FILE" "$OUT_FILE" -s read-only
```

**A missing seat script is a gap for every seat of the call.** When the Bash call exits non-zero with the stderr line `CODEX_GAP: codex_top_seat.sh missing or unreadable; no codex seat was started`, the guard stopped it before any seat ran and no seat output file was written: every seat of that call is a gap, to be handled exactly as if `$OUT_FILE` opened with `CODEX_GAP:`.

On a `CODEX_QUOTA_WAIT: <seat> (reason <token>; wait_advice <wait|notify>; resets_in_s <n>; stand-in <model>; use <U>; key <K>; requested <M>)` line (#322 — codex is out of quota; nothing is recorded yet), the agent that OWNS the seat:

1. With `wait_advice notify`, claims the wave's ONE notification first: `python3 ~/.claude/skills/_meta/codex_quota.py notify-claim`. Exit **0** (`notify`) → send the push notification BEFORE waiting: "codex at 100% (<seat>) — reset please; waiting up to 30 min". Exit **10** (`skip`) → another seat of the same wave — in ANY project, since codex quota is account-wide — already told the user; send none. The claim lives in `~/.claude/state` and is keyed on the active exhausted record, so it holds for that record's whole life (a far reset notifies ONCE, however many seats come later) and ends when the record clears; a new record is a new wave, and so is a re-exhaustion whose known reset time differs from the wave's by more than a minute (codex was reset unseen and used up again). With `wait` (the reset is ≤ 20 min away) it sends none. An agent without a notification tool (a spawned builder) does not wait: it returns `needs.kind: quota-exhausted` (the ladder's existing never-escalating kind) with `payload {seat, reason, wait_advice, resets_in_s, use, key, requested}` and the main loop notifies and waits.
2. Runs `python3 ~/.claude/skills/_meta/codex_quota.py await-reset --cycle-id <K> --project-root "${PROJECT_DIR:-$PWD}"` in a **BACKGROUND** Bash call (it waits up to 30 min; `wait` sleeps to the reset + 60 s, `notify` probes every 120 s so a reset by hand is seen). Each probe is one trivial non-ephemeral `codex exec` on the support tier, recorded as a `use: probe` row (under key K, in this project's store) that spends no budget. **One await-reset per account:** parallel seats — in any project — may each start one; the second JOINS the first and prints the same result with `"joined": true`, so no seat probes twice. **One full wait per exhausted record:** once a FULL 30-minute wait for the active record has timed out (a shorter `--max-wait` marks nothing), a later seat's `await-reset` does not wait again — it probes once (a reset by hand is still seen: exit 0) and otherwise exits **4** at once with `"source": "timed_out_for_record"`. That seat sends no notification (its `notify-claim` said `skip`) and goes straight to step 4.
3. Exit **0** (codex is back and its meter clears; `source` says `reset` or `user_reset`): re-runs the SAME `codex_top_seat` call ONCE. A second `CODEX_QUOTA_WAIT` does not wait again: record the stand-in with its reason, as in step 4.
4. Otherwise records the stand-in with the line's own use, key and model, then runs the D6 Claude main-tier stand-in below: `python3 ~/.claude/skills/_meta/seat_model.py substitute --role <R> --use <U> --cycle-id <K> --requested-model <M> --reason <REASON> --project-root "${PROJECT_DIR:-$PWD}"` (the same two lines as a substitution; drop `--requested-model` when the line says `requested -`). REASON by the exit code: **4** still exhausted after 30 min, or `timed_out_for_record` (this record's wait already timed out) → `quota_exhausted_timeout`; **6** three probes in a row failed for a non-quota reason → `quota_probe_error`; **3** the codex CLI is missing → `cli_missing`. Exit **5** is an auth failure, not quota — nothing was waited for: run `codex login`, and serve the seat with `--reason auth_failure`.

The same line comes from a TOP retry (U2) that codex refused for quota: its `use` is `top_retry` and its `key` the forge cycle, and step 4 names those. That step-4 stand-in closes the retry: the failed admission's one resumption is spent, and a later `--top-retry` for it exits 2.

On a `CODEX_SUBSTITUTE: <seat> -> <model> (reason <token>; provider gap: openai)` line, spawn `Agent(subagent_type="general-purpose", model="<model>")` with the brief file's content in a fresh context, attribute its findings to `<model> (substituting codex: <reason>)`, and record the round as Claude + Google (provider gap: OpenAI). A substitute does not spend the astra budget.

## Reasoning-Effort Tiers

Read `references/effort-tiers.md` when choosing or questioning a tier: the 2026-07-11 benchmark, the `high` policy finding, per-model tier support, the one owner of the timeouts, and the tier table (use, typical wall-clock, runaway cap).

```bash
# Challenger call — consultant_main (the codex std tier @ xhigh): model + effort pinned per call, no --ephemeral,
# admitted against the round's challenger budget in the same call. codex_top_seat is the function in
# "Seat Models" (paste its preamble into this Bash call); on astra unavailable challenge.md gets a
# CODEX_SUBSTITUTE line -> run the same brief on a fresh Claude main-tier agent.
declare -F codex_top_seat > /dev/null || { echo "define codex_top_seat (Seat Models) in this Bash call first" >&2; exit 2; }
codex_top_seat challenger consultant_main challenger "" "" \
  "$CODEX_WORK/brief.md" "$CODEX_WORK/challenge.md" -s read-only
```

**Delta-seeking challenger prompt (the honest-loop contract).** Prompt shape matters as
much as tier: telling codex "the basics are done" reallocates attention to the tail — at
`medium` this recovered a subtle bug that a plain review prompt missed even at `high`.
Template to embed in challenger briefs (the brief block: `skills/_meta/spawn-brief.md`):

<!-- spawn-brief.v1 id=codex-orchestration.delta-challenger -->
> A prior review already found: `<findings list>`. Your ONLY job: find genuine defects the
> prior review MISSED. Do not repeat, rephrase, or elaborate on listed findings. Inventing
> a finding to have something to say is a failure mode; if you find nothing genuinely new,
> output exactly: NONE_FOUND
> Goal: defects the prior review missed that would stop `<Done when / DW-n>` holding.
> Non-goals: the listed findings; style; new requirements; file changes.
> Open questions: none may be returned — decide, note the assumption, proceed.
> Done when: every new defect has a severity, file:line evidence and a fix, or NONE_FOUND.
> Stop when: the diff is covered, or your budget stops the search (then say coverage is incomplete).

**Operational notes:**
- Retry ONCE on `Selected model is at capacity` (transient; fails within ~2s, so the retry is cheap).
- Keep `-s read-only` on every consultancy call: at `max`, codex has run unrequested
  read-only shell detours (reading its own skill files) despite an explicit "do not browse
  the filesystem" instruction — the sandbox contained it.
- `max`/`ultra` workflow stages need raised timeouts (1200s/1800s), not the default 600s.

---

## Three-Model Validation Pattern

For COMPLEX tasks, run all three models for maximum coverage:

| Model | Role | Strength |
|-------|------|----------|
| Claude (session model; reviewer and consultant seats resolve the Claude main tier) | Orchestrator, architect | 1M context, skills/agents, MCP, conversation memory |
| Codex (role-pinned — see Seat Models) | Challenger, code review | Independent perspective, web search, structured review output |
| Antigravity (`agy`, newest roster-family model, role-pinned) | Third main deliberation provider, analyst, research | Independent Google perspective, headless `agy -p` delegation, brainstorming |

**Diverge → Challenge → Converge:**
1. Claude explores approaches (via forge design team)
2. Codex challenges (raw `codex exec` with a `consultant_main` pin, after a `challenger` admit — the `/codex:adversarial-review` plugin path is dead here)
3. agy independently analyzes (via `agy -p`)
4. Claude synthesizes — flag agreements (high confidence) and disagreements (investigate)

---

## Current State

Read `references/current-state.md` for what is installed, configured and verified on this host: the CLI versions and per-role pins, the `config.toml` snapshot, why the model is pinned and never inherited, the Claude and Codex strengths table, the subcommands added since 0.118, and the verified-facts table (versions, the codex roster).

---

## `codex exec` recipes

Read `references/codex-exec.md` before writing a raw `codex exec` call. It holds the "Core Integration" section (the command shape and its critical flags), the basic delegation pattern, and the full availability check (`check_codex`).

### Session Directory (REQUIRED)

The HARD-RULE "Always create a unique session directory before any Codex delegation" is above, with the opening hard rules. This is its recipe:

```bash
# Create ONCE per Codex delegation block — reuse for all tasks in that block
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX) || exit 1

# All briefs, results, schemas, and events go under $CODEX_WORK/
# The directory is unique per invocation — no collision possible
```

---

## Session-Scoped Availability

Check Codex once per session, cache the result:

```bash
CODEX_AVAILABLE=$(codex --version 2>/dev/null && echo "yes" || echo "no")
```

All subsequent checks in the session read this variable instead of re-running the command. Forge step 4b and all other callers should reference this pattern.

The full check (`check_codex`: the CLI is on PATH, a seat pin resolves, a pinned 10-second probe call answers) is in `references/codex-exec.md`.

---

## Sandbox Modes

| Mode | Codex Can | Use For |
|---|---|---|
| `read-only` | Read files only | Research, review, analysis |
| `workspace-write` | Read + write in project dir | Prototyping, code generation |
| `danger-full-access` | Full system access | Only in controlled environments |
| `--full-auto` | Auto-approve + workspace-write | Prototyping with file creation |

The HARD-RULE "Never use `--dangerously-bypass-approvals-and-sandbox` or `danger-full-access` unless the environment is externally sandboxed" is above, with the opening hard rules.

---

## When to Delegate to Codex vs Keep in Claude

| Delegate to Codex | Keep in Claude |
|---|---|
| Second opinion / challenger review | Primary implementation |
| Web research (Codex's tool use does this automatically) | File editing / code writing |
| Idea generation / brainstorming | Tool-heavy workflows (MCP, Grep, Read) |
| Independent prototype exploration | Tasks needing conversation context |
| Code review (`codex exec` with a `code_reviewer` pin — the native `codex review` subcommand has no `-m` flag) | Tasks needing memory access |
| Parallel background research | Interactive user dialogue |
| Stress-testing with different model perspective | Tasks needing Claude's agent spawning |
| Domain-specific review (with skill injection) | Multi-step orchestration (forge, agent-teams) |

---

## Shared Skill Library

Claude skills are symlinked into Codex's skill directory (`~/.codex/skills/`). Codex has access to 112 shared reference skills plus its own 7 native skills (119 total). Claude has 119 skills total.

**Symlink structure:** `~/.codex/skills/<name>` -> `~/.claude/skills/<name>`

**Skills NOT shared (Claude-specific):** `agent-teams`, `codex-orchestration`, `forge`, `vertex-banana`, `vertex-banana`, `research-for-skills`, `challenger` (Codex has native `challenger-review`).

**Naming note:** Claude's `challenger` skill = Codex's `challenger-review` skill. Both provide the same framework from different model perspectives.

---

## Reference Files

For advanced patterns, templates, and examples, see:
- **`patterns.md`** — handover patterns, progress tracking, skill injection, multi-file output, streaming
- **`templates.md`** — ready-to-use brief templates for challenger, approach explorer, research, escalation, prototyping, code review
- **`references/agy-patterns.md`** — the Antigravity CLI: headless `agy -p` rules (stdin, flag order, sandbox, model pin), invocation patterns, availability check
- **`references/effort-tiers.md`** — reasoning-effort tiers: benchmark, per-model tier support, timeout owner, tier table
- **`references/current-state.md`** — versions and pins on this host, `config.toml`, model override, cross-model strengths, newer subcommands, verified facts
- **`references/codex-exec.md`** — `codex exec` command shape and flags, basic delegation pattern, full availability check

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running Codex interactively from Claude | Blocks Claude's process | Use `codex exec` (non-interactive) |
| Unpinned `codex exec` (no `-m`) | Runs on whatever model `/model` last wrote to `config.toml` | `PIN="$(seat_model.py argv --role … --provider codex)" && codex exec … $PIN …` |
| `--ephemeral` on a role-resolved codex call | No rollout is written, so the call's quota goes unmetered | Omit it for every seat role — `code_reviewer` / `consultant_main` / `arbiter` / `escalation` AND `consultant_support` (#302) |
| Substituting a codex std or support model when `admit` refuses a TOP call | Same ChatGPT-plan quota pool — it hides the gap without saving quota | Never substitute a codex std/support model for TOP: serve the seat with a fresh-context Claude main-tier agent (`seat_model.py argv --use` exit 3, model on line 2) |
| Skipping an astra seat instead of the Claude main-tier substitute | Loses the seat's independent context, and the 2026-09-28 plan review never sees the unavailability | Run the fresh Claude main-tier agent on the same brief and label it `<model> (substituting codex: <reason>)`. Only the astra trial skips (exit 10) |
| Routing through `/codex:review` or `/codex:adversarial-review` | DEAD PATH: the plugin is not installed, so the command never runs | Raw `codex exec` with a seat pin |
| Passing secrets in prompts | Logged in Codex history | Use env vars or file references |
| Not checking availability first | Fails silently or hangs | Run availability check first |
| Huge prompts via command arg | Shell argument limits | Pipe via stdin: `cat brief.md \| codex exec -` |
| Ignoring sandbox modes | Security risk | Use `read-only` for analysis, `workspace-write` for prototyping |
| Not capturing output | Results lost | Always use `-o` or `--json` |
| Sequential Codex calls when parallel is possible | Slow | Use `&` and `wait` for parallel tasks |
| Re-checking availability every call | Wastes time and API calls | Cache with session-scoped variable |

---

## Related Skills

| Topic | Skill / Command |
|---|---|
| Forge design workflow | `forge` |
| Challenger role framework | `challenger` |
| Seat model registry (role → model, argv) | `skills/_meta/seat_model.py` (`argv` / `argv --use` / `model` / `emit --json` / `substitute`) |
| Codex quota meter + per-cycle budget | `skills/_meta/codex_quota.py` (`snapshot` / `admit` / `cycle-id` / `classify`; Python `unavailable()`) |
| Plugin adversarial review | `/codex:adversarial-review` — DEAD PATH (plugin not installed) |
| Plugin code review | `/codex:review` — DEAD PATH (plugin not installed) |
| Plugin task delegation | `/codex:rescue` — DEAD PATH (plugin not installed) |
| Plugin readiness check | `/codex:setup` — DEAD PATH (plugin not installed) |
| MCP server creation | `mcp-server-creator` |
| Large file analysis (cross-agent) | `large-file-analysis` |
| Code review methodology | `qa-reviewer` |
| Claude Code CLI reference | `claude-code-cli` |
| Antigravity CLI reference (full) | `antigravity-cli` |
| GitHub Copilot CLI reference | `gh-copilot-cli` |
| Cross-tool skill authoring rules | `research-for-skills/cross-tool-portability/cross-tool-portability.md` |
| GCP Workstations deployment | `gcp-workstations` |

---

## Gotchas

| Gotcha | Mitigation |
|---|---|
| **`codex exec` blocks reading stdin in non-interactive shells — even with an argv prompt.** With no prompt argument (or the explicit `-` stdin form) it hangs waiting on stdin (observed 2026-06-04); #155 (S049) established that in background/harness shells `codex exec "<argv prompt>"` ALSO reads stdin to EOF and hangs to timeout. | Close stdin on EVERY headless invocation: `codex exec "…" < /dev/null` (argv form) or piped (`cat brief.md \| codex exec -` — the pipe EOFs). Always wrap with `timeout` so any residual hang is bounded. |
| **Long-running Codex tasks may exit non-zero before writing synthesis** even when the research itself completes successfully. The `-o` output file may contain useful results despite a non-zero exit code. | Always check the output file before treating non-zero exit as fatal failure. Pattern: `codex exec ... -o "$OUT"; if [ -s "$OUT" ]; then echo "got result"; fi` |
| `--ephemeral` keeps a prompt out of `~/.codex/sessions/`, but every role-resolved call (TOP and `consultant_support`) runs non-ephemeral on purpose (quota metering), so their prompts DO persist there — and every prompt is visible in the running process | Never put secrets in any prompt; use env vars or file references. See HARD-RULE at top of file. |
| `/codex:review --background`, `/codex:status` and `/codex:result` are a DEAD PATH (plugin not installed) | Run `codex exec … -o "$OUT" &`, then `wait` and read the `-o` file. |

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: codex
    verified_against: "0.154.0"
    verified_on: "2026-09-14"
  - kind: tool_version
    subject: agy
    verified_against: "1.2.2"
    verified_on: "2026-09-14"
  - kind: tool_version
    subject: codex-plugin
    verified_against: "1.0.4"
    verified_on: "2026-06-10"
-->
