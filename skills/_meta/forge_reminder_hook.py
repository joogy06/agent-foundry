#!/usr/bin/env python3
"""
forge_reminder_hook.py — SessionStart hook.

Two halves, in strict priority order:

1. The **static forge routing reminder** (`REMINDER`). Assembled first, as an
   immutable prefix, before any detection code runs. This hook is currently the
   only mechanism guaranteeing forge routing is not skipped, so losing it is a
   worse outcome than having no digest at all. Every failure path below still
   emits it in full.

2. A **bounded, deterministic project + environment digest**, injected as
   `additionalContext`, so the CLAUDE.md session-start procedures stop depending
   on model discretion. Any exception, timeout, hung probe, malformed child
   output, or missing dependency in this half degrades to the static reminder
   plus a one-line note, and still exits 0.

Honesty note (design C3 / codex C4): no same-process handler protects against a
hard kill by the harness. Nothing in this file can guarantee output if the
harness SIGKILLs it. That is precisely why the parent process stays small — it
does no unbounded work itself and delegates every risky operation to a child in
its own process group, which it can kill on timeout. What the parent cannot
survive, it does not attempt.

The digest reports file **presence, size, and line count** plus explicitly
labelled bounded **excerpts**. It never states or implies that a file was read
when only its metadata was inspected.

Usage:
    forge_reminder_hook.py --hook    # emit SessionStart hook JSON on stdout
    forge_reminder_hook.py           # emit the same text plainly (manual check)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── the immutable prefix ───────────────────────────────────────────────────────
# Byte-for-byte unchanged. Nothing below is permitted to alter, wrap, or
# conditionally omit it.

REMINDER = """\
## Forge Routing Reminder (auto-injected every session)

**Autonomy**: Already configured globally (acceptEdits + Bash(*) + git push ask). Do NOT ask the user about autonomy mode.

**Forge routing**: Always-on per CLAUDE.md. Route tasks automatically:
- TRIVIAL (typo, config) → handle directly
- SIMPLE (single-file, clear output) → domain skill directly
- MEDIUM (2-3 files, some decisions) → forge (simple complexity)
- COMPLEX (architecture, cross-layer) → full forge cycle (design team + challengers + bob)

