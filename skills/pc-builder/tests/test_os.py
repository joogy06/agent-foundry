"""Red-first tests for the OS dimension (SteamOS and Linux). Research: docs/research/2026-09-27-pc-builder-os-research.md."""
from __future__ import annotations

import copy
import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import (BASE, RULES, SKILL_ROOT, SKILLS_DIR, TODAY, build, cli, find, good_page, ids, pc, run)

FIXTURE = json.loads((SKILL_ROOT / "tests" / "fixtures" / "awacy-fixture.json").read_text(encoding="utf-8"))
SNAPSHOT_PATH = SKILL_ROOT / "data" / "awacy-snapshot.json"
REFRESH = SKILL_ROOT / "scripts" / "refresh_awacy.py"
AMD_GPU = {"model": "Radeon RX 9070 XT 16GB", "tbp_w": 304, "pcie_gen": 5, "lanes": 16, "vram_gb": 16,
           "length_mm": 300, "slots": 3, "power_connector": "2x8-pin", "factory_oc": False,
           "supported_power_configs": [{"type": "direct_8pin", "min_cables": 2}]}


def linux(**changes):
    """A clean AMD Linux build; changes use the helpers.build path syntax."""
    b = copy.deepcopy(BASE)
    b["gpu"] = copy.deepcopy(AMD_GPU)
    b.update({"os": "linux", "distro": "Bazzite 44", "kernel": "6.16", "mesa": "26.2", "secure_boot": False,
              "wifi": {"chip": "BE200"}})
    for path, value in changes.items():
        parts = path.split("__")
        node = b
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return b


