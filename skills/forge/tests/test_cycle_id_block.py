"""Behaviour tests for forge's per-cycle astra budget key (S081 amendment 1 D7; lead decision J3).

The blocks under test are EXTRACTED from the SKILL.md next to this file, never retyped:
  * "Step 1: Understanding" — the cycle-start block: a FRESH `.forge/cycle-id` every
    cycle (temp file + move, not git-gated) plus the git-gated `.forge/cycle-base`.
  * "Step 6: Collect Results" — the close-out block, `rm -f .forge/cycle-id`.

Since #344 WP-4 forge is an entry file plus step references. The three blocks above and the
`.forge/size` mint stay in SKILL.md (DOC); the rest of Step 6 — the advisory code review and
its fix loop — is in the close-out reference (CLOSE_OUT_REF). So:
  * a block is extracted from DOC, where it has to be;
  * "no OTHER block writes or deletes `.forge/size`" is counted over the whole corpus
    (`_corpus()`), because a stray one would now most likely be written into a reference;
  * Step 6 is read as the reader meets it (`step6_section`): SKILL.md's section with the
    close-out reference's text standing where SKILL.md says to read it.
They run under bash in tmp project roots, and the budget decisions come from the real
`skills/_meta/codex_quota.py` next to this tree, with HOME redirected to a tmp tree so no live
budget store is read or written.

Why this exists. At the S081 WP-A02 halt the budget key was `.forge/session-id`, minted once and
never re-minted, so a fresh project was refused `budget_spent` from cycle 3 on and a project
with a session-id from cycle 2 on. The NEGATIVE CONTROL below runs the same cycle harness with a
block that writes a constant id and proves the harness reports exactly that defect.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DOC = Path(__file__).resolve().parents[1] / "SKILL.md"
META = Path(__file__).resolve().parents[2] / "_meta"
if str(META) not in sys.path:
    sys.path.insert(0, str(META))

import codex_quota as cq  # type: ignore  # noqa: E402

if str(META / "tests") not in sys.path:
    sys.path.insert(0, str(META / "tests"))
import skill_corpus  # type: ignore  # noqa: E402

SKILLS = META.parent
#: The reference that holds the body of Step 6: the report, the spot-check, the D21 review and fix loop.
CLOSE_OUT_REF = "references/10-close-out.md"


def _corpus():
    """SKILL.md plus every reference: what an ABSENT / "no other block" assertion must read."""
    return skill_corpus.corpus("forge", root=SKILLS)

STEP1_HEADING = "### Step 1: Understanding (Lead Only)"
STEP4_HEADING = "### Step 4: Write Design Doc"
CLOSE_OUT_HEADING = "### Step 6: Collect Results"
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
#: A block that does NOT rotate the id: the halt defect, reintroduced on purpose.
CONSTANT_ID_BLOCK = "mkdir -p .forge\necho constant-cycle-id > .forge/cycle-id\n"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="the forge blocks are bash and the cycle base needs git; bash or git is absent",
)


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _section(lines, heading):
    """Lines from `heading` to the next heading of the same or a higher level, fence-aware
    (bash comments and heredoc markdown inside fences are not headings)."""
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        pytest.fail(f"heading missing from {DOC}: {heading!r}")
    level = len(heading) - len(heading.lstrip("#"))
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


def extract_block(heading, must_contain):
    lines = DOC.read_text(encoding="utf-8").splitlines()
    found = [b for b in _bash_blocks(_section(lines, heading)) if must_contain in b]
    if len(found) != 1:
        pytest.fail(f"expected exactly one ```bash block containing {must_contain!r} under "
                    f"{heading!r} in {DOC}, found {len(found)}")
    return found[0]


@pytest.fixture(scope="module")
def step1_block():
    return extract_block(STEP1_HEADING, ".forge/cycle-id")


@pytest.fixture(scope="module")
def step4_block():
    """The `.forge/size` mint. Its size is a literal placeholder in the doc, so a caller that
    wants to RUN it substitutes a real size (see `run_step4`)."""
    return extract_block(STEP4_HEADING, ".forge/size")


@pytest.fixture(scope="module")
def close_out_block():
    return extract_block(CLOSE_OUT_HEADING, "rm -f .forge/cycle-id")


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fixture_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _env(tmp_path, extra_path=None):
    env = dict(os.environ)
    env.update({
        "HOME": str(tmp_path / "home"), "USERPROFILE": str(tmp_path / "home"),
        "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    })
    if extra_path is not None:
        env["PATH"] = str(extra_path) + os.pathsep + env.get("PATH", "")
    return env


def run_block(block, root, env):
    proc = subprocess.run(["bash", "-c", block], cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return proc


def _git(root, env, *args):
    return subprocess.run(["git", *args], cwd=str(root), env=env, check=True, capture_output=True,
                          text=True, encoding="utf-8", timeout=60).stdout.strip()


def _commit(root, env, n):
    (root / f"f{n}.txt").write_text(str(n), encoding="utf-8")
    _git(root, env, "add", "--", f"f{n}.txt")
    _git(root, env, "-c", "commit.gpgsign=false", "commit", "-q", "-m", f"c{n}")
    return _git(root, env, "rev-parse", "HEAD")


@pytest.fixture()
def git_project(tmp_path):
    root = tmp_path / "gitproj"
    root.mkdir()
    env = _env(tmp_path)
    _git(root, env, "init", "-q")
    _commit(root, env, 0)
    return root


@pytest.fixture()
def plain_project(tmp_path):
    root = tmp_path / "plainproj"
    root.mkdir()
    return root


@pytest.fixture(autouse=True)
def bash_sees_tmp(tmp_path):
    """A bash that cannot see this tmp tree (for example WSL bash on Windows) cannot run the
    blocks meaningfully: skip with the reason rather than fail on a path translation."""
    probe = subprocess.run(["bash", "-c", 'test -d "$1"', "_", str(tmp_path)], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=60)
    if probe.returncode != 0:
        pytest.skip("bash cannot see the test's tmp directory")
    if shutil.which("uuidgen") is None and shutil.which("python3") is None:
        pytest.skip("the Step 1 block needs uuidgen or python3 to generate a cycle id")


def _cycle_id_file(root):
    return root / ".forge" / "cycle-id"


def _size_file(root):
    return root / ".forge" / "size"


SIZE_PLACEHOLDER = "<light|medium|complex>"


def run_step4(block, root, env, size):
    """Run the Step 4 mint for a REAL size. The doc carries a placeholder because forge
    substitutes this cycle's assessment; a test that ran it verbatim would only ever prove the
    placeholder round-trips."""
    assert SIZE_PLACEHOLDER in block, "the Step 4 block no longer carries the size placeholder"
    return run_block(block.replace(SIZE_PLACEHOLDER, size), root, env)


def _day(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y%m%d")


def _admit(use, root, tmp_path, now):
    cycle_id = cq.cycle_id_for(root, now=now)
    decision = cq.admit(use, cycle_id, project_root=root, now=now, sessions_dir=tmp_path / "no-sessions")
    assert Path(decision["budget_path"]).is_relative_to(tmp_path / "home")  # never the live store
    return decision


def run_cycles(block, root, tmp_path, count):
    """forge step order per cycle: a new commit, the cycle-start block, then the round's
    consult and challenger admits keyed exactly as the raw codex block keys them."""
    env = _env(tmp_path)
    cycles = []
    for n in range(1, count + 1):
        _commit(root, env, n)
        run_block(block, root, env)
        now = time.time()
        consult = _admit("consult", root, tmp_path, now)
        challenger = _admit("challenger", root, tmp_path, now)
        cycles.append((consult, challenger))
    return cycles


# --------------------------------------------------------------------------- #
# The extracted blocks
# --------------------------------------------------------------------------- #
def test_blocks_are_extracted_from_the_skill_doc(step1_block, close_out_block):
    assert "cycle-id.tmp" in step1_block and "mv -f .forge/cycle-id.tmp .forge/cycle-id" in step1_block
    assert "git rev-parse --verify -q HEAD" in step1_block and ".forge/cycle-base" in step1_block
    assert "session-id" not in step1_block
    # RE-POINTED (S081 revision 4, WP-A4), never relaxed: close-out now ends BOTH cycle-scoped
    # files. Still an exact equality, because that is what makes this a pin -- a substring check
    # here would pass against a block that had quietly grown a third command.
    assert close_out_block.strip() == "rm -f .forge/cycle-id .forge/size"


def test_step1_twice_writes_two_different_valid_cycle_ids(step1_block, git_project, tmp_path):
    env = _env(tmp_path)
    ids = []
    for _ in range(2):
        run_block(step1_block, git_project, env)
        text = _cycle_id_file(git_project).read_text(encoding="utf-8").strip()
        assert cq.CYCLE_ID_PATTERN.match(text) and UUID_RE.match(text), text
        assert cq.cycle_id_for(git_project) == text
        assert cq.cycle_id_and_source(git_project)[1] == "cycle-id"
        ids.append(text)
    assert ids[0] != ids[1]
    assert (git_project / ".forge" / "cycle-base").read_text(encoding="utf-8").strip() == _git(
        git_project, env, "rev-parse", "HEAD")
    assert not (git_project / ".forge" / "cycle-id.tmp").exists()


def test_step1_in_a_non_git_root_writes_a_cycle_id_and_no_cycle_base(step1_block, plain_project, tmp_path):
    proc = run_block(step1_block, plain_project, _env(tmp_path))
    text = _cycle_id_file(plain_project).read_text(encoding="utf-8").strip()
    assert UUID_RE.match(text)
    assert not (plain_project / ".forge" / "cycle-base").exists()
    assert "cycle-base not recorded" in proc.stdout
    assert cq.cycle_id_for(plain_project) == text


def test_step1_prefers_uuidgen_and_a_failed_generator_leaves_no_stale_id(step1_block, git_project, tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    uuidgen = stubs / "uuidgen"
    uuidgen.write_text("#!/usr/bin/env bash\necho 11111111-2222-4333-8444-555555555555\n", encoding="utf-8")
    uuidgen.chmod(0o755)
    env = _env(tmp_path, extra_path=stubs)
    run_block(step1_block, git_project, env)
    assert _cycle_id_file(git_project).read_text(encoding="utf-8") == "11111111-2222-4333-8444-555555555555\n"
    # A generator that prints nothing must not leave the PREVIOUS cycle's id in place.
    uuidgen.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    proc = run_block(step1_block, git_project, env)
    assert not _cycle_id_file(git_project).exists()
    assert not (git_project / ".forge" / "cycle-id.tmp").exists()
    assert "could not generate a cycle id" in proc.stdout
    now = time.time()
    base = _git(git_project, env, "rev-parse", "HEAD")
    assert cq.cycle_id_and_source(git_project, now=now) == (f"adhoc-{_day(now)}-{base[:7]}", "adhoc-base", None)


# --------------------------------------------------------------------------- #
# The per-cycle budget
# --------------------------------------------------------------------------- #
def test_three_consecutive_cycles_are_all_admitted(step1_block, git_project, tmp_path):
    cycles = run_cycles(step1_block, git_project, tmp_path, 3)
    for consult, challenger in cycles:
        assert (consult["admitted"], consult["reason"], consult["cycle_id_source"]) == (True, "within_budget", "cycle-id")
        assert (challenger["admitted"], challenger["reason"]) == (True, "within_budget")
    assert len({consult["cycle_id"] for consult, _ in cycles}) == 3


def test_a_second_consult_within_one_cycle_is_refused(step1_block, git_project, tmp_path):
    """CONTROL for the roll-over: the budget still binds inside a cycle."""
    run_cycles(step1_block, git_project, tmp_path, 1)
    again = _admit("consult", git_project, tmp_path, time.time())
    assert (again["admitted"], again["reason"]) == (False, "budget_spent")


def test_negative_control_a_block_that_does_not_rotate_the_id_is_refused_in_cycle_two(git_project, tmp_path):
    """The same harness on a constant-id block reproduces the WP-A02 halt defect, so the
    all-admitted result above is evidence and not an artefact of the harness."""
    cycles = run_cycles(CONSTANT_ID_BLOCK, git_project, tmp_path, 2)
    assert cycles[0][0]["admitted"] is True
    assert [(d["admitted"], d["reason"]) for d in cycles[1]] == [(False, "budget_spent"), (False, "budget_spent")]


def test_amendment_mode_work_keeps_the_cycle_id(step1_block, git_project, tmp_path):
    run_block(step1_block, git_project, _env(tmp_path))
    path = _cycle_id_file(git_project)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    expected = before[0].decode("utf-8").strip()
    # Amendment mode runs no Step 1 and no Step 6: only reads, plus its own proposal file.
    (git_project / ".forge" / "amendment-rev-2.yaml.proposal").write_text("revision: 2\n", encoding="utf-8")
    assert [cq.cycle_id_for(git_project) for _ in range(3)] == [expected] * 3
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_close_out_deletes_the_cycle_id_and_the_next_cycle_gets_a_new_one(step1_block, close_out_block,
                                                                         git_project, tmp_path):
    env = _env(tmp_path)
    run_block(step1_block, git_project, env)
    old = _cycle_id_file(git_project).read_text(encoding="utf-8").strip()
    # CONTROL: without the close-out block the old id is still the key.
    assert cq.cycle_id_for(git_project) == old
    run_block(close_out_block, git_project, env)
    assert not _cycle_id_file(git_project).exists()
    now = time.time()
    base = _git(git_project, env, "rev-parse", "HEAD")
    assert cq.cycle_id_and_source(git_project, now=now) == (f"adhoc-{_day(now)}-{base[:7]}", "adhoc-base", None)
    out_of_round = _admit("consult", git_project, tmp_path, now)
    assert (out_of_round["cycle_id_source"], out_of_round["admitted"]) == ("adhoc-base", True)
    run_block(close_out_block, git_project, env)  # idempotent: rm -f on a missing file
    run_block(step1_block, git_project, env)
    new = _cycle_id_file(git_project).read_text(encoding="utf-8").strip()
    assert UUID_RE.match(new) and new != old
    assert cq.cycle_id_for(git_project) == new


# --------------------------------------------------------------------------- #
# `.forge/size` lifecycle (S081 revision 4, WP-A4, design section 2.1)
#
# The size file has exactly two lifecycle points -- the Step 4 mint and the close-out deletion --
# and the second is the one that matters here: `.forge/size` has NO age fallback of the kind
# `.forge/cycle-id` gets from CYCLE_ID_MAX_AGE_S, so a size that outlives its cycle is read as
# authoritative and bills the NEXT cycle's codex main seats at the wrong model class.
# --------------------------------------------------------------------------- #
def test_a4_close_out_deletes_the_size_with_the_cycle_id_and_the_next_cycle_reads_the_default(
        step1_block, step4_block, close_out_block, git_project, tmp_path):
    import seat_model as sm  # local: HOME is redirected by the autouse fixture before this runs

    env = _env(tmp_path)
    run_block(step1_block, git_project, env)
    run_step4(step4_block, git_project, env, "light")
    # The REAL reader agrees the cycle is light -- not merely that a file exists.
    assert sm.read_forge_size(git_project) == "light"

    run_block(close_out_block, git_project, env)

    assert not _size_file(git_project).exists()
    assert not _cycle_id_file(git_project).exists()
    # Absent size is the back-compat reading: complex, by `size_source: default`.
    assert sm.read_forge_size(git_project) is None


def test_a4_negative_control_a_close_out_that_only_removes_the_cycle_id_leaves_a_stale_size(
        step1_block, step4_block, git_project, tmp_path):
    """The regression this pin exists to catch, proven to be catchable.

    Runs the PRE-CHANGE close-out text. The cycle id ends, so the next cycle is a new budget
    round -- but the size survives it, and `read_forge_size` still answers `light` for a cycle
    whose size was never assessed. That is the mis-billing, reproduced.
    """
    import seat_model as sm

    env = _env(tmp_path)
    run_block(step1_block, git_project, env)
    run_step4(step4_block, git_project, env, "light")

    run_block("rm -f .forge/cycle-id", git_project, env)  # the superseded close-out

    assert not _cycle_id_file(git_project).exists()
    assert _size_file(git_project).exists()
    assert sm.read_forge_size(git_project) == "light"


def test_a4_close_out_is_idempotent_when_the_size_was_never_written(step1_block, close_out_block,
                                                                   git_project, tmp_path):
    """A cycle that never reached Step 4 (abandoned at design, or a FAILED status) must still
    close cleanly: close-out runs for EVERY status, and `rm -f` on a missing file is not an error.
    """
    env = _env(tmp_path)
    run_block(step1_block, git_project, env)
    assert not _size_file(git_project).exists()
    run_block(close_out_block, git_project, env)  # must not fail; run_block asserts returncode 0
    run_block(close_out_block, git_project, env)  # and again, on a root with neither file
    assert not _size_file(git_project).exists()


def test_a4_amendment_mode_work_keeps_the_size_as_well_as_the_cycle_id(step1_block, step4_block,
                                                                      git_project, tmp_path):
    """Amendment mode runs inside the PAUSED cycle: no Step 4, no Step 6. Re-minting would
    re-point the paused cycle's seats mid-cycle; deleting would silently promote them back to
    complex. Both files must be byte- and mtime-identical across it."""
    import seat_model as sm

    env = _env(tmp_path)
    run_block(step1_block, git_project, env)
    run_step4(step4_block, git_project, env, "medium")
    paths = (_cycle_id_file(git_project), _size_file(git_project))
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]

    (git_project / ".forge" / "amendment-rev-2.yaml.proposal").write_text("revision: 2\n",
                                                                         encoding="utf-8")
    assert [sm.read_forge_size(git_project) for _ in range(3)] == ["medium"] * 3

    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


#: `.forge/size` itself, never the `.tmp` the Step 4 mint writes and renames.
_SIZE_PATH = r"\.forge/size(?!\.tmp)(?![\w.-])"
#: A line that WRITES the size: a redirection into it, or a `mv` whose destination is it.
_SIZE_WRITE = re.compile(r"(?:>>?\s*" + _SIZE_PATH + r"|^\s*mv\b[^\n]*" + _SIZE_PATH + r"\s*$)", re.M)
#: A line that DELETES it: an `rm` naming it.
_SIZE_DELETE = re.compile(r"^\s*rm\b[^\n]*" + _SIZE_PATH, re.M)


def _size_lifecycle_blocks(text):
    """Every ```bash block that WRITES or DELETES `.forge/size` -- its two lifecycle points.

    SCOPED TO LIFECYCLE OPERATIONS, NOT TO MENTIONS, and the distinction is the whole of this pin.
    Until WP-D1 this counted every block containing the string, which was a PROXY for "touches the
    lifecycle" and over-counted by exactly one case: a block that only READS the size. That case is
    not hypothetical -- design 3.4 requires the forge explorer and challenger to read it with
    `$(cat .forge/size)`, so the proxy fired on a change the design ordered while the property it
    claims to protect ("written in one place and deleted in one place") was never in danger.

    The narrowing is a STRENGTHENING on the adversarial case, which the buffers below demonstrate
    rather than assert: a stray `rm` hiding in a block that also legitimately reads the size is
    caught here and is INVISIBLE to a mention-counter, because that block was going to be counted
    anyway. A mention-counter cannot tell a read from a delete; this can.
    """
    return [b for b in _bash_blocks(text.splitlines())
            if _SIZE_WRITE.search(b) or _SIZE_DELETE.search(b)]


def test_a4_the_doc_names_exactly_two_size_lifecycle_points(step4_block, close_out_block):
    """`.forge/size` is written in one place and deleted in one place, and the doc is the proof.

    A third bash block that WRITES or DELETES it -- a helpful `rm` in a troubleshooting section, a
    re-mint in amendment mode -- is exactly the drift the paired documentation exists to prevent, and
    it would not be caught by either behavioural test above because neither would ever run it.

    Reads do not count, and must not: the seats that consume the size have to read it somewhere.
    """
    blocks = _size_lifecycle_blocks(_corpus())
    assert len(blocks) == 2, [b[:80] for b in blocks]
    # IDENTITY, not merely arity: it is never enough that two lifecycle blocks exist somewhere in the
    # document -- they must be the Step 4 mint and the close-out deletion themselves.
    assert sorted(blocks) == sorted([step4_block, close_out_block])


# --------------------------------------------------------------------------- #
# The narrowing above is demonstrated on four buffers rather than described.
#
# Each is the live document plus one appended block, so the ONLY difference
# between them is the block under test. Three of the four must still FIRE: if the
# narrowing had cost the pin its teeth, they would pass.
# --------------------------------------------------------------------------- #
_READ_BLOCK = ('\n```bash\n'
               '# the read design 3.4 requires of the explorer and the challenger\n'
               'FORGE_SIZE="$(cat .forge/size 2>/dev/null || true)"\n'
               '```\n')
