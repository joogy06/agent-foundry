#!/usr/bin/env python3
"""pre-commit hook, in Python (#250) -- refuse a commit that stages a problem.

Six arms, in the order a blocker should stop you. Arms 1, 2 and 5 are unchanged
from the bash hook this replaces; arms 3 (#281), 4 (#344) and 6 (#350) are python-only:

  1. SKILL.md frontmatter (#237)     -- E blocks, W advises
  2. portability lint (#249/#251)    -- E blocks, W advises
  3. REVIEW-BY markers (#281)        -- E blocks, W advises
  4. skill standard audit (#344)     -- SA-E blocks (a skill on the conformant list),
                                        SA-W advises (every other skill)
  5. secrets scan, --staged          -- any finding blocks
  6. intake check (#350)             -- only in a repo that tracks the intake ledger:
                                        a block-rule hit (H1 to H9, H11) with no exception
                                        blocks, a new unit with no ledger entry blocks.
                                        H7 includes the layout of a git repository under
                                        any name, judged over the staged files beside the
                                        paths the index already tracks

WHY IT IS PYTHON NOW
--------------------
Keeping bash solely for the security hooks preserves exactly the dependency class
#261 exists to remove. The Windows laptop had no gate at all (#250): `.git/hooks`
held only samples, so every commit and push there was unscanned -- and a bash hook
that Git-for-Windows may or may not run is not the shape to fix that with.

WHAT IS DELIBERATELY IDENTICAL
------------------------------
The observable contract, pinned per-scenario in tests/hooks/. Exit codes and the
BLOCKED/WARN decisions were frozen as golden fixtures BEFORE this file was written
(#262), and the suite runs every scenario against BOTH implementations. That is
what makes "the same hook" a measured claim rather than a hopeful one.

Two behaviours are load-bearing and easy to lose in a port:

  * MISSING SCANNER FAILS CLOSED. An enforcement hook that silently skips is worse
    than no hook: it advertises protection that is not there. `--no-verify` remains
    the deliberate escape hatch.
  * WARNINGS DO NOT BLOCK. A check that fires on ~600 pre-existing sites you did
    not touch is how people learn to reach for `--no-verify`, which costs more than
    the warnings buy.

STREAM HARDENING IS NOT OPTIONAL HERE
-------------------------------------
This hook PRINTS the output of the linters, and that output contains em-dashes. On
a cp1252 Windows console an unhardened write raises UnicodeEncodeError -- and #251's
signature failure was exit 0 with NO output, which is indistinguishable from a clean
run. A secrets hook that silently prints nothing and exits 0 is the worst possible
failure mode, so the streams are hardened before anything is written.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "# managed-by: foundry-lab/skills/secret-scanning/hooks/pre_commit.py"

# Frontmatter lint indents its findings; portability lint does not. Both are
# compiled with the MULTILINE FLAG rather than passed as a positional argument --
# `Pattern.search(string, re.MULTILINE)` passes 8 as POS and silently disables the
# anchor, which is precisely how a CRITICAL secrets rule sat inert (#272).
FRONTMATTER_ERROR = re.compile(r"^  E[0-9]", re.MULTILINE)
FRONTMATTER_WARN = re.compile(r"^  W[0-9]", re.MULTILINE)
PORTABILITY_ERROR = re.compile(r"^E[0-9]", re.MULTILINE)
PORTABILITY_WARN = re.compile(r"^W[0-9]", re.MULTILINE)
# review_by_lint prefixes its findings `RB-`, so neither arm above can match them.
REVIEW_BY_ERROR = re.compile(r"^RB-E[0-9]", re.MULTILINE)
REVIEW_BY_WARN = re.compile(r"^RB-W[0-9]", re.MULTILINE)
# skill_audit prefixes `SA-`: SA-E for a skill on the conformant list, SA-W for any other.
SKILL_AUDIT_ERROR = re.compile(r"^SA-E ", re.MULTILINE)
SKILL_AUDIT_WARN = re.compile(r"^SA-W ", re.MULTILINE)


def _harden_streams() -> None:
    """UTF-8 with backslashreplace, before a single byte is written.

    `backslashreplace`, never `replace`: both survive the encode, but `replace`
    yields '?' and destroys the evidence needed to find the offending site.
    Uses portable_cli when it resolves, and degrades to the same call inline when
    it does not -- a hook must not depend on the harness being installed.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass  # a stream without reconfigure (pytest capture, a pipe) is fine


