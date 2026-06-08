"""test_registry_schema.py — closed-schema validation of every registry file."""
from __future__ import annotations

from pathlib import Path

import pytest

import advise


_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"
_REGISTRY_FILES = sorted(_REGISTRY_DIR.glob("*.yaml"))


@pytest.mark.parametrize("registry_path", _REGISTRY_FILES, ids=lambda p: p.name)
def test_registry_parses_and_validates(registry_path):
    data = advise.load_registry(registry_path)
    assert data.get("schema_version") == "affordance.v1"


def test_all_five_host_registries_present():
    """Day-one registries: claude-code, codex, antigravity-cli, copilot-cli, copilot-chat, gh."""
    names = {p.name for p in _REGISTRY_FILES}
    assert "claude-code.yaml"      in names
    assert "codex.yaml"            in names
    assert "antigravity-cli.yaml"  in names
    assert "copilot-cli.yaml"      in names
    assert "copilot-chat.yaml"     in names
    assert "gh.yaml"               in names


def test_copilot_chat_stub_has_empty_affordances():
    """copilot-chat.yaml is intentionally a stub for v1.0."""
    data = advise.load_registry(_REGISTRY_DIR / "copilot-chat.yaml")
    assert data.get("affordances") == []


def test_every_command_field_is_a_non_empty_string():
    for fp in _REGISTRY_FILES:
        data = advise.load_registry(fp)
        for aff in data.get("affordances", []):
            assert isinstance(aff["command"], str), \
                f"{fp.name}: command not a string: {aff}"
            assert aff["command"].strip(), \
                f"{fp.name}: empty command: {aff['id']}"


def test_every_risk_class_in_closed_set():
    valid = {"low", "medium", "high"}
    for fp in _REGISTRY_FILES:
        data = advise.load_registry(fp)
        for aff in data.get("affordances", []):
            assert aff["risk_class"] in valid, \
                f"{fp.name}/{aff['id']}: invalid risk_class {aff['risk_class']!r}"


def test_every_id_unique_per_file():
    for fp in _REGISTRY_FILES:
        data = advise.load_registry(fp)
        ids = [aff["id"] for aff in data.get("affordances", [])]
        assert len(ids) == len(set(ids)), f"{fp.name}: duplicate ids in registry"


def test_host_id_prefix_matches_filename():
    """Every affordance.id must begin with '<filename-stem>/'."""
    for fp in _REGISTRY_FILES:
        if fp.stem == "gh":
            # gh.yaml uses activation: tool_on_path, ids start with 'gh/'
            expected_prefix = "gh/"
        else:
            expected_prefix = fp.stem + "/"
        data = advise.load_registry(fp)
        for aff in data.get("affordances", []):
            assert aff["id"].startswith(expected_prefix), \
                f"{fp.name}: id {aff['id']!r} does not start with {expected_prefix!r}"


def test_closed_schema_rejects_extra_keys():
    """Adding a bogus key to an affordance must fail validation."""
    bogus = """
schema_version: affordance.v1
host_cli: claude-code
affordances:
  - id: claude-code/test
    command: "/test"
    risk_class: low
    workflow_match:
      orchestrator: ["bob"]
      completion_kind: ["x"]
    skip_when:
      orchestrator_failed: true
      already_suggested_this_session: true
    hint: |
      one-line
    reference: ~/test
    extra_key: "this should fail"
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(bogus)
        f.flush()
        path = Path(f.name)
    try:
        with pytest.raises(advise.RegistryParseError):
            advise.load_registry(path)
    finally:
        path.unlink()


def test_closed_schema_rejects_invalid_risk_class():
    bogus = """
schema_version: affordance.v1
host_cli: claude-code
affordances:
  - id: claude-code/test
    command: "/test"
    risk_class: nuclear
    workflow_match:
      orchestrator: ["bob"]
      completion_kind: ["x"]
    skip_when:
      orchestrator_failed: true
      already_suggested_this_session: true
    hint: |
      one-line
    reference: ~/test
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(bogus)
        f.flush()
        path = Path(f.name)
    try:
        with pytest.raises(advise.RegistryParseError):
            advise.load_registry(path)
    finally:
        path.unlink()
