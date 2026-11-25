"""Tests for pc_check.py rules. Stdlib unittest only.

Run from the skill root:  python3 -m unittest discover -s tests -v
Every rule in data/rules.v1.json has at least one test that builds a failing
case from a clean base build and asserts the finding (written red-first).
Revise-round items (codex skill_challenger) are in test_revise.py.
"""
from __future__ import annotations

import re
import unittest

from helpers import (BASE, FINDINGS_SCHEMA, RULES, SKILLS_DIR, build, cli, find, ids, pc, run)


class TestBaseAndContract(unittest.TestCase):
    def test_base_build_is_clean(self):
        r = run(BASE)
        self.assertEqual(ids(r, "HARD"), [])
        self.assertEqual(ids(r, "WARN"), [], r["findings"])
        self.assertEqual(r["exit_code"], 0)

    def test_every_rule_has_an_implementation_and_vice_versa(self):
        self.assertEqual({r["id"] for r in RULES["rules"]}, set(pc.RULE_IMPLS))

    def test_every_rule_carries_required_metadata(self):
        for r in RULES["rules"] + RULES["publish_rules"]:
            for key in ("id", "severity", "inputs", "relation", "message", "source"):
                self.assertIn(key, r, r["id"])
            self.assertIn(r["severity"], ("HARD", "WARN", "INFO"))
            self.assertIn(r["source"]["label"], ("V", "S", "I"))
            self.assertTrue(r["source"]["url"])

    def test_output_matches_findings_schema(self):
        r = run(build(gpu__vram_gb=8, psu__rated_w=500), use_case="aaa-1440p", band="1200-2000")
        self.assertEqual(pc.validate(r, FINDINGS_SCHEMA), [])

    def test_finding_sources_come_from_rules(self):
        r = run(build(cpu__socket="AM4"))
        f = find(r, "CPU_BOARD_SOCKET")[0]
        rule = next(x for x in RULES["rules"] if x["id"] == "CPU_BOARD_SOCKET")
        self.assertEqual(f["source"], rule["source"])


