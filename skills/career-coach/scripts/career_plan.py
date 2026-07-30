#!/usr/bin/env python3
"""career_plan.py — S074. The user's career profile, actions, and the routine recall.

Turns the career-* family from something you consult into something that KNOWS YOU and
comes back to you. One store per person, carried across sessions.

    init      create the store
    intake    the NEXT few questions worth asking — never the whole questionnaire
    set       record a profile field, with provenance
    note      record a free observation
    add       add an action — typed, optionally dated, optionally recurring
    done      close an action, capturing how it went
    drop      abandon an action, with a reason
    followup  actions that closed without an outcome — the "how did it go?" queue
    suggest   candidate actions derived from the profile — proposals, never auto-added
    status    what is due, overdue, stale, and still unknown — all COMPUTED
    review    the routine recall: run this at the start of any career conversation
    plan      render the current profile + open actions as a markdown plan

ACTIONS ARE TYPED, AND THE TYPE CARRIES A FOLLOW-UP QUESTION

"Apply for the role", "finish the course", "post on LinkedIn", "message the recruiter",
"raise it in your 1:1" are not the same kind of thing, and the useful question afterwards
differs: an application has a response, a conversation has a commitment, a post has a
reaction. So each kind carries its own follow-up, and `followup` asks it.

**Closing an action without recording what happened is the loss this prevents.** "Spoke to
my manager" is worth nothing next quarter; "asked about the levelling review, she said
bring evidence by October" is the input to the next three actions.

RECURRENCE ROLLS FORWARD, IT DOES NOT BACKFILL

A fortnightly 1:1 completed two months late must not spawn four instantly-overdue
occurrences. The next date is advanced from the original due date to preserve cadence, then
rolled forward until it is in the future — one action, correctly dated.

WHY INTAKE IS STAGED

A forty-question profile form gets abandoned, and an abandoned form leaves you with
neither the answers nor the goodwill to ask again. So questions carry a priority and a
statement of what they UNLOCK, and `intake` returns a handful at a time — the ones whose
answers actually change the next recommendation. Everything else waits until it matters.

WHAT THIS DELIBERATELY WILL NOT DO

It does not infer goals. A person who mentions a promotion is not thereby "targeting a
promotion", and a tool that quietly decides otherwise will produce a confident plan for a
career the user does not want. Unknown is stored as unknown, and it is distinct from "no".

Every field carries provenance -- `confirmed` (the user said it) or `inferred` (something
concluded it). Only the user can produce `confirmed`. A plan built on inferences that
present as facts is the failure mode this exists to prevent.

Nothing is asserted that can be computed. `overdue`, `stale` and `due_in_days` are derived
from dates at read time and never stored, because a stored status is wrong the next day.

Stdlib only. Exit: 0 nothing needs attention · 2 something is due/overdue/stale · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_STORE = Path.home() / ".claude" / "state" / "career" / "profile.json"
SCHEMA = "career-plan/1"

# Profile fields worth knowing, in the order they unlock advice.
# (key, question, why it matters / what it unlocks, priority 1=highest)
QUESTIONS = [
    ("current_role", "What is your official job title, and what grade or level is it recorded at?",
     "Everything anchors to the recorded title — it is the only machine-readable fact about you.", 1),
    ("target", "What role are you aiming at next, and roughly by when?",
     "Without a target, advice is generic. This selects which evidence matters.", 1),
    ("scope_vs_title", "Does your official title reflect what you actually do? If not, what is the gap?",
     "Decides whether the work is positioning or record-correction (career-internal-visibility §10).", 1),
    ("sector", "What sector, and is it regulated?",
     "Regulated sectors change publishing, outside-interest and evidence rules entirely.", 2),
    ("employer_cycle", "When do your performance review points fall (mid-year, year-end, calibration)?",
     "Every deadline in the plan is derived from these dates.", 2),
    ("tenure_in_role", "How long have you held the current title?",
     "A long unchanged title needs the progression curve shown, not just the years.", 2),
    ("evidence_habit", "Do you keep a running record of your accomplishments? Where?",
     "If not, this is usually the single highest-value change available.", 2),
    ("internal_system", "Does your employer run an internal talent marketplace (Eightfold or similar)?",
     "If yes, the internal skills profile gates which opportunities you are shown at all.", 3),
    ("sponsor", "Who, senior to you, would speak for you in a calibration room?",
     "Sponsorship decides senior promotions; its absence is a plan item, not a detail.", 3),
    ("public_presence", "What is your public presence — LinkedIn, writing, talks, code?",
     "Determines whether external positioning has anything to stand on.", 3),
    ("constraints", "Any constraints — location, visa, notice period, family, pay floor?",
     "A plan that ignores a hard constraint gets discarded, and the time is wasted.", 3),
    ("side_work", "Do you have a business, consultancy or side project alongside the role?",
     "Strong evidence of scope — but check contract and declaration duty before publishing.", 4),
    ("preferences", "How do you want to be coached — direct challenge, or steady encouragement?",
     "Sets the register. Recorded once, applied every session.", 4),
]
QMAP = {k: (q, why, pri) for k, q, why, pri in QUESTIONS}

STALE_DAYS = 180  # a profile field older than this is suspect, not wrong

# Action kinds. The follow-up is the question worth asking AFTER it is done — it differs
# by kind, which is the whole reason kinds exist.
KINDS = {
    "apply":       ("Job application", "Any response yet, and what stage is it at?"),
    "training":    ("Training / certification", "Finished it? What can you now evidence that you could not before?"),
    "post":        ("Public writing / LinkedIn post", "What response did it get, and from whom?"),
    "outreach":    ("Message a recruiter or contact", "Did they reply? What did they say?"),
    "conversation": ("Conversation with manager / sponsor / stakeholder",
                     "How did it go — and what, specifically, did they commit to?"),
    "meeting-prep": ("Prepare an agenda (1:1, review, skip-level)",
                     "Did you cover the agenda? What came out of it?"),
    "evidence":    ("Capture evidence / brag-doc entry", "Recorded with the number and who saw it?"),
    "profile":     ("Update CV, LinkedIn or internal skills profile", "Updated and live?"),
    "review":      ("Review-cycle task (self-assessment, 360, goals)", "Submitted? Any feedback yet?"),
    "admin":       ("Administrative step", "Done?"),
}
RECUR_DAYS = {"weekly": 7, "fortnightly": 14, "monthly": 30, "quarterly": 91}


# ---------------------------------------------------------------- store


def _today(s: str | None) -> date:
    if not s:
        return date.today()
    try:
        return date.fromisoformat(s)
    except ValueError:
        sys.exit(f"[input] --today must be YYYY-MM-DD, got {s!r}")


def load(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"[input] no store at {path} — run `init` first")
    try:
        d = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"[input] store is not valid JSON: {e}")
    if d.get("schema") != SCHEMA:
        sys.exit(f"[input] store schema {d.get('schema')!r}, expected {SCHEMA!r}")
    return d


def save(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


# ---------------------------------------------------------------- derived


def age_days(iso: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(iso[:10])).days
    except (ValueError, TypeError):
        return None


def derive(store: dict, today: date) -> dict:
    """Everything time-dependent, computed at read time. Never stored."""
    open_actions = []
    for a in store.get("actions", []):
        if a.get("state") != "open":
            continue
        row = dict(a)
        due = a.get("due")
        if due:
            try:
                row["due_in_days"] = (date.fromisoformat(due) - today).days
                row["overdue"] = row["due_in_days"] < 0
            except ValueError:
                row["due_in_days"] = None
                row["overdue"] = False
        else:
            row["due_in_days"] = None
            row["overdue"] = False
        open_actions.append(row)
    open_actions.sort(key=lambda r: (r["due_in_days"] is None, r["due_in_days"] or 0))

    prof = store.get("profile", {})
    stale = []
    for k, v in sorted(prof.items()):
        a = age_days(v.get("updated", ""), today)
        if a is not None and a > STALE_DAYS:
            stale.append({"key": k, "age_days": a})

    unanswered = [
        {"key": k, "question": q, "why": why, "priority": pri}
        for k, q, why, pri in QUESTIONS if k not in prof
    ]
    unanswered.sort(key=lambda r: r["priority"])

    inferred = [k for k, v in sorted(prof.items()) if v.get("provenance") == "inferred"]

    # Closed without an outcome recorded — the "how did it go?" queue.
    pending = []
    for a in store.get("actions", []):
        if a.get("state") == "done" and not a.get("outcome"):
            k = a.get("kind", "admin")
            pending.append({"id": a["id"], "text": a["text"], "kind": k,
                            "closed": a.get("closed"),
                            "question": KINDS.get(k, KINDS["admin"])[1]})

    return {"open": open_actions, "stale": stale, "unanswered": unanswered,
            "inferred": inferred, "followups": pending,
            "overdue": [r for r in open_actions if r["overdue"]],
            "due_soon": [r for r in open_actions
                         if not r["overdue"] and r["due_in_days"] is not None
                         and r["due_in_days"] <= 14]}


def next_due(prev_due: str | None, every: str, today: date) -> str:
    """Advance a recurrence WITHOUT backfilling missed occurrences.

    Cadence is preserved by stepping from the original due date, but a task completed
    late must not spawn a queue of instantly-overdue occurrences — so the date rolls
    forward until it is in the future. One action, correctly dated.
    """
    step = RECUR_DAYS[every]
    base = date.fromisoformat(prev_due) if prev_due else today
    nxt = base + timedelta(days=step)
    while nxt <= today:
        nxt += timedelta(days=step)
    return nxt.isoformat()


# ---------------------------------------------------------------- commands


def cmd_init(args) -> int:
    if args.store.is_file() and not args.force:
        print(f"store already exists at {args.store} — use --force to recreate")
        return 0
    save(args.store, {"schema": SCHEMA, "created": _today(args.today).isoformat(),
                      "profile": {}, "actions": [], "notes": [], "next_action_id": 1})
    print(f"created {args.store}")
    print("Next: `intake` for the questions worth asking first.")
    return 0


def cmd_intake(args) -> int:
    store = load(args.store)
    d = derive(store, _today(args.today))
    batch = d["unanswered"][: args.count]
    if not batch:
        print("Profile complete — every tracked field has an answer.")
        if d["stale"]:
            print(f"But {len(d['stale'])} field(s) are over {STALE_DAYS} days old; `review` lists them.")
        return 0
    print(f"Ask these {len(batch)} (of {len(d['unanswered'])} outstanding). "
          f"Ask them conversationally, not as a form:\n")
    for r in batch:
        print(f"  [{r['key']}] {r['question']}")
        print(f"      why: {r['why']}\n")
    print("Record each answer:  career_plan.py set --key <key> --value \"<their words>\"")
    print("An answer you were not given is NOT a field to guess — leave it unset.")
    return 0


def cmd_set(args) -> int:
    store = load(args.store)
    if args.key not in QMAP and not args.allow_custom:
        sys.exit(f"[input] unknown field {args.key!r}. Known: {', '.join(sorted(QMAP))}\n"
                 f"        (use --allow-custom to record something outside the schema)")
    prov = "inferred" if args.inferred else "confirmed"
    store.setdefault("profile", {})[args.key] = {
        "value": args.value, "provenance": prov,
        "updated": _today(args.today).isoformat(),
    }
    save(args.store, store)
    print(f"set {args.key} ({prov})")
    if prov == "inferred":
        print("  NOTE: inferred, not confirmed. Verify with the user before planning on it.")
    return 0


def cmd_note(args) -> int:
    store = load(args.store)
    store.setdefault("notes", []).append(
        {"date": _today(args.today).isoformat(), "text": args.text})
    save(args.store, store)
    print("noted")
    return 0


def _new_action(store: dict, text: str, kind: str, due: str | None,
                created: date, every: str | None) -> int:
    aid = store.get("next_action_id", 1)
    store.setdefault("actions", []).append({
        "id": aid, "text": text, "kind": kind, "due": due, "state": "open",
        "created": created.isoformat(), "recur": every,
    })
    store["next_action_id"] = aid + 1
    return aid


def cmd_add(args) -> int:
    store = load(args.store)
    if args.kind not in KINDS:
        sys.exit(f"[input] unknown --kind {args.kind!r}. Known: {', '.join(sorted(KINDS))}")
    if args.recur and args.recur not in RECUR_DAYS:
        sys.exit(f"[input] unknown --recur {args.recur!r}. Known: {', '.join(RECUR_DAYS)}")
    if args.due:
        try:
            date.fromisoformat(args.due)
        except ValueError:
            sys.exit("[input] --due must be YYYY-MM-DD")
    if args.recur and not args.due:
        sys.exit("[input] --recur needs --due — a cadence with no first date has nothing to step from")
    aid = _new_action(store, args.text, args.kind, args.due, _today(args.today), args.recur)
    save(args.store, store)
    print(f"added #{aid} [{args.kind}]: {args.text}"
          + (f" (due {args.due}" if args.due else "")
          + (f", every {args.recur})" if args.recur else (")" if args.due else "")))
    return 0


def _close(args, state: str, reason: str | None) -> int:
    store = load(args.store)
    today = _today(args.today)
    for a in store.get("actions", []):
        if a["id"] != args.id:
            continue
        if a["state"] != "open":
            print(f"#{args.id} is already {a['state']}")
            return 0
        a["state"] = state
        a["closed"] = today.isoformat()
        if reason:
            a["outcome" if state == "done" else "reason"] = reason
        msg = [f"#{args.id} -> {state}"]
        if state == "done" and a.get("recur"):
            nd = next_due(a.get("due"), a["recur"], today)
            nid = _new_action(store, a["text"], a.get("kind", "admin"), nd, today, a["recur"])
            msg.append(f"recurring: next occurrence #{nid} due {nd}")
        save(args.store, store)
        print("\n".join(msg))
        if state == "done" and not reason:
            k = a.get("kind", "admin")
            print(f"  no outcome recorded — ask: {KINDS.get(k, KINDS['admin'])[1]}")
            print(f"  then: career_plan.py done --id {args.id} ... or `followup` to see the queue")
        return 0
    sys.exit(f"[input] no open action #{args.id}")


def cmd_done(args) -> int:
    return _close(args, "done", args.result)


def cmd_drop(args) -> int:
    return _close(args, "dropped", args.reason)


def cmd_followup(args) -> int:
    """Actions that closed without anyone recording what happened."""
    store = load(args.store)
    d = derive(store, _today(args.today))
    if not d["followups"]:
        print("Nothing awaiting an outcome.")
        return 0
    print(f"{len(d['followups'])} action(s) closed with no outcome recorded. Ask:\n")
    for r in d["followups"]:
        print(f"  #{r['id']} [{r['kind']}] {r['text']}  (closed {r['closed']})")
        print(f"      -> {r['question']}\n")
    print("Record it:  career_plan.py outcome --id <n> --text \"<what happened>\"")
    print("An outcome usually produces the NEXT action — add it while you have it.")
    return 2


def cmd_outcome(args) -> int:
    store = load(args.store)
    for a in store.get("actions", []):
        if a["id"] == args.id:
            if a.get("state") == "open":
                sys.exit(f"[input] #{args.id} is still open — close it with `done` instead")
            a["outcome"] = args.text
            save(args.store, store)
            print(f"#{args.id} outcome recorded")
            return 0
    sys.exit(f"[input] no action #{args.id}")


# Suggestions are derived ONLY from recorded profile facts. Each states the field it
# depends on, so an unavailable suggestion names what is missing instead of guessing.
# (requires_key, condition, kind, text)
SUGGESTIONS = [
    ("evidence_habit", lambda v: "no" in v.lower() or "none" in v.lower(),
     "evidence", "Start a brag document — capture entries at completion, not in December"),
    ("scope_vs_title", lambda v: any(w in v.lower() for w in ("no", "gap", "under", "above", "more")),
     "conversation", "Ask your manager about the levelling/title review route, with scope evidence"),
    ("employer_cycle", lambda v: True,
     "review", "Draft the self-assessment from the brag document ahead of the review point"),
    ("sponsor", lambda v: any(w in v.lower() for w in ("no", "none", "unsure", "nobody")),
     "conversation", "Identify and approach a potential sponsor senior enough to speak in calibration"),
    ("internal_system", lambda v: "yes" in v.lower(),
     "profile", "Complete the internal skills profile, including aspiration fields"),
    ("target", lambda v: True,
     "post", "Write one public post on your target topic — topical consistency compounds"),
    ("public_presence", lambda v: any(w in v.lower() for w in ("no", "none", "thin", "outdated", "stale")),
     "profile", "Refresh the LinkedIn headline and skills section against the target role"),
    ("target", lambda v: True,
     "outreach", "Message one recruiter or practitioner working in the target area"),
]


def cmd_suggest(args) -> int:
    store = load(args.store)
    prof = store.get("profile", {})
    open_texts = {a["text"].lower() for a in store.get("actions", []) if a.get("state") == "open"}

    proposed, blocked = [], []
    for key, cond, kind, text in SUGGESTIONS:
        if key not in prof:
            blocked.append((key, text))
            continue
        try:
            ok = cond(str(prof[key]["value"]))
        except Exception:
            ok = False
        if ok and text.lower() not in open_texts:
            proposed.append((kind, text, key, prof[key]["provenance"]))

    if proposed:
        print("Candidate actions, from what you have told me:\n")
        for kind, text, key, prov in proposed:
            warn = "   [based on an INFERRED field — confirm first]" if prov == "inferred" else ""
            print(f"  [{kind}] {text}\n      because: {key} = {prof[key]['value']}{warn}\n")
        print("These are PROPOSALS. Nothing is added until you say so:")
        print("  career_plan.py add --kind <kind> --text \"...\" [--due YYYY-MM-DD]")
    else:
        print("No new suggestions from the current profile.")
    if blocked:
        print(f"\nNot suggested, because these fields are unknown "
              f"({len(blocked)}): " + ", ".join(sorted({k for k, _ in blocked})))
        print("  Run `intake` to fill them — suggestions improve as the profile does.")
    return 0


def cmd_status(args) -> int:
    store = load(args.store)
    today = _today(args.today)
    d = derive(store, today)
    if args.json:
        print(json.dumps({"today": today.isoformat(), **d}, indent=2))
    else:
        print(f"CAREER STATUS — {today.isoformat()}")
        print(f"  open actions: {len(d['open'])}   overdue: {len(d['overdue'])}   "
              f"due <=14d: {len(d['due_soon'])}")
        print(f"  profile: {len(store.get('profile', {}))}/{len(QUESTIONS)} known, "
              f"{len(d['stale'])} stale, {len(d['inferred'])} inferred-not-confirmed")
        print(f"  awaiting outcome: {len(d['followups'])}")
        for r in d["overdue"]:
            print(f"    OVERDUE  #{r['id']} {r['text']}  ({abs(r['due_in_days'])}d late)")
        for r in d["due_soon"]:
            print(f"    due {r['due_in_days']:>3}d  #{r['id']} {r['text']}")
    return 2 if (d["overdue"] or d["due_soon"] or d["stale"] or d["followups"]) else 0


def cmd_review(args) -> int:
    """The routine recall. Run at the START of any career conversation."""
    store = load(args.store)
    today = _today(args.today)
    d = derive(store, today)
    prof = store.get("profile", {})

    print(f"CAREER RECALL — {today.isoformat()}\n")
    if prof:
        print("What I already know about you:")
        for k in sorted(prof):
            v = prof[k]
            flag = "" if v["provenance"] == "confirmed" else "  [INFERRED — confirm]"
            print(f"  {k:18} {v['value']}{flag}")
    else:
        print("Nothing recorded yet — start with `intake`.")
    print()

    if d["overdue"]:
        print("Overdue — raise these first:")
        for r in d["overdue"]:
            print(f"  #{r['id']} {r['text']}  ({abs(r['due_in_days'])}d late)")
        print()
    if d["due_soon"]:
        print("Coming up:")
        for r in d["due_soon"]:
            print(f"  #{r['id']} {r['text']}  (in {r['due_in_days']}d)")
        print()
    if d["followups"]:
        print("Closed without an outcome — ask how these went:")
        for r in d["followups"]:
            print(f"  #{r['id']} {r['text']}")
            print(f"      {r['question']}")
        print()
    if d["stale"]:
        print(f"Stale — over {STALE_DAYS} days old, so re-check rather than assume:")
        for r in d["stale"]:
            print(f"  {r['key']} ({r['age_days']}d)")
        print()
    if d["inferred"]:
        print("Recorded as INFERRED, never confirmed — verify before planning on these:")
        print("  " + ", ".join(d["inferred"]) + "\n")
    if d["unanswered"]:
        top = d["unanswered"][0]
        print(f"Highest-value thing still unknown: [{top['key']}] {top['question']}")
        print(f"  why: {top['why']}")

    return 2 if (d["overdue"] or d["due_soon"] or d["stale"] or d["followups"]) else 0


def cmd_plan(args) -> int:
    store = load(args.store)
    today = _today(args.today)
    d = derive(store, today)
    prof = store.get("profile", {})
    out = [f"# Career plan — {today.isoformat()}", ""]

    if prof:
        out += ["## Profile", "", "| Field | Value | Provenance | Updated |", "|---|---|---|---|"]
        out += [f"| {k} | {prof[k]['value']} | {prof[k]['provenance']} | {prof[k]['updated']} |"
                for k in sorted(prof)]
        out.append("")
    unknown = [r["key"] for r in d["unanswered"]]
    if unknown:
        out += ["**Not known:** " + ", ".join(unknown) +
                " — the plan below is limited accordingly.", ""]

    out += ["## Open actions", ""]
    if d["open"]:
        out += ["| # | Kind | Action | Due | Status |", "|---|---|---|---|---|"]
        for r in d["open"]:
            when = r["due"] or "—"
            st = "OVERDUE" if r["overdue"] else (
                f"in {r['due_in_days']}d" if r["due_in_days"] is not None else "no date")
            out.append(f"| {r['id']} | {r.get('kind','admin')} | {r['text']} | {when} | {st} |")
    else:
        out.append("_None recorded._")
    out.append("")

    notes = store.get("notes", [])
    if notes:
        out += ["## Notes", ""] + [f"- {n['date']} — {n['text']}" for n in notes[-10:]] + [""]

    text = "\n".join(out)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- cli


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Career profile, actions and routine recall.")
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--today", help="YYYY-MM-DD, for testing and back-dating")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("intake"); p.add_argument("--count", type=int, default=4)
    p.set_defaults(fn=cmd_intake)

    p = sub.add_parser("set")
    p.add_argument("--key", required=True); p.add_argument("--value", required=True)
    p.add_argument("--inferred", action="store_true",
                   help="record as INFERRED — something concluded it, the user did not say it")
    p.add_argument("--allow-custom", action="store_true")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("note"); p.add_argument("--text", required=True)
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("add")
    p.add_argument("--text", required=True); p.add_argument("--due")
    p.add_argument("--kind", default="admin", help=f"one of: {', '.join(sorted(KINDS))}")
    p.add_argument("--recur", default=None, help=f"one of: {', '.join(RECUR_DAYS)} (needs --due)")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("done"); p.add_argument("--id", type=int, required=True)
    p.add_argument("--result", default=None); p.set_defaults(fn=cmd_done)

    p = sub.add_parser("drop"); p.add_argument("--id", type=int, required=True)
    p.add_argument("--reason", default=None); p.set_defaults(fn=cmd_drop)

    p = sub.add_parser("status"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("followup"); p.set_defaults(fn=cmd_followup)

    p = sub.add_parser("outcome")
    p.add_argument("--id", type=int, required=True); p.add_argument("--text", required=True)
    p.set_defaults(fn=cmd_outcome)

    p = sub.add_parser("suggest"); p.set_defaults(fn=cmd_suggest)

    p = sub.add_parser("review"); p.set_defaults(fn=cmd_review)

    p = sub.add_parser("plan"); p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_plan)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
