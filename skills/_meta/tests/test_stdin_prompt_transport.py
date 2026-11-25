"""The Claude reviewer launches carry their prompt on STDIN, as UTF-8 (#290, #291 fix round 1 B/C).

B. audit_spawn.run_claude_auditor put the prompt in argv. Linux caps ONE argv string at
   MAX_ARG_STRLEN = 131072 bytes, so a large audit prompt died with E2BIG before the model
   call and surfaced as AUDIT_UNAVAILABLE (the sibling of #290, fixed for the arbiter).
C. Both launchers wrote the prompt with text=True and no encoding, i.e. in the LOCALE codec:
   under a non-UTF-8 locale an em dash or a CJK character in the prompt raised an uncaught
   UnicodeEncodeError from subprocess.run. They now encode UTF-8 (decode with replace).

Every launch here goes through a REAL stub binary that drains its stdin and logs what it
got, from a parent process running under LC_ALL=C with UTF-8 mode off (PYTHONUTF8=0), so
the locale codec is ASCII. HOME and XDG_RUNTIME_DIR are temporary directories.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_META = Path(__file__).resolve().parents[1]
_POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="POSIX stub binaries and locale")

NON_ASCII_PROMPT = "Audit the bundle — 漢字 and café, then answer in JSON."

_STUB = """#!{python}
import json, os, select, sys

def drain_stdin():
    data = b""
    try:
        while True:
            ready, _, _ = select.select([0], [], [], 1.0)
            if not ready:
                return data, False
            chunk = os.read(0, 65536)
            if chunk == b"":
                return data, True
            data += chunk
    except OSError:
        return data, False

data, eof = drain_stdin()
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "stdin_eof": eof, "stdin_len": len(data),
                         "stdin_text": data.decode("utf-8", "replace")}}) + "\\n")
verdict = {{"verdict": "pass", "structured_disagreements": [
    {{"point": "p1 \\u2014 \\u6f22", "severity": "minor", "location": "comp-x"}},
    {{"point": "p2", "severity": "minor", "location": "comp-x"}},
    {{"point": "p3", "severity": "moderate", "location": "comp-x"}}],
    "evidence_verified": True, "reason": "stub \\u2014 \\u6f22\\u5b57"}}
envelope = {{"type": "result", "subtype": "success", "result": json.dumps(verdict, ensure_ascii=False),
            "num_turns": 1}}
sys.stdout.buffer.write(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
"""

_DRIVER = """
import json, sys
sys.path.insert(0, {meta!r})
import {module} as mod
prompt = json.loads(sys.argv[1]) if sys.argv[1].startswith('"') else open(sys.argv[1], encoding="utf-8").read()
parsed, err = mod.{func}(prompt, 60)
sys.stdout.write(json.dumps({{"err": err, "parsed": parsed}}, ensure_ascii=True) + "\\n")
"""

LAUNCHERS = [("audit_spawn", "run_claude_auditor"), ("verification_arbiter_spawn", "run_claude_arbiter")]


def _stub(tmp_path: Path) -> Path:
    stub = tmp_path / "bin" / "claude"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(_STUB.format(python=sys.executable), encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _launch(tmp_path: Path, module: str, func: str, prompt_arg: str, *, locale_c: bool = True):
    stub = _stub(tmp_path)
    log = tmp_path / "stub.jsonl"
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    runtime = tmp_path / "xdg"
    runtime.mkdir(mode=0o700, exist_ok=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER.format(meta=str(_META), module=module, func=func), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "PYTHON"))}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_RUNTIME_DIR=str(runtime),
               AUDIT_CLAUDE_BIN=str(stub), STUB_LOG=str(log))
    if locale_c:
        env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
    proc = subprocess.run([sys.executable, str(driver), prompt_arg], cwd=str(cwd), env=env,
                          capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls


def test_control_the_parent_really_runs_with_an_ascii_locale_codec(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "PYTHON"))}
    env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
    out = subprocess.run([sys.executable, "-c", "import locale; print(locale.getpreferredencoding(False))"],
                         env=env, capture_output=True, text=True, timeout=30).stdout.strip()
    assert out.lower().replace("-", "") in ("ansi_x3.41968", "ascii", "usascii"), out


@_POSIX_ONLY
@pytest.mark.parametrize("module, func", LAUNCHERS)
def test_a_non_ascii_prompt_reaches_the_cli_as_utf8_under_a_c_locale(tmp_path: Path, module: str,
                                                                     func: str) -> None:
    proc, calls = _launch(tmp_path, module, func, json.dumps(NON_ASCII_PROMPT))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    result = json.loads(proc.stdout.decode("ascii").strip().splitlines()[-1])
    assert result["err"] is None, result
    (call,) = calls
    assert call["stdin_text"] == NON_ASCII_PROMPT          # whole, byte-exact UTF-8
    assert call["stdin_eof"] is True
    assert NON_ASCII_PROMPT not in call["argv"]
    # The non-ASCII verdict text survived the decode side too.
    assert "漢" in json.dumps(result["parsed"], ensure_ascii=False)


@_POSIX_ONLY
def test_290_sibling_an_audit_prompt_over_max_arg_strlen_reaches_the_cli_on_stdin(tmp_path: Path) -> None:
    """B regression: a 200,000-byte prompt launches, arrives whole on stdin, and argv stays
    small. CONTROL: the same prompt as an argv string is E2BIG on this host."""
    big = "x" * 200_000
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(big, encoding="utf-8")
    proc, calls = _launch(tmp_path, "audit_spawn", "run_claude_auditor", str(prompt_file), locale_c=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    result = json.loads(proc.stdout.decode("ascii").strip().splitlines()[-1])
    assert result["err"] is None, result
    (call,) = calls
    assert call["stdin_len"] == len(big)
    assert call["stdin_eof"] is True
    assert sum(len(a) for a in call["argv"]) < 1000
    with pytest.raises(OSError) as ctx:
        subprocess.run([str(_stub(tmp_path)), "-p", big], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=30,
                       env=dict(os.environ, STUB_LOG=str(tmp_path / "control.jsonl")))
    assert ctx.value.errno == 7  # E2BIG


# --------------------------------------------------------------------------- #
# #291 fix round 2, N2 -- the CODEX audit arm takes its prompt on stdin too
# --------------------------------------------------------------------------- #
_CODEX_STUB = """#!{python}
import json, os, select, sys

def drain_stdin():
    data = b""
    try:
        while True:
            ready, _, _ = select.select([0], [], [], 1.0)
            if not ready:
                return data, False
            chunk = os.read(0, 65536)
            if chunk == b"":
                return data, True
            data += chunk
    except OSError:
        return data, False

data, eof = drain_stdin()
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "stdin_eof": eof, "stdin_len": len(data),
                         "stdin_text": data.decode("utf-8", "replace")}}) + "\\n")
