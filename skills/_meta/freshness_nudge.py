#!/usr/bin/env python3
"""freshness_nudge.py — the 4th SessionStart hook (Evergreening v1, S041).

A digest line at session start when the detection bus has something worth saying;
otherwise SILENCE (a suppressOutput envelope with zero text). Reads ONLY small JSON
files already on disk — NO subprocess, NO probing, NO corpus walk — so it stays well
under the §6.3 hard budget of <500ms.

Inputs (all best-effort; a missing/corrupt file is treated as "nothing to say"):
  ~/.claude/state/inventory.json                 (inventory age + plugins/mcp)
  ~/.claude/state/inventory-history.jsonl        (tail since the ack watermark)
  ~/.claude/state/freshness/rot-report.json      (RED count + mtime for staleness)
  ~/.claude/state/freshness/identity-report.json (#119 3-tree status)
  ~/.claude/state/freshness/index.json           (by_deadline horizon)
  ~/.claude/state/freshness/ack.json             (dedup watermark + ack_until)

Nudge policy (BINDING table, §6.3):
  major/minor cli/plugin bump                  -> YES
  patch bump                                   -> NO (counted, surfaces at sweep)
  patch bump + command-set delta already filed -> YES
  tool/plugin/MCP added or removed             -> YES
  rot RED count > 0                            -> YES
  deadline within 30d (60d high-volatility)    -> YES (NEVER suppressed by ack)
  #119 identity mismatch                       -> YES (severity CRITICAL)
  everything else                              -> SILENT

Dedup: per-finding fingerprint sha1(surface|id|field|after); last_nudged + ack_until
in ack.json; same fingerprint max 2 nudges per 14 days; deadlines + identity mismatch
are NEVER suppressed (always-on classes). The watermark advances when a sweep runs or
the user acks.

CLI:
  freshness_nudge.py --hook     # emit SessionStart hook JSON on stdout (the wired path)
  freshness_nudge.py            # human-readable: print the digest line (or "(silent)")
  freshness_nudge.py --ack      # advance the watermark / record an ack (suppress repeats)

NEVER raises to the caller: any internal failure emits the benign silent envelope.
Writes ONLY ack.json under ~/.claude/state/freshness/. (D1: no skill-write path.)
"""
from __future__ import annotations

import hashlib
import json
import os
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

MAX_NUDGES = 2
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


def _suppressed(ack: dict, fp: str, now: datetime) -> bool:
    """True if this fingerprint has hit its nudge cap inside the rolling window."""
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
    if count >= MAX_NUDGES and first:
        try:
            ft = datetime.fromisoformat(first.replace("Z", "+00:00"))
            if (now - ft).days < NUDGE_WINDOW_DAYS:
                return True
        except ValueError:
            pass
    return False


def _record_nudge(ack: dict, fp: str, now: datetime) -> None:
    fps = ack.setdefault("fingerprints", {})
    rec = fps.get(fp)
    nowiso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not rec or (now - datetime.fromisoformat(rec.get("first_ts", nowiso).replace("Z", "+00:00"))).days >= NUDGE_WINDOW_DAYS:
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
    for p in (HOME / ".claude" / "model-policy.yaml",
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
    """Return 'graded N/M spawns' for the cwd project, or None when there is nothing
    meaningful to show (no spawns recorded)."""
    try:
        root = os.getcwd()
        spawns_f = Path(root) / ".process-observations" / "spawn-runs.jsonl"
        decisions_f = HOME / ".claude" / "projects" / _slug(root) / "model-decisions.jsonl"
        spawns = 0
        if spawns_f.is_file():
            with spawns_f.open("r", encoding="utf-8") as fh:
                spawns = sum(1 for ln in fh if ln.strip())
        if spawns == 0:
            return None  # no denominator -> nothing to nudge about
        graded = 0
        if decisions_f.is_file():
            with decisions_f.open("r", encoding="utf-8") as fh:
                graded = sum(1 for ln in fh if ln.strip())
        return f"graded {graded}/{spawns} spawns"
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
        # rot scan staleness (>7d) — informational, always shown if stale
        age = _mtime_age_hours(ROT_REPORT)
        if age is not None and age > ROT_STALE_DAYS * 24:
            parts.append("rot scan stale")

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
    nowiso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ack["watermark_ts"] = nowiso
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
    sys.exit(main())