_STRAY_DELETE = '\n```bash\n# troubleshooting: clear a wedged cycle\nrm -f .forge/size\n```\n'
_STRAY_WRITE = '\n```bash\n# a re-mint in amendment mode\nprintf \'%s\\n\' complex > .forge/size\n```\n'


def _mention_blocks(text):
    """The SUPERSEDED proxy, kept only as the control below. Never used as a pin."""
    return [b for b in _bash_blocks(text.splitlines()) if ".forge/size" in b]


def test_a4_narrowing_a_read_only_block_is_not_a_lifecycle_point():
    """THE CASE THE OLD PROXY GOT WRONG, and the reason this pin was narrowed at all.

    Measured on the LIVE document, which already carries the sanctioned read that design 3.4 requires
    of the forge explorer and challenger. So this is not a hypothetical: the superseded mention-counter
    fires on the shipped document as it stands, and the lifecycle counter does not.
    """
    text = _corpus()
    assert len(_size_lifecycle_blocks(text)) == 2                      # the property that actually holds
    # CONTROL: the proxy this replaced reports MORE than two on the same bytes -- the two counters
    # genuinely differ, so this test measures the change rather than restating the new behaviour.
    assert len(_mention_blocks(text)) > 2
    # and adding one more READ moves the proxy again while the lifecycle count stays put.
    assert len(_size_lifecycle_blocks(text + _READ_BLOCK)) == 2
    assert len(_mention_blocks(text + _READ_BLOCK)) == len(_mention_blocks(text)) + 1


