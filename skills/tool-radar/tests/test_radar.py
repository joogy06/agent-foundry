"""Tests for scripts/radar.py and for the real entries shipped with the skill."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
import radar  # noqa: E402

GOOD = """```radar
name: Example Tool
slug: example-tool
category: dev-tool
alternative_to: Some Paid Tool
homepage: https://example.org
repo: https://example.org/repo
licence_code: MIT
licence_other: n/a
cost: free
maturity: v1.0.0 (2026-10-01)
mcp: none
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner
related_skills: []
tags: [example, widget]
verdict: An example | with a pipe.
```

## What it is

A tool.

## Verified facts

- VERIFIED: MIT. Source: https://example.org (read 2026-10-29).

## Claims that are false or overstated

- None found.

## Foundry fit

- None.

## Decision and next step

Assess.

## Sources

- https://example.org
"""


def make_lib(tmp_path, entries):
    root = tmp_path / "tool-radar"
    (root / "entries").mkdir(parents=True)
    for slug, text in entries.items():
        (root / "entries" / f"{slug}.md").write_text(text, encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    (root / "SKILL.md").write_text(skill, encoding="utf-8")
    return root


def errors_for(tmp_path, text, slug="example-tool"):
    path = tmp_path / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return radar.check_entry(radar.parse_entry(path))


# --- parsing and lint -------------------------------------------------------------

def test_good_entry_has_no_errors_or_warnings(tmp_path):
    errors, warnings = errors_for(tmp_path, GOOD)
    assert errors == [] and warnings == []


def test_lists_and_urls_with_colons_parse(tmp_path):
    path = tmp_path / "example-tool.md"
    path.write_text(GOOD, encoding="utf-8")
    entry = radar.parse_entry(path)
    assert entry.meta["tags"] == ["example", "widget"]
    assert entry.meta["related_skills"] == []
    assert entry.meta["homepage"] == "https://example.org"


@pytest.mark.parametrize("old,new,needle", [
    ("ring: assess", "ring: maybe", "ring 'maybe'"),
    ("category: dev-tool", "category: toys", "category 'toys'"),
    ("mcp: none", "mcp: yes", "mcp 'yes'"),
    ("review_by: 2027-01-27", "review_by: 2026-10-01", "review_by must be after"),
    ("reviewed: 2026-10-29", "reviewed: 29/10/2026", "not YYYY-MM-DD"),
    ("slug: example-tool", "slug: Example_Tool", "not lowercase"),
    ("homepage: https://example.org", "homepage: example.org", "homepage must be an http(s) URL"),
    ("tags: [example, widget]", "tags: example", "tags must be a list"),
    ("verdict: An example | with a pipe.\n", "", "missing field 'verdict'"),
    ("cost: free", "cost: ", "empty field 'cost'"),
    ("mcp: none", "mcp: none\ncolour: red", "unknown key 'colour'"),
    ("mcp: none", "mcp: none\nmcp: server", "duplicate key 'mcp'"),
    ("## Sources\n\n- https://example.org\n", "## Sources\n\n- the video\n", "Sources lists no URL"),
    ("- VERIFIED: MIT.", "- MIT.", "without a VERIFIED/LIKELY/UNCERTAIN tag"),
    ("## Foundry fit", "## Fit", "missing section '## Foundry fit'"),
])
def test_lint_rejects(tmp_path, old, new, needle):
    assert old in GOOD
    errors, _ = errors_for(tmp_path, GOOD.replace(old, new, 1))
    assert any(needle in e for e in errors), errors


def test_slug_must_match_file_name(tmp_path):
    errors, _ = errors_for(tmp_path, GOOD, slug="other-name")
    assert any("does not match slug" in e for e in errors)


def test_missing_block_and_block_not_first(tmp_path):
    errors, _ = errors_for(tmp_path, "# no metadata\n")
    assert any("no ```radar" in e for e in errors)
    errors, _ = errors_for(tmp_path, "intro\n" + GOOD)
    assert any("first thing" in e for e in errors)


def test_hold_requires_a_reason(tmp_path):
    held = GOOD.replace("ring: assess", "ring: hold")
    errors, _ = errors_for(tmp_path, held)
    assert any("ring hold needs" in e for e in errors)
    with_reason = held.replace("Assess.", "Hold because the licence forbids commercial use.")
    errors, _ = errors_for(tmp_path, with_reason)
    assert errors == []


def test_maturity_without_date_warns_only(tmp_path):
    errors, warnings = errors_for(tmp_path, GOOD.replace("v1.0.0 (2026-10-01)", "v1.0.0"))
    assert errors == [] and any("maturity" in w for w in warnings)


def test_missing_related_skill_warns(tmp_path):
    path = tmp_path / "example-tool.md"
    path.write_text(GOOD.replace("related_skills: []", "related_skills: [no-such-skill]"),
                    encoding="utf-8")
    errors, warnings = radar.check_entry(radar.parse_entry(path), skills_root=tmp_path)
    assert errors == [] and any("no-such-skill" in w for w in warnings)


# --- index, lint sync, stale, find --------------------------------------------------

def test_index_escapes_pipes_and_lint_detects_drift(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD})
    assert radar.main(["--root", str(root), "index"]) == 0
    index = (root / "INDEX.md").read_text(encoding="utf-8")
    assert "An example \\| with a pipe." in index
    assert "(entries/example-tool.md)" in index
    assert "`entries/example-tool.md`" in (root / "SKILL.md").read_text(encoding="utf-8")
    assert radar.main(["--root", str(root), "lint"]) == 0
    (root / "INDEX.md").write_text(index + "hand edit\n", encoding="utf-8")
    assert radar.main(["--root", str(root), "lint"]) == 1
    assert "INDEX.md: out of sync" in capsys.readouterr().out


def test_lint_detects_stale_skill_entry_list(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD})
    radar.main(["--root", str(root), "index"])
    (root / "entries" / "second-tool.md").write_text(
        GOOD.replace("example-tool", "second-tool"), encoding="utf-8")
    assert radar.main(["--root", str(root), "lint"]) == 1
    out = capsys.readouterr().out
    assert "SKILL.md: entry list out of sync" in out and "INDEX.md: out of sync" in out


def test_duplicate_slug_across_files(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD, "copy": GOOD})
    radar.main(["--root", str(root), "index"])
    assert radar.main(["--root", str(root), "lint"]) == 1
    assert "also used by" in capsys.readouterr().out


def test_stale_and_lookahead(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD})
    assert radar.main(["--root", str(root), "stale", "--today", "2026-12-01"]) == 0
    assert radar.main(["--root", str(root), "stale", "--today", "2026-12-01", "--days", "60"]) == 1
    assert "due 2027-01-27" in capsys.readouterr().out
    assert radar.main(["--root", str(root), "stale", "--today", "2027-02-01"]) == 1
    assert "OVERDUE" in capsys.readouterr().out


def test_find_matches_tags_case_insensitively_and_filters(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD})
    assert radar.main(["--root", str(root), "find", "WIDGET"]) == 0
    assert "entries/example-tool.md" in capsys.readouterr().out
    assert radar.main(["--root", str(root), "find", "widget", "--ring", "hold"]) == 1
    assert radar.main(["--root", str(root), "find", "paid tool"]) == 0
    assert radar.main(["--root", str(root), "find", "nothing-like-this"]) == 1


def test_missing_entries_dir_exits_2(tmp_path):
    assert radar.main(["--root", str(tmp_path), "lint"]) == 2


def test_non_ascii_survives_round_trip(tmp_path):
    root = make_lib(tmp_path, {"example-tool": GOOD.replace("A tool.", "Ein Werkzeug — für alle.")})
    assert radar.main(["--root", str(root), "index"]) == 0
    assert radar.main(["--root", str(root), "lint"]) == 0


# --- the real library ------------------------------------------------------------

def test_shipped_library_lints_clean(capsys):
    assert radar.main(["--root", str(SKILL), "lint"]) == 0, capsys.readouterr().out


def test_shipped_entries_have_expected_seed_rings():
    rings = {e.meta["slug"]: e.meta["ring"] for e in radar.load(SKILL)}
    assert rings == {"voicestudio": "assess", "openseo": "assess", "qwen-3-8-27b": "trial",
                     "opencode": "assess", "photocraft": "hold", "bmad-method": "assess",
                     "git-ai": "assess", "kittentts": "assess"}


SEED_369 = ("voicestudio", "openseo", "qwen-3-8-27b", "opencode", "photocraft")


def test_shipped_entries_link_back_to_369():
    for entry in (e for e in radar.load(SKILL) if e.meta["slug"] in SEED_369):
        assert "#369" in entry.meta.get("origin", ""), entry.path.name
        assert "docs/reviews/2026-10-29-video-tools-369.md" in entry.body, entry.path.name


PRIVATE = re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
                     r"|\blocalhost:\d+|\b127\.0\.0\.1\b|/home/\w+|[\w.+-]+@[\w-]+\.[\w.]+")


def test_shipped_entries_carry_no_private_addresses_paths_or_emails():
    for path in (SKILL / "entries").glob("*.md"):
        hits = PRIVATE.findall(path.read_text(encoding="utf-8"))
        assert not hits, (path.name, hits)


def test_template_body_passes_lint_once_filled(tmp_path):
    template = (SKILL / "references" / "entry-template.md").read_text(encoding="utf-8")
    body = template.split("\n---\n", 1)[1].lstrip()
    filled = (body.replace("slug: tool-name", "slug: example-tool")
              .replace("reviewed: YYYY-MM-DD", "reviewed: 2026-10-29")
              .replace("review_by: YYYY-MM-DD", "review_by: 2027-01-27"))
    errors, _ = errors_for(tmp_path, filled)
    assert errors == [], errors


# --- challenger round 1: negative cases ------------------------------------------

@pytest.mark.parametrize("text,needle", [
    ("```radar\n```\n", "holds no fields"),
    ("```radar\n# only a comment\n```\n", "holds no fields"),
    ("```radar\nname: x\n", "never closed"),
])
def test_empty_or_unclosed_block_fails(tmp_path, text, needle):
    errors, _ = errors_for(tmp_path, text)
    assert any(needle in e for e in errors), errors
    assert any("missing field" in e for e in errors) or "never closed" in needle


@pytest.mark.parametrize("old,new,needle", [
    ("- VERIFIED: MIT.", "- NOT VERIFIED: MIT.", "without a VERIFIED/LIKELY/UNCERTAIN tag"),
    ("Source: https://example.org (read 2026-10-29).", "(read 2026-10-29).", "without 'Source:'"),
    ("## What it is\n\nA tool.\n", "## What it is\n\n", "'## What it is' is empty"),
    ("## Foundry fit\n\n- None.\n", "```\n## Foundry fit\n```\n", "missing section '## Foundry fit'"),
    ("## Sources\n\n- https://example.org\n", "## Sources\n\n<!-- https://example.org -->x\n", "Sources lists no URL"),
    ("## Sources\n\n- https://example.org\n", "## Sources\n\n- https://#\n", "Sources lists no URL"),
    ("homepage: https://example.org", "homepage: https://#", "homepage must be"),
    ("reviewed: 2026-10-29", "reviewed: 20261029", "not YYYY-MM-DD"),
    ("review_by: 2027-01-27", "review_by: 2027-06-01", "the limit is 90"),
    ("tags: [example, widget]", "tags: [example,,widget]", "empty list element"),
    ("## Sources", "## What it is\n\nAgain.\n\n## Sources", "appears twice"),
])
def test_lint_rejects_round_1(tmp_path, old, new, needle):
    assert old in GOOD
    errors, _ = errors_for(tmp_path, GOOD.replace(old, new, 1))
    assert any(needle in e for e in errors), errors


def test_reviewed_in_the_future_fails(tmp_path):
    path = tmp_path / "example-tool.md"
    path.write_text(GOOD, encoding="utf-8")
    errors, _ = radar.check_entry(radar.parse_entry(path), today=radar.dt.date(2026, 10, 1))
    assert any("in the future" in e for e in errors)


def test_second_radar_block_fails(tmp_path):
    errors, _ = errors_for(tmp_path, GOOD + "\n```radar\nname: y\n```\n")
    assert any("more than one" in e for e in errors)


def test_bom_and_crlf_are_accepted(tmp_path):
    path = tmp_path / "example-tool.md"
    path.write_bytes(b"\xef\xbb\xbf" + GOOD.replace("\n", "\r\n").encode("utf-8"))
    errors, _ = radar.check_entry(radar.parse_entry(path))
    assert errors == []


@pytest.mark.parametrize("ring,decision,ok", [
    ("hold", "No reason supplied.", False),
    ("hold", "Hold because", False),
    ("hold", "Reason: the licence forbids commercial use.", True),
    ("hold", "HOLD because the repository signals look anomalous.", True),
    ("trial", "Trial on the next task.", False),
    ("trial", "Success: scores at least 80% on the capability cases.", True),
    ("adopt", "Adopt.", False),
    ("adopt", "Approved by the owner, 2026-10-29.", True),
])
def test_ring_evidence(tmp_path, ring, decision, ok):
    text = GOOD.replace("ring: assess", f"ring: {ring}").replace("Assess.", decision)
    errors, _ = errors_for(tmp_path, text)
    assert (errors == []) is ok, errors


def test_index_refuses_invalid_entries(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD, "broken": "# no block\n"})
    assert radar.main(["--root", str(root), "index"]) == 1
    assert not (root / "INDEX.md").exists()
    assert "invalid entry broken.md" in capsys.readouterr().err


def test_find_reports_invalid_entries(tmp_path, capsys):
    root = make_lib(tmp_path, {"example-tool": GOOD, "broken": "# no block\n"})
    assert radar.main(["--root", str(root), "find", "zzz"]) == 1
    captured = capsys.readouterr()
    assert "invalid entry broken.md" in captured.err and "could not be searched" in captured.out


def test_stale_survives_date_overflow(tmp_path):
    root = make_lib(tmp_path, {"example-tool": GOOD})
    assert radar.main(["--root", str(root), "stale", "--today", "9999-12-31", "--days", "1"]) == 1
    assert radar.main(["--root", str(root), "stale", "--days", str(10 ** 9)]) == 1


def test_index_is_byte_stable(tmp_path):
    root = make_lib(tmp_path, {"example-tool": GOOD, "second-tool": GOOD.replace(
        "example-tool", "second-tool")})
    radar.main(["--root", str(root), "index"])
    first = (root / "INDEX.md").read_bytes(), (root / "SKILL.md").read_bytes()
    radar.main(["--root", str(root), "index"])
    assert ((root / "INDEX.md").read_bytes(), (root / "SKILL.md").read_bytes()) == first


def test_cli_survives_a_cp1252_console(tmp_path):
    root = make_lib(tmp_path, {"example-tool": GOOD.replace("name: Example Tool",
                                                            "name: Example \u30c4ool \u2014 \U0001f9e0")})
    radar.main(["--root", str(root), "index"])
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    out = subprocess.run([sys.executable, str(SKILL / "scripts" / "radar.py"), "--root", str(root),
                          "find", "example"], capture_output=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    assert b"entries/example-tool.md" in out.stdout
