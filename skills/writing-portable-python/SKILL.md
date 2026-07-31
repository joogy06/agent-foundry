---
name: writing-portable-python
description: Use when writing or reviewing ANY Python that could run on an operating system other than the one you are on — harness scripts, skill scripts, hooks, installers, CLIs. Covers the failures that are invisible on the machine that wrote them, in the order they actually bite - platform-exclusive imports that fail at IMPORT and take down every caller, text I/O and console output that die on a cp1252 Windows console, path rendering for a TARGET os rather than the host, os.replace and file-locking semantics that differ on Windows, the missing exec bit, absent system binaries (jq/host/dig), and subprocess spawn cost that inverts the bash-is-lighter intuition. Enforced by `_meta/portability_lint.py`; this skill is the reasoning, the lint is the regression guard. Trigger on - writing a script, cross-platform, Windows, macOS, portability, "works on my machine", UnicodeEncodeError, ModuleNotFoundError fcntl, cp1252, charmap codec, file locking, atomic write, shebang.
---

# writing-portable-python

Python the language is cross-platform. **Your Python is not, and choosing Python is what makes that easy to miss.**

Every Windows failure found on 2026-07-30 was in pure Python, in a codebase that had been Python-first for months and had never once been run on Windows. None was caught by any check. All of them failed **open and silent** — exit 0, no output, indistinguishable from success.

That is the class this skill exists to prevent. It is not a style guide.

## When to use

- Writing **any** script that ships in a skill, a hook, an installer, or `_meta`
- Reviewing Python written on one OS that will run on another
- Debugging "it works here" — especially an empty output with a zero exit code
- Before porting a shell script to Python (the port is worthless if it reproduces this class)

## When NOT to use

- Application code that provably runs on one controlled OS (a container you own, a fixed server)
- Choosing between Python and another language — that is a different question

---

## The rules, in the order they bite

### 1. A platform-exclusive import fails at IMPORT, not at use

```python
import fcntl          # POSIX only — ModuleNotFoundError on Windows, at import
```

This is the worst one because of **when** it fails. The module never loads, so *every caller* dies, including callers that never touch locking. Ten modules here did this; nine were unimportable on Windows, and one of them was `claims.py` — which is why bob could not run there **in any host**.

Three guards work, and they are not equivalent:

```python
# (a) Guarded — module imports everywhere; you must handle `fcntl is None`.
try:
    import fcntl
except ImportError:
    fcntl = None

# (b) Deferred — module imports everywhere; raises only if this function is CALLED.
def rotate(path):
    import fcntl
    ...

# (c) Branched — explicit and readable when behaviour genuinely differs.
if sys.platform != "win32":
    import fcntl
```

**(b) is not a fix, it is a downgrade of severity.** The real `model_policy.py` used (b) next to an `except Exception: # never blocks resolve`, so on Windows its log rotation failed *silently* forever. Deferring converts "unimportable" into "silently broken when called" — sometimes that is what you want, but decide it rather than inherit it.

POSIX-only: `fcntl` `termios` `pwd` `grp` `resource` `posix`
Windows-only: `msvcrt` `winreg` `winsound` `_winapi`

For `fcntl` specifically, the answer is now none of (a)/(b)/(c) at your call site: **import `_meta/portable_lock.py`**, which uses (c) once, in one place, so nothing else has to. See rule 10.

### 2. Text I/O without `encoding=` uses the LOCALE codec

```python
path.write_text(text)                      # cp1252 on a Windows console
path.write_text(text, encoding="utf-8")    # correct, always
```

`install.py` wrote a file containing `←` (U+2190) with a bare `write_text()`. Python used cp1252, **opened the file (truncating it), then raised** — leaving a 0-byte file. Every placement guard was `exists() and not force`, so the empty file then read as "the user already has one" and was **never repaired by a re-run**. The layer looked configured and was inert for six weeks.

Two lessons, not one: pass `encoding=` on every `open()` / `read_text()` / `write_text()`, **and** never let `exists()` alone stand for "present and valid".

### 3. A CLI that prints non-ASCII must harden its streams

`sys.stdout` on a Windows console uses the locale codec. One emoji raises `UnicodeEncodeError`, and the observed failure is not a readable crash — `memory_primer.py` printed `🧠`, died, and **exited 0 with no output**, so the SessionStart digest simply never appeared. Its own error handler printed an emoji too, so the message announcing the failure also failed.

```python
from portable_cli import run_cli          # skills/_meta/portable_cli.py

if __name__ == "__main__":
    raise SystemExit(run_cli(main))
```

`errors="backslashreplace"`, **not** `"replace"`. Both survive; only one leaves evidence. `replace` renders the character `?`, which cannot be traced back to the site that produced it.

`PYTHONUTF8=1` in a spawned environment is defence in depth, **not** the fix — it does not help a process someone else launched.

**You can reproduce this on Linux**, which is what makes it testable at all:

```bash
PYTHONIOENCODING=cp1252 python3 your_script.py
```

### 4. Render paths for the TARGET os, never the host

