#!/usr/bin/env python3
"""test_live_home_guard.py - the live-HOME guard (#282 H2 "Live-HOME tests", plan K23).

No test here writes, or can write, the real home:

  * CHECK API. The positive controls point the guard's real-home root at a tmp "real home"
    (LiveHomeGuard(<tmp>)) and ask arm (i) about SIMULATED audit events and arm (ii) about snapshots
    of that tmp tree. The dispatch tests drive a PRIVATE runtime, never the running session's guard.
  * END TO END. Child pytest sessions run the shipped conftest.py + live_home_guard.py (copied into a
    tmp suite) with HOME - and so the child's captured real home - at a tmp dir.
  * SENTINELS. This session has the plugin registered; a collect-only child of each guarded suite
    (skills/_meta, skills/avengers, skills/forge, and all three together) prints the guard's header.

Run:
    pytest skills/_meta/tests/test_live_home_guard.py -v
"""
from __future__ import annotations

import importlib.util
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

_HERE = Path(__file__).resolve().parent
_SKILLS = _HERE.parents[1]
_GUARD_FILE = _HERE / "live_home_guard.py"
_CONFTEST_FILE = _HERE / "conftest.py"
_GUARD_NAME = "foundry_live_home_guard"


def _load_guard():
    module = sys.modules.get(_GUARD_NAME)
    if module is None:
        spec = importlib.util.spec_from_file_location(_GUARD_NAME, _GUARD_FILE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_GUARD_NAME] = module
        spec.loader.exec_module(module)
    return module


lhg = _load_guard()

W_CREATE = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
CHILD_TIMEOUT_S = 180


def _tops(home):
    return Path(home) / ".claude" / "state" / "seat-model-tops.json"


def _store(home, slug="x"):
    return Path(home) / ".claude" / "projects" / slug / "astra-budget.jsonl"


# --------------------------------------------------------------------------- #
# Check API - arm (i), the audit decision
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode,flags", [
    ("w", W_CREATE),
    ("a", os.O_WRONLY | os.O_CREAT | os.O_APPEND),
    ("x", os.O_WRONLY | os.O_CREAT | os.O_EXCL),
    ("r+", os.O_RDWR),
    (None, os.O_WRONLY | os.O_CREAT),          # the os.open form: no mode string
])
def test_arm_i_reports_a_simulated_tops_write_under_the_monkeypatched_real_home(tmp_path, mode, flags):
    fake = tmp_path / "real-home"
    guard = lhg.LiveHomeGuard(fake)
    target = _tops(fake)
    for spelled in (str(target), target, os.fsencode(str(target))):
        hit = guard.check_audit("open", (spelled, mode, flags))
        assert hit is not None, spelled
        label, path = hit
        assert label.startswith("open(") and path == os.path.abspath(str(target))


def test_arm_i_reports_the_creation_of_a_budget_store_its_lock_and_the_pins_file(tmp_path):
    fake = tmp_path / "real-home"
    guard = lhg.LiveHomeGuard(fake)
    for target in (_store(fake), _store(fake, "-tmp-pytest-of-user"),
                   _store(fake).with_name("astra-budget.jsonl.lock"),
                   fake / ".claude" / "state" / "seat-model-pins.json",
                   fake / ".claude" / "state" / "seat-model-tops.json.lock"):
        assert guard.check_audit("open", (str(target), "a+", os.O_RDWR | os.O_CREAT | os.O_APPEND)) is not None
        assert guard.is_protected(target)


def test_arm_i_reports_a_rename_or_replace_onto_a_protected_path(tmp_path):
    fake = tmp_path / "real-home"
    guard = lhg.LiveHomeGuard(fake)
    source = tmp_path / "staged.json"
    for event in ("os.replace", "os.rename"):
        assert guard.check_audit(event, (str(source), str(_tops(fake)), None, None)) == (
            f"{event} destination", os.path.abspath(str(_tops(fake))))
        assert guard.check_audit(event, (str(_store(fake)), str(source), None, None)) is None  # a source is no write


