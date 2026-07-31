#!/usr/bin/env python3
"""prefs.py — read/write per-domain user-preference profiles (stdlib only).

Durable, cross-project user preferences live as one markdown profile per domain
under the GLOBAL memory tier: `~/.claude/memory/preferences/<domain>.md`. Each
profile has a flat `key: value` frontmatter block (the structured prefs that get
loaded as constraints) plus a dated free-form body (nuance the user stated).

CAPTURE IS EXPLICIT ONLY — this engine writes a preference only when invoked with
`set`/`note` (i.e. the user stated one). Nothing here infers preferences.

Operations:
  list                          list domains + their key counts
  show   <domain>               print the full profile
  load   <domain>               print prefs as constraints (for injection before domain work)
  set    <domain> <key> <val>   set/update a structured key (+ a dated note)
  note   <domain> <text>        append a dated free-form note
Flags: --store DIR (default ~/.claude/memory/preferences), --date YYYY-MM-DD
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

KNOWN_DOMAINS = ("coding", "presentations", "email", "tone")


def store_dir(arg: str | None) -> Path:
    return Path(arg).expanduser() if arg else Path.home() / ".claude" / "memory" / "preferences"


def _oneline(s: str) -> str:
    """Collapse all whitespace (incl. newlines) to single spaces so a value can NEVER
    inject a new frontmatter key or break a list item on the next parse (Codex)."""
    return " ".join(s.split())


def _profile_path(store: Path, domain: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_-]+", domain):
        raise SystemExit(f"ERROR: invalid domain '{domain}' (use [a-z0-9_-]).")
    return store / f"{domain}.md"


def _parse(text: str) -> tuple[dict, str]:
    """Flat `key: value` frontmatter + body. Stdlib only (no PyYAML)."""
    fm: dict = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        body = m.group(2)
    return fm, body


def _render(fm: dict, body: str) -> str:
    keys = [k for k in fm if k not in ("domain", "updated")]
    lines = ["---", f"domain: {fm.get('domain', '')}", f"updated: {fm.get('updated', '')}"]
    for k in sorted(keys):
        lines.append(f"{k}: {fm[k]}")
    lines.append("---")
    return "\n".join(lines) + "\n" + (body if body.startswith("\n") else "\n" + body)


def _read(store: Path, domain: str) -> tuple[dict, str]:
    p = _profile_path(store, domain)
    if p.is_file():
        return _parse(p.read_text())
    return {"domain": domain, "updated": ""}, f"\n# {domain} preferences\n\nUser-stated preferences (explicit capture only).\n"


def _write(store: Path, domain: str, fm: dict, body: str, today: str):
    store.mkdir(parents=True, exist_ok=True)
    fm["domain"] = domain
    fm["updated"] = today
    _profile_path(store, domain).write_text(_render(fm, body))


def cmd_list(store: Path) -> int:
    if not store.is_dir():
        print("(no preferences yet)")
        return 0
    for p in sorted(store.glob("*.md")):
        fm, _ = _parse(p.read_text())
        nkeys = len([k for k in fm if k not in ("domain", "updated")])
        print(f"  {p.stem:<16} {nkeys} pref(s)  (updated {fm.get('updated', '?')})")
    return 0


def cmd_show(store: Path, domain: str) -> int:
    p = _profile_path(store, domain)
    print(p.read_text() if p.is_file() else f"(no profile for '{domain}' yet)")
    return 0


def cmd_load(store: Path, domain: str) -> int:
    """Compact constraint view for injecting before domain work."""
    fm, _ = _read(store, domain)
    keys = [k for k in fm if k not in ("domain", "updated")]
    if not keys:
        print(f"(no recorded {domain} preferences yet)")
        return 0
    print(f"Active {domain} preferences (honor these):")
    for k in sorted(keys):
        print(f"  - {k}: {fm[k]}")
    return 0


def cmd_set(store: Path, domain: str, key: str, value: str, today: str) -> int:
    if not re.fullmatch(r"[a-z0-9_]+", key):
        raise SystemExit(f"ERROR: invalid key '{key}' (use [a-z0-9_]).")
    value = _oneline(value)  # frontmatter values MUST stay single-line
    fm, body = _read(store, domain)
    old = fm.get(key)
    fm[key] = value
    note = f"- {today}: set `{key}` = {value}" + (f" (was: {old})" if old else "")
    body = body.rstrip() + "\n" + note + "\n"
    _write(store, domain, fm, body, today)
    print(f"  recorded {domain}.{key} = {value}")
    return 0


def cmd_note(store: Path, domain: str, text: str, today: str) -> int:
    text = _oneline(text)  # keep the note a single list item
    fm, body = _read(store, domain)
    body = body.rstrip() + f"\n- {today}: {text}\n"
    _write(store, domain, fm, body, today)
    print(f"  noted under {domain}: {text}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Per-domain user-preference profiles (explicit capture only).")
    p.add_argument("op", choices=["list", "show", "load", "set", "note"])
    p.add_argument("args", nargs="*")
    p.add_argument("--store", default=None)
    p.add_argument("--date", default=None)
    a = p.parse_args(argv)
    store = store_dir(a.store)
    today = a.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    if a.op == "list":
        return cmd_list(store)
    if not a.args:
        print(f"ERROR: '{a.op}' needs a domain (known: {', '.join(KNOWN_DOMAINS)} — custom allowed).",
              file=sys.stderr)
        return 2
    domain = a.args[0]
    if a.op == "show":
        return cmd_show(store, domain)
    if a.op == "load":
        return cmd_load(store, domain)
    if a.op == "set":
        if len(a.args) < 3:
            print("ERROR: set <domain> <key> <value...>", file=sys.stderr); return 2
        return cmd_set(store, domain, a.args[1], " ".join(a.args[2:]), today)
    if a.op == "note":
        if len(a.args) < 2:
            print("ERROR: note <domain> <text...>", file=sys.stderr); return 2
        return cmd_note(store, domain, " ".join(a.args[1:]), today)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
