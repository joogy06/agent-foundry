"""Per-rule positive + negative tests.

For each of the 16 active rules (E002 is a deliberate-dup marker, suppressed by
A001), this file verifies that:

- A POSITIVE fixture (rule SHOULD fire) produces the finding.
- A NEGATIVE fixture (rule should NOT fire) produces no finding.

Plus a small set of integration tests covering inline suppression, config-driven
ignore, and the JSON / Markdown / SARIF rendering paths.

Run from the skill directory:
    cd ~/.claude/skills/ms-office-security-python
    python3 -m pytest tests/ -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_office_security_check.ms_office_security_check import (
    AstScanner, Finding, Rule, _yaml_load_minimal, load_rules, scan_project,
    render_json, render_markdown, render_sarif,
)


RULES_YAML = Path(__file__).resolve().parents[1] / "ms_office_security_check" / "rules.yaml"


@pytest.fixture(scope="session")
def rules() -> list[Rule]:
    return load_rules(RULES_YAML)


def _run(tmp_path: Path, source: str, filename: str = "src.py", **kwargs) -> "list[Finding]":
    """Helper: write a single .py file, run the orchestrator, return findings."""
    src_file = tmp_path / filename
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text(source, encoding="utf-8")
    report = scan_project(
        tmp_path, kwargs.get("rules", load_rules(RULES_YAML)),
        kwargs.get("selected_rules"), kwargs.get("ignored_rules", set()),
        kwargs.get("changed_files"), kwargs.get("scope_allowlist", set()),
        kwargs.get("excludes", []),
    )
    return report.findings


def test_rules_yaml_loads(rules):
    # Per design §8 dedup note: bob MAY either delete E002 OR keep it documented
    # as always-suppressed-by-A001. We chose option 2 (document) — see SKILL.md §2.
    # Effective firing-rule count is 17 (16 active + E002 always-suppressed = 17).
    # Manifest entry count is 18 because E002 is listed-but-marked-suppressed.
    assert len(rules) == 18, f"expected 18 manifest entries (17 active + E002 always-suppressed-by-A001), got {len(rules)}"
    ids = {r.rule_id for r in rules}
    expected = {
        "MSOSEC-A001", "MSOSEC-A002", "MSOSEC-A003", "MSOSEC-A004",
        "MSOSEC-A009", "MSOSEC-A010", "MSOSEC-A013",
        "MSOSEC-B001",
        "MSOSEC-C001", "MSOSEC-C002", "MSOSEC-C003",
        "MSOSEC-E001", "MSOSEC-E002", "MSOSEC-E003", "MSOSEC-E004", "MSOSEC-E005",
        "MSOSEC-OFFICE001", "MSOSEC-OFFICE002",
    }
    assert ids == expected
    # The "effective" firing count = manifest - suppressed_by-marked entries.
    suppressed = {r.rule_id for r in rules if r.suppressed_by}
    assert suppressed == {"MSOSEC-E002"}, f"unexpected suppressed-by-marked rules: {suppressed}"
    effective = len(rules) - len(suppressed)
    assert effective == 17, f"expected 17 effective firing rules, got {effective}"


def test_a001_adal_positive(tmp_path):
    findings = _run(tmp_path, "import adal\n")
    assert any(f.rule_id == "MSOSEC-A001" for f in findings)


def test_a001_adal_negative(tmp_path):
    findings = _run(tmp_path, "import msal\n")
    assert not any(f.rule_id == "MSOSEC-A001" for f in findings)


def test_a002_msal_without_broker_positive(tmp_path):
    (tmp_path / "src.py").write_text("import msal\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0"\ndependencies = ["msal"]\n', encoding="utf-8"
    )
    report = scan_project(tmp_path, load_rules(RULES_YAML), None, set(), None, set(), [])
    assert any(f.rule_id == "MSOSEC-A002" for f in report.findings)


def test_a002_msal_with_broker_negative(tmp_path):
    (tmp_path / "src.py").write_text("import msal\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0"\ndependencies = ["msal[broker]"]\n',
        encoding="utf-8",
    )
    report = scan_project(tmp_path, load_rules(RULES_YAML), None, set(), None, set(), [])
    assert not any(f.rule_id == "MSOSEC-A002" for f in report.findings)


def test_a003_pca_without_broker_positive(tmp_path):
    src = (
        "import msal\n"
        "app = msal.PublicClientApplication(client_id='abc', authority='https://x/')\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-A003" for f in findings)


def test_a003_pca_with_broker_negative(tmp_path):
    src = (
        "import msal\n"
        "app = msal.PublicClientApplication(client_id='abc', authority='https://x/', enable_broker_on_windows=True)\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-A003" for f in findings)


def test_a004_hardcoded_client_secret_positive(tmp_path):
    src = (
        "import msal\n"
        "app = msal.ConfidentialClientApplication(client_id='abc', client_credential='shhh-its-a-secret')\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-A004" for f in findings)


def test_a004_vault_credential_negative(tmp_path):
    src = (
        "import msal, os\n"
        "secret = os.environ['CLIENT_SECRET']\n"
        "app = msal.ConfidentialClientApplication(client_id='abc', client_credential=secret)\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-A004" for f in findings)


def test_a009_verify_signature_false_positive(tmp_path):
    src = (
        "import jwt\n"
        "claims = jwt.decode(token, key, options={'verify_signature': False}, audience='aud')\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-A009" for f in findings)


def test_a009_signature_enabled_negative(tmp_path):
    src = (
        "import jwt\n"
        "claims = jwt.decode(token, key, algorithms=['RS256'], audience='aud', issuer='iss')\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-A009" for f in findings)


def test_a010_no_algorithms_positive(tmp_path):
    src = "import jwt\nclaims = jwt.decode(token, key)\n"
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-A010" for f in findings)


def test_a010_algorithms_set_negative(tmp_path):
    src = "import jwt\nclaims = jwt.decode(token, key, algorithms=['RS256'], issuer='iss')\n"
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-A010" for f in findings)


def test_a013_no_issuer_positive(tmp_path):
    src = "import jwt\nclaims = jwt.decode(token, key, algorithms=['RS256'])\n"
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-A013" for f in findings)


def test_a013_issuer_set_negative(tmp_path):
    src = "import jwt\nclaims = jwt.decode(token, key, algorithms=['RS256'], issuer='https://iss/')\n"
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-A013" for f in findings)


def test_b001_graph_verify_false_positive(tmp_path):
    src = (
        "import requests\n"
        "resp = requests.get('https://graph.microsoft.com/v1.0/me', verify=False)\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-B001" for f in findings)


def test_b001_non_graph_verify_false_negative(tmp_path):
    # bandit handles non-Graph verify=False; we should NOT duplicate it
    src = (
        "import requests\n"
        "resp = requests.get('https://example.com/api', verify=False)\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-B001" for f in findings)


def test_c001_unlisted_scope_positive(tmp_path):
    src = (
        "import msal\n"
        "scopes = ['Mail.Read']\n"
    )
    findings = _run(tmp_path, src)
    # without an allowlist, every scope literal is flagged
    assert any(f.rule_id == "MSOSEC-C001" for f in findings)


def test_c001_allowlisted_scope_negative(tmp_path):
    src = "scopes = ['Mail.Read']\n"
    findings = _run(tmp_path, src, scope_allowlist={"Mail.Read"})
    assert not any(f.rule_id == "MSOSEC-C001" for f in findings)


def test_c002_default_with_pca_positive(tmp_path):
    src = (
        "import msal\n"
        "app = msal.PublicClientApplication('abc', authority='https://x/', enable_broker_on_windows=True)\n"
        "token = app.acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-C002" for f in findings)


def test_c002_default_with_cca_negative(tmp_path):
    src = (
        "import msal\n"
        "app = msal.ConfidentialClientApplication('abc', authority='https://x/', client_credential=os.environ['S'])\n"
        "token = app.acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-C002" for f in findings)


def test_c003_broad_scope_positive(tmp_path):
    src = "scopes = ['Mail.ReadWrite.All']\n"
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-C003" for f in findings)


def test_c003_broad_scope_allowlisted_negative(tmp_path):
    src = "scopes = ['Mail.ReadWrite.All']\n"
    findings = _run(tmp_path, src, scope_allowlist={"Mail.ReadWrite.All"})
    assert not any(f.rule_id == "MSOSEC-C003" for f in findings)


def test_e001_exchangelib_online_positive(tmp_path):
    src = "import exchangelib\n# Exchange Online client\n"
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-E001" for f in findings)


def test_e001_exchangelib_onprem_negative(tmp_path):
    src = "# on-prem Exchange Server only\nimport exchangelib\n"
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-E001" for f in findings)


def test_e002_suppressed_by_a001(tmp_path):
    """E002 must be suppressed when A001 fires on the same import."""
    src = "import adal\n"
    findings = _run(tmp_path, src)
    a001 = [f for f in findings if f.rule_id == "MSOSEC-A001"]
    e002 = [f for f in findings if f.rule_id == "MSOSEC-E002"]
    assert a001, "A001 should fire on adal import"
    assert not e002, "E002 should be suppressed when A001 fires on same line"


def test_e003_outlook_com_positive(tmp_path):
    src = (
        "import win32com.client\n"
        "outlook = win32com.client.Dispatch('Outlook.Application')\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-E003" for f in findings)


def test_e003_other_com_negative(tmp_path):
    src = (
        "import win32com.client\n"
        "excel = win32com.client.Dispatch('Excel.Application')\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-E003" for f in findings)


def test_e004_requests_kerberos_positive(tmp_path):
    findings = _run(tmp_path, "import requests_kerberos\n")
    assert any(f.rule_id == "MSOSEC-E004" for f in findings)


def test_e004_requests_gssapi_negative(tmp_path):
    findings = _run(tmp_path, "import requests_gssapi\n")
    assert not any(f.rule_id == "MSOSEC-E004" for f in findings)


def test_e005_pymsteams_positive(tmp_path):
    findings = _run(tmp_path, "from pymsteams import connectorcard\n")
    assert any(f.rule_id == "MSOSEC-E005" for f in findings)


def test_e005_no_pymsteams_negative(tmp_path):
    findings = _run(tmp_path, "import requests\n")
    assert not any(f.rule_id == "MSOSEC-E005" for f in findings)


def test_office001_keep_vba_missing_positive(tmp_path):
    src = (
        "import openpyxl\n"
        "wb = openpyxl.load_workbook('input.xlsx')\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-OFFICE001" for f in findings)


def test_office001_keep_vba_set_negative(tmp_path):
    src = (
        "import openpyxl\n"
        "wb = openpyxl.load_workbook('input.xlsx', keep_vba=False)\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-OFFICE001" for f in findings)


def test_office002_xml_parse_in_office_file_positive(tmp_path):
    src = (
        "import openpyxl\n"
        "from lxml import etree\n"
        "doc = etree.parse('inside.xml')\n"
    )
    findings = _run(tmp_path, src)
    assert any(f.rule_id == "MSOSEC-OFFICE002" for f in findings)


def test_office002_xml_parse_without_office_negative(tmp_path):
    src = (
        "from lxml import etree\n"
        "doc = etree.parse('inside.xml')\n"
    )
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-OFFICE002" for f in findings)


# ---------------------------------------------------------------------------
# Inline suppression
# ---------------------------------------------------------------------------

def test_inline_ignore_one_rule(tmp_path):
    src = "import adal  # msosec: ignore MSOSEC-A001\n"
    findings = _run(tmp_path, src)
    assert not any(f.rule_id == "MSOSEC-A001" for f in findings)


def test_inline_ignore_file_wide(tmp_path):
    src = "# msosec: ignore file\nimport adal\nimport pymsteams\n"
    findings = _run(tmp_path, src)
    assert findings == []


# ---------------------------------------------------------------------------
# Renderers — round-trip
# ---------------------------------------------------------------------------

def test_render_json(tmp_path):
    src = "import adal\n"
    (tmp_path / "src.py").write_text(src, encoding="utf-8")
    report = scan_project(tmp_path, load_rules(RULES_YAML), None, set(), None, set(), [])
    out = render_json(report)
    parsed = json.loads(out)
    assert parsed["schema_version"] == "msosec.v1"
    assert any(f["rule_id"] == "MSOSEC-A001" for f in parsed["findings"])


def test_render_markdown_advisory_banner(tmp_path):
    src = "import adal\n"
    (tmp_path / "src.py").write_text(src, encoding="utf-8")
    report = scan_project(tmp_path, load_rules(RULES_YAML), None, set(), None, set(), [])
    out = render_markdown(report)
    assert "Advisory only" in out
    assert "MSOSEC-A001" in out


def test_render_sarif_shape(tmp_path):
    src = "import adal\n"
    (tmp_path / "src.py").write_text(src, encoding="utf-8")
    report = scan_project(tmp_path, load_rules(RULES_YAML), None, set(), None, set(), [])
    out = render_sarif(report)
    parsed = json.loads(out)
    assert parsed["version"] == "2.1.0"
    assert parsed["runs"][0]["tool"]["driver"]["name"] == "ms-office-security-check"


# ---------------------------------------------------------------------------
# Exclusion globs
# ---------------------------------------------------------------------------

def test_default_excludes_venv(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "vendored_adal.py").write_text("import adal\n", encoding="utf-8")
    (tmp_path / "src.py").write_text("import msal\n", encoding="utf-8")
    report = scan_project(tmp_path, load_rules(RULES_YAML), None, set(), None, set(), [])
    assert not any(f.rule_id == "MSOSEC-A001" for f in report.findings), \
        f"adal in .venv/ should be excluded; got findings: {report.findings}"


# ---------------------------------------------------------------------------
# YAML mini-parser
# ---------------------------------------------------------------------------

def test_yaml_minimal_handles_rules():
    data = _yaml_load_minimal(RULES_YAML.read_text(encoding="utf-8"))
    assert "rules" in data
    assert isinstance(data["rules"], list)
    # 18 manifest entries including the deliberate-dup E002 marker (see comment in
    # test_rules_yaml_loads). 17 effective firing rules.
    assert len(data["rules"]) == 18
    a001 = next(r for r in data["rules"] if r["rule_id"] == "MSOSEC-A001")
    assert a001["severity"] == "critical"
