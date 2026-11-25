#!/usr/bin/env python3
"""smart-config -- test_model_policy.py (S081 WP-301).

Regression coverage for three resolver defects recorded in the S080 codex-model-pinning
design (section 3 D8/D9, section 5 item 2):

  * ALIAS TABLE. The alias -> full-id VALUES had rotted and their only consumer was the
    "unknown model id" warning. The table is now a KEY SET; a former full-id value is an
    unknown id like any other and is warned about (it still passes through).
  * D8. A non-mapping policy shape on the resolve path (`tiers: [complex]` and its
    siblings) raised AttributeError -> exit 1 with EMPTY stdout, breaking the
    "resolve exits 0 on every path" contract. It now warns and falls through.
  * D9. A v1 agent pin is a claude-code-scoped scalar, but it was applied to every
    `--host`. On any host other than claude-code it is now SKIPPED, the host-keyed tier
    path resolves instead, and a warning names the pin, the agent and the host.

Isolation: every resolve runs the script as a subprocess with HOME/USERPROFILE pointed at
a tmp dir (so the GLOBAL layer is a tmp file), cwd inside tmp, `--project-root` at a tmp
project, and `--no-log`. The live ~/.claude/model-policy.yaml and the model-decisions
logs are never read or written. Each guarantee is paired with a control that passes on
both the old and the new resolver, so a RED result cannot come from a broken harness.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# The resolver's layers are YAML; without PyYAML every layer is skipped (fail-open) and
# these tests would assert against inheritance instead of the policy they wrote.
pytest.importorskip("yaml")

_RESOLVER = Path(__file__).resolve().parent.parent / "scripts" / "model_policy.py"

# The complex leaf is `haiku` only so the three leaves are distinguishable; it is a routing
# fixture, not a recommendation. It must not be a benched family (#291): a benched leaf is
# replaced with a warning, and this control asserts a SILENT resolve.
WELL_FORMED = (
    "version: 1\n"
    "tiers:\n"
    "  complex: {claude-code: haiku, codex: gpt-5.6-sol}\n"
    "  medium: {claude-code: opus}\n"
    "agents:\n"
    "  bob: opus[1m]\n"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("smart_config_model_policy", _RESOLVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path, *args, global_policy=None, project_policy=None):
    """Run `model_policy.py resolve` fully sandboxed; return the CompletedProcess."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    proj.mkdir(parents=True, exist_ok=True)
    if global_policy is not None:
        (home / ".claude" / "model-policy.yaml").write_text(global_policy, encoding="utf-8")
    if project_policy is not None:
        (proj / ".claude").mkdir(parents=True, exist_ok=True)
        (proj / ".claude" / "model-policy.yaml").write_text(project_policy, encoding="utf-8")
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)  # os.path.expanduser reads this on Windows
    return subprocess.run(
        [sys.executable, str(_RESOLVER), "resolve", "--project-root", str(proj), "--no-log", *args],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


def _resolve(tmp_path, *args, **layers):
    """Resolve and enforce the contract every path must keep: exit 0, one JSON object."""
    proc = _run(tmp_path, *args, **layers)
    assert proc.returncode == 0, f"resolve exited {proc.returncode}; stderr:\n{proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one JSON line on stdout, got {proc.stdout!r}"
    out = json.loads(lines[0])
    assert out["ok"] is True
    return out, proc


# --------------------------------------------------------------------------- #
# Alias table -> key set
# --------------------------------------------------------------------------- #
def test_aliases_is_a_key_set_not_a_mapping():
    mod = _load_module()
    assert not isinstance(mod.ALIASES, dict)
    assert set(mod.ALIASES) == {"fable", "opus", "sonnet", "haiku"}


def test_module_carries_no_versioned_claude_full_id():
    # The rot this WP removes: a family alias pinned to a dated/versioned full id.
    # Aliases auto-upgrade; a versioned id in this module is a scheduled second rot.
    text = _RESOLVER.read_text(encoding="utf-8")
    assert re.findall(r"claude-(?:fable|opus|sonnet|haiku)-\d", text) == []


@pytest.mark.parametrize("alias", ["opus", "sonnet", "haiku", "opus[1m]"])
def test_known_alias_resolves_silently(tmp_path, alias):
    # A benched alias is still a KEY of the set but never resolves silently: see the
    # #291 section below (test_benched_value_is_replaced_by_the_main_tier_on_every_layer).
    policy = f'version: 1\ntiers:\n  complex: {{claude-code: "{alias}"}}\n'
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "headless", global_policy=policy)
    assert out["model"] == alias
    assert out["warnings"] == []


@pytest.mark.parametrize("value", ["claude-opus-4-8", "claude-sonnet-4-6", "claude-nova-9"])
def test_non_key_value_is_warned_and_passed_through(tmp_path, value):
    # claude-opus-4-8 was a VALUE of the deleted table: with only keys left it is an
    # unknown id like any other. Passthrough, never an error. (The table's other former
    # value was a full id of a family the roster now benches; that one is REPLACED, not
    # passed through -- test_benched_value_is_replaced_by_the_main_tier_on_every_layer.)
    policy = f"version: 1\ntiers:\n  complex: {{claude-code: {value}}}\n"
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "headless", global_policy=policy)
    assert out["model"] == value
    assert any("unknown model id" in w and value in w for w in out["warnings"]), out["warnings"]


