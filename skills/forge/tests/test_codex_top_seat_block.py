"""Behaviour tests for the `codex_top_seat` bash block (#282 r12; plan K18, K19).

The function has ONE source and two pasted copies (#344 WP-3), and every one is EXTRACTED here, never
retyped:
  * skills/_meta/codex_top_seat.sh -- the SOURCE (the CODEX_GAP body). It is sourced, never executed.
  * adversarial-team-brainstorm SKILL.md, "Spawning Teams" (a pasted copy, NO_SHOW gap line)
  * cross-cli-deliberation SKILL.md, "Invocation pattern" (a pasted copy, CONSULTANT_ABSENT gap line)
The three function bodies must be textually identical except each one's own gap line
(CODEX_GAP / NO_SHOW / CONSULTANT_ABSENT), so a fix can never land in one and not another.

Three call sites no longer paste the function. Each carries a source-and-guard PREAMBLE instead, in the
same Bash call as its seat invocations (SITES below), and the preamble is extracted from the documents too:
  * forge references/03-codex-seats.md, "Spawning Codex Agents" (the design-exploration seats)
  * forge references/05-escalation.md, "Codex Escalation" (the escalation seat)
  * codex-orchestration SKILL.md, "Seat Models" (the reference call)
forge is an entry file plus step references (#344 WP-4), so each forge site names the reference that holds
it, and "no core document pastes the function" is checked over each skill's whole corpus (skill_corpus).
The guard stops the Bash call BEFORE any seat is started when the script is missing or defines nothing, so a
failed `source` can never leave a round continuing with empty seat files. Both halves are run here from a
fresh bash: the preamble plus a seat call under a fixture HOME, and the same lines under a HOME without the
script (the negative control), where the guard line and a non-zero exit are asserted.

Each copy runs under bash with:
  * a fixture HOME whose `.claude/skills/_meta` is a symlink to THIS tree's skills/_meta, so the block's
    `$HOME/.claude/skills/_meta/{seat_model,codex_quota}.py` are the modules under test, and every budget
    row, tops record and meter read lands in the fixture HOME (the live-home guard enforces it);
  * a stub `codex` on PATH (records argv per invocation, writes the -o file, emits a planned stderr and exit);
  * a `timeout` wrapper on PATH that records its first argument and delegates to the real timeout(1);
  * a `python3` wrapper on PATH that runs this interpreter, logs each `<script> <subcommand>`, and can break
    the seat's resolution right after an admitted `argv --use` (case c);
  * a tmp project root ($PROJECT_DIR) per run, so every run has its own budget store -- unless a test hands
    several runs ONE project on purpose (Harness.shared_project), which is the only way two seats can be
    seen spending one budget: the store is per-project (f12).

What r12 changed, each with the NEGATIVE CONTROL that proves the test can see it (the pre-fix block is saved
below as PRE_FIX_BODY, the forge copy as it was at commit 8761ce4):
  (a) the timeout comes from `seat_model.py timeout`. The pre-fix block ran `timeout 600` for the arbiter too.
  (b) a classify failure after codex exit 0 keeps codex's output and says CODEX_CLASSIFY_ERROR on stderr;
      after a failed codex call it stays a gap. The pre-fix block overwrote a good answer with the gap line.
  (c) a timeout lookup that fails after the admit is the gap line and codex never runs (K19). The pre-fix
      block, which asks no timeout, ran codex under the same break.
  (d) a refused admit is still the CODEX_SUBSTITUTE line, and no timeout is asked for.
  (e) a first timeout re-runs the exec line once; a model at capacity twice substitutes `capacity_twice`
      (the H2 vocabulary through `${ACT#substitute }`).

WHAT S081 REVISION 4 / D24 CHANGED (WP-A04), and why each assertion below moved
------------------------------------------------------------------------------
GNU `timeout` is GONE from the block. The exec line is now `codex_watch.py`, and the registry timeout is
handed to it as `--hard-cap` -- the RUNAWAY guard -- while the normal stop is INACTIVITY. Three consequences,
all of them re-pointed here BY NAME rather than deleted:

  * `timeout_args` is now `[]` in every watched run, and the cap moved to the new `hard_cap_args`. The
    `timeout` wrapper stays in the harness and is still load-bearing: the PRE_FIX_* controls run under it
    and still record, so `timeout_args == []` is evidence that the wall clock is gone, not a dead assertion.
  * the seat numbers themselves rose with the D24 caps (WP-A02): consultant_main (xhigh) 600 -> 2400 s,
    arbiter (max) 1200 -> 3600 s. They are read from the registry here, never retyped as a literal, and the
    "no literal in the body" assertion is widened to the whole new cap vocabulary so a hardcoded 2400 is
    caught exactly as a hardcoded 600 was.
  * the retryable stop is the watchdog's exit 111 (went silent), not GNU timeout's 124. Its sibling 112
    (ran away while still ACTIVE) is deliberately NOT retryable: a gap on the first hit, never a
    substitution. Test (e) drives a REAL idle timeout -- a genuinely silent stub under a scaled-down
    `--idle-timeout` injected by the python3 wrapper, so the whole chain is exercised rather than simulated.
    Test (f) covers 112 and is the control that proves the block tells the two stops apart.

SCALING, stated plainly: the wrapper injects `--poll-interval` always and `--idle-timeout` when a test asks,
so a 300 s threshold is proven in ~1 s. The RATIO is what is preserved. No model call and no network call is
made by this file -- `codex` is always the stub.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
META = SKILLS / "_meta"
if str(META) not in sys.path:
    sys.path.insert(0, str(META))

import codex_quota as cq  # type: ignore  # noqa: E402
import codex_watch as cw  # type: ignore  # noqa: E402
import model_roster  # type: ignore  # noqa: E402

if str(META / "tests") not in sys.path:
    sys.path.insert(0, str(META / "tests"))
import codex_roster_fixture as crf  # type: ignore  # noqa: E402
import skill_corpus  # type: ignore  # noqa: E402

#: The model a substituted codex TOP seat is served by: the Claude main tier, read from the roster (#291) so a
#: roster swap never needs this file edited. The block prints whatever `seat_model.py substitute` resolves.
SUBSTITUTE_MODEL = model_roster.CLAUDE_MAIN

FUNC_OPEN = "codex_top_seat() {"

#: Scaled watchdog thresholds, injected by the python3 wrapper so the REAL watchdog does the REAL work in
#: test time. The ratio is preserved: a silent stub of WATCH_SILENCE_S against an idle window of
#: WATCH_IDLE_TEST_S stands in for a call that goes quiet past the production 300 s.
WATCH_POLL_INTERVAL_S = 0.05
WATCH_IDLE_TEST_S = 1
WATCH_SILENCE_S = 6

#: The seat timeouts are NEVER retyped here. They are derived from the D24 hard-cap table that
#: `seat_model.py timeout` is pinned to (WP-A02's test_d24_seat_timeouts_match_the_watchdog_hard_caps), so a
#: registry that drifts off that table fails this file too, at the shell-block level.
#: RE-POINTED by the astra reserve (roster rev 4): the codex TOP rows are code_reviewer (xhigh) and escalation (max);
#: consultant_main and arbiter are Sol literals whose recipe path (and U2 retry) has its own tests at the end.
SEAT_TIERS = (("code_reviewer", "xhigh"), ("escalation", "max"))


def cap_for(effort):
    return str(cw.HARD_CAP_S[effort])

#: The ONE source of the function (#344 WP-3). Sourced by the SITES below; never executed.
SCRIPT = META / "codex_top_seat.sh"

#: copy id -> (document, heading prefix, gap token). Heading prefixes stay ASCII; each must match one heading.
#: "script" is the source: it has no heading, and its function is read from the file itself.
COPIES = {
    "script": (SCRIPT, None, "CODEX_GAP"),
    "adversarial-team-brainstorm": (SKILLS / "adversarial-team-brainstorm" / "SKILL.md", "### Spawning Teams",
                                    "NO_SHOW"),
    "cross-cli-deliberation": (SKILLS / "cross-cli-deliberation" / "SKILL.md", "## Invocation pattern",
                               "CONSULTANT_ABSENT"),
}

#: Each copy's gap line, unchanged by r12.
GAP_LINES = {
    "CODEX_GAP": '    *) echo "CODEX_GAP: $NAME seat skipped (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;',
    "NO_SHOW": '    *) echo "NO_SHOW: $NAME codex team (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;',
    "CONSULTANT_ABSENT": '    *) echo "CONSULTANT_ABSENT: $NAME (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;',
}
_GAP_LINE = re.compile(r'^    \*\) echo "(CODEX_GAP|NO_SHOW|CONSULTANT_ABSENT): .*$', re.M)
_GAP_PLACEHOLDER = "    *) <the copy's gap line>"

#: site id -> (document, heading prefix). The call sites that SOURCE the script instead of pasting the function.
#: A site names the ONE file that holds it: for forge, a step reference (#344 WP-4).
SITES = {
    "forge-design": (SKILLS / "forge" / "references" / "03-codex-seats.md", "#### Spawning Codex Agents ("),
    "forge-escalation": (SKILLS / "forge" / "references" / "05-escalation.md", "#### Codex Escalation ("),
    "codex-orchestration": (SKILLS / "codex-orchestration" / "SKILL.md", "## Seat Models "),
}


def site_skill(site_id):
    """The skill a site's document belongs to: the first directory under skills/."""
    return SITES[site_id][0].relative_to(SKILLS).parts[0]
#: What marks a site's block, and the first line of its preamble: the `.` (source) line.
SOURCE_LINE = '. "$HOME/.claude/skills/_meta/codex_top_seat.sh" 2>/dev/null'
#: The line the guard prints on stderr when the function is not defined after the source.
GUARD_LINE = "CODEX_GAP: codex_top_seat.sh missing or unreadable; no codex seat was started"

#: The forge copy BEFORE #282 r12 (commit 8761ce4): hardcoded `timeout 600`, and a failed classify after a
#: good codex answer fell to `*) RC=1` and overwrote the answer with the gap line. NEGATIVE CONTROLS only.
PRE_FIX_BODY = r'''codex_top_seat() {
  local NAME="$1" ROLE="$2" USE="$3" BRIEF="$4" DEST="$5" OUT RC ACT="" TRY; shift 5
  local SEAT="$HOME/.claude/skills/_meta/seat_model.py" QUOTA="$HOME/.claude/skills/_meta/codex_quota.py"
  OUT="$(python3 "$SEAT" argv --role "$ROLE" --provider codex --use "$USE" --project-root "${PROJECT_DIR:-$PWD}")"; RC=$?
  if [ "$RC" -eq 0 ]; then
    for TRY in 1 2; do
      timeout 600 codex exec "$@" $OUT -o "$DEST" "$(cat "$BRIEF")" < /dev/null 2> "$DEST.stderr"; RC=$?
      ACT="$(python3 "$QUOTA" classify --exit-code "$RC" --attempt "$TRY" $([ "$RC" -eq 124 ] && echo --timed-out) \
               --stderr-file "$DEST.stderr" --output-file "$DEST" --prompt-file "$BRIEF")"
      [ "${ACT%% *}" = retry ] || break
    done
    case "$ACT" in
      "ok -") ;;
      "substitute "*) OUT="$(python3 "$SEAT" substitute --role "$ROLE" --use "$USE" --reason "${ACT#substitute }" \
                               --requested-model "$(set -- $OUT; echo "$2")" --project-root "${PROJECT_DIR:-$PWD}")"; RC=$? ;;
      *) RC=1 ;;
    esac
  fi
  case "$RC" in
    0) ;;  # codex answered: $DEST holds its output
    3) printf 'CODEX_SUBSTITUTE: %s -> %s (reason %s; provider gap: openai)\nbrief: %s\n' \
         "$NAME" "${OUT##*$'\n'}" "${OUT%%$'\n'*}" "$BRIEF" > "$DEST" ;;
    *) echo "CODEX_GAP: $NAME seat skipped (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;
  esac
}
'''