def test_a4_narrowing_still_catches_a_stray_delete():
    """The first drift the docstring names: a helpful `rm` in a troubleshooting section."""
    blocks = _size_lifecycle_blocks(_corpus() + _STRAY_DELETE)
    assert len(blocks) == 3, [b[:80] for b in blocks]


def test_a4_narrowing_still_catches_a_stray_write():
    """The second drift the docstring names: a re-mint in amendment mode."""
    blocks = _size_lifecycle_blocks(_corpus() + _STRAY_WRITE)
    assert len(blocks) == 3, [b[:80] for b in blocks]


def test_a4_narrowing_catches_a_stray_delete_even_beside_a_legitimate_read():
    """THE ADVERSARIAL CASE, and the one that makes this a strengthening rather than a relaxation.

    A document carrying BOTH the sanctioned read and a stray delete. The mention-counter reports 4
    and fires -- but it would have fired on the read ALONE too, so its alarm cannot distinguish
    "someone added a delete" from "someone added the read the design ordered". A maintainer who had
    just added the read would see the expected failure and wave it through, taking the stray delete
    with it. The lifecycle counter reports 3 against an expected 2 and is pointing at the delete.
    """
    text = _corpus() + _READ_BLOCK + _STRAY_DELETE
    lifecycle = _size_lifecycle_blocks(text)
    assert len(lifecycle) == 3, [b[:80] for b in lifecycle]
    assert any(_SIZE_DELETE.search(b) and "troubleshooting" in b for b in lifecycle)
    # and the read is NOT among what it flags: the alarm names the delete, not the sanctioned read.
    assert not any("FORGE_SIZE=" in b for b in lifecycle)


