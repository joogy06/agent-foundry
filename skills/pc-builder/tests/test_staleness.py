"""Red-first tests for the staleness guards: data age, unknown newer parts, knowledge-horizon text."""
from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path

from helpers import (BASE, RULES, SKILL_ROOT, SKILLS_DIR, build, cli, find, good_page, ids, pc, run)

BANDS = json.loads((SKILL_ROOT / "data" / "budget-bands.uk.v1.json").read_text(encoding="utf-8"))
SKILLS = ["pc-builder", "pc-compatibility", "pc-power-sizing", "pc-gpu-tiering", "pc-build-recommendations"]


def days_after(as_of: str, n: int) -> str:
    return (datetime.date.fromisoformat(as_of) + datetime.timedelta(days=n)).isoformat()


class RulesDataAge(unittest.TestCase):
    def test_thresholds_live_in_the_data(self):
        self.assertEqual(RULES["stale_after_days"], 120)
        self.assertEqual(RULES["block_after_days"], 180)
        self.assertEqual(BANDS["stale_after_days"], 90)
        self.assertEqual(BANDS["block_after_days"], 120)

    def test_fresh_rules_are_quiet(self):
        self.assertNotIn("RULES_DATA_STALE", ids(run(BASE, today=days_after(RULES["as_of"], 100))))

    def test_stale_rules_warn(self):
        r = run(BASE, today=days_after(RULES["as_of"], 121))
        f = find(r, "RULES_DATA_STALE")
        self.assertEqual(f[0]["severity"], "WARN")
        self.assertIn("121 days old", f[0]["message"])
        self.assertIn(RULES["as_of"], f[0]["message"])
        self.assertEqual(r["exit_code"], 0)

    def test_stale_rules_do_not_block_final_before_180_days(self):
        self.assertEqual(run(BASE, final=True, today=days_after(RULES["as_of"], 150))["exit_code"], 0)

    def test_very_stale_rules_block_final(self):
        r = run(BASE, final=True, today=days_after(RULES["as_of"], 181))
        self.assertEqual(r["exit_code"], 3)
        self.assertIn("RULES_DATA_STALE", [i["id"] for i in r["incomplete"]])

    def test_very_stale_rules_block_publish_gate(self):
        today = days_after(RULES["as_of"], 181)
        page = good_page()
        page["priced_at"] = today
        r = pc.publish_gate(page, today=today)
        self.assertIn("PUB_CHECK_INCOMPLETE", [b["id"] for b in r["publish_blockers"]])

    def test_cli_today_flag_and_bad_date(self):
        proc = cli(BASE, "--today", days_after(RULES["as_of"], 121))
        self.assertIn("RULES_DATA_STALE", proc.stdout)
        self.assertEqual(cli(BASE, "--today", "2026-02-30").returncode, 3)

    def test_system_date_is_the_default(self):
        r = pc.check(BASE)  # no today: uses the real date; must not crash
        self.assertIn(r["exit_code"], (0, 2, 3))


class BandsDataAge(unittest.TestCase):
    def test_stale_bands_warn(self):
        r = run(BASE, band="1200-2000", today=days_after(BANDS["as_of"], 91))
        self.assertIn("BANDS_DATA_STALE", ids(r, "WARN"))
        self.assertNotIn("RULES_DATA_STALE", ids(r))

    def test_bands_not_checked_without_a_band(self):
        self.assertNotIn("BANDS_DATA_STALE", ids(run(BASE, today=days_after(BANDS["as_of"], 91))))

    def test_very_stale_bands_block_final(self):
        r = run(BASE, band="1200-2000", final=True, today=days_after(BANDS["as_of"], 121))
        self.assertEqual(r["exit_code"], 3)
        self.assertIn("BANDS_DATA_STALE", [i["id"] for i in r["incomplete"]])

    def test_caller_bands_without_as_of_cannot_be_trusted_in_final(self):
        bands = {"bands": [{"id": "custom", "min_gbp": 0, "max_gbp": 5000}]}
        r = pc.check(BASE, band="custom", bands=bands, today=RULES["as_of"])
        f = find(r, "BANDS_DATA_STALE")
        self.assertIn("missing", f[0])
        r = pc.check(BASE, band="custom", bands=bands, today=RULES["as_of"], final=True)
        self.assertEqual(r["exit_code"], 3)


