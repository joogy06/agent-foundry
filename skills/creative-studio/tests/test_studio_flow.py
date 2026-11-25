#!/usr/bin/env python3
"""test_studio_flow.py -- #352: the three flows the contract map declares, end to end.

Design docs/plans/2026-10-12-352-creative-studio-design.md (DW-1, DW-4, DW-11). The flows are the
ones `progress/contract-map.yaml` lists under `flows`, and no other path is walked here:

  flow-page-run            studio-runner -> visual-doctrines -> studio-capture -> design-critique ->
                           studio-verdict. Two pages built at test time are captured in Chrome; one
                           of them is wider than every screen. A filled verdict with an eligible
                           winner and typed borrows is accepted; one naming the page that failed the
                           floor is refused.
  flow-article-run         studio-runner -> copy-schools -> studio-claims -> studio-verdict. A draft
                           with a figure the truth pack does not hold is ineligible; a verdict
                           naming it winner is refused; the other draft can win.
  flow-family-resolution   studio-wiring. Every family a shipped profile loads resolves; with a
                           member taken out of a copy of the tree the runner refuses before a brief
                           is written.

Every step runs the shipped code against the repository's own skills: the real profiles, the real
doctrines and school files, the real critic references, the real capture. Only the makers and the
critic are stood in for, by files written here, because they are agents. Each contract a stand-in
maker files is its house's own Value column, read from the house's file at test time.

Runs live in a temp run root. The page flow needs node, puppeteer-core and Chrome and skips with
the reason where one is absent. Every test name starts with its flow, so no two tests of this
suite share a name.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent
_REPO = _SKILL.parent.parent
SKILLS = _REPO / "skills"
META = SKILLS / "_meta"
FIX = Path(__file__).resolve().parent / "fixtures"
SCRIPTS = _SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(META))

import skill_resolve  # noqa: E402
import studio  # noqa: E402
import studio_axes  # noqa: E402
import studio_claims  # noqa: E402
import studio_verdict  # noqa: E402

REQUEST = json.loads((FIX / "run-request-sample.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((FIX / "family-registry-sample.json").read_text(encoding="utf-8"))
PACK = json.loads((FIX / "claim-list-sample.json").read_text(encoding="utf-8"))["truth_pack"]
ARTICLE = (FIX / "article-draft-sample.md").read_text(encoding="utf-8")

VISUAL_AXES = [axis for axis, _ in studio_axes.VISUAL_AXES]
COPY_AXES = [axis for axis, _ in studio_axes.COPY_AXES]
#: A contract for the single maker of the baseline, which has no house: values of the vocabulary.
NO_HOUSE = ["two-roles", "tonal", "compact", "still", "single-column", "supporting", "structural"]
WIDTHS = (390, 768, 1280)
ACCEPTED = {"schema_version": "studio-verdict-check.v1", "accepted": True, "reasons": []}

COMPARISON = "It draws less power than the Example Card 700."
UNSUPPORTED = "The Example Card 900 has 32 GB of memory."
ARTICLE_BRIEF = {"subject": "Which of two sample graphics cards suits a small case.",
                 "reader": "Someone building a small computer who knows what a graphics card is.",
                 "action": "Read the memory guide.", "length": "60-400", "truth-pack": PACK}
CONSTRAINTS = ("# Constraints\n\n## The search question\n\nWhich sample card suits a small case?\n\n"
               "## Heading outline\n\n- What the card gives you\n- What it costs to run\n")
BRIEFS = {
    "website-page": REQUEST["brief"],
    "article": ARTICLE_BRIEF,
    "social-post": {"platform": "LinkedIn",
                    "reader": "Engineers who run a nightly batch and have seen it overrun.",
                    "action": "Read the write-up of how the batch was cut.",
                    "proof": ["The sample nightly batch went from six hours to two."]},
    "cv": {"role": "A platform engineer at a mid-sized firm.",
           "achievements": ["Cut the nightly batch from six hours to two.", "Led the move of forty services."],
           "voice": "Direct, first person left out, British spelling."},
}


def cli(*argv: object) -> tuple:
    """Run the runner's main in-process. Returns (exit code, stdout)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = studio.main([str(a) for a in argv])
    return code, out.getvalue()


def own_values(rel: str) -> list:
    """The Value column of a house's axis table, as the file under skills/ has it today."""
    table = studio_axes.axis_table((SKILLS / rel).read_text(encoding="utf-8"))
    return [row["value"] for row in table.values()]


