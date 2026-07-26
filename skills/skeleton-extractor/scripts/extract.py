#!/usr/bin/env python3
"""extract.py — skeleton-extractor Python CLI wrapper.

Thin wrapper that spawns the Node subprocess (_meta/skeleton_extractor.mjs),
sends a JSON payload on stdin, captures the single JSON blob on stdout, and
persists a draft design-skeleton.v1 YAML via trusted_runner.atomic_write_bytes.

CB3 compliance: this wrapper (invoked under trusted_runner discipline) owns
the file write; the Node subprocess is stdout-only.

Usage:
    python3 extract.py \\
        --mockup /abs/path/to/mockup.html \\
        --out /abs/path/out.draft.yaml \\
        [--breakpoints 420,700,1280] \\
        [--tokens-path /abs/path/to/index.yaml]

Exit codes:
    0 = draft written successfully
    2 = subprocess failed (non-zero exit or timeout); an observation is
        emitted (fail-open) and the Python exception propagates as stderr.
    3 = usage / environment error (missing arg, unreadable input, chrome
        binary absent).

Design refs:
    docs/plans/2026-04-23-ecosystem-keystone-design.md §2.4 (algorithm)
    progress/contract-map.yaml skeleton-extractor (TS-SE-01..04)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- locate _meta on sys.path so we can import trusted_runner ---------------
# When run from the staged location in foundry-lab/skills/skeleton-extractor/scripts/,
# _meta sits at ~/.claude/skills/_meta OR at foundry-lab/skills/_meta once
# synced. Support both lookup paths.
_META_CANDIDATES = [
    Path.home() / ".claude" / "skills" / "_meta",
    Path(__file__).resolve().parent.parent.parent / "_meta",
]
for _p in _META_CANDIDATES:
    if (_p / "trusted_runner.py").exists():
        sys.path.insert(0, str(_p))
        break

from trusted_runner import atomic_write_bytes  # noqa: E402


# --- fail-open observation wrapper -----------------------------------------
def _observe(category: str, what_happened: str, subject_id: str = "skeleton-extractor") -> None:
    """Emit a process-observation with full fail-open semantics (§4.4).

    ImportError (skill not available in this env), any runtime error, or
    environment issue inside claude_observe MUST NOT block the caller. This
    wrapper swallows everything.
    """
    try:
        sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "process-observation" / "scripts"))
        from write import claude_observe  # type: ignore
        claude_observe(
            category,
            subject_id,
            what_happened,
            subject_type="external_tool",
            severity="blocking",
        )
    except Exception:
        # Fail-open per ecosystem-keystone §4.4.
        pass


# --- Node subprocess --------------------------------------------------------
def _find_extractor_mjs() -> Path:
    """Locate skeleton_extractor.mjs. Prefer ~/.claude/skills/_meta, fall back
    to the staged copy under foundry-lab/skills/_meta.
    """
    candidates = [
        Path.home() / ".claude" / "skills" / "_meta" / "skeleton_extractor.mjs",
        Path(__file__).resolve().parent.parent.parent / "_meta" / "skeleton_extractor.mjs",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"skeleton_extractor.mjs not found in any of: {[str(c) for c in candidates]}"
    )


def _sanitized_env() -> Dict[str, str]:
    """Mirrors trusted_runner.sanitized_env() — minimal env for node + chrome.

    We preserve NODE_PATH and SKELETON_EXTRACTOR_PUPPETEER_PATH so the mjs
    can locate puppeteer-core when it is not installed in a node_modules
    tree adjacent to _meta/skeleton_extractor.mjs. DISPLAY/XDG_RUNTIME_DIR
    are preserved so Chrome headless works in sandboxed environments.
    """
    keys = (
        "PATH", "HOME", "LANG", "LC_ALL", "USER", "SHELL", "TMPDIR", "TERM",
        "NODE_PATH", "SKELETON_EXTRACTOR_PUPPETEER_PATH",
        "DISPLAY", "XDG_RUNTIME_DIR",
    )
    env = {k: os.environ[k] for k in keys if k in os.environ}

    # If the caller did not set SKELETON_EXTRACTOR_PUPPETEER_PATH but we can
    # discover a puppeteer-core package directory via NODE_PATH, pass it
    # through explicitly — this is the most reliable way to make ESM imports
    # work inside subprocess on this host.
    if "SKELETON_EXTRACTOR_PUPPETEER_PATH" not in env:
        node_path = env.get("NODE_PATH") or os.environ.get("NODE_PATH") or ""
        for candidate_root in node_path.split(os.pathsep):
            if not candidate_root:
                continue
            p = Path(candidate_root) / "puppeteer-core"
            if p.is_dir() and (p / "package.json").is_file():
                env["SKELETON_EXTRACTOR_PUPPETEER_PATH"] = str(p)
                break

    return env


def _run_extractor(
    mockup_path: Path,
    breakpoints: List[int],
    tokens: Optional[Dict[str, Any]],
    timeout_s: int = 120,
) -> Dict[str, Any]:
    """Spawn the Node extractor, pipe JSON stdin, capture JSON stdout.

    Raises:
        FileNotFoundError: mjs or node binary missing.
        subprocess.TimeoutExpired: subprocess ran past timeout_s.
        RuntimeError: non-zero exit or non-JSON stdout.
    """
    mjs = _find_extractor_mjs()
    payload = {
        "mockupHtml": str(mockup_path),
        "breakpoints": list(breakpoints),
        "tokens": tokens or {},
    }
    stdin_bytes = json.dumps(payload).encode("utf-8")
    try:
        proc = subprocess.run(
            ["node", str(mjs)],
            input=stdin_bytes,
            env=_sanitized_env(),
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as e:
        _observe("external_tool_fail", f"node binary missing: {e}")
        raise
    except subprocess.TimeoutExpired as e:
        _observe("external_tool_slow", f"skeleton extractor exceeded {timeout_s}s timeout")
        raise

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-4000:]
        _observe("external_tool_fail", f"skeleton extractor exit {proc.returncode}: {stderr_tail[:200]}")
        raise RuntimeError(
            f"skeleton_extractor.mjs exited {proc.returncode}. stderr tail:\n{stderr_tail}"
        )

    stdout_text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if not stdout_text:
        _observe("external_tool_fail", "skeleton extractor emitted empty stdout")
        raise RuntimeError("skeleton_extractor.mjs emitted empty stdout")
    try:
        return json.loads(stdout_text)
    except json.JSONDecodeError as e:
        _observe("external_tool_fail", f"skeleton extractor malformed JSON: {e}")
        raise RuntimeError(f"skeleton_extractor.mjs returned non-JSON stdout: {e}")


# --- YAML serialization ----------------------------------------------------
def _to_yaml(obj: Any, indent: int = 0) -> str:
    """Minimal deterministic YAML writer — no external dep required.

    Supports dict, list, str, int, float, bool, None. Strings are double-quoted
    when they contain special characters. Preserves insertion order.
    """
    lines: List[str] = []
    pad = "  " * indent

    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, str):
        if obj == "" or any(c in obj for c in ":#[]{}&*!|>'\"%@`,\n") or obj.strip() != obj:
            return '"' + obj.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return obj
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        out = []
        for k, v in obj.items():
            key = str(k)
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key}:")
                out.append(_to_yaml(v, indent + 1))
            else:
                out.append(f"{pad}{key}: {_to_yaml(v, indent + 1) if not isinstance(v, (dict, list)) else ('{}' if isinstance(v, dict) else '[]')}")
        return "\n".join(out)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        out = []
        for item in obj:
            if isinstance(item, (dict, list)) and item:
                # first key/item inline after dash, then continue
                rendered = _to_yaml(item, indent + 1)
                first_line, _, rest = rendered.partition("\n")
                stripped = first_line.lstrip()
                out.append(f"{pad}- {stripped}")
                if rest:
                    out.append(rest)
            else:
                out.append(f"{pad}- {_to_yaml(item, indent + 1)}")
        return "\n".join(out)
    return str(obj)


def _load_tokens(tokens_path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Load declared tokens from an index.yaml-shaped file.

    Very permissive: if PyYAML is available, use it; otherwise parse a simple
    key/value subset. Test fixtures use a small, predictable YAML form.
    """
    if not tokens_path:
        return None
    if not tokens_path.is_file():
        return None
    raw = tokens_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        doc = yaml.safe_load(raw) or {}
        # index.yaml has top-level "tokens" block; pass it through as-is.
        if isinstance(doc, dict) and "tokens" in doc and isinstance(doc["tokens"], dict):
            return doc["tokens"]
        return doc if isinstance(doc, dict) else None
    except Exception:
        # Minimal fallback: no YAML parser and the file is a simple token map.
        return None