STUB_CODEX = r'''#!/bin/sh
# stub codex: one numbered record per invocation; the behaviour of invocation N is planned in $STUB_DIR
n=$(( $(cat "$STUB_DIR/calls" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STUB_DIR/calls"
printf '%s\n' "$@" > "$STUB_DIR/argv.$n"
# A planned SILENT stretch: nothing on stdout, nothing on stderr, no -o file yet. This is what the
# watchdog has to read as inactivity, and it is the only way to drive a real idle timeout from here.
if [ -f "$STUB_DIR/sleep.$n" ]; then sleep "$(cat "$STUB_DIR/sleep.$n")"; fi
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
if [ -f "$STUB_DIR/stderr.$n" ]; then cat "$STUB_DIR/stderr.$n" >&2; fi
if [ -f "$STUB_DIR/bigstderr.$n" ]; then head -c "$(cat "$STUB_DIR/bigstderr.$n")" /dev/zero >&2; fi
if [ -n "$out" ] && [ ! -f "$STUB_DIR/nooutput.$n" ]; then printf 'codex answer %s\n' "$n" > "$out"; fi
code=0
if [ -f "$STUB_DIR/exit.$n" ]; then code=$(cat "$STUB_DIR/exit.$n"); fi
exit "$code"
'''

TIMEOUT_WRAPPER = r'''#!/bin/sh
printf '%s\n' "$1" >> "$STUB_DIR/timeout.args"
exec "$REAL_TIMEOUT" "$@"
'''

PYTHON_WRAPPER = r'''#!/bin/sh
printf '%s %s\n' "${1##*/}" "$2" >> "$STUB_DIR/python.log"
if [ "${1##*/}" = seat_model.py ]; then
  # WP-D1: record the FULL argv of every seat_model call, one line per argument, so a test can assert
  # which flags the block really passed rather than that it called the script. This is a RECORDER, not a
  # substitution: the real seat_model still runs below with exactly these arguments.
  n=$(( $(cat "$STUB_DIR/seatcalls" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$STUB_DIR/seatcalls"
  printf '%s\n' "$@" > "$STUB_DIR/seat.argv.$n"
fi
if [ "${1##*/}" = codex_watch.py ]; then
  # Record the runaway cap the block asked the registry for. The block's own --hard-cap is left in place
  # and untouched, so what gets asserted is the value the block really passes, not one the test chose.
  prev=""
  for arg in "$@"; do
    if [ "$prev" = "--hard-cap" ]; then printf '%s\n' "$arg" >> "$STUB_DIR/hardcap.args"; fi
    prev="$arg"
  done
  # $WATCH_INJECT goes BEFORE the block's flags: a scaled --poll-interval always, and a scaled
  # --idle-timeout when a test drives a silent call. The REAL watchdog then does the REAL work in test time.
  script="$1"
  shift
  "$REAL_PYTHON" "$script" $WATCH_INJECT "$@"
  exit $?
fi
"$REAL_PYTHON" "$@"
rc=$?
if [ -n "$BREAK_AFTER_ADMIT" ] && [ "${1##*/}" = seat_model.py ] && [ "$2" = argv ] && [ "$rc" -eq 0 ]; then
  printf '%s\n' '{"schema": "seat-model-pins.v1", "pins": {"codex": {"top": "gpt-reserve"}}}' \
    > "$HOME/.claude/state/seat-model-pins.json"
fi
exit "$rc"
'''

#: The block as it stood at commit 19, BEFORE S081 revision 4 / WP-D1 gave it SIZE and KEY. Embedded
#: verbatim rather than fetched with `git show`, for the reason WP-C2 recorded: this file runs in BOTH
#: trees and ~/.claude is not a git repository. NEGATIVE CONTROL ONLY -- it takes five arguments, and it
#: passes neither --size nor --cycle-id, which is the whole of what WP-D1 changed.
PRE_D1_BODY = r'''codex_top_seat() {
  local NAME="$1" ROLE="$2" USE="$3" BRIEF="$4" DEST="$5" OUT RC ACT="" TRY TO MDL; shift 5
  local SEAT="$HOME/.claude/skills/_meta/seat_model.py" QUOTA="$HOME/.claude/skills/_meta/codex_quota.py"
  local WATCH="$HOME/.claude/skills/_meta/codex_watch.py"
  OUT="$(python3 "$SEAT" argv --role "$ROLE" --provider codex --use "$USE" --project-root "${PROJECT_DIR:-$PWD}")"; RC=$?
  if [ "$RC" -eq 0 ]; then
    TO="$(python3 "$SEAT" timeout --role "$ROLE" --provider codex)" || { ACT="seat_model timeout exit $?"; RC=1; }
    MDL="$(set -- $OUT; echo "$2")"
  fi
  if [ "$RC" -eq 0 ]; then
    for TRY in 1 2; do
      python3 "$WATCH" --mode codex --hard-cap "$TO" --model "$MDL" \
        --stdout-file "$DEST.stdout" --stderr-file "$DEST.stderr" \
        -- codex exec "$@" $OUT -o "$DEST" "$(cat "$BRIEF")"; RC=$?
      ACT="$(python3 "$QUOTA" classify --exit-code "$RC" --attempt "$TRY" $([ "$RC" -eq 111 ] && echo --timed-out) \
               --stderr-file "$DEST.stderr" --output-file "$DEST" --prompt-file "$BRIEF")" || ACT=classify_error
      [ "${ACT%% *}" = retry ] || break
    done
    case "$ACT" in
      "ok -") ;;
      "substitute "*) OUT="$(python3 "$SEAT" substitute --role "$ROLE" --use "$USE" --reason "${ACT#substitute }" \
                               --requested-model "$MDL" --project-root "${PROJECT_DIR:-$PWD}")"; RC=$? ;;
      classify_error) if [ "$RC" -eq 0 ]; then
                        echo "CODEX_CLASSIFY_ERROR: $NAME: classify failed after codex exit 0; $DEST keeps its output" >&2
                      else RC=1; fi ;;
      *) RC=1 ;;
    esac
  fi
  case "$RC" in
    0) ;;
    3) printf 'CODEX_SUBSTITUTE: %s -> %s (reason %s; provider gap: openai)\nbrief: %s\n' \
         "$NAME" "${OUT##*$'\n'}" "${OUT%%$'\n'*}" "$BRIEF" > "$DEST" ;;
    *) echo "CODEX_GAP: $NAME seat skipped (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;
  esac
}
'''
#: The FIVE-argument call line every copy of the block took before WP-D1 inserted SIZE and KEY. Both
#: embedded controls -- PRE_FIX_BODY (#282 r12) and PRE_D1_BODY (commit 19) -- are pre-D1 bodies and must
#: be driven through it; the default call line now passes seven, and a five-argument body given seven
#: would silently read SIZE as its brief and KEY as its destination.
PRE_SIZE_CALL = 'codex_top_seat "$SEAT_NAME" "$SEAT_ROLE" "$SEAT_USE" "$SEAT_BRIEF" "$SEAT_DEST" -s read-only\n'

CAPACITY_LINE = "ERROR: Selected model is at capacity. Please try a different model.\n"
BRIEF_TEXT = "Review the approach under test. Answer on stdout.\n"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or any(shutil.which(tool) is None for tool in ("bash", "timeout", "head")),
    reason="the codex_top_seat block is bash; it needs bash, coreutils timeout and head, and POSIX shebangs",
)


# --------------------------------------------------------------------------- #
# Extraction (the test_cycle_id_block.py pattern: fence-aware, pytest.fail when a block is missing)
# --------------------------------------------------------------------------- #
def _section(doc, lines, heading_prefix):
    matches = [i for i, line in enumerate(lines) if line.startswith(heading_prefix)]
    if len(matches) != 1:
        pytest.fail(f"expected exactly one heading starting {heading_prefix!r} in {doc}, found {len(matches)}")
    start = matches[0]
    level = len(heading_prefix) - len(heading_prefix.lstrip("#"))
    out, in_fence = [], False
    for line in lines[start + 1:]:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#"):
            depth = len(line) - len(line.lstrip("#"))
            if depth <= level and line[depth:depth + 1] == " ":
                break
        out.append(line)
    return out


def _bash_blocks(lines):
    blocks, current = [], None
    for line in lines:
        stripped = line.strip()
        if current is None and stripped == "```bash":
            current = []
        elif current is not None and stripped.startswith("```"):
            blocks.append("\n".join(current) + "\n")
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def extract_block(doc, heading_prefix, must_contain):
    lines = doc.read_text(encoding="utf-8").splitlines()
    found = [b for b in _bash_blocks(_section(doc, lines, heading_prefix)) if must_contain in b]
    if len(found) != 1:
        pytest.fail(f"expected exactly one ```bash block containing {must_contain!r} under "
                    f"{heading_prefix!r} in {doc}, found {len(found)}")
    return found[0]


def function_body(block, where):
    lines = block.splitlines()
    starts = [i for i, line in enumerate(lines) if line == FUNC_OPEN]
    if len(starts) != 1:
        pytest.fail(f"expected exactly one {FUNC_OPEN!r} line in {where}, found {len(starts)}")
    end = next((i for i in range(starts[0] + 1, len(lines)) if lines[i] == "}"), None)
    if end is None:
        pytest.fail(f"the codex_top_seat function in {where} has no closing '}}' line")
    return "\n".join(lines[starts[0]:end + 1]) + "\n"


def copy_body(copy_id):
    doc, heading, _token = COPIES[copy_id]
    if heading is None:                                                 # the script: the file is the block
        return function_body(doc.read_text(encoding="utf-8"), str(doc))
    return function_body(extract_block(doc, heading, FUNC_OPEN), f"{doc} / {heading}")


def site_block(site_id):
    """The ONE ```bash block of a call site that sources the script."""
    doc, heading = SITES[site_id]
    return extract_block(doc, heading, SOURCE_LINE)


def site_preamble(site_id):
    """A site's source-and-guard preamble, extracted: from the source line to the guard's closing `fi`."""
    lines = site_block(site_id).splitlines()
    starts = [i for i, line in enumerate(lines) if line == SOURCE_LINE]
    if len(starts) != 1:
        pytest.fail(f"expected exactly one source line in the {site_id} block, found {len(starts)}")
    end = next((i for i in range(starts[0] + 1, len(lines)) if lines[i] == "fi"), None)
    if end is None:
        pytest.fail(f"the guard in the {site_id} block has no closing 'fi' line")
    return "\n".join(lines[starts[0]:end + 1]) + "\n"


def normalized(body):
    return _GAP_LINE.sub(_GAP_PLACEHOLDER, body)