**Critical**: Do NOT skip forge for MEDIUM/COMPLEX tasks. Do NOT write implementation code yourself for MEDIUM/COMPLEX — forge spawns bob for that. If you catch yourself about to write code for a multi-file task without having run forge, STOP and invoke forge first.
"""

# ── bounds (every one of these is a hard cap, not a hint) ──────────────────────

# Total monotonic budget for the whole detection half. The harness allows this
# hook 10 s (CANONICAL_SESSION_START_HOOKS); 6 s leaves headroom for interpreter
# startup and for the harness's own accounting.
TOTAL_DEADLINE_S = 6.0
# Per-probe ceiling, additionally clamped by whatever remains of the total.
# Measured on the reference host: probe.sh check cold 1.47 s / warm 0.85 s,
# discover.sh 0.03 s. 4 s is ~2.7x the cold measurement.
PER_PROBE_TIMEOUT_S = 4.0

# A manifest younger than this is reused verbatim; no probe subprocess is spawned.
# Matches STALENESS_HOURS=24 in both probe.sh and discover.sh.
MANIFEST_FRESH_S = 24 * 3600
# How long a cached digest may still be served to a `compact` event.
DIGEST_CACHE_TTL_S = 12 * 3600

MAX_ROOT_WALK_DEPTH = 8          # levels walked upward looking for a project root
MAX_SCAN_BYTES = 512 * 1024      # per-file ceiling for line counting
MAX_EXCERPT_BYTES = 400          # per-file ceiling for a quoted excerpt
MAX_EXCERPT_LINES = 6
MAX_DIR_ENTRIES = 500            # ceiling on any directory enumeration
MAX_REGISTRY_BYTES = 256 * 1024  # ceiling on the wiki-registry read
MAX_DIGEST_BYTES = 4000          # ceiling on the whole digest
MAX_NOTE_CHARS = 240             # ceiling on the one-line degradation note

# CLAUDE.md's canonical session-start marker set. Ordering is the reading order
# CLAUDE.md prescribes, not alphabetical.
MARKER_FILES = [
    "PROJECT.md",
    "history.md",
    "tasks.md",
    "session_control.md",
    "index.md",
]
MARKER_DIRS = [
    "docs/plans",
    "docs/components",
]
# Only this file gets a quoted excerpt: it is the smallest, most session-specific
# marker, and the one whose *content* changes what should happen next.
EXCERPT_FILE = "session_control.md"

# history.md over this many lines triggers CLAUDE.md's head+tail reading advice.
HISTORY_HEAD_TAIL_THRESHOLD = 400


# ── small helpers ─────────────────────────────────────────────────────────────


def _claude_home() -> Path:
    """Root of the Claude configuration tree.

    `CLAUDE_CONFIG_DIR` is honored if set (this is also what lets the test suite
    redirect state and probe scripts at a throwaway directory instead of the
    user's live `~/.claude`).
    """
    env = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / ".claude"


def _human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _age_s(path: Path) -> float | None:
    """Age of `path` in seconds, or None if it cannot be stat'ed."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _human_age(seconds: float | None) -> str:
    if seconds is None:
        return "age unknown"
    if seconds < 90:
        return f"{int(seconds)}s old"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m old"
    return f"{seconds / 3600:.1f}h old"


def _read_json(path: Path) -> object | None:
    """Parse a JSON file. Returns None on any failure — never raises."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 — malformed manifest is a degradation, not a crash
        return None


# ── hook input (R7: use the payload's cwd, do not drain-and-discard) ───────────


def _read_hook_input() -> dict:
    """Parse the SessionStart JSON payload from stdin.

    Returns {} for a tty, empty stdin, non-JSON, or a JSON non-object. The old
    implementation read stdin only to throw it away, which is what made the hook
    blind to the authoritative `cwd`.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_cwd(payload: dict) -> tuple[Path, str]:
    """Authoritative working directory, with a documented fallback chain.

    hook input `cwd` -> $CLAUDE_PROJECT_DIR -> os.getcwd(). Each candidate must
    exist and be a directory to be accepted.
    """
    candidates = [
        (payload.get("cwd"), "hook cwd"),
        (os.environ.get("CLAUDE_PROJECT_DIR"), "CLAUDE_PROJECT_DIR"),
    ]
    for value, label in candidates:
        if not value or not isinstance(value, str):
            continue
        try:
            p = Path(value)
            if p.is_dir():
                return p, label
        except OSError:
            continue
    try:
        return Path(os.getcwd()), "process cwd (fallback)"
    except OSError:
        return Path("."), "unresolved"


def _find_project_root(start: Path) -> tuple[Path, str]:
    """Walk upward a bounded number of levels for PROJECT.md or .git.

    `.git` is accepted as either a directory or a **file** — a git worktree
    records its gitdir in a plain file, and treating that as "not a repo" would
    silently mis-root every worktree session.
    """
    try:
        current = start.resolve()
    except OSError:
        current = start
    for _ in range(MAX_ROOT_WALK_DEPTH):
        try:
            if (current / "PROJECT.md").is_file():
                return current, "matched PROJECT.md"
            git = current / ".git"
            if git.is_dir():
                return current, "matched .git/"
            if git.is_file():
                return current, "matched .git file (worktree)"
        except OSError:
            pass
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start, "no PROJECT.md or .git found within %d levels" % MAX_ROOT_WALK_DEPTH


# ── bounded filesystem inspection ─────────────────────────────────────────────


def _file_facts(path: Path) -> dict:
    """Metadata for one marker file, plus a bounded line count.

    Symlinks are followed via stat() but a broken or unreadable link degrades to
    `state: unreadable` rather than raising. Line counting stops at
    MAX_SCAN_BYTES and says so.
    """
    facts: dict = {"state": "absent", "size": 0, "lines": None, "lines_capped": False}
    try:
        st = path.stat()
    except OSError:
        # Covers absent, broken symlink, and permission-denied alike.
        if os.path.lexists(path):
            facts["state"] = "unreadable"
        return facts
    if not os.path.isfile(path):
        facts["state"] = "not-a-file"
        return facts
    facts["state"] = "present"
    facts["size"] = st.st_size
    try:
        newlines = 0
        scanned = 0
        last_byte = b""
        with open(path, "rb") as fh:
            while scanned < MAX_SCAN_BYTES:
                chunk = fh.read(min(65536, MAX_SCAN_BYTES - scanned))
                if not chunk:
                    break
                scanned += len(chunk)
                newlines += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if scanned >= MAX_SCAN_BYTES and st.st_size > scanned:
            facts["lines_capped"] = True
        elif last_byte and last_byte != b"\n":
            newlines += 1  # trailing line with no terminator
        facts["lines"] = newlines
    except OSError:
        facts["lines"] = None
    return facts


def _excerpt(path: Path, size: int) -> tuple[list[str], bool, int]:
    """Bounded excerpt: (lines, truncated, bytes_taken).

    Decoded with errors="replace" so invalid UTF-8 never raises. Control
    characters are stripped so a binary-ish file cannot corrupt the digest.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_EXCERPT_BYTES)
    except OSError:
        return [], False, 0
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = len(raw) < size
    if len(lines) > MAX_EXCERPT_LINES:
        lines = lines[:MAX_EXCERPT_LINES]
        truncated = True
    elif truncated and lines:
        # The final line was cut mid-way by the byte cap; drop the fragment.
        lines = lines[:-1]
    clean = ["".join(ch for ch in ln if ch == "\t" or ord(ch) >= 32)[:160] for ln in lines]
    return clean, truncated, len(raw)


def _dir_facts(path: Path) -> dict:
    """Bounded entry count for a marker directory."""
    facts = {"state": "absent", "count": 0, "capped": False}
    if not path.is_dir():
        if os.path.lexists(path):
            facts["state"] = "not-a-dir"
        return facts
    facts["state"] = "present"
    try:
        count = 0
        with os.scandir(path) as it:
            for _ in it:
                count += 1
                if count >= MAX_DIR_ENTRIES:
                    facts["capped"] = True
                    break
        facts["count"] = count
    except OSError:
        facts["state"] = "unreadable"
    return facts


def _wiki_binding(root: Path, home: Path) -> str:
    """Wiki binding per CLAUDE.md: .wiki-link, .wiki/, and the registry."""
    found = []
    missing = []
    try:
        (found if (root / ".wiki-link").is_file() else missing).append(".wiki-link")
        (found if (root / ".wiki").is_dir() else missing).append(".wiki/")
    except OSError:
        missing.append("(root probe failed)")

    # CLAUDE.md puts the registry in the user home, *beside* ~/.claude rather
    # than inside it — so home.parent is the authoritative location and equals
    # ~ in production. Checking it first also keeps a redirected CLAUDE_CONFIG_DIR
    # from silently reading the real user's registry.
    registry = home.parent / ".wiki-registry.yaml"
    if not registry.is_file():
        registry = Path(os.path.expanduser("~")) / ".wiki-registry.yaml"
    try:
        if registry.is_file():
            raw = registry.read_bytes()[:MAX_REGISTRY_BYTES]
            text = raw.decode("utf-8", errors="replace")
            if str(root) in text:
                found.append("~/.wiki-registry.yaml entry")
            else:
                missing.append("registry entry for this root")
        else:
            missing.append("~/.wiki-registry.yaml (absent)")
    except OSError:
        missing.append("registry unreadable")

    if found:
        return "bound — " + ", ".join(found)
    return "none (absent: " + ", ".join(missing) + ")"


# ── bounded child processes ───────────────────────────────────────────────────


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group, so grandchildren cannot survive.

    A probe script that itself spawns helpers would otherwise leak them past the
    hook's lifetime; killing only `proc.pid` reaps the shell and orphans the rest.
    """
    killed_group = False
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            killed_group = True
    except Exception:  # noqa: BLE001 — already exited, or no POSIX groups
        pass
    if not killed_group:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=2)
    except Exception:  # noqa: BLE001
        pass