# --------------------------------------------------------------------------- #
# D8 -- non-mapping shapes never break the exit-0 contract
# --------------------------------------------------------------------------- #
def test_well_formed_policy_control(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "headless", global_policy=WELL_FORMED)
    assert (out["model"], out["tier"], out["source"], out["warnings"]) == ("haiku", "complex", "global", [])


@pytest.mark.parametrize("layer", ["global_policy", "project_policy"])
def test_list_shaped_tiers_falls_through_to_default_tier(tmp_path, layer):
    # On the project layer the list REPLACES the global mapping (scalars replace on merge),
    # so both layers reach the same broken shape.
    layers = {layer: "version: 1\ntiers: [complex]\n"}
    if layer == "project_policy":
        layers["global_policy"] = WELL_FORMED
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "headless", **layers)
    assert out["tier_requested"] == "complex"
    assert out["tier"] == "medium"  # builtin defaults.tier
    assert out["model"] is None  # inherit
    assert any("tiers" in w and "not a mapping" in w for w in out["warnings"]), out["warnings"]


@pytest.mark.parametrize(
    "policy, args, fragment",
    [
        ("version: 1\ndefaults: [medium]\n", ("--surface", "headless"), "defaults"),
        ("version: 1\ndefaults: {tier: [medium]}\n", ("--surface", "headless"), "defaults.tier"),
        ("version: 1\nagents: [bob]\n", ("--tier", "complex", "--surface", "headless", "--agent", "bob"), "agents"),
    ],
    ids=["defaults-list", "defaults-tier-list", "agents-list"],
)
def test_sibling_non_mapping_shapes_keep_exit_zero(tmp_path, policy, args, fragment):
    out, _ = _resolve(tmp_path, *args, global_policy=policy)
    assert out["model"] is None
    assert any(w.startswith(fragment) for w in out["warnings"]), out["warnings"]


def test_unhashable_version_across_layers_keeps_exit_zero(tmp_path):
    out, _ = _resolve(
        tmp_path, "--tier", "complex", "--surface", "headless",
        global_policy="version: [1]\ntiers:\n  complex: {claude-code: haiku}\n",
        project_policy="version: 1\n",
    )
    assert out["model"] == "haiku"
    assert any("version mismatch" in w for w in out["warnings"]), out["warnings"]


# --------------------------------------------------------------------------- #
# D9 -- v1 agent pins are claude-code-scoped
# --------------------------------------------------------------------------- #
def test_agent_pin_applies_on_claude_code_host(tmp_path):
    out, proc = _resolve(
        tmp_path, "--tier", "complex", "--surface", "headless", "--agent", "bob", "--host", "claude-code",
        global_policy=WELL_FORMED,
    )
    assert (out["model"], out["source"]) == ("opus[1m]", "agent-pin")
    assert out["warnings"] == []
    assert "skipped" not in proc.stderr


@pytest.mark.parametrize("layer, source", [("global_policy", "global"), ("project_policy", "project")])
def test_agent_pin_skipped_on_other_host(tmp_path, layer, source):
    out, proc = _resolve(
        tmp_path, "--tier", "complex", "--surface", "headless", "--agent", "bob", "--host", "codex",
        **{layer: WELL_FORMED},
    )
    assert out["model"] == "gpt-5.6-sol"  # the host-keyed tier path, not the Claude pin
    assert out["source"] == source  # what actually happened, not "agent-pin"
    skip = [w for w in out["warnings"] if "skipped" in w]
    assert len(skip) == 1, out["warnings"]
    for name in ("agents.bob", "opus[1m]", "codex"):
        assert name in skip[0]
    assert "agents.bob" in proc.stderr and "codex" in proc.stderr  # loud: also on stderr


def test_agent_pin_skipped_on_host_without_tier_entry_inherits(tmp_path):
    out, _ = _resolve(
        tmp_path, "--tier", "medium", "--surface", "headless", "--agent", "bob", "--host", "vscode-copilot",
        global_policy=WELL_FORMED,
    )
    assert out["model"] is None  # medium has no vscode-copilot leaf -> inherit
    assert out["source"] == "global"
    assert any("skipped" in w and "vscode-copilot" in w for w in out["warnings"]), out["warnings"]


def test_unpinned_agent_on_other_host_has_no_skip_warning(tmp_path):
    out, proc = _resolve(
        tmp_path, "--tier", "complex", "--surface", "headless", "--agent", "alf", "--host", "codex",
        global_policy=WELL_FORMED,
    )
    assert out["model"] == "gpt-5.6-sol"
    assert not any("skipped" in w for w in out["warnings"])
    assert "skipped" not in proc.stderr


# --------------------------------------------------------------------------- #
# #291 design s3.4 -- a benched model is replaced by the Claude main tier, on every layer
# --------------------------------------------------------------------------- #
_HARNESS_META = _RESOLVER.resolve().parents[2] / "_meta"


