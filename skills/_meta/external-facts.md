# External-fact register

Facts this harness depends on that **somebody else owns and can change without telling us** —
vendor pricing, plan limits, API deprecations, licence terms, account defaults.

Every other `FRESHNESS:v1` anchor points at a file whose *contents* rot. These do not. The thing
that rots is outside the repo, so re-verification needs an authoritative source and a date the
claim was last confirmed against it. That is why `external_fact` requires `source_url` and
`verified_on` — an anchor that only says *"check something, somewhere"* is the prose reminder this
kind exists to replace.

## What belongs here

- A fact we **rely on** in a skill, gate, or design decision, and
- which is **controlled by a third party**, and
- whose change would be **silent** — nothing in the harness would fail or warn.

## What does NOT belong here

- Anything with a file we can read → use `date_review` on that file.
- A one-off task with a due date → `tasks.md` with the `⏰ ON/AFTER` convention.
- **Facts owned by a consumer project.** trading02's Alpaca non-professional / non-display terms
  and its FMP *"Usage: Individual"* licence conflict are exactly this class, but they are that
  project's dependencies, not foundry's. Foundry builds the mechanism; the tenant registers its
  own facts. (See PROJECT.md, *Foundry BUILDS; projects CONSUME*.)

---

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: claude-p-subscription-billing
    source_url: https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
    verified_on: 2026-08-06
    review_by: 2026-11-04
    claim: "Headless `claude -p` and the Claude Agent SDK STILL draw from the Claude subscription's usage limits. The 2026-06-15 change that would have moved them off-subscription onto a monthly credit was PAUSED and the credit is not available."
-->

## `claude-p-subscription-billing`

**Current claim, verified 2026-08-06:** headless `claude -p` draws on the Claude subscription, the
same pool as interactive use.

**Why it is registered as high volatility:** this fact already changed and changed back inside two
months. A billing split was announced for 2026-06-15 — Agent SDK and `claude -p` usage would stop
counting against subscription limits, replaced by a monthly credit — and was then paused before
taking effect, with the credit withdrawn. The source page currently reads *"For now, nothing has
changed."* A paused change is an unstable state; it can resume.

**What depends on it.** Every design that treats LLM quota as a single arbitrated pool shared
between headless members and the operator's own interactive session. If the split resumes, headless
delegation moves to separate billing and that premise is void — quota contention disappears and a
real per-token cost appears in its place.

**How to re-verify.** Fetch the source URL and check whether the pause is still in effect. Then
confirm against the account, which is authoritative for *this* host:

```bash
# account tier + whether extra usage is live (NOT the same as the account flag)
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude.json')));\
print(d['oauthAccount'].get('organizationRateLimitTier'), d.get('cachedExtraUsageDisabledReason'));\
print(json.dumps(d['cachedUsageUtilization']['utilization'].get('extra_usage'),indent=2))"
```

**Trap found on 2026-08-06, worth repeating at every review:** `oauthAccount.hasExtraUsageEnabled`
and the live `extra_usage.is_enabled` **disagreed** — the account flag said `true` while the
utilization record said `false` with `disabled_reason: "out_of_credits"`. Read the utilization
record, not the flag. Note also that `cachedUsageUtilization` is a *cache*: check `fetchedAtMs`
before trusting it (it was 11 days stale when this was written, with both reset windows long past).
`/usage` in an interactive session is the way to force a fresh read.

---

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: codex-model-roster
    source_url: https://learn.chatgpt.com/docs/models
    verified_on: 2026-09-24
    review_by: 2026-12-24
    claim: "The codex CLI roster cache ~/.codex/models_cache.json carries fetched_at, client_version and per-model slug, visibility, priority, supported_in_api, supported_reasoning_levels (objects keyed effort) and upgrade. On 2026-09-24 (08:01Z), client 0.156.1, the listed models were gpt-6-astra p1, gpt-6-sol p2, gpt-6-luna p3, gpt-5.6-sol p4, gpt-5.6-terra p7, gpt-5.6-luna p8 and gpt-5.5 p12 (gpt-5.5 retires 2026-10-14); gpt-reserve (p3) and codex-auto-review (p43) were hidden; there is no GPT-6 Terra; upgrade was null on every 5.6/6 entry; gpt-6-sol and gpt-5.6-terra offer low through max and ultra. priority is NOT stable between refreshes: on 2026-09-15 gpt-5.6-sol was observed at 4, 1 (tied with gpt-6-astra), 4 and 1 again, so every priority above is a snapshot. A tie between models of different generations breaks by generation (#282 R16), but gpt-6-astra and gpt-6-sol are the same generation, so their tie breaks by incumbent, then slug."
  - kind: external_fact
    subject: agy-model-roster
    source_url: https://antigravity.google/docs/models/
    verified_on: 2026-09-14
    review_by: 2026-12-14
    claim: "agy models lists the models the Antigravity account can select, one slug per line in the first tab-separated column. On 2026-09-14, agy 1.2.2, that was gemini-3.8-flash, gemini-3.7-flash and gemini-3.6-flash at high, medium and low, gemini-3.1-pro-high, gemini-3.1-pro-low, claude-sonnet-4-6, claude-opus-4-6-thinking and gpt-oss-120b-medium. gemini-3.5-flash was no longer listed."
