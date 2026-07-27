#!/usr/bin/env python3
"""inventory_history.py — change-record history writer for the env-adoption sensor.

Part of Ecosystem Evergreening v1 (S041). Invoked by probe.sh AFTER a REAL probe
(cache-miss / --force) writes inventory.json. Does three things:

  1. Collect additional surfaces the bash probe does not: `plugins` (from the
     enabled-plugins map in settings.json + each plugin cache package.json) and
     `mcp_servers` (sorted name list from ~/.claude.json). These are MERGED back
     into inventory.json (so downstream readers — nudge, rot_scan cross-ref — see
     them). Absence reads as `coverage: partial`, NEVER a phantom add/remove.

  2. Diff the freshly-written inventory.json against the previous snapshot
     (~/.claude/state/inventory-prev.json) across tool versions, plugin versions,
     and the mcp_servers set.

  3. Append ONE canonical-JSON record PER CHANGE to
     ~/.claude/state/inventory-history.jsonl (O_APPEND, best-effort-never-raise —
     gate_runs.py discipline). No change -> no record (the debounce primitive).

Design refs: §6.1 (inventory-history.v1 schema), Adjudication 2 (change-records),
Adjudication 3 (placement: probe owns versions), spec-review Issue 3 (verify key
names live; default to empty on absence).

Schema (inventory-history.v1):
  {"schema_version":"inventory-history.v1","ts":"<iso>","surface":"cli|plugin|mcp|tool",
   "id":"<name>","field":"version|presence","before":<val>,"after":<val>,
   "severity":"patch|minor|major|added|removed","probe_id":"<uuid>"}

This module is stdlib-only and deterministic (modulo ts/probe_id). It NEVER writes
to any path under ~/.claude/skills/ — only ~/.claude/state/. (D1 structural invariant.)
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "inventory-history.v1"

HOME = Path(os.environ.get("HOME", str(Path.home())))
CLAUDE_DIR = HOME / ".claude"
STATE_DIR = CLAUDE_DIR / "state"
INVENTORY_FILE = STATE_DIR / "inventory.json"
PREV_FILE = STATE_DIR / "inventory-prev.json"
HISTORY_FILE = STATE_DIR / "inventory-history.jsonl"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
CLAUDE_JSON = HOME / ".claude.json"
PLUGIN_CACHE = CLAUDE_DIR / "plugins" / "cache"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── surface collectors ──────────────────────────────────────────────────────

def collect_plugins() -> dict:
    """Return {plugin_id: {"enabled": bool, "version": str|None}}.

    plugin_id is the enabled-plugins key ("name@marketplace") when available,
    else the bare cache directory name. Version is read from the plugin's
    package.json if present, else None. Absence of any source yields {} (which
    the diff treats as coverage: partial, not a wholesale removal).
    """
    out: dict = {}

    # enabled-plugins map from settings.json (verified live key: "enabledPlugins",
    # shape dict["name@marketplace": bool] — spec-review Issue 3 pre-flight).
    settings = _read_json(SETTINGS_FILE) or {}
    enabled = settings.get("enabledPlugins")
    if isinstance(enabled, dict):
        for key, val in enabled.items():
            out[key] = {"enabled": bool(val), "version": None}

    # versions from plugin cache package.json files (best-effort).
    # Cache layout: plugins/cache/<marketplace>/<plugin>/[<sub>/]package.json
    if PLUGIN_CACHE.is_dir():
        for pkg in PLUGIN_CACHE.glob("*/*/package.json"):
            _merge_pkg(out, pkg)
        for pkg in PLUGIN_CACHE.glob("*/*/*/package.json"):
            _merge_pkg(out, pkg)

    return out


def _merge_pkg(out: dict, pkg: Path) -> None:
    data = _read_json(pkg)
    if not isinstance(data, dict):
        return
    name = data.get("name")
    version = data.get("version")
    if not name:
        return
    marketplace = pkg.parent.parent.name  # plugins/cache/<marketplace>/<plugin>/...
    key_full = f"{name}@{marketplace}"
    # Attach the version to the matching enabled-plugins key if one exists;
    # otherwise register the plugin under its bare name (still tracked).
    if key_full in out:
        out[key_full]["version"] = version
    elif name in out:
        out[name]["version"] = version
    else:
        # Match any enabled key that starts with "<name>@" (marketplace mismatch).
        matched = next((k for k in out if k.split("@", 1)[0] == name), None)
        if matched is not None:
            out[matched]["version"] = version
        else:
            out[name] = {"enabled": False, "version": version}


def collect_mcp_servers() -> list:
    """Return a sorted list of MCP server names.

    Canonical location (verified live): ~/.claude.json top-level "mcpServers".
    Project-scoped maps (projects.<path>.mcpServers) are unioned in when present.
    Absence yields [] (coverage: partial), never a phantom set.
    """
    names: set = set()
    cj = _read_json(CLAUDE_JSON) or {}
    top = cj.get("mcpServers")
    if isinstance(top, dict):
        names.update(top.keys())
    projects = cj.get("projects")
    if isinstance(projects, dict):
        for pv in projects.values():
            if isinstance(pv, dict):
                pm = pv.get("mcpServers")
                if isinstance(pm, dict):
                    names.update(pm.keys())
    return sorted(names)


# ── semver severity ─────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")


def _parse_semver(v):
    if not isinstance(v, str):
        return None
    m = _SEMVER_RE.match(v.strip())
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) is not None else 0
    return (major, minor, patch)


def version_severity(before, after) -> str:
    """Classify a version transition. 0.x tools treat the SECOND digit as minor
    (design §6.1: "0.x tools: treat second digit as minor"). Falls back to
    'minor' when versions are unparseable but differ."""
    pb = _parse_semver(before)
    pa = _parse_semver(after)
    if pb is None or pa is None:
        return "minor"
    if pa == pb:
        return "patch"  # caller filters equality before calling; defensive
    # 0.x convention: when major is 0 on both sides, minor-digit change == "minor",
    # patch-digit change == "patch", and a 0->1 major bump is "major".
    if pb[0] != pa[0]:
        return "major"
    if pb[1] != pa[1]:
        return "minor"
    return "patch"


# ── diffing ──────────────────────────────────────────────────────────────────

def diff_inventories(prev: dict | None, cur: dict, probe_id: str) -> list:
    """Produce inventory-history.v1 records for every real change.

    prev is None (first-ever probe) -> emit NOTHING (no baseline to diff against;
    avoids a phantom "everything added" storm on initial adoption)."""
    records: list = []
    if not isinstance(prev, dict):
        return records
    ts = _now_iso()

    # ── tools (surface: cli/tool) ──
    prev_tools = (prev.get("tools") or {}) if isinstance(prev.get("tools"), dict) else {}
    cur_tools = (cur.get("tools") or {}) if isinstance(cur.get("tools"), dict) else {}
    cli_ids = {"claude", "codex", "agy", "copilot", "gh"}
    for tid in sorted(set(prev_tools) | set(cur_tools)):
        pv = prev_tools.get(tid) or {}
        cv = cur_tools.get(tid) or {}
        p_inst = bool(pv.get("installed"))
        c_inst = bool(cv.get("installed"))
        surface = "cli" if tid in cli_ids else "tool"
        if p_inst != c_inst:
            records.append(_rec(ts, surface, tid, "presence", p_inst, c_inst,
                                "added" if c_inst else "removed", probe_id))
            continue
        if not c_inst:
            continue
        pver = pv.get("version")
        cver = cv.get("version")
        if pver != cver and (pver is not None or cver is not None):
            sev = version_severity(pver, cver)
            records.append(_rec(ts, surface, tid, "version", pver, cver, sev, probe_id))

    # ── plugins (surface: plugin) ──
    prev_pl = prev.get("plugins") if isinstance(prev.get("plugins"), dict) else {}
    cur_pl = cur.get("plugins") if isinstance(cur.get("plugins"), dict) else {}
    # Only diff when BOTH snapshots have a plugins map (else coverage: partial —
    # do not emit add/remove churn from a side that simply lacked the sensor).
    if prev_pl and cur_pl:
        for pid in sorted(set(prev_pl) | set(cur_pl)):
            pe = pid in prev_pl
            ce = pid in cur_pl
            if pe != ce:
                records.append(_rec(ts, "plugin", pid, "presence", pe, ce,
                                    "added" if ce else "removed", probe_id))
                continue
            pver = (prev_pl.get(pid) or {}).get("version")
            cver = (cur_pl.get(pid) or {}).get("version")
            if pver != cver and (pver is not None or cver is not None):
                sev = version_severity(pver, cver)
                records.append(_rec(ts, "plugin", pid, "version", pver, cver, sev, probe_id))

    # ── mcp_servers (surface: mcp) ──
    prev_mcp = prev.get("mcp_servers")
    cur_mcp = cur.get("mcp_servers")
    if isinstance(prev_mcp, list) and isinstance(cur_mcp, list):
        ps, cs = set(prev_mcp), set(cur_mcp)
        for name in sorted(cs - ps):
            records.append(_rec(ts, "mcp", name, "presence", False, True, "added", probe_id))
        for name in sorted(ps - cs):
            records.append(_rec(ts, "mcp", name, "presence", True, False, "removed", probe_id))

    return records


def _rec(ts, surface, _id, field, before, after, severity, probe_id) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "surface": surface,
        "id": _id,
        "field": field,
        "before": before,
        "after": after,
        "severity": severity,
        "probe_id": probe_id,
    }


# ── append (O_APPEND, never-raise) ──────────────────────────────────────────

def append_records(records: list) -> int:
    if not records:
        return 0
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # O_APPEND guarantees each write lands at EOF even with concurrent writers.
        fd = os.open(str(HISTORY_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            for rec in records:
                line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
                os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return len(records)
    except OSError:
        # best-effort-never-raise: a history-write failure must not break the probe.
        return 0


# ── main: collect → merge into inventory.json → diff prev → append ──────────

def run() -> int:
    """Returns number of change-records appended. Never raises."""
    try:
        cur = _read_json(INVENTORY_FILE)
        if not isinstance(cur, dict):
            return 0  # no inventory to augment; nothing to do

        # The snapshot we diff AGAINST is the prev file as it stands BEFORE we
        # overwrite it. probe.sh copies inventory.json -> inventory-prev.json
        # *before* the real probe; so PREV_FILE here is the prior inventory.
        prev = _read_json(PREV_FILE)

        # Collect the extra surfaces and merge them into the current inventory so
        # downstream consumers (nudge, rot cross-ref) and the NEXT diff see them.
        plugins = collect_plugins()
        mcp_servers = collect_mcp_servers()
        cur["plugins"] = plugins
        cur["mcp_servers"] = mcp_servers
        cur.setdefault("coverage", {})
        cur["coverage"]["plugins"] = "full" if plugins else "partial"
        cur["coverage"]["mcp_servers"] = "full" if mcp_servers else "partial"

        # Re-write inventory.json with the merged surfaces (atomic-ish: temp+rename).
        try:
            tmp = INVENTORY_FILE.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(cur, fh, indent=2, sort_keys=False)
                fh.write("\n")
            os.replace(str(tmp), str(INVENTORY_FILE))
        except OSError:
            pass  # if the merge-write fails, history diff still proceeds on in-mem cur

        probe_id = str(uuid.uuid4())
        records = diff_inventories(prev, cur, probe_id)
        return append_records(records)
    except Exception:  # noqa: BLE001 — absolute never-raise boundary (gate_runs discipline)
        return 0


if __name__ == "__main__":
    n = run()
    if "--verbose" in sys.argv:
        print(f"inventory-history: {n} change-record(s) appended", file=sys.stderr)
    sys.exit(0)