def _run_probe(argv: list[str], deadline_at: float) -> str | None:
    """Run one probe to completion. Returns None on success, else a short reason.

    stdout and stderr are both routed to DEVNULL. The probes communicate through
    their manifest files, which this hook reads separately — so child stderr has
    no path into `additionalContext` at all, by construction rather than by
    filtering.
    """
    remaining = deadline_at - time.monotonic()
    if remaining <= 0.25:
        return "deadline exhausted"
    budget = min(PER_PROBE_TIMEOUT_S, remaining)
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if hasattr(os, "setsid"):
        kwargs["start_new_session"] = True  # own process group -> killable as a unit
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError as exc:
        return f"probe not runnable ({exc.__class__.__name__})"
    try:
        rc = proc.wait(timeout=budget)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        return f"probe timeout after {budget:.1f}s (process group killed)"
    return None if rc == 0 else f"probe exit {rc}"


def _ensure_manifest(script: Path, argv: list[str], manifest: Path, deadline_at: float) -> str | None:
    """Reuse a manifest younger than 24 h; otherwise refresh it via one probe."""
    age = _age_s(manifest)
    if age is not None and age < MANIFEST_FRESH_S:
        return None  # fresh — no subprocess
    if not script.is_file():
        return f"{script.name} missing"
    return _run_probe(argv, deadline_at)


