#!/usr/bin/env python3
"""load_secrets.py — deliver secrets from ~/.secrets/ into os.environ.

    from load_secrets import load_secrets
    load_secrets("myproject")          # common.env, then myproject.env

Storage is ``~/.secrets/<project>.env`` (0600); this module is the DELIVERY half.

PRECEDENCE: a variable already present in ``os.environ`` WINS over the file value.
That is deliberate — one-off overrides, CI injection and container env keep working
without editing files. Pass ``override=True`` only if you specifically want the file
to win.

This is plaintext-at-rest, NOT a secret manager. See references/storage-standard.md
for the honest caveats (env vars are not a security boundary; scrubbing is not
rotation; the upgrade path is age+sops or pass).

Stdlib only — no dependency on python-dotenv, so it works in any interpreter on the
host including bare system python.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

__all__ = ["load_secrets", "secrets_dir", "SecretsError"]


class SecretsError(RuntimeError):
    """Raised when the secrets directory or requested project file is unusable."""


def secrets_dir() -> Path:
    return Path(os.environ.get("SECRETS_DIR", Path.home() / ".secrets"))


def _warn(msg: str) -> None:
    print(f"load_secrets: WARNING {msg}", file=sys.stderr)


def _check_mode(path: Path, want: int) -> None:
    """Warn (never raise) if permissions are looser than expected.

    Deliberately non-fatal: a too-open file is a real problem, but refusing to run
    would push people back to committing .env files, which is worse.
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode != want:
        _warn(f"{path} is mode {mode:03o}, expected {want:03o}")


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key or not all(c.isalnum() or c == "_" for c in key):
            continue  # skip malformed keys rather than exporting garbage
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def load_secrets(project: str, *, override: bool = False, required: bool = True) -> list[str]:
    """Load ``common.env`` then ``<project>.env`` into ``os.environ``.

    Returns the list of variable names actually set. Later files win over earlier
    ones; the real environment wins over both unless ``override=True``.
    """
    d = secrets_dir()
    if not d.is_dir():
        msg = f"no {d} (mkdir -p {d} && chmod 700 {d})"
        if required:
            raise SecretsError(msg)
        _warn(msg)
        return []
    _check_mode(d, 0o700)

    # Snapshot the REAL environment before we touch it. Precedence is:
    #   real env  >  <project>.env  >  common.env
    # Without this snapshot, a value we ourselves exported from common.env would
    # look "already set" and wrongly block the project file from overriding it.
    pre_existing = set(os.environ)
    applied: list[str] = []
    seen_any = False
    for name in ("common.env", f"{project}.env"):
        f = d / name
        if not f.is_file():
            continue
        seen_any = True
        _check_mode(f, 0o600)
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            _warn(f"could not read {f}: {exc}")
            continue
        for key, val in _parse(text).items():
            if key in pre_existing and not override:
                continue  # the REAL environment wins over any file
            os.environ[key] = val
            applied.append(key)

    if not seen_any:
        msg = f"no secrets files for {project!r} in {d}"
        if required:
            raise SecretsError(msg)
        _warn(msg)
    return applied


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: load_secrets.py <project>   # prints names only, never values",
              file=sys.stderr)
        raise SystemExit(2)
    names = load_secrets(sys.argv[1], required=False)
    # NAMES ONLY — printing values would defeat the entire point of the standard.
    print(f"loaded {len(names)} variable(s): {', '.join(sorted(names)) or '(none)'}")
