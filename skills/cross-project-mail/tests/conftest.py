"""Shared pytest fixtures for cross-project-mail tests."""
import sys
from pathlib import Path
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
import pytest


SKILL_ROOT = Path(__file__).resolve().parent.parent
CPMAIL_PATH = SKILL_ROOT / "scripts" / "cpmail"


@pytest.fixture
def cpmail(monkeypatch, tmp_path):
    """Import cpmail with AI_MAILBOX redirected to a tmp dir, fresh per test."""
    mb = tmp_path / "ai-mailbox"
    mb.mkdir()
    monkeypatch.setenv("AI_MAILBOX", str(mb))
    monkeypatch.chdir(tmp_path)

    # cpmail script has no .py extension; use SourceFileLoader explicitly
    loader = SourceFileLoader("cpmail", str(CPMAIL_PATH))
    spec = spec_from_loader("cpmail", loader)
    mod = module_from_spec(spec)
    sys.modules["cpmail"] = mod
    loader.exec_module(mod)
    return mod


@pytest.fixture
def mailbox(tmp_path):
    """Return the tmp mailbox path."""
    return tmp_path / "ai-mailbox"