@pytest.fixture(scope="module")
def bodies():
    return {copy_id: copy_body(copy_id) for copy_id in COPIES}


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #
def _iso_nanos(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".887906859Z"


class Harness:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        (self.home / ".claude" / "skills").mkdir(parents=True)
        (self.home / ".claude" / "state").mkdir(parents=True)
        (self.home / ".codex").mkdir(parents=True)
        os.symlink(str(META), str(self.home / ".claude" / "skills" / "_meta"), target_is_directory=True)
        (self.home / ".codex" / "models_cache.json").write_text(json.dumps({
            "fetched_at": _iso_nanos(time.time() - 3600), "client_version": "0.154.0",
            # #302 WP-1: astra plus the roster's codex tiers (the shared synthetic roster), so a sized
            # light/medium seat finds the std model whatever the roster names it.
            "models": crf.codex_entries(slugs=("gpt-6-astra",))}), encoding="utf-8")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name, text in (("codex", STUB_CODEX), ("timeout", TIMEOUT_WRAPPER), ("python3", PYTHON_WRAPPER)):
            path = self.bin / name
            path.write_text(text, encoding="utf-8")
            path.chmod(0o755)
        self.runs = 0

    def shared_project(self, name):
        """A project root that SEVERAL runs can share (f12). `run` gives every seat a fresh project -- and so a
        fresh budget store -- by default, which hides sharing entirely: seats that must spend one key's
        allowance between them have to run in ONE project, against ONE store. The HOME stays the fixture's."""
        project = self.tmp / f"shared-{name}"
        project.mkdir()
        return project

    def env(self, stub_dir, project, **extra):
        env = dict(os.environ)
        env.update({
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
            "STUB_DIR": str(stub_dir), "REAL_TIMEOUT": REAL_TIMEOUT, "REAL_PYTHON": sys.executable,
            "PROJECT_DIR": str(project),
        })
        env.pop("BREAK_AFTER_ADMIT", None)
        env.update(extra)
        return env

    def run(self, body, *, role="code_reviewer", use="consult", name="seat", plan=None,
            watch_idle=None, size="", key="", invocation=None, project=None, **extra_env):
        """Run one seat of `body` in a fresh stub directory and, unless `project` is given, a fresh project.
        `plan` = {invocation: {exit, stderr, bigstderr, nooutput, sleep}} for the stub codex. `watch_idle`
        scales the watchdog's idle timeout down to test time (a `sleep` step longer than it drives a REAL idle
        stop). Returns a Run.

        `size` / `key` fill the WP-D1 SIZE and KEY slots and default to "" -- the empty caller, which is
        what every pre-D1 call site effectively was. `invocation` overrides the whole call line, so a test
        can drive the PRE-D1 five-argument shape against the old body as a control. `project` (from
        shared_project) runs this seat in an EXISTING project, so its budget row lands in the same store
        as every other seat run there; the stub directory stays per run, so each seat's codex calls are
        still counted on their own.
        """
        self.runs += 1
        run_dir = self.tmp / f"run-{self.runs}"
        stub_dir = run_dir / "stub"
        stub_dir.mkdir(parents=True)
        if project is None:                                             # the default: one budget store per run
            project = run_dir / "project"
            project.mkdir()
        for n, step in (plan or {}).items():
            if "exit" in step:
                (stub_dir / f"exit.{n}").write_text(str(step["exit"]), encoding="utf-8")
            if "stderr" in step:
                (stub_dir / f"stderr.{n}").write_text(step["stderr"], encoding="utf-8")
            if "bigstderr" in step:
                (stub_dir / f"bigstderr.{n}").write_text(str(step["bigstderr"]), encoding="utf-8")
            if step.get("nooutput"):
                (stub_dir / f"nooutput.{n}").write_text("", encoding="utf-8")
            if "sleep" in step:
                (stub_dir / f"sleep.{n}").write_text(str(step["sleep"]), encoding="utf-8")
        inject = f"--poll-interval {WATCH_POLL_INTERVAL_S}"
        if watch_idle is not None:
            inject += f" --idle-timeout {watch_idle}"
        extra_env.setdefault("WATCH_INJECT", inject)
        brief, dest = run_dir / "brief.md", run_dir / "out.md"
        brief.write_text(BRIEF_TEXT, encoding="utf-8")
        call = invocation if invocation is not None else (
            'codex_top_seat "$SEAT_NAME" "$SEAT_ROLE" "$SEAT_USE" "$SEAT_SIZE" "$SEAT_KEY" '
            '"$SEAT_BRIEF" "$SEAT_DEST" -s read-only\n')
        script = body + call
        env = self.env(stub_dir, project, SEAT_NAME=name, SEAT_ROLE=role, SEAT_USE=use, SEAT_BRIEF=str(brief),
                       SEAT_DEST=str(dest), SEAT_SIZE=size, SEAT_KEY=key, **extra_env)
        proc = subprocess.run(["bash", "-c", script], cwd=str(project), env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8", timeout=180)
        return Run(proc, stub_dir, project, brief, dest)


class Run:
    def __init__(self, proc, stub_dir, project, brief, dest):
        self.proc, self.stub_dir, self.project, self.brief, self.dest = proc, stub_dir, project, brief, dest

    def _lines(self, name):
        path = self.stub_dir / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    @property
    def codex_calls(self):
        return int((self.stub_dir / "calls").read_text(encoding="utf-8")) if (self.stub_dir / "calls").exists() else 0

    def codex_argv(self, n):
        return self._lines(f"argv.{n}")

    @property
    def timeout_args(self):
        """GNU timeout(1)'s first argument, per call. EMPTY for a watched block by design (D24): the wall
        clock is gone. The recorder is still live -- the PRE_FIX_* controls below make it record."""
        return self._lines("timeout.args")

    @property
    def hard_cap_args(self):
        """The `--hard-cap` the block handed codex_watch.py, per call. This is where the registry's timeout
        went: it is the RUNAWAY guard now, not the normal stop."""
        return self._lines("hardcap.args")

    @property
    def python_calls(self):
        return self._lines("python.log")

    def seat_argv(self, n):
        """The FULL argv of the n-th seat_model.py call, as the block really spelled it (WP-D1)."""
        return self._lines(f"seat.argv.{n}")

    def seat_argv_for(self, subcommand):
        """Every seat_model call of one subcommand, newest last. `argv` is the admit; `substitute` the
        substitution record. Returns a list of argv lists, so a test asserts on flags, never on a count."""
        total = int((self.stub_dir / "seatcalls").read_text(encoding="utf-8")) \
            if (self.stub_dir / "seatcalls").exists() else 0
        out = []
        for n in range(1, total + 1):
            argv = self.seat_argv(n)
            if len(argv) > 1 and argv[1] == subcommand:
                out.append(argv)
        return out

    @staticmethod
    def flag_value(argv, flag):
        """The value following `flag` in an argv list, or None when the flag is absent. None and "" are
        DIFFERENT answers here: absent is the back-compat path, empty would be a usage error."""
        return next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag), None)

    @property
    def output(self):
        return self.dest.read_text(encoding="utf-8") if self.dest.exists() else None

    def rows(self):
        path = cq.budget_path_for(self.project)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def drop_big_stderr(self):
        stderr_file = Path(str(self.dest) + ".stderr")
        if stderr_file.exists():
            stderr_file.unlink()


REAL_TIMEOUT = shutil.which("timeout") or "timeout"


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    probe = subprocess.run(["bash", "-c", 'test -d "$1"', "_", str(tmp_path)], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=60)
    if probe.returncode != 0:
        pytest.skip("bash cannot see the test's tmp directory")
    h = Harness(tmp_path)
    monkeypatch.setenv("HOME", str(h.home))                              # in-process store paths read the same HOME
    monkeypatch.setenv("USERPROFILE", str(h.home))
    return h


def _gap(copy_id, name, detail):
    token = COPIES[copy_id][2]
    text = {"CODEX_GAP": f"CODEX_GAP: {name} seat skipped ({detail}; see stderr)\n",
            "NO_SHOW": f"NO_SHOW: {name} codex team ({detail}; see stderr)\n",
            "CONSULTANT_ABSENT": f"CONSULTANT_ABSENT: {name} ({detail}; see stderr)\n"}
    return text[token]


def _substitute_line(name, reason, brief):
    return f"CODEX_SUBSTITUTE: {name} -> {SUBSTITUTE_MODEL} (reason {reason}; provider gap: openai)\nbrief: {brief}\n"


def _admitted(rows):
    return [r for r in rows if r.get("admitted") is True]


def _substitutions(rows):
    return [r for r in rows if r.get("kind") == "substitution"]


ALL_COPIES = pytest.mark.parametrize("copy_id", sorted(COPIES))


# --------------------------------------------------------------------------- #
# The script and the two pasted copies
# --------------------------------------------------------------------------- #
def test_the_script_and_the_pasted_copies_are_extracted_and_identical_except_their_gap_line(bodies):
    for copy_id, body in bodies.items():
        token = COPIES[copy_id][2]
        gap_lines = _GAP_LINE.findall(body)
        assert gap_lines == [token], (copy_id, gap_lines)
        assert GAP_LINES[token] in body.splitlines(), copy_id          # the gap line itself is unchanged
    reference = normalized(bodies["script"])
    assert {copy_id: normalized(body) == reference for copy_id, body in bodies.items()} == \
        {copy_id: True for copy_id in COPIES}
    # CONTROL: the normalisation hides ONLY the gap line - the pre-fix body is still told apart from the copies.
    assert normalized(PRE_FIX_BODY) != reference


# --------------------------------------------------------------------------- #
# #344 WP-3: the script is a definition and nothing else
# --------------------------------------------------------------------------- #
def test_the_script_holds_one_function_definition_and_no_top_level_command():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.endswith("}\n") and "\r" not in text
    code = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    body = function_body(text, str(SCRIPT)).splitlines()
    assert code == body                                                 # every non-comment line is the function
    assert not text.startswith("#!")                                    # sourced, never executed: no shebang
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr


#: Sources "$1" with a DEBUG trap counting every command bash runs (functrace on, so the count reaches into
#: the sourced file), then prints the count and the shell's state. A function DEFINITION is not a command.
#: The state is read from $- / $SHELLOPTS / $BASHOPTS, not from `$(set -o)`: bash clears errexit inside a
#: command substitution, so the substituted form cannot see a `set -e`.
_PROBE = r"""
set -T
N=0
BEFORE="$-|$SHELLOPTS|$BASHOPTS|$PWD|$(umask)|$(trap -p)"
FUNCS="$(declare -F)"
trap 'N=$((N+1))' DEBUG
. "$1"
trap - DEBUG
echo "commands=$N"
trap 'N=0' DEBUG; trap - DEBUG
if [ "$BEFORE" = "$-|$SHELLOPTS|$BASHOPTS|$PWD|$(umask)|$(trap -p)" ]; then echo state=unchanged; else echo state=CHANGED; fi
echo "functions_before=[$FUNCS]"
declare -F
"""


