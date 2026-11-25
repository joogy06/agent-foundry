#!/usr/bin/env python3
"""test_studio_wiring.py -- #352: the studio wired into the library.

Design docs/plans/2026-10-12-352-creative-studio-design.md (DW-2, DW-9):
  TS-WIR-01   the families visual-craft-restrained, visual-craft-expressive, copy-plain, copy-voiced
              and social each resolve to a non-empty member list from the repo's skills/, and every
              `loads` of every shipped profile resolves
  TS-WIR-02   the skill directories new in this cycle are at most five; the list is held here and
              checked against the tree (what the shipped profiles reach), not against git history
  and: taking a family's only member out of a copy of the tree makes the runner refuse before a
  brief is written; two rival seats never load the same family (cv is the stated exception, by
  angle); every new and every edited unit has a current intake ledger entry; the five new
  descriptions are inside the per-entry limit and open with the subject; an install into a
  throwaway home places what a run needs, and `studio.py plan` runs from the installed copy for
  each of the four profiles.

Nothing here writes outside a temp directory. The installer runs get a throwaway HOME and
--claude-home, and pass --no-git-hooks, --no-extras and --no-log. The installer and intake tests
skip with the reason when this file is read from an installed copy (no install.py beside skills/).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent
_REPO = _SKILL.parent.parent
SKILLS = _REPO / "skills"
META = SKILLS / "_meta"
FIX = Path(__file__).resolve().parent / "fixtures"
SCRIPTS = _SKILL / "scripts"
INSTALLER = _REPO / "install.py"
INTAKE = SKILLS / "intake-scan" / "scripts" / "intake.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(META))

import skill_resolve  # noqa: E402
import studio  # noqa: E402

#: The skill directories this cycle added. TS-WIR-02 holds the list to five.
NEW_SKILLS = ("creative-studio", "design-critique", "web-craft-restrained", "web-craft-expressive", "social-post")
#: Skills this cycle edited (a family line, a school or format file, the probe).
EDITED_SKILLS = ("business-writing", "content-writer", "human-voice-writing")
#: Skills that existed before the cycle and that a shipped profile loads as they are.
REUSED_SKILLS = EDITED_SKILLS + (
    "seo-keyword-strategist", "seo-structure-architect", "seo-meta-optimizer", "seo-content-strategist",
    "conversion-psychology", "audience-experience-design", "ai-search-optimizer", "ux-reviewer",
    "career-application-writer", "career-positioning")
#: family -> the skills that declare it.
FAMILIES = {"visual-craft-restrained": ["web-craft-restrained"],
            "visual-craft-expressive": ["web-craft-expressive"],
            "copy-plain": ["business-writing"],
            "copy-voiced": ["content-writer"],
            "social": ["social-post"]}
PROFILES = ("article", "cv", "social-post", "website-page")
#: Profiles whose two seats load the SAME skill and differ by `angle` (the design's stated exception).
SAME_LOADS_BY_ANGLE = ("cv",)
MAX_NEW_SKILLS = 5
DESCRIPTION_LIMIT = 250

PACK = json.loads((FIX / "claim-list-sample.json").read_text(encoding="utf-8"))["truth_pack"]
BRIEFS = {
    "website-page": json.loads((FIX / "run-request-sample.json").read_text(encoding="utf-8"))["brief"],
    "article": {"subject": "Which of two sample graphics cards suits a small case.",
                "reader": "Someone building a small computer who knows what a graphics card is.",
                "action": "Read the memory guide.", "length": "60-400", "truth-pack": PACK},
    "social-post": {"platform": "LinkedIn",
                    "reader": "Engineers who run a nightly batch and have seen it overrun.",
                    "action": "Read the write-up of how the batch was cut.",
                    "proof": ["The sample nightly batch went from six hours to two."]},
    "cv": {"role": "A platform engineer at a mid-sized firm.",
           "achievements": ["Cut the nightly batch from six hours to two.", "Led the move of forty services."],
           "voice": "Direct, first person left out, British spelling."},
}
#: What `plan` prints on a fresh run root: (at most, planned) for the full mode, and the light count.
#: The page's first three runs carry the single-maker baseline, which light mode never drops.
COUNTS = {"website-page": ((17, 9), 5), "article": ((15, 7), 4), "social-post": ((12, 6), 4), "cv": ((9, 5), 4)}

#: Files a run reads at run time, relative to the installed skills tree.
RUN_TIME_FILES = (
    "creative-studio/SKILL.md",
    "creative-studio/scripts/studio.py", "creative-studio/scripts/studio_axes.py",
    "creative-studio/scripts/studio_verdict.py", "creative-studio/scripts/studio_capture.py",
    "creative-studio/scripts/studio_claims.py", "creative-studio/scripts/capture_page.mjs",
    "creative-studio/schemas/studio-profile.v1.json", "creative-studio/schemas/studio-verdict.v1.json",
    "creative-studio/schemas/truth-pack.v1.json",
    "creative-studio/profiles/website-page.json", "creative-studio/profiles/article.json",
    "creative-studio/profiles/social-post.json", "creative-studio/profiles/cv.json",
    "creative-studio/references/text-critic.md", "creative-studio/assets/font-kit/README.md",
    "_meta/chrome_launch.mjs", "_meta/convergence-rule.md", "_meta/skill_resolve.py", "_meta/skill_frontmatter.py",
    "design-critique/SKILL.md", "design-critique/references/critic-brief.md",
    "design-critique/references/neutral-floor.md", "design-critique/references/rubric.md",
    "web-craft-restrained/SKILL.md", "web-craft-restrained/references/doctrine.md",
    "web-craft-expressive/SKILL.md", "web-craft-expressive/references/doctrine.md",
    "social-post/SKILL.md", "social-post/references/platform-formats.md",
    "business-writing/references/school-plain.md", "content-writer/references/school-voiced.md",
    "human-voice-writing/scripts/pattern_probe.py", "human-voice-writing/references/ATTRIBUTION.md",
)


# ---------------------------------------------------------------------------------------------
# what the tree says
# ---------------------------------------------------------------------------------------------

def frontmatter(text: str) -> dict:
    """The top-level `key: value` lines of a SKILL.md's front block."""
    block = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    return dict(re.findall(r"^([A-Za-z][\w-]*):[ \t]*(.*)$", block.group(1), re.M)) if block else {}