def contract(values: list, axes: list) -> str:
    rows = "\n".join(f"| `{axis}` | `{value}` | it serves the brief |" for axis, value in zip(axes, values))
    return (f"# Direction contract\n\n## Axis table\n\n| Axis | Value | Why |\n|---|---|---|\n{rows}\n\n"
            "## Three lines\n\n1. The piece gives most weight to the one action.\n"
            "2. Nothing was added to fill space.\n3. One accent, one job.\n")


def built_page(title: str, extra: str = "") -> str:
    """A small page that passes the floor. `extra` is markup added to the last section."""
    words = ("Enough words to wrap over several lines at every width the capture uses, so that the paragraph "
             "counts as running body text and its line length can be measured with some sense. ") * 2
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n<style>\n"
        ":root { --ink: #1c1b19; --paper: #faf8f4; }\n"
        "body { margin: 0; font: 18px/1.5 Georgia, serif; color: var(--ink); background: var(--paper); }\n"
        "main > section { max-width: 40rem; margin: 0 auto; padding: 2rem 1rem; }\n"
        "h1 { font-size: 2rem; } h2 { font-size: 1.5rem; }\n"
        ".proof { border-left: 4px solid #7a2e1f; padding-left: 1rem; }\n"
        "</style>\n</head>\n<body>\n<main>\n"
        f"<section>\n<h1>{title}</h1>\n<p>{words}</p>\n</section>\n"
        f"<section class=\"proof\">\n<h2>The proof</h2>\n<p>{words}</p>\n</section>\n"
        f"<section>\n<h2>What happens next</h2>\n<p>{words}</p>\n<p>{words}</p>\n{extra}</section>\n"
        "</main>\n</body>\n</html>\n"
    )


SOUND_PAGE = built_page("A page that fits its screen")
WIDE_PAGE = built_page("A page wider than its screen",
                       "<div style=\"width:1600px;height:20px;background:#ccc\"></div>\n")
PROOF_SECTION = "body > main:nth-of-type(1) > section:nth-of-type(2)"