# --------------------------------------------------------------------------- #
# S081 revision 4, WP-C2 (design §3.2-3.3; D10-D13, D21, D22)
#
# The advisory code review at forge close-out. The step is PROSE, not a runner
# (L8), so what is checkable about it is: that it EXISTS, that it sits BEFORE the
# `.forge/cycle-id` / `.forge/size` deletion, and that the seat/size/use mapping
# it states agrees with the registry that will actually serve the call.
#
# The third is the one worth having. `advisory_review` is budgeted for the TOP
# model class ONLY and `review_std` for the std class ONLY, so a prose table that
# paired them the other way round would document a call the registry refuses
# `class_not_budgeted`. Nothing else in the tree compares those two facts: the
# prose-vs-code gap #282 F16/K48 was raised for.
#
# CONTROL. Every assertion below is a function of a SECTION's lines, and each is
# run twice -- once against the live doc, once against PRE_C2_STEP6, the Step 6
# section as it stood at commit 18 (`3e313d5`), embedded verbatim. An assertion
# that cannot tell those two apart is not measuring the change it claims to. The
# control is embedded rather than read through `git show` on purpose: this file
# runs in BOTH trees and ~/.claude is not a git repository.
# --------------------------------------------------------------------------- #
#: The Step 6 section at commit 18, BEFORE the review step was added. Negative control only.
PRE_C2_STEP6 = '''
Bob returns a structured execution report. When you receive it:

1. **Check status** - COMPLETE / PARTIAL / FAILED

**Forge spot-checks bob's verification artifacts.** Bob produces concrete verification artifacts
(test output, lint output, build output) in his report. For medium/complex tasks, forge must:
1. Pick at least one verification artifact from bob's report and re-run the command independently
4. If spot-check fails: flag the discrepancy to the user before presenting

**Close the cycle - last, after the results are presented, for EVERY status.** Run from the project root:

```bash
rm -f .forge/cycle-id .forge/size
```

The cycle's astra budget ends here: out-of-round codex work afterwards keys on `adhoc-<date>-<cycle-base>`.
'''.splitlines()