def test_arm_i_negative_controls(tmp_path):
    fake = tmp_path / "real-home"
    guard = lhg.LiveHomeGuard(fake)
    temp_home = tmp_path / "temp-home"
    # a write under the TEST's temp HOME, not the real home
    assert guard.check_audit("open", (str(_tops(temp_home)), "w", W_CREATE)) is None
    assert guard.check_audit("open", (str(_store(temp_home)), "a", os.O_WRONLY | os.O_CREAT)) is None
    # a READ of a protected path
    assert guard.check_audit("open", (str(_tops(fake)), "r", os.O_RDONLY)) is None
    assert guard.check_audit("open", (str(_store(fake)), "rb", os.O_RDONLY)) is None
    # a NEW unprotected state file under the real home
    assert guard.check_audit("open", (str(fake / ".claude" / "state" / "other.json"), "w", W_CREATE)) is None
    # near misses: wrong depth, a file descriptor, an unrelated event
    assert guard.check_audit("open", (str(fake / ".claude" / "state" / "sub" / "seat-model-tops.json"), "w", W_CREATE)) is None
    assert guard.check_audit("open", (str(fake / ".claude" / "projects" / "astra-budget.jsonl"), "w", W_CREATE)) is None
    assert guard.check_audit("open", (str(fake / ".claude" / "projects" / "a" / "b" / "astra-budget.jsonl"), "w", W_CREATE)) is None
    assert guard.check_audit("open", (7, "w", W_CREATE)) is None
    assert guard.check_audit("os.remove", (str(_tops(fake)),)) is None


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="POSIX symlinks")
def test_arm_i_sees_a_write_through_a_symlinked_directory(tmp_path):
    fake = tmp_path / "real-home"
    (fake / ".claude" / "state").mkdir(parents=True)
    link = tmp_path / "link-to-state"
    link.symlink_to(fake / ".claude" / "state", target_is_directory=True)
    guard = lhg.LiveHomeGuard(fake)
    assert guard.check_audit("open", (str(link / "seat-model-tops.json"), "w", W_CREATE)) is not None


# --------------------------------------------------------------------------- #
# Check API - arm (ii), the stat snapshot
# --------------------------------------------------------------------------- #
def test_arm_ii_reports_the_creation_modification_and_deletion_of_protected_files(tmp_path):
    fake = tmp_path / "real-home"
    guard = lhg.LiveHomeGuard(fake)
    tops, store = _tops(fake), _store(fake)
    tops.parent.mkdir(parents=True)
    store.parent.mkdir(parents=True)
    before = guard.snapshot()
    assert before == {}
    tops.write_text("{}", encoding="utf-8")            # the tmp "real home", never the real one
    store.write_text("{}\n", encoding="utf-8")
    created = guard.snapshot()
    assert [(c.change, c.path) for c in guard.compare(before, created)] == sorted(
        [("created", str(store)), ("created", str(tops))], key=lambda item: item[1])
    staged = tmp_path / "staged.json"
    staged.write_text('{"tops": {}}', encoding="utf-8")
    os.replace(staged, tops)                            # a new inode and size
    store.unlink()
    changed = guard.snapshot()
    assert {(c.change, c.path) for c in guard.compare(created, changed)} == {
        ("modified", str(tops)), ("deleted", str(store))}
    # the synthetic form: no file at all
    assert guard.compare({}, {str(tops): (1, 2, 3)}) == [lhg.StatChange("created", str(tops), None, (1, 2, 3))]


def test_arm_ii_negative_controls(tmp_path):
    fake = tmp_path / "real-home"
    guard = lhg.LiveHomeGuard(fake)
    (fake / ".claude" / "state").mkdir(parents=True)
    pins = fake / ".claude" / "state" / "seat-model-pins.json"
    pins.write_text("{}", encoding="utf-8")
    before = guard.snapshot()
    (fake / ".claude" / "state" / "other.json").write_text("{}", encoding="utf-8")   # unprotected
    _tops(tmp_path / "temp-home").parent.mkdir(parents=True)
    _tops(tmp_path / "temp-home").write_text("{}", encoding="utf-8")                  # another home
    assert pins.read_text(encoding="utf-8") == "{}"                                   # a read
    assert guard.compare(before, guard.snapshot()) == []


