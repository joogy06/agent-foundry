"""Every agy command line in the shipped text pins its model (#367 review fix round 2, R3; WP-C M-d).

The agy family rule (global/CLAUDE.md) says every agy call passes `--model`, resolved through
`seat_model.py argv --role <role> --provider agy`; an unpinned call silently rides the
Antigravity-account default. This lint scans skills/, agents/, commands/, templates/, global/,
workflows/, vs-code/ and the files at the repo root for agy COMMANDS -- `agy ... -p|--print|--prompt`
followed by a prompt argument (a quote, `<` or `$`) -- and fails on any whose flags before the prompt
are not pinned. Pinned means ONE of:
- `--model <slug>` (a literal, or a `<placeholder>` in a template);
- `${AGY_MODEL:?resolve via seat_model.py argv --role R --provider agy}` (the `:?` form expands to
  nothing usable and stops the shell when the variable is unset, and its message names seat_model);
- `$AGY_MODEL` / `${AGY_MODEL}` / `${=AGY_MODEL}` WITH an assignment `AGY_MODEL=...seat_model...` in the
  same recipe, at or before the call: the same fenced code block of a markdown file (or the same line,
  outside a fence), or anywhere earlier in any other file. A bare `$AGY_MODEL` that nothing assigns
  expands to the empty string, so the call runs unpinned; WP-C M-d found ~13 such one-line recipes.

What it deliberately does not flag:
- prose that names the flag (`agy -p` returns plain text): `-p` is not followed by a prompt;
- the wrong-order illustration `agy -p --sandbox "X"`: `-p` is followed by a flag, not a prompt;
- model-eval-pack's cases/ and scripts/run_eval.py: they pass a literal `--model` on purpose (the
  measurement exception); the rest of that skill is scanned like any other;
- this file, whose fixtures are unpinned calls on purpose.

The same scan holds every ADVISORY call to Pattern 1 (#366). An advisory call is any agy command
without `--dangerously-skip-permissions`; it must carry `--mode plan` and no `--add-dir`, and an
executable recipe (one that expands $AGY_MODEL) must make its cwd an empty directory with `mktemp -d`
at or before the call. Illustrations with a `<slug>` placeholder are held to the flags only. Code
that builds the argv as a list or array is checked by its own pattern (`_ARGV_NO_PLAN`).

Backslash-continued lines are joined first, so a multi-line recipe is read as one command. A file
that is not UTF-8 is a FAILURE, never a silent skip: an undecodable file is one the lint cannot vouch for.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_TREE = _META.parent.parent
_ROOTS = ("skills", "agents", "commands", "templates", "global", "workflows", "vs-code")
_SUFFIXES = {".md", ".sh", ".py", ".txt", ".yaml", ".yml", ".json", ".js", ".ps1", ".toml"}
_SKIP_PARTS = {"__pycache__", "node_modules", ".git"}
#: Records of old text by design: a split manifest quotes the lines it replaced.
_SKIP_NAMES = {".split-manifest.json"}
#: The measurement exception (relative to the repo): model-eval-pack names the model under test.
_SKIP_PATHS = ("skills/model-eval-pack/cases/", "skills/model-eval-pack/scripts/run_eval.py")
#: Root files that are dated records, not shipped instructions (their old commands are history).
_ROOT_HISTORY = {"history.md", "history.md.pre-rotation-bak",
                 "agy.md"}   # the dated 2026-06-03 gemini -> agy migration spec, gemini-era commands quoted

# An agy command: `agy`, then flags (no backtick, pipe or `;` in between), then -p / --print /
# --prompt followed by whitespace and a prompt argument.
#: The prompt argument: a quote (escaped or not, as inside another quoted string), `<`, `$`, or `{` (an
#: f-string); `--prompt=x`; or a closing backtick, the shorthand `agy <flags> -p` (`tick`), which counts
#: only with flags before it, because a bare `agy -p` in backticks is prose naming the option.
_CALL = re.compile(r"\bagy\b(?P<flags>[^`|;]*?)\s(?:-p|--print|--prompt)"
                   r"(?:\s+(?:\\?[\"'<$]|\{)|=\S|(?P<tick>`))")
_LITERAL_PIN = re.compile(r"--model\b")
#: `${AGY_MODEL:?<message naming seat_model>}`: pinned on its own (an unset variable stops the shell).
_GUARDED_PIN = re.compile(r"\$\{AGY_MODEL:\?[^}]*seat_model[^}]*\}")
#: Any other expansion of the variable: pinned only when the recipe assigns it.
_VAR_USE = re.compile(r"\$\{?=?AGY_MODEL\}?")
#: An assignment from the seat registry: `AGY_MODEL=` (optionally `export`/`local`) on a line naming seat_model.
_ASSIGN = re.compile(r"(?<![\w$])AGY_MODEL=")
_FENCE = re.compile(r"^\s*(```|~~~)")

#: A pipe into agy, bare or through a subshell, or a file redirected to its stdin. Piped text never
#: reaches the model and rc stays 0 (#366, summary5.txt): a seat that relies on it reviews nothing.
_PIPED = re.compile(r"\|\s*\(?\s*(?:\w+=\S+(?: -d\)\")?\s*&&\s*)?(?:cd\s[^|&]*&&\s*)?(?:timeout\s+\S+\s+)?(?:[\w./~-]*/)?agy\s+--")
_STDIN_FILE = re.compile(r"[\"']\s+<\s*(?!/dev/null)[\"'$\w/~.]")
_PLAN = re.compile(r"--mode[ =]plan\b")
_ADD_DIR = re.compile(r"--add-dir\b")
_SKIP_PERMS = "--dangerously-skip-permissions"
#: `cd` into `$(mktemp -d)` is `cd ""` when mktemp fails: it succeeds and stays in the caller's repo.
_CD_MKTEMP = re.compile(r"\bcd\s+\"?\$\(mktemp -d")
#: The only accepted empty cwd: a `cd` into a variable whose mktemp was checked (`&&` or `|| exit`).
_MKTEMP_VAR = re.compile(r"(\w+)=\"?\$\(mktemp -d[^)]*\)\"?\s*(?:&&|\|\|\s*exit)")
_CD_VAR = re.compile(r"\bcd\s+\"?\$\{?(\w+)\}?")
#: A statement that allocates and stops there: a failed mktemp leaves the variable empty and the next
#: line runs on it (design C1). Safe under errexit, so a script that sets it is exempt.
_BARE_MKTEMP = re.compile(r"(?:^|[\s`(])[A-Za-z_]\w*=\"?\$\(mktemp[^)]*\)\"?[ \t]*(?:`|#.*)?$", re.M)
_ERREXIT = re.compile(r"^\s*set\s+(?:-[a-z]*e[a-z]*\b|-o\s+errexit\b)", re.M)
#: A literal-`--model` line that is a recipe to run, not an illustration of the flags.
_RUNNABLE = re.compile(r"\btimeout\s+\S+\s*$")
#: An argv built in code (`["agy", "--sandbox", ...]`, `cmd+=("$AGY_BIN" --sandbox)`) without the flag.
_ARGV_NO_PLAN = re.compile(r"""(?:["']agy["'],\s*["']--sandbox["'](?!,\s*["']--mode["'],\s*["']plan["']))"""
                           r"""|(?:AGY_BIN"\s+--sandbox(?!\s+--mode\s+plan))""")

# (path relative to the repo, text the line contains) -> why it is not an advisory call to hold to
# Pattern 1. Keep this small.
ADVISORY_ALLOW = {
    ("skills/antigravity-cli/SKILL.md", 'a plain `agy -p "create a file …"` probe wrote the file'):
        "the dated 2026-07-02 counter-example, not a recipe",
    ("skills/_meta/codex_watch.py", "Probed live on 2026-09-16 against a real `agy --sandbox -p`"):
        "the dated record of what was probed, not a recipe",
    ("skills/avengers/tests/test_convene.py", 'agy.index("--model") < agy.index(" -p ")'):
        "a test assertion about flag order, not a call",
    ("skills/avengers/tests/test_convene.py", 'policy["agy"].index("--model") < policy["agy"].index(" -p ")'):
        "a test assertion about flag order, not a call",
}

# (path relative to the repo, text the line contains) -> why it is not a call to pin.
# Keep this small: a new entry needs a reason a reviewer would accept.
ALLOW = {
    ("skills/antigravity-cli/SKILL.md", 'a plain `agy -p "create a file …"` probe wrote the file'):
        "historical counter-example: the dated 2026-07-02 probe that showed headless -p "
        "auto-approves writes; it is the incident being described, not a recipe",
    ("skills/_meta/codex_watch.py", "Probed live on 2026-09-16 against a real `agy --sandbox -p`"):
        "the dated record of what was probed, not a recipe",
}


def _logical_lines(text: str):
    """(first line number, line) with backslash continuations joined."""
    buf, start = "", 1
    for n, line in enumerate(text.splitlines(), 1):
        if not buf:
            start = n
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        yield start, buf + line
        buf = ""
    if buf:
        yield start, buf


def _assigns(line: str, upto: int | None = None, seat_seen: bool = False) -> bool:
    """Does `line` (up to column `upto`) assign AGY_MODEL from seat_model? The registry may be named
    on the line itself or earlier in the same recipe (`SEAT=.../seat_model.py`, then `"$SEAT" argv`)."""
    head = line if upto is None else line[:upto]
    return bool(_ASSIGN.search(head)) and (seat_seen or "seat_model" in line.lower())


def unpinned_calls(text: str, markdown: bool = True) -> list[tuple[int, str]]:
    """The (line number, line) of every agy command in `text` that does not pin its model.

    `markdown`: a recipe is one fenced code block (or one line outside a fence); otherwise the
    whole file is one recipe, read top to bottom."""
    hits = []
    in_fence, assigned, seat_seen = False, False, False
    for n, line in _logical_lines(text):
        if markdown and _FENCE.match(line):
            in_fence, assigned, seat_seen = not in_fence, False, False
            continue
        if markdown and not in_fence:
            assigned = seat_seen = False     # outside a fence, every line is its own recipe
        for m in filter(_is_call, _CALL.finditer(line)):
            flags = m.group("flags")
            if _LITERAL_PIN.search(flags) or _GUARDED_PIN.search(flags):
                continue
            if m.group("tick") and _VAR_USE.search(flags):
                continue                     # shorthand naming the pinned form, not a command to run
            if _VAR_USE.search(flags) and (assigned or _assigns(line, m.start(), seat_seen)):
                continue
            hits.append((n, line.strip()))
            break
        if _assigns(line, None, seat_seen):
            assigned = True
        if "seat_model" in line.lower():
            seat_seen = True
    return hits


def _is_call(m: re.Match) -> bool:
    """A closing backtick is a call only with flags before it: `agy -p` alone names the option."""
    return not m.group("tick") or "--" in m.group("flags")


def advisory_gaps(text: str, markdown: bool = True) -> list[tuple[int, str, str]]:
    """The (line number, line, what is wrong) of every advisory agy command not on Pattern 1 (#366).

    The empty cwd is reset after every call, in a script as in a fence: each call needs its own `cd`."""
    hits = []
    in_fence, cwd_seen, fresh = False, False, set()

    def scan_cwd(part: str) -> None:
        nonlocal cwd_seen
        fresh.update(_MKTEMP_VAR.findall(part))
        if any(v in fresh for v in _CD_VAR.findall(part)):
            cwd_seen = True

    for n, line in _logical_lines(text):
        if markdown and _FENCE.match(line):
            in_fence, cwd_seen = not in_fence, False
            fresh.clear()
            continue
        if markdown and not in_fence:
            cwd_seen = False                 # outside a fence, every line is its own recipe
            fresh.clear()
        if _CD_MKTEMP.search(line):
            hits.append((n, line.strip(), "unchecked mktemp: a failed mktemp stays in the caller's repo"))
        pos = 0
        for m in filter(_is_call, _CALL.finditer(line)):
            flags = m.group("flags")
            scan_cwd(line[pos:m.end()])
            pos0, pos = pos, m.end()
            if _SKIP_PERMS in flags:
                continue
            runnable = not m.group("tick") and (
                bool(_VAR_USE.search(flags)) or "< /dev/null" in line[m.end():]
                or bool(_RUNNABLE.search(line[:m.start("flags") - 3])))
            if _PIPED.search(line[pos0:m.end()]) or _STDIN_FILE.search(line[m.end():]):
                hits.append((n, line.strip(), "content piped to stdin never reaches the model"))
            elif not _PLAN.search(flags):
                hits.append((n, line.strip(), "no --mode plan"))
            elif _ADD_DIR.search(flags):
                hits.append((n, line.strip(), "--add-dir puts a directory in the workspace"))
            elif runnable and not cwd_seen:
                hits.append((n, line.strip(), "no empty cwd (cd into mktemp -d)"))
            cwd_seen = False
        scan_cwd(line[pos:])
    return hits


def _scanned(p: Path) -> bool:
    rel = p.relative_to(_TREE).as_posix()
    # This file is skipped: its fixtures are unpinned calls on purpose.
    return (p.is_file() and p.suffix in _SUFFIXES and not _SKIP_PARTS.intersection(p.parts)
            and p.name not in _SKIP_NAMES
            and not rel.startswith(_SKIP_PATHS) and p.resolve() != Path(__file__).resolve())


def _files():
    for p in sorted(_TREE.iterdir()):
        if p.name not in _ROOT_HISTORY and _scanned(p):
            yield p
    for root in _ROOTS:
        base = _TREE / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if _scanned(p):
                yield p


class ScannerSemantics(unittest.TestCase):
    ASSIGN = 'AGY_MODEL="$(python3 seat_model.py argv --role consultant_support --provider agy)" &&'

    def test_pinned_forms_pass(self):
        for ok in (f'{self.ASSIGN} timeout 600 agy --sandbox $AGY_MODEL -p "x" < /dev/null',
                   f'{self.ASSIGN} agy --sandbox ${{AGY_MODEL}} -p "x"',
                   f'{self.ASSIGN} agy --sandbox ${{=AGY_MODEL}} -p "x"',
                   'agy --sandbox --model gemini-4-argon-high -p "x"',
                   'agy --sandbox --model <pinned slug> -p "x"',
                   'agy --sandbox ${AGY_MODEL:?resolve via seat_model.py argv --role R --provider agy} -p "x"',
                   f'{self.ASSIGN} cat f | agy --sandbox $AGY_MODEL -p "x"',
                   f'{self.ASSIGN}\nagy --sandbox --dangerously-skip-permissions \\\n  $AGY_MODEL \\\n  -p "x" < /dev/null'):
            self.assertEqual(unpinned_calls(ok, markdown=False), [], ok)

    def test_an_unassigned_variable_is_not_a_pin(self):
        """WP-C M-d: `$AGY_MODEL` with nothing assigning it expands to nothing - the call is unpinned."""
        for bad in ('timeout 600 agy --sandbox $AGY_MODEL -p "x" < /dev/null',
                    'agy --sandbox ${AGY_MODEL} -p "x"',
                    'agy --sandbox ${AGY_MODEL:?unset} -p "x"',              # the guard must name seat_model
                    'AGY_MODEL=gemini-4-argon-high agy --sandbox $AGY_MODEL -p "x"',   # not from seat_model
                    f'agy --sandbox $AGY_MODEL -p "x"; {self.ASSIGN} true'):  # assigned only AFTER the call
            self.assertEqual(len(unpinned_calls(bad)), 1, bad)

    def test_a_markdown_recipe_is_one_fenced_block(self):
        same = f"```bash\n{self.ASSIGN}\nagy --sandbox $AGY_MODEL -p \"x\" < /dev/null\n```\n"
        self.assertEqual(unpinned_calls(same), [])
        other = (f"```bash\n{self.ASSIGN} true\n```\n\n```bash\n"
                 "agy --sandbox $AGY_MODEL -p \"x\" < /dev/null\n```\n")
        self.assertEqual(len(unpinned_calls(other)), 1)        # assigned in ANOTHER block
        prose = f"{self.ASSIGN} true\n\n`agy --sandbox $AGY_MODEL -p \"x\"`\n"
        self.assertEqual(len(unpinned_calls(prose)), 1)        # outside a fence, a line is its own recipe
        script = f"{self.ASSIGN} true\n\nagy --sandbox $AGY_MODEL -p \"x\" < /dev/null\n"
        self.assertEqual(unpinned_calls(script, markdown=False), [])   # a script reads top to bottom

    def test_unpinned_forms_fail(self):
        for bad in ('timeout 600 agy --sandbox -p "x" < /dev/null',
                    "agy -p 'Reply with exactly: OK' < /dev/null",
                    'cat f | agy --sandbox -p "$PROMPT"',
                    'agy --sandbox --print "x"',
                    'agy -p "fix" \\\n  --add-dir .'):
            self.assertEqual(len(unpinned_calls(bad)), 1, bad)

    def test_prose_and_the_wrong_order_illustration_are_not_calls(self):
        for prose in ('`agy -p` returns plain text',
                      'so `agy -p --sandbox "X"` runs UN-sandboxed',
                      'a single `agy -p` call',
                      'agy --print-timeout 15m is a flag'):
            self.assertEqual(unpinned_calls(prose), [], prose)


class PromptForms(unittest.TestCase):
    """Fix round M2: forms the first `_CALL` missed, one fixture each, on both checks."""
    FORMS = ('agy --sandbox -p \\"x\\"',            # an escaped quote, inside another string
             'agy --sandbox --prompt="y"',
             'agy --sandbox --print=$X',
             'agy --sandbox -p $PROMPT',
             'agy --sandbox -p {prompt}',
             '`agy --sandbox -p`')                     # the backticked shorthand

    def test_each_form_is_seen(self):
        for form in self.FORMS:
            self.assertEqual(len(unpinned_calls(form)), 1, form)
            self.assertEqual(len(advisory_gaps(form)), 1, form)

    def test_a_bare_backticked_option_is_still_prose(self):
        for prose in ('`agy -p` returns plain text', 'a single `agy -p` call', '`agy --help`'):
            self.assertEqual(unpinned_calls(prose), [], prose)
            self.assertEqual(advisory_gaps(prose), [], prose)


class PipedContent(unittest.TestCase):
    """Fix round 2: a pipe into agy delivers nothing and exits 0, so the lint fails it."""
    WHY = "content piped to stdin never reaches the model"

    def test_each_pipe_shape_fails(self):
        for bad in ('cat f | agy --sandbox --mode plan --model <slug> -p "x"',
                    'cat f | (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x")',
                    'tail -n +1 f | (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "x")',
                    '(d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x" < "$FILE")'):
            self.assertEqual([h[2] for h in advisory_gaps(bad)], [self.WHY], bad)

    def test_a_backslash_continued_pipe_fails(self):
        self.assertEqual(len(advisory_gaps('cat f \\\n  | (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x")')), 1)

    def test_inline_content_passes(self):
        for ok in ('C="$(cat f)" && (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x $C" < /dev/null)',
                   'C="$(a | b)" && (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null)'):
            self.assertEqual(advisory_gaps(ok), [], ok)


def bare_mktemps(text: str) -> list[str]:
    """Allocations with no check after them, unless the file stops on any error."""
    return [] if _ERREXIT.search(text) else [m.group(0).strip() for m in _BARE_MKTEMP.finditer(text)]


class MktempChecked(unittest.TestCase):
    def test_a_bare_allocation_fails(self):
        for bad in ('X=$(mktemp -d /tmp/x-XXXX)\n', 'X="$(mktemp -d)"\ncd "$X"\n', '  tmp=$(mktemp a.XX)  # note\n',
                    'Create it: `X=$(mktemp -d /tmp/x)`.'.replace('`.', '`\n')):
            self.assertEqual(len(bare_mktemps(bad)), 1, bad)

    def test_a_checked_allocation_passes(self):
        for ok in ('X=$(mktemp -d /tmp/x) || exit 1\n', 'X="$(mktemp -d)" && cd "$X"\n',
                   'X=$(mktemp) || { echo no; return 2; }\n', 'X=$(mktemp -d) codex exec "OK"\n',
                   'set -euo pipefail\nX="$(mktemp)"\n', 'set -o errexit\nX="$(mktemp)"\n'):
            self.assertEqual(bare_mktemps(ok), [], ok)


class AdvisorySemantics(unittest.TestCase):
    """DW-3 (#366): the lint fails an advisory call without --mode plan."""
    GOOD = '(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null)'

    def test_pattern_1_passes(self):
        for ok in (self.GOOD,
                   'agy --sandbox --mode plan --model <slug> -p "x"',
                   'agy --sandbox --mode plan --print-timeout 15m --model <slug> -p "x"'):
            self.assertEqual(advisory_gaps(ok), [], ok)

    def test_an_advisory_call_without_the_flag_fails(self):
        for bad in ('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox $AGY_MODEL -p "x" < /dev/null)',
                    'agy --sandbox --model <slug> -p "x"',
                    'agy --model <slug> -p "x"',
                    'agy --sandbox --model <slug> -p "x" --mode plan'):     # after -p it is the prompt's
            self.assertEqual([h[2] for h in advisory_gaps(bad)], ["no --mode plan"], bad)

    def test_a_live_workspace_fails(self):
        self.assertEqual(advisory_gaps('agy --sandbox --mode plan --add-dir . --model <slug> -p "x"')[0][2],
                         "--add-dir puts a directory in the workspace")
        self.assertEqual(advisory_gaps('timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null')[0][2],
                         "no empty cwd (cd into mktemp -d)")

    def test_an_unchecked_mktemp_fails(self):
        """Design C1: when mktemp fails, `cd ""` succeeds and agy runs in the caller's repo."""
        for bad in ('(cd "$(mktemp -d)" && agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null)',
                    'cd "$(mktemp -d)"',
                    'cd $(mktemp -d) && agy --sandbox --mode plan --model <slug> -p "x"'):
            self.assertTrue([h for h in advisory_gaps(bad) if "unchecked mktemp" in h[2]], bad)
        for bad in ('d="$(mktemp -d)"; cd "$d"; agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null',
                    'd="$(mktemp -d)"\ncd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null'):
            self.assertEqual([h[2] for h in advisory_gaps(bad, markdown=False)], ["no empty cwd (cd into mktemp -d)"], bad)
        self.assertEqual(advisory_gaps('d="$(mktemp -d)" || exit 1\ncd "$d" && agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null',
                                       markdown=False), [])

    def test_mktemp_without_a_cd_is_not_an_empty_cwd(self):
        for bad in ('D="$(mktemp -d)"; agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null',
                    'cd "$PROJECT"; agy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null'):
            self.assertEqual(len(advisory_gaps(bad)), 1, bad)
        self.assertEqual(advisory_gaps('D="$(mktemp -d)" && cd "$D" && agy --sandbox --mode plan $AGY_MODEL -p "x"'), [])

    def test_the_empty_cwd_is_reset_after_every_call(self):
        two = ('d="$(mktemp -d)" && cd "$d"\nagy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null\n'
               'agy --sandbox --mode plan $AGY_MODEL -p "y" < /dev/null\n')
        self.assertEqual([h[0] for h in advisory_gaps(two, markdown=False)], [3])

    def test_a_literal_model_recipe_needs_the_empty_cwd_too(self):
        self.assertEqual(len(advisory_gaps('timeout 600 agy --sandbox --mode plan --model <slug> -p "x"')), 1)
        self.assertEqual(len(advisory_gaps('agy --sandbox --mode plan --model <slug> -p "x" < /dev/null')), 1)

    def test_an_empty_cwd_set_earlier_in_the_recipe_counts_and_does_not_leak_out_of_it(self):
        same = '```bash\nd="$(mktemp -d)" && cd "$d"\nagy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null\n```\n'
        self.assertEqual(advisory_gaps(same), [])
        other = ('```bash\nd="$(mktemp -d)" && cd "$d"\n```\n\n'
                 '```bash\nagy --sandbox --mode plan $AGY_MODEL -p "x" < /dev/null\n```\n')
        self.assertEqual(len(advisory_gaps(other)), 1)

    def test_pattern_2_is_not_an_advisory_call(self):
        self.assertEqual(advisory_gaps('agy --sandbox --dangerously-skip-permissions $AGY_MODEL -p "x"'), [])

    def test_code_that_builds_the_argv_is_held_to_the_flag(self):
        for bad in ('["agy", "--sandbox", *pin, "-p", prompt]', 'cmd+=("$AGY_BIN" --sandbox)'):
            self.assertTrue(_ARGV_NO_PLAN.search(bad), bad)
        for ok in ('["agy", "--sandbox", "--mode", "plan", *pin, "-p", prompt]',
                   'cmd+=("$AGY_BIN" --sandbox --mode plan)'):
            self.assertIsNone(_ARGV_NO_PLAN.search(ok), ok)


class Scope(unittest.TestCase):
    def test_the_scan_covers_the_root_and_vs_code_and_narrows_the_eval_pack_skip(self):
        if not (_TREE / "global").is_dir():
            self.skipTest("not a foundry-lab checkout (installed copy)")
        rels = {p.relative_to(_TREE).as_posix() for p in _files()}
        self.assertIn("install.py", rels)
        self.assertIn("bootstrap-environment.py", rels)
        self.assertTrue(any(r.startswith("vs-code/") for r in rels))
        self.assertIn("skills/model-eval-pack/SKILL.md", rels)
        self.assertNotIn("skills/model-eval-pack/scripts/run_eval.py", rels)
        self.assertFalse(any(r.startswith("skills/model-eval-pack/cases/") for r in rels))
        self.assertNotIn("history.md", rels)


class ShippedText(unittest.TestCase):
    def test_every_agy_call_pins_its_model(self):
        if not (_TREE / "global").is_dir():
            self.skipTest("not a foundry-lab checkout (installed copy)")
        bad, used = [], set()
        for p in _files():
            rel = p.relative_to(_TREE).as_posix()
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                bad.append(f"{rel}: cannot be read as UTF-8 ({type(exc).__name__}); the lint cannot vouch for it")
                continue
            for n, line in unpinned_calls(text, markdown=p.suffix == ".md"):
                key = next((k for k in ALLOW if k[0] == rel and k[1] in line), None)
                if key:
                    used.add(key)
                    continue
                bad.append(f"{rel}:{n}: {line[:160]}")
        self.assertEqual(bad, [], "agy calls without $AGY_MODEL / --model (pin them through "
                                  "seat_model.py argv --role <role> --provider agy):\n" + "\n".join(bad))
        self.assertEqual(set(ALLOW) - used, set(), "stale allow-list entries: remove them")

    def test_every_mktemp_allocation_is_checked(self):
        if not (_TREE / "global").is_dir():
            self.skipTest("not a foundry-lab checkout (installed copy)")
        bad = []
        for p in _files():
            if "tests" in p.relative_to(_TREE).parts:
                continue                     # fixtures allocate on purpose, under pytest's own failure
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            bad += [f"{p.relative_to(_TREE).as_posix()}: {hit}" for hit in bare_mktemps(text)]
        self.assertEqual(bad, [], "unchecked mktemp (add `|| exit 1`, or `&&` on the same line):\n" + "\n".join(bad))

    def test_every_advisory_call_is_pattern_1(self):
        if not (_TREE / "global").is_dir():
            self.skipTest("not a foundry-lab checkout (installed copy)")
        bad, used = [], set()
        for p in _files():
            rel = p.relative_to(_TREE).as_posix()
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue                     # reported by test_every_agy_call_pins_its_model
            for n, line, why in advisory_gaps(text, markdown=p.suffix == ".md"):
                key = next((k for k in ADVISORY_ALLOW if k[0] == rel and k[1] in line), None)
                if key:
                    used.add(key)
                    continue
                bad.append(f"{rel}:{n}: {why}: {line[:140]}")
            for m in _ARGV_NO_PLAN.finditer(text):
                bad.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: argv without --mode plan")
        self.assertEqual(bad, [], "advisory agy calls not on Pattern 1 (`--sandbox --mode plan` from an "
                                  "empty cwd; see global/CLAUDE.md, #366):\n" + "\n".join(bad))
        self.assertEqual(set(ADVISORY_ALLOW) - used, set(), "stale allow-list entries: remove them")