# --- CLI --------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract design-skeleton draft from an HTML mockup.")
    parser.add_argument("--mockup", required=True, help="Absolute path to HTML mockup.")
    parser.add_argument("--out", required=True, help="Absolute path for draft YAML output.")
    parser.add_argument("--breakpoints", default="420,700,1280", help="Comma-list of viewport widths.")
    parser.add_argument("--tokens-path", default=None, help="Optional path to index.yaml with declared tokens.")
    parser.add_argument("--timeout", type=int, default=120, help="Subprocess timeout seconds.")
    args = parser.parse_args(argv)

    mockup = Path(args.mockup).resolve()
    out = Path(args.out).resolve()
    if not mockup.is_file():
        sys.stderr.write(f"[extract] mockup not found: {mockup}\n")
        return 3

    # Chrome presence check — diagnostic only.
    if not Path("/bin/google-chrome").exists():
        sys.stderr.write("[extract] /bin/google-chrome missing; subprocess will fail\n")
        _observe("external_tool_fail", "google-chrome binary absent at /bin/google-chrome")
        return 3

    try:
        bps = [int(x) for x in args.breakpoints.split(",") if x.strip()]
    except ValueError:
        sys.stderr.write(f"[extract] invalid --breakpoints: {args.breakpoints}\n")
        return 3

    tokens_path = Path(args.tokens_path).resolve() if args.tokens_path else None
    tokens = _load_tokens(tokens_path)

    draft = _run_extractor(mockup, bps, tokens, timeout_s=args.timeout)
    yaml_text = _to_yaml(draft) + "\n"
    atomic_write_bytes(out, yaml_text.encode("utf-8"))
    sys.stdout.write(f"[extract] wrote draft: {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