def _live_roster():
    """The committed roster, loaded by file path (never a sys.path lookup), so these tests
    follow the roster through a swap instead of hard-coding one revision's values. The
    explicit-literal fixture pairs are in test_the_replacement_follows_an_injected_roster."""
    spec = importlib.util.spec_from_file_location("_sc_test_model_roster", _HARNESS_META / "model_roster.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ROSTER = _live_roster()
_BENCHED_FAMILY = sorted(_ROSTER.CLAUDE_BENCHED)[0] if _ROSTER.CLAUDE_BENCHED else None
_needs_bench = pytest.mark.skipif(_BENCHED_FAMILY is None, reason="the committed roster benches nothing")


def _benched_forms():
    fam = _BENCHED_FAMILY or "unbenched"
    # bare alias, alias[1m] (quoted below: flow style), a full id, and upper case: the same
    # four spellings seat_model.is_benched normalises.
    return [fam, f"{fam}[1m]", f"claude-{fam}-5-1", fam.upper()]


def _policy_with(layer, value):
    if layer == "agents":
        return f'version: 1\ntiers:\n  complex: {{claude-code: sonnet}}\nagents:\n  bob: "{value}"\n'
    return f'version: 1\ntiers:\n  complex: {{claude-code: "{value}"}}\n'


def _args_for(layer):
    extra = ("--agent", "bob") if layer == "agents" else ()
    return ("--tier", "complex", "--surface", "headless", *extra)


@_needs_bench
@pytest.mark.parametrize("value", _benched_forms())
@pytest.mark.parametrize("where", ["global-tier", "project-tier", "agents-pin"])
def test_benched_value_is_replaced_by_the_main_tier_on_every_layer(tmp_path, where, value):
    layer = "agents" if where == "agents-pin" else "tiers"
    key = "project_policy" if where == "project-tier" else "global_policy"
    out, proc = _resolve(tmp_path, *_args_for(layer), **{key: _policy_with(layer, value)})
    assert out["model"] == _ROSTER.CLAUDE_MAIN  # replaced -- not a hard fail, not inherit (None)
    assert out["source"] == ("agent-pin" if layer == "agents" else where.split("-")[0])
    hits = [w for w in out["warnings"] if "benched" in w and repr(value) in w]
    assert len(hits) == 1, out["warnings"]
    assert repr(_ROSTER.CLAUDE_MAIN) in hits[0]
    assert "benched" in proc.stderr  # loud: also on stderr, like the D9 pin skip


@_needs_bench
def test_the_acceptance_fixture_project_full_id_on_complex(tmp_path):
    # design s7 / WP-3 acceptance, spelled out: a project .claude/model-policy.yaml pinning
    # the complex tier to a benched family's FULL id (which used to pass through as an
    # "unknown model id") resolves to the main tier with a warning.
    full_id = f"claude-{_BENCHED_FAMILY}-5-1"
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "agent",
                      project_policy=f"version: 1\ntiers:\n  complex: {{claude-code: {full_id}}}\n")
    assert out["model"] == _ROSTER.CLAUDE_MAIN
    assert not any("unknown model id" in w for w in out["warnings"]), out["warnings"]


@_needs_bench
def test_a_project_override_does_not_launder_a_benched_global_leaf(tmp_path):
    # Every layer is checked BEFORE the merge: the global benched leaf is reported even
    # though the project leaf wins, and the resolved value is the project's.
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "headless",
                      global_policy=_policy_with("tiers", _BENCHED_FAMILY),
                      project_policy="version: 1\ntiers:\n  complex: {claude-code: sonnet}\n")
    assert out["model"] == "sonnet"
    assert any(w.startswith("global tiers.complex.claude-code") and "benched" in w for w in out["warnings"])


@pytest.mark.parametrize("tier", ["complex", "medium", "light"])
@pytest.mark.parametrize("policy", ["template", "all-benched"])
def test_resolve_never_returns_a_benched_model(tmp_path, tier, policy):
    sys.path.insert(0, str(_HARNESS_META))
    try:
        import seat_model  # the one normaliser, the same one the resolver uses
    finally:
        sys.path.remove(str(_HARNESS_META))
    if policy == "template":
        body = (_RESOLVER.resolve().parents[1] / "templates" / "model-policy.yaml").read_text(encoding="utf-8")
    else:
        fam = _BENCHED_FAMILY or "opus"
        body = ("version: 1\ntiers:\n"
                + "".join(f'  {t}: {{claude-code: "{fam}[1m]"}}\n' for t in ("complex", "medium", "light")))
    for surface in ("agent", "workflow", "headless"):
        out, _ = _resolve(tmp_path, "--tier", tier, "--surface", surface, global_policy=body)
        assert out["model"] is not None
        assert not seat_model.is_benched(out["model"]), (surface, out)


_FIXTURE_FLOOR = 'frozenset({"fable"})'


def _copy_resolver_into(tmp_path, meta_files, floor=_FIXTURE_FLOOR):
    """A throwaway harness tree: skills/smart-config/scripts/model_policy.py plus a
    skills/_meta holding only `meta_files` ({name: text}); None = no _meta at all.
    The copy's _FLOOR_BENCHED is pinned to the FIXTURE `floor` (#291 fix round 1 E), so the
    fallback tests do not depend on what the committed floor holds after a swap or revert."""
    scripts = tmp_path / "tree" / "skills" / "smart-config" / "scripts"
    scripts.mkdir(parents=True)
    copy = scripts / "model_policy.py"
    text = _RESOLVER.read_text(encoding="utf-8")
    pinned = re.sub(r"^_FLOOR_BENCHED = .*$", "_FLOOR_BENCHED = " + floor, text, count=1, flags=re.MULTILINE)
    assert pinned.count("_FLOOR_BENCHED = " + floor) == 1
    copy.write_text(pinned, encoding="utf-8")
    if meta_files is not None:
        meta = tmp_path / "tree" / "skills" / "_meta"
        meta.mkdir(parents=True)
        for name, text in meta_files.items():
            (meta / name).write_text(text, encoding="utf-8")
    return copy