#: The phrase the close-out review step leads with. Pinned because the ORDERING assertion
#: needs a stable anchor, and because "the step exists" has to mean something specific.
REVIEW_ANCHOR = "Advisory code review"

#: The deletion the review must precede, as the close-out block spells it.
DELETION_LINE = "rm -f .forge/cycle-id .forge/size"


def _step6_as_read(entry_lines, reference_lines, reference=CLOSE_OUT_REF):
    """Step 6 in the order a reader meets it: SKILL.md's section, with the reference's text standing at
    the line that says to read it.

    The ORDER the checkers below measure is therefore SKILL.md's own: the review precedes the deletion
    only if the line that sends the reader to the close-out reference precedes the `rm -f`. A section
    that never names the reference gets none of its text, so every checker fails on it.
    """
    section = _section(entry_lines, CLOSE_OUT_HEADING)
    at = _index_of(section, reference)
    if at is None:
        return section
    return section[:at + 1] + list(reference_lines) + section[at + 1:]


@pytest.fixture(scope="module")
def step6_section():
    return _step6_as_read(DOC.read_text(encoding="utf-8").splitlines(),
                          skill_corpus.read("forge", CLOSE_OUT_REF, root=SKILLS).splitlines())


def _index_of(lines, needle):
    """First line index containing `needle`, or None. Used for ORDER, so it must not
    silently answer 0 for an absent needle -- None is the absence."""
    return next((i for i, line in enumerate(lines) if needle in line), None)