verdict = {{"verdict": "pass", "structured_disagreements": [
    {{"point": "p1", "severity": "minor", "location": "comp-x"}},
    {{"point": "p2", "severity": "minor", "location": "comp-x"}},
    {{"point": "p3", "severity": "moderate", "location": "comp-x"}}],
    "evidence_verified": True, "reason": "stub"}}
sys.stdout.write(json.dumps(verdict) + "\\n")
"""


def _launch_codex(tmp_path: Path, prompt_arg: str, *, locale_c: bool = False):
    stub = tmp_path / "bin" / "codex"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(_CODEX_STUB.format(python=sys.executable), encoding="utf-8")
    stub.chmod(0o755)
    log = tmp_path / "codex.jsonl"
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    runtime = tmp_path / "xdg"
    runtime.mkdir(mode=0o700, exist_ok=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER.format(meta=str(_META), module="audit_spawn", func="run_codex_auditor"),
                      encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "PYTHON"))}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_RUNTIME_DIR=str(runtime),
               AUDIT_CODEX_BIN=str(stub), STUB_LOG=str(log))
    if locale_c:
        env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
    proc = subprocess.run([sys.executable, str(driver), prompt_arg], cwd=str(cwd), env=env,
                          capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls, stub


@_POSIX_ONLY
def test_n2_a_codex_audit_prompt_over_max_arg_strlen_reaches_codex_on_stdin(tmp_path: Path) -> None:
    """N2 regression: a 200,000-byte prompt used to be argv -> OSError E2BIG -> a GAP
    (AUDIT_UNAVAILABLE, no substitute) on every attempt. It now arrives whole on stdin with
    `-` as the PROMPT positional. CONTROL: the same prompt as an argv string is E2BIG."""
    big = "y" * 200_000
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(big, encoding="utf-8")
    proc, calls, stub = _launch_codex(tmp_path, str(prompt_file))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    result = json.loads(proc.stdout.decode("ascii").strip().splitlines()[-1])
    assert result["err"] is None, result
    assert result["parsed"]["verdict"] == "pass"
    (call,) = calls
    assert call["argv"][-1] == "-"
    assert call["stdin_len"] == len(big)
    assert call["stdin_eof"] is True
    assert sum(len(a) for a in call["argv"]) < 1000
    with pytest.raises(OSError) as ctx:
        subprocess.run([str(stub), "exec", big], stdin=subprocess.DEVNULL, capture_output=True,
                       timeout=30, env=dict(os.environ, STUB_LOG=str(tmp_path / "control.jsonl")))
    assert ctx.value.errno == 7  # E2BIG


@_POSIX_ONLY
def test_n2_a_non_ascii_codex_prompt_reaches_codex_as_utf8_under_a_c_locale(tmp_path: Path) -> None:
    proc, calls, _ = _launch_codex(tmp_path, json.dumps(NON_ASCII_PROMPT), locale_c=True)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    result = json.loads(proc.stdout.decode("ascii").strip().splitlines()[-1])
    assert result["err"] is None, result
    (call,) = calls
    assert call["stdin_text"] == NON_ASCII_PROMPT
    assert call["stdin_eof"] is True
    assert NON_ASCII_PROMPT not in call["argv"]