@pytest.mark.parametrize("meta_files, expect_model, expect_warning", [
    (None, None, "model roster unavailable"),
    ({"model_roster.py": "raise RuntimeError('roster broken on purpose')\n"}, None, "model roster unavailable"),
    # seat_model and model_ids missing beside it; CLAUDE_BENCHED absent -> the hard floor
    ({"model_roster.py": "CLAUDE_MAIN = 'opus'\n"}, "opus", "hard floor"),
], ids=["no-meta-dir", "roster-raises", "seat-model-missing"])
def test_a_failed_roster_import_still_never_passes_a_benched_value(tmp_path, meta_files, expect_model,
                                                                   expect_warning):
    # #291 fix round 1, finding A: this used to assert the OLD behaviour (the benched value
    # passed straight through). A broken harness now falls back to the hard floor
    # {"fable"} (== bob-serial-exec.js DEFAULT_BENCHED): the value is replaced by a usable
    # CLAUDE_MAIN when the roster offers one, else dropped to inherit (None). Never "fable".
    copy = _copy_resolver_into(tmp_path, meta_files)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "model-policy.yaml").write_text(
        'version: 1\ntiers:\n  complex: {claude-code: "fable"}\n', encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(copy), "resolve", "--tier", "complex", "--surface", "headless",
         "--project-root", str(tmp_path / "proj"), "--no-log"],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["model"] == expect_model
    assert any(expect_warning in w for w in out["warnings"]), out["warnings"]
    assert any("benched" in w and "'fable'" in w for w in out["warnings"]), out["warnings"]


def test_the_hard_floor_matches_the_workflow_default_and_the_roster():
    mod = _load_module()
    text = (_RESOLVER.resolve().parents[3] / "workflows" / "bob-serial-exec.js").read_text(encoding="utf-8")
    m = re.search(r"^const DEFAULT_BENCHED = (\[[^\]]*\]);", text, re.MULTILINE)
    assert m is not None
    assert sorted(mod._FLOOR_BENCHED) == sorted(json.loads(m.group(1)))
    # While the roster benches anything, the floor is exactly the roster's set (runbook s3).
    if _ROSTER.CLAUDE_BENCHED:
        assert mod._FLOOR_BENCHED == _ROSTER.CLAUDE_BENCHED


def _resolve_injected(tmp_path, monkeypatch, capsys, surface, value, main="opus", benched=("fable",)):
    """Resolve in process against an INJECTED roster (the committed values are never read;
    #291 fix round 1 E), exactly as test_the_replacement_follows_an_injected_roster does."""
    mod = _load_module()
    assert mod._load_roster([])[1] is not None  # imports the harness modules
    roster = sys.modules["model_roster"]
    monkeypatch.setattr(roster, "CLAUDE_MAIN", main)
    monkeypatch.setattr(roster, "CLAUDE_BENCHED", frozenset(benched))
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "model-policy.yaml").write_text(
        f'version: 1\ntiers:\n  complex: {{claude-code: "{value}"}}\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    args = mod.build_parser().parse_args(
        ["resolve", "--tier", "complex", "--surface", surface, "--project-root", str(tmp_path / "p"), "--no-log"])
    return mod, args


