"""Red-first tests for the codex skill_challenger revise round (items 1-10)."""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from helpers import (BASE, RESEARCH, RULES, SKILL_ROOT, SKILLS_DIR, build, cli, find, good_page, ids, pc, run)

CHILDREN = ["pc-compatibility", "pc-power-sizing", "pc-gpu-tiering", "pc-build-recommendations"]


def frontmatter_description(skill: str) -> str:
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip()


def research_text() -> str:
    return RESEARCH.read_text(encoding="utf-8")


# The research doc lives in the foundry repo (docs/research/), not in an installed copy of the skill.
needs_research = unittest.skipUnless(RESEARCH.is_file(), "research doc only exists in the repo checkout")


def gate(page, **kw):
    kw.setdefault("today", "2026-09-27")
    return pc.publish_gate(page, **kw)


def blockers(result):
    return [b["id"] for b in result["publish_blockers"]]


class Item1DisplayOutput(unittest.TestCase):
    """Display output, with iGPU presence from the DB record, else a sourced platform rule."""

    def nogpu(self, model, family, socket="AM5", igpu=None, **kw):
        return build(gpu=None, cpu__model=model, cpu__family=family, cpu__socket=socket, cpu__igpu=igpu, **kw)

    def test_7500f_without_gpu_is_hard(self):
        r = run(self.nogpu("AMD Ryzen 5 7500F", "ryzen-7000"))
        self.assertIn("DISPLAY_OUTPUT", ids(r, "HARD"))
        self.assertEqual(r["exit_code"], 2)

    def test_265kf_without_gpu_is_hard(self):
        b = self.nogpu("Intel Core Ultra 7 265KF", "core-ultra-200s", socket="LGA1851",
                       board__socket="LGA1851", board__chipset="Z890")
        self.assertIn("DISPLAY_OUTPUT", ids(run(b), "HARD"))

    def test_14600kf_without_gpu_is_hard(self):
        b = self.nogpu("Intel Core i5-14600KF", "core-14", socket="LGA1700", board__socket="LGA1700",
                       board__chipset="Z790")
        self.assertIn("DISPLAY_OUTPUT", ids(run(b), "HARD"))

    def test_9600x_is_not_treated_as_igpu_less(self):
        r = run(self.nogpu("AMD Ryzen 5 9600X", "ryzen-9000", cpu__ppt_w=88))
        self.assertNotIn("DISPLAY_OUTPUT", ids(r))
        info = find(r, "IGPU_CLASS")
        self.assertEqual(info[0]["severity"], "INFO")
        self.assertIn("display/office class, not for gaming", info[0]["message"])

    def test_8700g_is_gaming_light_class(self):
        r = run(self.nogpu("AMD Ryzen 7 8700G", "ryzen-8000g", cpu__box_cooler=True))
        self.assertNotIn("DISPLAY_OUTPUT", ids(r))
        self.assertIn("light gaming", find(r, "IGPU_CLASS")[0]["message"])

    def test_am4_5000_split_on_g_suffix(self):
        common = dict(socket="AM4", board__socket="AM4", board__chipset="B550", board__memory_type="DDR4",
                      ram__type="DDR4")
        self.assertIn("DISPLAY_OUTPUT", ids(run(self.nogpu("AMD Ryzen 5 5600X", "ryzen-5000", **common)), "HARD"))
        self.assertNotIn("DISPLAY_OUTPUT", ids(run(self.nogpu("AMD Ryzen 5 5600G", "ryzen-5000", **common))))

    def test_db_value_wins_when_rule_is_silent(self):
        r = run(self.nogpu("Some Future CPU 1234", "unknown-family", igpu=True))
        self.assertNotIn("DISPLAY_OUTPUT", ids(r))

    def test_conflict_is_warned_and_trusts_neither_side(self):
        r = run(self.nogpu("AMD Ryzen 5 9600X", "ryzen-9000", igpu=False))
        conflict = find(r, "IGPU_DATA_CONFLICT")
        self.assertEqual(conflict[0]["severity"], "WARN")
        self.assertIn("DB says no iGPU, platform rule says iGPU", conflict[0]["message"])
        self.assertNotIn("DISPLAY_OUTPUT", ids(r, "HARD"))
        self.assertIn("DISPLAY_OUTPUT", [f["id"] for f in r["findings"] if "missing" in f])
        self.assertEqual(run(self.nogpu("AMD Ryzen 5 9600X", "ryzen-9000", igpu=False), final=True)["exit_code"], 3)

    def test_conflict_reported_even_with_a_gpu(self):
        r = run(build(cpu__model="AMD Ryzen 5 7500F", cpu__family="ryzen-7000", cpu__igpu=True))
        self.assertIn("IGPU_DATA_CONFLICT", ids(r, "WARN"))

    def test_board_without_outputs_is_hard(self):
        r = run(self.nogpu("AMD Ryzen 5 9600X", "ryzen-9000", board__display_outputs=0))
        self.assertIn("DISPLAY_OUTPUT", ids(r, "HARD"))

    def test_unknown_igpu_blocks_in_final(self):
        r = run(self.nogpu("Some Future CPU 1234", "unknown-family"), final=True)
        self.assertEqual(r["exit_code"], 3)
        self.assertIn("DISPLAY_OUTPUT", [i["id"] for i in r["incomplete"]])

    def test_office_on_am5_igpu_needs_no_dgpu(self):
        b = self.nogpu("AMD Ryzen 5 7600", "ryzen-7000", cpu__ppt_w=88, cpu__box_cooler=True)
        r = run(b, use_case="office")
        self.assertEqual(ids(r, "HARD"), [])
        gpu_warns = [f for f in r["findings"] if f["severity"] == "WARN" and "GPU" in f["id"] and "missing" not in f]
        self.assertEqual(gpu_warns, [])

    @needs_research
    def test_igpu_rules_are_in_the_research_with_sources(self):
        text = research_text()
        for needle in ("7500F", "Discrete Graphics Card Required", "265KF", "No integrated graphics", "780M"):
            self.assertIn(needle, text)
        rule_ids = [r["id"] for r in RULES["platforms"]["igpu_rules"]]
        self.assertTrue(rule_ids)
        for r in RULES["platforms"]["igpu_rules"]:
            self.assertIn(r["source"]["label"], ("V", "S"))