def missing_tool() -> str:
    """Why the page flow cannot render on this host. Empty when it can."""
    if not shutil.which("node"):
        return "node is not on PATH"
    chrome = [os.environ.get("CHROME_PATH"), "/bin/google-chrome", "/usr/bin/google-chrome",
              "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    if not any(c and Path(c).exists() for c in chrome):
        return "no Chrome binary found"
    launch = META / "chrome_launch.mjs"
    probe = subprocess.run(
        ["node", "--input-type=module", "-e",
         f"const m = await import({json.dumps(launch.as_uri())}); "
         "await m.loadPuppeteer({envVars: ['STUDIO_CAPTURE_PUPPETEER_PATH']});"],
        capture_output=True, timeout=60, check=False)
    return "" if probe.returncode == 0 else "puppeteer-core could not be loaded"


def filled(run: studio.Run, winner: str, read: int, **critic: object) -> None:
    """Fill one read's record as a critic would. The runner part is left as the runner wrote it."""
    path = run.dir / "verdicts" / f"read-{read}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    borrowed = critic.pop("borrowed", [])
    taken = {b["from"] for b in borrowed}
    record["critic"] = {
        "reads": [{"read": read, "pick": winner}],
        "tells": [{"variant": v, "tells": [{"axis": "density", "held": True, "observation": "As promised."}]}
                  for v in run.variants],
        "rubric": [{"criterion": "The one action is reachable from the first tile", "visitor_mode": "persuade",
                    "favours": winner, "reason": "It sits above the fold at 390."}],
        "outcome": "winner", "winner": winner, "selected_for_repair": False, "repair": None, "no_award": None,
        "borrowed": borrowed,
        "rejected": [{"variant": v, "reason": "Nothing in it serves the brief better."}
                     for v in run.variants if v != winner and v not in taken],
        "could_not_judge": [{"what": "motion", "why": "Still tiles cannot show it."}], "open_to_user": [],
    }
    record["critic"].update(critic)
    path.write_text(json.dumps(record), encoding="utf-8")


def filled_all(run: studio.Run, winner: str, **critic: object) -> None:
    for read in range(1, run.plan["reads"] + 1):
        filled(run, winner, read, **dict(critic))


_WHY_NOT = missing_tool()


# ---------------------------------------------------------------------------------------------
# flow-page-run
# ---------------------------------------------------------------------------------------------

@unittest.skipIf(bool(_WHY_NOT), f"the page flow renders in Chrome: {_WHY_NOT}")
class PageRunFlow(unittest.TestCase):
    """One website-page run, carried once from the sample request to an open verdict.

    The seat of the restrained house and the single maker of the baseline file the page that fits;
    the seat of the expressive house files the page that is wider than every screen.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio-flow-page-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.runs = cls.tmp / "runs"
        brief = cls.tmp / "brief.json"
        brief.write_text(json.dumps(REQUEST["brief"]), encoding="utf-8")
        argv = [str(brief) if a == "brief.json" else a for a in REQUEST["argv"]]
        code, out = cli(*argv, "--run-root", cls.runs, "--skills-root", SKILLS, "--name", "flow")
        assert code == 0, out
        cls.planned = out
        cls.run_id = re.search(r"^run: (.+)$", out, re.M).group(1)
        code, out = cli("brief", "--run", cls.run_id, "--run-root", cls.runs)
        assert code == 0, out
        run = studio.open_run(cls.run_id, cls.runs)
        cls.sound, cls.wide = run.variant_of("visual-a"), run.variant_of("visual-b")
        cls.baseline = run.record["baseline"]["variant"]
        cls.houses = {"visual-a": "web-craft-restrained", "visual-b": "web-craft-expressive"}
        for variant in run.variants:
            seat = run.seat_of(variant)
            target = run.dir / "variants" / variant
            (target / "index.html").write_text(WIDE_PAGE if variant == cls.wide else SOUND_PAGE, encoding="utf-8")
            values = own_values(f"{cls.houses[seat]}/references/doctrine.md") if seat in cls.houses else NO_HOUSE
            (target / "direction-contract.md").write_text(contract(values, VISUAL_AXES), encoding="utf-8")
        (run.dir / "constraints.md").write_text("# Constraints\n\nThe one action is reachable from the first screen.\n",
                                                encoding="utf-8")
        schools = {"copy-a": "business-writing/references/school-plain.md",
                   "copy-b": "content-writer/references/school-voiced.md"}
        for seat, variant in run.record["pairs"].items():
            target = run.dir / "variants" / variant
            (target / "copy.md").write_text("---\ntitle: A page\ndescription: Words for the page.\n---\n# Hero\n\n"
                                            "A headline.\n", encoding="utf-8")
            (target / "copy-contract.md").write_text(contract(own_values(schools[seat]), COPY_AXES), encoding="utf-8")
        cls.distance = [cli("distance", "--run", cls.run_id, "--function", f, "--run-root", cls.runs)
                        for f in ("copy", "visual")]
        # The real capture, through the command line a main loop uses.
        cls.captured = subprocess.run(
            [sys.executable, str(SCRIPTS / "studio.py"), "capture", "--run", cls.run_id, "--run-root", str(cls.runs)],
            capture_output=True, text=True, encoding="utf-8", timeout=900, check=False)
        cls.opened = cli("verdict", "open", "--run", cls.run_id, "--run-root", cls.runs)

    def run_now(self) -> studio.Run:
        return studio.open_run(self.run_id, self.runs)

    def evidence(self, variant: str) -> dict:
        return json.loads((self.run_now().dir / "evidence" / variant / "c1" / "evidence.json").read_text(encoding="utf-8"))

    def check(self) -> tuple:
        return cli("verdict", "check", "--run", self.run_id, "--run-root", self.runs)

    # studio-runner -----------------------------------------------------------------------------

    def test_flow_page_run_the_sample_request_plans_three_variants_and_prints_the_count(self) -> None:
        run = self.run_now()
        self.assertIn("agents: 17 at most = 9 planned + 8 in permitted retries (cap 17, mode full)", self.planned)
        self.assertEqual(sorted(run.variants), sorted({self.sound, self.wide, self.baseline}))
        self.assertEqual(len(run.variants), 3)
        self.assertEqual((run.profile["name"], run.plan["reads"]), ("website-page", 2))

    # visual-doctrines --------------------------------------------------------------------------

    def test_flow_page_run_each_visual_brief_holds_its_own_house_and_never_the_rival(self) -> None:
        run = self.run_now()
        for seat, rival in (("visual-a", "visual-b"), ("visual-b", "visual-a")):
            text = (run.dir / "briefs" / f"{seat}.md").read_text(encoding="utf-8")
            own = (SKILLS / self.houses[seat] / "references" / "doctrine.md").read_text(encoding="utf-8")
            self.assertIn(own.rstrip(), text, seat)
            self.assertNotIn(self.houses[rival], text, seat)
            self.assertNotIn(rival, text, seat)
            self.assertEqual(set(re.findall(r"variant-\d+", text)), {run.variant_of(seat)})

    def test_flow_page_run_the_two_houses_own_contracts_are_distinct_and_inside_their_houses(self) -> None:
        self.assertEqual(self.distance, [(0, "rivalry: distinct (copy)\n"), (0, "rivalry: distinct (visual)\n")])
        rivalry = self.run_now().record["rivalry"]["visual"]
        self.assertEqual(rivalry["state"], "distinct")
        self.assertGreaterEqual(len(rivalry["differing_axes"]), studio_axes.MIN_DISTANCE)

    # studio-capture ----------------------------------------------------------------------------

    def test_flow_page_run_both_built_pages_are_captured_clean_at_the_three_widths(self) -> None:
        self.assertEqual(self.captured.returncode, 0, self.captured.stdout + self.captured.stderr)
        lines = re.findall(r"^(variant-\d): ok exit 0 -> evidence/variant-\d/c1$", self.captured.stdout, re.M)
        self.assertEqual(sorted(lines), sorted(self.run_now().variants))
        for variant in (self.sound, self.wide):
            evidence = self.evidence(variant)
            self.assertEqual(evidence["capture"]["status"], "ok")
            self.assertEqual(evidence["requests"]["outside"], [])
            self.assertEqual({r["viewport"] for r in evidence["floor_rows"]}, set(WIDTHS))
            for ref in evidence["tiles"]:
                self.assertTrue((self.run_now().dir / "evidence" / variant / "c1" / ref).is_file(), ref)
            self.assertTrue({f"w{w}" for w in WIDTHS} <= {ref.split("/")[1] for ref in evidence["tiles"]})

    def test_flow_page_run_the_wide_page_fails_the_overflow_row_and_the_other_page_passes_the_floor(self) -> None:
        wide = {r["viewport"]: r for r in self.evidence(self.wide)["floor_rows"] if r["id"] == "overflow-x"}
        self.assertEqual({(r["result"], r["blocking"]) for r in wide.values()}, {("fail", True)})
        self.assertGreater(wide[390]["measured"], wide[1280]["measured"])
        self.assertGreater(wide[1280]["measured"], 0)
        sound = self.evidence(self.sound)["floor_rows"]
        self.assertEqual({r["result"] for r in sound if r["blocking"]}, {"pass"})

    # design-critique ---------------------------------------------------------------------------

    def test_flow_page_run_the_critic_brief_inlines_the_critics_references_and_names_no_house(self) -> None:
        self.assertEqual(self.opened[0], 0, self.opened[1])
        run = self.run_now()
        for read in (1, 2):
            text = (run.dir / "briefs" / f"critic-read-{read}.md").read_text(encoding="utf-8")
            for ref in run.profile["critic"]["references"]:
                whole = (SKILLS / "design-critique" / ref).read_text(encoding="utf-8")
                self.assertIn(whole.rstrip(), text, ref)
            self.assertIn((META / "convergence-rule.md").read_text(encoding="utf-8").rstrip(), text)
            for name in ("web-craft-restrained", "web-craft-expressive", "visual-craft-restrained",
                         "visual-craft-expressive", "visual-a", "visual-b", "baseline"):
                self.assertNotIn(name, text.replace(str(run.dir), ""), name)
            for variant in run.variants:
                self.assertIn(f"`{variant}`", text)
        orders = run.record["read_orders"]
        self.assertEqual(orders[1], orders[0][::-1])

    def test_flow_page_run_the_critic_is_handed_the_measured_rows_of_the_capture(self) -> None:
        skeleton = json.loads((self.run_now().dir / "verdicts" / "skeleton.json").read_text(encoding="utf-8"))
        self.assertEqual(studio_verdict.skeleton_problems(skeleton), [])
        for variant in (self.sound, self.wide, self.baseline):
            mine = [{k: v for k, v in r.items() if k != "variant"}
                    for r in skeleton["runner"]["floor_rows"] if r["variant"] == variant]
            self.assertEqual(mine, self.evidence(variant)["floor_rows"], variant)
        self.assertEqual(sorted(studio_verdict.eligible_variants(skeleton)), sorted([self.sound, self.baseline]))

    # studio-verdict ----------------------------------------------------------------------------

    def test_flow_page_run_the_verdict_is_refused_for_the_wide_page_and_accepted_with_typed_borrows(self) -> None:
        """The terminal output of the flow. One test, in the order a run goes: held, refused, accepted."""
        self.assertEqual(self.opened[0], 0, self.opened[1])
        run = self.run_now()
        # No judgement is shown before the blind ranking, whatever the record says.
        filled_all(run, self.wide)
        code, out = self.check()
        self.assertEqual((code, out.splitlines()[0]), (3, "stopped: ranking_missing"))
        self.assertNotIn("variant-", out.replace(str(run.dir), ""))
        code, out = cli("verdict", "rank", "--run", self.run_id, "--order", ",".join(run.variants),
                        "--run-root", self.runs)
        self.assertEqual(code, 0, out)

        # The page that failed a blocking row cannot be named the winner.
        self.assertEqual(self.check(), (2, f"refused\n  winner_ineligible {self.wide}\n"))
        refusal = json.loads((run.dir / "verdicts" / "check.json").read_text(encoding="utf-8"))
        self.assertEqual((refusal["accepted"], refusal["reasons"]),
                         (False, [{"code": "winner_ineligible", "at": self.wide}]))
        self.assertFalse((run.dir / "verdicts" / "record.json").exists())
        self.assertFalse((run.dir / "borrow-cards").exists())

        # An eligible winner with one borrow of each kind, each from a losing variant.
        tile = next(ref for ref in self.evidence(self.baseline)["tiles"] if "/w390/" in ref)
        borrows = [
            {"from": self.wide, "kind": "fragment", "what": "the proof section", "why": "It carries the proof.",
             "locator": {"markup": PROOF_SECTION}},
            {"from": self.wide, "kind": "system", "what": "its axis choices", "why": "They hold together.",
             "anchor": {"in": "direction_contract", "name": "density"}},
            {"from": self.baseline, "kind": "move", "what": "the opening", "why": "It answers the visitor first.",
             "technique": "open on the offer",
             "evidence_region": {"evidence": f"evidence/{self.baseline}/c1/{tile}"}},
        ]
        filled_all(run, self.sound, borrowed=borrows)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn(f"winner: {self.sound} (seat visual-a)", out)
        self.assertEqual(json.loads((run.dir / "verdicts" / "check.json").read_text(encoding="utf-8")), ACCEPTED)
        cards = {n: json.loads((run.dir / "borrow-cards" / f"card-{n}" / "card.json").read_text(encoding="utf-8"))
                 for n in (1, 2, 3)}
        self.assertEqual([(cards[n]["kind"], cards[n]["cut"]) for n in (1, 2, 3)],
                         [("fragment", "cut"), ("system", "cut"), ("move", "described")])
        fragment = (run.dir / "borrow-cards" / "card-1" / "fragment.html").read_text(encoding="utf-8")
        self.assertIn("The proof", fragment)
        self.assertNotIn("A page wider than its screen", fragment)      # the part, never the losing page
        self.assertFalse((run.dir / "borrow-cards" / "card-1" / "index.html").exists())
        self.assertTrue((run.dir / "borrow-cards" / "card-2" / "direction-contract.md").is_file())
        self.assertEqual(cards[3]["files"], ["tiles/" + tile.rsplit("/", 1)[1]])
        record = self.run_now().record
        self.assertEqual((record["verdict"]["state"], record["verdict"]["winner_seat"]), ("accepted", "visual-a"))

        # A fourth borrow is over the profile's limit, and a borrow from the winner is no borrow.
        filled_all(run, self.sound, borrowed=borrows + [dict(borrows[0], what="the first section")])
        self.assertEqual(self.check(), (2, "refused\n  borrow_over_max critic.borrowed\n"))
        filled_all(run, self.sound, borrowed=[dict(borrows[0], **{"from": self.sound})],
                   rejected=[{"variant": v, "reason": "Nothing in it serves the brief better."}
                             for v in (self.wide, self.baseline)])
        self.assertIn("borrow_source", self.check()[1])

        # Each refused record went back to the critic: three repair rounds, one per variant, all the
        # run has. A fourth is not sent back: the run stops for the user, and only their decision
        # lets it go on.
        repairs = self.run_now().record["repairs"]
        self.assertEqual((repairs["cap"], [r["kind"] for r in repairs["log"]]), (3, ["record", "record", "record"]))
        code, out = self.check()
        self.assertEqual((code, out.splitlines()[0]), (3, "stopped: to_user"))
        # The command is the user's, typed at a terminal: from here (no terminal) it is refused.
        allow = ("repairs", "--run", self.run_id, "--allow", "1", "--run-root", self.runs)
        self.assertEqual(cli(*allow)[0], 2)
        self.assertEqual(self.check()[0], 3)
        with mock.patch.object(studio, "_at_a_terminal", return_value=True):
            self.assertEqual(cli(*allow)[0], 0)
        self.assertIn("borrow_source", self.check()[1])
        self.assertEqual(self.run_now().record["repairs"]["allowed_by_user"], 1)


# ---------------------------------------------------------------------------------------------
# flow-article-run
# ---------------------------------------------------------------------------------------------

class ArticleRunFlow(unittest.TestCase):
    """One article run per test: the seat of the plain school files the sample draft, the seat of the
    voiced school the same draft with one figure the truth pack does not hold."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-flow-article-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs = self.tmp / "runs"
        brief = self.tmp / "brief.json"
        brief.write_text(json.dumps(ARTICLE_BRIEF), encoding="utf-8")
        code, out = cli("plan", "--profile", "article", "--brief", brief, "--mode", "full",
                        "--run-root", self.runs, "--skills-root", SKILLS, "--name", "flow")
        self.assertEqual(code, 0, out)
        self.planned = out
        self.run_id = re.search(r"^run: (.+)$", out, re.M).group(1)
        self.assertEqual(self.cli("brief")[0], 0)
        run = self.run_now()
        self.good, self.bad = run.variant_of("copy-a"), run.variant_of("copy-b")

    def cli(self, *argv: object) -> tuple:
        return cli(*argv, "--run", self.run_id, "--run-root", self.runs)

    def run_now(self) -> studio.Run:
        return studio.open_run(self.run_id, self.runs)

    def drafts(self) -> None:
        run = self.run_now()
        (run.dir / "constraints.md").write_text(CONSTRAINTS, encoding="utf-8")
        for variant, text, school in ((self.good, ARTICLE, "business-writing/references/school-plain.md"),
                                      (self.bad, ARTICLE + f"\n{UNSUPPORTED}\n",
                                       "content-writer/references/school-voiced.md")):
            target = run.dir / "variants" / variant
            (target / "article.md").write_text(text, encoding="utf-8")
            (target / "direction-contract.md").write_text(contract(own_values(school), COPY_AXES), encoding="utf-8")

    def claim_id(self, variant: str, sentence: str) -> str:
        run = self.run_now()
        taken = run.record["captures"][variant][-1]["dir"]
        listed = json.loads((run.dir / taken / "claim-list.json").read_text(encoding="utf-8"))
        return next(c["id"] for c in listed["claims"] if c["sentence"] == sentence)

    def checked_claims(self) -> None:
        """Both drafts through the claim check, with the comparison ruled and the stray figure ruled badly."""
        self.drafts()
        self.assertEqual(self.cli("distance"), (0, "rivalry: distinct (copy)\n"))
        code, out = self.cli("claims")
        self.assertEqual(code, 3, out)
        self.assertIn("stopped: claims_need_rulings", out)
        self.assertNotIn("Example Card", out)                 # ids and counts, never a maker's sentence
        run = self.run_now()
        rulings = [{"variant": v, "claim": self.claim_id(v, COMPARISON), "ruling": "supported",
                    "entry": "card-700-power", "reason": "300 W against 350 W."} for v in (self.good, self.bad)]
        rulings.append({"variant": self.bad, "claim": self.claim_id(self.bad, UNSUPPORTED), "ruling": "supported",
                        "entry": "an-entry-the-pack-does-not-have", "reason": "It sounds right."})
        (run.dir / "claims").mkdir(exist_ok=True)
        (run.dir / "claims" / "rulings.json").write_text(
            json.dumps({"schema_version": "studio-claim-rulings.v1", "rulings": rulings}), encoding="utf-8")
        code, out = self.cli("claims")
        self.assertEqual(code, 0, out)
        self.claims_out = out

    def judge(self, winner: str) -> None:
        run = self.run_now()
        tells = [{"variant": v, "tells": [{"axis": "first-screen", "held": True,
                                           "observation": "The reader has the answer before the first section."},
                                          {"axis": "unlisted-statements", "held": True, "observation": "None found."},
                                          {"axis": "opening", "held": True, "observation": "As the contract says."}]}
                 for v in run.variants]
        filled_all(run, winner, tells=tells, could_not_judge=[])

    # studio-runner -> copy-schools ---------------------------------------------------------------

    def test_flow_article_run_the_plan_has_two_copy_seats_a_claim_check_and_no_capture(self) -> None:
        run = self.run_now()
        self.assertIn("agents: 15 at most = 7 planned + 8 in permitted retries (cap 15, mode full)", self.planned)
        self.assertEqual(sorted(run.variants), sorted([self.good, self.bad]))
        self.assertFalse(run.profile["evidence"]["capture"])
        self.assertEqual(run.truth_pack(), PACK)
        self.assertEqual(cli("capture", "--run", self.run_id, "--run-root", self.runs),
                         (2, "refused\n  profile_has_no_capture\n"))

    def test_flow_article_run_each_copy_brief_holds_its_own_school_and_never_the_rival(self) -> None:
        run = self.run_now()
        for seat, own, rival in (("copy-a", "business-writing/references/school-plain.md", "content-writer"),
                                 ("copy-b", "content-writer/references/school-voiced.md", "business-writing")):
            text = (run.dir / "briefs" / f"{seat}.md").read_text(encoding="utf-8")
            self.assertIn((SKILLS / own).read_text(encoding="utf-8").rstrip(), text, seat)
            self.assertNotIn(rival, text, seat)
            self.assertEqual(set(re.findall(r"variant-\d+", text)), {run.variant_of(seat)})
            self.assertIn("`truth-pack.json`", text)

    def test_flow_article_run_the_two_schools_own_contracts_are_distinct(self) -> None:
        self.drafts()
        self.assertEqual(self.cli("distance"), (0, "rivalry: distinct (copy)\n"))
        self.assertEqual(len(self.run_now().record["rivalry"]["copy"]["differing_axes"]), len(COPY_AXES))

    # studio-claims -------------------------------------------------------------------------------

    def test_flow_article_run_the_stray_figure_is_one_unsupported_claim_whatever_the_ruling_says(self) -> None:
        self.checked_claims()
        self.assertIn(f"{self.good}: claims 7, supported 7, unsupported 0", self.claims_out)
        self.assertIn(f"{self.bad}: claims 8, supported 7, unsupported 1 (of them without a ruling 0)", self.claims_out)
        run = self.run_now()
        listed = json.loads((run.dir / "evidence" / self.bad / "c2" / "claim-list.json").read_text(encoding="utf-8"))
        stray = [c for c in listed["claims"] if c["status"] == "unsupported"]
        self.assertEqual([c["sentence"] for c in stray], [UNSUPPORTED])
        row = next(r for r in listed["floor_rows"] if r["id"] == studio_claims.ROW_CLAIMS)
        self.assertEqual((row["blocking"], row["result"], row["measured"]), (True, "fail", 1))

    def test_flow_article_run_the_claim_rows_reach_the_verdict_record_and_decide_who_may_win(self) -> None:
        self.checked_claims()
        self.assertEqual(self.cli("verdict", "open")[0], 0)
        run = self.run_now()
        skeleton = json.loads((run.dir / "verdicts" / "skeleton.json").read_text(encoding="utf-8"))
        for variant in (self.good, self.bad):
            listed = json.loads((run.dir / "evidence" / variant / "c2" / "claim-list.json").read_text(encoding="utf-8"))
            mine = [{k: v for k, v in r.items() if k != "variant"}
                    for r in skeleton["runner"]["floor_rows"] if r["variant"] == variant]
            self.assertEqual(mine, listed["floor_rows"], variant)
        self.assertEqual(studio_verdict.eligible_variants(skeleton), [self.good])
        # The pattern report is filed beside each claim list as a pointer; no value of it is in the record.
        for variant in (self.good, self.bad):
            self.assertEqual(run.record["captures"][variant][-1]["pattern_probe"], "ran")
            self.assertTrue((run.dir / "evidence" / variant / "c2" / studio.PATTERN_REPORT).is_file())
        self.assertNotIn("pattern", json.dumps(skeleton))
        text = (run.dir / "briefs" / "critic-read-1.md").read_text(encoding="utf-8")
        self.assertIn((SKILLS / "creative-studio" / "references" / "text-critic.md").read_text(encoding="utf-8").rstrip(),
                      text)
        for name in ("copy-a", "copy-b", "business-writing", "content-writer", "copy-plain", "copy-voiced"):
            self.assertNotIn(name, text.replace(str(run.dir), ""), name)

    # studio-verdict ------------------------------------------------------------------------------

    def test_flow_article_run_a_verdict_naming_the_unsupported_draft_is_refused_and_the_other_wins(self) -> None:
        self.checked_claims()
        self.assertEqual(self.cli("verdict", "open")[0], 0)
        run = self.run_now()
        self.judge(self.bad)
        self.assertEqual(self.cli("verdict", "check"), (2, f"refused\n  winner_ineligible {self.bad}\n"))
        refusal = json.loads((run.dir / "verdicts" / "check.json").read_text(encoding="utf-8"))
        self.assertEqual(refusal["reasons"], [{"code": "winner_ineligible", "at": self.bad}])
        self.assertFalse((run.dir / "verdicts" / "record.json").exists())
        self.judge(self.good)
        code, out = self.cli("verdict", "check")
        self.assertEqual(code, 0, out)
        self.assertIn(f"winner: {self.good} (seat copy-a)", out)
        self.assertEqual(json.loads((run.dir / "verdicts" / "check.json").read_text(encoding="utf-8")), ACCEPTED)
        record = self.run_now().record
        self.assertEqual((record["verdict"]["state"], record["verdict"]["winner_seat"]), ("accepted", "copy-a"))


# ---------------------------------------------------------------------------------------------
# flow-family-resolution
# ---------------------------------------------------------------------------------------------

def shipped_profiles() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((_SKILL / "profiles").glob("*.json"))}