`Path` is `WindowsPath` on Windows and `PosixPath` elsewhere, so **stringifying it describes the host**, not the target. A preview built to refuse to lie about macOS from Linux lied in the mirror direction from Windows, rendering `\Users\<you>\` with backslashes.

```python
from pathlib import PurePosixPath, PureWindowsPath
cls = PureWindowsPath if os_key == "windows" else PurePosixPath
```

Take an explicit `os_key`; never read `sys.platform` inside a function that describes another machine. That is also what makes the cell unit-testable without the OS it describes.

### 5. `os.replace()` fails on Windows if the destination is open

The atomic-write recipe is the same everywhere — build in memory, write a temp file **in the destination directory**, flush, `os.replace()` — but on Windows a reader still holding a handle **breaks the writer**. That surfaces nowhere else, so test it with genuinely concurrent **processes**, not threads. Six SessionStart hooks fire together here and two of them write manifests.

### 6. There is no exec bit on Windows

Windows uses the extension. Do not emulate POSIX permission bits or wrap NTFS ACLs to mimic `chmod 0755`. Record the intent in git instead:

```bash
git update-index --chmod=+x path/to/script.py
```

### 7. Shebangs: bake the interpreter you know, do not hope for PATH

For a file **you generate** (a git hook, a wrapper), `#!/usr/bin/env python3` depends on a PATH that GUI clients, IDE integrations and the Windows Store `python` alias-stub all routinely break. An installer already knows the right answer — `sys.executable` — so write it in. Git for Windows runs hooks through MSYS bash, so test the `/c/Users/...` shebang form, not `C:\Users\...`.

### 8. System binaries are not a dependency you can declare

`jq`, `host`, `dig` are **absent on Windows** and no `requirements.txt` can express them. Two SessionStart probes died at exit 127 with `jq: command not found` and wrote nothing, so two whole harness layers sat inert while looking wired. An AST scan of Python imports cannot see this class — only an explicit system-command manifest can.

Prefer stdlib: `json` over `jq`, `socket.getaddrinfo` over `host`/`dig`, `shutil`/`pathlib` over `rsync` for anything but a genuine mirror-with-delete.

### 9. Spawn cost inverts the "bash is lighter" intuition

Measured, both hosts:

| | Linux | Windows |
|---|---|---|
| bash start | ~1.1 ms | — |
| python start (bare) | ~9 ms | ~66 ms |
| python + stdlib imports | ~18.5 ms | ~128 ms |
| **one subprocess spawn** | cheap | **~41.6 ms** |

A bash script spawning 73 subprocesses pays ~3 seconds on Windows before doing any work; the Python port pays 128 ms once. But a spawn-light script gets **slower** in Python on Linux. So the porting criterion is **spawn count and criticality**, not language preference.

### 10. File locks are not portable, and the differences are not symmetric

Do not reach for `fcntl` or `msvcrt` directly — use `_meta/portable_lock.py`. This rule is what it encapsulates, and every line of it came from a defect.

**`msvcrt.locking()` locks `nbytes` from the CURRENT file position.** `flock` locks the whole file regardless of position, so POSIX code never has to think about this. Port it naively and you lock a range nobody else contends for — the call succeeds, no exception is raised, and the lock excludes **nothing**. Seek the *descriptor* to 0 first and restore it after:

```python
pos = os.lseek(fd, 0, os.SEEK_CUR)     # os.lseek, not fh.seek — msvcrt reads the
os.lseek(fd, 0, os.SEEK_SET)           # DESCRIPTOR position, and going through the
try:                                    # buffered layer would force a flush and can
    msvcrt.locking(fd, mode, 1)         # move the caller's logical position
finally:
    os.lseek(fd, pos, os.SEEK_SET)
```

**Never open a lock file `"w"`.** The truncation happens *at open*, before any lock is taken. On Windows locks are **mandatory**, so the open itself fails while another process holds the range; on POSIX it silently blanks a file someone is mid-write on. Six call sites here did this. Use `"a+"` — it creates without truncating.

**There is no shared lock on Windows.** `msvcrt` has no `LOCK_SH` equivalent, so a shared lock must degrade to exclusive. That costs reader concurrency and buys nothing away from correctness — taking a *stronger* lock than asked is safe. Degrade inside the adapter; raising `NotImplementedError` instead just pushes a platform branch into every caller, which is what the adapter exists to prevent.

**Normalise contention to one exception type.** POSIX reports it as `EAGAIN`/`EWOULDBLOCK`, sometimes `EACCES`. CPython maps `EAGAIN` to `BlockingIOError` for free but maps `EACCES` to `PermissionError` — a class no caller catches, so an ordinary contended lock surfaces as a hard failure.

**What survives a process dying is the property to decide on deliberately.** `flock` and Windows byte-range locks both release when the handle closes, and the handle closes when the process dies. A lock built on `os.mkdir` does **not** — it needs stale-lock detection by PID and timestamp, which is a new failure mode. That difference is why #249 chose adapters over directory locking.

**Process locks are not thread locks.** Neither `flock` nor `msvcrt` serialises threads sharing one descriptor. If you need that, you need a `threading.Lock` as well.

---

## Enforcement

`portability_lint.py` guards regressions; this skill explains what to do instead.

```bash
python3 ~/.claude/skills/_meta/portability_lint.py lint <tree> --summary
python3 ~/.claude/skills/_meta/portability_lint.py check <files>     # pre-commit
```

| Code | | Rule |
|---|---|---|
| E001 | blocks | unguarded platform-exclusive import (rule 1) |
| W002 | advises | text I/O with no `encoding=` (rule 2) |
| W003 | advises | entrypoint emits non-ASCII without hardening (rule 3) |

It is **AST-based on purpose.** Regex guards here have twice flagged prose *describing* the pattern they hunted — a test searching for `pip` matched a help string reading *"the skill never pip-installs at runtime"*. Rules 4–9 are not lintable today; they are review checks.

## The honest limit

Rules 5 and 7 are **reasoned, not verified** — no Mac has run any of this, and the Windows shebang form has not been tested under a GUI git client. Declared is not verified. Say which one you have.

## See also

- `_meta/portable_cli.py` — the shared stream-hardening wrapper
- `_meta/portability_lint.py` — the enforcement arm
- `windows_laptop_message.md` — the session that produced every rule above