def check(b, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("awacy", FIXTURE)
    return pc.check(b, **kw)


def os_ids(r, severity=None):
    return [i for i in ids(r, severity) if i.startswith("OS_") or i == "AWACY_DATA_STALE"]


class NoOsNoChange(unittest.TestCase):
    def test_os_absent_gives_no_os_findings(self):
        self.assertEqual(os_ids(check(BASE)), [])

    def test_windows_gives_no_os_findings(self):
        self.assertEqual(os_ids(check(build(os="windows"))), [])

    def test_clean_amd_linux_build(self):
        r = check(linux())
        self.assertEqual([i for i in os_ids(r) if i not in os_ids(r, "INFO")], [], r["findings"])


class SteamOS(unittest.TestCase):
    def steamos(self, **kw):
        return linux(os="steamos", distro=None, kernel=None, **kw)

    def test_steamos_nvidia_is_hard(self):
        b = self.steamos()
        b["gpu"] = copy.deepcopy(BASE["gpu"])  # RTX 5070 Ti
        r = check(b)
        self.assertIn("OS_STEAMOS_NVIDIA", ids(r, "HARD"))
        self.assertEqual(r["exit_code"], 2)

    def test_vendor_comes_from_the_record_first(self):
        b = self.steamos(gpu__vendor="nvidia")
        self.assertIn("OS_STEAMOS_NVIDIA", ids(check(b), "HARD"))

    def test_steamos_intel_is_community_tier(self):
        b = self.steamos(gpu__model="Intel Arc B580 12GB", gpu__vram_gb=12, gpu__tbp_w=190, gpu__lanes=8,
                         gpu__pcie_gen=4)
        self.assertIn("OS_STEAMOS_INTEL", ids(check(b), "WARN"))

    def test_steamos_uses_its_own_kernel(self):
        self.assertNotIn("OS_KERNEL_MINIMUM", ids(check(self.steamos())))

    def test_dual_boot_warns(self):
        self.assertIn("OS_STEAMOS_DUAL_BOOT", ids(check(self.steamos(dual_boot=True)), "WARN"))

    def test_branding_without_licence_is_hard(self):
        r = check(self.steamos(branding="Powered by SteamOS"))
        self.assertIn("OS_STEAMOS_BRANDING", ids(r, "HARD"))
        self.assertNotIn("OS_STEAMOS_BRANDING", ids(check(self.steamos(branding="Steam Machine", valve_licence=True))))
        self.assertNotIn("OS_STEAMOS_BRANDING",
                         ids(check(self.steamos(branding="SteamOS preinstalled (community-supported install)"))))


class LinuxNvidia(unittest.TestCase):
    def nv(self, **kw):
        b = linux(**kw)
        b["gpu"] = copy.deepcopy(BASE["gpu"])
        return b

    def test_nvidia_dx12_warn(self):
        self.assertIn("OS_NVIDIA_DX12", ids(check(self.nv()), "WARN"))

    def test_nvidia_secure_boot_warn(self):
        self.assertIn("OS_NVIDIA_SECURE_BOOT", ids(check(self.nv(secure_boot=True)), "WARN"))
        self.assertNotIn("OS_NVIDIA_SECURE_BOOT", ids(check(self.nv(secure_boot=False))))

    def test_nvidia_legacy_arch_warn(self):
        b = self.nv()
        b["gpu"]["arch"] = "pascal"
        self.assertIn("OS_NVIDIA_LEGACY", ids(check(b), "WARN"))


class LinuxWifi(unittest.TestCase):
    def test_mt7927_is_hard(self):
        r = check(linux(wifi__chip="MT7927"))
        self.assertIn("OS_WIFI_UNSUPPORTED", ids(r, "HARD"))
        self.assertIn("Intel", find(r, "OS_WIFI_UNSUPPORTED")[0]["message"])

    def test_rtl8922ae_warns(self):
        self.assertIn("OS_WIFI_REGRESSION", ids(check(linux(wifi__chip="RTL8922AE")), "WARN"))

    def test_unknown_chip_is_verify(self):
        r = check(linux(wifi__chip="QCA9999"))
        self.assertIn("OS_WIFI_UNVERIFIED", ids(r, "WARN"))

    def test_known_good_chips(self):
        for chip in ("MT7925", "AX210", "BE200", "Intel AX211"):
            self.assertNotIn("OS_WIFI_UNVERIFIED", ids(check(linux(wifi__chip=chip))), chip)


class LinuxKernel(unittest.TestCase):
    def test_rdna4_on_kernel_6_8_is_hard(self):
        self.assertIn("OS_KERNEL_MINIMUM", ids(check(linux(kernel="6.8")), "HARD"))

    def test_rdna4_on_old_mesa_is_hard(self):
        self.assertIn("OS_KERNEL_MINIMUM", ids(check(linux(mesa="24.3")), "HARD"))

    def test_arc_b_on_kernel_6_8_is_hard(self):
        b = linux(kernel="6.8", gpu__model="Intel Arc B580 12GB", gpu__vram_gb=12, gpu__tbp_w=190,
                  gpu__lanes=8, gpu__pcie_gen=4)
        self.assertIn("OS_KERNEL_MINIMUM", ids(check(b), "HARD"))

    def test_panther_lake_on_kernel_6_16_is_hard(self):
        b = linux(kernel="6.16", gpu=None, cpu__igpu=True)
        b["cpu"]["igpu_arch"] = "xe3"
        self.assertIn("OS_KERNEL_MINIMUM", ids(check(b), "HARD"))

    def test_ryzen_9000_on_kernel_6_9_warns(self):
        b = linux(kernel="6.9")
        b["gpu"] = copy.deepcopy(BASE["gpu"])  # not RDNA4, isolates the CPU rule
        r = check(b)
        self.assertIn("OS_KERNEL_RECOMMENDED", ids(r, "WARN"))
        self.assertNotIn("OS_KERNEL_MINIMUM", ids(r))

    def test_arrow_lake_on_kernel_6_12_warns(self):
        b = linux(kernel="6.12", cpu__family="core-ultra-200s", cpu__model="Core Ultra 7 265K", cpu__socket="LGA1851",
                  board__socket="LGA1851", board__chipset="Z890")
        self.assertIn("OS_KERNEL_RECOMMENDED", ids(check(b), "WARN"))

    def test_unparseable_kernel_is_verify(self):
        r = check(linux(kernel="latest"))
        self.assertIn("OS_KERNEL_UNVERIFIED", ids(r, "WARN"))
        self.assertNotIn("OS_KERNEL_MINIMUM", ids(r, "HARD"))

    def test_missing_kernel_blocks_final_for_rdna4(self):
        r = check(linux(kernel=None), final=True)
        self.assertEqual(r["exit_code"], 3)


class Games(unittest.TestCase):
    def test_fortnite_on_linux_is_hard(self):
        r = check(linux(buyer={"games": ["Fortnite"]}))
        self.assertIn("OS_GAME_ANTICHEAT", ids(r, "HARD"))
        self.assertIn("Fortnite", find(r, "OS_GAME_ANTICHEAT")[0]["message"])

    def test_broken_game_is_hard_and_supported_is_fine(self):
        self.assertIn("OS_GAME_ANTICHEAT", ids(check(linux(buyer={"games": ["PUBG: Battlegrounds"]})), "HARD"))
        self.assertEqual(os_ids(check(linux(buyer={"games": ["counter-strike 2"]})), "HARD"), [])

    def test_unknown_or_planned_game_is_verify(self):
        for g in ("Some Indie Game", "Example Planned Game"):
            self.assertIn("OS_GAME_UNVERIFIED", ids(check(linux(buyer={"games": [g]})), "WARN"), g)

    def test_fortnite_on_windows_is_fine(self):
        self.assertEqual(os_ids(check(build(os="windows", buyer={"games": ["Fortnite"]}))), [])

    def test_wants_windows_only_things(self):
        r = check(linux(buyer={"wants": ["game_pass", "ms_office"]}))
        self.assertIn("OS_BUYER_WANTS", ids(r, "WARN"))


class Distros(unittest.TestCase):
    def test_unknown_distro_is_verify(self):
        self.assertIn("OS_DISTRO_UNKNOWN", ids(check(linux(distro="Linux Mint 22")), "WARN"))

    def test_distro_near_eol_warns(self):
        b = linux(distro="Fedora 44")
        self.assertNotIn("OS_DISTRO_EOL", ids(check(b)))
        self.assertIn("OS_DISTRO_EOL", ids(check(b, today="2027-01-15"), "WARN"))

    def test_aliases_resolve(self):
        for d in ("Ubuntu 26.04 LTS", "Pop!_OS 24.04", "CachyOS", "bazzite"):
            self.assertNotIn("OS_DISTRO_UNKNOWN", ids(check(linux(distro=d))), d)


class AwacySnapshot(unittest.TestCase):
    def test_snapshot_is_data_not_rules(self):
        rules_text = (SKILL_ROOT / "data" / "rules.v1.json").read_text(encoding="utf-8")
        self.assertNotIn("Fortnite", rules_text)
        snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(snap["stale_after_days"], 30)
        self.assertEqual(snap["block_after_days"], 60)
        self.assertEqual(len(snap["games"]), 1167)
        for key in ("Denied", "Broken", "Supported", "Running"):
            self.assertIn(key, snap["counts"])
        self.assertEqual(set(snap["games"][0]), {"name", "status"})

    def test_stale_snapshot_warns_and_blocks_final(self):
        old = dict(FIXTURE, as_of="2026-07-01")
        r = check(linux(), awacy=old, today="2026-08-05")
        self.assertIn("AWACY_DATA_STALE", ids(r, "WARN"))
        r = check(linux(), awacy=old, today="2026-09-27", final=True)
        self.assertEqual(r["exit_code"], 3)
        self.assertIn("AWACY_DATA_STALE", [i["id"] for i in r["incomplete"]])

    def test_snapshot_not_consulted_without_linux(self):
        old = dict(FIXTURE, as_of="2020-01-01")
        self.assertNotIn("AWACY_DATA_STALE", ids(check(BASE, awacy=old)))

    def test_refresh_script_trims_and_dates(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "snap.json"
            proc = subprocess.run([sys.executable, str(REFRESH), "--input",
                                   str(SKILL_ROOT / "tests" / "fixtures" / "games-raw.json"),
                                   "--output", str(out), "--today", "2026-10-01", "--min-games", "1"],
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            snap = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(snap["as_of"], "2026-10-01")
        self.assertEqual(snap["games"][0], {"name": "Fortnite", "status": "Denied"})
        self.assertEqual(snap["counts"]["Denied"], 1)

    def test_refresh_refuses_a_suspiciously_small_or_bad_download(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "snap.json"
            proc = subprocess.run([sys.executable, str(REFRESH), "--input",
                                   str(SKILL_ROOT / "tests" / "fixtures" / "games-raw.json"), "--output", str(out)],
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(out.exists())

    def test_cli_awacy_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.json"
            p.write_text(json.dumps(FIXTURE), encoding="utf-8")
            proc = cli(linux(buyer={"games": ["Fortnite"]}), "--awacy", str(p))
        self.assertEqual(proc.returncode, 2)


class Profiles(unittest.TestCase):
    def test_linux_profiles_exist(self):
        for uc in ("linux-gaming", "steamos-living-room"):
            self.assertIn(uc, RULES["use_cases"])

    def test_profile_os_mismatch_warns(self):
        self.assertIn("OS_PROFILE_MISMATCH", ids(check(BASE, use_case="linux-gaming"), "WARN"))
        self.assertNotIn("OS_PROFILE_MISMATCH", ids(check(linux(), use_case="linux-gaming")))


class PublishGate(unittest.TestCase):
    DISCLOSURES = {
        "anti_cheat": ["Fortnite", "Valorant", "Apex Legends", "Call of Duty: Warzone"],
        "game_pass_office": "No PC Game Pass or Microsoft Office desktop apps; Xbox Cloud and Office on the web work.",
        "rgb_software": "Windows-only RGB and fan software will not work; OpenRGB is partial.",
        "support_scope": "We support the hardware and the preinstalled OS; community support covers the rest.",
        "return_path": "If a must-have game will not run, return it within 30 days.",
    }

    def page(self, os="linux", disclosures=True, **kw):
        p = good_page()
        p["build"] = linux(os=os, **kw)
        p["build"].pop("pricing", None)
        p["build"].pop("buyer", None)
        if os == "steamos":
            p["build"].pop("distro", None)
            p["build"].pop("kernel", None)
        if disclosures:
            p["os_disclosures"] = dict(self.DISCLOSURES)
            if os == "steamos":
                p["os_disclosures"]["os_description"] = "SteamOS preinstalled (community-supported install)"
        return p

    def blockers(self, p):
        r = pc.publish_gate(p, today=TODAY, awacy=FIXTURE)
        return [b["id"] for b in r["publish_blockers"]], r

    def test_linux_page_with_disclosures_passes(self):
        b, r = self.blockers(self.page())
        self.assertEqual(b, [], r["publish_blockers"])

    def test_linux_page_missing_disclosures_is_blocked(self):
        self.assertIn("PUB_OS_DISCLOSURES", self.blockers(self.page(disclosures=False))[0])
        p = self.page()
        p["os_disclosures"]["return_path"] = " "
        self.assertIn("PUB_OS_DISCLOSURES", self.blockers(p)[0])

    def test_windows_page_needs_no_os_disclosures(self):
        self.assertNotIn("PUB_OS_DISCLOSURES", self.blockers(good_page())[0])

    def test_steamos_page_needs_the_community_wording(self):
        p = self.page(os="steamos")
        self.assertEqual(self.blockers(p)[0], [])
        del p["os_disclosures"]["os_description"]
        self.assertIn("PUB_OS_DISCLOSURES", self.blockers(p)[0])

    def test_steamos_branding_without_licence_is_blocked(self):
        p = self.page(os="steamos")
        p["headline"] = "Our pick: Powered by SteamOS living-room PC"
        self.assertIn("PUB_STEAMOS_BRANDING", self.blockers(p)[0])
        p["build"]["valve_licence"] = True
        self.assertNotIn("PUB_STEAMOS_BRANDING", self.blockers(p)[0])


class Text(unittest.TestCase):
    def test_os_sections(self):
        needles = {"pc-builder": "## Operating systems", "pc-compatibility": "Linux kernel",
                   "pc-gpu-tiering": "## Linux drivers", "pc-build-recommendations": "steamos-living-room"}
        for skill, needle in needles.items():
            self.assertIn(needle, (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8"), skill)

    def test_os_quarterly_list_is_anchored(self):
        text = "".join((SKILLS_DIR / s / "SKILL.md").read_text(encoding="utf-8") for s in
                       ("pc-builder", "pc-gpu-tiering", "pc-compatibility", "pc-build-recommendations"))
        for subject in ("awacy-anti-cheat-list", "steamos-nvidia-and-desktop-policy", "nvidia-linux-driver-branch",
                        "linux-kernel-mesa-minimums", "rtw89-mt7927-fixes", "linux-distro-eols",
                        "game-pass-on-linux", "steam-survey-linux-share"):
            self.assertIn(f"subject: {subject}", text, subject)


if __name__ == "__main__":
    unittest.main()