class NotInRulesData(unittest.TestCase):
    def part_messages(self, r):
        return [f["message"] for f in find(r, "NOT_IN_RULES_DATA")]

    def test_base_is_fully_known(self):
        self.assertEqual(find(run(BASE), "NOT_IN_RULES_DATA"), [])

    def test_unknown_family_warns_and_blocks_final(self):
        b = build(cpu__family="Ryzen 11000", cpu__model="AMD Ryzen 7 11700X")
        r = run(b)
        msgs = self.part_messages(r)
        self.assertTrue(any("Ryzen 11000" in m and "verify it live before recommending it" in m for m in msgs), msgs)
        self.assertEqual(run(b, final=True)["exit_code"], 3)

    def test_unknown_chipset_is_flagged_not_called_incompatible(self):
        r = run(build(board__chipset="X970"))
        self.assertTrue(any("X970" in m for m in self.part_messages(r)))
        self.assertNotIn("BOARD_CHIPSET_SOCKET", ids(r, "HARD"))
        self.assertIn("NOT_IN_RULES_DATA", [i["id"] for i in run(build(board__chipset="X970"), final=True)["incomplete"]])

    def test_unknown_socket_is_flagged_not_rejected(self):
        b = build(cpu__socket="AM6", board__socket="AM6", cooler__sockets=["AM5", "AM6"])
        r = run(b)
        self.assertTrue(any("AM6" in m for m in self.part_messages(r)))
        self.assertEqual(cli(b).returncode, 0)  # accepted, not bad input
        self.assertEqual(run(b, final=True)["exit_code"], 3)

    def test_unknown_gpu_warns_but_is_never_mapped_to_a_known_card(self):
        b = build(gpu__model="GeForce RTX 6070 16GB")
        r = run(b, use_case="aaa-1440p")
        self.assertTrue(any("RTX 6070" in m for m in self.part_messages(r)))
        self.assertIn("UC_BALANCE", [f["id"] for f in r["findings"] if "missing" in f])
        self.assertNotIn("NOT_IN_RULES_DATA", [i["id"] for i in run(b, final=True)["incomplete"]])

    def test_newer_power_standards_block_final(self):
        for kw, needle in ((dict(psu__atx_version="3.2"), "ATX 3.2"),
                           (dict(gpu__power_connector="12V-3x8"), "12V-3x8")):
            with self.subTest(needle):
                b = build(**kw)
                self.assertTrue(any(needle in m for m in self.part_messages(run(b))))
                self.assertIn("NOT_IN_RULES_DATA", [i["id"] for i in run(b, final=True)["incomplete"]])

    def test_known_8pin_connectors_are_not_flagged(self):
        for conn in ("2x8-pin", "3x8-pin", "8-pin", "12VHPWR", "16-pin"):
            self.assertEqual(find(run(build(gpu__power_connector=conn)), "NOT_IN_RULES_DATA"), [], conn)


class KnowledgeHorizonText(unittest.TestCase):
    def test_every_skill_has_a_knowledge_horizon_section(self):
        for s in SKILLS:
            text = (SKILLS_DIR / s / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(s):
                self.assertIn("## Knowledge horizon", text)
                self.assertIn("as_of", text)
                self.assertIn("web-research", text)
        router = (SKILLS_DIR / "pc-builder" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("training data", router)
        self.assertIn("references/refresh-procedure.md", router)

    def test_refresh_procedure_exists_and_covers_the_loop(self):
        text = (SKILL_ROOT / "references" / "refresh-procedure.md").read_text(encoding="utf-8")
        for needle in ("quarterly", "rules.v", "as_of", "tests", "source", "NOT_IN_RULES_DATA", "ROCm"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
