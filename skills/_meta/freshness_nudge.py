#!/usr/bin/env python3
"""freshness_nudge.py — the 4th SessionStart hook (Evergreening v1, S041).

A digest line at session start when the detection bus has something worth saying;
otherwise SILENCE (a suppressOutput envelope with zero text). Reads ONLY small JSON
files already on disk — NO subprocess, NO probing, NO corpus walk — so it stays well
under the §6.3 hard budget of <500ms.

Inputs (all best-effort; a missing/corrupt file is treated as "nothing to say"):
  ~/.claude/state/inventory.json                 (inventory age + plugins/mcp + tools)
  ~/.claude/state/inventory-history.jsonl        (tail since the ack watermark)
  ~/.claude/state/freshness/rot-report.json      (RED count + mtime for staleness)
  ~/.claude/state/freshness/identity-report.json (#119 3-tree status)
  ~/.claude/state/freshness/index.json           (by_deadline horizon)
  ~/.claude/state/freshness/ack.json             (dedup watermark + ack_until)
  ~/.claude/model-policy.yaml                    (validity; S081 complex-tier divergence)
  S081 seat-model inputs (design §4.3, §4.4; plan WP-203) — read, NEVER resolved:
  ~/.codex/models_cache.json                     (codex roster: listed count, fetched_at, client)
  ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl   (quota, via codex_quota.snapshot's bounded walk)
  ~/.claude/state/agy-models.json                (agy roster cache written by probe.sh)
  ~/.claude/state/seat-model-pins.json           (active freeze pins)
  ~/.claude/state/seat-model-tops.json           (last resolved TOP per provider, for announcements)
  S081 amendment 1 input (D5, D6; plan WP-F06, J18) — read, NEVER admitted or recorded:
  ~/.claude/projects/*/astra-budget.jsonl        (astra substitutions, ACCOUNT-WIDE: the 64 newest
                                                  store files, the last 256 KiB of each)
  #291 model-roster inputs (design s3.7; plan WP-5) — PARSED with ast, never executed:
  ~/.claude/skills/_meta/model_roster.py         (installed roster: REVISION, tiers, HISTORY)
  <cwd's foundry-lab checkout>/skills/_meta/model_roster.py   (repo roster, drift only)
  <cwd>/.process-observations/spawn-runs.jsonl   (served_model per Claude alias, last 256 KiB)

Nudge policy (BINDING table, §6.3):
  major/minor cli/plugin bump                  -> YES
  patch bump                                   -> NO (counted, surfaces at sweep)
  patch bump + command-set delta already filed -> YES
  tool/plugin/MCP added or removed             -> YES
  rot RED count > 0                            -> YES
  deadline within 30d (60d high-volatility)    -> YES (NEVER suppressed by ack)
  #119 identity mismatch                       -> YES (severity CRITICAL)
  S081 seat-model freeze pin active            -> YES (always-on while the pin exists)
  S081 roster stale / absent (tool in use)     -> YES (always-on while stale)
  S081 TOP changed (seat-model-tops.json)      -> YES (one episode per change, see below)
  #282 R16 codex priority tie recorded
       (seat-model-tops.json tie_break)        -> YES (ONE session per tie, never re-armed)
  S081 complex tier != roster Claude main      -> YES (default dedup class; #291: CLAUDE_MAIN)
  #291 model roster swapped (installed rev)    -> YES (one episode per revision, like TOP)
  #291 roster drift, repo rev != home rev
       (session inside a foundry-lab checkout) -> YES (one episode per rev pair, like TOP)
  #291 Claude alias re-pointed (spawn-runs
       served_model changed for the alias)     -> YES (one episode per change, like TOP)
  S081 astra substitutions this week, N >= 1   -> YES (default dedup class; a new count re-arms it;
                                                  once capped it still RIDES a non-empty digest)
  S081 codex roster currency, codex quota,
       astra substitutions this week, N == 0   -> RIDER (joins a non-empty digest only)
  S081 no astra budget store anywhere          -> SILENT (for that segment)
  everything else                              -> SILENT

Dedup: per-finding fingerprint sha1(surface|id|field|after); last_nudged + ack_until
in ack.json; same fingerprint max 2 nudges per 14 days; deadlines + identity mismatch
are NEVER suppressed (always-on classes). The watermark advances when a sweep runs or
the user acks (`--ack` also spends every current #291 roster episode). A TOP-change
announcement, and each #291 roster segment, uses the same fingerprint store with the
window disabled: one episode per change, at most MAX_NUDGES sessions, never re-armed
(so a manual `freshness_nudge.py` run cannot consume the only announcement). A recorded
codex priority tie (#282 R16, plan K29) is announced the same way with a cap of ONE
session (TIE_MAX_NUDGES), fingerprinted on (provider, priority_winner, sorted
((tied_with | {top}) - {winner})) — the deciding RULE and the served model are
displayed but are NOT part of the identity (#282 fix round 1 F11 / K45, so a rule that
flips slug -> incumbent on an unchanged tie is not a second announcement; fix round 2
G5 / K57 re-adds the served model to the IDENTITY, not the display, so following an
upgrade is not a second announcement either) — so only a different tie is announced
again; a manual run DOES spend it.

CLI:
  freshness_nudge.py --hook     # emit SessionStart hook JSON on stdout (the wired path)
  freshness_nudge.py            # human-readable: print the digest line (or "(silent)")
  freshness_nudge.py --ack      # advance the watermark / record an ack (suppress repeats)

NEVER raises to the caller: any internal failure emits the benign silent envelope.
Writes ONLY ack.json under ~/.claude/state/freshness/. (D1: no skill-write path.) The
S081 segments never call seat_model.resolve()/emit() — those rewrite
seat-model-tops.json — and never run a subprocess: codex_quota.snapshot() and
codex_model.load_roster_entries() are local bounded reads given explicit paths. The
astra segment never calls codex_quota.admit() or record_substitution() (each appends
to a budget store) and takes no lock: it reads the stores' bytes and nothing else.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
STATE = HOME / ".claude" / "state"
FRESH = STATE / "freshness"
INVENTORY = STATE / "inventory.json"
HISTORY = STATE / "inventory-history.jsonl"
ROT_REPORT = FRESH / "rot-report.json"
IDENTITY_REPORT = FRESH / "identity-report.json"
INDEX = FRESH / "index.json"
ACK = FRESH / "ack.json"
MODEL_POLICY = HOME / ".claude" / "model-policy.yaml"

# S081 seat-model inputs (WP-203). Module globals, like every path above, so the tests
# redirect them; the codex paths match codex_model / codex_quota (CODEX_HOME is not
# honoured there either).
CODEX_ROSTER = HOME / ".codex" / "models_cache.json"
CODEX_SESSIONS = HOME / ".codex" / "sessions"
AGY_ROSTER = STATE / "agy-models.json"
SEAT_PINS = STATE / "seat-model-pins.json"
SEAT_TOPS = STATE / "seat-model-tops.json"
# S081 amendment 1 (WP-F06): the per-project astra budget stores live one level below this.
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
_META = Path(__file__).resolve().parent

MAX_NUDGES = 2
TIE_MAX_NUDGES = 1   # #282 R16 (K29): a codex priority tie is announced in ONE session
NUDGE_WINDOW_DAYS = 14
DEFAULT_HORIZON = 30
HIGH_VOL_HORIZON = 60
ROT_STALE_DAYS = 7
HISTORY_TAIL_LINES = 200  # bounded read; we never scan the whole file


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mtime_age_hours(path: Path) -> float | None:
    try:
        return (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return None


def _fingerprint(surface, _id, field, after) -> str:
    raw = f"{surface}|{_id}|{field}|{after}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ── ack / dedup state ────────────────────────────────────────────────────────

def load_ack() -> dict:
    d = _read_json(ACK)
    return d if isinstance(d, dict) else {"fingerprints": {}, "watermark_ts": None}


def save_ack(ack: dict) -> None:
    try:
        FRESH.mkdir(parents=True, exist_ok=True)
        tmp = ACK.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ack, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(ACK))
    except OSError:
        pass


def _suppressed(ack: dict, fp: str, now: datetime,
                window_days: int | None = NUDGE_WINDOW_DAYS, cap: int = MAX_NUDGES) -> bool:
    """True if this fingerprint has hit its nudge cap inside the rolling window.
    `window_days=None` never re-arms: the cap, once reached, holds for good (S081
    TOP-change announcements — one episode per change). `cap` is the per-fingerprint
    session count (#282 R16: the tie announcement uses TIE_MAX_NUDGES)."""
    rec = ack.get("fingerprints", {}).get(fp)
    if not rec:
        return False
    ack_until = rec.get("ack_until")
    if ack_until:
        try:
            if now < datetime.fromisoformat(ack_until.replace("Z", "+00:00")):
                return True
        except ValueError:
            pass
    count = rec.get("count", 0)
    first = rec.get("first_ts")
    if count >= cap and window_days is None:
        return True
    if count >= cap and first:
        try:
            ft = datetime.fromisoformat(first.replace("Z", "+00:00"))
            if (now - ft).days < window_days:
                return True
        except ValueError:
            pass
    return False


def _record_nudge(ack: dict, fp: str, now: datetime,
                  window_days: int | None = NUDGE_WINDOW_DAYS) -> None:
    fps = ack.setdefault("fingerprints", {})
    rec = fps.get(fp)
    nowiso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not rec or (window_days is not None and (now - datetime.fromisoformat(
            rec.get("first_ts", nowiso).replace("Z", "+00:00"))).days >= window_days):
        fps[fp] = {"first_ts": nowiso, "count": 1, "last_ts": nowiso}
    else:
        rec["count"] = rec.get("count", 0) + 1
        rec["last_ts"] = nowiso


# ── feed readers (bounded) ──────────────────────────────────────────────────

def _tail_history(watermark_ts: str | None) -> list[dict]:
    """Read the bounded tail of inventory-history.jsonl; return records newer than
    the watermark (or the whole tail if no watermark)."""
    if not HISTORY.exists():
        return []
    try:
        with HISTORY.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()[-HISTORY_TAIL_LINES:]
    except OSError:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if watermark_ts and rec.get("ts", "") <= watermark_ts:
            continue
        out.append(rec)
    return out


def _deadlines_due(index: dict, today: date) -> list[dict]:
    out = []
    for d in (index.get("by_deadline") or []):
        due = _parse_date(d.get("date", ""))
        if due is None:
            continue
        horizon = HIGH_VOL_HORIZON if d.get("volatility") == "high" else DEFAULT_HORIZON
        delta = (due - today).days
        if delta <= horizon:
            out.append({**d, "days_remaining": delta})
    return out


def _parse_date(ds: str):
    ds = (ds or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(ds, fmt)
            if fmt == "%Y":
                return date(dt.year, 12, 31)
            if fmt == "%Y-%m":
                return date(dt.year, dt.month, 1)
            return dt.date()
        except ValueError:
            continue
    return None


# ── S059 smart-config: model-policy digest segment (design §6.1) ──────────────
# A ONE-LINE segment (V-3 budget discipline — no subprocess, small bounded reads):
#   "model-policy: INVALID — fail-open active"  when `validate` fails, AND/OR
#   a spawns-vs-graded-decisions ratio so grading atrophy (R-1) is visible per session.
# Denominator: the per-project spawn-runs.jsonl sidecar (S046, project-local). Numerator:
# the project's model-decisions.jsonl (lines = graded resolves). Best-effort; silent on
# any error. NO subprocess — we read the same policy files the resolver reads and do a
# minimal in-process validity check (presence + parseable + version==1).

def _slug(project_root: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_root))


def _policy_invalid() -> bool:
    """Cheap in-process validity check of the merged global+project policy (cwd).
    True only when a policy file EXISTS but is unparseable / wrong-version (a real
    misconfig worth surfacing). Missing files are valid (zero-config no-op)."""
    try:
        import yaml  # type: ignore
    except Exception:
        return False  # no yaml -> resolver fails open too; nothing to surface
    bad = False
    for p in (MODEL_POLICY,
              Path(os.getcwd()) / ".claude" / "model-policy.yaml"):
        try:
            if not p.is_file():
                continue
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                bad = True
        except Exception:
            bad = True
    return bad


def _spawn_vs_decisions() -> str | None:
    """Return 'graded N/M Claude spawns' for the cwd project, or None when there is nothing
    meaningful to show (no Claude dispatch recorded).

    #311 (design s3.5): numerator and denominator now come from the SAME rows. The old ratio
    divided model-decisions.jsonl lines by every spawn-runs.jsonl line -- two unrelated files,
    and a denominator that was almost all codex_watch rows ("graded 17/696"). Now: Claude
    DISPATCH rows (tool claude_dispatch, written by effort_policy.py) whose effort came from a
    WP grade, over all Claude dispatch rows. The counting rule is effort_rollup's, imported."""
    try:
        import effort_rollup  # beside this file; a failed import is silent like every segment
        rows, _ = effort_rollup.read_rows(Path(os.getcwd()) / effort_rollup.SPAWN_RUNS)
        graded, total = effort_rollup.claude_spawn_counts(rows)
        if total == 0:
            return None  # no denominator -> nothing to nudge about
        return f"graded {graded}/{total} Claude spawns"
    except Exception:
        return None


def _model_policy_segment() -> str | None:
    """One compact segment for the digest, or None when silent."""
    bits = []
    if _policy_invalid():
        bits.append("INVALID — fail-open active")
    ratio = _spawn_vs_decisions()
    if ratio:
        bits.append(ratio)
    if not bits:
        return None
    return "model-policy: " + "; ".join(bits)


# ── S081 seat-model segments (design §4.3.2, §4.3.4, §4.3.5, §4.4; plan WP-203, I14) ──
# The LIVE half of the codex/agy roster facts whose static half is registered in
# external-facts.md (a markdown anchor cannot read a JSON file). Eight segments, each
# silent when it has nothing to say, and each failing silent on its own:
#   (1) codex-roster       RIDER       listed count · cache date · client, or its stale/unknown form
#   (2) model-roster       STANDALONE  a TOP change recorded in seat-model-tops.json, one episode
#   (8) model-roster tie   STANDALONE  #282 R16: a codex priority tie recorded in the tops record
#                                      (tie_break / tied_with), ONE session per tie (TIE_MAX_NUDGES,
#                                      window disabled), independent of (2); see _tie_announcements
#   (3) roster stale       STANDALONE  codex/agy cache older than 7d or absent, for a tool in use
#   (4) codex-quota        RIDER       codex_quota.snapshot(); silent when unknown
#   (5) seat-model freeze  STANDALONE  every active pin, always-on while it exists (I13: agy
#                                      auto-follow stays off until a user removes the agy pin)
#   (6) model-policy       STANDALONE  tiers.complex.claude-code differs from the roster's Claude
#                                      MAIN tier (I14; #291: model_roster.CLAUDE_MAIN, the value
#                                      every protected Claude row serves), default dedup class — the two are
#                                      decoupled on purpose, so a deliberate difference must
#                                      not nag every session
#   (7) astra              STANDALONE  N >= 1 codex seats served by a Claude substitute in the
#                          / RIDER     last 7 days, account-wide, with the plan review date
#                                      (amendment 1 D5/D6, J18); RIDER when N == 0; see below
# A stale or absent source is reported as stale or unknown, NEVER as current. Staleness
# uses seat_model's own rule (ROSTER_STALE_AFTER_S, its ISO parser) so the digest and the
# resolver cannot disagree about whether a roster is stale. Every value copied from a
# state file is ASCII-escaped and length-capped before it reaches the session context.

_SEAT_MODULES: object = None      # (seat_model, codex_model, codex_quota) or the import error
STATE_FILE_MAX_BYTES = 1 << 20    # pins / tops / agy cache / model-policy: small files by contract
_CTX_SUFFIX = re.compile(r"\[[^\]]*\]$")   # "fable[1m]" names the same model as "fable"
_SEAT_PROVIDERS = ("codex", "agy")


def _seat_modules():
    """(seat_model, codex_model, codex_quota), imported once. Re-raises a cached failure."""
    global _SEAT_MODULES
    if _SEAT_MODULES is None:
        try:
            if str(_META) not in sys.path:
                sys.path.insert(0, str(_META))
            import seat_model  # noqa: E402 — imports codex_model and codex_quota itself
            _SEAT_MODULES = (seat_model, seat_model.codex_model, seat_model.codex_quota)
        except Exception as exc:  # noqa: BLE001 — surfaced as a digest segment, never raised
            _SEAT_MODULES = exc
    if isinstance(_SEAT_MODULES, BaseException):
        raise _SEAT_MODULES
    return _SEAT_MODULES


def _rot_staleness():
    if str(_META) not in sys.path:
        sys.path.insert(0, str(_META))
    import rot_staleness  # noqa: E402
    return rot_staleness


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — one broken segment must not silence the others
        return default


def _clip(value, limit: int = 64) -> str:
    """ASCII-only, no control characters, at most `limit` characters."""
    text = str(value).encode("ascii", "backslashreplace").decode("ascii")
    text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _read_state_text(path: Path) -> tuple[str, str | None]:
    """("absent", None) | ("invalid", None) | ("ok", text). Bounded; never raises."""
    try:
        if path.stat().st_size > STATE_FILE_MAX_BYTES:
            return "invalid", None
        return "ok", path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "absent", None
    except (OSError, ValueError):
        return "invalid", None


def _read_state_json(path: Path) -> tuple[str, object]:
    status, text = _read_state_text(path)
    if status != "ok":
        return status, None
    try:
        return "ok", json.loads(text)
    except ValueError:
        return "invalid", None


def _age_state(sm, iso, now: datetime) -> str:
    """'fresh' | 'stale' | 'unparseable', by seat_model's staleness rule, against `now`."""
    epoch = sm._parse_iso(iso)
    if epoch is None:
        return "unparseable"
    return "stale" if (now.timestamp() - epoch) > sm.ROSTER_STALE_AFTER_S else "fresh"


def _day(sm, iso) -> str:
    epoch = sm._parse_iso(iso)
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d") if epoch is not None else "?"


def _codex_roster_view(sm, cm, now: datetime) -> dict:
    """state in {fresh, stale, unparseable, absent, invalid} plus the facts to print."""
    try:
        doc = cm.load_roster_entries(CODEX_ROSTER)
    except Exception as exc:  # noqa: BLE001 — CodexModelError wraps the OSError
        missing = isinstance(exc.__cause__, FileNotFoundError)
        return {"state": "absent" if missing else "invalid", "entries": None}
    return {
        "state": _age_state(sm, doc.fetched_at, now),
        "fetched_at": doc.fetched_at,
        "client": doc.client_version,
        "listed": sum(1 for e in doc.entries.values() if e.visibility == "list"),
        "entries": doc.entries,
    }


def _agy_roster_view(sm, now: datetime) -> dict:
    status, doc = _read_state_json(AGY_ROSTER)
    if status == "absent":
        return {"state": "absent"}
    if status != "ok" or not isinstance(doc, dict) or doc.get("schema") != sm.AGY_ROSTER_SCHEMA \
            or not isinstance(doc.get("models"), list):
        return {"state": "invalid"}
    return {"state": _age_state(sm, doc.get("fetched_at"), now), "fetched_at": doc.get("fetched_at")}


def _tool_in_use(provider: str, inventory, pins_doc, tops_doc) -> bool:
    """A roster only matters on a host that uses the tool: installed per the inventory, or
    already carrying a freeze pin or a resolved TOP for it. Keeps hosts without codex/agy quiet."""
    tools = inventory.get("tools") if isinstance(inventory, dict) else None
    rec = tools.get(provider) if isinstance(tools, dict) else None
    if isinstance(rec, dict) and rec.get("installed") is True:
        return True
    for doc, key in ((pins_doc, "pins"), (tops_doc, "tops")):
        table = doc.get(key) if isinstance(doc, dict) else None
        if isinstance(table, dict) and provider in table:
            return True
    return False


def _codex_roster_segment(sm, view: dict, in_use: bool) -> str | None:
    state = view["state"]
    if state == "fresh":
        client = _clip(view["client"]) if view.get("client") else "?"
        return (f"codex-roster: {view['listed']} models, cache fetched "
                f"{_day(sm, view['fetched_at'])}, client {client}")
    if state == "stale":
        return (f"codex-roster: cache age unknown (fetched {_day(sm, view['fetched_at'])}, "
                f"older than {sm.ROSTER_STALE_AFTER_S // 86400}d)")
    if state == "unparseable":
        return "codex-roster: cache age unknown (fetched_at unreadable)"
    if not in_use:
        return None
    return ("codex-roster: unknown (no local cache)" if state == "absent"
            else "codex-roster: unknown (cache unreadable)")


def _roster_stale_segment(sm, codex: dict, agy: dict, in_use: dict) -> str | None:
    items = []
    if in_use["codex"] and codex["state"] != "fresh":
        items.append("codex")   # the codex-roster rider in the same line carries the detail
    if in_use["agy"] and agy["state"] != "fresh":
        detail = {
            "stale": f"fetched {_day(sm, agy.get('fetched_at'))}, older than {sm.ROSTER_STALE_AFTER_S // 86400}d",
            "unparseable": "fetched_at unreadable",
            "absent": "no cache",
            "invalid": "cache unreadable",
        }[agy["state"]]
        items.append(f"agy ({detail})")
    return "roster stale: " + ", ".join(items) if items else None


def _pin_top(pins_doc, provider: str):
    table = pins_doc.get("pins") if isinstance(pins_doc, dict) else None
    entry = table.get(provider) if isinstance(table, dict) else None
    top = entry.get("top") if isinstance(entry, dict) else None
    return top if isinstance(top, str) and top else None


#: #302 (design s3.2, challenger #4): appended to a codex TOP-change line whose new TOP is a roster
#: non-TOP tier. astra and gpt-6-sol are one generation, so a priority flap is no longer broken by
#: generation; the seat still follows the roster, and this makes the inversion visible.
TOP_INVERSION_NOTE = "(TOP resolved to a std/support model)"


def _installed_codex_tiers() -> frozenset:
    """The INSTALLED roster's codex tiers {CODEX_STD, CODEX_SUPPORT} (support defaults to std,
    JC-1), parsed never executed. Empty when the roster is unreadable. Never raises."""
    roster = _safe(lambda: _read_roster(INSTALLED_ROSTER), None)
    if not isinstance(roster, dict):
        return frozenset()
    std = roster.get("CODEX_STD")
    support = roster.get("CODEX_SUPPORT", std)
    return frozenset(v for v in (std, support) if isinstance(v, str) and v)


def _top_announcements(sm, tops_doc, pins_doc, ack: dict, now: datetime,
                       codex_tiers: frozenset | None = None) -> list[str]:
    """One episode per TOP change: at most MAX_NUDGES sessions, never re-armed by the window.

    #302: a codex line gains TOP_INVERSION_NOTE when the record carries top_resolved_to_std, or
    when the new TOP is one of `codex_tiers` (default: the installed roster's CODEX_STD and
    CODEX_SUPPORT). seat_model records the flag in a seat's provenance, not in the tops record,
    so the digest derives the same fact from the roster the installed resolver reads."""
    out: list[str] = []
    if not isinstance(tops_doc, dict) or tops_doc.get("schema") != sm.TOPS_SCHEMA \
            or not isinstance(tops_doc.get("tops"), dict):
        return out
    for provider in _SEAT_PROVIDERS:
        rec = tops_doc["tops"].get(provider)
        if not isinstance(rec, dict):
            continue
        top, previous, changed_at = rec.get("top"), rec.get("previous"), rec.get("changed_at")
        if not all(isinstance(v, str) and v for v in (top, previous, changed_at)) or top == previous:
            continue
        fp = _fingerprint("seat-model-top", provider, previous, f"{top}@{changed_at}")
        if _suppressed(ack, fp, now, window_days=None):
            continue
        _record_nudge(ack, fp, now, window_days=None)
        pin = _pin_top(pins_doc, provider)
        if provider == "codex":
            frozen = pin == top
            tail = "timeout from tier floor; trial cohort closed"
        else:  # agy records the version family; the pin carries a level
            frozen = sm.is_agy_family(pin) and f"gemini-{sm._agy_version(pin)}-{sm.AGY_FAMILY}" == top
            tail = "level and timeout from role row"
        how = "freeze pin" if frozen else "auto-followed"
        line = f"model-roster: {provider} top {_clip(previous)} → {_clip(top)} ({how}; {tail})"
        if provider == "codex":
            flag = getattr(sm, "TOP_RESOLVED_TO_STD", "top_resolved_to_std")
            if codex_tiers is None:
                codex_tiers = _installed_codex_tiers()
            if rec.get(flag) is True or top in codex_tiers:
                line += " " + TOP_INVERSION_NOTE
        out.append(line)
    return out


TIE_BREAKS = ("generation", "incumbent", "slug")   # == codex_model.TIE_BREAKS (test-guarded)
TIE_SLUGS_SHOWN = 8


def _tie_announcements(sm, tops_doc, ack: dict, now: datetime) -> list[str]:
    """#282 R16 (plan K29): one line per provider record carrying a priority tie, in ONE session.

    seat_model writes `tie_break` and `tied_with` into a tops record only when that TOP came from a
    tied selection, and drops them otherwise, so a record without them says nothing.

    #282 fix round 1 (plan K45) and fix round 2 (G5, plan K57). The IDENTITY and the DISPLAYED set
    are deliberately different. Identity is (provider, priority_winner, sorted((tied_with | {top})
    - {winner})): the RULE is DISPLAYED but is not part of it (F11 — the first resolution of a tie
    records its winner, which gives the NEXT one an incumbent, so the rule flipped slug -> incumbent
    on an otherwise unchanged tie and the same tie was announced twice), and neither is the served
    model — re-adding `top` and dropping `winner` reverses F14's removal FOR THE IDENTITY ONLY, so
    one tie has one identity whether or not an upgrade was followed (G5: codex_model builds
    `tied_with` by dropping the winner AND the served model, so the two shapes differed by exactly
    the served slug and announced twice). A different winner or tied set is a new tie and is
    announced again; the same tie is never re-armed (window disabled). RESIDUAL, accepted and
    test-pinned: when a followed upgrade puts a slug from OUTSIDE the tie into `top`, that slug is
    in the identity and the no-upgrade shape of the same tie is announced once more.

    The winner named is the record's `priority_winner` when it carries one — written exactly when
    an upgrade was followed, so the served `top` is NOT the slug the priority rules chose — else
    `top`. `tied_with` excludes the served model (F14), so it may be an EMPTY list while a tie
    happened: `tie_break` is what says one did, and the ` = <others>` clause is then omitted rather
    than printing the served model as its own tie partner (`sol = sol -> sol`). Independent of the
    TOP-change announcement, which keeps its own fingerprint and cap. Reads only the tops document
    already read.
    """
    out: list[str] = []
    if not isinstance(tops_doc, dict) or tops_doc.get("schema") != sm.TOPS_SCHEMA \
            or not isinstance(tops_doc.get("tops"), dict):
        return out
    for provider in _SEAT_PROVIDERS:
        rec = tops_doc["tops"].get(provider)
        if not isinstance(rec, dict):
            continue
        top, rule, tied = rec.get("top"), rec.get("tie_break"), rec.get("tied_with")
        if not isinstance(top, str) or not top or rule not in TIE_BREAKS or not isinstance(tied, list) \
                or not all(isinstance(slug, str) and slug for slug in tied):
            continue
        # #282 fix round 2 (G7b, K59b): read the key through getattr so an OLD seat_model beside
        # a NEW nudge — what a partial dual-location copy leaves — cannot raise in the hook.
        winner = rec.get(getattr(sm, "PRIORITY_WINNER", "priority_winner"), top)
        if not isinstance(winner, str) or not winner:
            continue
        others = sorted(set(tied))                     # DISPLAYED (F14): never the served model
        identity = sorted((set(tied) | {top}) - {winner})   # #282 fix round 2 (G5, K57)
        fp = _fingerprint("seat-model-tie", provider, winner, json.dumps(identity, ensure_ascii=True))
        if _suppressed(ack, fp, now, window_days=None, cap=TIE_MAX_NUDGES):
            continue
        _record_nudge(ack, fp, now, window_days=None)
        shown = [_clip(slug) for slug in others[:TIE_SLUGS_SHOWN]]
        if len(others) > TIE_SLUGS_SHOWN:
            shown.append(f"{len(others) - TIE_SLUGS_SHOWN} more")
        tied_clause = f" = {' = '.join(shown)}" if shown else ""
        upgrade_clause = f", upgrade -> {_clip(top)}" if top != winner else ""
        out.append(f"model-roster: {provider} priority tie {_clip(winner)}{tied_clause} "
                   f"-> {_clip(winner)} (by {rule}){upgrade_clause}")
    return out


def _freeze_segment(sm, pins_status: str, pins_doc, codex: dict) -> str | None:
    if pins_status == "absent":
        return None
    if pins_status != "ok" or not isinstance(pins_doc, dict) or pins_doc.get("schema") != sm.PINS_SCHEMA \
            or not isinstance(pins_doc.get("pins"), dict):
        return "seat-model freeze: INVALID pins file — TOP seats take their failure path"
    items = []
    for provider in _SEAT_PROVIDERS:
        if provider not in pins_doc["pins"]:
            continue
        top = _pin_top(pins_doc, provider)
        if top is None:
            items.append(f"{provider}=INVALID (no usable top)")
        elif provider == "agy" and not sm.is_agy_family(top):
            items.append(f"agy={_clip(top)} (INVALID: not agy family {sm.AGY_FAMILY})")
        elif provider == "codex" and codex.get("entries") is not None and top not in codex["entries"]:
            items.append(f"codex={_clip(top)} (INVALID: not in roster)")
        else:
            items.append(f"{provider}={_clip(top)}")
    return "seat-model freeze: " + ", ".join(items) if items else None


def _quota_segment(cq, now: datetime) -> str | None:
    """S081 revision 4 (WP-A4), discharging the #282 D5 deferral: an UNCERTAIN reading is
    VISIBLE, with the reason it is uncertain, instead of going silent.

    `uncertain` means a reading exists but a newer one may exist unread (#282 R6), so the
    percentages are real and are shown — #282 r9 reads them as a lower bound. Going silent
    made that case indistinguishable from `unknown`, which means no data at all and stays
    silent: that is the existing and correct behaviour, and it is unchanged.

    The reason token is READ FROM THE SNAPSHOT rather than assumed. FINDING (WP-A4): the plan
    sources it as `STATE_UNCERTAIN / REASON_OBSERVED_TOO_LONG_AGO`, but those two never pair
    in codex_quota — `observed_too_long_ago` accompanies STATE_STALE, while uncertain's own
    reasons are `newer_candidate_unread` and `stat_budget_exhausted`. Reading the snapshot is
    correct whichever reason arrives, and survives a new one being added."""
    snap = cq.snapshot(sessions_dir=CODEX_SESSIONS, now=now)
    state = snap.get("state")
    if state not in (cq.STATE_FRESH, cq.STATE_STALE, cq.STATE_UNCERTAIN):
        return None   # unknown -> silent

    def pct(value) -> str:
        return f"{value:g}%" if isinstance(value, (int, float)) and not isinstance(value, bool) else "?"

    note = state
    if state == cq.STATE_UNCERTAIN:
        reason = snap.get("reason")
        # A missing reason must not silence the line again: the STATE is the finding.
        if isinstance(reason, str) and reason.strip():
            note = f"{state}: {_clip(reason, 48)}"

    return (f"codex-quota: 5h {pct(snap.get('primary_used_percent'))} · weekly "
            f"{pct(snap.get('secondary_used_percent'))} ({note})")


def _claude_main(sm) -> str:
    """#291 design s3.7: the Claude MAIN tier (model_roster.CLAUDE_MAIN) as seat_model sees it.

    Read through the model_roster module seat_model imported, so the digest and the resolver
    can never disagree. An OLD seat_model beside a NEW nudge (a partial dual-location copy has
    no model_roster attribute) falls back to the code_reviewer Claude row, which is the value
    CLAUDE_MAIN feeds on a current copy."""
    roster = getattr(sm, "model_roster", None)
    main = getattr(roster, "CLAUDE_MAIN", None)
    if isinstance(main, str) and main:
        return main
    return sm.ROLE_TABLE[sm.CODE_REVIEWER][sm.CLAUDE].value


def _complex_tier_divergence(sm, ack: dict, now: datetime) -> str | None:
    """I14, #291 s3.7. Home policy only (never the cwd project file); silent when the policy is
    absent, invalid (the INVALID segment owns that), or has no complex claude-code value. The
    policy value is compared with the roster's Claude MAIN tier (model_roster.CLAUDE_MAIN), the
    tier every protected Claude seat serves."""
    try:
        import yaml  # type: ignore
    except Exception:
        return None
    status, text = _read_state_text(MODEL_POLICY)
    if status != "ok":
        return None
    try:
        data = yaml.safe_load(text)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    tiers = data.get("tiers")
    complex_tier = tiers.get("complex") if isinstance(tiers, dict) else None
    value = complex_tier.get("claude-code") if isinstance(complex_tier, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    policy_model = _CTX_SUFFIX.sub("", value.strip())
    main_model = _claude_main(sm)
    if policy_model == main_model:
        return None
    fp = _fingerprint("model-policy", "tiers.complex.claude-code", main_model, policy_model)
    if _suppressed(ack, fp, now):
        return None
    _record_nudge(ack, fp, now)
    return (f"model-policy: tiers.complex.claude-code={_clip(value)} differs from "
            f"roster Claude main={_clip(main_model)}")


# ── (9)-(11) model roster (#291 design s3.7; plan WP-5) ──
# Three STANDALONE segments, each one episode per change under the TOP-announcement rules
# (same fingerprint store, window disabled, at most MAX_NUDGES sessions, never re-armed; a
# new change is a new fingerprint), and each silenced for good by `--ack`:
#   (9)  roster swap   the INSTALLED model_roster.py carries a REVISION reached by a swap (a
#                      HISTORY row before it) -> "Model roster rev N: Claude main X→Y,
#                      support A→B[, codex std C→D][, codex support E→F], benched {…} — reason"
#                      (a codex segment only when that tier moved; #302). A roster that was never
#                      swapped (one HISTORY row) says nothing; the identity is the revision number.
#   (10) roster drift  ONLY when the session cwd is inside a foundry-lab checkout: the repo's
#                      model_roster.REVISION differs from the installed one -> "roster drift:
#                      repo rev N, home rev M — run install.py" (M is `absent` before the first
#                      install that ships the roster).
#   (11) alias re-point the concrete served id recorded for a Claude alias in the session
#                      project's EXISTING spawn telemetry (spawn-runs.jsonl served_model)
#                      changed -> "alias opus now serves <id> (was <id>)". A benched family
#                      is never spawned, so a new release of it cannot be seen this way:
#                      re-instating one stays a human trigger (the runbook says so).
# READ-ONLY and CALL-FREE: the roster files are parsed with `ast` and never executed (the
# repo copy lives under the session cwd, which the hook does not trust), the telemetry is a
# bounded tail read, and no model, subprocess or network call is made. A missing or
# malformed input silences its own segment and nothing else.
INSTALLED_ROSTER = HOME / ".claude" / "skills" / "_meta" / "model_roster.py"
ROSTER_RELPATH = ("skills", "_meta", "model_roster.py")
FOUNDRY_MARKERS = ("install.py", "skills/_meta/seat_model.py")   # beside ROSTER_RELPATH
FOUNDRY_MAX_PARENTS = 40
SESSION_CWD: Path | None = None   # None -> os.getcwd(); the tests point it at a fixture dir
SPAWN_RUNS_RELPATH = (".process-observations", "spawn-runs.jsonl")
ALIAS_TAIL_BYTES = 256 << 10
CLAUDE_ALIAS_FAMILIES = ("fable", "haiku", "opus", "sonnet")   # == seat_model.CLAUDE_ALIASES (test-guarded)
MODEL_UNKNOWN = "unknown"   # == audit_spawn.MODEL_UNKNOWN: a served id nobody observed
# #302 (challenger #6): an ALLOWLIST - a name not in it is silently skipped, so a new roster
# tier must be added here or the digest never sees it.
_ROSTER_NAMES = frozenset({"REVISION", "CLAUDE_MAIN", "CLAUDE_SUPPORT", "CLAUDE_BENCHED",
                           "CODEX_STD", "CODEX_SUPPORT", "HISTORY"})
_ROSTER_SETS = frozenset({"frozenset", "set", "tuple"})


def _session_cwd() -> Path:
    return Path(SESSION_CWD) if SESSION_CWD is not None else Path(os.getcwd())


def _roster_literal(node):
    """ast.literal_eval, plus `frozenset({...})` / `set(...)` / `tuple(...)` of a literal."""
    import ast
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _ROSTER_SETS and not node.keywords and len(node.args) <= 1:
        return frozenset(ast.literal_eval(node.args[0])) if node.args else frozenset()
    return ast.literal_eval(node)


def _read_roster(path: Path) -> dict | None:
    """The roster's literals, parsed WITHOUT executing the file, or None when the file is
    absent, oversized, unparseable or carries no integer REVISION. Never raises."""
    import ast
    status, text = _read_state_text(path)
    if status != "ok":
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    out: dict = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if not isinstance(target, ast.Name) or target.id not in _ROSTER_NAMES:
            continue
        try:
            out[target.id] = _roster_literal(value)
        except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
            continue
    rev = out.get("REVISION")
    if not isinstance(rev, int) or isinstance(rev, bool):
        return None
    return out


def _roster_swap_finding(roster: dict | None):
    """(fingerprint, text) for the installed roster's latest swap, or None."""
    if roster is None:
        return None
    rev, history = roster["REVISION"], roster.get("HISTORY")
    if not isinstance(history, (tuple, list)):
        return None
    rows = [row for row in history if isinstance(row, dict)
            and isinstance(row.get("rev"), int) and not isinstance(row.get("rev"), bool)]
    current = next((row for row in reversed(rows) if row["rev"] == rev), None)
    previous = [row for row in rows if row["rev"] < rev]
    if current is None or not previous:
        return None   # never swapped (or no row for the live revision): nothing to announce
    prev = previous[-1]

    def live(name, key):
        value = roster.get(name)
        return value if isinstance(value, str) and value else current.get(key)

    main, support, std = (live("CLAUDE_MAIN", "claude_main"), live("CLAUDE_SUPPORT", "claude_support"),
                          live("CODEX_STD", "codex_std"))
    benched = roster.get("CLAUDE_BENCHED", current.get("benched", ()))
    benched = sorted(str(b) for b in benched) if isinstance(benched, (set, frozenset, tuple, list)) else []
    text = (f"Model roster rev {rev}: Claude main {_clip(prev.get('claude_main'), 32)}→{_clip(main, 32)}, "
            f"support {_clip(prev.get('claude_support'), 32)}→{_clip(support, 32)}")
    if prev.get("codex_std") != std and prev.get("codex_std") is not None:
        text += f", codex std {_clip(prev['codex_std'], 32)}→{_clip(std, 32)}"
    # #302: the codex SUPPORT tier, named only when this roster HAS one (a live CODEX_SUPPORT or a
    # codex_support on the current row). A row without codex_support served support on its
    # codex_std (JC-1), so the rev 2 -> 3 swap reads "codex support gpt-5.6-sol→gpt-5.6-terra".
    # D21 fix round 1 (m2): when only the PREVIOUS row names a support tier (a rev-2-shaped revert
    # row, no live CODEX_SUPPORT), the effective support is the live codex std, so a real support
    # move (terra -> sol) is still announced. Neither side naming one: no segment (std covers it).
    explicit = live("CODEX_SUPPORT", "codex_support")
    support_tier = explicit if explicit is not None else (std if prev.get("codex_support") else None)
    if support_tier is not None:
        was = prev.get("codex_support") or prev.get("codex_std")
        if was is not None and was != support_tier:
            text += f", codex support {_clip(was, 32)}→{_clip(support_tier, 32)}"
    text += ", benched {" + ", ".join(_clip(b, 32) for b in benched[:8]) + "}"
    # #367: the agy family (a row before rev 6 served flash) and the agy size -> level map (rev 7),
    # named only when this swap moved them.
    family, was_family = current.get("agy_family"), prev.get("agy_family", "flash")
    if isinstance(family, str) and family != was_family:
        text += f", agy family {_clip(was_family, 20)}→{_clip(family, 20)}"
    levels = current.get("agy_level_by_size")
    if isinstance(levels, dict) and levels != prev.get("agy_level_by_size"):
        text += ", agy level by size " + ", ".join(
            f"{_clip(size, 10)}→{_clip(level, 10)}" for size, level in list(levels.items())[:3])
    reason = current.get("reason")
    if isinstance(reason, str) and reason.strip():
        text += f" — {_clip(reason.strip(), 96)}"
    return _fingerprint("model-roster-rev", "claude", prev["rev"], rev), text


def _foundry_checkout(start: Path) -> Path | None:
    """The nearest ancestor of `start` (itself included) that is a foundry-lab checkout: it
    holds skills/_meta/model_roster.py beside install.py and skills/_meta/seat_model.py.
    Bounded; never raises."""
    try:
        here = start.resolve()
    except (OSError, RuntimeError):
        return None
    for count, candidate in enumerate((here, *here.parents)):
        if count >= FOUNDRY_MAX_PARENTS:
            break
        try:
            if candidate.joinpath(*ROSTER_RELPATH).is_file() \
                    and all((candidate / marker).is_file() for marker in FOUNDRY_MARKERS):
                return candidate
        except OSError:
            continue
    return None


def _roster_drift_finding(installed: dict | None):
    """(fingerprint, text) when the session sits in a foundry-lab checkout whose roster
    REVISION differs from the installed one, else None."""
    root = _foundry_checkout(_session_cwd())
    if root is None:
        return None
    # (A session running from the installed tree reads the same file twice: equal revisions.)
    repo = _read_roster(root.joinpath(*ROSTER_RELPATH))
    if repo is None:
        return None   # an unreadable repo roster is `seat_model.py check`'s finding, not drift
    repo_rev = repo["REVISION"]
    home_rev = installed["REVISION"] if installed is not None else "absent"
    if repo_rev == home_rev:
        return None
    return (_fingerprint("model-roster-drift", "home", repo_rev, home_rev),
            f"roster drift: repo rev {repo_rev}, home rev {home_rev} — run install.py")


def _tail_bytes(path: Path, limit: int) -> bytes:
    """The whole lines inside the last `limit` bytes of a REGULAR file. Raises OSError.
    Stat before open, so a FIFO named like the file never blocks the hook."""
    if not stat.S_ISREG(path.stat().st_mode):
        raise OSError(f"not a regular file: {path.name}")
    with open(path, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"not a regular file: {path.name}")
        start = max(0, st.st_size - limit)
        fh.seek(max(0, start - 1))
        data = fh.read(st.st_size - max(0, start - 1))
    if start == 0:
        return data
    if data[:1] == b"\n":
        return data[1:]
    cut = data.find(b"\n")
    return data[cut + 1:] if cut >= 0 else b""


def _alias_of(value) -> str | None:
    if not isinstance(value, str):
        return None
    alias = _CTX_SUFFIX.sub("", value.strip()).strip().lower()
    return alias if alias in CLAUDE_ALIAS_FAMILIES else None


def _serves_alias(served, alias: str) -> str | None:
    """The concrete served id when it names `alias` as a dash-delimited token (the rule
    audit_spawn uses for served_model_mismatch), else None — a mismatch is not a re-point."""
    if not isinstance(served, str):
        return None
    served = _CTX_SUFFIX.sub("", served.strip()).strip()
    tokens = served.lower().split("-")
    if not served or served.lower() in (MODEL_UNKNOWN, alias) or alias not in tokens:
        return None
    return served


def _alias_repoint_findings() -> list:
    """[(fingerprint, text)] — one per Claude alias whose latest served id differs from the
    one served before it, within the bounded tail of the session project's spawn-runs.jsonl."""
    path = _session_cwd().joinpath(*SPAWN_RUNS_RELPATH)
    try:
        data = _tail_bytes(path, ALIAS_TAIL_BYTES)
    except OSError:
        return []
    served_by: dict[str, list[str]] = {}
    for line in data.split(b"\n"):
        if b'"served_model"' not in line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(row, dict):
            continue
        requested = row.get("requested_model")
        alias = _alias_of(requested if isinstance(requested, str) else row.get("model"))
        served = _serves_alias(row.get("served_model"), alias) if alias else None
        if served:
            served_by.setdefault(alias, []).append(served)
    out = []
    for alias in sorted(served_by):
        seq = served_by[alias]
        now_id = seq[-1]
        was = next((sid for sid in reversed(seq) if sid != now_id), None)
        if was is None:
            continue
        out.append((_fingerprint("claude-alias", alias, was, now_id),
                    f"alias {alias} now serves {_clip(now_id)} (was {_clip(was)})"))
    return out


def _roster_findings() -> list:
    """Every current (fingerprint, text) of segments (9)-(11), unfiltered. Never raises."""
    installed = _safe(lambda: _read_roster(INSTALLED_ROSTER), None)
    found = []
    for finding in (_safe(lambda: _roster_swap_finding(installed), None),
                    _safe(lambda: _roster_drift_finding(installed), None)):
        if finding:
            found.append(finding)
    found.extend(_safe(_alias_repoint_findings, []))
    return found


def _roster_segments(ack: dict, now: datetime) -> list[str]:
    """Segments (9)-(11) under the TOP-announcement episode rules. Never raises."""
    out = []
    for fp, text in _roster_findings():
        if _suppressed(ack, fp, now, window_days=None):
            continue
        _record_nudge(ack, fp, now, window_days=None)
        out.append(text)
    return out


def _ack_roster_findings(ack: dict, now: datetime) -> int:
    """`--ack`: spend every current roster episode, so an acked change is never shown again.
    A NEW change has a new fingerprint and is announced as usual."""
    nowiso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fps = ack.setdefault("fingerprints", {})
    spent = 0
    for fp, _text in _roster_findings():
        rec = fps.get(fp) or {"first_ts": nowiso}
        rec.update({"count": max(MAX_NUDGES, rec.get("count", 0)), "last_ts": nowiso, "acked_ts": nowiso})
        fps[fp] = rec
        spent += 1
    return spent


# ── (7) astra substitutions (S081 amendment 1 D5/D6; plan WP-F06, J18) ──
# `astra: <N> substitutions this week (<reason> <n>, …) · plan review 2026-09-28` — the
# evidence the 2026-09-28 ChatGPT Plus review (D5) is decided on, surfaced every session.
# ACCOUNT-WIDE because the codex quota is account-wide: every project's
# ~/.claude/projects/<slug>/astra-budget.jsonl counts, not just the cwd's. A row counts when
# `substitute_for == "codex"` (codex_quota.record_substitution's rows; admit rows also carry
# a `reason` but never `substitute_for`) and its `at` lies in the last ASTRA_WINDOW_S
# (a row up to ASTRA_FUTURE_SKEW_S in the future is tolerated; a planted far-future row is
# not). Bounded: at most ASTRA_MAX_PROJECT_DIRS directory entries are examined, the
# ASTRA_MAX_STORES newest regular store files are read, and only the last ASTRA_TAIL_BYTES of
# each (rows are appended in time order, so the tail holds the newest). Honest limit: a store
# whose last week of rows, admit rows included, outgrows the tail (roughly 700 substitution
# rows), a 65th store, or a store beyond the directory-entry bound is undercounted; the partial
# note covers the store bound and an unreadable store only. No lock is taken (a
# half-appended last line is simply skipped) and nothing is written. A malformed row is
# skipped; a reason is ASCII-escaped and capped before it reaches the session context.
ASTRA_PLAN_REVIEW = "2026-09-28"    # == external-facts.md `chatgpt-plus-codex-quota` review_by (test-guarded)
ASTRA_STORE_NAME = "astra-budget.jsonl"   # codex_quota.BUDGET_FILENAME
ASTRA_WINDOW_S = 7 * 86400
ASTRA_FUTURE_SKEW_S = 120                 # codex_quota.FUTURE_SKEW_S
ASTRA_MAX_STORES = 64
ASTRA_TAIL_BYTES = 256 << 10
ASTRA_MAX_PROJECT_DIRS = 4096
ASTRA_REASON_CHARS = 32
ASTRA_REASONS_SHOWN = 10
# S081 revision 4 (WP-A4): design §2.2 lands the use vocabulary everywhere at once —
# `USES`, `USE_FALLBACK_ROLE`, `SUBSTITUTION_USES`, `seat_model substitute --use`, and these
# DIGEST LABELS. A substitution's `use` says WHICH KIND of call lost astra (a light review, a
# brainstorm, a cross-cli ballot, an avengers seat); until now the digest read the row's
# `reason` and dropped its `use`, so the four uses WP-A3 added were invisible here.
# The vocabulary is NOT enumerated: uses are read from the rows, so a use added to
# codex_quota later is named automatically and can never fall into `other uses` because a
# list here went stale. `other uses` is an OVERFLOW bucket only, exactly like the reason one.
ASTRA_USE_CHARS = 32
ASTRA_USES_SHOWN = 10
ASTRA_USE_UNRECORDED = "unrecorded"       # a row whose `use` is missing or malformed
_ASTRA_ROW_MARKER = b'"substitute_for"'   # cheap pre-filter: admit rows never carry the key


def _astra_stores() -> tuple[list[Path], int]:
    """(the ASTRA_MAX_STORES newest regular store files, how many regular stores exist).
    A FIFO or directory named like a store is not a store (reading a FIFO would block)."""
    found: list[tuple[float, str, Path]] = []
    try:
        entries = os.scandir(CLAUDE_PROJECTS)
    except OSError:
        return [], 0
    with entries:
        for count, entry in enumerate(entries):
            if count >= ASTRA_MAX_PROJECT_DIRS:
                break
            path = Path(entry.path) / ASTRA_STORE_NAME
            try:
                st = path.stat()
            except OSError:          # no store here (or the entry is not a directory)
                continue
            if stat.S_ISREG(st.st_mode):
                found.append((-st.st_mtime, entry.name, path))
    found.sort()
    return [path for _, _, path in found[:ASTRA_MAX_STORES]], len(found)


def _astra_read_tail(path: Path) -> bytes:
    """The whole lines inside the last ASTRA_TAIL_BYTES of `path`. Raises OSError.

    Called only for paths _astra_stores() saw as regular files, so the open cannot block on
    a FIFO; swapping one in between the stat and the open needs write access to
    ~/.claude/projects, and the fstat below still refuses what it finds."""
    with open(path, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"not a regular file: {path.name}")
        start = max(0, st.st_size - ASTRA_TAIL_BYTES)
        # Read one byte before the tail too: it tells whether the tail starts on a line boundary.
        fh.seek(max(0, start - 1))
        data = fh.read(st.st_size - max(0, start - 1))
    if start == 0:
        return data
    if data[:1] == b"\n":
        return data[1:]
    cut = data.find(b"\n")
    return data[cut + 1:] if cut >= 0 else b""


def _astra_row_epoch(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def _astra_counts(now: datetime) -> dict | None:
    """None when no store exists anywhere, else {n, reasons, uses, read, found}. Never writes.

    `n` and `reasons` are unchanged: the count is still driven by the reason, so the
    account-wide 7-day total cannot move. `uses` is counted over the SAME rows, which is why
    a row whose `use` is missing or malformed is counted as ASTRA_USE_UNRECORDED instead of
    being skipped — skipping it would make the uses silently sum to less than `n`."""
    stores, found = _astra_stores()
    if not found:
        return None
    low = now.timestamp() - ASTRA_WINDOW_S
    high = now.timestamp() + ASTRA_FUTURE_SKEW_S
    reasons: dict[str, int] = {}
    uses: dict[str, int] = {}
    read = 0
    for path in stores:
        try:
            data = _astra_read_tail(path)
        except OSError:
            continue
        read += 1
        for line in data.split(b"\n"):
            if _ASTRA_ROW_MARKER not in line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):   # UnicodeDecodeError is a ValueError
                continue
            if not isinstance(row, dict) or row.get("substitute_for") != "codex":
                continue
            at = _astra_row_epoch(row.get("at"))
            reason = row.get("reason")
            if at is None or not low <= at <= high or not isinstance(reason, str) or not reason.strip():
                continue
            reasons[reason] = reasons.get(reason, 0) + 1
            use = row.get("use")
            if not isinstance(use, str) or not use.strip():
                use = ASTRA_USE_UNRECORDED
            uses[use] = uses.get(use, 0) + 1
    return {"n": sum(reasons.values()), "reasons": reasons, "uses": uses,
            "read": read, "found": found}


def _astra_segment(ack: dict, now: datetime) -> tuple[str, str] | None:
    """("standalone" | "rider", text), or None when no store exists anywhere."""
    counts = _astra_counts(now)
    if counts is None:
        return None
    n = counts["n"]
    ordered = sorted(counts["reasons"].items(), key=lambda item: (-item[1], item[0]))
    shown = [f"{_clip(reason, ASTRA_REASON_CHARS)} {count}" for reason, count in ordered[:ASTRA_REASONS_SHOWN]]
    rest = sum(count for _, count in ordered[ASTRA_REASONS_SHOWN:])
    if rest:
        shown.append(f"other reasons {rest}")
    by_use = sorted(counts["uses"].items(), key=lambda item: (-item[1], item[0]))
    used = [f"{_clip(use, ASTRA_USE_CHARS)} {count}" for use, count in by_use[:ASTRA_USES_SHOWN]]
    use_rest = sum(count for _, count in by_use[ASTRA_USES_SHOWN:])
    if use_rest:
        used.append(f"other uses {use_rest}")
    text = f"astra: {n} substitution{'' if n == 1 else 's'} this week"
    if shown:
        text += " (" + ", ".join(shown) + ")"
    if used:
        text += " [uses: " + ", ".join(used) + "]"
    if counts["read"] < counts["found"]:
        text += f" [partial: {counts['read']} of {counts['found']} stores read]"
    text += f" · plan review {ASTRA_PLAN_REVIEW}"
    if n == 0:
        return "rider", text
    # Default dedup class. N, every per-reason count AND every per-use count are in the
    # fingerprint, so a new substitution re-arms it; a capped count is demoted to a rider,
    # never hidden outright. The uses belong in it because a changed use mix under an
    # UNCHANGED reason mix changes the line, and a changed line must not stay suppressed.
    # (_fingerprint takes exactly four fields, so the two breakdowns travel as one value.)
    fingerprint = _fingerprint("astra-substitutions", "7d", n,
                               json.dumps([ordered, by_use], ensure_ascii=True))
    if _suppressed(ack, fingerprint, now):
        return "rider", text
    _record_nudge(ack, fingerprint, now)
    return "standalone", text


def _seat_model_segments(ack: dict, now: datetime) -> tuple[list[str], list[str]]:
    """(standalone, riders). Never raises. Reads only; ack is the in-memory dedup state."""
    standalone: list[str] = []
    riders: list[str] = []
    # (7) needs no seat module, so an import failure below cannot silence it.
    astra = _safe(lambda: _astra_segment(ack, now), None)
    try:
        standalone_part, rider_part = _seat_module_segments(ack, now)
        standalone.extend(standalone_part)
        riders.extend(rider_part)
    except Exception:  # noqa: BLE001 — never break the digest the older segments build
        pass
    # (9)-(11) need no seat module either (#291 s3.7): the roster is parsed, never imported.
    standalone.extend(_safe(lambda: _roster_segments(ack, now), []))
    if astra is not None:
        (standalone if astra[0] == "standalone" else riders).append(astra[1])
    return standalone, riders


def _seat_module_segments(ack: dict, now: datetime) -> tuple[list[str], list[str]]:
    """Segments (1)-(6): the ones that need seat_model / codex_model / codex_quota."""
    standalone: list[str] = []
    riders: list[str] = []
    try:
        sm, cm, cq = _seat_modules()
    except Exception as exc:  # noqa: BLE001
        if (_META / "seat_model.py").is_file():
            standalone.append(f"seat-model: import failed ({type(exc).__name__})")
        return standalone, riders
    try:
        inventory = _read_json(INVENTORY)
        pins_status, pins_doc = _read_state_json(SEAT_PINS)
        _tops_status, tops_doc = _read_state_json(SEAT_TOPS)
        codex = _safe(lambda: _codex_roster_view(sm, cm, now), {"state": "invalid", "entries": None})
        agy = _safe(lambda: _agy_roster_view(sm, now), {"state": "invalid"})
        in_use = {p: _tool_in_use(p, inventory, pins_doc, tops_doc) for p in _SEAT_PROVIDERS}

        standalone.extend(_safe(lambda: _top_announcements(sm, tops_doc, pins_doc, ack, now), []))
        standalone.extend(_safe(lambda: _tie_announcements(sm, tops_doc, ack, now), []))
        for segment in (
            _safe(lambda: _freeze_segment(sm, pins_status, pins_doc, codex), None),
            _safe(lambda: _roster_stale_segment(sm, codex, agy, in_use), None),
            _safe(lambda: _complex_tier_divergence(sm, ack, now), None),
        ):
            if segment:
                standalone.append(segment)
        for segment in (
            _safe(lambda: _codex_roster_segment(sm, codex, in_use["codex"]), None),
            _safe(lambda: _quota_segment(cq, now), None),
        ):
            if segment:
                riders.append(segment)
    except Exception:  # noqa: BLE001 — never break the digest the older segments build
        pass
    return standalone, riders


# ── digest assembly (the policy table) ───────────────────────────────────────

def build_digest(today: date, now: datetime) -> tuple[str | None, dict]:
    """Return (digest_line_or_None, updated_ack). Pure read of feeds + ack."""
    ack = load_ack()
    watermark = ack.get("watermark_ts")
    parts: list[str] = []
    nudged_any = False

    # --- version/presence changes from inventory-history (ack-gated) ---
    history = _tail_history(watermark)
    # Aggregate version bumps that the policy says to surface.
    surfaced_versions = []
    presence_changes = []
    command_delta_ids = set()  # would be populated by drift feed (v1: best-effort empty)
    for rec in history:
        sev = rec.get("severity")
        surface = rec.get("surface")
        _id = rec.get("id")
        field = rec.get("field")
        after = rec.get("after")
        fp = _fingerprint(surface, _id, field, after)
        if field == "presence" and sev in ("added", "removed"):
            if not _suppressed(ack, fp, now):
                presence_changes.append(rec)
                _record_nudge(ack, fp, now)
                nudged_any = True
        elif field == "version" and sev in ("minor", "major"):
            if not _suppressed(ack, fp, now):
                surfaced_versions.append(rec)
                _record_nudge(ack, fp, now)
                nudged_any = True
        elif field == "version" and sev == "patch":
            # patch bump -> NO, UNLESS a command-set delta is already on file.
            if _id in command_delta_ids and not _suppressed(ack, fp, now):
                surfaced_versions.append(rec)
                _record_nudge(ack, fp, now)
                nudged_any = True
            # else: silent (counted in the feed; visible at next sweep)

    for rec in surfaced_versions:
        parts.append(f"{rec['id']} {rec.get('before')}→{rec.get('after')} ({rec.get('severity')})")
    for rec in presence_changes:
        verb = "added" if rec.get("severity") == "added" else "removed"
        parts.append(f"{rec.get('surface')} {rec['id']} {verb}")

    # --- rot RED count (ack-gated as one aggregate fingerprint) ---
    rot = _read_json(ROT_REPORT)
    if isinstance(rot, dict):
        red = (rot.get("counts") or {}).get("RED", 0)
        if red and red > 0:
            fp = _fingerprint("rot", "RED", "count", red)
            if not _suppressed(ack, fp, now):
                parts.append(f"{red} rot RED")
                _record_nudge(ack, fp, now)
                nudged_any = True
    # rot scan staleness, with its age: a note past 7 days, an ALARM past 14 (never ack-suppressed;
    # a stale report is exactly the state in which new skills go unscanned). rot_staleness.py.
    rot_seg = _safe(lambda: _rot_staleness().segment(rot if isinstance(rot, dict) else None,
                                                     ROT_REPORT, now), None)
    if rot_seg:
        parts.append(rot_seg)
        nudged_any = True

    # --- deadlines within horizon (NEVER suppressed by ack) ---
    index = _read_json(INDEX)
    if isinstance(index, dict):
        due = _deadlines_due(index, today)
        if due:
            soonest = min(d["days_remaining"] for d in due)
            parts.append(f"{len(due)} deadline(s) ≤horizon (soonest {soonest:+d}d)")
            nudged_any = True  # always-on class

    # --- #119 identity mismatch (NEVER suppressed; CRITICAL) ---
    ident = _read_json(IDENTITY_REPORT)
    if isinstance(ident, dict):
        status = ident.get("status")
        if status == "mismatch":
            mism = ident.get("mismatch_count", "")
            parts.append(f"gates 3-tree MISMATCH{f' ({mism})' if mism else ''} [CRITICAL]")
            nudged_any = True  # always-on class

    # --- S081 seat-model status (design §4.3/§4.4, plan WP-203) ---
    # Standalone classes join here (before the model-policy block, so its INVALID fold into
    # parts[-1] still lands on the INVALID segment); riders join after the S059 ratio rider.
    seat_standalone, seat_riders = _seat_model_segments(ack, now)
    if seat_standalone:
        parts.extend(seat_standalone)
        nudged_any = True

    # --- S059 model-policy status (design §6.1) ---
    # INVALID is an always-on class (real misconfig, surfaces standalone). The
    # spawns-vs-decisions ratio is a RIDER: it only joins an already-non-empty digest
    # (it is informational atrophy signal, not a standalone nudge). One line either way.
    mp_invalid = _policy_invalid()
    if mp_invalid:
        parts.append("model-policy: INVALID — fail-open active")
        nudged_any = True  # always-on class
    if parts:
        ratio = _spawn_vs_decisions()
        if ratio and not mp_invalid:
            parts.append(f"model-policy: {ratio}")
        elif ratio and mp_invalid:
            # already added INVALID; fold the ratio into the same segment
            parts[-1] = parts[-1] + f"; {ratio}"
    if parts and seat_riders:
        parts.extend(seat_riders)   # S081 riders: informational, never a standalone nudge

    # --- inventory age (informational tail, shown only when we already have a digest) ---
    inv = _read_json(INVENTORY)
    inv_age = _mtime_age_hours(INVENTORY)

    if not parts:
        return None, ack  # SILENT

    head = "[evergreen] " + " · ".join(parts)
    if inv_age is not None and inv_age >= 24:
        head += f" · inventory {int(inv_age)}h old"
    head += (' — say "run the version sweep" or: '
             'bash ~/.claude/skills/_meta/alf_sweep_launcher.sh version')

    # advance the watermark to the newest history ts we considered (so the same
    # version bumps don't re-fire next session beyond their cap).
    if history:
        newest = max((r.get("ts", "") for r in history), default=watermark)
        if newest:
            ack["watermark_ts"] = newest
    return head, ack


# ── hook emission ────────────────────────────────────────────────────────────

def emit_hook(digest: str | None) -> None:
    if digest:
        out = {
            "continue": True,
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": digest,
            },
        }
    else:
        # Quiet session: zero text, no additionalContext.
        out = {"continue": True, "suppressOutput": True}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")


def cmd_ack() -> int:
    """Advance the watermark to 'now' and set ack_until on all current fingerprints
    (the user explicitly acked). Best-effort."""
    ack = load_ack()
    now = datetime.now(timezone.utc)
    nowiso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ack["watermark_ts"] = nowiso
    _safe(lambda: _ack_roster_findings(ack, now), 0)   # #291 s3.7: an acked roster change stays quiet
    save_ack(ack)
    print("freshness_nudge: watermark advanced; version nudges suppressed until new changes")
    return 0


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # Drain stdin if piped (hook protocol) so we never block.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    if "--ack" in argv:
        return cmd_ack()

    hook_mode = "--hook" in argv
    try:
        today = date.today()
        now = datetime.now(timezone.utc)
        digest, ack = build_digest(today, now)
        # Persist the updated dedup state (watermark + counts) — only if we built a digest.
        if digest is not None:
            save_ack(ack)
        if hook_mode:
            emit_hook(digest)
        else:
            print(digest if digest else "(silent — nothing to nudge)")
        return 0
    except Exception:  # noqa: BLE001 — never break a session
        if hook_mode:
            sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}) + "\n")
        else:
            print("(silent — nudge error)")
        return 0


if __name__ == "__main__":
    from portable_cli import run_cli          # #251 — see portable_cli.py
    sys.exit(run_cli(main))