-->

## `codex-model-roster`

**Current claim, verified 2026-09-24** (08:01Z, this host's cache, codex 0.156.1): seven listed models —
`gpt-6-astra` (priority 1), `gpt-6-sol` (2), `gpt-6-luna` (3), `gpt-5.6-sol` (4), `gpt-5.6-terra` (7),
`gpt-5.6-luna` (8), `gpt-5.5` (12, **retires 2026-10-14**) — plus two hidden entries, `gpt-reserve` (3) and
`codex-auto-review` (43). **There is no GPT-6 Terra.** `upgrade` is null on every 5.6/6 entry today; it flaps, so
it is never auto-followed as a roster decision. `gpt-6-sol` and `gpt-5.6-terra` both offer `low` through `max` and
`ultra`. Roster rev 3 (#302) seats `gpt-6-sol` as the codex std tier and `gpt-5.6-terra` as the codex support tier.

**Earlier snapshot, verified 2026-09-14** against the vendor page and this host's cache (codex 0.154.0): five
listed models — `gpt-6-astra` (1), `gpt-5.6-sol` (4), `gpt-5.6-terra` (7), `gpt-5.6-luna` (8), `gpt-5.5` (12) —
the same two hidden entries, `upgrade` null on every entry. No model supports the `minimal` effort;
`gpt-5.6-luna` lacks `ultra`, `gpt-5.5` lacks `max` and `ultra`.

**`priority` FLAPS — the numbers above are a snapshot, not a standing fact (observed 2026-09-15).** The vendor
rewrites this cache every few minutes, and `gpt-5.6-sol`'s priority moved four times in eight hours: 4 at
14:38:49Z, **1 at 20:45:50Z** (tied with `gpt-6-astra`), back to 4 at 22:25:15Z, and 1 again at 22:38:08Z. Do not
treat any dated priority for `gpt-5.6-sol` as current, here or in any skill that quotes it. What IS stable is the
tie-break rule: a tie between models of DIFFERENT generations goes to the higher generation (#282 R16), which is
what held the 2026-09-15 ties for `gpt-6-astra` over `gpt-5.6-sol`. It does not cover `gpt-6-sol`: astra and
sol-6 are both generation 6, so their tie breaks by the incumbent (the last recorded TOP), then by slug, and a
strict inversion serves the std model on TOP seats with `top_resolved_to_std: true` in provenance (#302).

**What depends on it.** `skills/_meta/seat_model.py` resolves every codex TOP selector (`code_reviewer`,
`consultant_main`, `arbiter`, `escalation`) through `codex_model.select_top()`: the lowest-priority entry that is
`visibility == "list"`, `supported_in_api`, and supports the role's effort, following a populated `upgrade`. Those
field meanings are the vendor's, not ours. If `visibility` gains a third value, `priority` stops meaning
preference, or `supported_reasoning_levels` changes shape, the selector keeps working and quietly picks the wrong
model.

**Why this anchor is only half the fact.** The roster itself changes faster than any review cadence, and a
markdown anchor cannot read a JSON file. The live half is the SessionStart digest (`_meta/freshness_nudge.py`):
it prints `codex-roster: <N> models, cache fetched <date>, client <ver>`, announces a TOP change once per
change, warns `roster stale` when the cache is older than 7 days, and shows every active freeze pin. This anchor
covers what the digest cannot see: whether the field semantics above still hold.

**How to re-verify.** Read the vendor page, then the local cache, which is authoritative for what this account
can call:

```bash
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.codex/models_cache.json'),encoding='utf-8'));\
print(d.get('fetched_at'),d.get('client_version'));\
[print(m['slug'],m.get('visibility'),m.get('priority'),m.get('supported_in_api'),\
[l.get('effort') for l in m.get('supported_reasoning_levels') or []],m.get('upgrade'))\
 for m in sorted(d['models'],key=lambda m:m.get('priority') or 999)]"
```

**Traps found on 2026-09-14.** The vendor page is not per-account: it also lists `gpt-5.3-codex-spark`,
`gpt-5.4`, `gpt-5.4-mini`, `gpt-5.2` and `gpt-5.3-codex`, none of which are in this account's cache, and it names
no default model. `https://developers.openai.com/codex/models` now answers with a 308 redirect to the source URL
above. Do not confirm the roster with `seat_model.py emit`: it resolves every seat and so rewrites
`~/.claude/state/seat-model-tops.json` (by design), which can move a TOP-change announcement.

---

## `agy-model-roster`

**Host cache update, 2026-10-20** (agy 1.4.3, `~/.claude/state/agy-models.json`; NOT re-verified against the
vendor page): `gemini-4-argon-*` and `gemini-3.8-flash-*` at `high`, `medium` and `low`, `claude-opus-5-5-*`,
`claude-sonnet-5-5-*` and `gpt-oss-120b-medium`. No pro line is listed. Argon became the roster's agy family at
rev 6 (#367).

**Last vendor-page claim, verified 2026-09-14** against the vendor page and this host's cache (agy 1.2.2): the account
lists `gemini-3.8-flash-*`, `gemini-3.7-flash-*` and `gemini-3.6-flash-*` at `high`, `medium` and `low`,
`gemini-3.1-pro-high` and `-low`, and three non-Google models. `gemini-3.5-flash-*` is gone.

**What depends on it.** The agy family rule is enforced in code (`seat_model.AGY_FAMILY_PATTERN`,
`^gemini-\d{1,9}(\.\d{1,9})*-<family>-(high|medium|low)$`, the family read from `model_roster.AGY_FAMILY`; rev 6:
`argon`), and the agy TOP selector picks the highest version `v` for which `gemini-<v>-<family>-<level>` is listed.
Both assume the vendor keeps that slug pattern. A renamed line (a new suffix, a dropped level) would make every agy
seat fall back to its failure path; another model renamed into the family pattern would be selected.

**The live half** is the same digest: `roster stale: agy (...)` when `~/.claude/state/agy-models.json` is older
than 7 days or absent on a host that uses agy, and the agy freeze pin while one exists. `env-adoption/scripts/probe.sh`
refreshes the cache on its inventory path; `freshness_nudge.py` only reads it (no subprocess).

**How to re-verify.** Read the vendor page, then list the account's models. `agy models` is a roster listing, not
a model call; stdin must be closed (CLAUDE.md STDIN RULE):

```bash
timeout 5 agy models < /dev/null | cut -f1
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/state/agy-models.json'),encoding='utf-8'));\
print(d.get('fetched_at'),d.get('agy_version'));print(*d['models'],sep='\n')"
```

**Traps found on 2026-09-14.** The vendor page lists display names ("Gemini 3.8 Flash", "Claude Opus 4.6
(thinking)"), not slugs, and does not show levels; only `agy models` gives the slugs the selector matches. The page
also says availability depends on the plan (it marks the Claude and GPT models unavailable on Enterprise plans), so
a different account can list a different roster. A web search summary on the same day repeated an older blog
post's "Gemini 3.5 Flash is the default"; the models page itself names no default.

---

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: chatgpt-plus-codex-quota
    source_url: https://learn.chatgpt.com/docs/pricing
    verified_on: 2026-09-15
    review_by: 2026-09-28
    claim: "Codex on the ChatGPT Plus plan draws on one usage allowance estimated per five-hour period, and weekly limits may also apply; OpenAI publishes estimated ranges, not fixed limits, and points to the usage dashboard for current limits. On 2026-09-15 the pricing page estimated Plus local messages per five-hour period at 5-45 for GPT-6 Astra and 10-100 for GPT-5.6 Sol. LOCAL observations, not vendor facts (design 2.4, n=2, 2026-09-14, concurrent use not excluded): a repo-exploring astra xhigh call moved this account's 5h window from 0 to 15 percent and weekly from 0 to 2; a targeted challenger moved them from 19 to 26 and from 3 to 4."
-->

## `chatgpt-plus-codex-quota`

**Current claim, verified 2026-09-15** against the vendor pricing page: Codex on ChatGPT Plus draws on one
usage allowance, estimated per five-hour period, and weekly limits may also apply. The page's Plus column gives
`GPT-6 Astra` **5-45** and `GPT-5.6 Sol` **10-100** local messages per five-hour period (Terra 25-200, Luna
250-2,000); Pro 5x and Pro 20x list five and twenty times those ranges. In its own words: *"The estimates below
show local messages per five-hour period. […] These estimates are not fixed message limits; check your usage
dashboard for current limits and reset times."* and *"Local messages and cloud chats share your plan's usage
allowance. Weekly limits may also apply."*

**Local observations, not vendor facts.** Design §2.4 of `docs/plans/2026-09-14-top-tier-model-roles-design.md`
measured two astra @ xhigh calls on this account on 2026-09-14 (n=2, concurrent use not excluded): a
repo-exploring design explorer moved the 5h window 0 → 15% and weekly 0 → 2%; a challenger with targeted reads
moved them 19 → 26% and 3 → 4%. That is roughly 6-7 repo-exploring astra calls per window, at the low end of the
vendor's 5-45 because call shape dominates cost. These numbers belong to this host. They are evidence for the
review, and they do not re-verify the claim.

**Why a plan review is registered here.** The register excludes a one-off task with a due date, and the
2026-09-28 review is one. What is registered is the third-party fact the review depends on: OpenAI owns the Plus
limits and can move them silently. `review_by` carries the review date because the decision must not outlive a
re-check of the fact it rests on.

**What depends on it.** Amendment 1 (`docs/plans/2026-09-14-top-tier-model-roles-amendment-1.md`) D5: stay on
ChatGPT Plus for two weeks and review the plan on **2026-09-28** from recorded evidence. The astra admission in
`_meta/codex_quota.py` assumes a Plus-sized window: a per-cycle budget of at most one consult, one challenger and one
advisory review. The 70% trip-wire it once assumed was retired by #322 (2026-09-27): a seat is refused for quota
only on real exhaustion — a fresh reading at 99% or more on either window, the limit reached, or the persisted
exhausted-until record — and a quota refusal first waits for the reset (notifying the user when it is more than
20 minutes away, up to 30 minutes) before a stand-in serves. Under D6 a codex TOP seat that astra cannot serve is
run by a fresh Claude main-tier agent. If OpenAI narrows the Plus ranges, more seats
are substituted; if they widen, or the plan changes, the budget refuses astra work the window could have carried.
Either way the review reads it from the substitution rows.

**The live half** is the SessionStart digest (`_meta/freshness_nudge.py`):
`astra: <N> substitutions this week (<reason> <n>, …) · plan review 2026-09-28`, counted account-wide from every
`~/.claude/projects/*/astra-budget.jsonl`, next to the `codex-quota: 5h <p>% · weekly <w>%` rider. The date lives in
`freshness_nudge.ASTRA_PLAN_REVIEW`, and `tests/test_freshness_nudge.py` fails when it drifts from this anchor's
`review_by`. Move both together.

**How to re-verify.** Fetch the source URL (`https://developers.openai.com/codex/pricing` answers with a 308
redirect to it) and read the Plus column. Then read this account's own window, which is authoritative for this
host (`/status` inside an interactive codex session shows the same), and tally the substitution evidence without
writing anything:

```bash
python3 ~/.claude/skills/_meta/codex_quota.py snapshot --json
python3 -c "import collections,glob,json,os;n=collections.Counter();\
[n.update([(r.get('use'),r.get('reason'))]) for f in glob.glob(os.path.expanduser('~/.claude/projects/*/astra-budget.jsonl'))\
 for l in open(f,encoding='utf-8') if '\"substitute_for\"' in l for r in [json.loads(l)] if r.get('substitute_for')=='codex'];\
print(sum(n.values()),'substitutions (all time) by (use, reason):',dict(n))"
```

**Traps found on 2026-09-15.** The ranges are per *local message*, and the page warns that "larger projects,
long-running tasks, or extended sessions that require the agent to hold more context will use significantly more
per message". A range cannot be turned into a call budget; only the account's own `rate_limits` readings can. The
OpenAI Help Center articles on Codex plan limits answered HTTP 403 to a non-browser fetch, so none of them could be
the source. The same pricing page carries dated promotions ("From June 11 through June 24, 2026, …" banked
rate-limit resets), so read the dates before treating a change as permanent. Do not probe the live window with
`seat_model.py argv … --use` or `codex_quota.py admit --record`: each appends a row to a real budget store, and a
probe consumes a slot or fabricates review evidence. A bare `codex_quota.py admit` is check-only since #282 r15 and
writes nothing, but it still reads the live meter and budget store; `codex_quota.py snapshot --json` reads the
window alone.

---

## Candidates not yet registered

Listed rather than added, so the register stays deliberate rather than accumulating:

- **agy account default model** — self-reported as `gemini-3.6-flash` by a 2026-09-09 consultancy call
  (self-report is unreliable). The roster is registered above (`agy-model-roster`); the default is not. Since
  S081 deliberative agy seats pin their model through `seat_model`, and since #367 (2026-10-21) every agy call does,
so the default reaches only an unpinned call — which then rides a family the roster forbids.
- **Anthropic model roster and pricing** — the `claude-api` skill carries a table marked
  `cached: 2026-06-24`.
- **Codex CLI plan tier** — `plan_type: plus` in the rollouts. Which plan the account is on is the user's choice
  (amendment 1 D5), not a vendor fact; the Plus plan's Codex limits are registered above
  (`chatgpt-plus-codex-quota`).