class Item2FinalMode(unittest.TestCase):
    def test_base_is_complete_in_final(self):
        r = run(BASE, final=True)
        self.assertEqual(r["exit_code"], 0, r.get("incomplete"))
        self.assertEqual(r["incomplete"], [])

    def test_missing_hard_input_is_incomplete_exit_3_in_final(self):
        r = run(build(board__socket=None), final=True)
        self.assertEqual(r["exit_code"], 3)
        self.assertIn("CPU_BOARD_SOCKET", [i["id"] for i in r["incomplete"]])

    def test_same_gap_outside_final_is_warn_exit_0(self):
        self.assertEqual(run(build(board__socket=None))["exit_code"], 0)

    def test_hard_failure_outranks_incomplete(self):
        r = run(build(board__socket=None, ram__type="DDR4"), final=True)
        self.assertEqual(r["exit_code"], 2)

    def test_cli_final_flag(self):
        self.assertEqual(cli(build(case=None), "--final").returncode, 3)

    def test_page_contract_forbids_cannot_check_in_published_claims(self):
        text = (SKILLS_DIR / "pc-build-recommendations" / "references" / "our-pick-page-contract.md").read_text(
            encoding="utf-8")
        self.assertRegex(text, r"(?i)never .*cannot check")
        self.assertIn("--final", text)