def _review_table(lines):
    """The seat table's data rows, as lists of stripped cells.

    Keyed on the header's own cells rather than on a line number, so inserting a
    paragraph above the table does not silently return the wrong table.
    """
    head = next((i for i, line in enumerate(lines)
                 if line.startswith("|") and "effective size" in line and "--use" in line), None)
    if head is None:
        return []
    rows = []
    for line in lines[head + 2:]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


# --- the four checkers, each usable against ANY section's lines ------------- #
def _check_step_exists(lines):
    assert _index_of(lines, REVIEW_ANCHOR) is not None, "no advisory code review step"


def _check_review_precedes_deletion(lines):
    review = _index_of(lines, REVIEW_ANCHOR)
    deletion = _index_of(lines, DELETION_LINE)
    assert review is not None, "no advisory code review step"
    assert deletion is not None, "no close-out deletion in this section"
    assert review < deletion, (
        f"the review step is at line {review} and the deletion at {deletion}: the review must "
        f"run BEFORE the deletion, because `.forge/cycle-id` is its budget key and `.forge/size` "
        f"its size source")


def _check_seat_table_matches_registry(lines):
    """The prose's size -> `--use` mapping must be the one the registry budgets.

    Derived, never retyped: `STD_SIZES` says which sizes serve the std model,
    `BUDGET_LIMITS` says which use each model class may spend. A `None` cell is
    REFUSED `class_not_budgeted`, so exactly one use is legal per class.
    """
    import seat_model as sm  # noqa: E402

    rows = _review_table(lines)
    assert rows, "no seat table with an `effective size` / `--use` header"

    def budgeted_use(model_class):
        uses = [u for u, limits in cq.BUDGET_LIMITS.items()
                if u in ("advisory_review", "review_std") and limits.get(model_class) is not None]
        assert len(uses) == 1, f"{model_class}: expected one budgeted review use, got {uses}"
        return uses[0]

    seen = set()
    for cells in rows:
        size, klass, use, model = cells[0], cells[1], cells[2], cells[3]
        size = size.strip("`*")
        use = use.strip("`")
        model = model.strip("`")
        user_request = "--user-request" in cells[0]
        # What the registry would actually do with this size.
        std = (not user_request) and size in sm.STD_SIZES
        expected_class = cq.MODEL_CLASS_STD if std else cq.MODEL_CLASS_TOP
        assert klass.strip("`").lower() == expected_class, (
            f"row {cells!r}: the registry serves the {expected_class!r} class at this size, "
            f"not {klass!r}")
        assert use == budgeted_use(expected_class), (
            f"row {cells!r}: `{use}` is not the use budgeted for the {expected_class!r} class; "
            f"the registry would refuse it `class_not_budgeted`")
        if std:
            assert model == sm.CODEX_STD_MODEL, (
                f"row {cells!r}: the std model is seat_model.CODEX_STD_MODEL "
                f"({sm.CODEX_STD_MODEL!r}), not {model!r}")
        else:
            assert model == "codex TOP", (
                f"row {cells!r}: name the TOP seat as `codex TOP`, never a slug -- the TOP "
                f"selector auto-follows the vendor (D1) and a literal here goes stale silently")
        seen.add((size, use))
    assert sm.CODE_REVIEWER in sm.SIZED_ROLES, "code_reviewer must be a SIZED role for this to hold"
    assert {s for s, _ in seen} >= set(sm.STD_SIZES) | {"complex"}, (
        f"the table must cover every size the registry knows: {seen}")