def _probe(path, cwd):
    proc = subprocess.run(["bash", "--noprofile", "--norc", "-c", _PROBE, "_", str(path)], cwd=str(cwd),
                          env={"PATH": os.environ.get("PATH", ""), "HOME": str(cwd), "LANG": "C.UTF-8"},
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr
    return proc.stdout.splitlines()


def test_sourcing_the_script_runs_no_command_and_changes_no_shell_state(tmp_path):
    empty = tmp_path / "empty.sh"
    empty.write_text("# nothing\n", encoding="utf-8")
    baseline = _probe(empty, tmp_path)                                  # what the probe itself costs
    assert baseline[1:] == ["state=unchanged", "functions_before=[]"]
    out = _probe(SCRIPT, tmp_path)
    assert out[0] == baseline[0], (out[0], baseline[0])                 # not one command more than an empty file
    assert out[1:] == ["state=unchanged", "functions_before=[]", "declare -f codex_top_seat"]
    assert (tmp_path / "empty.sh").exists() and sorted(p.name for p in tmp_path.iterdir()) == ["empty.sh"]
    # CONTROL: the probe can see a top-level command -- one `:` after the function is one command more.
    tainted = tmp_path / "tainted.sh"
    tainted.write_text(SCRIPT.read_text(encoding="utf-8") + ":\n", encoding="utf-8")
    count = lambda line: int(line.split("=", 1)[1])                     # noqa: E731
    assert count(_probe(tainted, tmp_path)[0]) == count(baseline[0]) + 1
    # CONTROL: and a changed shell option -- a `set -e` at top level is seen as changed state.
    strict = tmp_path / "strict.sh"
    strict.write_text("set -e\n" + SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    assert _probe(strict, tmp_path)[1] == "state=CHANGED"


# --------------------------------------------------------------------------- #
# #344 WP-3: the three call sites source the script behind a guard
# --------------------------------------------------------------------------- #
ALL_SITES = pytest.mark.parametrize("site_id", sorted(SITES))

#: A seat call as the sites make it: backgrounded, then waited for. AFTER_SEATS proves the Bash call went on.
_BACKGROUND_CALL = ('codex_top_seat "$SEAT_NAME" "$SEAT_ROLE" "$SEAT_USE" "$SEAT_SIZE" "$SEAT_KEY" '
                    '"$SEAT_BRIEF" "$SEAT_DEST" -s read-only &\nwait\necho AFTER_SEATS\n')
_SEAT_CALL = re.compile(r"^\s*codex_top_seat\s+\S")


def whole_skill(skill: str, root: Path = SKILLS) -> str:
    """Every file of the skill an absent-text check must read: the entry file, every reference AND the files
    beside the entry (codex-orchestration keeps `patterns.md` and `templates.md` there; #344 fix round 1, m5)."""
    return skill_corpus.corpus(skill, root=root, root_level=True)


def test_no_core_document_pastes_the_function_any_more():
    # ABSENT, so over each skill's WHOLE corpus (entry file, every reference, every root-level file): a
    # function pasted back into any file of a core skill is caught, wherever its call sites live. The source
    # line is counted the same way -- a skill has exactly as many as it has sites -- and then per document,
    # which pins each to its file.
    for skill in sorted({site_skill(s) for s in SITES}):
        whole = whole_skill(skill)
        assert FUNC_OPEN not in whole, skill
        assert whole.count(SOURCE_LINE) == sum(1 for s in SITES if site_skill(s) == skill), skill
    for doc in sorted({doc for doc, _heading in SITES.values()}):
        text = doc.read_text(encoding="utf-8")
        assert text.count(SOURCE_LINE) == sum(1 for d, _h in SITES.values() if d == doc), doc
    # the two non-core documents still paste it (phase 2), which is what the copies test above compares
    assert all(FUNC_OPEN in COPIES[c][0].read_text(encoding="utf-8")
               for c in ("adversarial-team-brainstorm", "cross-cli-deliberation"))


def test_NEGATIVE_CONTROL_a_function_pasted_into_a_reference_is_caught(tmp_path):
    """The absent-text check above must not be vacuous for a split skill: the function pasted into a REFERENCE
    is seen by the corpus reader, and is invisible to a reader of the entry file alone."""
    skill = tmp_path / "forge"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# entry\n", encoding="utf-8")
    (skill / "references" / "03-codex-seats.md").write_text(
        "```bash\n" + SCRIPT.read_text(encoding="utf-8") + "```\n", encoding="utf-8")
    assert FUNC_OPEN not in skill_corpus.read("forge", root=tmp_path)
    assert FUNC_OPEN in skill_corpus.corpus("forge", root=tmp_path)


def test_NEGATIVE_CONTROL_a_function_pasted_into_a_root_level_file_is_caught(tmp_path):
    """m5: a file BESIDE the entry file (codex-orchestration's `patterns.md`) is outside the default corpus, so
    the absent-text check above read past it. `whole_skill` is what that check reads."""
    skill = tmp_path / "codex-orchestration"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# entry\n", encoding="utf-8")
    (skill / "patterns.md").write_text(
        "```bash\n" + SCRIPT.read_text(encoding="utf-8") + "```\n", encoding="utf-8")
    assert FUNC_OPEN not in skill_corpus.corpus("codex-orchestration", root=tmp_path)
    assert FUNC_OPEN in whole_skill("codex-orchestration", root=tmp_path)


@ALL_SITES
def test_each_site_carries_the_preamble_and_the_guard_precedes_every_seat_call(site_id):
    preamble = site_preamble(site_id)
    assert preamble == site_preamble("codex-orchestration")             # one preamble, three sites
    assert preamble.splitlines() == [
        SOURCE_LINE,
        "if ! declare -F codex_top_seat >/dev/null; then",
        f'  echo "{GUARD_LINE}" >&2',
        "  exit 1",
        "fi",
    ]
    lines = site_block(site_id).splitlines()
    guard_end = lines.index(SOURCE_LINE) + len(preamble.splitlines()) - 1
    calls = [i for i, line in enumerate(lines) if _SEAT_CALL.match(line)]
    backgrounded = [i for i, line in enumerate(lines) if line.rstrip().endswith("&")]
    assert calls, site_id                                               # the SAME Bash call runs the seats
    assert all(guard_end < i for i in calls + backgrounded), (site_id, guard_end, calls, backgrounded)


@ALL_SITES
def test_the_documented_preamble_and_a_seat_call_run_from_a_fresh_bash(harness, site_id):
    """The fixture HOME's `.claude/skills/_meta` is this tree's, so the sourced script is the one under test."""
    run = harness.run(site_preamble(site_id), name="sourced", invocation=_BACKGROUND_CALL)
    assert run.proc.returncode == 0, run.proc.stderr
    assert GUARD_LINE not in run.proc.stderr and run.proc.stdout == "AFTER_SEATS\n"
    assert run.codex_calls == 1 and run.output == "codex answer 1\n"
    assert run.python_calls == ["seat_model.py argv", "seat_model.py timeout",
                                "codex_watch.py --mode", "codex_quota.py classify"]
    assert [(r["use"], r["reason"]) for r in _admitted(run.rows())] == [("consult", "within_budget")]


def _home_with_meta(tmp_path, name, script_text):
    """A HOME whose `.claude/skills/_meta` holds everything this tree's does EXCEPT codex_top_seat.sh, which
    is absent (script_text None) or replaced by `script_text`. So only the script differs from the harness."""
    home = tmp_path / name
    meta = home / ".claude" / "skills" / "_meta"
    meta.mkdir(parents=True)
    (home / ".claude" / "state").mkdir()
    for entry in META.iterdir():
        if entry.name != SCRIPT.name and entry.name != "__pycache__":
            os.symlink(str(entry), str(meta / entry.name), target_is_directory=entry.is_dir())
    if script_text is not None:
        (meta / SCRIPT.name).write_text(script_text, encoding="utf-8")
    return home


@ALL_SITES
@pytest.mark.parametrize("script_text", [None, "", "# a script that defines nothing\n:\n"],
                         ids=["absent", "empty", "defines-nothing"])
def test_NEGATIVE_CONTROL_without_the_script_the_guard_stops_the_call_before_any_seat(
        harness, tmp_path, site_id, script_text):
    home = _home_with_meta(tmp_path, "bare-home", script_text)
    run = harness.run(site_preamble(site_id), name="unsourced", invocation=_BACKGROUND_CALL, HOME=str(home),
                      USERPROFILE=str(home))
    assert run.proc.returncode == 1, (run.proc.returncode, run.proc.stderr)
    assert run.proc.stderr == GUARD_LINE + "\n"                         # the guard line, and nothing else
    assert run.proc.stdout == ""                                        # the Bash call did not go on
    assert run.codex_calls == 0 and run.output is None                  # no seat started, no seat file written
    assert run.python_calls == [] and run.rows() == []                  # nothing admitted, nothing spent


def test_NEGATIVE_CONTROL_without_the_guard_a_missing_script_lets_the_call_go_on(harness, tmp_path):
    """Why the guard exists: the source line alone fails quietly and the Bash call carries on to the end, with
    no seat and no seat file -- a round would then read an empty seat as a no-show."""
    home = _home_with_meta(tmp_path, "bare-home", None)
    run = harness.run(SOURCE_LINE + "\n", name="unguarded", invocation=_BACKGROUND_CALL, HOME=str(home),
                      USERPROFILE=str(home))
    assert run.proc.returncode == 0 and run.proc.stdout == "AFTER_SEATS\n"
    assert GUARD_LINE not in run.proc.stderr and run.codex_calls == 0 and run.output is None


#: Every number the D24 tables can produce for a cap, plus the idle window and the progress interval. A
#: literal ANY of these in the function body means a threshold was retyped instead of asked for.
_CAP_VOCABULARY = re.compile(
    r"\b(%s)\b" % "|".join(sorted(
        {str(v) for v in cw.HARD_CAP_S.values()}
        | {str(cw.IDLE_TIMEOUT_S), str(cw.PROGRESS_INTERVAL_S), str(cw.AGY_HARD_CAP_S), "600"},
        key=len, reverse=True)))


def test_the_block_takes_its_timeout_from_the_registry_after_the_admit(bodies):
    body = bodies["script"]
    lines = body.splitlines()
    admit = next(i for i, line in enumerate(lines) if "argv --role \"$ROLE\" --provider codex --use \"$USE\"" in line)
    lookup = next(i for i, line in enumerate(lines)
                  if 'TO="$(python3 "$SEAT" timeout --role "$ROLE" --provider codex)"' in line)
    # D24: the exec line is the watchdog, and the registry timeout reaches it as the RUNAWAY cap.
    exec_line = next(i for i, line in enumerate(lines)
                     if 'python3 "$WATCH" --mode codex --hard-cap "$TO"' in line)
    assert admit < lookup < exec_line                                   # K19: asked only after the admit
    assert '-- codex exec "$@" $OUT -o "$DEST"' in body                 # codex runs UNDER the watchdog, not beside it
    assert not re.search(r"\btimeout\s+[\"$0-9]", body)                 # GNU timeout(1) is gone from the block
    assert not _CAP_VOCABULARY.search(body)                             # no literal threshold left in the function
    assert "word-split" in body and "$OUT" in body                      # the comment says why it is not an argv line
    assert "CODEX_CLASSIFY_ERROR" in body
    # The two watchdog stops are told APART: 111 (went silent) is the retryable one and is the only one that
    # reaches classify as --timed-out; 112 (ran away while active) is left to fall through to the gap branch.
    assert '$([ "$RC" -eq %d ] && echo --timed-out)' % cw.EXIT_IDLE_TIMEOUT in body
    # 112 is DOCUMENTED in the body's comment but gets no branch of its own: it reaches classify as a plain
    # non-zero exit and falls to (gap, codex_error), which is what makes it a gap on the FIRST hit.
    assert re.search(r"-eq\s+%d\b" % cw.EXIT_HARD_CAP, body) is None
    assert body.count("--timed-out") == 1 and re.search(r"-eq\s+%d\b" % cw.EXIT_IDLE_TIMEOUT, body)
    # CONTROL: every one of those assertions sees the pre-fix block for what it is -- a hardcoded wall clock,
    # keyed off GNU timeout's 124, with no classify-error branch at all.
    assert re.search(r"\btimeout 600 codex exec\b", PRE_FIX_BODY)
    assert _CAP_VOCABULARY.search(PRE_FIX_BODY)
    assert '$([ "$RC" -eq 124 ] && echo --timed-out)' in PRE_FIX_BODY
    assert "CODEX_CLASSIFY_ERROR" not in PRE_FIX_BODY and '"$WATCH"' not in PRE_FIX_BODY


# --------------------------------------------------------------------------- #
# (a) the registry's timeout
# --------------------------------------------------------------------------- #
@ALL_COPIES
def test_a_the_timeout_is_the_seats_registry_timeout(bodies, harness, copy_id):
    body = bodies[copy_id]
    for role, effort in SEAT_TIERS:
        seconds = cap_for(effort)                                       # derived from the D24 table, never retyped
        run = harness.run(body, role=role, name=f"{role}-seat")
        assert run.proc.returncode == 0, run.proc.stderr
        # D24: the registry timeout is the watchdog's RUNAWAY cap, and GNU timeout(1) never runs at all.
        assert run.hard_cap_args == [seconds], (role, run.hard_cap_args)
        assert run.timeout_args == [], (role, run.timeout_args)
        assert run.output == "codex answer 1\n"
        argv = run.codex_argv(1)
        assert argv[:3] == ["exec", "-s", "read-only"] and argv[-1] == BRIEF_TEXT.rstrip("\n")
        assert argv[3:9] == ["-m", "gpt-6-astra", "-c", f"model_reasoning_effort={effort}", "-o", str(run.dest)]
        assert run.python_calls == ["seat_model.py argv", "seat_model.py timeout",
                                    "codex_watch.py --mode", "codex_quota.py classify"]
        rows = run.rows()
        assert [(r["use"], r["reason"]) for r in _admitted(rows)] == [("consult", "within_budget")]
        assert _substitutions(rows) == [] and harness.home in cq.budget_path_for(run.project).parents


def test_a_the_two_seat_tiers_really_do_differ(harness):
    """CONTROL for the parametrized assertion above: the caps it compares are not the same number, so a
    block that ignored $ROLE and passed one fixed cap could not pass both halves of the loop."""
    assert len({cap_for(effort) for _role, effort in SEAT_TIERS}) == len(SEAT_TIERS)
    assert cap_for("xhigh") != "600" and cap_for("max") != "1200"        # the D24 raise really landed


def test_a_negative_control_the_pre_fix_block_runs_the_arbiter_under_600(harness):
    run = harness.run(PRE_FIX_BODY, role="escalation", name="escalation-seat", invocation=PRE_SIZE_CALL)
    assert run.proc.returncode == 0, run.proc.stderr
    assert run.timeout_args == ["600"]
    assert "model_reasoning_effort=max" in run.codex_argv(1)


# --------------------------------------------------------------------------- #
# (b) a classify failure never overwrites a good answer
# --------------------------------------------------------------------------- #
_TOO_BIG = cq.CLASSIFY_READ_BYTES + 1                                    # classify refuses: "cannot classify"


@ALL_COPIES
def test_b_a_classify_failure_after_codex_exit_0_keeps_the_output(bodies, harness, copy_id):
    body = bodies[copy_id]
    run = harness.run(body, name="kept", plan={1: {"exit": 0, "bigstderr": _TOO_BIG}})
    run.drop_big_stderr()
    assert run.proc.returncode == 0
    assert run.output == "codex answer 1\n"                            # codex's output survives
    assert "CODEX_CLASSIFY_ERROR: kept" in run.proc.stderr
    assert "cannot classify" in run.proc.stderr                         # the classifier's own error, also on stderr
    assert run.codex_calls == 1                                         # no retry on a classify failure
    rows = run.rows()
    assert len(_admitted(rows)) == 1 and _substitutions(rows) == []
    # After a FAILED codex call a classify failure stays a gap, and no CODEX_CLASSIFY_ERROR is claimed. The failed
    # call exits 3 on purpose: the block's own "substitute" status is 3, so a block that kept codex's status here
    # would print a CODEX_SUBSTITUTE line built from the pin - a gap laundered into a substitution.
    failed = harness.run(body, name="failed", plan={1: {"exit": 3, "nooutput": True, "bigstderr": _TOO_BIG}})
    failed.drop_big_stderr()
    assert failed.output == _gap(copy_id, "failed", "classify_error")
    assert "CODEX_CLASSIFY_ERROR" not in failed.proc.stderr and failed.codex_calls == 1
    assert _substitutions(failed.rows()) == []


def test_b_negative_control_the_pre_fix_block_overwrites_a_good_answer(harness):
    run = harness.run(PRE_FIX_BODY, name="kept", plan={1: {"exit": 0, "bigstderr": _TOO_BIG}},
                      invocation=PRE_SIZE_CALL)
    run.drop_big_stderr()
    assert run.codex_calls == 1
    assert run.output == "CODEX_GAP: kept seat skipped (exit 1; see stderr)\n"


# --------------------------------------------------------------------------- #
# (c) no timeout -> the gap line, and codex never runs (K19)
# --------------------------------------------------------------------------- #
@ALL_COPIES
def test_c_a_timeout_lookup_that_fails_is_a_gap_and_codex_never_runs(bodies, harness, copy_id):
    run = harness.run(bodies[copy_id], name="untimed", BREAK_AFTER_ADMIT="1")
    assert run.output == _gap(copy_id, "untimed", "seat_model timeout exit 1")
    assert run.codex_calls == 0 and run.timeout_args == []              # codex never ran, timeout(1) never ran
    assert run.python_calls == ["seat_model.py argv", "seat_model.py timeout"]
    assert "gpt-reserve" in run.proc.stderr                             # the registry's own error, on stderr
    # K19 residual: the admission stays spent (one slot), never an unpinned or untimed call.
    rows = run.rows()
    assert [(r["use"], r["reason"]) for r in _admitted(rows)] == [("consult", "within_budget")]
    assert _substitutions(rows) == []


def test_c_negative_control_the_pre_fix_block_runs_codex_under_the_same_break(harness):
    run = harness.run(PRE_FIX_BODY, name="untimed", BREAK_AFTER_ADMIT="1", invocation=PRE_SIZE_CALL)
    assert run.codex_calls == 1 and run.output == "codex answer 1\n"
    assert run.python_calls == ["seat_model.py argv", "codex_quota.py classify"]


# --------------------------------------------------------------------------- #
# (d) a refused admit: the substitute line, and no timeout is asked
# --------------------------------------------------------------------------- #
def _write_fresh_reading(home, primary):
    observed = time.time() - 60
    day_dir = home / ".codex" / "sessions" / datetime.fromtimestamp(observed, timezone.utc).strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(observed, timezone.utc)
    rate_limits = {
        "limit_id": "codex", "limit_name": None,
        "primary": {"used_percent": primary, "window_minutes": 300, "resets_at": int(observed + 7200)},
        "secondary": {"used_percent": 10, "window_minutes": 10080, "resets_at": int(observed + 259200)},
        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
        "individual_limit": None, "plan_type": "plus", "rate_limit_reached_type": None,
    }
    event = {"timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z",
             "type": "event_msg",
             "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 1, "output_tokens": 1}},
                         "rate_limits": rate_limits}}
    path = day_dir / "rollout-2026-09-15T12-00-00-fixture.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    os.utime(path, (observed, observed))                                # the meter ranks rollouts by mtime (#282 R6)
    return path


def _quota_wait_line(name, reason, advice, resets_in, brief, use, key, requested):
    """#322 fix round 1 (item 5): the line also names the use, key and codex model a later `substitute` passes."""
    return (f"CODEX_QUOTA_WAIT: {name} (reason {reason}; wait_advice {advice}; resets_in_s {resets_in}; "
            f"stand-in {SUBSTITUTE_MODEL}; use {use}; key {key}; requested {requested})\nbrief: {brief}\n")


@ALL_COPIES
def test_d_a_quota_refusal_writes_the_quota_wait_line_and_asks_no_timeout(bodies, harness, copy_id):
    """RE-POINTED by #322 (was test_d_a_refused_admit_writes_the_substitute_line_and_asks_no_timeout, whose
    99% reading is a QUOTA refusal). The block admits with --await-quota, so the refusal records NO
    substitution: $DEST gets the CODEX_QUOTA_WAIT line (reason, advice, reset, the stand-in model read from
    LINE 2) and the seat's owner notifies / waits / re-admits. No timeout is asked and codex never runs."""
    _write_fresh_reading(harness.home, 99)
    run = harness.run(bodies[copy_id], name="refused")
    rows = run.rows()
    refusals = [r for r in rows if r.get("admitted") is False]
    assert [r["reason"] for r in refusals] == ["quota_exhausted"], rows
    assert _substitutions(rows) == []                                   # deferred: the wait decides
    out = run.output
    resets_in = re.search(r"resets_in_s (\d+);", out).group(1)
    assert 7000 <= int(resets_in) <= 7200
    [refusal] = refusals
    assert out == _quota_wait_line("refused", "quota_exhausted", "notify", resets_in, run.brief,
                                   refusal["use"], refusal["key"], refusal["requested_model"])
    assert run.codex_calls == 0 and run.timeout_args == []
    assert run.python_calls == ["seat_model.py argv"]                   # no timeout lookup before or after a refusal
    assert "--await-quota" in run.seat_argv_for("argv")[0]


@ALL_COPIES
def test_d_a_non_quota_refusal_still_writes_the_substitute_line(bodies, harness, copy_id):
    """The pre-#322 half of test (d): a refusal that is NOT quota (budget_spent) is substituted and recorded
    at once, and the CODEX_SUBSTITUTE line names the model from line 2."""
    project = harness.shared_project(f"budget-{copy_id}")
    first = harness.run(bodies[copy_id], name="first", project=project, key="k1")
    assert first.codex_calls == 1
    run = harness.run(bodies[copy_id], name="refused", project=project, key="k1")
    assert run.output == _substitute_line("refused", "budget_spent", run.brief)
    assert [(r["reason"], r["served_model"]) for r in _substitutions(run.rows())] == [
        ("budget_spent", SUBSTITUTE_MODEL)]
    assert run.codex_calls == 0 and run.timeout_args == []


def test_d_negative_control_a_last_line_reader_names_a_wait_line_as_the_model(bodies, harness):
    """Why the block reads the model as LINE 2 (#322): the same body reading the LAST line -- as every copy
    did before #322 -- and admitting without --await-quota would hand the seat a key=value line as its
    model. The derived control reverts exactly those two edits."""
    body = bodies["script"]
    old = body.replace(' "$NAME" "$L2" "${OUT%%$\'\\n\'*}" "$BRIEF" > "$DEST" ;;',
                       ' "$NAME" "${OUT##*$\'\\n\'}" "${OUT%%$\'\\n\'*}" "$BRIEF" > "$DEST" ;;')
    old = old.replace("           --await-quota ${SIZE:+", "           ${SIZE:+")
    assert old != body and "--await-quota ${SIZE" not in old
    _write_fresh_reading(harness.home, 99)
    run = harness.run(old, name="refused")
    assert run.output.startswith("CODEX_SUBSTITUTE: refused -> wait_advice=notify (reason quota_exhausted;")


# --------------------------------------------------------------------------- #
# (e) retry once, and capacity twice -> capacity_twice
# --------------------------------------------------------------------------- #
@ALL_COPIES
def test_e_a_first_timeout_retries_once_and_capacity_twice_substitutes(bodies, harness, copy_id):
    body = bodies[copy_id]
    cap = cap_for("xhigh")
    # D24: attempt 1 goes GENUINELY SILENT past the (scaled) idle window, so the REAL watchdog stops it and
    # exits 111. That is the retryable stop, so the exec line runs a second time -- the retry the pre-fix
    # block got from GNU timeout's 124 and this one must get from the watchdog.
    retried = harness.run(body, name="retried", watch_idle=WATCH_IDLE_TEST_S,
                          plan={1: {"sleep": WATCH_SILENCE_S, "nooutput": True}, 2: {"exit": 0}})
    assert retried.codex_calls == 2 and retried.output == "codex answer 2\n"
    assert retried.hard_cap_args == [cap, cap]                          # both attempts under the registry cap
    assert retried.timeout_args == []                                   # and neither under a wall clock
    assert retried.codex_argv(1) == retried.codex_argv(2)               # the same exec line, same model
    assert len(_admitted(retried.rows())) == 1 and _substitutions(retried.rows()) == []

    busy = harness.run(body, name="busy", plan={1: {"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE},
                                                2: {"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE}})
    assert busy.codex_calls == 2
    assert busy.output == _substitute_line("busy", "capacity_twice", busy.brief)
    rows = busy.rows()
    assert len(_admitted(rows)) == 1
    assert [(r["reason"], r["use"], r["requested_model"]) for r in _substitutions(rows)] == [
        ("capacity_twice", "consult", "gpt-6-astra")]
    # RE-POINTED by the astra reserve (U2): capacity twice asks for the ONE TOP retry. This seat already ran
    # on TOP, so seat_model refuses it (top_retry_same_pin, in the event row) and the seat goes to D6 for its
    # ORIGINAL failure in that same call - no separate `substitute` call, no second model, no TOP slot spent.
    # it asks the TOP timeout first, then offers the failed attempt's receipt. This seat's admission is
    # TOP-class, so seat_model refuses the proof (exit 2, NOTHING written) and the block substitutes the
    # original failure itself - no second model, no TOP slot, no event row.
    assert busy.python_calls == ["seat_model.py argv", "seat_model.py timeout",
                                 "codex_watch.py --mode", "codex_quota.py classify",
                                 "codex_watch.py --mode", "codex_quota.py classify",
                                 "seat_model.py timeout", "seat_model.py argv", "seat_model.py substitute"]
    assert [e for e in rows if e.get("kind") == "top_retry"] == []


# --------------------------------------------------------------------------- #
# (f) D24: the OTHER watchdog stop. A runaway is a gap on the FIRST hit, never a substitution.
# --------------------------------------------------------------------------- #
@ALL_COPIES
def test_f_a_hard_cap_stop_is_a_gap_on_the_first_hit_and_never_substitutes(bodies, harness, copy_id):
    """The block can only ever SEE an exit code, so the stub returns 112 directly rather than burning a
    real cap in test time; the watchdog's own production of 112 on a live runaway is codex_watch's test.
    What is under test here is the BLOCK's mapping, and its control is test (e) immediately above: the same
    block, the same two planned attempts, and a completely different outcome for the idle stop. A block
    that treated every non-zero stop alike would pass one of these two tests and fail the other."""
    run = harness.run(bodies[copy_id], name="runaway",
                      plan={1: {"exit": cw.EXIT_HARD_CAP, "nooutput": True},
                            2: {"exit": cw.EXIT_HARD_CAP, "nooutput": True}})
    assert run.codex_calls == 1                                         # NOT retried: a runaway is not retryable
    # the classifier's own verdict, unchanged and uninvented: no new SUBSTITUTION_REASONS token was needed
    assert run.output == _gap(copy_id, "runaway", "gap codex_error")
    rows = run.rows()
    assert len(_admitted(rows)) == 1                                    # the admission is still spent
    assert _substitutions(rows) == []                                   # and nothing was laundered into one
    assert run.python_calls == ["seat_model.py argv", "seat_model.py timeout",
                                "codex_watch.py --mode", "codex_quota.py classify"]
    assert run.hard_cap_args == [cap_for("xhigh")] and run.timeout_args == []


# --------------------------------------------------------------------------- #
# S081 revision 4, WP-D1 (design 3.4, D14-D18): SIZE and KEY
#
# The block gained two slots so that a consultancy caller can spend its OWN
# budget at its OWN size. Both are OPTIONAL and both default to empty, and an
# empty one must reach `seat_model.py argv` as NO FLAG AT ALL -- not as an empty
# string, which is a usage error, and not as a literal stand-in, which would
# record a `size_source: routing` decision nobody made.
#
# CONTROL for every test below: PRE_D1_BODY, the block at commit 19, driven
# through its own five-argument call line. It reaches the same `argv` subcommand
# and passes NEITHER flag -- so an assertion that cannot tell the two bodies
# apart is not measuring what WP-D1 changed.
# --------------------------------------------------------------------------- #
def _admit_argv(run):
    """The one `seat_model.py argv` call the block makes to admit the seat."""
    calls = run.seat_argv_for("argv")
    assert len(calls) == 1, calls
    return calls[0]


@ALL_COPIES
def test_d1_a_sized_keyed_seat_passes_both_flags_to_seat_model_argv(bodies, harness, copy_id):
    run = harness.run(bodies[copy_id], name="sized", size="light", key="tournament-abc")
    assert run.proc.returncode == 0, run.proc.stderr
    argv = _admit_argv(run)
    assert Run.flag_value(argv, "--size") == "light"
    assert Run.flag_value(argv, "--cycle-id") == "tournament-abc"
    # the seat still ran, and the admit still came FIRST: the new flags join the admit, they do not
    # become a second call that could be admitted separately.
    assert run.output == "codex answer 1\n"
    assert run.python_calls[0] == "seat_model.py argv"


@ALL_COPIES
def test_d1_an_empty_size_or_key_passes_NO_flag_rather_than_an_empty_one(bodies, harness, copy_id):
    """The back-compat path, and the reason `${SIZE:+...}` is used rather than a bare expansion.

    An empty `--size ""` is a usage error and an empty `--cycle-id ""` is refused as blank by
    `_check_usage`, so passing the flag with an empty value would BREAK every un-migrated call site.
    Absent is a different answer from empty, and `flag_value` returns None for absent on purpose.
    """
    run = harness.run(bodies[copy_id], name="unsized")                  # size="" and key="" by default
    assert run.proc.returncode == 0, run.proc.stderr
    argv = _admit_argv(run)
    assert Run.flag_value(argv, "--size") is None
    assert Run.flag_value(argv, "--cycle-id") is None
    assert "--size" not in argv and "--cycle-id" not in argv
    assert run.output == "codex answer 1\n"                             # and the seat resolves exactly as before


@ALL_COPIES
def test_d1_one_flag_without_the_other_is_passed_alone(bodies, harness, copy_id):
    """forge passes a SIZE and no KEY; a tournament passes both. Neither implies the other."""
    sized = harness.run(bodies[copy_id], name="size-only", size="complex")
    assert Run.flag_value(_admit_argv(sized), "--size") == "complex"
    assert Run.flag_value(_admit_argv(sized), "--cycle-id") is None
    keyed = harness.run(bodies[copy_id], name="key-only", key="ballot-xyz")
    assert Run.flag_value(_admit_argv(keyed), "--cycle-id") == "ballot-xyz"
    assert Run.flag_value(_admit_argv(keyed), "--size") is None


def test_d1_CONTROL_the_pre_d1_block_passes_neither_flag(harness):
    """THE NEGATIVE CONTROL. The commit-19 block, driven through its own five-argument call line, reaches
    the same `seat_model.py argv` subcommand and passes NEITHER flag. Without this, the three tests above
    would pass just as happily against a block that had never been changed."""
    run = harness.run(PRE_D1_BODY, name="pre-d1", invocation=PRE_SIZE_CALL)
    assert run.proc.returncode == 0, run.proc.stderr
    argv = _admit_argv(run)
    assert argv[1] == "argv" and "--use" in argv                        # it IS the same admit call
    assert Run.flag_value(argv, "--size") is None                       # and it carries neither new flag
    assert Run.flag_value(argv, "--cycle-id") is None
    assert run.output == "codex answer 1\n"


def test_d1_CONTROL_the_recorder_can_see_a_flag_when_one_is_passed(harness, bodies):
    """The recorder is DEMONSTRATED to be able to fail before it is trusted.

    Both control assertions above are `is None`, and a recorder that silently logged nothing would satisfy
    them for the wrong reason -- the empty-extraction shape this plan has paid for three times. So: the
    same recorder, the same run, a flag that IS passed, and a positive reading of it.
    """
    run = harness.run(bodies["script"], name="recorder", size="medium", key="ballot-1")
    argv = _admit_argv(run)
    assert Run.flag_value(argv, "--size") == "medium"                   # the recorder CAN see a flag
    assert Run.flag_value(argv, "--role") == "code_reviewer"            # and it records the pre-existing ones
    assert len(argv) > 5                                                # it captured a real argv, not an empty list


@ALL_COPIES
def test_d1_the_key_reaches_the_budget_row_so_the_seat_spends_its_own_budget(bodies, harness, copy_id):
    """The POINT of the key, asserted on the budget row rather than on the flag.

    A flag that reached `argv` but not the store would leave every consultancy seat still sharing the
    round's allowance -- the flag would be decorative and every assertion above would still pass.
    """
    run = harness.run(bodies[copy_id], name="keyed", use="brainstorm", key="tournament-shared-1")
    rows = _admitted(run.rows())
    assert len(rows) == 1, rows
    assert rows[0]["cycle_id"] == "tournament-shared-1"
    assert rows[0]["use"] == "brainstorm"


def test_d1_two_seats_on_ONE_minted_key_share_a_budget_and_two_tournaments_do_not(harness, bodies):
    """`brainstorm` is budgeted 2 TOP calls per key, so both seats of ONE tournament -- the diverge lead and
    the final cross-fire -- are admitted on its ONE minted key, and between them they spend that key's
    whole allowance. That is what "the diverge lead and the final cross-fire share one key" means in the
    store, and the store is per-project: so both seats run in ONE project and BOTH admitted rows are read
    back from that ONE store. (f12: this test used to run its two seats on DIFFERENT keys in two fresh
    projects, so it could not fail on a sharing regression.) Sharing is asserted three ways: both rows
    carry the same key; they are two admissions, not one row read twice; and a third seat on that key is
    refused `budget_spent`, because the two before it spent the allowance they share.

    CONTROL: a SECOND tournament mints a DIFFERENT key, and in the SAME project -- with the first key
    already spent -- both of its seats are admitted against a fresh budget rather than inheriting the first
    tournament's spend. Sharing and isolation are asserted together, because a key that was accidentally
    constant (or a store that ignored the key) would satisfy the first half and fail the second.
    """
    body = bodies["adversarial-team-brainstorm"]
    one, two = "tournament-11111111-1111-4111-8111-111111111111", \
               "tournament-22222222-2222-4222-8222-222222222222"
    project = harness.shared_project("tournaments")                   # ONE project, so ONE budget store
    store = cq.budget_path_for(project)
    assert harness.home in store.parents                                # the fixture HOME's store, never a live one

    def seat(name, key):
        run = harness.run(body, name=name, use="brainstorm", key=key, project=project)
        assert run.proc.returncode == 0, run.proc.stderr
        assert run.project == project and cq.budget_path_for(run.project) == store
        return run

    first = seat("diverge", one)
    assert [r["cycle_id"] for r in _admitted(first.rows())] == [one]
    # the SAME key again, in the SAME project: the store is per-project, so a fresh project would hide
    # sharing entirely.
    crossfire = seat("crossfire", one)
    assert crossfire.output == "codex answer 1\n", crossfire.output    # admitted and RAN, not refused + substituted
    assert first.output == "codex answer 1\n"
    rows = _admitted(crossfire.rows())                                  # BOTH rows, read back from the ONE store
    assert [(r["cycle_id"], r["use"], r["reason"]) for r in rows] == [(one, "brainstorm", "within_budget")] * 2
    assert len({r["admission_id"] for r in rows}) == 2                  # two admissions, not one row read twice
    assert cq.BUDGET_LIMITS["brainstorm"]["top"] == 2                   # the per-key allowance, RESTATED as a literal
    # on purpose (not derived): the third seat's refusal below rests on it, so a change to the limit fails HERE,
    # by name, rather than as an unexplained refusal further down.
    # ...so the two seats have spent the key's whole allowance BETWEEN them: a third seat on it is refused.
    third = seat("third", one)
    assert third.codex_calls == 0
    assert third.output == _substitute_line("third", "budget_spent", third.brief)
    # CONTROL, isolation: the second tournament's key, in the same project, after the first key is spent.
    assert one != two
    other = [seat(name, two) for name in ("diverge-2", "crossfire-2")]
    assert [run.output for run in other] == ["codex answer 1\n"] * 2
    assert [r["cycle_id"] for r in _admitted(other[-1].rows()) if r["cycle_id"] == two] == [two, two]
    assert [r["cycle_id"] for r in _admitted(other[-1].rows())] == [one, one, two, two]
    assert [(r["cycle_id"], r["reason"]) for r in other[-1].rows() if r.get("admitted") is False] == [
        (one, "budget_spent")]                                          # the ONE refusal is the third seat's


# --------------------------------------------------------------------------- #
# WP-D1: the KEY MINTS, extracted from the documents that carry them.
#
# The mint is the half of the change the block itself cannot enforce: the block
# passes whatever KEY it is handed, so whether a tournament's two seats really
# share one key -- and whether a FAILED mint quietly becomes an unkeyed call --
# is decided in the caller's own bash, in the SKILL.md. So the snippets are run
# from the documents rather than retyped here.
# --------------------------------------------------------------------------- #
def _snippet(block, first, last):
    """The lines of `block` from the one containing `first` to the one containing `last`, inclusive.
    Fails loudly rather than returning a partial snippet -- an empty extraction that still 'runs' is
    the shape this plan has paid for repeatedly."""
    lines = block.splitlines()
    starts = [i for i, line in enumerate(lines) if first in line]
    ends = [i for i, line in enumerate(lines) if last in line]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        pytest.fail(f"expected one {first!r} and one later {last!r}; got {starts} and {ends}")
    return "\n".join(lines[starts[0]:ends[0] + 1]) + "\n"


def _mint_snippet(copy_id, first, last):
    doc, heading, _token = COPIES[copy_id]
    return _snippet(extract_block(doc, heading, FUNC_OPEN), first, last)


def _run_snippet(snippet, tmp_path, *, epilogue, broken_mint=False, env_extra=None):
    """Run a doc snippet under bash and return its stdout. `broken_mint` shadows BOTH uuidgen and
    python3 with failing stubs, which is the only way the mint can fail on a real host."""
    run_dir = tmp_path / f"snip-{abs(hash((snippet, epilogue, broken_mint))) % 10**8}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"WORK": str(run_dir), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"})
    env.update(env_extra or {})
    if broken_mint:
        shadow = run_dir / "shadow"
        shadow.mkdir(exist_ok=True)
        for name in ("uuidgen", "python3"):
            stub = shadow / name
            stub.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
            stub.chmod(0o755)
        env["PATH"] = str(shadow) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(["bash", "-c", snippet + epilogue], cwd=str(run_dir), env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


ATB_MINT = ('if [ ! -s "$WORK/tournament-id" ]', 'TOURNAMENT_KEY="$(cat')
BALLOT_MINT = ('BID="$(uuidgen', 'BALLOT_SIZE=')


def test_d1_the_tournament_mint_produces_a_key_that_codex_quota_accepts(tmp_path):
    snippet = _mint_snippet("adversarial-team-brainstorm", *ATB_MINT)
    key = _run_snippet(snippet, tmp_path, epilogue='printf "%s" "$TOURNAMENT_KEY"\n')
    assert key.startswith("tournament-")
    assert cq.CYCLE_ID_PATTERN.match(key), key                          # the registry will accept it
    assert len(key) == len("tournament-") + 36                          # and it carries a real uuid


def test_d1_one_tournament_reuses_its_key_and_a_second_tournament_mints_a_different_one(tmp_path):
    """Criterion [3]'s property, asserted where it is decided. The diverge lead and the final
    cross-fire are SEPARATE Bash calls, so the key survives only because it is persisted: running the
    mint twice against the same $WORK must read the first key back, not mint a second.

    CONTROL: a different $WORK is a different tournament and MUST get a different key. Without it a
    mint that always produced a constant would satisfy the sharing half perfectly.
    """
    snippet = _mint_snippet("adversarial-team-brainstorm", *ATB_MINT)
    echo = 'printf "%s" "$TOURNAMENT_KEY"\n'
    first = _run_snippet(snippet, tmp_path / "t1", epilogue=echo)
    again = _run_snippet(snippet, tmp_path / "t1", epilogue=echo)       # same $WORK: the same tournament
    assert again == first and first                                     # SHARED, and not merely both empty
    second = _run_snippet(snippet, tmp_path / "t2", epilogue=echo)      # a different tournament
    assert second and second != first


def test_d1_a_failed_mint_yields_NO_key_so_the_seat_cannot_run_unkeyed(tmp_path):
    """Criterion [5]'s second half, and the defect it exists to prevent.

    `tournament-` with an EMPTY uuid SATISFIES codex_quota.CYCLE_ID_PATTERN -- a malformed key that
    passes validation. Had the mint been the obvious `KEY="tournament-$(uuidgen)"`, a host without
    uuidgen would hand every tournament that same valid-looking key, and they would all share one
    budget: exactly the starvation this work package exists to end, reintroduced silently.
    """
    assert cq.CYCLE_ID_PATTERN.match("tournament-")                     # THE HAZARD, stated as a fact
    snippet = _mint_snippet("adversarial-team-brainstorm", *ATB_MINT)
    key = _run_snippet(snippet, tmp_path, epilogue='printf "%s" "$TOURNAMENT_KEY"\n', broken_mint=True)
    assert key == ""                                                    # no key at all, rather than a bare prefix
    assert not (tmp_path / "tournament-id").exists()


def test_d1_the_ballot_mint_produces_a_key_that_codex_quota_accepts(tmp_path):
    snippet = _mint_snippet("cross-cli-deliberation", *BALLOT_MINT)
    out = _run_snippet(snippet, tmp_path, epilogue='printf "%s|%s" "$BALLOT_KEY" "$BALLOT_SIZE"\n')
    key, size = out.split("|")
    assert key.startswith("ballot-")
    assert cq.CYCLE_ID_PATTERN.match(key), key                          # the shape criterion [5] asked be proven
    assert size == "complex"                                            # a RATIFICATION ballot is complex


def test_d1_a_failed_ballot_mint_leaves_no_key_rather_than_the_bare_prefix(tmp_path):
    """The same hazard on the ballot side, and the same answer: no key, so no unkeyed call."""
    assert cq.CYCLE_ID_PATTERN.match("ballot-")                         # the bare prefix would have passed
    snippet = _mint_snippet("cross-cli-deliberation", *BALLOT_MINT)
    out = _run_snippet(snippet, tmp_path, epilogue='printf "%s|%s" "$BALLOT_KEY" "$BALLOT_SIZE"\n',
                       broken_mint=True)
    assert out.split("|")[0] == ""


# E1 (WP-D4, plan revision 39): the ONLY in-process seat resolution in this file (swept per node). With no
# fixture it ran under the PROCESS home, so `sm.resolve` recorded a TOP into that home's
# ~/.claude/state/seat-model-tops.json -- a developer's real ~/.claude whenever a roster is present, which
# the sentinel-home run surfaced as a live-home-guard violation. #282 H2 convention, as documented in
# skills/avengers/tests/test_steward.py: an EMPTY temp HOME plus a stub `codex` (conftest's
# `empty_live_home`). The assertions are unchanged.
@pytest.mark.usefixtures("empty_live_home")
def test_d1_ratification_resolves_complex_and_a_smaller_declared_size_is_NOT_promoted():
    """Criterion [6]'s third pair. The ballot declares `complex` because ratifying a design is
    deliberative work whatever the change's size -- and the CONTROL is that the sizing machinery is
    not simply always-complex: a plain ballot at a declared `light` resolves light and would seat the
    std model. Without the control, `complex` here would prove nothing about ratification.
    """
    import seat_model as sm
    ratification = sm.resolve_size("complex", project_root=None)
    plain = sm.resolve_size("light", project_root=None)
    assert (ratification.size, ratification.size_source) == ("complex", "routing")
    assert (plain.size, plain.size_source) == ("light", "routing")
    # D21 fix round 1 (m4): the SPECIFIC class. The empty temp home has no codex roster, so an unsized
    # code_reviewer falls open to the harness TOP literal - astra, TOP class. `in {"top", "std"}`
    # accepted every value model_class_of can return, so it could not fail. (RE-POINTED by the astra
    # reserve: consultant_main is the Sol literal now; code_reviewer is the TOP row this means.)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert pin.model == sm.CODEX_TOP_HARNESS_LITERAL
    assert sm.model_class_of(pin.model) == "top"


@pytest.mark.parametrize("use,key", [("brainstorm", "tournament-k"), ("ballot", "ballot-k")])
def test_d1_the_two_new_uses_admit_end_to_end_against_their_own_key(harness, bodies, use, key):
    """The parser accepting a string and the registry SPENDING that budget are different claims.

    `brainstorm` (atb) and `ballot` (cross-cli) are the two uses WP-D1 moves these call sites onto. This
    drives the real block through the real admit and asserts the row that comes out, so a use that
    parsed but was not budgeted -- the `class_not_budgeted` refusal -- could not pass unnoticed.
    """
    assert use in cq.BUDGET_LIMITS, use                                 # budgeted, not merely spellable
    run = harness.run(bodies["script"], name=f"{use}-seat", use=use, key=key)
    assert run.proc.returncode == 0, run.proc.stderr
    assert run.output == "codex answer 1\n"                             # the seat actually ran
    rows = _admitted(run.rows())
    assert [(r["use"], r["cycle_id"]) for r in rows] == [(use, key)]


# =========================================================================== #
# The astra reserve U2 / F3 (design docs/plans/2026-09-27-astra-reserve-design.md s4a): ONE TOP retry for a
# Sol seat that failed on CAPABILITY, driven end to end through the real block with the stub codex. The Sol
# seats are consultant_main (the challenger / explorer) and arbiter; `challenger` is the use they admit on.
# =========================================================================== #
QUOTA_LINE = "ERROR: You've hit your usage limit. Upgrade to Pro or try again later.\n"
AUTH_LINE = "ERROR: Your access token could not be refreshed. Please sign in again.\n"
SOL = model_roster.CODEX_STD


def _top_retry_events(rows):
    return [r for r in rows if r.get("kind") == "top_retry"]


def _receipt(run):
    path = Path(str(run.dest) + ".admit")
    return path.read_text(encoding="utf-8").split() if path.exists() else None


@ALL_COPIES
@pytest.mark.parametrize("failure", ["capacity", "malformed"])
def test_u2_a_capability_failure_on_sol_reruns_once_on_top(bodies, harness, copy_id, failure):
    step = ({"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE} if failure == "capacity"
            else {"exit": 0, "nooutput": True})
    run = harness.run(bodies[copy_id], role="consultant_main", use="challenger", name="sol-seat",
                      plan={1: step, 2: step, 3: {"exit": 0}})
    assert run.proc.returncode == 0, run.proc.stderr
    assert run.codex_calls == 3 and run.output == "codex answer 3\n"      # the TOP attempt's answer
    assert [run.codex_argv(n)[4] for n in (1, 2, 3)] == [SOL, SOL, "gpt-6-astra"]
    assert "model_reasoning_effort=xhigh" in run.codex_argv(3)             # the same effort on TOP
    assert run.python_calls == ["seat_model.py argv", "seat_model.py timeout",
                                "codex_watch.py --mode", "codex_quota.py classify",
                                "codex_watch.py --mode", "codex_quota.py classify",
                                "seat_model.py timeout", "seat_model.py argv",
                                "codex_watch.py --mode", "codex_quota.py classify"]
    rows = run.rows()
    first = [r for r in _admitted(rows) if r["use"] == "challenger"][0]
    retry_argv = run.seat_argv_for("argv")[-1]
    assert "--top-retry" in retry_argv
    assert "--await-quota" in retry_argv       # #322 fix round 1 (item 9): a quota-refused retry waits too
    assert Run.flag_value(retry_argv, "--failed-admission-id") == first["admission_id"]   # the EXACT attempt
    assert Run.flag_value(retry_argv, "--failed-reason") == f"{failure}_twice"
    assert [(r["use"], r["model_class"], r["requested_model"]) for r in _admitted(rows)] == [
        ("challenger", "std", SOL), ("top_retry", "top", "gpt-6-astra")]
    [ev] = _top_retry_events(rows)
    assert (ev["origin_use"], ev["outcome"], ev["failed_admission_id"]) == ("challenger", "admitted",
                                                                            first["admission_id"])
    assert _substitutions(rows) == []


@ALL_COPIES
@pytest.mark.parametrize("plan,reason", [
    ({1: {"exit": 1, "nooutput": True, "stderr": QUOTA_LINE}}, "quota_exhausted"),
    ({1: {"exit": 1, "nooutput": True, "stderr": AUTH_LINE}}, "auth_failure"),
    ({1: {"exit": cw.EXIT_IDLE_TIMEOUT, "nooutput": True}, 2: {"exit": cw.EXIT_IDLE_TIMEOUT, "nooutput": True}},
     "timeout_twice"),
])
def test_u2_quota_auth_and_timeout_never_buy_a_top_retry(bodies, harness, copy_id, plan, reason):
    run = harness.run(bodies[copy_id], role="consultant_main", use="challenger", name="sol-seat", plan=plan)
    assert run.output == _substitute_line("sol-seat", reason, run.brief)   # straight to D6
    assert all("--top-retry" not in argv for argv in run.seat_argv_for("argv"))
    assert all(argv[4] == SOL for argv in (run.codex_argv(n) for n in range(1, run.codex_calls + 1)))
    rows = run.rows()
    assert _top_retry_events(rows) == [] and [a["use"] for a in _admitted(rows)] == ["challenger"]
    assert [(s["use"], s["reason"]) for s in _substitutions(rows)] == [("challenger", reason)]


@ALL_COPIES
def test_u2_a_budget_refusal_never_reaches_codex_or_the_retry(bodies, harness, copy_id):
    project = harness.shared_project(f"u2-budget-{copy_id}")
    for _ in range(2):                                                     # the challenger's std budget is 2
        assert harness.run(bodies[copy_id], role="consultant_main", use="challenger", key="k",
                           project=project).output == "codex answer 1\n"
    refused = harness.run(bodies[copy_id], role="consultant_main", use="challenger", key="k",
                          name="sol-seat", project=project)
    assert refused.codex_calls == 0 and refused.output == _substitute_line("sol-seat", "budget_spent", refused.brief)
    assert _top_retry_events(refused.rows()) == [] and _receipt(refused) is None


@ALL_COPIES
def test_u2_an_unavailable_top_falls_to_the_opus_stand_in_and_is_bounded_per_cycle(bodies, harness, copy_id):
    """F1: two seats on DIFFERENT originating keys (a tournament, a ballot) share the cycle's ONE retry."""
    busy = {"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE}
    project = harness.shared_project(f"u2-bound-{copy_id}")
    first = harness.run(bodies[copy_id], role="consultant_main", use="challenger", key="tournament-a",
                        project=project, plan={1: busy, 2: busy, 3: {"exit": 0}})
    assert first.output == "codex answer 3\n"                              # the cycle's one TOP retry
    second = harness.run(bodies[copy_id], role="arbiter", use="ballot", key="ballot-b", name="arb",
                         project=project, plan={1: busy, 2: busy})
    assert second.codex_calls == 2                                         # no third call: TOP refused
    assert second.output == _substitute_line("arb", "budget_spent", second.brief)
    events = _top_retry_events(second.rows())
    assert [(e["role"], e["origin_key"], e["outcome"], e["reason"]) for e in events] == [
        ("consultant_main", "tournament-a", "admitted", None), ("arbiter", "ballot-b", "substituted", "budget_spent")]
    assert len({e["key"] for e in events}) == 1                            # one forge-cycle key for both


@ALL_COPIES
def test_u2_a_failed_top_attempt_keeps_its_key_and_is_never_retried_again(bodies, harness, copy_id):
    """F3 (astra F5): the substitution after a failed TOP attempt names the retry's OWN key (the cycle's),
    not the round's default; and the TOP attempt runs exactly once."""
    busy = {"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE}
    run = harness.run(bodies[copy_id], role="consultant_main", use="challenger", name="sol-seat", key="tournament-x",
                      plan={1: busy, 2: busy, 3: busy, 4: {"exit": 0}})
    assert run.codex_calls == 3                                            # Sol twice, TOP ONCE (no inner retry)
    assert run.output == _substitute_line("sol-seat", "capacity_twice", run.brief)
    rows = run.rows()
    retry = [r for r in _admitted(rows) if r["use"] == "top_retry"][0]
    assert [(s["use"], s["reason"], s["requested_model"], s["key"]) for s in _substitutions(rows)] == [
        ("top_retry", "capacity_twice", "gpt-6-astra", retry["key"])]
    assert Run.flag_value(run.seat_argv_for("substitute")[-1], "--cycle-id") == retry["key"]
    assert len(run.seat_argv_for("argv")) == 2                             # the admit and ONE --top-retry


@ALL_COPIES
def test_u2_a_timeout_lookup_that_fails_spends_no_retry_slot(bodies, harness, copy_id):
    """Opus 6: the TOP timeout is asked BEFORE the retry is admitted. BREAK_AFTER_ADMIT plants an invalid freeze,
    which breaks only the TOP rows - the Sol seat runs, and its retry's timeout lookup fails: no retry is
    admitted, no event is written, and the original failure is substituted on the seat's own key."""
    busy = {"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE}
    run = harness.run(bodies[copy_id], role="consultant_main", use="challenger", name="sol-seat", key="tournament-y",
                      plan={1: busy, 2: busy}, BREAK_AFTER_ADMIT="1")
    assert run.codex_calls == 2
    assert run.output == _substitute_line("sol-seat", "capacity_twice", run.brief)
    rows = run.rows()
    assert [r["use"] for r in _admitted(rows)] == ["challenger"] and _top_retry_events(rows) == []
    assert [(s["use"], s["key"]) for s in _substitutions(rows)] == [("challenger", "tournament-y")]



# =========================================================================== #
# D21 fix round 2: the receipt / proof plumbing, across the script and both pasted copies
# =========================================================================== #
BUSY = {"exit": 1, "nooutput": True, "stderr": CAPACITY_LINE}


@ALL_COPIES
@pytest.mark.parametrize("size", ["light", "medium"])
def test_fr2_a_sized_std_review_gets_the_top_retry(bodies, harness, copy_id, size):
    """Item 1: forge's D21 std code review (code_reviewer review_std at light/medium, Sol) is a std seat."""
    run = harness.run(bodies[copy_id], role="code_reviewer", use="review_std", size=size, name="review",
                      plan={1: BUSY, 2: BUSY, 3: {"exit": 0}})
    assert run.output == "codex answer 3\n", run.proc.stderr
    assert [run.codex_argv(n)[4] for n in (1, 2, 3)] == [SOL, SOL, "gpt-6-astra"]


@ALL_COPIES
def test_fr2_the_retry_names_the_receipts_key_when_the_caller_passed_none(bodies, harness, copy_id):
    """Item 2: the retry passes the failed admission's OWN key (receipt field 2), not a re-derivation."""
    run = harness.run(bodies[copy_id], role="consultant_main", use="challenger", name="sol-seat",
                      plan={1: BUSY, 2: BUSY, 3: {"exit": 0}})
    first = [r for r in _admitted(run.rows()) if r["use"] == "challenger"][0]
    retry_argv = run.seat_argv_for("argv")[-1]
    assert Run.flag_value(retry_argv, "--cycle-id") == first["key"]


@ALL_COPIES
def test_fr2_the_block_runs_under_set_u(bodies, harness, copy_id):
    """Item 3(a): the receipt fields are read with ${1-} / ${2-}, so `set -u` does not abort the seat."""
    call = ('set -u\ncodex_top_seat "$SEAT_NAME" "$SEAT_ROLE" "$SEAT_USE" "$SEAT_SIZE" "$SEAT_KEY" '
            '"$SEAT_BRIEF" "$SEAT_DEST" -s read-only\n')
    run = harness.run(bodies[copy_id], role="consultant_main", use="challenger", name="sol-seat",
                      plan={1: BUSY, 2: BUSY, 3: {"exit": 0}}, invocation=call)
    assert run.proc.returncode == 0 and run.output == "codex answer 3\n", run.proc.stderr


@ALL_COPIES
def test_fr2_a_refused_retry_still_substitutes_on_the_seats_own_key(bodies, harness, copy_id):
    """Item 3(c): the receipt is removed before the retry argv; a refused proof (a TOP-class seat) still
    substitutes the original failure on the key the seat was admitted on."""
    run = harness.run(bodies[copy_id], role="code_reviewer", use="advisory_review", name="review", key="rev-k",
                      plan={1: BUSY, 2: BUSY})
    assert run.output == _substitute_line("review", "capacity_twice", run.brief)
    assert [(s["use"], s["key"]) for s in _substitutions(run.rows())] == [("advisory_review", "rev-k")]
    assert not Path(str(run.dest) + ".admit").exists()                   # no stale receipt survives the refusal