# ── digest assembly ───────────────────────────────────────────────────────────


def _env_line(home: Path, note: str | None) -> str:
    manifest = home / "state" / "inventory.json"
    data = _read_json(manifest)
    age = _human_age(_age_s(manifest))
    suffix = f" [{note}]" if note else ""
    if not isinstance(data, dict):
        return f"[env] unavailable — no readable inventory.json{suffix}"
    tier = data.get("tier")
    label = data.get("tier_label") or "?"
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    missing = sorted(
        name for name, info in tools.items()
        if isinstance(info, dict) and not info.get("installed")
    )
    miss = ("missing: " + ", ".join(missing)) if missing else "no gaps"
    return f"[env] Tier {tier} ({label}) — {miss}  (inventory {age}){suffix}"


def _grounding_line(home: Path, note: str | None) -> str:
    manifest = home / "state" / "sources.json"
    data = _read_json(manifest)
    age = _human_age(_age_s(manifest))
    suffix = f" [{note}]" if note else ""
    if not isinstance(data, dict):
        return f"[grounding] unavailable — no readable sources.json{suffix}"
    mode = data.get("grounding_mode", "?")
    reach = "internet reachable" if data.get("internet_reachable") else "no internet"
    airgap = " · strict_airgap" if data.get("strict_airgap") else ""
    return f"[grounding] {mode} — {reach}{airgap}  (sources {age}){suffix}"


def _project_block(root: Path, root_how: str, cwd_how: str, home: Path) -> list[str]:
    lines = [
        f"[project] {root.name or str(root)}",
        f"  root: {root} (via {cwd_how}; {root_how})",
        "  context files — METADATA ONLY (size + line count). CONTENTS NOT READ:",
    ]
    absent: list[str] = []
    excerpt_target: tuple[Path, dict] | None = None

    for name in MARKER_FILES:
        path = root / name
        f = _file_facts(path)
        if f["state"] == "absent":
            absent.append(name)
            continue
        if f["state"] != "present":
            lines.append(f"    {name:<20} {f['state']}")
            continue
        if f["lines"] is None:
            shape = "line count unavailable"
        elif f["lines_capped"]:
            shape = f">{f['lines']} lines (scan capped at {_human_bytes(MAX_SCAN_BYTES)})"
        else:
            shape = f"{f['lines']} lines"
        extra = ""
        if name == "history.md" and (f["lines"] or 0) > HISTORY_HEAD_TAIL_THRESHOLD:
            extra = f"  -> >{HISTORY_HEAD_TAIL_THRESHOLD} lines: read head ~50 + tail ~200, check history/INDEX.md"
        lines.append(f"    {name:<20} {_human_bytes(f['size']):>9}  {shape}{extra}")
        if name == EXCERPT_FILE:
            excerpt_target = (path, f)

    for name in MARKER_DIRS:
        d = _dir_facts(root / name)
        if d["state"] == "absent":
            absent.append(name + "/")
            continue
        if d["state"] != "present":
            lines.append(f"    {name + '/':<20} {d['state']}")
            continue
        cap = "+ (capped)" if d["capped"] else ""
        lines.append(f"    {name + '/':<20} {d['count']}{cap} entries")

    if absent:
        lines.append(f"    absent: {', '.join(absent)}")

    if excerpt_target is not None:
        path, f = excerpt_target
        body, truncated, taken = _excerpt(path, f["size"])
        if body:
            head = (
                f"  {EXCERPT_FILE} EXCERPT — first {len(body)} lines, "
                f"{taken} of {f['size']} bytes"
            )
            head += " [TRUNCATED — read the file for the rest]:" if truncated else " [complete]:"
            lines.append(head)
            lines.extend(f"    | {ln}" for ln in body)

    lines.append(f"  wiki: {_wiki_binding(root, home)}")
    return lines


def _cache_path(home: Path, root: Path) -> Path:
    import hashlib

    key = hashlib.sha256(str(root).encode("utf-8", errors="replace")).hexdigest()[:16]
    return home / "state" / "session-digest-cache" / f"{key}.json"


