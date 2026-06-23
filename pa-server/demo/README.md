# AMY M0b — real-data briefing demo

A runnable, real-data demo of the AMY M0b **routine engine** (`pa_core.pa_brief`).
It seeds a realistic Monday-morning workspace into a throwaway SQLite `pa.db`
(the production schema via `pa_server.init_db`) and composes the catch-up
briefing through the **real** routine-engine, so you can see the M0b engine
working end-to-end.

## Run it

```bash
cd pa-server
python3 demo/m0b_briefing_demo.py
# reproducible clock (DUE_TODAY / nudge-drain windows):
python3 demo/m0b_briefing_demo.py --now 2026-06-15T12:00:00
# persist the demo pa.db somewhere to poke at it:
python3 demo/m0b_briefing_demo.py --workspace /tmp/amy-demo-ws
```

## What it proves

The demo carries **zero business logic** — every behavior shown is the
production code path. With the default seed it renders the ~12-line terminal
briefing (`brief_output`) below and demonstrates:

- **Urgency taxonomy ordering** — `CONFLICT < OVERDUE_NUDGE < BLOCKER <
  DUE_TODAY < DELEGATION_FOLLOWUP < IN_FLIGHT < FYI`.
- **5-above-the-fold + a mandatory `[+N more]`** — exactly five concerns above
  the fold; the rest are folded behind the affordance and never dropped (T-RE-1).
- **In-composer nudge drain** — a due, thrice-snoozed *ingested* nudge is
  promoted (`pending` → `shown`) and surfaces louder as `OVERDUE_NUDGE`.
- **Role-lens reweight** — the workspace `role_profile` (Scrum) drives the
  `velocity` week-review framing; the reweight is ordering-only (membership
  invariant).
- **Remote-field delimiter wrapping** — the remote `conflict_detail` and the
  ingested nudge message stay `<untrusted_remote_content>…</…>` wrapped
  end-to-end (security floor L1); the user's own blocker note is **not** wrapped.

The reference body (workspace id is derived from the workspace path, so the
header varies) is captured at
[`../tests/fixtures/m0b-demo/expected_briefing.txt`](../tests/fixtures/m0b-demo/expected_briefing.txt):

```
AMY briefing — <workspace-id>
1. [CONFLICT] Sync conflict: jira ACME-204
2. [OVERDUE!] Overdue nudge (escalated)
3. [BLOCKER critical] Security review blocking the prod release
4. [BLOCKER high] Staging env down — waiting on infra
5. [DUE TODAY] Submit the Q2 board deck
[+5 more]
```

## Verified

The demo is asserted end-to-end by
[`../tests/integration/test_m0b_real_data_demo.py`](../tests/integration/test_m0b_real_data_demo.py),
which drives this same module and checks the fold, the urgency ordering, the
role-lens framing, the nudge drain, and remote-field wrapping on the realistic
seed. stdlib + pytest only — no new pip dependency.
