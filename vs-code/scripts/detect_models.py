#!/usr/bin/env python3
"""detect_models.py — S074. Discover which models this VS Code / Copilot install can reach.

NOTHING here hardcodes a model version, and that is a deliberate constraint rather than a
convenience. Copilot's roster changes frequently and varies by plan, organisation policy and
region, so a version baked into a config becomes a silent failure that presents as a
permissions error. Detect, report, and let the caller choose from what actually exists.

Run at install time AND at runtime — the answer legitimately differs between them, because an
org policy or a plan change moves the roster without touching this machine.

Sources, cheapest first:
  1. `copilot` CLI, if present and able to list models
  2. VS Code / Copilot config files on disk
  3. Nothing — reported honestly as unknown, never as a guessed default

Exit: 0 models found · 2 none detectable (state it, do not assume) · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Families we know Copilot has offered. Used ONLY to classify a detected id into a routing
# tier — never to assert that a model is available. An empty detection stays empty.
FAMILY_HINTS = (
    ("claude", "anthropic"), ("opus", "anthropic"), ("sonnet", "anthropic"), ("haiku", "anthropic"),
    ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("codex", "openai"),
    ("gemini", "google"),
)


def classify(model_id: str) -> str:
    low = model_id.lower()
    for token, vendor in FAMILY_HINTS:
        if token in low:
            return vendor
    return "unknown"


def from_cli() -> List[str]:
    exe = shutil.which("copilot")
    if not exe:
        return []
    for argv in (["model", "list"], ["models"], ["--list-models"]):
        try:
            p = subprocess.run([exe, *argv], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if p.returncode == 0 and p.stdout.strip():
            out = []
            for line in p.stdout.splitlines():
                tok = line.strip().split()[0] if line.strip() else ""
                if tok and not tok.startswith(("-", "#", "Model", "NAME")):
                    out.append(tok)
            if out:
                return sorted(set(out))
    return []


def config_candidates() -> List[Path]:
    home = Path.home()
    sysname = platform.system()
    if sysname == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        roots = [base / "Code" / "User"]
    elif sysname == "Darwin":
        roots = [home / "Library" / "Application Support" / "Code" / "User"]
    else:
        roots = [home / ".config" / "Code" / "User", home / ".vscode-server" / "data" / "User"]
    return [r / "settings.json" for r in roots] + [home / ".copilot" / "config.json"]


def from_config() -> List[str]:
    found: List[str] = []
    for path in config_candidates():
        if not path.is_file():
            continue
        try:
            raw = path.read_text(errors="ignore")
        except OSError:
            continue
        for line in raw.splitlines():
            for part in line.split('"'):
                p_low = part.strip().lower()
                if not p_low or len(part) > 60:
                    continue
                if not any(tok in p_low for tok in (t for t, _ in FAMILY_HINTS)):
                    continue
                # A settings KEY is not a model id. Keys are camelCase or dotted
                # (`claudeCode.preferredLocation`); model ids are lowercase with
                # separators (`claude-opus-4`, `gpt-4o`). Shipping the former as a
                # model would put a value in the picker that can never resolve.
                if "." in part or (part != part.lower() and "-" not in part):
                    continue
                if not any(c in part for c in "-_"):
                    continue
                found.append(part.strip())
    return sorted(set(found))


def detect() -> Dict[str, Any]:
    cli, cfg = from_cli(), from_config()
    models = sorted(set(cli) | set(cfg))
    by_vendor: Dict[str, List[str]] = {}
    for m in models:
        by_vendor.setdefault(classify(m), []).append(m)

    return {
        "detected_at": None,  # stamped by the caller; this script does not invent time
        "platform": platform.system(),
        "copilot_cli": bool(shutil.which("copilot")),
        "vscode_cli": bool(shutil.which("code")),
        "sources": {"cli": cli, "config": cfg},
        "models": models,
        "by_vendor": by_vendor,
        "vendors_available": sorted(v for v in by_vendor if v != "unknown"),
        "note": (
            "Detected, never asserted. An empty list means detection could not reach a roster on "
            "this machine — NOT that no models exist. Check in the VS Code model picker and record "
            "what you see; do not fall back to a remembered model id, which fails silently as a "
            "permissions error."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Detect reachable Copilot/VS Code models.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = detect()

    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"MODEL DETECTION — {r['platform']} · copilot CLI: {r['copilot_cli']} · "
              f"code CLI: {r['vscode_cli']}\n")
        if r["models"]:
            for vendor in sorted(r["by_vendor"]):
                print(f"  {vendor}:")
                for m in r["by_vendor"][vendor]:
                    print(f"    - {m}")
            print(f"\n  vendors reachable: {', '.join(r['vendors_available']) or 'none classified'}")
        else:
            print("  no models detected from CLI or config")
        print(f"\n  {r['note']}")
    return 0 if r["models"] else 2


if __name__ == "__main__":
    sys.exit(main())