def description_of(skill: str, root: Path = SKILLS) -> str:
    value = frontmatter((root / skill / "SKILL.md").read_text(encoding="utf-8"))["description"].strip()
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'" else value


def shipped_profiles() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((_SKILL / "profiles").glob("*.json"))}


def load_tokens(profile: dict) -> list:
    """Every load token of a profile, in the order the profile holds them, once each."""
    tokens = list(profile["constraints"]["loads"])
    for function in profile["functions"]:
        for seat in function["seats"]:
            tokens += seat["loads"]
    for step in profile["finish"]:
        tokens += step["loads"]
    critic = profile["critic"]
    tokens += ([critic["skill"]] if "skill" in critic else []) + list(critic.get("loads", []))
    seen: set = set()
    return [t for t in tokens if not (t in seen or seen.add(t))]


def file_roots(profile: dict) -> list:
    """The skill directories a profile names through a file path (a school, a format, a critic reference)."""
    paths = [seat[key] for f in profile["functions"] for seat in f["seats"]
             for key in ("school_file", "format_file") if key in seat]
    if "reference" in profile["critic"]:
        paths.append(profile["critic"]["reference"])
    return sorted({p.split("/", 1)[0] for p in paths})


def reached(profile: dict, index: dict) -> list:
    """Every skill directory a profile reaches: its resolved loads and the files it names."""
    result = skill_resolve.resolve(load_tokens(profile), index, set())
    return sorted(set(result["resolved"]) | set(file_roots(profile)))