def _write_cache(home: Path, root: Path, digest: str) -> None:
    """Best-effort cache write. A failure here is never allowed to matter."""
    try:
        path = _cache_path(home, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"project_root": str(root), "generated_at": time.time(), "digest": digest}),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def _read_cache(home: Path, root: Path) -> tuple[str, float] | None:
    data = _read_json(_cache_path(home, root))
    if not isinstance(data, dict):
        return None
    digest = data.get("digest")
    generated = data.get("generated_at")
    if not isinstance(digest, str) or not isinstance(generated, (int, float)):
        return None
    if data.get("project_root") != str(root):
        return None  # hash collision or a moved tree: refuse to serve it
    age = time.time() - generated
    if age < 0 or age > DIGEST_CACHE_TTL_S:
        return None
    return digest, age


def _bound(text: str) -> str:
    """Final total-size cap, with an explicit notice when it bites."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_DIGEST_BYTES:
        return text
    cut = encoded[:MAX_DIGEST_BYTES].decode("utf-8", errors="ignore")
    return (
        cut.rstrip()
        + f"\n  [DIGEST TRUNCATED — {len(encoded)} bytes exceeded the {MAX_DIGEST_BYTES}-byte cap]"
    )


def _build_digest(payload: dict, home: Path, deadline_at: float) -> str:
    """The detection half. Callers must treat any exception as recoverable."""
    cwd, cwd_how = _resolve_cwd(payload)
    root, root_how = _find_project_root(cwd)

    env_note = _ensure_manifest(
        home / "skills" / "env-adoption" / "scripts" / "probe.sh",
        ["bash", str(home / "skills" / "env-adoption" / "scripts" / "probe.sh"), "check"],
        home / "state" / "inventory.json",
        deadline_at,
    )
    ground_note = _ensure_manifest(
        home / "skills" / "knowledge-grounding" / "scripts" / "discover.sh",
        [
            "bash",
            str(home / "skills" / "knowledge-grounding" / "scripts" / "discover.sh"),
            "discover",
            "--silent",
        ],
        home / "state" / "sources.json",
        deadline_at,
    )

    lines = ["## Session Context Digest (auto-generated, deterministic)", ""]
    lines += _project_block(root, root_how, cwd_how, home)
    lines.append(_env_line(home, env_note))
    lines.append(_grounding_line(home, ground_note))
    lines += [
        "",
        "-> The context files above were NOT read — only their size and line count were "
        "inspected. Read them before acting, per the CLAUDE.md session-start check.",
    ]
    digest = _bound("\n".join(lines))
    _write_cache(home, root, digest)
    return digest


def _compact_context(home: Path, payload: dict) -> str:
    """`source: compact` — cached digest only. Never spawns a probe subprocess.

    A compaction event is a bad moment to pay for detection: the session is
    already mid-flight and the harness is under time pressure. On a cache miss
    the honest output is the static reminder alone.
    """
    cwd, _ = _resolve_cwd(payload)
    root, _ = _find_project_root(cwd)
    hit = _read_cache(home, root)
    if hit is None:
        return ""
    digest, age = hit
    return digest + f"\n  [served from cache after compaction — digest is {_human_age(age)}]"


def build_context(payload: dict) -> str:
    """Assemble the full `additionalContext`.

    The static reminder is the first thing built and the last thing that can be
    lost: every failure below is caught here and converted into a one-line note.
    """
    parts = [REMINDER]  # immutable prefix — assembled BEFORE any detection
    try:
        home = _claude_home()
        deadline_at = time.monotonic() + TOTAL_DEADLINE_S
        source = payload.get("source") if isinstance(payload, dict) else None
        if source == "compact":
            body = _compact_context(home, payload)
            if body:
                parts.append(body)
            else:
                parts.append(
                    "[context] compaction event with no fresh cached digest — "
                    "static reminder only (no probe is run on compaction)."
                )
        else:
            parts.append(_build_digest(payload, home, deadline_at))
    except BaseException as exc:  # noqa: BLE001 — the reminder outranks everything
        # Only the exception *type* is surfaced. Child stderr and message text
        # can carry paths or secrets and are deliberately not propagated.
        note = f"[context] detection degraded ({type(exc).__name__}) — static reminder above is unaffected."
        parts.append(note[:MAX_NOTE_CHARS])
    return "\n\n".join(parts)


def main() -> int:
    payload = _read_hook_input()
    context = build_context(payload)

    if "--hook" not in sys.argv:
        sys.stdout.write(context)
        sys.stdout.write("\n")
        return 0

    out = {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        },
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    from portable_cli import run_cli          # #251 — see portable_cli.py
    sys.exit(run_cli(main))