def _check_fix_loop_has_all_six_steps(lines):
    """D21's six steps, each keyed on the word that carries its obligation."""
    text = "\n".join(lines)
    required = {
        "verify": "Stage-1.5 verification",
        "fix": "re-reviewed",
        "bound": "TWO fix rounds",
        "unfixable": "UNFIXABLE",
        "minor": "minor",
        "report": "docs/reviews/YYYY-MM-DD-<cycle>-review.md",
    }
    missing = [name for name, token in required.items() if token not in text]
    assert not missing, f"the D21 fix loop is missing its {missing} step(s)"


_CHECKERS = (_check_step_exists, _check_review_precedes_deletion,
             _check_seat_table_matches_registry, _check_fix_loop_has_all_six_steps)


@pytest.mark.parametrize("checker", _CHECKERS, ids=[c.__name__ for c in _CHECKERS])
def test_c2_the_close_out_review_is_documented(checker, step6_section):
    checker(step6_section)


@pytest.mark.parametrize("checker", _CHECKERS, ids=[c.__name__ for c in _CHECKERS])
def test_c2_negative_control_every_check_fails_on_the_pre_change_section(checker):
    """Each assertion must FAIL against the Step 6 section as it stood before this change.

    Without this, a checker that accidentally always passes -- a `in text` that matches
    something else, a table lookup that returns early on absence -- would occupy the slot
    while measuring nothing. That failure mode cost this cycle a mutant escape at WP-C1.
    """
    with pytest.raises(AssertionError):
        checker(PRE_C2_STEP6)