def wiring_report(root: Path = SKILLS) -> dict:
    """The resolved families, the profiles' loads and the new skills, as the tree at `root` has them."""
    index = skill_resolve.build_index(root)
    profiles = shipped_profiles()
    surface = sorted({"creative-studio"} | {s for p in profiles.values() for s in reached(p, index)})
    return {
        "families": {f: skill_resolve.resolve([f"family:{f}"], index, set())["resolved"] for f in FAMILIES},
        "profiles": {name: {"loads": load_tokens(p), "skills": reached(p, index)} for name, p in profiles.items()},
        "new_skills": [s for s in surface if s not in REUSED_SKILLS],
        "new_skill_count": len([s for s in surface if s not in REUSED_SKILLS]),
        "new_skill_limit": MAX_NEW_SKILLS,
        "descriptions": {s: len(description_of(s, root)) for s in NEW_SKILLS},
    }


def run_py(script: Path, *argv: str, cwd: Path = None, env: dict = None, isolated: bool = False) -> tuple:
    """Run a Python script as its own process. Returns (exit code, stdout + stderr)."""
    command = [sys.executable] + (["-I"] if isolated else []) + [str(script)] + [str(a) for a in argv]
    done = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return done.returncode, done.stdout + done.stderr


def copy_skill(name: str, tree: Path) -> None:
    shutil.copytree(SKILLS / name, tree / name, ignore=shutil.ignore_patterns("__pycache__", "tests"))


