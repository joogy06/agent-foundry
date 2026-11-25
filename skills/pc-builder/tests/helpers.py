"""Shared fixtures for the pc_check tests. Stdlib only."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = SKILL_ROOT.parent
SCRIPT = SKILL_ROOT / "scripts" / "pc_check.py"
RESEARCH = SKILLS_DIR.parent / "docs" / "research" / "2026-09-27-pc-builder-research.md"


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


RULES = load_json(SKILL_ROOT / "data" / "rules.v1.json")
FINDINGS_SCHEMA = load_json(SKILL_ROOT / "schemas" / "findings.v1.json")


def _load_module():
    spec = importlib.util.spec_from_file_location("pc_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pc = _load_module()

BASE = {
    "schema": "build.v1",
    "cpu": {"model": "AMD Ryzen 7 9800X3D", "family": "ryzen-9000", "socket": "AM5", "ppt_w": 162,
            "cores": 8, "unlocked": True, "box_cooler": False, "igpu": True, "tier": "enthusiast"},
    "board": {"model": "Example B850 ATX", "socket": "AM5", "chipset": "B850", "memory_type": "DDR5",
              "dimm_slots": 4, "form_factor": "ATX", "gpu_slot_pcie_gen": 5, "display_outputs": 2,
              "bios": {"agesa": "1.2.8.0", "cpu_support_confirmed": True}, "lane_sharing": []},
    "ram": {"type": "DDR5", "modules": 2, "module_capacity_gb": 16, "speed": 5600},
    "gpu": {"model": "GeForce RTX 5070 Ti 16GB", "tbp_w": 300, "pcie_gen": 5, "lanes": 16, "vram_gb": 16,
            "length_mm": 304, "slots": 3, "power_connector": "12V-2x6", "factory_oc": False,
            "min_system_psu_w": 750,
            "supported_power_configs": [{"type": "adapter_8pin", "min_cables": 3},
                                        {"type": "native_16pin", "min_cable_w": 450}]},
    "psu": {"model": "Example 850", "rated_w": 850, "atx_version": "3.1", "native_12v2x6": True,
            "native_12v2x6_cable_w": 600, "pcie_8pin_cables": 3,
            "cybenetics_eta": "Gold", "spl_tier": "A", "form_factor": "ATX"},
    "case": {"model": "Example mesh", "board_form_factors": ["ATX", "mATX", "ITX"], "psu_form_factors": ["ATX"],
             "gpu_max_length_mm": 400, "gpu_max_slots": 4, "cpu_cooler_max_height_mm": 170,
             "radiator_mm_supported": [240, 280, 360], "front": "mesh"},
    "cooler": {"model": "Example dual tower", "type": "air", "class": "top_dual_tower", "height_mm": 168,
               "sockets": ["AM4", "AM5", "LGA1700", "LGA1851"]},
    "storage": [{"model": "Example NVMe", "type": "nvme", "pcie_gen": 4, "slot": "M2_1", "capacity_gb": 2000}],
    "pricing": {"total_gbp_inc_vat": 1500, "vat_inclusive": True, "priced_at": "2026-09-27"},
}


def build(**changes):
    """Deep-copy BASE and apply double-underscore path changes; value None deletes the key."""
    b = copy.deepcopy(BASE)
    for path, value in changes.items():
        parts = path.split("__")
        node = b
        for p in parts[:-1]:
            node = node[p]
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return b


TODAY = RULES["as_of"]  # pinned so the suite does not age; the staleness tests move it explicitly


def run(b, use_case=None, band=None, catalog=None, final=False, today=TODAY):
    return pc.check(b, use_case=use_case, band=band, catalog=catalog, final=final, today=today)


def ids(result, severity=None):
    return [f["id"] for f in result["findings"] if severity is None or f["severity"] == severity]


def find(result, rule_id):
    return [f for f in result["findings"] if f["id"] == rule_id]


def cli(payload, *args):
    """Run the CLI on PAYLOAD (dict or raw text); returns CompletedProcess."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "in.json"
        p.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        if "--today" not in args:
            args = (*args, "--today", TODAY)
        return subprocess.run([sys.executable, str(SCRIPT), str(p), *args],
                              capture_output=True, text=True, encoding="utf-8")


def good_page():
    """A publishable our-pick.v1 page around BASE."""
    b = copy.deepcopy(BASE)
    b.pop("pricing")
    return {
        "schema": "our-pick.v1",
        "use_case": "aaa-1440p",
        "band": "1200-2000",
        "workload": "1440p high settings",
        "headline": "Our pick: 1440p gaming PC",
        "priced_at": "2026-09-27",
        "currency": "GBP",
        "vat_inclusive": True,
        "line_items": [
            {"role": "cpu", "sku": "C1", "name": "CPU", "source": "db", "unit_price_gbp_inc_vat": 400.0, "quantity": 1},
            {"role": "gpu", "sku": "G1", "name": "GPU", "source": "db", "unit_price_gbp_inc_vat": 700.0, "quantity": 1},
            {"role": "ram", "sku": "R1", "name": "RAM", "source": "db", "unit_price_gbp_inc_vat": 90.0, "quantity": 2},
        ],
        "mandatory_charges": [{"name": "Build and test", "source": "db", "amount_gbp_inc_vat": 60.0}],
        "headline_total_gbp_inc_vat": 1340.0,
        "performance_class": "1440p high settings class",
        "upgrade_path": "AM5: CPU upgrades promised to Zen 6; PSU headroom 100 W",
        "exclusions": ["operating system", "monitor"],
        "skip": ["RGB"],
        "selection_criteria": {"as_of": "2026-09-27",
                               "criteria": ["lowest runtime price meeting the aaa-1440p profile"]},
        "disclosed_warnings": [],
        "build": b,
    }