# --------------------------------------------------------------------------- #
# Dispatch and windows, on a PRIVATE runtime
# --------------------------------------------------------------------------- #
def _runtime(fake, mode):
    rt = lhg._Runtime()
    rt.start(fake)
    rt.mode = mode
    return rt


def test_enforce_refuses_the_write_and_records_it_for_the_open_window(tmp_path):
    fake = tmp_path / "real-home"
    rt = _runtime(fake, "enforce")
    frame = lhg.open_window(rt, "suite/test_x.py::test_writer")
    with pytest.raises(PermissionError) as err:
        lhg.dispatch_audit(rt, "open", (str(_tops(fake)), "w", W_CREATE))
    assert "live-home-guard" in str(err.value) and str(err.value).isascii()
    found = lhg.close_window(rt, frame)
    assert found == [lhg.Violation("suite/test_x.py::test_writer", lhg.ARM_AUDIT,
                                   f"open(mode='w', flags={W_CREATE:#x})", os.path.abspath(str(_tops(fake))))]
    assert not _tops(fake).exists()                                   # dispatch itself never writes
    # CONTROLS: an unprotected path, a read, and an inactive runtime record nothing and raise nothing
    frame = lhg.open_window(rt, "suite/test_x.py::test_clean")
    lhg.dispatch_audit(rt, "open", (str(fake / ".claude" / "state" / "other.json"), "w", W_CREATE))
    lhg.dispatch_audit(rt, "open", (str(_tops(fake)), "r", os.O_RDONLY))
    assert lhg.close_window(rt, frame) == []
    rt.stop()
    lhg.dispatch_audit(rt, "open", (str(_tops(fake)), "w", W_CREATE))
    assert rt.pending == []


def test_report_mode_records_without_refusing(tmp_path):
    fake = tmp_path / "real-home"
    rt = _runtime(fake, "report")
    frame = lhg.open_window(rt, "t::report")
    lhg.dispatch_audit(rt, "os.replace", (str(tmp_path / "a"), str(_store(fake)), None, None))   # no raise
    found = lhg.close_window(rt, frame)
    assert [(v.arm, v.event) for v in found] == [(lhg.ARM_AUDIT, "os.replace destination")]
    assert rt.recorded == found


def test_a_stat_change_is_reported_once_and_explains_the_session_comparison(tmp_path):
    fake = tmp_path / "real-home"
    _store(fake).parent.mkdir(parents=True)
    rt = _runtime(fake, "enforce")
    outer = lhg.open_window(rt, "collect:suite")
    inner = lhg.open_window(rt, "collect:suite/test_m.py")
    _store(fake).write_text("row\n", encoding="utf-8")
    assert [(v.owner, v.arm, v.event) for v in lhg.window_violations(rt, inner)] == [
        ("collect:suite/test_m.py", lhg.ARM_STAT, "created")]
    assert lhg.window_violations(rt, inner) == []          # the same change is not reported twice
    assert lhg.close_window(rt, inner) == []
    assert lhg.close_window(rt, outer) == []               # nor by the enclosing window
    assert lhg.session_violations(rt) == []                # explained
    # CONTROL: a change outside every window is a session violation
    _tops(fake).parent.mkdir(parents=True)
    _tops(fake).write_text("{}", encoding="utf-8")
    assert [(v.owner, v.arm, v.event) for v in lhg.session_violations(rt)] == [
        (lhg.OWNER_SESSION, lhg.ARM_STAT, "created")]


def test_messages_are_ascii():
    violation = lhg.Violation("t::café", lhg.ARM_STAT, "created", "/höme/.claude/state/seat-model-tops.json")
    assert violation.line().isascii()
    assert lhg.failure_text([violation]).isascii()