def _err(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def repo_root() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out) if out else None


def resolve_helper(root: Path, repo_rel: str, home_rel: str) -> Path | None:
    """Repo copy first, then the installed harness copy.

    Repo-first matters: a repo that vendors its own scanner must be gated by THAT
    one, not by whatever happens to be in the developer's home tree.
    """
    candidate = root / repo_rel
    if candidate.is_file():
        return candidate
    home = Path(os.path.expanduser("~")) / ".claude" / home_rel
    return home if home.is_file() else None


def staged_paths(root: Path, suffix: str = "", name: str = "",
                 diff_filter: str = "ACM", no_renames: bool = False,
                 strict: bool = False) -> list[str]:
    """Staged paths, NUL-separated (`-z`) so core.quotePath never quotes a non-ASCII name
    into a string no file has. Decoded with surrogateescape: undecodable bytes survive the
    round trip back to git. The suffix match ignores case (`.MD` is markdown too).

    `no_renames` lists a staged rename as a delete plus an add, so the path a file LEFT is
    named too (git names a rename by its destination only).

    `strict` raises OSError when git cannot list the paths, for a caller that must tell
    "nothing staged" from "could not look" (the default reads both as an empty list)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z",
             f"--diff-filter={diff_filter}"] + (["--no-renames"] if no_renames else []),
            capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        if strict:
            raise OSError("git could not list the staged paths")
        return []
    hits = []
    for line in out.decode("utf-8", errors="surrogateescape").split("\0"):
        if not line:
            continue
        if name and Path(line).name != name:
            continue
        if suffix and not line.lower().endswith(suffix.lower()):
            continue
        hits.append(line)
    return hits


#: Exit code _run reports when a lint subprocess ran past its timeout.
EXIT_TIMED_OUT = 124


def _run(cmd: list[str], stdin_data: str | None = None,
         timeout: float | None = None) -> tuple[int, str]:
    try:
        if stdin_data is None:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, input=stdin_data,
                                  encoding="utf-8", errors="surrogateescape", timeout=timeout)
    except subprocess.TimeoutExpired:
        return EXIT_TIMED_OUT, f"{cmd[1] if len(cmd) > 1 else cmd[0]} timed out after {timeout}s"
    except OSError as exc:
        return 127, f"could not execute {cmd[0]}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


#: Upper bound on a fail-closed lint arm's run (seconds).
FAIL_CLOSED_TIMEOUT_S = 120

# Exit codes that mean "the linter could not run", not "the linter found nothing":
# 127 is _run's could-not-execute; 3 is review_by_lint's missing-dependency exit.
UNAVAILABLE_RCS = (127, 3)


def run_lint_arm(root: Path, *, repo_rel: str, home_rel: str, paths: list[str],
                 error_re: re.Pattern, warn_re: re.Pattern,
                 blocked_message: list[str], extra_args: tuple = (),
                 fail_closed: bool = False, paths_on_stdin: bool = False) -> int:
    """One lint arm. Returns 1 to block, 0 to continue.

    A missing linter is NOT a block. Unlike the scanner, these arms are quality
    gates rather than the security gate, and refusing every commit in a repo that
    does not vendor them would make the hook unusable where it is most needed.

    `fail_closed` (the REVIEW-BY arm, #281, and the skill audit arm, #344): a linter that is present but exits
    non-zero without printing a single error finding crashed or was misused, and
    that is a block -- otherwise one traceback silently passes every staged file. Except
    an UNAVAILABLE linter (exit 3: its own dependency is missing; 127: it could not be
    executed): that is the missing-linter case, a visible warning and not a block.

    `--` always precedes the paths, so a staged path that starts with `-` is a path and not
    an option. `paths_on_stdin` sends them NUL-separated on stdin (`--paths-from -`) so a
    large commit cannot exceed a command-line length limit (32k on Windows).
    """
    if not paths:
        return 0
    linter = resolve_helper(root, repo_rel, home_rel)
    if linter is None:
        return 0
    # A fail-closed arm must also never HANG a commit (post-review m1): bounded runtime.
    timeout = FAIL_CLOSED_TIMEOUT_S if fail_closed else None
    if paths_on_stdin:
        # Trailing NUL: a lone path containing a newline stays one path (post-review n1).
        rc, out = _run([sys.executable, str(linter), "check", *extra_args,
                        "--paths-from", "-"], stdin_data="\0".join(paths) + "\0",
                       timeout=timeout)
    else:
        rc, out = _run([sys.executable, str(linter), "check", *extra_args, "--", *paths],
                       timeout=timeout)
    if error_re.search(out):
        _err(out)
        _err("")
        for line in blocked_message:
            _err(line.format(linter=linter, root=root) if fail_closed else line)
        return 1
    if fail_closed and rc in UNAVAILABLE_RCS:
        _err(out)
        _err(f"pre-commit: WARN - {linter} is unavailable (exit {rc}); "
             "these files were NOT checked.")
        return 0
    if fail_closed and rc == EXIT_TIMED_OUT:
        _err(out)
        _err("")
        _err(f"pre-commit: BLOCKED - {linter.name} did not finish in {FAIL_CLOSED_TIMEOUT_S}s;")
        _err("  failing closed rather than passing files it could not check.")
        _err("  Bypass deliberately with: git commit --no-verify")
        return 1
    if fail_closed and rc != 0:
        _err(out)
        _err("")
        _err(f"pre-commit: BLOCKED - {linter.name} exited {rc} without a finding;")
        _err("  failing closed rather than passing files it could not check.")
        _err("  Bypass deliberately with: git commit --no-verify")
        return 1
    if warn_re.search(out):
        _err(out)
    return 0


# --- Arm 6: the intake check (#350) -------------------------------------------
INTAKE_LEDGER_REL = "skills/_meta/intake-ledger.json"
INTAKE_HELPER_REL = "skills/intake-scan/scripts/intake_ledger.py"
INTAKE_OVERRIDES_REL = "intake/overrides.jsonl"
INTAKE_ROOTS = ("skills", "agents", "commands", "workflows")
#: Above this many staged paths the arm reads the four roots whole and filters, so a
#: large commit cannot exceed a command-line length limit (32k on Windows).
INTAKE_MAX_PATHSPECS = 100
INTAKE_MAX_LISTED = 20
#: A path made of these characters only is printed; any other prints as a stand-in.
_INTAKE_PLAIN_PATH = re.compile(r"^[A-Za-z0-9._/@+-]{1,200}$")


class _IntakeStep(Exception):
    """A step of the intake arm that could not be done. The message is fixed text of ours."""


def _git_bytes(root: Path, *args: str) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except OSError:
        return 127, b""
    return proc.returncode, proc.stdout


def _index_blob(root: Path, rel: str) -> bytes | None:
    """The staged content of one path, or None when the index does not hold it."""
    rc, _out = _git_bytes(root, "cat-file", "-e", ":" + rel)
    if rc != 0:
        return None
    rc, out = _git_bytes(root, "cat-file", "blob", ":" + rel)
    if rc != 0:
        raise _IntakeStep("git could not read the staged copy of " + rel)
    return out


def _intake_ledger_state(root: Path) -> str:
    """`staged` when the index holds the ledger, `removed` when HEAD holds it and the
    index does not (this commit deletes it), `absent` in a repo that never tracked one."""
    rc, _out = _git_bytes(root, "cat-file", "-e", ":" + INTAKE_LEDGER_REL)
    if rc == 0:
        return "staged"
    rc, _out = _git_bytes(root, "cat-file", "-e", "HEAD:" + INTAKE_LEDGER_REL)
    return "removed" if rc == 0 else "absent"


def _load_intake_helper(path: Path):
    """The ledger module, loaded by path into this process. It loads the rule set from its
    own directory the same way, so no scanner subprocess is started."""
    name = "_foundry_intake_ledger"
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise _IntakeStep("the helper could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _staged_overrides(il, root: Path) -> list:
    """The override log as STAGED. The helper reads it from a root directory, so the staged
    blob is written into a temporary one."""
    blob = _index_blob(root, INTAKE_OVERRIDES_REL)
    if blob is None:
        return []
    with tempfile.TemporaryDirectory(prefix="intake-arm-") as tmp:
        target = Path(tmp) / INTAKE_OVERRIDES_REL
        target.parent.mkdir(parents=True)
        target.write_bytes(blob)
        return il.read_overrides(tmp)


def _intake_show(path: str, il=None, doc=None, sha256: str = "") -> str:
    """A staged path as it may be printed. The helper decides when it can (a file inside
    an adopted unit shows as its unit and a digest: its name was chosen by the source)."""
    show = getattr(il, "show_path", None)
    if show is not None:
        return show(doc, path, sha256)
    return path if _INTAKE_PLAIN_PATH.match(path) else "(name withheld)"


def _intake_blocked(step: str, detail: str) -> int:
    _err("pre-commit: BLOCKED - the intake check could not run.")
    _err(f"  failing step: {step}")
    if detail:
        _err(f"  {detail}")
    _err(f"  This repo tracks {INTAKE_LEDGER_REL}, so the check is required here;")
    _err("  failing closed rather than passing files it could not check.")
    return 1


def run_intake_arm(root: Path) -> int:
    """Arm 6. Returns 1 to block, 0 to continue.

    Judges what the commit will hold: the staged blobs, the staged ledger and the staged
    override log, never the working tree. Only the paths this commit adds or changes are
    read; a deletion is always allowed. The other tracked paths are listed (not read) so
    that a staged file which completes the layout of a git repository is seen as that.
    """
    state = _intake_ledger_state(root)
    if state == "absent":
        return 0          # not a repo that uses the ledger: skipped, silently
    if state == "removed":
        _err("pre-commit: BLOCKED - this commit removes the intake ledger")
        _err(f"  ({INTAKE_LEDGER_REL}), which would switch the intake check off.")
        return 1
    try:
        listed = staged_paths(root, diff_filter="ACMRT", no_renames=True, strict=True)
    except OSError:
        # "Could not look" is not "nothing staged": the arm fails closed here too.
        return _intake_blocked("listing the staged paths", "git could not list the staged paths")
    staged = [p for p in listed if "/" in p and p.split("/", 1)[0] in INTAKE_ROOTS]
    if not staged:
        return 0
    wanted = set(staged)

    step = "finding the intake helper"
    saved_literal = os.environ.get("GIT_LITERAL_PATHSPECS")
    try:
        helper = resolve_helper(root, INTAKE_HELPER_REL, INTAKE_HELPER_REL)
        if helper is None:
            return _intake_blocked(step, f"expected: $repo/{INTAKE_HELPER_REL} or "
                                         f"~/.claude/{INTAKE_HELPER_REL}")
        step = "loading the intake helper"
        il = _load_intake_helper(helper)
        # A staged path is a path, never a pattern, in every git call the helper makes.
        os.environ["GIT_LITERAL_PATHSPECS"] = "1"
        step = "reading the staged ledger"
        blob = _index_blob(root, INTAKE_LEDGER_REL)
        if blob is None:
            raise _IntakeStep("the staged ledger could not be read")
        doc = il.validate(json.loads(blob.decode("utf-8")))
        overrides = _staged_overrides(il, root)
        step = "reading the staged files"
        prefixes = sorted(wanted) if len(wanted) <= INTAKE_MAX_PATHSPECS else list(INTAKE_ROOTS)
        items = [item for item in il.read_items(str(root), il.SOURCE_INDEX, prefixes)
                 if item.path in wanted]
        if {item.path for item in items} != wanted:
            raise _IntakeStep("a staged file could not be read from the index")
        step = "listing the tracked paths"
        # A directory is a git repository by what it holds (HEAD beside objects and refs),
        # so a staged file is judged beside every path the index already has.
        rc, listing = _git_bytes(root, "ls-files", "-z", "--", *INTAKE_ROOTS)
        if rc != 0:
            raise _IntakeStep("git could not list the tracked paths")
        tracked = [chunk.decode("utf-8", "surrogateescape") for chunk in listing.split(b"\x00") if chunk]
        step = "running the block rules"
        hits = il.unexcepted_hits(
            doc, items, overrides=overrides,
            unit_digest=lambda unit: il.unit_tree_digest(str(root), unit, il.SOURCE_INDEX),
            context_paths=tracked)
        missing = il.units_missing_entry(doc, wanted)
        described = []
        for hit in hits[:INTAKE_MAX_LISTED]:
            try:
                text = il._rules().describe(hit.rule_id)
            except KeyError:
                text = "a block rule"
            where = ("(the staged file set)" if hit.path == "-"
                     else f"{_intake_show(hit.path, il, doc, hit.sha256)}:{hit.line}")
            described.append(f"  {hit.rule_id}  {where}  {text}")
    except _IntakeStep as exc:
        return _intake_blocked(step, str(exc))
    except Exception as exc:  # a crashing helper blocks, with the step named
        fixed = str(exc) if type(exc).__module__ == "_foundry_intake_ledger" else ""
        return _intake_blocked(step, (fixed + " " if fixed else "") + f"({type(exc).__name__})")
    finally:
        if saved_literal is None:
            os.environ.pop("GIT_LITERAL_PATHSPECS", None)
        else:
            os.environ["GIT_LITERAL_PATHSPECS"] = saved_literal

    if not hits and not missing:
        return 0
    cli = "python3 skills/intake-scan/scripts/intake.py"
    if hits:
        _err(f"pre-commit: BLOCKED - {len(hits)} staged block-rule hit(s) have no exception.")
        for line in described:
            _err(line)
        if len(hits) > INTAKE_MAX_LISTED:
            _err(f"  (+{len(hits) - INTAKE_MAX_LISTED} more)")
        _err("  Fix the file. If the hit is a documented example, a person records an exception:")
        _err(f"    {cli} except <rule> <path> --reason \"...\"")
        _err("  An exception is keyed to the file's content and stops matching when it changes.")
    if missing:
        _err(f"pre-commit: BLOCKED - {len(missing)} staged unit(s) have no intake ledger entry.")
        for unit in missing[:INTAKE_MAX_LISTED]:
            _err(f"  {_intake_show(unit)}")
        if len(missing) > INTAKE_MAX_LISTED:
            _err(f"  (+{len(missing) - INTAKE_MAX_LISTED} more)")
        _err(f"  Written here: {cli} scan --local <unit>")
        _err(f"  Brought in:   {cli} scan <source>, then adopt <id> --to <unit>")
        _err(f"  Then stage {INTAKE_LEDGER_REL} and intake/records/ with the unit.")
    return 1


def main() -> int:
    _harden_streams()

    root = repo_root()
    if root is None:
        return 0  # not a git repo: nothing to gate, and never wedge the caller

    # --- Arm 1: SKILL.md frontmatter (#237) ---------------------------------
    # Claude Code's loader tolerates YAML that yaml.safe_load and Codex reject, so
    # a broken skill is invisible here and MISSING there. Landed twice before.
    rc = run_lint_arm(
        root,
        repo_rel="skills/_meta/frontmatter_lint.py",
        home_rel="skills/_meta/frontmatter_lint.py",
        paths=staged_paths(root, name="SKILL.md"),
        error_re=FRONTMATTER_ERROR, warn_re=FRONTMATTER_WARN,
        blocked_message=[
            "pre-commit: BLOCKED - a staged SKILL.md has invalid frontmatter.",
            "  Commonest cause: an unquoted ': ' inside a value. Quote the value.",
            "  Bypass deliberately with: git commit --no-verify",
        ])
    if rc:
        return rc

    # --- Arm 2: portability lint (#249/#251) --------------------------------
    # Staged files ONLY, deliberately. A tree-wide gate would block every commit
    # on pre-existing findings, and a check that fires on work you did not do is
    # how people learn to reach for --no-verify.
    rc = run_lint_arm(
        root,
        repo_rel="skills/_meta/portability_lint.py",
        home_rel="skills/_meta/portability_lint.py",
        paths=staged_paths(root, suffix=".py"),
        error_re=PORTABILITY_ERROR, warn_re=PORTABILITY_WARN,
        blocked_message=[
            "pre-commit: BLOCKED - a staged .py breaks on another platform.",
            "  E001: guard the import (try/except ImportError), defer it into the",
            "  function, or branch on sys.platform. An unguarded platform-only import",
            "  fails at IMPORT, so it takes down every caller, not just the code path.",
            "  Bypass deliberately with: git commit --no-verify",
        ])
    if rc:
        return rc

    # --- Arm 3: dated REVIEW-BY markers (#281) ------------------------------
    # A prose `REVIEW-BY: <date>` with no matching FRESHNESS:v1 anchor is a deadline
    # freshness.py never sees -- 22 of them accumulated while check-deadlines said
    # "none due". Staged .md only, for the same reason as the portability arm --
    # and the STAGED BLOB of each (`check --staged`), not the working tree: a
    # marker staged with its FRESHNESS block left unstaged must not pass. Renames
    # (R) are included, or `git mv` + edit would slip past. Fails closed on a
    # linter crash; a MISSING or UNAVAILABLE linter still does not block (same as
    # arms 1-2), but says so. The linter judges only skills/ agents/ workflows/
    # (the harvester's roots); every other staged .md passes through it untouched.
    rc = run_lint_arm(
        root,
        repo_rel="skills/_meta/review_by_lint.py",
        home_rel="skills/_meta/review_by_lint.py",
        # Only the harvester's roots, filtered HERE too: a linter that crashes or is version-
        # skewed can then never block a commit that stages only tasks.md / docs/ (post-review).
        # T included: a symlink replaced by a real file is staged as a type change.
        paths=[p for p in staged_paths(root, suffix=".md", diff_filter="ACMRT")
               if p.split("/", 1)[0] in ("skills", "agents", "workflows")],
        extra_args=("--staged", "--repo", str(root)),
        fail_closed=True, paths_on_stdin=True,
        error_re=REVIEW_BY_ERROR, warn_re=REVIEW_BY_WARN,
        blocked_message=[
            "pre-commit: BLOCKED - a staged .md has a dated REVIEW-BY marker that",
            "  freshness.py cannot see. Keep the prose marker and add a FRESHNESS:v1",
            "  block with a matching anchor, e.g.",
            "    <!-- FRESHNESS:v1",
            "    anchors:",
            "      - kind: date_review",
            "        subject: <what-is-reviewed>",
            "        review_by: \"<the marker's date; YYYY-MM means its last day>\"",
            "    -->",
            "  If the line is prose, or mentions ANOTHER file's marker, append",
            "    <!-- review-by: mention -->   to that line instead (never invent a deadline).",
            "  Check with: python3 {linter} check --repo {root} <file>",
            "  Bypass deliberately with: git commit --no-verify (this also skips the secrets scan)",
        ])
    if rc:
        return rc

    # --- Arm 4: skill standard audit (#344) ---------------------------------
    # Staged paths under skills/ only; the auditor maps each to its skill and audits
    # the whole skill, because its rules are about the skill (is this reference named
    # in SKILL.md, how long is SKILL.md), not about one blob. It reads the skill, the
    # conformant list and the exemption list from the git INDEX -- what this commit
    # will hold -- so an unstaged edit can neither hide a staged failure nor change
    # which skills are held to the rules (#344 fix round 1).
    # A fail BLOCKS only for a skill named in skills/_meta/standard-conformant.txt of
    # THIS repo -- the skills that have been brought to the standard and must stay
    # there. For every other skill the same finding is a warning, by the rule in this
    # file's header: a check that blocks on findings you did not introduce teaches
    # --no-verify. D included: deleting a reference or a SKILL.md line can break a
    # listed skill too; --no-renames for the same reason, since a file renamed OUT of a
    # skill is otherwise listed by its destination alone and the skill it left is never
    # audited (#344 fix round 2; this arm only). Fails closed on an auditor crash; a
    # MISSING auditor does not block (same as arms 1-3).
    rc = run_lint_arm(
        root,
        repo_rel="skills/_meta/skill_audit.py",
        home_rel="skills/_meta/skill_audit.py",
        paths=[p for p in staged_paths(root, diff_filter="ACMRTD", no_renames=True)
               if p.split("/", 1)[0] == "skills"],
        extra_args=("--repo", str(root)),
        fail_closed=True, paths_on_stdin=True,
        error_re=SKILL_AUDIT_ERROR, warn_re=SKILL_AUDIT_WARN,
        blocked_message=[
            "pre-commit: BLOCKED - a staged change leaves a skill on the conformant list",
            "  (skills/_meta/standard-conformant.txt) failing the skill standard. Each SA-E",
            "  line above names the rule (A1-A11), the file and what is wrong.",
            "  Check with: python3 {linter} audit --root {root}/skills --only <skill>",
            "  Bypass deliberately with: git commit --no-verify (this also skips the secrets scan)",
        ])
    if rc:
        return rc

    # --- Arm 5: secrets scan (the security gate) ----------------------------
    scanner = resolve_helper(
        root,
        "scripts/secrets-scan.py",
        "skills/secret-scanning/scripts/secrets-scan.py")
    if scanner is None:
        # FAIL CLOSED. The installer refuses to install without a scanner, so
        # reaching here means it was REMOVED afterwards.
        _err("pre-commit: BLOCKED - secrets scanner missing.")
        _err("  expected: $repo/scripts/secrets-scan.py or "
             "~/.claude/skills/secret-scanning/scripts/secrets-scan.py")
        _err("  Restore it, or bypass deliberately with: git commit --no-verify")
        return 1

    status, out = _run([sys.executable, str(scanner), str(root), "--staged"])
    if out.strip():
        _err(out.rstrip())
    if status != 0:
        _err("")
        _err("pre-commit: BLOCKED - staged content matches a secret pattern.")
        _err("  Move the value to ~/.secrets/<project>.env (0600) and load it at runtime.")
        _err("  See: skills/secret-scanning/references/storage-standard.md")
        _err("  If the credential was ever committed, ROTATE it - scrubbing is not rotation.")
    if status:
        return status

    # --- Arm 6: intake check (#350) -----------------------------------------
    # Active only in a repo that tracks skills/_meta/intake-ledger.json; any other repo
    # skips it silently, so a consumer project that installs this hook is unaffected.
    # With the ledger tracked, a missing or crashing helper BLOCKS and names the step
    # that failed. The staged blobs under skills/, agents/, commands/ and workflows/ are
    # run through block rules H1 to H9 and H11 in this process (H7 with its repository-layout
    # check, which reads the tracked paths too); the full scan (third-party scanners, H10)
    # belongs to `intake.py scan`, not to a commit.
    return run_intake_arm(root)


if __name__ == "__main__":
    sys.exit(main())