class Tmp(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-wiring-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def brief(self, profile: str) -> Path:
        path = self.tmp / f"brief-{profile}.json"
        path.write_text(json.dumps(BRIEFS[profile]), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------------------------
# TS-WIR-01: the families and the loads resolve
# ---------------------------------------------------------------------------------------------

class FamiliesResolve(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = skill_resolve.build_index(SKILLS)
        cls.profiles = shipped_profiles()

    def test_ts_wir_01_each_studio_family_resolves_to_existing_skills(self) -> None:
        for family, members in FAMILIES.items():
            result = skill_resolve.resolve([f"family:{family}"], self.index, set())
            self.assertEqual(result["unresolved"], [], family)
            self.assertEqual(result["resolved"], members, family)
            for member in result["resolved"]:
                self.assertTrue((SKILLS / member / "SKILL.md").is_file(), member)

    def test_ts_wir_01_the_resolver_command_agrees(self) -> None:
        code, out = run_py(META / "skill_resolve.py", "--skills-root", SKILLS, "--json",
                           *[f"family:{f}" for f in FAMILIES])
        self.assertEqual(code, 0, out)
        report = json.loads(out)
        self.assertEqual(report["unresolved"], [])
        self.assertEqual({k.split(":", 1)[1]: v for k, v in report["expanded"].items()}, FAMILIES)

    def test_a_family_nobody_declares_does_not_resolve(self) -> None:
        result = skill_resolve.resolve(["family:visual-craft-undeclared"], self.index, set())
        self.assertEqual(result["resolved"], [])
        self.assertEqual([u["name"] for u in result["unresolved"]], ["family:visual-craft-undeclared"])

    def test_the_shipped_profiles_are_the_four(self) -> None:
        self.assertEqual(tuple(sorted(self.profiles)), PROFILES)

    def test_ts_wir_01_every_load_of_every_shipped_profile_resolves(self) -> None:
        for name, profile in self.profiles.items():
            self.assertEqual(studio.profile_problems(profile), [], name)
            loads = studio.resolve_loads(profile, SKILLS)  # raises Refused when one does not
            for function in profile["functions"]:
                for seat in function["seats"]:
                    entry = loads[seat["id"]]
                    self.assertTrue(entry["members"], f"{name} {seat['id']}")
                    for inline in entry["inline"]:
                        self.assertTrue((SKILLS / inline["path"]).is_file(), inline["path"])
            unresolved = skill_resolve.resolve(load_tokens(profile), self.index, set())["unresolved"]
            self.assertEqual(unresolved, [], name)

    def test_every_studio_family_is_loaded_by_a_shipped_profile(self) -> None:
        loaded = {t.split(":", 1)[1] for p in self.profiles.values() for t in load_tokens(p) if t.startswith("family:")}
        self.assertEqual(loaded, set(FAMILIES))

    def test_the_family_lines_are_written_one_way(self) -> None:
        """A top-level `family:` line, as every other family of the library is declared."""
        for family, members in FAMILIES.items():
            for member in members:
                text = (SKILLS / member / "SKILL.md").read_text(encoding="utf-8")
                front = text.split("\n---\n", 1)[0]
                self.assertEqual(re.findall(r"^family:[ \t]*(\S+)[ \t]*$", front, re.M), [family], member)
                self.assertNotRegex(front, r"(?m)^[ \t]+family:", member)


# ---------------------------------------------------------------------------------------------
# TS-WIR-02: at most five new skills
# ---------------------------------------------------------------------------------------------

class AtMostFiveNewSkills(unittest.TestCase):

    def test_ts_wir_02_the_new_skill_directories_are_at_most_five_and_exist(self) -> None:
        self.assertLessEqual(len(NEW_SKILLS), MAX_NEW_SKILLS)
        self.assertEqual(len(set(NEW_SKILLS)), len(NEW_SKILLS))
        for name in NEW_SKILLS:
            meta = frontmatter((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(meta.get("name"), name)

    def test_ts_wir_02_what_the_profiles_reach_is_the_five_plus_skills_that_already_existed(self) -> None:
        """A sixth new skill wired into a profile is in neither list, and fails here."""
        report = wiring_report()
        self.assertEqual(sorted(report["new_skills"]), sorted(NEW_SKILLS))
        self.assertLessEqual(report["new_skill_count"], MAX_NEW_SKILLS)
        self.assertFalse(set(NEW_SKILLS) & set(REUSED_SKILLS))

    def test_a_sixth_skill_in_a_profile_is_counted(self) -> None:
        index = skill_resolve.build_index(SKILLS)
        profile = json.loads(json.dumps(shipped_profiles()["article"]))
        profile["constraints"]["loads"].append("project-documentation")
        new = [s for s in reached(profile, index) if s not in REUSED_SKILLS and s not in NEW_SKILLS]
        self.assertEqual(new, ["project-documentation"])

    def test_the_new_descriptions_are_inside_the_limit_and_open_with_the_subject(self) -> None:
        total = 0
        for name in NEW_SKILLS:
            text = description_of(name)
            total += len(text)
            self.assertLessEqual(len(text), DESCRIPTION_LIMIT, name)
            self.assertNotRegex(text, r"(?i)^(use|used)\s+(when|this|for|to)\b", name)
            self.assertNotRegex(text, r"(?i)^(this skill|a skill|skill for)\b", name)
        self.assertLessEqual(total, MAX_NEW_SKILLS * DESCRIPTION_LIMIT)

    def test_the_audit_reports_nothing_on_the_five_but_the_family_line(self) -> None:
        code, out = run_py(META / "skill_audit.py", "audit", "--root", SKILLS, "--only", ",".join(NEW_SKILLS), "--json")
        self.assertEqual(code, 0, out)
        skills = json.loads(out)["skills"]
        self.assertEqual(sorted(skills), sorted(NEW_SKILLS))
        declaring = {m for members in FAMILIES.values() for m in members}
        for name, record in skills.items():
            self.assertLessEqual(record["description_chars"], record["description_limit"], name)
            others = [f for f in record["findings"] if not (f["code"] == "A1" and "`family`" in f["message"])]
            self.assertEqual(others, [], name)
            self.assertEqual(len(record["findings"]), 1 if name in declaring else 0, name)


# ---------------------------------------------------------------------------------------------
# the flow: a family with no member stops the run before a brief
# ---------------------------------------------------------------------------------------------

class AnEmptiedFamilyStopsTheRun(Tmp):

    def tree_for(self, profile: dict) -> Path:
        tree = self.tmp / "tree"
        for name in reached(profile, skill_resolve.build_index(SKILLS)):
            copy_skill(name, tree)
        (tree / "_meta").mkdir()
        shutil.copyfile(META / "convergence-rule.md", tree / "_meta" / "convergence-rule.md")
        return tree

    def plan(self, name: str, tree: Path, runs: Path) -> tuple:
        return run_py(SCRIPTS / "studio.py", "plan", "--profile", name, "--brief", self.brief(name),
                      "--run-root", runs, "--skills-root", tree, cwd=self.tmp)

    def test_each_family_with_its_members_removed_refuses_every_profile_that_loads_it(self) -> None:
        profiles = shipped_profiles()
        checked = set()
        for name, profile in profiles.items():
            families = [t.split(":", 1)[1] for t in load_tokens(profile) if t.startswith("family:")]
            tree = self.tree_for(profile)
            code, out = self.plan(name, tree, self.tmp / "runs-whole")
            self.assertEqual(code, 0, f"{name}: the copied tree must plan before a member is taken out\n{out}")
            shutil.rmtree(self.tmp / "runs-whole")
            for family in families:
                held = self.tmp / "held"
                for member in FAMILIES[family]:
                    shutil.move(str(tree / member), str(held / member))
                runs = self.tmp / "runs"
                code, out = self.plan(name, tree, runs)
                self.assertEqual(code, 2, f"{name} without {family}\n{out}")
                self.assertRegex(out, rf"family_empty_or_missing [\w-]+: family:{re.escape(family)}\b")
                self.assertFalse(runs.exists(), f"{name} without {family}: a run directory was written")
                self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if not p.name.startswith("brief-")), ["held", "tree"])
                for member in FAMILIES[family]:
                    shutil.move(str(held / member), str(tree / member))
                checked.add(family)
            shutil.rmtree(tree)
        self.assertEqual(checked, set(FAMILIES))

    def test_a_member_whose_family_line_is_gone_is_no_member(self) -> None:
        profile = shipped_profiles()["article"]
        tree = self.tree_for(profile)
        entry = tree / "content-writer" / "SKILL.md"
        text = entry.read_text(encoding="utf-8")
        entry.write_text(re.sub(r"(?m)^family:.*\n", "", text, count=1), encoding="utf-8")
        runs = self.tmp / "runs"
        code, out = self.plan("article", tree, runs)
        self.assertEqual(code, 2, out)
        self.assertIn("family_empty_or_missing copy-b: family:copy-voiced", out)
        self.assertFalse(runs.exists())


# ---------------------------------------------------------------------------------------------
# the rival-pair rule
# ---------------------------------------------------------------------------------------------

def rival_problems(name: str, profile: dict, index: dict) -> list:
    """Why the seats of one function are not rivals. An empty list means they are."""
    problems = []
    for function in profile["functions"]:
        seats = function["seats"]
        for i, first in enumerate(seats):
            for second in seats[i + 1:]:
                pair = f"{function['id']}: {first['id']} / {second['id']}"
                fam = [{t for t in seat["loads"] if t.startswith("family:")} for seat in (first, second)]
                if fam[0] & fam[1]:
                    problems.append(f"same_family {pair}: {sorted(fam[0] & fam[1])}")
                if name in SAME_LOADS_BY_ANGLE:
                    angles = [str(seat.get("angle", "")).strip() for seat in (first, second)]
                    if not all(angles) or angles[0] == angles[1]:
                        problems.append(f"same_angle {pair}")
                    continue
                if not fam[0] or not fam[1]:
                    problems.append(f"no_family {pair}")
                members = [set(skill_resolve.resolve(seat["loads"], index, set())["resolved"]) for seat in (first, second)]
                if not (members[0] - members[1]) or not (members[1] - members[0]):
                    problems.append(f"same_members {pair}")
    return problems


class RivalSeats(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = skill_resolve.build_index(SKILLS)
        cls.profiles = shipped_profiles()

    def test_two_seats_of_one_function_never_load_the_same_family(self) -> None:
        for name, profile in self.profiles.items():
            self.assertEqual(rival_problems(name, profile, self.index), [], name)
            for function in profile["functions"]:
                self.assertEqual(len(function["seats"]), 2, f"{name} {function['id']}")

    def test_the_cv_seats_are_the_exception_and_differ_by_angle(self) -> None:
        seats = self.profiles["cv"]["functions"][0]["seats"]
        self.assertEqual(seats[0]["loads"], seats[1]["loads"])
        self.assertEqual(len({seat["angle"] for seat in seats}), 2)
        for name in PROFILES:
            if name not in SAME_LOADS_BY_ANGLE:
                for function in self.profiles[name]["functions"]:
                    self.assertNotEqual(function["seats"][0]["loads"], function["seats"][1]["loads"], name)

    def test_the_rule_catches_a_shared_family_a_shared_member_and_a_shared_angle(self) -> None:
        article = json.loads(json.dumps(self.profiles["article"]))
        article["functions"][0]["seats"][1]["loads"] = ["family:copy-plain"]
        self.assertIn("same_family copy: copy-a / copy-b: ['family:copy-plain']", rival_problems("article", article, self.index))
        article["functions"][0]["seats"][1]["loads"] = ["business-writing"]
        self.assertEqual(rival_problems("article", article, self.index),
                         ["no_family copy: copy-a / copy-b", "same_members copy: copy-a / copy-b"])
        cv = json.loads(json.dumps(self.profiles["cv"]))
        cv["functions"][0]["seats"][1]["angle"] = cv["functions"][0]["seats"][0]["angle"]
        self.assertEqual(rival_problems("cv", cv, self.index), ["same_angle cv: cv-a / cv-b"])


# ---------------------------------------------------------------------------------------------
# the intake ledger
# ---------------------------------------------------------------------------------------------

@unittest.skipUnless((_REPO / "intake" / "records").is_dir() and INTAKE.is_file(),
                     "no intake records beside this tree (an installed copy)")
class IntakeLedger(unittest.TestCase):

    def test_every_new_and_every_edited_unit_has_one_current_entry(self) -> None:
        entries = json.loads((META / "intake-ledger.json").read_text(encoding="utf-8"))["entries"]
        for name in NEW_SKILLS + EDITED_SKILLS:
            mine = [e for e in entries if e["unit"] == f"skills/{name}"]
            self.assertEqual(len(mine), 1, name)
            self.assertNotEqual(mine[0]["verdict"], "block", name)
            self.assertTrue((_REPO / "intake" / "records" / f"{mine[0]['record_id']}.json").is_file(), name)

    def test_intake_verify_passes_on_the_whole_tree(self) -> None:
        code, out = run_py(INTAKE, "verify", cwd=_REPO)
        self.assertEqual(code, 0, out)
        self.assertIn("result: ok", out)


# ---------------------------------------------------------------------------------------------
# the installer places what a run needs (JC-8)
# ---------------------------------------------------------------------------------------------

def install(home: Path, mode: str, *extra: str) -> tuple:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    for key in ("CLAUDE_CONFIG_DIR", "STUDIO_RUN_ROOT", "PYTHONPATH"):
        env.pop(key, None)
    return run_py(INSTALLER, "--target", "c", "--mode", mode, "--noninteractive", "--no-git-hooks", "--no-extras",
                  "--no-log", "--claude-home", home / ".claude", *extra, cwd=_REPO, env=env)


#: How capture_page.mjs names the shared launch module: two directories up from scripts/, then _meta.
LAUNCH_JOIN = 'path.join(HERE, "..", "..", "_meta", "chrome_launch.mjs")'


@unittest.skipUnless(INSTALLER.is_file(), "no install.py beside this tree (an installed copy)")
class InstalledTree(unittest.TestCase):
    """One copy-mode install into a throwaway home; the runner is then run FROM that home."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio-install-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.home = cls.tmp / "home"
        cls.home.mkdir()
        cls.dry_code, cls.dry_out = install(cls.home, "move", "--dry-run")
        cls.dry_left = sorted(p.name for p in (cls.home / ".claude").rglob("*")) if (cls.home / ".claude").exists() else []
        cls.code, cls.out = install(cls.home, "move")
        cls.tree = cls.home / ".claude" / "skills"
        cls.runner = cls.tree / "creative-studio" / "scripts" / "studio.py"

    def plan(self, name: str, runs: Path, *extra: str, runner: Path = None, home: Path = None) -> tuple:
        brief = self.tmp / f"brief-{name}.json"
        brief.write_text(json.dumps(BRIEFS[name]), encoding="utf-8")
        env = {"HOME": str(home or self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        return run_py(runner or self.runner, "plan", "--profile", name, "--brief", brief, "--run-root", runs, *extra,
                      cwd=self.tmp, env=env, isolated=True)

    def test_the_dry_run_exits_zero_and_places_nothing(self) -> None:
        self.assertEqual(self.dry_code, 0, self.dry_out)
        self.assertIn("dry run complete", self.dry_out)
        self.assertEqual(self.dry_left, [])
        self.assertRegex(self.dry_out, r"create: \d+")

    def test_the_install_exits_zero_into_the_throwaway_home_only(self) -> None:
        self.assertEqual(self.code, 0, self.out)
        self.assertNotIn("Traceback", self.out)
        self.assertTrue(self.tree.is_dir())
        self.assertFalse(self.tree.is_symlink())
        self.assertFalse((self.tree / "creative-studio").is_symlink())

    def test_every_file_a_run_reads_is_placed(self) -> None:
        missing = [rel for rel in RUN_TIME_FILES if not (self.tree / rel).is_file()]
        self.assertEqual(missing, [])

    def test_the_eight_units_are_placed_whole_and_byte_equal(self) -> None:
        for name in NEW_SKILLS + EDITED_SKILLS:
            for source in sorted((SKILLS / name).rglob("*")):
                if not source.is_file() or "__pycache__" in source.parts or ".pytest_cache" in source.parts:
                    continue
                placed = self.tree / source.relative_to(SKILLS)
                self.assertTrue(placed.is_file(), str(source.relative_to(SKILLS)))
                self.assertEqual(placed.read_bytes(), source.read_bytes(), str(source.relative_to(SKILLS)))
        for rel in ("chrome_launch.mjs", "convergence-rule.md", "skill_resolve.py", "skill_frontmatter.py"):
            self.assertEqual((self.tree / "_meta" / rel).read_bytes(), (META / rel).read_bytes(), rel)

    def test_the_capture_script_finds_the_launch_module_in_the_installed_layout(self) -> None:
        script = self.tree / "creative-studio" / "scripts" / "capture_page.mjs"
        self.assertIn(LAUNCH_JOIN, script.read_text(encoding="utf-8"))
        module = (script.parent / ".." / ".." / "_meta" / "chrome_launch.mjs").resolve()
        self.assertTrue(module.is_file())
        self.assertEqual(module, (self.tree / "_meta" / "chrome_launch.mjs").resolve())
        self.assertNotEqual(module, (META / "chrome_launch.mjs").resolve())

    def test_node_loads_the_installed_launch_module(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH")
        module = self.tree / "_meta" / "chrome_launch.mjs"
        code = "const m = await import(process.argv[1]); console.log(Object.keys(m).sort().join(' '));"
        done = subprocess.run([node, "--input-type=module", "-e", code, module.as_uri()], cwd=str(self.tmp),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        for name in ("confirmSandbox", "findChrome", "launchChrome", "loadPuppeteer"):
            self.assertIn(name, done.stdout.split())

    def test_plan_runs_from_the_installed_copy_for_each_profile(self) -> None:
        for name in PROFILES:
            (full, planned), light = COUNTS[name]
            runs = self.tmp / f"runs-{name}"
            code, out = self.plan(name, runs)
            self.assertEqual(code, 0, f"{name}\n{out}")
            self.assertRegex(out, rf"(?m)^agents: {full} at most = {planned} planned \+ {full - planned} in permitted retries")
            directory = Path(re.search(r"(?m)^directory: (.+)$", out).group(1))
            self.assertEqual(directory.parent, runs)
            self.assertTrue((directory / "plan.json").is_file())
            code, out = self.plan(name, self.tmp / f"runs-light-{name}", "--mode", "light")
            self.assertEqual(code, 0, f"{name} light\n{out}")
            self.assertRegex(out, rf"(?m)^agents: {light} at most = {light} planned \+ 0 in permitted retries")

    def test_the_installed_runner_resolves_against_the_installed_skills(self) -> None:
        """Take one house out of the INSTALLED copy: only a runner reading that copy refuses."""
        house = self.tree / "web-craft-expressive"
        held = self.tmp / "held-house"
        shutil.move(str(house), str(held))
        try:
            runs = self.tmp / "runs-no-house"
            code, out = self.plan("website-page", runs)
            self.assertEqual(code, 2, out)
            self.assertIn("family_empty_or_missing visual-b: family:visual-craft-expressive", out)
            self.assertFalse(runs.exists())
        finally:
            shutil.move(str(held), str(house))
        code, out = self.plan("website-page", self.tmp / "runs-house-back")
        self.assertEqual(code, 0, out)

    def test_the_installed_resolver_lists_the_five_families(self) -> None:
        code, out = run_py(self.tree / "_meta" / "skill_resolve.py", "--skills-root", self.tree, "--json",
                           *[f"family:{f}" for f in FAMILIES], cwd=self.tmp, isolated=True)
        self.assertEqual(code, 0, out)
        self.assertEqual({k.split(":", 1)[1]: v for k, v in json.loads(out)["expanded"].items()}, FAMILIES)

    def test_a_link_mode_install_also_plans(self) -> None:
        home = self.tmp / "home-link"
        home.mkdir()
        code, out = install(home, "link")
        self.assertEqual(code, 0, out)
        tree = home / ".claude" / "skills"
        missing = [rel for rel in RUN_TIME_FILES if not (tree / rel).is_file()]
        self.assertEqual(missing, [])
        code, out = self.plan("cv", self.tmp / "runs-link", runner=tree / "creative-studio" / "scripts" / "studio.py", home=home)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^agents: 9 at most = 5 planned")


# ---------------------------------------------------------------------------------------------
# the tracked fixture pair
# ---------------------------------------------------------------------------------------------

class WiringFixtures(unittest.TestCase):

    def test_the_family_registry_sample_is_what_the_resolver_reads(self) -> None:
        sample = json.loads((FIX / "family-registry-sample.json").read_text(encoding="utf-8"))
        index = skill_resolve.build_index(SKILLS)
        self.assertEqual(sample["families"], {f: index["families"].get(f, []) for f in FAMILIES})
        self.assertEqual(sample["families"], FAMILIES)
        declared = {m: f for f, members in FAMILIES.items() for m in members}
        self.assertEqual(sample["declared_by"], declared)
        for member, family in declared.items():
            self.assertEqual(frontmatter((SKILLS / member / "SKILL.md").read_text(encoding="utf-8")).get("family"), family)

    def test_the_wiring_report_sample_is_a_fresh_report(self) -> None:
        sample = json.loads((FIX / "wiring-report-sample.json").read_text(encoding="utf-8"))
        fresh = wiring_report()
        for key in fresh:
            self.assertEqual(sample[key], fresh[key], key)
        self.assertEqual(sample["new_skill_count"], 5)

    def test_the_recorded_listing_budget_adds_up(self) -> None:
        """The before and after figures are a record of 2026-10-12; only their arithmetic is held."""
        budget = json.loads((FIX / "wiring-report-sample.json").read_text(encoding="utf-8"))["listing_budget"]
        before, after = budget["before"], budget["after"]
        self.assertEqual(after["skills"] - before["skills"], len(NEW_SKILLS))
        self.assertEqual(after["description_chars_total"] - before["description_chars_total"],
                         sum(budget["new_description_chars"].values()))
        self.assertEqual(budget["added_chars"], after["all_descriptions_chars"] - before["all_descriptions_chars"])
        self.assertEqual(sorted(budget["new_description_chars"]), sorted(NEW_SKILLS))
        self.assertLessEqual(max(budget["new_description_chars"].values()), DESCRIPTION_LIMIT)

    def test_the_fixture_manifest_hashes_match_the_files(self) -> None:
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["studio-wiring"]
        entries = [f for side in ("inputs", "outputs") for port in component[side].values() for f in port["fixtures"]]
        self.assertEqual(sorted(Path(e["path"]).name for e in entries),
                         ["family-registry-sample.json", "wiring-report-sample.json"])
        for entry in entries:
            digest = hashlib.sha256((_REPO / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(entry["hash"], "sha256:" + digest, entry["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