class Item3PsuPolicy(unittest.TestCase):
    def sizing(self, ppt, tbp, maker=None, oc=False, catalog=None):
        b = build(cpu__ppt_w=ppt, gpu__tbp_w=tbp, gpu__factory_oc=oc, gpu__min_system_psu_w=maker)
        return run(b, catalog=catalog)["psu_sizing"]

    def test_user_expectations(self):
        cases = [("9800X3D+5080", 162, 360, 850, 850), ("9800X3D+5070Ti", 162, 300, 750, 750),
                 ("9600X+5060", 88, 145, 550, 550), ("9950X+5090", 230, 575, 1000, 1200)]
        for name, ppt, tbp, maker, expected in cases:
            with self.subTest(name):
                self.assertEqual(self.sizing(ppt, tbp, maker)["recommended_psu_w"], expected)

    def test_5090_arithmetic_is_880(self):
        s = self.sizing(230, 575, 1000)
        self.assertEqual(s["dc_w"], 880)
        self.assertEqual(s["recommended_min_w"], 1100)

    def test_research_dc_rows(self):
        for ppt, tbp, oc, dc in [(88, 145, False, 308), (162, 250, False, 487), (162, 300, False, 537),
                                 (162, 304, True, 571), (250, 360, False, 685)]:
            self.assertEqual(self.sizing(ppt, tbp, oc=oc)["dc_w"], dc)

    def test_hard_only_below_dc_over_090(self):
        # DC 537: 0.90 -> 596.7, 0.80 -> 671.25
        r = run(build(psu__rated_w=650, gpu__min_system_psu_w=None))
        self.assertNotIn("PSU_BELOW_MINIMUM", ids(r, "HARD"))
        self.assertIn("PSU_BELOW_RECOMMENDED", ids(r, "WARN"))
        r = run(build(psu__rated_w=550, gpu__min_system_psu_w=None))
        self.assertIn("PSU_BELOW_MINIMUM", ids(r, "HARD"))

    def test_hard_below_maker_minimum(self):
        r = run(build(psu__rated_w=700, gpu__min_system_psu_w=750))
        self.assertIn("PSU_BELOW_MINIMUM", ids(r, "HARD"))

    def test_quiet_target_is_info_only(self):
        # 9800X3D + 5080 on 850 W: DC 597, quiet target 853 W
        r = run(build(gpu__tbp_w=360, gpu__min_system_psu_w=850, gpu__model="GeForce RTX 5080 16GB"))
        self.assertIn("PSU_QUIET_TARGET", ids(r, "INFO"))
        self.assertNotIn("PSU_BELOW_RECOMMENDED", ids(r))
        self.assertEqual(r["psu_sizing"]["quiet_target_w"], 853)

    @needs_research
    def test_research_formula_updated(self):
        text = research_text()
        self.assertIn("DC/0.90", text)
        self.assertIn("880", text)
        self.assertNotIn("| 9950X + 5090 | 905 W", text)

    def test_skill_states_new_policy(self):
        text = (SKILLS_DIR / "pc-power-sizing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("min_system_psu_w", text)
        self.assertIn("quiet target", text.lower())


class Item4Connectors(unittest.TestCase):
    def test_5080_adapter_with_three_8pin_cables_is_not_hard(self):
        b = build(psu__native_12v2x6=False, psu__native_12v2x6_cable_w=None, psu__atx_version="2.52",
                  psu__pcie_8pin_cables=3)
        r = run(b)
        self.assertNotIn("GPU_POWER_CONFIG", ids(r, "HARD"))
        self.assertIn("PSU_NATIVE_12V2X6_PREFERRED", ids(r, "WARN"))
        self.assertIn("PSU_ATX3_PREFERRED", ids(r, "WARN"))
        self.assertEqual(r["exit_code"], 0)

    def test_too_few_8pin_cables_is_hard(self):
        b = build(psu__native_12v2x6=False, psu__native_12v2x6_cable_w=None, psu__pcie_8pin_cables=2)
        self.assertIn("GPU_POWER_CONFIG", ids(run(b), "HARD"))

    def test_native_cable_below_card_rating_is_hard(self):
        b = build(gpu__supported_power_configs=[{"type": "native_16pin", "min_cable_w": 600}],
                  psu__native_12v2x6_cable_w=450)
        self.assertIn("GPU_POWER_CONFIG", ids(run(b), "HARD"))

    def test_native_cable_satisfies_5090(self):
        b = build(gpu__supported_power_configs=[{"type": "adapter_8pin", "min_cables": 4},
                                                {"type": "native_16pin", "min_cable_w": 600}],
                  gpu__tbp_w=575, gpu__min_system_psu_w=1000, psu__rated_w=1200)
        r = run(b)
        self.assertNotIn("GPU_POWER_CONFIG", ids(r))
        self.assertNotIn("PSU_NATIVE_12V2X6_PREFERRED", ids(r))

    def test_unknown_supported_configs_is_cannot_check(self):
        r = run(build(gpu__supported_power_configs=None))
        self.assertIn("gpu.supported_power_configs", find(r, "GPU_POWER_CONFIG")[0]["missing"])

    @needs_research
    def test_research_no_blanket_no_adapters(self):
        text = research_text()
        self.assertNotIn("No adapters:", text)
        self.assertIn("independent dedicated cables", text)


class Item5BiosSupport(unittest.TestCase):
    def test_known_unsupported_is_hard(self):
        r = run(build(board__bios={"cpu_support_confirmed": False}))
        self.assertIn("BIOS_CPU_SUPPORT", ids(r, "HARD"))

    def test_support_list_without_cpu_is_hard(self):
        r = run(build(board__bios={"supported_cpus": ["Ryzen 7 9700X"]}))
        self.assertIn("BIOS_CPU_SUPPORT", ids(r, "HARD"))

    def test_support_list_with_cpu_passes(self):
        r = run(build(board__bios={"supported_cpus": ["AMD Ryzen 7 9800X3D"]}))
        self.assertNotIn("BIOS_CPU_SUPPORT", ids(r))

    def test_unknown_support_warns_outside_final(self):
        r = run(build(board__bios={"agesa": "1.2.8.0"}))
        self.assertEqual(find(r, "BIOS_CPU_SUPPORT")[0]["severity"], "WARN")
        self.assertEqual(r["exit_code"], 0)

    def test_unknown_support_blocks_final(self):
        r = run(build(board__bios={"agesa": "1.2.8.0"}), final=True)
        self.assertEqual(r["exit_code"], 3)
        self.assertIn("BIOS_CPU_SUPPORT", [i["id"] for i in r["incomplete"]])


class Item6PublishGate(unittest.TestCase):
    def test_good_page_passes(self):
        r = gate(good_page())
        self.assertEqual(r["publish_blockers"], [], r["publish_blockers"])
        self.assertEqual(r["exit_code"], 0)

    def test_total_is_recomputed(self):
        p = good_page()
        p["headline_total_gbp_inc_vat"] = 1280.0  # excludes the mandatory charge
        self.assertIn("PUB_TOTAL_MISMATCH", blockers(gate(p)))

    def test_line_items_must_come_from_db(self):
        p = good_page()
        p["line_items"][0]["source"] = "manual"
        self.assertIn("PUB_LINE_ITEM_SOURCE", blockers(gate(p)))

    def test_missing_pricing_blocks(self):
        p = good_page()
        del p["mandatory_charges"]
        self.assertIn("PUB_MISSING_PRICING", blockers(gate(p)))
        p = good_page()
        p["line_items"] = []
        self.assertIn("PUB_MISSING_PRICING", blockers(gate(p)))

    def test_out_of_band_total_blocks(self):
        p = good_page()
        p["band"] = "800-1200"
        self.assertIn("PUB_BAND", blockers(gate(p)))

    def test_stale_or_future_price_date_blocks(self):
        self.assertIn("PUB_PRICE_DATE", blockers(gate(good_page(), today="2026-10-30")))
        self.assertIn("PUB_PRICE_DATE", blockers(gate(good_page(), today="2026-09-01")))

    def test_ex_vat_blocks(self):
        p = good_page()
        p["vat_inclusive"] = False
        self.assertIn("PUB_NOT_VAT_INCLUSIVE", blockers(gate(p)))

    def test_required_fields(self):
        for field in ("performance_class", "upgrade_path"):
            p = good_page()
            p[field] = " "
            self.assertIn("PUB_REQUIRED_FIELD", blockers(gate(p)), field)
        p = good_page()
        p["exclusions"] = ["monitor"]
        self.assertIn("PUB_EXCLUSIONS", blockers(gate(p)))

    def test_undisclosed_warn_blocks(self):
        p = good_page()
        p["build"]["ram"]["modules"] = 4
        p["line_items"][2]["quantity"] = 2
        self.assertIn("PUB_UNDISCLOSED_WARN", blockers(gate(p)))
        p["disclosed_warnings"] = ["AM5_FOUR_DIMMS"]
        self.assertNotIn("PUB_UNDISCLOSED_WARN", blockers(gate(p)))

    def test_cannot_check_blocks(self):
        p = good_page()
        p["build"]["board"].pop("lane_sharing")
        self.assertIn("PUB_CANNOT_CHECK", blockers(gate(p)))

    def test_hard_and_incomplete_block(self):
        p = good_page()
        p["build"]["cpu"]["socket"] = "AM4"
        self.assertIn("PUB_CHECK_HARD", blockers(gate(p)))
        p = good_page()
        del p["build"]["case"]
        self.assertIn("PUB_CHECK_INCOMPLETE", blockers(gate(p)))

    def test_cli_publish_gate_exit_codes(self):
        self.assertEqual(cli(good_page(), "--publish-gate", "--today", "2026-09-27").returncode, 0)
        p = good_page()
        p["headline_total_gbp_inc_vat"] = 1.0
        self.assertEqual(cli(p, "--publish-gate", "--today", "2026-09-27").returncode, 2)

    def test_page_schema_exists_and_is_strict(self):
        schema = json.loads((SKILL_ROOT / "schemas" / "our-pick.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(pc.validate(good_page(), schema, strict=True), [])
        p = good_page()
        p["surprise"] = 1
        self.assertNotEqual(pc.validate(p, schema, strict=True), [])

    def test_bands_override_file(self):
        with tempfile.TemporaryDirectory() as d:
            bands = Path(d) / "bands.json"
            bands.write_text(json.dumps({"bands": [{"id": "custom", "min_gbp": 0, "max_gbp": 5000}]}),
                             encoding="utf-8")
            proc = cli(BASE, "--bands", str(bands), "--band", "custom")
        self.assertEqual(proc.returncode, 0, proc.stderr)


class Item7Cap(unittest.TestCase):
    def test_selection_criteria_required(self):
        p = good_page()
        del p["selection_criteria"]
        self.assertIn("PUB_SELECTION_CRITERIA", blockers(gate(p)))
        p = good_page()
        p["selection_criteria"]["as_of"] = "someday"
        self.assertIn("PUB_SELECTION_CRITERIA", blockers(gate(p)))

    def test_superlative_needs_evidence(self):
        p = good_page()
        p["headline"] = "The best 1440p gaming PC"
        self.assertIn("PUB_SUPERLATIVE", blockers(gate(p)))
        p["superlative_evidence"] = {"as_of": "2026-09-27", "source": "internal market survey",
                                     "summary": "lowest price among 40 compared builds"}
        self.assertNotIn("PUB_SUPERLATIVE", blockers(gate(p)))

    @needs_research
    def test_cap_citations_corrected_everywhere(self):
        files = list(SKILLS_DIR.glob("pc-*/**/*.md")) + [RESEARCH]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "3.33" in line:
                    self.assertNotRegex(line, r"(?i)best", f"{f}: CAP 3.33 still tied to 'best' claims")
        rec = (SKILLS_DIR / "pc-build-recommendations" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("3.34", rec)
        self.assertIn("same need", rec)


class Item8Validation(unittest.TestCase):
    def test_nan_and_infinity_rejected(self):
        raw = json.dumps(BASE).replace('"ppt_w": 162', '"ppt_w": NaN')
        self.assertEqual(cli(raw).returncode, 3)
        raw = json.dumps(BASE).replace('"ppt_w": 162', '"ppt_w": Infinity')
        self.assertEqual(cli(raw).returncode, 3)
        raw = json.dumps(BASE).replace('"ppt_w": 162', '"ppt_w": 1e999')
        self.assertEqual(cli(raw).returncode, 3)

    def test_atx_version_parsed_exactly(self):
        self.assertEqual(cli(build(psu__atx_version="3 bananas")).returncode, 3)

    def test_dates_parsed_exactly(self):
        self.assertEqual(cli(build(pricing__priced_at="2026-13-40")).returncode, 3)

    def test_empty_catalog_rejected(self):
        self.assertEqual(cli(build(psu_catalog_w=[])).returncode, 3)
        self.assertEqual(cli(BASE, "--psu-catalog", "").returncode, 3)
        with self.assertRaises(pc.BadInput):
            pc.check(BASE, catalog=[])

    def test_unknown_fields_rejected_in_final_only(self):
        b = build(cpu__colour="red")
        self.assertEqual(cli(b).returncode, 0)
        self.assertEqual(cli(b, "--final").returncode, 3)

    def test_module_capacity_rename(self):
        self.assertEqual(cli(build(ram__capacity_gb=16, ram__module_capacity_gb=None), "--final").returncode, 3)
        r = run(build(ram__module_capacity_gb=8), use_case="dev")
        self.assertIn("UC_RAM_MIN", ids(r, "WARN"))


class Item9UseCaseScope(unittest.TestCase):
    def test_streaming_cores_only_for_cpu_encoding(self):
        b = build(cpu__cores=6, workload={"encoding_mode": "gpu"})
        self.assertNotIn("UC_CORES_MIN", ids(run(b, use_case="streaming")))
        b = build(cpu__cores=6, workload={"encoding_mode": "cpu"})
        self.assertIn("UC_CORES_MIN", ids(run(b, use_case="streaming"), "WARN"))

    def test_esports_vram_is_preference(self):
        b = build(gpu__model="GeForce RTX 5060 8GB", gpu__vram_gb=8, gpu__tbp_w=145, gpu__lanes=8, cpu__tier="mainstream")
        r = run(b, use_case="esports")
        self.assertNotIn("UC_VRAM_MIN", ids(r))
        self.assertIn("UC_VRAM_PREFERRED", ids(r, "INFO"))

    def test_8gb_note_is_scoped_info(self):
        r = run(build(gpu__vram_gb=8))
        f = find(r, "VRAM_8GB_SCOPE")
        self.assertEqual(f[0]["severity"], "INFO")
        self.assertIn("67", f[0]["message"])
        self.assertNotIn("legacy", f[0]["message"].lower())


class Item10Minor(unittest.TestCase):
    def test_claim_specific_freshness_anchors(self):
        for f in (SKILLS_DIR / "pc-gpu-tiering" / "references" / "gpu-and-ai-tables.md",
                  SKILLS_DIR / "pc-gpu-tiering" / "SKILL.md"):
            text = f.read_text(encoding="utf-8")
            self.assertIn("subject: puget-2025-creator-results", text, f)
            self.assertIn("subject: hub-8gb-vram-verdict", text, f)

    def test_descriptions_short_and_distinct(self):
        router = frontmatter_description("pc-builder")
        for child in CHILDREN:
            self.assertIn(child, router)
            desc = frontmatter_description(child)
            self.assertLessEqual(len(desc), 360, child)
            for other in CHILDREN + ["pc-builder"]:
                if other != child:
                    self.assertNotIn(other, desc, f"{child} names {other}")
        self.assertLessEqual(len(router), 420)

    def test_context_gate_structured_result(self):
        r = pc.context_gate(use_case=None, band="800-1200", workload=None)
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(set(r["missing"]), {"use_case", "workload"})
        self.assertTrue(r["question"])
        self.assertEqual(pc.context_gate(use_case="aaa-1440p", band="1200-2000", workload=None)["status"], "ok")
        proc = cli({}, "--context-gate", "--band", "800-1200")
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(json.loads(proc.stdout)["status"], "needs_input")

    @needs_research
    def test_every_tabled_chipset_is_in_the_research(self):
        text = research_text()
        for chip in RULES["platforms"]["chipsets"]:
            self.assertRegex(text, r"\b" + re.escape(chip) + r"\b", chip)


class FollowUpFamilyNormalisation(unittest.TestCase):
    """cpu.family in human form is normalised for lookup; absent family is derived from the model."""

    ALIASES = {
        "Ryzen 9000": "ryzen-9000", "AMD Ryzen 9000 Series": "ryzen-9000", "ryzen_9000": "ryzen-9000",
        "Ryzen 8000G": "ryzen-8000g", "AMD Ryzen 5000 Series": "ryzen-5000",
        "Core Ultra 200S": "core-ultra-200s", "Intel Core Ultra 200S": "core-ultra-200s",
        "Core Ultra 200S Plus": "core-ultra-200s-plus",
        "14th Gen Core": "core-14", "Core i5 14th gen": "core-14", "Intel 13th Gen Core": "core-13",
        "ryzen-7000": "ryzen-7000",
    }
    MODELS = {
        "AMD Ryzen 5 9600X": "ryzen-9000", "Ryzen 5 7500F": "ryzen-7000", "AMD Ryzen 7 8700G": "ryzen-8000g",
        "Ryzen 5 5600X": "ryzen-5000", "Core Ultra 7 265KF": "core-ultra-200s", "i5-14600KF": "core-14",
        "Intel Core i9-13900K": "core-13", "Intel Core i5-12400F": "core-12",
    }

    def test_alias_forms_normalise(self):
        for raw, slug in self.ALIASES.items():
            with self.subTest(raw):
                self.assertEqual(pc.canonical_family(raw, RULES), slug)

    def test_family_derived_from_model(self):
        for model, slug in self.MODELS.items():
            with self.subTest(model):
                self.assertEqual(pc.family_from_model(model, RULES), slug)

    def test_unknown_family_and_model_are_not_guessed(self):
        self.assertIsNone(pc.canonical_family("Zen Mystery", RULES))
        self.assertIsNone(pc.canonical_family("Ryzen 4000", RULES))
        self.assertIsNone(pc.family_from_model("Some Future CPU 1234", RULES))
        self.assertIsNone(pc.family_from_model("AMD Ryzen 5 8400F", RULES))  # 8000 non-G: not in the tables

    def nogpu(self, **kw):
        b = build(gpu=None, **kw)
        b["cpu"].pop("igpu", None)
        return b

    def test_human_family_drives_igpu_rules(self):
        r = run(self.nogpu(cpu__model="AMD Ryzen 5 9600X", cpu__family="Ryzen 9000", cpu__ppt_w=88))
        self.assertNotIn("DISPLAY_OUTPUT", ids(r))
        r = run(self.nogpu(cpu__model="Intel Core Ultra 7 265KF", cpu__family="Intel Core Ultra 200S",
                           cpu__socket="LGA1851", board__socket="LGA1851", board__chipset="Z890"))
        self.assertIn("DISPLAY_OUTPUT", ids(r, "HARD"))

    def test_absent_family_derived_from_model_for_rules(self):
        r = run(self.nogpu(cpu__model="AMD Ryzen 5 7500F", cpu__family=None))
        self.assertIn("DISPLAY_OUTPUT", ids(r, "HARD"))
        r = run(self.nogpu(cpu__model="i5-14600KF", cpu__family=None, cpu__socket="LGA1700",
                           board__socket="LGA1700", board__chipset="Z790"))
        self.assertIn("DISPLAY_OUTPUT", ids(r, "HARD"))

    def test_human_family_drives_bios_minimum(self):
        r = run(build(cpu__family="AMD Ryzen 9000 Series", board__chipset="B650", board__bios={"agesa": "1.1.7.0"}))
        self.assertIn("BIOS_MINIMUM", ids(r, "WARN"))

    def test_unrecognised_family_is_cannot_check_and_final_incomplete(self):
        b = self.nogpu(cpu__model="AMD Ryzen 5 9600X", cpu__family="Zen Mystery")
        r = run(b)
        f = [x for x in find(r, "DISPLAY_OUTPUT") if "missing" in x]
        self.assertTrue(f)
        self.assertIn("unrecognised", " ".join(f[0]["missing"]))
        self.assertEqual(run(b, final=True)["exit_code"], 3)

    def test_schema_documents_canonical_slugs_and_aliases(self):
        schema = json.loads((SKILL_ROOT / "schemas" / "build.v1.json").read_text(encoding="utf-8"))
        fam = schema["properties"]["cpu"]["properties"]["family"]
        self.assertEqual(sorted(fam["x-canonical-values"]), sorted(RULES["platforms"]["cpu_families"]))
        self.assertIn("Ryzen 9000", json.dumps(fam["x-accepted-aliases"]))
        self.assertNotIn("enum", fam)  # aliases must validate


if __name__ == "__main__":
    unittest.main()