class TestCompatibility(unittest.TestCase):
    def test_socket_mismatch_is_hard(self):
        r = run(build(cpu__socket="LGA1851"))
        self.assertIn("CPU_BOARD_SOCKET", ids(r, "HARD"))
        self.assertEqual(r["exit_code"], 2)

    def test_chipset_not_on_socket_is_hard(self):
        self.assertIn("BOARD_CHIPSET_SOCKET", ids(run(build(board__chipset="Z890")), "HARD"))

    def test_board_memory_type_not_allowed_by_socket_is_hard(self):
        r = run(build(board__memory_type="DDR4", ram__type="DDR4"))
        self.assertIn("BOARD_MEMORY_TYPE_SOCKET", ids(r, "HARD"))

    def test_ddr_mismatch_is_hard(self):
        r = run(build(ram__type="DDR4"))
        self.assertIn("RAM_TYPE_BOARD", ids(r, "HARD"))
        self.assertEqual(r["exit_code"], 2)

    def test_lga1700_board_may_be_ddr4(self):
        b = build(cpu__socket="LGA1700", cpu__family="core-14", cpu__model="Intel Core i5-14600K",
                  board__socket="LGA1700", board__chipset="Z790", board__memory_type="DDR4",
                  ram__type="DDR4", board__bios={"cpu_support_confirmed": True})
        r = run(b)
        self.assertNotIn("BOARD_MEMORY_TYPE_SOCKET", ids(r))
        self.assertNotIn("RAM_TYPE_BOARD", ids(r))

    def test_ryzen_2000_on_b550_is_hard(self):
        b = build(cpu__socket="AM4", cpu__family="ryzen-2000", cpu__model="Ryzen 5 2600",
                  board__socket="AM4", board__chipset="B550", board__memory_type="DDR4", ram__type="DDR4")
        self.assertIn("CPU_CHIPSET_UNSUPPORTED", ids(run(b), "HARD"))

    def test_ryzen_9000_on_old_agesa_warns(self):
        r = run(build(board__chipset="B650", board__bios={"agesa": "1.1.7.0"}))
        self.assertIn("BIOS_MINIMUM", ids(r, "WARN"))

    def test_ryzen_9000_on_new_agesa_passes_minimum(self):
        r = run(build(board__chipset="B650", board__bios={"agesa": "1.2.0.2"}, cpu__model="Ryzen 7 9700X"))
        self.assertNotIn("BIOS_MINIMUM", ids(r))

    def test_9950x3d2_needs_letter_suffixed_agesa(self):
        r = run(build(cpu__model="Ryzen 9 9950X3D2", board__bios={"agesa": "1.3.0.0"}))
        self.assertIn("BIOS_MINIMUM", ids(r, "WARN"))
        r = run(build(cpu__model="Ryzen 9 9950X3D2", board__bios={"agesa": "1.3.0.0a"}))
        self.assertNotIn("BIOS_MINIMUM", ids(r))

    def test_bios_requirement_confirmed_passes(self):
        r = run(build(board__chipset="B650", board__bios={"cpu_support_confirmed": True}))
        self.assertNotIn("BIOS_MINIMUM", ids(r))

    def test_too_many_modules_is_hard(self):
        self.assertIn("RAM_MODULES_SLOTS", ids(run(build(board__dimm_slots=2, ram__modules=4)), "HARD"))

    def test_four_dimms_on_am5_warns(self):
        r = run(build(ram__modules=4))
        self.assertIn("AM5_FOUR_DIMMS", ids(r, "WARN"))
        self.assertIn("3600", find(r, "AM5_FOUR_DIMMS")[0]["message"])

    def test_speed_above_official_is_info(self):
        self.assertIn("RAM_SPEED_OFFICIAL", ids(run(build(ram__speed=6000)), "INFO"))

    def test_unlocked_cpu_on_locked_chipset_warns(self):
        self.assertIn("OC_CHIPSET_LOCKED", ids(run(build(board__chipset="B840")), "WARN"))

    def test_8500g_limits_gpu_to_x4(self):
        r = run(build(cpu__model="Ryzen 5 8500G", cpu__family="ryzen-8000g", cpu__ppt_w=88))
        self.assertIn("APU_GPU_LANES", ids(r, "WARN"))
        self.assertIn("x4", find(r, "APU_GPU_LANES")[0]["message"])

    def _x8(self, **kw):
        base = dict(gpu__model="GeForce RTX 5060 Ti 8GB", gpu__lanes=8, gpu__vram_gb=8, gpu__tbp_w=180,
                    gpu__min_system_psu_w=None)
        base.update(kw)
        return build(**base)

    def test_8gb_x8_card_on_pcie4_warns(self):
        b = self._x8(board__chipset="B550", board__socket="AM4", board__gpu_slot_pcie_gen=4,
                     cpu__socket="AM4", cpu__family="ryzen-5000", cpu__model="Ryzen 5 5600", cpu__igpu=False,
                     board__memory_type="DDR4", ram__type="DDR4", board__bios={"cpu_support_confirmed": True})
        self.assertIn("X8_LINK_GEN_LOW_VRAM", ids(run(b), "WARN"))

    def test_8gb_x8_card_on_pcie3_warns(self):
        b = self._x8(board__chipset="B450", board__socket="AM4", board__gpu_slot_pcie_gen=None,
                     cpu__socket="AM4", cpu__family="ryzen-5000", cpu__model="Ryzen 5 5600", cpu__igpu=False,
                     board__memory_type="DDR4", ram__type="DDR4", board__bios={"cpu_support_confirmed": True})
        r = run(b)
        self.assertIn("X8_LINK_GEN_LOW_VRAM", ids(r, "WARN"))
        self.assertIn("3.0", find(r, "X8_LINK_GEN_LOW_VRAM")[0]["message"])

    def test_x8_lanes_come_from_table_when_record_omits_them(self):
        r = run(self._x8(gpu__lanes=None, board__gpu_slot_pcie_gen=4))
        self.assertIn("X8_LINK_GEN_LOW_VRAM", ids(r, "WARN"))

    def test_16gb_x8_card_on_pcie4_is_info_only(self):
        r = run(self._x8(gpu__model="GeForce RTX 5060 Ti 16GB", gpu__vram_gb=16, board__gpu_slot_pcie_gen=4))
        self.assertIn("X8_LINK_GEN", ids(r, "INFO"))
        self.assertNotIn("X8_LINK_GEN_LOW_VRAM", ids(r))

    def test_rx_9060_xt_is_not_treated_as_x8(self):
        r = run(self._x8(gpu__model="Radeon RX 9060 XT 8GB", gpu__lanes=None, board__gpu_slot_pcie_gen=4))
        self.assertNotIn("X8_LINK_GEN_LOW_VRAM", ids(r))

    def test_lane_sharing_trigger_warns(self):
        r = run(build(board__lane_sharing=[{"trigger_slot": "M2_1", "effect": "gpu_x8"}]))
        self.assertIn("LANE_SHARING", ids(r, "WARN"))

    def test_lane_sharing_unknown_is_cannot_check(self):
        f = find(run(build(board__lane_sharing=None)), "LANE_SHARING")
        self.assertEqual(f[0]["severity"], "WARN")
        self.assertIn("board.lane_sharing", f[0]["missing"])