@pytest.mark.parametrize("surface", ["agent", "workflow", "headless"])
def test_the_final_shaped_value_is_checked_too(tmp_path, monkeypatch, capsys, surface):
    # Finding F, defence in depth: even if a benched value escaped the per-layer check, the
    # FINAL surface-shaped value is refused. Simulated by disabling the layer check.
    mod, args = _resolve_injected(tmp_path, monkeypatch, capsys, surface, "fable[1m]")
    monkeypatch.setattr(mod, "_refuse_benched", lambda layer, *a, **k: layer)
    assert mod.cmd_resolve(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model"] == "opus", out
    assert any(w.startswith("resolved value") and "benched" in w for w in out["warnings"]), out["warnings"]


def test_no_layer_means_no_roster_import_and_no_warning(tmp_path):
    # Zero-config stays a perfect no-op: with no readable layer the roster is not consulted.
    copy = _copy_resolver_into(tmp_path, None)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    proc = subprocess.run(
        [sys.executable, str(copy), "resolve", "--tier", "complex", "--project-root", str(tmp_path / "p"), "--no-log"],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    out = json.loads(proc.stdout)
    assert (out["model"], out["warnings"]) == (None, [])


@pytest.mark.parametrize("main, benched, value, expect_model, expect_benched_warning", [
    # (main, support, benched) = (opus, sonnet, {fable}) -- the rev-2 shape
    ("opus", frozenset({"fable"}), "claude-fable-5-1", "opus", True),
    ("opus", frozenset({"fable"}), "fable", "opus", True),
    ("opus", frozenset({"fable"}), "sonnet", "sonnet", False),
    # (fable, opus, {}) -- the rev-1 shape: nothing benched, nothing replaced
    ("fable", frozenset(), "fable", "fable", False),
    ("fable", frozenset(), "claude-fable-5-1", "claude-fable-5-1", False),
], ids=["rev2-full-id", "rev2-alias", "rev2-unbenched", "rev1-alias", "rev1-full-id"])
def test_the_replacement_follows_an_injected_roster(tmp_path, monkeypatch, capsys,
                                                    main, benched, value, expect_model, expect_benched_warning):
    # Reversibility (design s3.9): the resolver reads the roster at CALL time, so a swap
    # needs no edit here. Injected in-process by monkeypatching model_roster attributes --
    # no production path override. Expected values are the explicit literals above.
    mod = _load_module()
    assert mod._load_roster([]) is not None  # imports the harness modules
    roster = sys.modules["model_roster"]
    monkeypatch.setattr(roster, "CLAUDE_MAIN", main)
    monkeypatch.setattr(roster, "CLAUDE_BENCHED", benched)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "model-policy.yaml").write_text(
        f'version: 1\ntiers:\n  complex: {{claude-code: "{value}"}}\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    args = mod.build_parser().parse_args(
        ["resolve", "--tier", "complex", "--surface", "headless", "--project-root", str(tmp_path / "p"), "--no-log"])
    assert mod.cmd_resolve(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model"] == expect_model
    assert any("benched" in w for w in out["warnings"]) is expect_benched_warning


# --------------------------------------------------------------------------- #
# #291 fix round 1, finding A -- a broken seat_model must not skip the benched refusal
# --------------------------------------------------------------------------- #
def _full_meta_copy(tmp_path, roster_edit=None):
    """A throwaway harness tree holding a COPY of the real skills/_meta (tests and caches
    left out), optionally with model_roster.py rewritten by `roster_edit(text) -> text`."""
    import shutil
    copy = _copy_resolver_into(tmp_path, None)
    meta = tmp_path / "tree" / "skills" / "_meta"
    shutil.copytree(_HARNESS_META, meta,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", ".pytest_cache"))
    if roster_edit is not None:
        roster = meta / "model_roster.py"
        roster.write_text(roster_edit(roster.read_text(encoding="utf-8")), encoding="utf-8")
    return copy


def _run_copy(tmp_path, copy, policy, *args):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "model-policy.yaml").write_text(policy, encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(copy), "resolve", *args,
         "--project-root", str(tmp_path / "proj"), "--no-log"],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout), proc


def _bump_revision_only(text):
    # A FIXTURE roster (#291 fix round 1 E: never the committed values) that benches fable
    # and is valid except for one invariant: REVISION 99 while HISTORY ends at rev 2, so
    # seat_model raises SeatModelError at import while model_roster itself imports fine.
    return (
        'SCHEMA = "model-roster.v1"\n'
        "REVISION = 99\n"
        'CLAUDE_MAIN = "opus"\n'
        'CLAUDE_SUPPORT = "sonnet"\n'
        'CLAUDE_BENCHED = frozenset({"fable"})\n'
        'CLAUDE_MAIN_ELIGIBLE = frozenset({"fable", "opus"})\n'
        'CODEX_STD = "gpt-5.6-sol"\n'
        'CODEX_TOP_ROLES = ("code_reviewer@complex", "escalation")\n'   # the astra reserve (rev 4)
        'AGY_FAMILY = "argon"\n'                                         # the agy family (rev 6, #367)
        'AGY_HARNESS_VERSION = "4"\n'
        'HISTORY = (\n'
        '    {"rev": 1, "at": "2026-09-14", "claude_main": "fable", "claude_support": "opus",\n'
        '     "codex_std": "gpt-5.6-sol", "benched": (), "reason": "fixture"},\n'
        '    {"rev": 2, "at": "2026-09-23", "claude_main": "opus", "claude_support": "sonnet",\n'
        '     "codex_std": "gpt-5.6-sol", "benched": ("fable",), "reason": "fixture"},\n'
        ')\n'
    )


@pytest.mark.parametrize("value", ["fable", "fable[1m]", "claude-fable-5-1", "FABLE"])
@pytest.mark.parametrize("surface", ["agent", "workflow", "headless"])
def test_an_invariant_violating_roster_still_refuses_the_benched_family(tmp_path, value, surface):
    copy = _full_meta_copy(tmp_path, _bump_revision_only)
    out, proc = _run_copy(tmp_path, copy, f'version: 1\ntiers:\n  complex: {{claude-code: "{value}"}}\n',
                          "--tier", "complex", "--surface", surface)
    assert out["ok"] is True
    # seat_model cannot import, but model_roster can: its benched set is still refused and the
    # value is replaced by its (usable, unbenched) main tier.
    assert out["model"] == "opus", out   # the fixture roster's CLAUDE_MAIN
    assert "fable" not in json.dumps(out["model"]).lower()
    assert any("benched" in w and repr(value) in w for w in out["warnings"]), out["warnings"]
    assert any("seat_model" in w for w in out["warnings"]), out["warnings"]


def test_control_the_invariant_violating_copy_really_breaks_seat_model(tmp_path):
    copy = _full_meta_copy(tmp_path, _bump_revision_only)
    meta = copy.parents[2] / "_meta"
    proc = subprocess.run([sys.executable, "-c", "import seat_model"], cwd=str(meta),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0 and "SeatModelError" in proc.stderr, proc.stderr


# --------------------------------------------------------------------------- #
# #291 fix round 1, finding F -- stacked context suffixes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", ["fable[1m][1m]", "fable[1m][1m][1m]", "claude-fable-5-1[1m][1m]"])
@pytest.mark.parametrize("surface", ["agent", "workflow", "headless"])
def test_a_stacked_suffix_does_not_smuggle_a_benched_family(tmp_path, monkeypatch, capsys, value, surface):
    mod, args = _resolve_injected(tmp_path, monkeypatch, capsys, surface, value)
    assert mod.cmd_resolve(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model"] == "opus", out   # the literal replacement (the injected main tier)


@pytest.mark.parametrize("surface", ["agent", "workflow", "headless"])
def test_control_an_empty_bench_passes_the_same_value_through(tmp_path, monkeypatch, capsys, surface):
    # Reversibility: with nothing benched the stacked value is not refused (it is shaped).
    mod, args = _resolve_injected(tmp_path, monkeypatch, capsys, surface, "fable[1m][1m]",
                                  main="fable", benched=())
    assert mod.cmd_resolve(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model"] is not None and out["model"].startswith("fable"), out
    assert not any("benched" in w for w in out["warnings"]), out["warnings"]


# --------------------------------------------------------------------------- #
# #291 fix round 2, N1 -- tier 2 must not trust the (possibly broken) CLAUDE_BENCHED alone
# --------------------------------------------------------------------------- #
def _fixture_roster(revision, benched_live, history_benched, main="opus"):
    """A FIXTURE roster: `benched_live` is the live CLAUDE_BENCHED literal, `history_benched`
    the rev-2 HISTORY row's benched tuple literal. Everything else is the rev-2 shape."""
    return (
        'SCHEMA = "model-roster.v1"\n'
        f"REVISION = {revision}\n"
        f'CLAUDE_MAIN = "{main}"\n'
        'CLAUDE_SUPPORT = "sonnet"\n'
        f"CLAUDE_BENCHED = {benched_live}\n"
        'CLAUDE_MAIN_ELIGIBLE = frozenset({"fable", "opus"})\n'
        'CODEX_STD = "gpt-5.6-sol"\n'
        'CODEX_TOP_ROLES = ("code_reviewer@complex", "escalation")\n'   # the astra reserve (rev 4)
        'AGY_FAMILY = "argon"\n'                                         # the agy family (rev 6, #367)
        'AGY_HARNESS_VERSION = "4"\n'
        'HISTORY = (\n'
        '    {"rev": 1, "at": "2026-09-14", "claude_main": "fable", "claude_support": "opus",\n'
        '     "codex_std": "gpt-5.6-sol", "benched": (), "reason": "fixture"},\n'
        '    {"rev": 2, "at": "2026-09-23", "claude_main": "opus", "claude_support": "sonnet",\n'
        f'     "codex_std": "gpt-5.6-sol", "benched": {history_benched}, "agy_family": "argon", "reason": "fixture"}},\n'
        ')\n'
    )


@pytest.mark.parametrize("roster_text", [
    # The N1 repro: the live bench emptied, HISTORY untouched -> seat_model refuses to import,
    # and the ONLY benched source tier 2 used to read was the broken edit itself.
    _fixture_roster(2, "frozenset()", '("fable",)'),
    # A REVISION-only fault on a roster that benches fable everywhere (control shape).
    _fixture_roster(99, 'frozenset({"fable"})', '("fable",)'),
    # Live AND HISTORY both empty, REVISION faulty: the floor alone still refuses.
    _fixture_roster(99, "frozenset()", "()"),
], ids=["live-bench-emptied", "revision-only", "live-and-history-emptied"])
@pytest.mark.parametrize("value", ["Fable[1m]", "fable", "claude-fable-5-1"])
def test_a_broken_roster_can_only_refuse_more(tmp_path, roster_text, value):
    copy = _full_meta_copy(tmp_path, lambda _t: roster_text)
    out, _ = _run_copy(tmp_path, copy, f'version: 1\ntiers:\n  complex: {{claude-code: "{value}"}}\n',
                       "--tier", "complex", "--surface", "headless")
    assert out["ok"] is True
    assert any("seat_model" in w for w in out["warnings"]), out["warnings"]
    assert out["model"] is None or "fable" not in out["model"].lower(), out
    assert any("benched" in w and repr(value) in w for w in out["warnings"]), out["warnings"]


def test_a_legit_revert_still_unbenches(tmp_path):
    # Runbook s7: roster + HISTORY + floor all edited together as a NEW revision. seat_model
    # imports (tier 1) and nothing refuses fable -- tier 2's union must not leak into this.
    rev3 = _fixture_roster(3, "frozenset()", '("fable",)', main="fable")
    assert rev3.endswith('},\n)\n')
    rev3 = rev3[:-2] + ('    {"rev": 3, "at": "2026-09-24", "claude_main": "fable", "claude_support": "sonnet",\n'
                        '     "codex_std": "gpt-5.6-sol", "benched": (),\n'
                        # the astra reserve (roster rev 4): a revert carries the live TOP reserve too
                        '     "codex_top_roles": ("code_reviewer@complex", "escalation"), "agy_family": "argon", "reason": "fixture revert"},\n)\n')
    import shutil
    copy = _copy_resolver_into(tmp_path, None, floor="frozenset()")
    meta = tmp_path / "tree" / "skills" / "_meta"
    shutil.copytree(_HARNESS_META, meta,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", ".pytest_cache"))
    (meta / "model_roster.py").write_text(rev3, encoding="utf-8")
    ok = subprocess.run([sys.executable, "-c", "import seat_model"], cwd=str(meta),
                        capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stderr
    out, _ = _run_copy(tmp_path, copy, 'version: 1\ntiers:\n  complex: {claude-code: "fable"}\n',
                       "--tier", "complex", "--surface", "headless")
    assert out["model"] == "fable", out
    assert not any("benched" in w for w in out["warnings"]), out["warnings"]


# --------------------------------------------------------------------------- #
# #291 fix round 2, N6 -- an inherit drop says WHAT the spawn will inherit
# --------------------------------------------------------------------------- #
def test_an_inherit_drop_names_the_interactive_session_model(tmp_path, monkeypatch, capsys):
    mod, args = _resolve_injected(tmp_path, monkeypatch, capsys, "headless", "fable", main="fable")
    assert mod.cmd_resolve(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model"] is None, out
    drops = [w for w in out["warnings"] if "benched" in w and "inherit" in w]
    assert drops, out["warnings"]
    assert all("interactive session model" in w for w in drops), drops


# --------------------------------------------------------------------------- #
# #311 phase 1: host-keyed tier effort, the execution grade, --effort-step
# --------------------------------------------------------------------------- #
EFFORT_POLICY = (
    "version: 1\n"
    "tiers:\n"
    "  complex: {claude-code: opus, effort: {claude-code: high}}\n"
    "  medium: {claude-code: opus}\n"
    "  light: {claude-code: sonnet, effort: {claude-code: low}}\n"
)


@pytest.mark.parametrize("tier, effort", [("light", "low"), ("complex", "high")])
def test_311_a_tier_effort_leaf_resolves_beside_the_model(tmp_path, tier, effort):
    out, _ = _resolve(tmp_path, "--tier", tier, "--surface", "workflow", global_policy=EFFORT_POLICY)
    # #311 fix round 2 item 4: a policy-file level is source `policy` (not reserved), no grade
    assert (out["effort"], out["effort_source"], out["grade"]) == (effort, "policy", None)
    assert out["warnings"] == []


@pytest.mark.parametrize("grade, files, effort, source", [
    ("S", [], "low", "grade"), ("M", [], "medium", "grade"), ("L", [], "high", "grade"),
    ("S", ["skills/_meta/gates.py"], "medium", "promotion"),
    ("M", ["skills/_meta/seat_model.py"], "high", "promotion"),
    ("L", ["skills/_meta/seat_model.py"], "high", "grade"),
])
def test_311_the_execution_grade_sets_the_first_attempt_effort(tmp_path, grade, files, effort, source):
    args = ["--tier", "medium", "--surface", "workflow", "--grade", grade]
    for f in files:
        args += ["--file", f]
    out, _ = _resolve(tmp_path, *args, global_policy=EFFORT_POLICY)
    assert (out["effort"], out["effort_source"], out["grade"]) == (effort, source, grade)
    assert out["policy_hash"].startswith("sha256:")


def test_311_an_ungraded_execution_spawn_gets_high_default_ungraded(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "medium", "--surface", "headless", global_policy=EFFORT_POLICY)
    assert (out["effort"], out["effort_source"], out["grade"]) == ("high", "default-ungraded", None)


def test_311_no_config_means_no_routed_effort(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "medium", "--surface", "workflow")
    assert (out["effort"], out["effort_source"]) == (None, "inherit")


@pytest.mark.parametrize("policy, fragment", [
    ("version: 1\ntiers:\n  light: {claude-code: sonnet, effort: {claude-code: ludicrous}}\n", "not an effort level"),
    ("version: 1\ntiers:\n  light: {claude-code: sonnet, effort: low}\n", "not a host-keyed mapping"),
])
def test_311_a_malformed_effort_fails_open_to_inherit(tmp_path, policy, fragment):
    out, _ = _resolve(tmp_path, "--tier", "light", "--surface", "workflow", global_policy=policy)
    assert (out["effort"], out["effort_source"]) == (None, "inherit")
    assert out["model"] == "sonnet"
    assert any(fragment in w for w in out["warnings"]), out["warnings"]


def test_311_a_null_project_leaf_inherits_and_other_hosts_get_nothing(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "light", "--surface", "workflow", global_policy=EFFORT_POLICY,
                      project_policy="version: 1\ntiers:\n  light: {effort: {claude-code: null}}\n")
    assert out["effort"] is None
    out, _ = _resolve(tmp_path, "--tier", "light", "--host", "vscode-copilot", global_policy=EFFORT_POLICY)
    assert out["effort"] is None
    out, _ = _resolve(tmp_path, "--tier", "medium", "--host", "codex", "--grade", "S", global_policy=EFFORT_POLICY)
    assert out["effort"] is None and any("claude-code-scoped" in w for w in out["warnings"])


def test_311_the_agent_surface_cannot_carry_an_effort(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "light", "--surface", "agent", global_policy=EFFORT_POLICY)
    assert (out["effort"], out["effort_source"]) == (None, "inherit")
    assert any("not expressible on the agent surface" in w for w in out["warnings"])


def test_311_effort_step_is_distinct_from_escalate_and_caps_at_the_policy_ceiling(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "light", "--surface", "workflow", "--effort-step", "1",
                      global_policy=EFFORT_POLICY)
    assert (out["effort"], out["effort_step"], out["model"], out["escalated"]) == ("medium", 1, "sonnet", False)
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "workflow", "--effort-step", "5",
                      global_policy=EFFORT_POLICY)
    assert out["effort"] == "high"
    assert any("capped at high" in w for w in out["warnings"])
    out, _ = _resolve(tmp_path, "--tier", "light", "--surface", "workflow", "--escalate",
                      global_policy=EFFORT_POLICY)
    assert out["escalated"] is True and out["effort_step"] == 0


def test_311_validate_reports_a_bad_effort_leaf(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "model-policy.yaml").write_text(
        "version: 1\ntiers:\n  light: {claude-code: sonnet, effort: {claude-code: turbo}}\n", encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    proc = subprocess.run([sys.executable, str(_RESOLVER), "validate", "--project-root", str(tmp_path)],
                          env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert proc.returncode == 3
    assert "turbo" in proc.stdout


def test_311_the_template_carries_the_documented_effort_leaves(tmp_path):
    template = (_RESOLVER.parent.parent / "templates" / "model-policy.yaml").read_text(encoding="utf-8")
    for tier, effort in (("light", "low"), ("complex", "high")):
        out, _ = _resolve(tmp_path, "--tier", tier, "--surface", "workflow", global_policy=template)
        assert out["effort"] == effort, tier
    out, _ = _resolve(tmp_path, "--tier", "medium", "--surface", "workflow", global_policy=template)
    assert out["effort_source"] == "default-ungraded"



# --------------------------------------------------------------------------- #
# #311 fix round 1 F3 / m6
# --------------------------------------------------------------------------- #
def _validate(tmp_path, policy):
    home = tmp_path / "vhome"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "model-policy.yaml").write_text(policy, encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run([sys.executable, str(_RESOLVER), "validate", "--project-root", str(tmp_path)],
                          env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


@pytest.mark.parametrize("level", ["xhigh", "max"])
def test_311_f3_a_reserved_leaf_is_a_validate_error_and_resolves_capped_at_high(tmp_path, level):
    """Fix round 2 item 4: a policy file can set at most `high` (xhigh/max are reserved)."""
    policy = "version: 1\ntiers:\n  complex: {claude-code: opus, effort: {claude-code: %s}}\n" % level
    proc = _validate(tmp_path, policy)
    assert proc.returncode == 3 and level in proc.stdout
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "workflow", global_policy=policy)
    assert (out["effort"], out["effort_source"]) == ("high", "policy")
    assert any("capped at high" in w for w in out["warnings"]), out["warnings"]
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "workflow", global_policy=EFFORT_POLICY,
                      project_policy="version: 1\ntiers:\n  complex: {effort: {claude-code: %s}}\n" % level)
    assert out["effort"] == "high", "a project file cannot reach a reserved level either"


def test_311_f3_an_effort_leaf_on_the_execution_tier_is_forbidden(tmp_path):
    policy = "version: 1\ntiers:\n  medium: {claude-code: opus, effort: {claude-code: low}}\n"
    proc = _validate(tmp_path, policy)
    assert proc.returncode == 3 and "medium" in proc.stdout
    out, _ = _resolve(tmp_path, "--tier", "medium", "--surface", "workflow", global_policy=policy)
    assert (out["effort"], out["effort_source"]) == ("high", "default-ungraded")
    assert any("execution tier" in w for w in out["warnings"]), out["warnings"]


def test_311_f3_an_effort_step_never_passes_the_policy_ceiling(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "complex", "--surface", "workflow", "--effort-step", "3",
                      global_policy=EFFORT_POLICY)
    assert out["effort"] == "high"


def test_311_m6_the_floor_levels_equal_effort_policy():
    mod = _load_module()
    sys.path.insert(0, str(_RESOLVER.parents[2] / "_meta"))
    import effort_policy
    assert tuple(mod._FLOOR_EFFORTS) == effort_policy.LEVELS



# --------------------------------------------------------------------------- #
# #311 fix round 2 items 3 and 4: every resolve output is one check_consistency accepts
# --------------------------------------------------------------------------- #
def test_311_r2_item3_effort_step_is_refused_with_a_grade(tmp_path):
    out, _ = _resolve(tmp_path, "--tier", "medium", "--surface", "workflow", "--grade", "L", "--effort-step", "1",
                      global_policy=EFFORT_POLICY)
    assert (out["effort"], out["effort_source"], out["effort_step"]) == ("high", "grade", 0)
    assert any("--effort-step is refused with --grade" in w for w in out["warnings"]), out["warnings"]
    out, _ = _resolve(tmp_path, "--tier", "medium", "--surface", "workflow", "--effort-step", "1",
                      global_policy=EFFORT_POLICY)
    assert (out["effort"], out["effort_source"], out["effort_step"]) == ("high", "default-ungraded", 0)


def test_311_r2_every_resolve_output_passes_check_consistency(tmp_path):
    sys.path.insert(0, str(_RESOLVER.parents[2] / "_meta"))
    import effort_policy
    policies = [EFFORT_POLICY,
                "version: 1\ntiers:\n  complex: {claude-code: opus, effort: {claude-code: max}}\n"
                "  light: {claude-code: sonnet, effort: {claude-code: xhigh}}\n  medium: {claude-code: opus}\n"]
    runs = 0
    for i, policy in enumerate(policies):
        for tier in ("light", "medium", "complex"):
            for grade in (None, "S", "M", "L"):
                for step in ("0", "1", "4"):
                    for files in ([], ["skills/_meta/gates.py"]):
                        args = ["--tier", tier, "--surface", "workflow", "--effort-step", step]
                        if grade:
                            args += ["--grade", grade]
                        for f in files:
                            args += ["--file", f]
                        out, _ = _resolve(tmp_path / f"p{i}", *args, global_policy=policy)
                        runs += 1
                        if out["effort"] is None:
                            assert out["effort_source"] == "inherit"
                            continue
                        effort_policy.check_consistency(out["effort"], out["effort_source"], out["grade"])
    assert runs == 2 * 3 * 4 * 3 * 2