def test_c2_the_review_is_in_the_close_out_reference_and_the_deletion_in_the_entry_file():
    """#344 WP-4, the location pins. The review step lives in the close-out reference and nowhere else;
    the deletion block lives in SKILL.md and nowhere else (it is one of the three fail-silent blocks,
    and a second copy in a reference is exactly the stray lifecycle block the A4 pin forbids)."""
    heading = "#### " + REVIEW_ANCHOR
    assert skill_corpus.rel("forge", skill_corpus.file_of("forge", heading, root=SKILLS), root=SKILLS) == CLOSE_OUT_REF
    assert skill_corpus.file_of("forge", "\n" + DELETION_LINE + "\n", root=SKILLS) == DOC


def _moved(lines, needle, after):
    """`lines` with the first line containing `needle` moved to just after the first containing `after`."""
    src = _index_of(lines, needle)
    moved, rest = lines[src], lines[:src] + lines[src + 1:]
    dst = _index_of(rest, after)
    return rest[:dst + 1] + [moved] + rest[dst + 1:]


def test_c2_NEGATIVE_CONTROL_the_order_check_follows_the_read_line_in_the_entry_file():
    """The ordering checker must still measure something now that the review text is in a reference.

    Two mutants of the live SKILL.md, each differing from it by ONE line of its Step 6 section:
    the read line moved BELOW the deletion (the review would then be read after the files it keys on
    are gone), and the read line removed (the review would never be read at all). Both must fail."""
    entry = DOC.read_text(encoding="utf-8").splitlines()
    reference = skill_corpus.read("forge", CLOSE_OUT_REF, root=SKILLS).splitlines()
    _check_review_precedes_deletion(_step6_as_read(entry, reference))             # the live doc passes

    start = entry.index(CLOSE_OUT_HEADING)
    read_at = start + 1 + _index_of(entry[start + 1:], CLOSE_OUT_REF)
    assert _index_of(entry, DELETION_LINE) > read_at                              # the mutants differ from it

    late = entry[:start] + _moved(entry[start:], CLOSE_OUT_REF, DELETION_LINE)
    with pytest.raises(AssertionError, match="BEFORE the deletion"):
        _check_review_precedes_deletion(_step6_as_read(late, reference))

    unnamed = entry[:read_at] + entry[read_at + 1:]
    with pytest.raises(AssertionError, match="no advisory code review step"):
        _check_review_precedes_deletion(_step6_as_read(unnamed, reference))


def test_c2_the_numbered_checklist_names_the_review_before_the_deletion():
    """Item 11 is the summary a reader skims instead of Step 6, so the ordering has to be
    visible there too -- the same argument that keeps the cycle-id and size lifecycles in one
    paragraph. A summary that omits the review is how a mandatory step becomes an optional one.
    """
    lines = DOC.read_text(encoding="utf-8").splitlines()
    item = next((line for line in lines if line.startswith("11. ")), None)
    assert item is not None, "the numbered forge checklist has no item 11"
    assert "review" in item.lower(), f"item 11 does not name the review: {item!r}"
    assert item.lower().index("review") < item.index(".forge/cycle-id"), (
        f"item 11 names the deletion before the review: {item!r}")


def test_c2_the_hard_rules_checklist_carries_the_trigger():
    """L8's sub-choice, taken: the REVIEW / COMPLETION section of the main loop's own
    pre-completion nudge gains the trigger line. A trigger nobody reads is not a trigger.

    Pinned HERE rather than in a _meta test because the two halves have to move together:
    this file already owns the forge close-out prose, and a trigger that named a step forge
    had dropped (or vice versa) is exactly the drift a single owner prevents.
    """
    checklist = META / "hard-rules-checklist.md"
    lines = checklist.read_text(encoding="utf-8").splitlines()
    start = _index_of(lines, "### REVIEW / COMPLETION")
    assert start is not None, f"no REVIEW / COMPLETION section in {checklist}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")), len(lines))
    section = "\n".join(lines[start:end])
    for token in ("advisory code review", "before", ".forge/cycle-id"):
        assert token.lower() in section.lower(), (
            f"the REVIEW / COMPLETION section does not carry {token!r}")