def family_loads(profile: dict) -> list:
    """(where, family) for every `family:` load of a profile: its constraints round, seats, finish and critic."""
    holders = [("constraints", profile["constraints"]["loads"])]
    holders += [(seat["id"], seat["loads"]) for function in profile["functions"] for seat in function["seats"]]
    holders += [(step["id"], step["loads"]) for step in profile["finish"]]
    holders.append(("critic", profile["critic"].get("loads", [])))
    return [(where, token.split(":", 1)[1]) for where, loads in holders for token in loads
            if token.startswith("family:")]


class FamilyResolutionFlow(unittest.TestCase):
    """The registry the fixture records, the tree as it is, and a copy of the tree with a member gone."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-flow-family-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def plan(self, name: str, tree: Path, runs: Path) -> tuple:
        brief = self.tmp / f"brief-{name}.json"
        brief.write_text(json.dumps(BRIEFS[name]), encoding="utf-8")
        return cli("plan", "--profile", name, "--brief", brief, "--run-root", runs, "--skills-root", tree)

    def copied_tree(self, profile: dict) -> Path:
        """A copy of every skill the profile reaches, and the rule file the critic brief inlines."""
        tree = self.tmp / "tree"
        loads = studio.resolve_loads(profile, SKILLS)
        roots = {name for seat in loads.values() for name in seat["members"] + seat["named"]}
        roots |= {entry["path"].split("/", 1)[0] for seat in loads.values() for entry in seat["inline"]}
        for name in sorted(roots - {"_meta"}):
            shutil.copytree(SKILLS / name, tree / name, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        (tree / "_meta").mkdir()
        shutil.copyfile(META / "convergence-rule.md", tree / "_meta" / "convergence-rule.md")
        return tree

    def test_flow_family_resolution_the_registry_is_what_the_tree_declares_today(self) -> None:
        index = skill_resolve.build_index(SKILLS)
        self.assertEqual(len(REGISTRY["families"]), 5)
        for family, members in REGISTRY["families"].items():
            result = skill_resolve.resolve([f"family:{family}"], index, set())
            self.assertEqual((result["resolved"], result["unresolved"]), (members, []), family)
            for member in members:
                self.assertTrue((SKILLS / member / "SKILL.md").is_file(), member)

    def test_flow_family_resolution_every_family_a_shipped_profile_loads_resolves_to_members(self) -> None:
        profiles = shipped_profiles()
        self.assertEqual(sorted(profiles), ["article", "cv", "social-post", "website-page"])
        loaded = set()
        for name, profile in profiles.items():
            resolved = studio.resolve_loads(profile, SKILLS)                 # raises Refused when one does not
            for where, family in family_loads(profile):
                reached = resolved[where]["members"] + resolved[where]["named"]
                self.assertTrue(REGISTRY["families"][family], family)
                self.assertTrue(set(REGISTRY["families"][family]) <= set(reached), f"{name} {where}: {family}")
                loaded.add(family)
        self.assertEqual(loaded, set(REGISTRY["families"]))

    def test_flow_family_resolution_every_shipped_profile_plans_on_the_tree_as_it_is(self) -> None:
        for name in shipped_profiles():
            runs = self.tmp / f"runs-{name}"
            code, out = self.plan(name, SKILLS, runs)
            self.assertEqual(code, 0, f"{name}\n{out}")
            run_dir = Path(re.search(r"^directory: (.+)$", out, re.M).group(1))
            self.assertEqual(sorted(p.name for p in (run_dir / "briefs").iterdir()) if (run_dir / "briefs").exists()
                             else [], [], f"{name}: plan writes no brief")

    def test_flow_family_resolution_a_removed_member_refuses_the_run_before_a_brief_is_written(self) -> None:
        profiles = shipped_profiles()
        checked = set()
        for name, profile in profiles.items():
            tree = self.copied_tree(profile)
            whole = self.tmp / "runs-whole"
            code, out = self.plan(name, tree, whole)
            self.assertEqual(code, 0, f"{name}: the copied tree must plan before a member is taken out\n{out}")
            shutil.rmtree(whole)
            for where, family in family_loads(profile):
                held = self.tmp / "held"
                for member in REGISTRY["families"][family]:
                    shutil.move(str(tree / member), str(held / member))
                runs = self.tmp / "runs"
                code, out = self.plan(name, tree, runs)
                self.assertEqual(code, 2, f"{name} without {family}\n{out}")
                self.assertIn(f"family_empty_or_missing {where}: family:{family}", out)
                self.assertFalse(runs.exists(), f"{name} without {family}: something was written")
                self.assertEqual(list(self.tmp.rglob("briefs")), [])
                for member in REGISTRY["families"][family]:
                    shutil.move(str(held / member), str(tree / member))
                checked.add(family)
            shutil.rmtree(tree)
        self.assertEqual(checked, set(REGISTRY["families"]))


if __name__ == "__main__":
    unittest.main()