class TestPhysicalFit(unittest.TestCase):
    def test_board_too_big_for_case_is_hard(self):
        self.assertIn("BOARD_CASE_FIT", ids(run(build(board__form_factor="E-ATX")), "HARD"))

    def test_atx_psu_in_sfx_case_is_hard(self):
        self.assertIn("PSU_CASE_FIT", ids(run(build(case__psu_form_factors=["SFX"])), "HARD"))

    def test_sfx_psu_in_atx_case_needs_bracket(self):
        r = run(build(psu__form_factor="SFX"))
        self.assertNotIn("PSU_CASE_FIT", ids(r))
        self.assertIn("PSU_SFX_BRACKET", ids(r, "INFO"))

    def test_gpu_too_long_is_hard(self):
        self.assertIn("GPU_CASE_LENGTH", ids(run(build(case__gpu_max_length_mm=300)), "HARD"))

    def test_gpu_too_thick_is_hard(self):
        self.assertIn("GPU_CASE_SLOTS", ids(run(build(gpu__slots=3.5, case__gpu_max_slots=3)), "HARD"))

    def test_air_cooler_too_tall_is_hard(self):
        self.assertIn("COOLER_CASE_FIT", ids(run(build(case__cpu_cooler_max_height_mm=160)), "HARD"))

    def test_radiator_not_supported_is_hard(self):
        r = run(build(cooler={"model": "AIO 420", "type": "aio", "class": "aio_420", "radiator_mm": 420,
                              "sockets": ["AM5"]}))
        self.assertIn("COOLER_CASE_FIT", ids(r, "HARD"))

    def test_cooler_without_socket_mount_is_hard(self):
        self.assertIn("COOLER_SOCKET", ids(run(build(cooler__sockets=["LGA1700"])), "HARD"))

    def test_lga1700_mount_fits_lga1851(self):
        b = build(cpu__socket="LGA1851", cpu__family="core-ultra-200s", cpu__model="Core Ultra 7 265K",
                  cpu__ppt_w=250, board__socket="LGA1851", board__chipset="Z890",
                  board__bios={"cpu_support_confirmed": True},
                  cooler__sockets=["LGA1700"], cooler__class="aio_360", cooler__type="aio", cooler__radiator_mm=360)
        self.assertNotIn("COOLER_SOCKET", ids(run(b)))

    def test_no_cooler_for_no_box_cooler_cpu_is_hard(self):
        self.assertIn("COOLER_REQUIRED", ids(run(build(cooler=None)), "HARD"))

    def test_no_box_cooler_known_from_table(self):
        self.assertIn("COOLER_REQUIRED", ids(run(build(cooler=None, cpu__box_cooler=None)), "HARD"))

    def test_box_cooler_cpu_without_cooler_passes(self):
        r = run(build(cooler=None, cpu__box_cooler=True, cpu__model="Ryzen 5 8500G",
                      cpu__family="ryzen-8000g", cpu__ppt_w=88, gpu=None))
        self.assertNotIn("COOLER_REQUIRED", ids(r))

    def test_single_tower_on_162w_cpu_warns(self):
        self.assertIn("COOLER_CAPACITY", ids(run(build(cooler__class="single_tower")), "WARN"))

    def test_dual_tower_on_230w_cpu_warns(self):
        r = run(build(cooler__class="dual_tower", cpu__ppt_w=230, cpu__model="Ryzen 9 9950X"))
        self.assertIn("COOLER_CAPACITY", ids(r, "WARN"))


class TestPsuQuality(unittest.TestCase):
    def test_bronze_850_warns(self):
        self.assertIn("PSU_EFFICIENCY", ids(run(build(psu__cybenetics_eta="Bronze")), "WARN"))

    def test_tier_b_with_300w_gpu_warns(self):
        self.assertIn("PSU_TIER", ids(run(build(psu__spl_tier="B")), "WARN"))

    def test_tier_b_with_small_gpu_passes(self):
        r = run(build(psu__spl_tier="B", gpu__tbp_w=250, gpu__model="GeForce RTX 5070 12GB"))
        self.assertNotIn("PSU_TIER", ids(r))

    def test_cultists_tier_is_ignored_with_warn(self):
        self.assertIn("PSU_CULTISTS_IGNORED", ids(run(build(psu__cultists_tier="A")), "WARN"))