# --------------------------------------------------------------------------- #
# Isolation helpers
# --------------------------------------------------------------------------- #
def test_empty_live_home_fixture_is_empty_has_a_stub_codex_first_and_is_not_the_real_home(empty_live_home):
    assert Path.home() == empty_live_home
    assert list(empty_live_home.iterdir()) == []
    codex = shutil.which("codex")
    assert codex is not None and Path(codex).parent == Path(os.environ["PATH"].split(os.pathsep)[0])
    assert os.path.realpath(str(Path.home())) != os.path.realpath(str(lhg.real_home()))


def test_empty_home_restores_the_environment_and_removes_its_tree(tmp_path, monkeypatch):
    saved = {var: os.environ.get(var) for var in ("HOME", "USERPROFILE", "PATH")}
    with lhg.empty_home() as home:
        assert Path.home() == home and list(home.iterdir()) == []
        assert Path(shutil.which("codex")).parent == home.parent / "bin"
        stub = subprocess.run([shutil.which("codex"), "exec"], capture_output=True, text=True, timeout=30) \
            if os.name != "nt" else None
        if stub is not None:
            assert stub.returncode == 2 and "no model call" in stub.stderr
    assert {var: os.environ.get(var) for var in saved} == saved
    assert not home.parent.exists()
    # import_under_empty_home imports under that HOME (CONTROL: a cached module is returned untouched)
    (tmp_path / "lhg_probe_module.py").write_text(
        "from pathlib import Path\nHOME_AT_IMPORT = Path.home()\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "lhg_probe_module", raising=False)
    probe = lhg.import_under_empty_home("lhg_probe_module")
    assert probe.HOME_AT_IMPORT != Path.home() and probe.HOME_AT_IMPORT.name == "home"
    assert lhg.import_under_empty_home("lhg_probe_module") is probe
    monkeypatch.delitem(sys.modules, "lhg_probe_module")


def test_import_under_empty_home_moves_only_the_target_and_names_an_unlisted_dependency(tmp_path, monkeypatch):
    """Only the target's import-time work runs under the empty HOME: a preloaded dependency keeps the
    session HOME. CONTROL: an unlisted skills-tree dependency first imported inside the window is an
    ImportError naming it (it would stay bound to a deleted temp HOME)."""
    tree = tmp_path / "tree"
    tree.mkdir()
    for suffix in ("", "2"):
        (tree / f"lhg_dep{suffix}.py").write_text(
            "from pathlib import Path\nHOME_AT_IMPORT = Path.home()\n", encoding="utf-8")
        (tree / f"lhg_target{suffix}.py").write_text(
            f"from pathlib import Path\nimport lhg_dep{suffix}\nHOME_AT_IMPORT = Path.home()\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tree))
    monkeypatch.setattr(lhg, "_SKILLS_ROOT", tree)
    for name in ("lhg_dep", "lhg_target", "lhg_dep2", "lhg_target2"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    target = lhg.import_under_empty_home("lhg_target", preload=("lhg_dep", "lhg_absent_dependency"))
    assert sys.modules["lhg_dep"].HOME_AT_IMPORT == Path.home()          # the session HOME
    assert target.HOME_AT_IMPORT != Path.home() and target.HOME_AT_IMPORT.name == "home"
    with pytest.raises(ImportError, match="lhg_dep2"):
        lhg.import_under_empty_home("lhg_target2")
    for name in ("lhg_dep", "lhg_target", "lhg_dep2", "lhg_target2"):
        monkeypatch.delitem(sys.modules, name, raising=False)


_AUDIT_IMPORT_PROBE = '''\
import importlib.util, json, sys
guard_file, meta, mode = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("foundry_live_home_guard", guard_file)
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)
if mode == "helper":
    aud = guard.import_audit_spawn()
else:
    sys.path.insert(0, meta)
    import audit_spawn as aud
import codex_model, trusted_runner, write
print(json.dumps({
    "models_cache": str(codex_model.MODELS_CACHE_PATH),
    "inventory": str(trusted_runner.DEFAULT_INVENTORY_PATH),
    "rollup": str(write.GLOBAL_ROLLUP_PATH),
    "codex_model": aud.CODEX_PIN.model,
}))
'''


def _fixture_roster_home(home):
    """A HOME holding a fresh fixture codex roster, so resolving the codex reviewer records a TOP."""
    (home / ".codex").mkdir(parents=True)
    (home / ".claude" / "state").mkdir(parents=True)
    efforts = [{"effort": e, "description": e} for e in ("low", "medium", "high", "xhigh", "max")]
    doc = {
        "fetched_at": datetime.fromtimestamp(time.time() - 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "client_version": "0.154.0",
        "models": [
            {"slug": "gpt-fixture-top", "priority": 1, "visibility": "list", "supported_in_api": True,
             "supported_reasoning_levels": efforts, "upgrade": None},
            {"slug": "gpt-5.6-sol", "priority": 4, "visibility": "list", "supported_in_api": True,
             "supported_reasoning_levels": efforts, "upgrade": None},
        ],
    }
    (home / ".codex" / "models_cache.json").write_text(json.dumps(doc), encoding="utf-8")


def test_import_audit_spawn_records_no_top_and_keeps_its_dependencies_on_the_session_home(tmp_path):
    """The #282 collection-time hazard, reproduced in a child process whose HOME is a tmp tree with a
    codex roster: a PLAIN `import audit_spawn` records seat-model-tops.json (CONTROL); the helper does
    not, and codex_model / trusted_runner / write stay bound to the session HOME."""
    results = {}
    for mode in ("plain", "helper"):
        home = tmp_path / f"session-home-{mode}"
        _fixture_roster_home(home)
        proc = subprocess.run(
            [sys.executable, "-c", _AUDIT_IMPORT_PROBE, str(_GUARD_FILE), str(_HERE.parent), mode],
            cwd=str(tmp_path), env=_child_env(home), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=CHILD_TIMEOUT_S)
        assert proc.returncode == 0, proc.stderr
        results[mode] = (home, json.loads(proc.stdout.strip().splitlines()[-1]))
    home, plain = results["plain"]
    assert _tops(home).exists(), "CONTROL: a plain import under a roster HOME records a TOP"
    assert plain["codex_model"] == "gpt-fixture-top"
    home, helper = results["helper"]
    assert not _tops(home).exists(), "import_audit_spawn() wrote the session HOME's tops record"
    assert helper["codex_model"] != "gpt-fixture-top"                     # resolved under the empty HOME
    assert helper["models_cache"] == str(home / ".codex" / "models_cache.json")
    assert helper["inventory"] == str(home / ".claude" / "state" / "inventory.json")
    assert helper["rollup"] == str(home / ".claude" / "state" / "observations.jsonl")


def test_the_isolation_assertion_fires_on_the_real_home(monkeypatch):
    monkeypatch.setenv("HOME", str(lhg.real_home()))
    monkeypatch.setenv("USERPROFILE", str(lhg.real_home()))
    with pytest.raises(AssertionError, match="isolation failed"):
        lhg.assert_not_real_home()


# --------------------------------------------------------------------------- #
# End to end: child sessions with the shipped conftest and a tmp real home
# --------------------------------------------------------------------------- #
_CHILD_TESTS = '''\
import os
import subprocess
import sys
from pathlib import Path


def _state():
    return Path.home() / ".claude" / "state"


def _store(slug):
    return Path.home() / ".claude" / "projects" / slug / "astra-budget.jsonl"


def test_in_process_tops_write():
    try:
        (_state() / "seat-model-tops.json").write_text("{}", encoding="utf-8")
    except PermissionError:
        pass


def test_replace_onto_a_budget_store(tmp_path):
    store = _store("-tmp-pytest-slug")
    store.parent.mkdir(parents=True, exist_ok=True)
    staged = tmp_path / "row.jsonl"
    staged.write_text("row\\n", encoding="utf-8")
    try:
        os.replace(staged, store)
    except PermissionError:
        pass


def test_child_process_creates_a_budget_store():
    store = _store("-tmp-child-slug")
    store.parent.mkdir(parents=True, exist_ok=True)
    code = "import sys; open(sys.argv[1], 'w', encoding='utf-8').write('row')"
    subprocess.run([sys.executable, "-c", code, str(store)], check=True)


def test_unprotected_write_and_a_protected_read():
    (_state() / "other.json").write_text("{}", encoding="utf-8")
    assert (_state() / "seat-model-pins.json").read_text(encoding="utf-8") == "{}"
'''

_CHILD_COLLECT = '''\
from pathlib import Path

(Path.home() / ".claude" / "state" / "seat-model-tops.json").write_text("{}", encoding="utf-8")


def test_never_reached_in_enforce():
    pass
'''

_CHILD_SESSION_CONFTEST_TAIL = '''

def pytest_collection_finish(session):
    import subprocess, sys
    from pathlib import Path
    store = Path.home() / ".claude" / "projects" / "-outside-windows" / "astra-budget.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    code = "import sys; open(sys.argv[1], 'w', encoding='utf-8').write('row')"
    subprocess.run([sys.executable, "-c", code, str(store)], check=True)
'''


def _child_suite(tmp_path, files, conftest_tail=""):
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(_GUARD_FILE, suite / "live_home_guard.py")
    conftest = _CONFTEST_FILE.read_text(encoding="utf-8") + conftest_tail
    (suite / "conftest.py").write_text(conftest, encoding="utf-8")
    (suite / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name, text in files.items():
        (suite / name).write_text(text, encoding="utf-8")
    home = tmp_path / "child-real-home"
    (home / ".claude" / "state").mkdir(parents=True)
    (home / ".claude" / "state" / "seat-model-pins.json").write_text("{}", encoding="utf-8")
    return suite, home


def _child_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE="1")
    return env


def _run_child(cwd, home, *args):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rA", *args],
        cwd=str(cwd), env=_child_env(home), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=CHILD_TIMEOUT_S)
    return proc.returncode, proc.stdout + proc.stderr


def _outcomes(output):
    return dict((m.group(2), m.group(1)) for m in re.finditer(
        r"^(PASSED|FAILED|ERROR) \S*?::(\w+)", output, re.MULTILINE))


def _guard_lines(output):
    return [line.strip() for line in output.splitlines() if " | arm " in line]


def test_enforce_fails_each_writer_names_path_and_event_and_keeps_in_process_writes_out(tmp_path):
    suite, home = _child_suite(tmp_path, {"test_writes.py": _CHILD_TESTS})
    rc, out = _run_child(suite, home)
    assert rc == 1, out
    assert _outcomes(out) == {
        "test_in_process_tops_write": "FAILED",
        "test_replace_onto_a_budget_store": "FAILED",
        "test_child_process_creates_a_budget_store": "FAILED",
        "test_unprotected_write_and_a_protected_read": "PASSED",       # NEGATIVE CONTROL
    }, out
    lines = _guard_lines(out)
    tops = str(_tops(home))
    assert any(l.startswith("test_writes.py::test_in_process_tops_write | arm audit | open(mode='w'")
               and l.endswith(tops) for l in lines), out
    # os.replace raises the "os.rename" audit event (CPython routes both through one rename)
    assert any("test_replace_onto_a_budget_store | arm audit | os.rename destination | "
               + str(_store(home, "-tmp-pytest-slug")) in l for l in lines), out
    assert any("test_child_process_creates_a_budget_store | arm stat | created | "
               + str(_store(home, "-tmp-child-slug")) in l for l in lines), out
    assert not _tops(home).exists() and not _store(home, "-tmp-pytest-slug").exists()   # refused in process
    assert _store(home, "-tmp-child-slug").exists()               # a child's write lands; arm (ii) reports it
    assert "live-home-guard: enforce; real home" in out and "3 violation(s)" in out
    assert (home / ".claude" / "state" / "seat-model-pins.json").read_text(encoding="utf-8") == "{}"


def test_report_mode_lists_every_writer_and_changes_no_outcome(tmp_path):
    suite, home = _child_suite(tmp_path, {"test_writes.py": _CHILD_TESTS})
    rc, out = _run_child(suite, home, "--live-home-guard=report")
    assert rc == 0, out
    assert set(_outcomes(out).values()) == {"PASSED"}, out
    events = {(l.split(" | ")[0].split("::")[-1], l.split(" | ")[1], l.split(" | ")[2].split("(")[0])
              for l in _guard_lines(out)}
    assert events == {
        ("test_in_process_tops_write", "arm audit", "open"),
        ("test_in_process_tops_write", "arm stat", "created"),
        ("test_replace_onto_a_budget_store", "arm audit", "os.rename destination"),
        ("test_replace_onto_a_budget_store", "arm stat", "created"),
        ("test_child_process_creates_a_budget_store", "arm stat", "created"),
    }, out
    assert _tops(home).exists() and _store(home, "-tmp-pytest-slug").exists()   # report never refuses
    assert "live-home-guard: report; real home" in out


def test_a_collection_time_write_fails_collection_in_enforce_and_is_listed_in_report(tmp_path):
    suite, home = _child_suite(tmp_path, {"test_collect_write.py": _CHILD_COLLECT})
    rc, out = _run_child(suite, home)
    assert rc != 0, out
    assert "ERROR collecting test_collect_write.py" in out or "ERROR test_collect_write.py" in out, out
    assert any(l.startswith("collect:test_collect_write.py | arm audit | open(") for l in _guard_lines(out)), out
    assert not _tops(home).exists()
    rc, out = _run_child(suite, home, "--live-home-guard=report")        # CONTROL: report mode
    assert rc == 0, out
    assert any(l.startswith("collect:test_collect_write.py | arm") for l in _guard_lines(out)), out


def test_a_write_outside_every_window_turns_a_green_session_red(tmp_path):
    suite, home = _child_suite(tmp_path, {"test_clean.py": "def test_clean():\n    pass\n"},
                               conftest_tail=_CHILD_SESSION_CONFTEST_TAIL)
    rc, out = _run_child(suite, home)
    assert _outcomes(out) == {"test_clean": "PASSED"}, out
    assert rc == 1, out
    assert any(l.startswith("session | arm stat | created | ") for l in _guard_lines(out)), out
    rc, out = _run_child(suite, home, "--live-home-guard=report")        # CONTROL: report keeps it green
    assert rc == 0, out


# --------------------------------------------------------------------------- #
# Sentinels: the guard is registered in each guarded suite's session
# --------------------------------------------------------------------------- #
def test_the_guard_is_registered_in_this_session(request):
    plugin = request.config.pluginmanager.get_plugin(lhg.PLUGIN_NAME)
    assert plugin is not None
    rt = lhg.runtime()
    assert rt.active and rt.mode in lhg.MODES and "_meta/tests" in rt.registrants
    assert lhg._HOOK_INSTALLED[0] is True
    assert os.path.realpath(str(lhg.real_home())) == os.path.realpath(str(Path.home()))


@pytest.mark.parametrize("suites", [("_meta",), ("avengers",), ("forge",), ("_meta", "avengers", "forge")])
def test_each_guarded_suite_session_registers_the_guard(tmp_path, suites):
    home = tmp_path / "home"
    home.mkdir()
    args = ["--collect-only", "--ignore-glob=*test_*.py"] + [str(_SKILLS / name / "tests") for name in suites]
    rc, out = _run_child(tmp_path, home, *args)
    assert rc in (0, 5), out                                   # 5: nothing collected, by design
    header = [line for line in out.splitlines() if line.startswith("live-home-guard: enforce (real home")]
    assert len(header) == 1, out
    assert repr(str(home)) in header[0] or ascii(str(home)) in header[0], out
    for name in suites:
        assert f"{name}/tests" in header[0], out
    assert "already added" not in out