class TestUseCaseAndBudget(unittest.TestCase):
    def test_use_case_vram_minimum(self):
        r = run(build(gpu__vram_gb=12, gpu__model="GeForce RTX 5070 12GB"), use_case="aaa-4k")
        self.assertIn("UC_VRAM_MIN", ids(r, "WARN"))

    def test_use_case_ram_minimum(self):
        self.assertIn("UC_RAM_MIN", ids(run(build(), use_case="creator"), "WARN"))

    def test_use_case_core_minimum(self):
        self.assertIn("UC_CORES_MIN", ids(run(build(), use_case="creator"), "WARN"))

    def test_office_with_dgpu_is_info(self):
        self.assertIn("UC_DGPU_UNNEEDED", ids(run(build(), use_case="office"), "INFO"))

    def test_flagship_cpu_with_entry_gpu_warns_for_gaming(self):
        b = build(gpu__model="GeForce RTX 5060 8GB", gpu__vram_gb=8, gpu__tbp_w=145, gpu__lanes=8)
        self.assertIn("UC_BALANCE", ids(run(b, use_case="esports"), "WARN"))

    def test_flagship_gpu_with_entry_cpu_warns_for_productivity(self):
        b = build(cpu__tier="entry", cpu__cores=16, gpu__model="GeForce RTX 5090 32GB", gpu__vram_gb=32,
                  gpu__tbp_w=575, gpu__min_system_psu_w=1000, psu__rated_w=1300, ram__module_capacity_gb=32)
        self.assertIn("UC_BALANCE", ids(run(b, use_case="creator"), "WARN"))

    def test_local_ai_reports_what_fits(self):
        f = find(run(build(), use_case="local-ai"), "UC_LOCAL_AI_VRAM")
        self.assertEqual(f[0]["severity"], "INFO")
        self.assertIn("14B at Q8", f[0]["message"])

    def test_total_outside_band_warns(self):
        self.assertIn("BAND_TOTAL", ids(run(build(), band="800-1200"), "WARN"))

    def test_total_inside_band_passes(self):
        self.assertNotIn("BAND_TOTAL", ids(run(build(), band="1200-2000")))

    def test_undated_price_warns(self):
        self.assertIn("PRICE_VAT_DATED", ids(run(build(pricing__priced_at=None)), "WARN"))

    def test_ex_vat_price_warns(self):
        self.assertIn("PRICE_VAT_DATED", ids(run(build(pricing__vat_inclusive=False)), "WARN"))


class TestMissingInputs(unittest.TestCase):
    def test_missing_field_is_warn_cannot_check_never_silent(self):
        f = find(run(build(board__socket=None)), "CPU_BOARD_SOCKET")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "WARN")
        self.assertIn("cannot check", f[0]["message"])
        self.assertIn("board.socket", f[0]["missing"])

    def test_missing_gpu_power_leaves_psu_unsized(self):
        r = run(build(gpu__tbp_w=None))
        self.assertIsNone(r["recommended_psu_w"])
        self.assertIn("PSU_BELOW_MINIMUM", ids(r, "WARN"))

    def test_missing_psu_is_warn_not_pass(self):
        r = run(build(psu=None))
        self.assertIn("PSU_BELOW_MINIMUM", ids(r, "WARN"))
        self.assertIn("GPU_POWER_CONFIG", ids(r, "WARN"))


class TestCli(unittest.TestCase):
    def test_clean_build_exits_0(self):
        import json
        proc = cli(BASE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["recommended_psu_w"], 750)

    def test_hard_failure_exits_2(self):
        self.assertEqual(cli(build(cpu__socket="AM4")).returncode, 2)

    def test_bad_json_exits_3(self):
        self.assertEqual(cli("{not json").returncode, 3)

    def test_wrong_type_exits_3(self):
        self.assertEqual(cli(build(cpu__ppt_w="162")).returncode, 3)

    def test_unknown_use_case_exits_3(self):
        self.assertEqual(cli(BASE, "--use-case", "mining").returncode, 3)

    def test_unknown_band_exits_3(self):
        self.assertEqual(cli(BASE, "--band", "999").returncode, 3)

    def test_psu_catalog_flag(self):
        import json
        out = json.loads(cli(BASE, "--psu-catalog", "500,800,1000").stdout)
        self.assertEqual(out["recommended_psu_w"], 800)


class TestNoPricesInSkills(unittest.TestCase):
    def test_no_gbp_amounts_in_skill_text(self):
        for md in SKILLS_DIR.glob("pc-*/**/*.md"):
            text = md.read_text(encoding="utf-8")
            self.assertIsNone(re.search(chr(0xA3) + r"\s?\d", text), f"price-like GBP amount in {md}")


if __name__ == "__main__":
    unittest.main()
