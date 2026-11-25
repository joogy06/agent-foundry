#!/usr/bin/env python3
"""pc_check.py - deterministic PC build compatibility and PSU sizing checker.

Reads a build JSON (schemas/build.v1.json) of component records from the
caller's database and applies the rules in data/rules.v1.json. No LLM, no
network, standard library only.

Usage:
    python3 pc_check.py BUILD.json [--use-case UC] [--band BAND] [--final]
                        [--bands FILE] [--psu-catalog 550,650,...] [--rules FILE]
    python3 pc_check.py PAGE.json --publish-gate [--today YYYY-MM-DD]
                        [--max-price-age-days N] [--bands FILE] [--psu-catalog ...]
    python3 pc_check.py - --context-gate [--use-case UC] [--band BAND] [--workload W]
    python3 pc_check.py - < BUILD.json

Modes:
  check (default)  Missing inputs on HARD/WARN rules are WARN "cannot check".
  --final          Publication check: unknown fields are rejected (exit 3), and a
                   HARD rule that could not run makes the result incomplete
                   (exit 3) unless a HARD finding already failed (exit 2).
  --publish-gate   PAGE.json is an our-pick.v1 page (schemas/our-pick.v1.json):
                   the embedded build is re-checked with --final and the page is
                   held to the publish_rules. Exit 0 publishable, 2 blocked.
  --context-gate   Ambiguity gate for callers that cannot ask: prints a
                   needs-input.v1 result. Exit 0 ok, 3 needs input.

Output: one JSON object (schemas/findings.v1.json, or needs-input.v1) on stdout.
Exit codes: 0 no HARD finding, 2 at least one HARD finding (or a publish
blocker), 3 bad input or (under --final) an incomplete check.

A missing input on a HARD or WARN rule produces a WARN "cannot check" finding
that lists the missing fields; it never passes silently. INFO rules are
context only and are skipped when their inputs are missing. An absent
optional component (gpu, cooler, storage, pricing, workload) makes the rules
that need it not applicable; required components (cpu, board, ram, psu, case)
that are absent make their rules report "cannot check". Numbers must be
finite: NaN, Infinity and overflowing literals are bad input.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = SKILL_ROOT / "data" / "rules.v1.json"
DEFAULT_BANDS = SKILL_ROOT / "data" / "budget-bands.uk.v1.json"
BUILD_SCHEMA = SKILL_ROOT / "schemas" / "build.v1.json"
PAGE_SCHEMA = SKILL_ROOT / "schemas" / "our-pick.v1.json"
DEFAULT_AWACY = SKILL_ROOT / "data" / "awacy-snapshot.json"

EXIT_OK, EXIT_HARD, EXIT_BAD_INPUT = 0, 2, 3


class BadInput(Exception):
    """Input that cannot be checked at all (exit 3)."""


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()


# -- small helpers ------------------------------------------------------------

def _reject_constant(name: str):
    raise BadInput(f"non-finite number {name} is not allowed")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise BadInput(f"number {text} overflows to a non-finite value")
    return value


def loads(text: str) -> object:
    """json.loads that rejects NaN, Infinity and overflowing literals."""
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def load_json(path: Path) -> object:
    return loads(path.read_text(encoding="utf-8"))


def parse_date(text) -> datetime.date | None:
    """Exact ISO date (YYYY-MM-DD), else None."""
    if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def get(build: dict, dotted: str):
    node = build
    for part in dotted.split("."):
        if not isinstance(node, dict) or node.get(part) is None:
            return MISSING
        node = node[part]
    return node


def has(build: dict, component: str) -> bool:
    return isinstance(build.get(component), dict)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).upper().replace("_", " ")).strip()


def model_matches(key: str, text: str, suffixes: list[str]) -> bool:
    """Whole-token match of KEY in TEXT, refusing a following variant suffix.

    'RTX 5060' matches 'GEFORCE RTX 5060 8GB' but not 'RTX 5060 TI'.
    """
    key_n, text_n = normalise(key), normalise(text)
    for m in re.finditer(r"(?<![A-Z0-9])" + re.escape(key_n) + r"(?![A-Z0-9])", text_n):
        rest = text_n[m.end():].split()
        if rest and rest[0] in suffixes:
            continue
        return True
    return False


def lookup_model(table: dict, text, suffixes: list[str]):
    """Longest matching key of TABLE found in TEXT, or None."""
    if text is MISSING:
        return None
    for key in sorted((k for k in table if k not in ("source", "not_x8")), key=len, reverse=True):
        if model_matches(key, text, suffixes):
            return key
    return None


def version_tuple(v: str):
    m = re.match(r"\s*(\d+(?:\.\d+)*)([A-Za-z]*)", str(v))
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split(".")), m.group(2).lower()


def version_ge(have: str, need: str) -> bool | None:
    a, b = version_tuple(have), version_tuple(need)
    if a is None or b is None:
        return None
    width = max(len(a[0]), len(b[0]))
    pad = lambda t: t + (0,) * (width - len(t))  # noqa: E731
    return (pad(a[0]), a[1]) >= (pad(b[0]), b[1])


def atx_major(v) -> float | None:
    """Exact ATX version ('3', '3.1', '2.52') as a float, else None."""
    if not isinstance(v, str) or not re.fullmatch(r"\d+(?:\.\d+)?", v):
        return None
    return float(v)


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def round_up_to_catalog(watts: float, catalog: list[int]) -> int | None:
    for size in sorted(catalog):
        if size >= watts:
            return size
    return None


# -- CPU family normalisation ----------------------------------------------------------

_FAMILY_NOISE = {"AMD", "INTEL", "SERIES", "PROCESSOR", "PROCESSORS", "DESKTOP", "FAMILY", "(R)", "(TM)"}


def canonical_family(raw, rules: dict) -> str | None:
    """Resolve a DB cpu.family value ('Ryzen 9000', 'Core i5 14th gen', 'ryzen-9000') to a slug, or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    slugs = rules["platforms"]["cpu_families"]
    text = raw.replace(chr(0x2122), " ").replace(chr(0xAE), " ")  # trademark signs
    words = [w for w in re.split(r"[\s_\-]+", text.upper()) if w and w not in _FAMILY_NOISE]
    direct = "-".join(words).lower()
    if direct in slugs:
        return direct
    for slug, info in slugs.items():
        if any(normalise(a) == normalise(raw) for a in info.get("aliases", [])):
            return slug
    candidate = None
    if "RYZEN" in words:
        nums = [w for w in words if re.fullmatch(r"\d{4}G?", w)]
        if len(nums) == 1:
            candidate = f"ryzen-{nums[0].lower()}"
    elif "ULTRA" in words and "200S" in words:
        candidate = "core-ultra-200s-plus" if "PLUS" in words else "core-ultra-200s"
    elif "CORE" in words or "GEN" in words or "GENERATION" in words:
        gens = [m.group(1) for w in words for m in [re.fullmatch(r"(\d{2})(?:TH)?", w)] if m]
        if len(gens) == 1 and ("GEN" in words or "GENERATION" in words or any(w.endswith("TH") for w in words)):
            candidate = f"core-{gens[0]}"
    return candidate if candidate in slugs else None


def family_from_model(model, rules: dict) -> str | None:
    """Derive the family slug from a model name with the sourced SKU tables, or None."""
    sku = sku_token(model if isinstance(model, str) else MISSING)
    if sku is None:
        return None
    words = set(normalise(str(model).replace("-", " ")).split())
    for entry in rules["platforms"]["cpu_family_from_model"]:
        if not words & set(entry["needs_word"].split("|")):
            continue
        if entry.get("also_word") and entry["also_word"] not in words:
            continue
        if re.search(entry["sku_regex"], sku):
            return entry["family"]
    return None


# -- minimal JSON Schema subset validator -------------------------------------------
# Supports: type, properties, required, items, enum, minimum, maximum, minItems,
# pattern, format: date. strict=True also rejects properties a schema does not list.

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def validate(value, schema: dict, path: str = "$", strict: bool = False) -> list[str]:
    errors: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        return [f"{path}: non-finite number"]
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](value) for x in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.fullmatch(schema["pattern"].strip("^$"), value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if schema.get("format") == "date" and parse_date(value) is None:
            errors.append(f"{path}: {value!r} is not an ISO date (YYYY-MM-DD)")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required {req!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value and value[key] is not None:
                errors.extend(validate(value[key], sub, f"{path}.{key}", strict))
        if strict and props:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unknown field {key!r}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{i}]", strict))
    return errors


# -- checking context ------------------------------------------------------------

class Ctx:
    def __init__(self, build: dict, rules: dict, use_case, band, catalog, final: bool = False,
                 today: datetime.date | None = None, bands_doc: dict | None = None, awacy: dict | None = None):
        self.b = build
        self.data = rules
        self.rules = {r["id"]: r for r in rules["rules"]}
        self.plat = rules["platforms"]
        self.suffixes = self.plat["model_suffix_tokens"]
        self.use_case = use_case
        self.band = band
        self.catalog = catalog
        self.final = final
        self.today = today or datetime.date.today()
        self.bands_doc = bands_doc
        self._awacy = awacy
        self.findings: list[dict] = []
        self.incomplete: list[dict] = []
        self.psu = {"dc_w": None, "hard_minimum_w": None, "recommended_min_w": None,
                    "maker_min_system_psu_w": None, "recommended_psu_w": None,
                    "quiet_target_w": None, "catalog_w": list(catalog)}
        self._dc_exact = None

    # finding emitters
    def fail(self, rule_id: str, **fmt):
        rule = self.rules[rule_id]
        try:
            msg = rule["message"].format(**fmt)
        except (KeyError, IndexError):
            msg = rule["message"]
        self.findings.append({"id": rule_id, "severity": rule["severity"], "message": msg,
                              "source": dict(rule["source"])})

    def missing(self, rule_id: str, fields: list[str]):
        rule = self.rules[rule_id]
        if rule["severity"] == "INFO":
            return
        if rule["severity"] == "HARD":
            self.incomplete.append({"id": rule_id, "missing": list(fields)})
        self.findings.append({
            "id": rule_id, "severity": "WARN",
            "message": f"cannot check {rule_id}: missing {', '.join(fields)} ({rule['relation']}).",
            "source": dict(rule["source"]), "missing": list(fields)})

    def block_final(self, rule_id: str, reason: str):
        """Under --final, record a non-HARD finding that must still block publication."""
        if self.final:
            self.incomplete.append({"id": rule_id, "missing": [reason]})

    def need(self, rule_id: str, *paths: str):
        """Return values for PATHS, or None after reporting the missing ones."""
        values = [get(self.b, p) for p in paths]
        absent = [p for p, v in zip(paths, values) if v is MISSING]
        if absent:
            self.missing(rule_id, absent)
            return None
        return values

    # derived facts
    def socket(self):
        s = get(self.b, "board.socket")
        return s if s is not MISSING else get(self.b, "cpu.socket")

    def chipset(self):
        c = get(self.b, "board.chipset")
        return None if c is MISSING else normalise(c)

    def chipset_info(self) -> dict:
        c = self.chipset()
        return self.plat["chipsets"].get(c, {}) if c else {}

    def family(self):
        """Canonical family slug, or MISSING (absent and not derivable, or unrecognised)."""
        raw = get(self.b, "cpu.family")
        if raw is not MISSING:
            slug = canonical_family(raw, self.data)
        else:
            slug = family_from_model(get(self.b, "cpu.model"), self.data)
        return slug if slug else MISSING

    # -- OS facts (SteamOS / Linux) --
    def os_mode(self):
        """'linux' or 'steamos' when OS rules apply, else None (absent or windows)."""
        v = get(self.b, "os")
        return v if v in ("linux", "steamos") else None

    def awacy(self) -> dict:
        if self._awacy is None:
            self._awacy = load_json(DEFAULT_AWACY)
        return self._awacy

    def gpu_vendor(self):
        if not has(self.b, "gpu"):
            return None
        v = get(self.b, "gpu.vendor")
        if v is not MISSING:
            return v
        model = get(self.b, "gpu.model")
        if model is MISSING:
            return None
        words = set(normalise(model).split())
        for entry in self.data["os"]["gpu_vendor_from_model"]:
            if words & set(entry["words"]):
                return entry["vendor"]
        return None

    def gpu_arch(self):
        if not has(self.b, "gpu"):
            return None
        a = get(self.b, "gpu.arch")
        if a is not MISSING:
            return str(a).lower()
        model = get(self.b, "gpu.model")
        if model is MISSING:
            return None
        for entry in self.data["os"]["gpu_arch_from_model"]:
            if re.search(entry["regex"], normalise(model)):
                return entry["arch"]
        return None

    def kernel(self):
        k = get(self.b, "kernel")
        if k is MISSING and self.os_mode() == "steamos":
            return self.data["os"]["steamos"]["kernel"]
        return k

    def family_gap(self) -> str:
        """Why the family is unknown, as a missing-field label."""
        raw = get(self.b, "cpu.family")
        if raw is not MISSING:
            return f"cpu.family (unrecognised: {raw!r})"
        return "cpu.family (absent, and cpu.model matches no SKU table)"

    def cpu_label(self) -> str:
        m = get(self.b, "cpu.model")
        return m if m is not MISSING else str(get(self.b, "cpu.family"))

    def gpu_lanes_gen(self):
        """(lanes, pcie_gen) of the card, from the record, else the x8/x16 tables."""
        lanes, gen = get(self.b, "gpu.lanes"), get(self.b, "gpu.pcie_gen")
        table = self.plat["x8_gpus"]
        model = get(self.b, "gpu.model")
        if lanes is MISSING or gen is MISSING:
            key = lookup_model(table, model, self.suffixes)
            if key:
                lanes = 8 if lanes is MISSING else lanes
                gen = table[key]["pcie_gen"] if gen is MISSING else gen
            else:
                key16 = lookup_model(table["not_x8"], model, self.suffixes)
                if key16:
                    lanes = table["not_x8"][key16]["lanes"] if lanes is MISSING else lanes
                    gen = table["not_x8"][key16]["pcie_gen"] if gen is MISSING else gen
        return lanes, gen

    def slot_gen(self):
        g = get(self.b, "board.gpu_slot_pcie_gen")
        if g is MISSING:
            g = self.chipset_info().get("gpu_slot_pcie_gen", MISSING)
        return g

    def apu_limit(self):
        key = lookup_model(self.plat["apu_gpu_lanes"], get(self.b, "cpu.model"), self.suffixes)
        return (key, self.plat["apu_gpu_lanes"][key]) if key else (None, None)

    def lane_sharing_active(self) -> list[dict]:
        sharing = get(self.b, "board.lane_sharing")
        storage = self.b.get("storage")
        if sharing is MISSING or not isinstance(storage, list):
            return []
        slots = {normalise(s.get("slot")) for s in storage if isinstance(s, dict) and s.get("slot")}
        return [e for e in sharing if isinstance(e, dict) and normalise(e.get("trigger_slot", "")) in slots]

    def gpu_tier(self):
        t = get(self.b, "gpu.tier")
        if t is not MISSING:
            return t
        model, vram = get(self.b, "gpu.model"), get(self.b, "gpu.vram_gb")
        if model is MISSING:
            return None
        best = None
        for entry in sorted(self.data["gpu_tiers"]["models"], key=lambda e: len(e["model"]), reverse=True):
            if not model_matches(entry["model"], model, self.suffixes):
                continue
            if "vram_gb" in entry:
                if vram is not MISSING and vram == entry["vram_gb"]:
                    return entry["tier"]
                continue
            best = best or entry["tier"]
        return best

    def use_case_profile(self) -> dict:
        return self.data["use_cases"][self.use_case] if self.use_case else {}


# -- rules: compatibility -----------------------------------------------------------

def r_cpu_board_socket(c: Ctx):
    v = c.need("CPU_BOARD_SOCKET", "cpu.socket", "board.socket")
    if v and normalise(v[0]) != normalise(v[1]):
        c.fail("CPU_BOARD_SOCKET", cpu_socket=v[0], board_socket=v[1])


def r_board_chipset_socket(c: Ctx):
    v = c.need("BOARD_CHIPSET_SOCKET", "board.socket", "board.chipset")
    if not v:
        return
    sock = c.plat["sockets"].get(v[0])
    known = c.plat["chipsets"].get(normalise(v[1]))
    # An unknown chipset is NOT_IN_RULES_DATA, not an incompatibility.
    if sock and known and known["socket"] != v[0]:
        c.fail("BOARD_CHIPSET_SOCKET", chipset=v[1], board_socket=v[0])


def r_board_memory_type_socket(c: Ctx):
    v = c.need("BOARD_MEMORY_TYPE_SOCKET", "board.socket", "board.memory_type")
    if not v:
        return
    sock = c.plat["sockets"].get(v[0])
    if sock and v[1] not in sock["memory_types"]:
        c.fail("BOARD_MEMORY_TYPE_SOCKET", board_socket=v[0], allowed="/".join(sock["memory_types"]),
               memory_type=v[1])


def r_ram_type_board(c: Ctx):
    v = c.need("RAM_TYPE_BOARD", "ram.type", "board.memory_type")
    if v and v[0] != v[1]:
        c.fail("RAM_TYPE_BOARD", ram_type=v[0], memory_type=v[1])


def r_cpu_chipset_unsupported(c: Ctx):
    chip = c.chipset()
    if chip is None:
        c.missing("CPU_CHIPSET_UNSUPPORTED", ["board.chipset"])
        return
    for entry in c.plat["unsupported_cpu_on_chipset"]:
        if chip not in entry["chipsets"]:
            continue
        fam = c.family()
        if fam is MISSING:
            c.missing("CPU_CHIPSET_UNSUPPORTED", [c.family_gap()])
        elif fam in entry["cpu_families"]:
            c.fail("CPU_CHIPSET_UNSUPPORTED", chipset=chip, cpu_family=fam)
        return


def _bios_requirements(c: Ctx):
    chip, fam, model = c.chipset(), c.family(), get(c.b, "cpu.model")
    sock = c.socket()
    reqs, family_unknown = [], False
    for req in c.plat["bios_minimums"]:
        if "cpu_model" in req:
            if model is not MISSING and model_matches(req["cpu_model"], model, c.suffixes) \
                    and sock in req.get("sockets", [sock]):
                reqs.append(req)
            continue
        families = req.get("cpu_families") or [req["cpu_family"]]
        if chip in req["chipsets"]:
            if fam is MISSING:
                family_unknown = True
            elif fam in families:
                reqs.append(req)
    return reqs, family_unknown


def _bios_support(c: Ctx):
    """True confirmed, False known unsupported, None unknown (for this exact CPU and BIOS)."""
    bios = get(c.b, "board.bios")
    if bios is MISSING:
        return None
    if isinstance(bios.get("cpu_support_confirmed"), bool):
        return bios["cpu_support_confirmed"]
    listed = bios.get("supported_cpus")
    if isinstance(listed, list):
        model = get(c.b, "cpu.model")
        if model is MISSING:
            return None
        return any(normalise(x) == normalise(model) or model_matches(x, model, c.suffixes)
                   or model_matches(model, x, c.suffixes) for x in listed)
    return None


def r_bios_cpu_support(c: Ctx):
    if not has(c.b, "cpu") or not has(c.b, "board"):
        c.missing("BIOS_CPU_SUPPORT", [p for p in ("cpu", "board") if not has(c.b, p)])
        return
    support = _bios_support(c)
    if support is None:
        c.missing("BIOS_CPU_SUPPORT", ["board.bios.cpu_support_confirmed or board.bios.supported_cpus (+ cpu.model)"])
    elif support is False:
        bios = c.b["board"]["bios"]
        detail = ("the board record marks it unsupported" if bios.get("cpu_support_confirmed") is False
                  else "it is not on the board's BIOS support list")
        c.fail("BIOS_CPU_SUPPORT", cpu_label=c.cpu_label(), detail=detail)


def r_bios_minimum(c: Ctx):
    if _bios_support(c) is True:
        return  # confirmed support for this exact BIOS supersedes the dated AGESA guidance
    if c.chipset() is None:
        c.missing("BIOS_MINIMUM", ["board.chipset"])
        return
    reqs, family_unknown = _bios_requirements(c)
    if family_unknown and not reqs:
        c.missing("BIOS_MINIMUM", [c.family_gap()])
        return
    if not reqs:
        return
    bios = c.b["board"].get("bios")
    if not isinstance(bios, dict):
        c.missing("BIOS_MINIMUM", ["board.bios"])
        return
    for req in reqs:
        agesa, need = bios.get("agesa"), req.get("min_agesa")
        if need and agesa and version_ge(agesa, need):
            continue
        c.fail("BIOS_MINIMUM", cpu_label=c.cpu_label(), chipset=c.chipset(), requirement=req["requirement"])


def r_ram_modules_slots(c: Ctx):
    modules = get(c.b, "ram.modules")
    slots = get(c.b, "board.dimm_slots")
    if slots is MISSING:
        slots = c.chipset_info().get("max_dimms", MISSING)
    absent = [p for p, v in (("ram.modules", modules), ("board.dimm_slots", slots)) if v is MISSING]
    if absent:
        c.missing("RAM_MODULES_SLOTS", absent)
    elif modules > slots:
        c.fail("RAM_MODULES_SLOTS", modules=modules, dimm_slots=slots)


def r_am5_four_dimms(c: Ctx):
    sock = c.socket()
    if sock is MISSING:
        c.missing("AM5_FOUR_DIMMS", ["board.socket"])
        return
    if sock != "AM5":
        return
    v = c.need("AM5_FOUR_DIMMS", "ram.modules")
    if v and v[0] >= 4:
        c.fail("AM5_FOUR_DIMMS")


def r_ram_speed_official(c: Ctx):
    fam, modules, speed = c.family(), get(c.b, "ram.modules"), get(c.b, "ram.speed")
    if MISSING in (fam, modules, speed):
        return
    table = c.plat["memory_official"].get(fam, {})
    key = "2" if modules <= 2 else "4"
    official = table.get(key)
    if official and speed > official:
        c.fail("RAM_SPEED_OFFICIAL", speed=speed, official=official, cpu_family=fam, modules=modules)


def r_oc_chipset_locked(c: Ctx):
    chip = c.chipset()
    if chip is None:
        c.missing("OC_CHIPSET_LOCKED", ["board.chipset"])
        return
    if chip not in c.plat["oc_incapable_chipsets"]:
        return
    v = c.need("OC_CHIPSET_LOCKED", "cpu.unlocked")
    if v and v[0] is True:
        c.fail("OC_CHIPSET_LOCKED", chipset=chip)


def r_apu_gpu_lanes(c: Ctx):
    if not has(c.b, "gpu"):
        return
    key, limit = c.apu_limit()
    if not key:
        return
    lanes, _gen = c.gpu_lanes_gen()
    if lanes is MISSING:
        c.missing("APU_GPU_LANES", ["gpu.lanes"])
    elif lanes > limit["lanes"]:
        c.fail("APU_GPU_LANES", cpu_model=key, apu_lanes=limit["lanes"], gpu_lanes=lanes)


def _effective_link(c: Ctx):
    """(effective_lanes, effective_gen, card_gen, missing_fields) for the GPU link."""
    lanes, gen = c.gpu_lanes_gen()
    missing = [p for p, v in (("gpu.lanes", lanes), ("gpu.pcie_gen", gen)) if v is MISSING]
    if missing:
        return None, None, None, missing
    eff_lanes, caps = lanes, []
    key, limit = c.apu_limit()
    if key:
        eff_lanes = min(eff_lanes, limit["lanes"])
        caps.append(limit["pcie_gen"])
    if any(e.get("effect") == "gpu_x8" for e in c.lane_sharing_active()):
        eff_lanes = min(eff_lanes, 8)
    if eff_lanes > 8:
        return eff_lanes, None, gen, []
    slot = c.slot_gen()
    if slot is MISSING:
        return eff_lanes, None, gen, ["board.gpu_slot_pcie_gen"]
    return eff_lanes, min([gen, slot] + caps), gen, []


def r_x8_link_gen_low_vram(c: Ctx):
    if not has(c.b, "gpu"):
        return
    lanes, eff_gen, card_gen, missing = _effective_link(c)
    if missing:
        c.missing("X8_LINK_GEN_LOW_VRAM", missing)
        return
    if lanes > 8 or eff_gen >= card_gen:
        return
    v = c.need("X8_LINK_GEN_LOW_VRAM", "gpu.vram_gb")
    if v and v[0] <= 8:
        c.fail("X8_LINK_GEN_LOW_VRAM", effective_gen=eff_gen)


def r_x8_link_gen(c: Ctx):
    if not has(c.b, "gpu"):
        return
    lanes, eff_gen, card_gen, missing = _effective_link(c)
    vram = get(c.b, "gpu.vram_gb")
    if missing or vram is MISSING or lanes > 8 or eff_gen >= card_gen:
        return  # missing inputs are reported once by X8_LINK_GEN_LOW_VRAM
    if vram > 8:
        c.fail("X8_LINK_GEN", effective_gen=eff_gen, gpu_gen=card_gen)


def r_lane_sharing(c: Ctx):
    storage = c.b.get("storage")
    if not isinstance(storage, list) or not storage:
        return
    if get(c.b, "board.lane_sharing") is MISSING:
        c.missing("LANE_SHARING", ["board.lane_sharing"])
        return
    for e in c.lane_sharing_active():
        effect = e.get("detail") or {"gpu_x8": "the GPU slot drops to x8",
                                      "sata_disabled": "some SATA ports are disabled"}.get(e.get("effect"), e.get("effect"))
        c.fail("LANE_SHARING", slot=e.get("trigger_slot"), effect=effect)


def sku_token(model) -> str | None:
    """The SKU token of a CPU model name: 'Intel Core i5-14600KF' -> '14600KF'."""
    if model is MISSING:
        return None
    tokens = re.findall(r"(?<![A-Z0-9])\d{3,5}[A-Z0-9]*(?![A-Z0-9])", normalise(str(model).replace("-", " ")))
    return tokens[-1] if tokens else None


def igpu_from_rules(c: Ctx):
    """(igpu, class, rule_id) from the sourced platform rules, or (None, None, None)."""
    fam, sku = c.family(), sku_token(get(c.b, "cpu.model"))
    if fam is MISSING:
        return None, None, None
    for rule in c.plat["igpu_rules"]:
        if fam not in rule["families"]:
            continue
        if "sku_regex" in rule and (sku is None or not re.search(rule["sku_regex"], sku)):
            continue
        return rule["igpu"], rule.get("class"), rule["id"]
    return None, None, None


def igpu_status(c: Ctx):
    """(igpu True/False/None, class, conflict tuple or None). The DB field wins unless the rule contradicts it."""
    db = get(c.b, "cpu.igpu")
    derived, cls, rule_id = igpu_from_rules(c)
    if db is not MISSING and derived is not None and db != derived:
        return None, None, (db, derived, rule_id)
    if db is not MISSING:
        return db, (cls if derived is not None else None), None
    return derived, cls, None


def _yn(v: bool) -> str:
    return "iGPU" if v else "no iGPU"


def r_igpu_data_conflict(c: Ctx):
    _igpu, _cls, conflict = igpu_status(c)
    if conflict:
        db, derived, rule_id = conflict
        c.fail("IGPU_DATA_CONFLICT", db=_yn(db), rule=_yn(derived), platform_rule=rule_id)


def r_display_output(c: Ctx):
    if has(c.b, "gpu"):
        return
    igpu, _cls, conflict = igpu_status(c)
    outs = get(c.b, "board.display_outputs")
    if igpu is False:
        c.fail("DISPLAY_OUTPUT", detail="no discrete GPU and the CPU has no integrated graphics.")
    elif outs is not MISSING and outs < 1:
        c.fail("DISPLAY_OUTPUT", detail="no discrete GPU and the board has no video outputs.")
    else:
        absent = []
        if igpu is None:
            if conflict:
                absent.append("cpu.igpu (conflicts with the platform rule)")
            elif c.family() is MISSING:
                absent.append("cpu.igpu or " + c.family_gap())
            else:
                absent.append("cpu.igpu (and no platform rule covers this CPU)")
        if outs is MISSING:
            absent.append("board.display_outputs")
        if absent:
            c.missing("DISPLAY_OUTPUT", absent)


def r_igpu_class(c: Ctx):
    if has(c.b, "gpu"):
        return
    igpu, cls, _conflict = igpu_status(c)
    if igpu and cls:
        c.fail("IGPU_CLASS", text=c.plat["igpu_class_text"][cls])


# -- rules: physical fit ------------------------------------------------------------

def r_board_case_fit(c: Ctx):
    v = c.need("BOARD_CASE_FIT", "board.form_factor", "case.board_form_factors")
    if v and v[0] not in v[1]:
        c.fail("BOARD_CASE_FIT", form_factor=v[0], case_boards="/".join(v[1]))


def _psu_fit(c: Ctx):
    ff, bays = get(c.b, "psu.form_factor"), get(c.b, "case.psu_form_factors")
    return ff, bays


def r_psu_case_fit(c: Ctx):
    v = c.need("PSU_CASE_FIT", "psu.form_factor", "case.psu_form_factors")
    if not v:
        return
    ff, bays = v
    if ff in bays or (ff in ("SFX", "SFX-L") and "ATX" in bays):
        return
    c.fail("PSU_CASE_FIT", psu_ff=ff, case_psus="/".join(bays))


def r_psu_sfx_bracket(c: Ctx):
    ff, bays = _psu_fit(c)
    if MISSING in (ff, bays):
        return
    if ff in ("SFX", "SFX-L") and ff not in bays and "ATX" in bays:
        c.fail("PSU_SFX_BRACKET", psu_ff=ff)


def r_gpu_case_length(c: Ctx):
    if not has(c.b, "gpu"):
        return
    v = c.need("GPU_CASE_LENGTH", "gpu.length_mm", "case.gpu_max_length_mm")
    if v and v[0] > v[1]:
        c.fail("GPU_CASE_LENGTH", length=v[0], max=v[1])


def r_gpu_case_slots(c: Ctx):
    if not has(c.b, "gpu"):
        return
    v = c.need("GPU_CASE_SLOTS", "gpu.slots", "case.gpu_max_slots")
    if v and v[0] > v[1]:
        c.fail("GPU_CASE_SLOTS", slots=v[0], max=v[1])


def r_cooler_case_fit(c: Ctx):
    if not has(c.b, "cooler"):
        return
    t = c.need("COOLER_CASE_FIT", "cooler.type")
    if not t or t[0] == "box":
        return
    if t[0] == "air":
        v = c.need("COOLER_CASE_FIT", "cooler.height_mm", "case.cpu_cooler_max_height_mm")
        if v and v[0] > v[1]:
            c.fail("COOLER_CASE_FIT", detail=f"Air cooler is {v[0]} mm tall; the case clears {v[1]} mm.")
    elif t[0] == "aio":
        v = c.need("COOLER_CASE_FIT", "cooler.radiator_mm", "case.radiator_mm_supported")
        if v and v[0] not in v[1]:
            c.fail("COOLER_CASE_FIT",
                   detail=f"{v[0]} mm radiator; the case mounts {'/'.join(str(x) for x in v[1])} mm.")


def r_cooler_socket(c: Ctx):
    if not has(c.b, "cooler") or get(c.b, "cooler.type") == "box":
        return
    v = c.need("COOLER_SOCKET", "cpu.socket", "cooler.sockets")
    if not v:
        return
    sock, mounts = v[0], [normalise(s) for s in v[1]]
    ok = sock in mounts or (sock == "LGA1851" and "LGA1700" in mounts)
    if not ok:
        c.fail("COOLER_SOCKET", sockets="/".join(v[1]), cpu_socket=sock)


def r_cooler_required(c: Ctx):
    if has(c.b, "cooler"):
        return
    box = get(c.b, "cpu.box_cooler")
    if box is MISSING:
        if lookup_model({k: 1 for k in c.plat["no_box_cooler_models"]}, get(c.b, "cpu.model"), c.suffixes):
            box = False
    if box is MISSING:
        c.missing("COOLER_REQUIRED", ["cpu.box_cooler", "cooler"])
    elif box is False:
        c.fail("COOLER_REQUIRED", cpu_label=c.cpu_label())


def r_cooler_capacity(c: Ctx):
    if not has(c.b, "cooler") or get(c.b, "cooler.type") == "box":
        return
    v = c.need("COOLER_CAPACITY", "cpu.ppt_w", "cooler.class")
    if not v:
        return
    ppt, cls = v
    table = c.data["cooling"]["class_max_w"]
    if cls not in table:
        c.missing("COOLER_CAPACITY", [f"cooler.class in {sorted(table)} (got {cls!r})"])
        return
    cap = table[cls]
    if cap is not None and ppt > cap:
        advice = c.data["cooling"]["advice"]["over_160" if ppt > 160 else "over_100"]
        c.fail("COOLER_CAPACITY", cooler_class=cls, max=cap, ppt=ppt, advice=advice)


# -- rules: power -------------------------------------------------------------------
# Policy (no overkill): recommended = smallest stocked size >= max(DC/0.80, maker minimum);
# HARD only below DC/0.90 or below the card maker's minimum; WARN below DC/0.80;
# DC/0.70 is an optional quiet target reported as INFO.

def compute_psu(c: Ctx):
    p = c.data["power"]
    ppt = get(c.b, "cpu.ppt_w")
    maker = get(c.b, "gpu.min_system_psu_w") if has(c.b, "gpu") else MISSING
    if has(c.b, "gpu"):
        tbp = get(c.b, "gpu.tbp_w")
        oc = get(c.b, "gpu.factory_oc") is True
    else:
        tbp, oc = 0, False
    if maker is not MISSING:
        c.psu["maker_min_system_psu_w"] = maker
    if MISSING in (ppt, tbp):
        return
    dc = ppt + tbp * (p["factory_oc_multiplier"] if oc else 1.0) + p["rest_of_system_w"]
    target = max(dc / p["recommended_load"], 0 if maker is MISSING else maker)
    c._dc_exact = dc
    c.psu.update(dc_w=round_half_up(dc), hard_minimum_w=round_half_up(dc / p["hard_min_load"]),
                 recommended_min_w=round_half_up(dc / p["recommended_load"]),
                 recommended_psu_w=round_up_to_catalog(target, c.catalog),
                 quiet_target_w=round_half_up(dc / p["quiet_load"]))


def _power_inputs_missing(c: Ctx) -> list[str]:
    miss = [] if get(c.b, "cpu.ppt_w") is not MISSING else ["cpu.ppt_w"]
    if has(c.b, "gpu") and get(c.b, "gpu.tbp_w") is MISSING:
        miss.append("gpu.tbp_w")
    if get(c.b, "psu.rated_w") is MISSING:
        miss.append("psu.rated_w")
    return miss


def r_psu_below_minimum(c: Ctx):
    miss = _power_inputs_missing(c)
    if miss:
        c.missing("PSU_BELOW_MINIMUM", miss)
        return
    rated, p = get(c.b, "psu.rated_w"), c.data["power"]
    maker = c.psu["maker_min_system_psu_w"]
    problems = []
    if rated < c._dc_exact / p["hard_min_load"]:
        problems.append(f"the {c.psu['dc_w']} W DC load would run it above 90% "
                        f"(needs at least {c.psu['hard_minimum_w']} W, DC/0.90)")
    if maker is not None and rated < maker:
        problems.append(f"the card maker's minimum system PSU is {maker} W")
    if problems:
        c.fail("PSU_BELOW_MINIMUM", rated=rated, detail="; ".join(problems) + ".")


def r_psu_below_recommended(c: Ctx):
    if _power_inputs_missing(c):
        return  # reported once by PSU_BELOW_MINIMUM
    rated, p = get(c.b, "psu.rated_w"), c.data["power"]
    maker = c.psu["maker_min_system_psu_w"]
    if rated < c._dc_exact / p["hard_min_load"] or (maker is not None and rated < maker):
        return  # the HARD finding already covers it
    if rated < c._dc_exact / p["recommended_load"]:
        c.fail("PSU_BELOW_RECOMMENDED", rated=rated, dc=c.psu["dc_w"], rec_min=c.psu["recommended_min_w"])


def r_psu_quiet_target(c: Ctx):
    if _power_inputs_missing(c):
        return
    rated, p = get(c.b, "psu.rated_w"), c.data["power"]
    if c._dc_exact / p["recommended_load"] <= rated < c._dc_exact / p["quiet_load"]:
        c.fail("PSU_QUIET_TARGET", quiet=c.psu["quiet_target_w"])


def _power_config_ok(cfg: dict, c: Ctx):
    """True if the PSU can supply CFG, False if it cannot, or a list of missing fields."""
    kind = cfg.get("type")
    if kind == "native_16pin":
        native = get(c.b, "psu.native_12v2x6")
        if native is MISSING:
            return ["psu.native_12v2x6"]
        if native is False:
            return False
        need = cfg.get("min_cable_w")
        if need is None:
            return True
        have = get(c.b, "psu.native_12v2x6_cable_w")
        return ["psu.native_12v2x6_cable_w"] if have is MISSING else have >= need
    if kind in ("adapter_8pin", "direct_8pin"):
        have = get(c.b, "psu.pcie_8pin_cables")
        return ["psu.pcie_8pin_cables"] if have is MISSING else have >= cfg.get("min_cables", 1)
    return False


def _describe_config(cfg: dict) -> str:
    if cfg.get("type") == "native_16pin":
        return f"one native 16-pin cable rated {cfg.get('min_cable_w', '?')} W+"
    label = "via the maker's adapter" if cfg.get("type") == "adapter_8pin" else "direct"
    return f"{cfg.get('min_cables', '?')} independent 8-pin cables ({label})"


def r_gpu_power_config(c: Ctx):
    if not has(c.b, "gpu"):
        return
    configs = get(c.b, "gpu.supported_power_configs")
    if configs is MISSING or not has(c.b, "psu"):
        c.missing("GPU_POWER_CONFIG", ["gpu.supported_power_configs"] if configs is MISSING else ["psu"])
        return
    results = [(cfg, _power_config_ok(cfg, c)) for cfg in configs]
    if any(r is True for _cfg, r in results):
        return
    unknown = sorted({f for _cfg, r in results if isinstance(r, list) for f in r})
    if unknown:
        c.missing("GPU_POWER_CONFIG", unknown)
        return
    offered = (f"PSU offers {get(c.b, 'psu.pcie_8pin_cables')} x 8-pin cables, native 12V-2x6: "
               f"{get(c.b, 'psu.native_12v2x6')} ({get(c.b, 'psu.native_12v2x6_cable_w')} W)")
    c.fail("GPU_POWER_CONFIG", detail=f"the card supports {'; or '.join(_describe_config(x) for x in configs)}. {offered}.")


def r_psu_atx3_preferred(c: Ctx):
    if not has(c.b, "gpu"):
        return
    v = c.need("PSU_ATX3_PREFERRED", "gpu.tbp_w")
    if not v or v[0] < c.data["power"]["atx3_preferred_gpu_w"]:
        return
    a = c.need("PSU_ATX3_PREFERRED", "psu.atx_version")
    if a and (atx_major(a[0]) or 0) < 3.0:
        c.fail("PSU_ATX3_PREFERRED", tbp=v[0], atx=a[0])


def r_psu_native_12v2x6_preferred(c: Ctx):
    if not has(c.b, "gpu"):
        return
    v = c.need("PSU_NATIVE_12V2X6_PREFERRED", "gpu.power_connector")
    if not v or normalise(v[0]).replace(" ", "") not in c.data["power"]["sixteen_pin_connectors"]:
        return
    configs = get(c.b, "gpu.supported_power_configs")
    natives = [x for x in configs if x.get("type") == "native_16pin"] if configs is not MISSING \
        else [{"type": "native_16pin"}]
    status = [_power_config_ok(x, c) for x in natives]
    if any(s is True for s in status):
        return
    unknown = sorted({f for s in status if isinstance(s, list) for f in s})
    if unknown:
        c.missing("PSU_NATIVE_12V2X6_PREFERRED", unknown)
    else:
        c.fail("PSU_NATIVE_12V2X6_PREFERRED")


def r_psu_efficiency(c: Ctx):
    v = c.need("PSU_EFFICIENCY", "psu.rated_w")
    if not v or v[0] < c.data["power"]["eta_min_rated_w"]:
        return
    e = c.need("PSU_EFFICIENCY", "psu.cybenetics_eta")
    if not e:
        return
    order = c.data["power"]["eta_order"]
    rank = order.index(e[0]) if e[0] in order else -1
    if rank < order.index(c.data["power"]["eta_min"]):
        c.fail("PSU_EFFICIENCY", eta=e[0])


def r_psu_tier(c: Ctx):
    p = c.data["power"]
    if has(c.b, "gpu"):
        g = c.need("PSU_TIER", "gpu.tbp_w")
        if not g:
            return
        needed = p["spl_min_high_power"] if g[0] >= p["atx3_preferred_gpu_w"] else p["spl_min_default"]
    else:
        needed = p["spl_min_default"]
    t = c.need("PSU_TIER", "psu.spl_tier")
    if t and p["spl_order"].index(t[0]) > p["spl_order"].index(needed):
        c.fail("PSU_TIER", tier=t[0], needed=needed)


def r_psu_cultists_ignored(c: Ctx):
    if get(c.b, "psu.cultists_tier") is not MISSING:
        c.fail("PSU_CULTISTS_IGNORED")


# -- rules: GPU, use case, budget -------------------------------------------------------

def r_vram_8gb_scope(c: Ctx):
    vram = get(c.b, "gpu.vram_gb") if has(c.b, "gpu") else MISSING
    if vram is not MISSING and vram <= 8:
        c.fail("VRAM_8GB_SCOPE", vram=vram)


def r_uc_vram_min(c: Ctx):
    need = c.use_case_profile().get("min_vram_gb")
    if not need:
        return
    if not has(c.b, "gpu"):
        c.fail("UC_VRAM_MIN", use_case=c.use_case, min=need, vram=0)
        return
    v = c.need("UC_VRAM_MIN", "gpu.vram_gb")
    if v and v[0] < need:
        c.fail("UC_VRAM_MIN", use_case=c.use_case, min=need, vram=v[0])


def r_uc_vram_preferred(c: Ctx):
    pref = c.use_case_profile().get("preferred_vram_gb")
    vram = get(c.b, "gpu.vram_gb") if has(c.b, "gpu") else MISSING
    if pref and vram is not MISSING and vram < pref:
        c.fail("UC_VRAM_PREFERRED", use_case=c.use_case, pref=pref, vram=vram)


def r_uc_ram_min(c: Ctx):
    need = c.use_case_profile().get("min_ram_gb")
    if not need:
        return
    v = c.need("UC_RAM_MIN", "ram.module_capacity_gb", "ram.modules")
    if v and v[0] * v[1] < need:
        c.fail("UC_RAM_MIN", use_case=c.use_case, min=need, total=v[0] * v[1])


def r_uc_cores_min(c: Ctx):
    profile = c.use_case_profile()
    need = profile.get("min_cores")
    if "min_cores_cpu_encoding" in profile:
        mode = get(c.b, "workload.encoding_mode")
        if mode is MISSING:
            c.missing("UC_CORES_MIN", ["workload.encoding_mode"])
            return
        need = profile["min_cores_cpu_encoding"] if mode == "cpu" else None
    if not need:
        return
    v = c.need("UC_CORES_MIN", "cpu.cores")
    if v and v[0] < need:
        c.fail("UC_CORES_MIN", use_case=c.use_case, min=need, cores=v[0])


def r_uc_dgpu_unneeded(c: Ctx):
    if c.use_case_profile().get("dgpu") is False and has(c.b, "gpu"):
        c.fail("UC_DGPU_UNNEEDED", use_case=c.use_case)


def r_uc_balance(c: Ctx):
    kind = c.use_case_profile().get("kind")
    if kind not in ("gaming", "productivity") or not has(c.b, "gpu"):
        return
    cpu_tier, gpu_tier = get(c.b, "cpu.tier"), c.gpu_tier()
    absent = (["cpu.tier"] if cpu_tier is MISSING else []) + (["gpu.tier (or a known gpu.model)"] if gpu_tier is None else [])
    if absent:
        c.missing("UC_BALANCE", absent)
        return
    if kind == "gaming" and cpu_tier == "enthusiast" and gpu_tier == "entry":
        c.fail("UC_BALANCE", detail="Gaming build pairs an enthusiast CPU with an entry GPU; move budget to the GPU.")
    if kind == "productivity" and cpu_tier == "entry" and gpu_tier in ("enthusiast", "workstation-ai"):
        c.fail("UC_BALANCE", detail="Productivity build pairs a flagship GPU with an entry CPU; balance it unless GPU compute is the workload.")


def r_uc_local_ai_vram(c: Ctx):
    if c.use_case != "local-ai" or not has(c.b, "gpu"):
        return
    vram = get(c.b, "gpu.vram_gb")
    if vram is MISSING:
        return
    fits = [e for e in c.data["vram_model_fit"] if e["vram_gb"] <= vram]
    if fits:
        c.fail("UC_LOCAL_AI_VRAM", vram=vram, fits=fits[-1]["fits"])


def r_band_total(c: Ctx):
    if not c.band or not has(c.b, "pricing"):
        return  # pricing is optional; a page's total is checked by the publish gate (PUB_BAND)
    v = c.need("BAND_TOTAL", "pricing.total_gbp_inc_vat")
    if not v:
        return
    lo, hi = c.band.get("min_gbp") or 0, c.band.get("max_gbp")
    if v[0] < lo or (hi is not None and v[0] >= hi):
        c.fail("BAND_TOTAL", total=v[0], band=c.band["id"])


def r_price_vat_dated(c: Ctx):
    if not has(c.b, "pricing"):
        return
    problems = []
    if get(c.b, "pricing.vat_inclusive") is not True:
        problems.append("vat_inclusive is not true.")
    if get(c.b, "pricing.priced_at") is MISSING:
        problems.append("priced_at is missing.")
    if problems:
        c.fail("PRICE_VAT_DATED", detail=" ".join(problems))


# -- rules: staleness guards ------------------------------------------------------------
# The rules data is dated. A model's memory lags reality by 1-2 years, so anything newer than
# the data is flagged, never filled in from memory or mapped to the nearest known part.

def _data_age(c: Ctx, rule_id: str, doc: dict, label: str, stale_default: int, block_default: int):
    as_of = parse_date(doc.get("as_of"))
    if as_of is None:
        c.missing(rule_id, [f"{label}.as_of"])
        c.block_final(rule_id, f"{label}.as_of (the data carries no date, so its age cannot be checked)")
        return
    age = (c.today - as_of).days
    stale = doc.get("stale_after_days", stale_default)
    block = doc.get("block_after_days", block_default)
    if age > stale:
        c.fail(rule_id, age=age, as_of=as_of.isoformat(), block=block)
    if age > block:
        c.block_final(rule_id, f"{label} re-verified within {block} days (as_of {as_of.isoformat()}, {age} days old)")


def r_rules_data_stale(c: Ctx):
    _data_age(c, "RULES_DATA_STALE", c.data, "rules", 120, 180)


def r_bands_data_stale(c: Ctx):
    if c.band is not None and c.bands_doc is not None:
        _data_age(c, "BANDS_DATA_STALE", c.bands_doc, "bands", 90, 120)


def _gpu_known(c: Ctx, model: str) -> bool:
    if any(model_matches(e["model"], model, c.suffixes) for e in c.data["gpu_tiers"]["models"]):
        return True
    x8 = c.plat["x8_gpus"]
    return bool(lookup_model(x8, model, c.suffixes) or lookup_model(x8["not_x8"], model, c.suffixes))


def r_not_in_rules_data(c: Ctx):
    parts: list[tuple[str, bool]] = []  # (description, blocks --final)
    raw_family = get(c.b, "cpu.family")
    if raw_family is not MISSING and canonical_family(raw_family, c.data) is None:
        parts.append((f"CPU family {raw_family!r}", True))
    seen = set()
    for path in ("cpu.socket", "board.socket"):
        v = get(c.b, path)
        if v is not MISSING and v not in c.plat["sockets"] and v not in seen:
            seen.add(v)
            parts.append((f"Socket {v!r}", True))
    chip = get(c.b, "board.chipset")
    if chip is not MISSING and normalise(chip) not in c.plat["chipsets"]:
        parts.append((f"Chipset {chip!r}", True))
    model = get(c.b, "gpu.model") if has(c.b, "gpu") else MISSING
    if model is not MISSING and not _gpu_known(c, model):
        parts.append((f"GPU {model!r}", False))
    atx = get(c.b, "psu.atx_version")
    if atx is not MISSING and (atx_major(atx) or 0) > c.data["power"]["known_atx_max"]:
        parts.append((f"PSU standard ATX {atx}", True))
    conn = get(c.b, "gpu.power_connector") if has(c.b, "gpu") else MISSING
    if conn is not MISSING and not re.fullmatch(c.data["power"]["known_connector_regex"],
                                                normalise(conn).replace(" ", "")):
        parts.append((f"GPU power connector {conn!r}", True))
    for text, blocks in parts:
        c.fail("NOT_IN_RULES_DATA", part=text)
        if blocks:
            c.block_final("NOT_IN_RULES_DATA", text)


# -- rules: OS (SteamOS / Linux) ------------------------------------------------------
# Research: docs/research/2026-09-27-pc-builder-os-research.md section 7. No OS rule runs
# unless build.os is steamos or linux.

def version_tuple_strict(v):
    """Leading dotted number of a version string ('6.16.3-arch1' -> (6, 16, 3)), or None."""
    m = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[-+~ ].*)?$", str(v))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _vlt(have, need) -> bool:
    a, b = version_tuple_strict(have), version_tuple_strict(need)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) < b + (0,) * (width - len(b))


def _game_key(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", str(name).casefold().replace(chr(0x2122), "").replace(chr(0xAE), "")).strip()


def r_os_steamos_nvidia(c: Ctx):
    if c.os_mode() != "steamos" or not has(c.b, "gpu"):
        return
    vendor = c.gpu_vendor()
    if vendor is None:
        c.missing("OS_STEAMOS_NVIDIA", ["gpu.vendor (or a gpu.model naming the brand)"])
    elif vendor == "nvidia":
        c.fail("OS_STEAMOS_NVIDIA")


def r_os_steamos_intel(c: Ctx):
    if c.os_mode() == "steamos" and c.gpu_vendor() in c.data["os"]["steamos"]["community_tier_vendors"]:
        c.fail("OS_STEAMOS_INTEL")


def r_os_steamos_dual_boot(c: Ctx):
    if c.os_mode() == "steamos" and get(c.b, "dual_boot") is True:
        c.fail("OS_STEAMOS_DUAL_BOOT")


def _protected_mark(c: Ctx, text) -> str | None:
    if not isinstance(text, str):
        return None
    for mark in c.data["os"]["steamos"]["protected_branding"]:
        if mark.casefold() in text.casefold():
            return mark
    return None


def r_os_steamos_branding(c: Ctx):
    if c.os_mode() != "steamos":
        return
    mark = _protected_mark(c, get(c.b, "branding"))
    if mark and get(c.b, "valve_licence") is not True:
        c.fail("OS_STEAMOS_BRANDING", branding=mark)


def _linux_nvidia(c: Ctx) -> bool:
    return c.os_mode() == "linux" and c.gpu_vendor() == "nvidia"


def r_os_nvidia_legacy(c: Ctx):
    arch = c.gpu_arch()
    if _linux_nvidia(c) and arch in c.data["os"]["drivers"]["nvidia_legacy_arches"]:
        c.fail("OS_NVIDIA_LEGACY", arch=arch.capitalize())


def r_os_nvidia_secure_boot(c: Ctx):
    if not _linux_nvidia(c):
        return
    v = c.need("OS_NVIDIA_SECURE_BOOT", "secure_boot")
    if v and v[0] is True:
        c.fail("OS_NVIDIA_SECURE_BOOT")


def r_os_nvidia_dx12(c: Ctx):
    if _linux_nvidia(c):
        c.fail("OS_NVIDIA_DX12")


def _wifi(c: Ctx):
    chip = get(c.b, "wifi.chip") if c.os_mode() else MISSING
    return None if chip is MISSING else normalise(chip)


def _chip_in(chip: str, table: dict):
    return next((k for k in table if re.search(r"(?<![A-Z0-9])" + re.escape(k) + r"(?![A-Z0-9])", chip)), None)


def r_os_wifi_unsupported(c: Ctx):
    chip = _wifi(c)
    key = chip and _chip_in(chip, c.data["os"]["wifi"]["unsupported"])
    if key:
        c.fail("OS_WIFI_UNSUPPORTED", detail=c.data["os"]["wifi"]["unsupported"][key] + ".")


def r_os_wifi_regression(c: Ctx):
    chip = _wifi(c)
    key = chip and _chip_in(chip, c.data["os"]["wifi"]["regression"])
    if key:
        c.fail("OS_WIFI_REGRESSION", detail=c.data["os"]["wifi"]["regression"][key] + ".")


def r_os_wifi_unverified(c: Ctx):
    chip = _wifi(c)
    w = c.data["os"]["wifi"]
    if not chip or _chip_in(chip, w["unsupported"]) or _chip_in(chip, w["regression"]):
        return
    if not any(re.search(rx, chip) for rx in w["known_good_regex"]):
        c.fail("OS_WIFI_UNVERIFIED", chip=get(c.b, "wifi.chip"))


def _minimum_applies(c: Ctx, match: dict) -> bool:
    if "gpu_arch" in match:
        return c.gpu_arch() == match["gpu_arch"]
    if "igpu_arch" in match:
        return str(get(c.b, "cpu.igpu_arch")).lower() == match["igpu_arch"]
    if "cpu_family" in match:
        fams = match["cpu_family"] if isinstance(match["cpu_family"], list) else [match["cpu_family"]]
        return c.family() in fams
    return False


def _kernel_rule(c: Ctx, rule_id: str, severity: str):
    if not c.os_mode():
        return
    for m in c.data["os"]["kernel_minimums"]:
        if m["severity"] != severity or not _minimum_applies(c, m["match"]):
            continue
        needs = [("kernel", c.kernel(), m.get("kernel")), ("mesa", get(c.b, "mesa"), m.get("mesa"))]
        absent = [f for f, have, need in needs if need and have is MISSING]
        if absent:
            c.missing(rule_id, absent)
            continue
        low = [f"{f} {have} < {need}" for f, have, need in needs
               if need and version_tuple_strict(have) is not None and _vlt(have, need)]
        if low:
            c.fail(rule_id, detail=f"{m['text']} (this build: {', '.join(low)}).")


def r_os_kernel_minimum(c: Ctx):
    _kernel_rule(c, "OS_KERNEL_MINIMUM", "HARD")


def r_os_kernel_recommended(c: Ctx):
    _kernel_rule(c, "OS_KERNEL_RECOMMENDED", "WARN")


def r_os_kernel_unverified(c: Ctx):
    if not c.os_mode():
        return
    for field, value in (("kernel", c.kernel()), ("mesa", get(c.b, "mesa"))):
        if value is not MISSING and version_tuple_strict(value) is None:
            c.fail("OS_KERNEL_UNVERIFIED", field=field, value=value)


def _games(c: Ctx):
    games = get(c.b, "buyer.games") if c.os_mode() else MISSING
    if games is MISSING:
        return []
    snap = c.awacy()
    index = {_game_key(g["name"]): g for g in snap.get("games", [])}
    return [(g, index.get(_game_key(g)), snap.get("as_of", "?")) for g in games]


def r_os_game_anticheat(c: Ctx):
    blocking = c.data["os"]["awacy"]["blocking_statuses"]
    for game, entry, as_of in _games(c):
        if entry and entry["status"] in blocking:
            c.fail("OS_GAME_ANTICHEAT", game=entry["name"], status=entry["status"], as_of=as_of)


def r_os_game_unverified(c: Ctx):
    a = c.data["os"]["awacy"]
    for game, entry, _as_of in _games(c):
        if entry is None:
            c.fail("OS_GAME_UNVERIFIED", game=game,
                   detail="not in the anti-cheat snapshot (it lists anti-cheat games only)")
        elif entry["status"] not in a["blocking_statuses"] + a["ok_statuses"]:
            c.fail("OS_GAME_UNVERIFIED", game=entry["name"], detail=f"anti-cheat status is {entry['status']}")


def r_os_buyer_wants(c: Ctx):
    wants = get(c.b, "buyer.wants") if c.os_mode() else MISSING
    if wants is MISSING:
        return
    table = c.data["os"]["windows_only_wants"]
    hits = [table[w] for w in wants if w in table]
    if hits:
        c.fail("OS_BUYER_WANTS", detail="; ".join(hits))


def _distro(c: Ctx):
    raw = get(c.b, "distro")
    if raw is MISSING:
        return MISSING, None
    key = re.sub(r"\s+", " ", str(raw).casefold()).strip()
    for slug, info in c.data["os"]["distros"].items():
        if key == slug or key in info["aliases"]:
            return raw, slug
    return raw, None


def r_os_distro_unknown(c: Ctx):
    if c.os_mode() != "linux":
        return
    raw, slug = _distro(c)
    if raw is MISSING:
        c.missing("OS_DISTRO_UNKNOWN", ["distro"])
    elif slug is None:
        c.fail("OS_DISTRO_UNKNOWN", distro=raw)


def r_os_distro_eol(c: Ctx):
    if c.os_mode() != "linux":
        return
    raw, slug = _distro(c)
    info = c.data["os"]["distros"].get(slug or "", {})
    eol = parse_date(info.get("eol"))
    if eol and (eol - c.today).days < c.data["os"]["distro_eol_warn_days"]:
        c.fail("OS_DISTRO_EOL", distro=raw, eol=eol.isoformat(), note=info.get("eol_note", ""))


def r_os_profile_mismatch(c: Ctx):
    want = c.use_case_profile().get("os")
    have = get(c.b, "os")
    have = "windows" if have is MISSING else have
    if want and have not in want:
        c.fail("OS_PROFILE_MISMATCH", use_case=c.use_case, want=" or ".join(want), os=have)


def r_awacy_data_stale(c: Ctx):
    if c.os_mode():
        _data_age(c, "AWACY_DATA_STALE", c.awacy(), "awacy", 30, 60)


RULE_IMPLS = {
    "CPU_BOARD_SOCKET": r_cpu_board_socket,
    "BOARD_CHIPSET_SOCKET": r_board_chipset_socket,
    "BOARD_MEMORY_TYPE_SOCKET": r_board_memory_type_socket,
    "RAM_TYPE_BOARD": r_ram_type_board,
    "CPU_CHIPSET_UNSUPPORTED": r_cpu_chipset_unsupported,
    "BIOS_CPU_SUPPORT": r_bios_cpu_support,
    "BIOS_MINIMUM": r_bios_minimum,
    "RAM_MODULES_SLOTS": r_ram_modules_slots,
    "AM5_FOUR_DIMMS": r_am5_four_dimms,
    "RAM_SPEED_OFFICIAL": r_ram_speed_official,
    "OC_CHIPSET_LOCKED": r_oc_chipset_locked,
    "APU_GPU_LANES": r_apu_gpu_lanes,
    "X8_LINK_GEN_LOW_VRAM": r_x8_link_gen_low_vram,
    "X8_LINK_GEN": r_x8_link_gen,
    "LANE_SHARING": r_lane_sharing,
    "DISPLAY_OUTPUT": r_display_output,
    "IGPU_DATA_CONFLICT": r_igpu_data_conflict,
    "IGPU_CLASS": r_igpu_class,
    "BOARD_CASE_FIT": r_board_case_fit,
    "PSU_CASE_FIT": r_psu_case_fit,
    "PSU_SFX_BRACKET": r_psu_sfx_bracket,
    "GPU_CASE_LENGTH": r_gpu_case_length,
    "GPU_CASE_SLOTS": r_gpu_case_slots,
    "COOLER_CASE_FIT": r_cooler_case_fit,
    "COOLER_SOCKET": r_cooler_socket,
    "COOLER_REQUIRED": r_cooler_required,
    "COOLER_CAPACITY": r_cooler_capacity,
    "PSU_BELOW_MINIMUM": r_psu_below_minimum,
    "PSU_BELOW_RECOMMENDED": r_psu_below_recommended,
    "PSU_QUIET_TARGET": r_psu_quiet_target,
    "GPU_POWER_CONFIG": r_gpu_power_config,
    "PSU_ATX3_PREFERRED": r_psu_atx3_preferred,
    "PSU_NATIVE_12V2X6_PREFERRED": r_psu_native_12v2x6_preferred,
    "PSU_EFFICIENCY": r_psu_efficiency,
    "PSU_TIER": r_psu_tier,
    "PSU_CULTISTS_IGNORED": r_psu_cultists_ignored,
    "VRAM_8GB_SCOPE": r_vram_8gb_scope,
    "UC_VRAM_MIN": r_uc_vram_min,
    "UC_VRAM_PREFERRED": r_uc_vram_preferred,
    "UC_RAM_MIN": r_uc_ram_min,
    "UC_CORES_MIN": r_uc_cores_min,
    "UC_DGPU_UNNEEDED": r_uc_dgpu_unneeded,
    "UC_BALANCE": r_uc_balance,
    "UC_LOCAL_AI_VRAM": r_uc_local_ai_vram,
    "BAND_TOTAL": r_band_total,
    "PRICE_VAT_DATED": r_price_vat_dated,
    "RULES_DATA_STALE": r_rules_data_stale,
    "BANDS_DATA_STALE": r_bands_data_stale,
    "NOT_IN_RULES_DATA": r_not_in_rules_data,
    "OS_STEAMOS_NVIDIA": r_os_steamos_nvidia,
    "OS_STEAMOS_INTEL": r_os_steamos_intel,
    "OS_STEAMOS_DUAL_BOOT": r_os_steamos_dual_boot,
    "OS_STEAMOS_BRANDING": r_os_steamos_branding,
    "OS_NVIDIA_LEGACY": r_os_nvidia_legacy,
    "OS_NVIDIA_SECURE_BOOT": r_os_nvidia_secure_boot,
    "OS_NVIDIA_DX12": r_os_nvidia_dx12,
    "OS_WIFI_UNSUPPORTED": r_os_wifi_unsupported,
    "OS_WIFI_REGRESSION": r_os_wifi_regression,
    "OS_WIFI_UNVERIFIED": r_os_wifi_unverified,
    "OS_KERNEL_MINIMUM": r_os_kernel_minimum,
    "OS_KERNEL_RECOMMENDED": r_os_kernel_recommended,
    "OS_KERNEL_UNVERIFIED": r_os_kernel_unverified,
    "OS_GAME_ANTICHEAT": r_os_game_anticheat,
    "OS_GAME_UNVERIFIED": r_os_game_unverified,
    "OS_BUYER_WANTS": r_os_buyer_wants,
    "OS_DISTRO_UNKNOWN": r_os_distro_unknown,
    "OS_DISTRO_EOL": r_os_distro_eol,
    "OS_PROFILE_MISMATCH": r_os_profile_mismatch,
    "AWACY_DATA_STALE": r_awacy_data_stale,
}


# -- public entry points --------------------------------------------------------------

def _resolve_band(band, bands: dict | None):
    """(bands document, band record) or (None, None) when no band is in use."""
    if band is None:
        return None, None
    if isinstance(band, dict):
        return bands, band
    bands = bands if bands is not None else load_json(DEFAULT_BANDS)
    rec = next((b for b in bands.get("bands", []) if b.get("id") == band), None)
    if rec is None:
        raise BadInput(f"unknown band {band!r}; known: {[b.get('id') for b in bands.get('bands', [])]}")
    return bands, rec


def _today(today) -> datetime.date:
    if today is None:
        return datetime.date.today()
    if isinstance(today, datetime.date):
        return today
    d = parse_date(today)
    if d is None:
        raise BadInput(f"--today {today!r} is not an ISO date")
    return d


def check(build: dict, use_case: str | None = None, band: str | dict | None = None,
          catalog: list[int] | None = None, rules: dict | None = None, bands: dict | None = None,
          final: bool = False, today: str | datetime.date | None = None, awacy: dict | None = None) -> dict:
    """Check BUILD and return a findings.v1 dict. Raises BadInput for unusable input.

    final=True is the publication mode: unknown fields are rejected, and a HARD
    rule that could not run makes the result incomplete (exit 3).
    """
    rules = rules if rules is not None else load_json(DEFAULT_RULES)
    if not isinstance(build, dict):
        raise BadInput("build must be a JSON object")
    errors = validate(build, load_json(BUILD_SCHEMA), strict=final)
    if errors:
        raise BadInput("; ".join(errors))
    if use_case is not None and use_case not in rules["use_cases"]:
        raise BadInput(f"unknown use case {use_case!r}; known: {sorted(rules['use_cases'])}")
    bands_doc, band_rec = _resolve_band(band, bands)
    today_d = _today(today)
    if catalog is None:
        catalog = build["psu_catalog_w"] if "psu_catalog_w" in build else rules["power"]["default_catalog_w"]
    if not catalog:
        raise BadInput("PSU catalog is empty; pass the sizes you stock or omit it to use the default")

    c = Ctx(build, rules, use_case, band_rec, list(catalog), final=final, today=today_d, bands_doc=bands_doc,
            awacy=awacy)
    compute_psu(c)
    for rule in rules["rules"]:
        RULE_IMPLS[rule["id"]](c)

    summary = {s: sum(1 for f in c.findings if f["severity"] == s) for s in ("HARD", "WARN", "INFO")}
    if summary["HARD"]:
        exit_code = EXIT_HARD
    elif final and c.incomplete:
        exit_code = EXIT_BAD_INPUT
    else:
        exit_code = EXIT_OK
    return {
        "schema": "findings.v1",
        "rules_version": rules["version"],
        "mode": "final" if final else "check",
        "exit_code": exit_code,
        "use_case": use_case,
        "band": band_rec["id"] if band_rec else None,
        "summary": summary,
        "findings": c.findings,
        "incomplete": c.incomplete,
        "recommended_psu_w": c.psu["recommended_psu_w"],
        "psu_sizing": c.psu,
    }


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def publish_gate(page: dict, today: str | None = None, max_age_days: int | None = None,
                 bands: dict | None = None, catalog: list[int] | None = None,
                 rules: dict | None = None, awacy: dict | None = None) -> dict:
    """Hold an our-pick.v1 PAGE to the publish_rules. Raises BadInput for unusable input."""
    rules = rules if rules is not None else load_json(DEFAULT_RULES)
    if not isinstance(page, dict):
        raise BadInput("page must be a JSON object")
    errors = validate(page, load_json(PAGE_SCHEMA), strict=True)
    if errors:
        raise BadInput("; ".join(errors))
    pub, prules = rules["publish"], {r["id"]: r for r in rules["publish_rules"]}
    today_d = _today(today)
    max_age = pub["max_price_age_days"] if max_age_days is None else max_age_days

    blockers: list[dict] = []

    def block(rule_id: str, **fmt):
        rule = prules[rule_id]
        try:
            msg = rule["message"].format(**fmt)
        except (KeyError, IndexError):
            msg = rule["message"]
        blockers.append({"id": rule_id, "severity": "HARD", "message": msg, "source": dict(rule["source"])})

    use_case = page.get("use_case")
    result = check(page["build"], use_case=use_case, band=page.get("band"), catalog=catalog, rules=rules,
                   bands=bands, final=True, today=today_d, awacy=awacy)
    _bands_doc, band_rec = _resolve_band(page.get("band"), bands)

    # pricing (CMA209: mandatory charges in the headline total; VAT is mandatory)
    items, charges = page.get("line_items"), page.get("mandatory_charges")
    total = page.get("headline_total_gbp_inc_vat")
    absent = [k for k, v in (("line_items", items or None), ("mandatory_charges", charges),
                             ("headline_total_gbp_inc_vat", total), ("priced_at", page.get("priced_at")))
              if v is None]
    if absent:
        block("PUB_MISSING_PRICING", detail="missing " + ", ".join(absent) + ".")
    not_db = [x.get("sku") or x.get("name") for x in (items or []) + (charges or []) if x.get("source") != "db"]
    if not_db:
        block("PUB_LINE_ITEM_SOURCE", detail=", ".join(str(x) for x in not_db) + " not sourced from the database.")
    if page.get("vat_inclusive") is not True:
        block("PUB_NOT_VAT_INCLUSIVE")
    if items and charges is not None and total is not None:
        computed = sum(x["unit_price_gbp_inc_vat"] * x["quantity"] for x in items) \
            + sum(x["amount_gbp_inc_vat"] for x in charges)
        if abs(computed - total) > pub["total_tolerance_gbp"]:
            block("PUB_TOTAL_MISMATCH", headline=f"{total:.2f}", computed=f"{computed:.2f}")
    priced = parse_date(page.get("priced_at"))
    if priced is not None:
        age = (today_d - priced).days
        if age < 0:
            block("PUB_PRICE_DATE", priced_at=page["priced_at"], detail="is in the future.")
        elif age > max_age:
            block("PUB_PRICE_DATE", priced_at=page["priced_at"],
                  detail=f"is {age} days old (limit {max_age}); reprice from the database.")
    if band_rec is not None and total is not None:
        lo, hi = band_rec.get("min_gbp") or 0, band_rec.get("max_gbp")
        if total < lo or (hi is not None and total >= hi):
            block("PUB_BAND", total=f"{total:.2f}", band=band_rec["id"])

    # required content
    for field in ("use_case", "band", "workload", "headline", "performance_class", "upgrade_path"):
        if _blank(page.get(field)):
            block("PUB_REQUIRED_FIELD", field=field)
    have = {str(x).strip().lower() for x in page.get("exclusions") or []}
    for need in pub["required_exclusions"]:
        if need not in have:
            block("PUB_EXCLUSIONS", missing=need)

    # CAP 3.7: objective claims need dated evidence held before publication
    sel = page.get("selection_criteria")
    if not sel:
        block("PUB_SELECTION_CRITERIA", detail="selection_criteria is missing.")
    elif parse_date(sel.get("as_of")) is None:
        block("PUB_SELECTION_CRITERIA", detail=f"as_of {sel.get('as_of')!r} is not an ISO date.")
    elif not [x for x in sel.get("criteria", []) if not _blank(x)]:
        block("PUB_SELECTION_CRITERIA", detail="no criteria listed.")
    claim_text = " ".join(str(page.get(k) or "") for k in ("headline", "performance_class"))
    m = re.search(pub["superlative_pattern"], claim_text, re.IGNORECASE)
    if m:
        ev = page.get("superlative_evidence")
        if not ev or parse_date(ev.get("as_of")) is None or _blank(ev.get("source")):
            block("PUB_SUPERLATIVE", word=m.group(0))

    # Linux / SteamOS: written disclosures before sale, and no unlicensed Valve marks
    build_os = page["build"].get("os")
    licensed = page["build"].get("valve_licence") is True
    if build_os in ("linux", "steamos"):
        osd = rules["os"]["disclosures"]
        disc = page.get("os_disclosures") or {}
        missing_disc = [k for k in osd["required_fields"]
                        if (k == "anti_cheat" and not [x for x in disc.get(k) or [] if not _blank(x)])
                        or (k != "anti_cheat" and _blank(disc.get(k)))]
        if build_os == "steamos" and not licensed:
            wording = rules["os"]["steamos"]["allowed_wording"]
            if wording.casefold() not in str(disc.get("os_description") or "").casefold():
                missing_disc.append(f"os_description ('{wording}')")
        if missing_disc:
            block("PUB_OS_DISCLOSURES", detail=", ".join(missing_disc))
    if not licensed:
        for text in (page.get("headline"), page.get("performance_class"),
                     (page.get("os_disclosures") or {}).get("os_description")):
            mark = next((mk for mk in rules["os"]["steamos"]["protected_branding"]
                         if isinstance(text, str) and mk.casefold() in text.casefold()), None)
            if mark:
                block("PUB_STEAMOS_BRANDING", mark=mark)
                break

    # the build itself, re-checked in final mode (never trusted from the page)
    hard = [f["id"] for f in result["findings"] if f["severity"] == "HARD"]
    if hard:
        block("PUB_CHECK_HARD", detail=", ".join(sorted(set(hard))))
    if result["incomplete"]:
        block("PUB_CHECK_INCOMPLETE", detail=", ".join(i["id"] for i in result["incomplete"]))
    incomplete_ids = {i["id"] for i in result["incomplete"]}
    unchecked = sorted({f["id"] for f in result["findings"] if "missing" in f and f["id"] not in incomplete_ids})
    if unchecked:
        block("PUB_CANNOT_CHECK", detail=", ".join(unchecked))
    disclosed = set(page.get("disclosed_warnings") or [])
    undisclosed = sorted({f["id"] for f in result["findings"]
                          if f["severity"] == "WARN" and "missing" not in f and f["id"] not in disclosed})
    if undisclosed:
        block("PUB_UNDISCLOSED_WARN", detail=", ".join(undisclosed))

    result.update(mode="publish-gate", band=band_rec["id"] if band_rec else None,
                  publish_blockers=blockers, exit_code=EXIT_HARD if blockers else EXIT_OK)
    return result


def context_gate(use_case: str | None, band: str | None, workload: str | None,
                 rules: dict | None = None, bands: dict | None = None) -> dict:
    """Ambiguity gate for callers that cannot ask: a needs-input.v1 result."""
    rules = rules if rules is not None else load_json(DEFAULT_RULES)
    bands = bands if bands is not None else load_json(DEFAULT_BANDS)
    known_uc = sorted(rules["use_cases"])
    known_bands = [b.get("id") for b in bands.get("bands", [])]
    missing, invalid = [], []
    if _blank(use_case):
        missing.append("use_case")
    elif use_case not in rules["use_cases"]:
        invalid.append(f"use_case={use_case}")
    if _blank(band):
        missing.append("band")
    elif band not in known_bands:
        invalid.append(f"band={band}")
    profile = rules["use_cases"].get(use_case or "", {})
    if _blank(workload) and profile.get("needs_workload", True):
        missing.append("workload")
    status = "needs_input" if missing or invalid else "ok"
    parts = []
    if "use_case" in missing or any(x.startswith("use_case") for x in invalid):
        parts.append("what the PC is mainly for (" + ", ".join(known_uc) + ")")
    if "workload" in missing:
        parts.append("the resolution or main workload")
    if "band" in missing or any(x.startswith("band") for x in invalid):
        parts.append("which budget band (" + ", ".join(known_bands) + ")")
    question = ("Please confirm " + "; ".join(parts) + ".") if parts else ""
    return {"schema": "needs-input.v1", "status": status, "missing": missing, "invalid": invalid,
            "question": question, "known": {"use_cases": known_uc, "bands": known_bands}}


def _parse_catalog(text: str) -> list[int]:
    try:
        sizes = [int(x) for x in text.split(",") if x.strip()]
    except ValueError as e:
        raise BadInput(f"--psu-catalog must be comma-separated watts: {e}") from e
    if not sizes or any(s <= 0 for s in sizes):
        raise BadInput("--psu-catalog must list positive watt sizes")
    return sizes


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic PC build compatibility and PSU sizing checker.")
    ap.add_argument("input", nargs="?", help="build JSON (or our-pick page with --publish-gate), or - for stdin")
    ap.add_argument("--use-case", help="use-case profile id from rules.v1.json use_cases")
    ap.add_argument("--band", help="budget band id")
    ap.add_argument("--workload", help="resolution or workload (context gate)")
    ap.add_argument("--bands", help="override budget-bands JSON (default data/budget-bands.uk.v1.json)")
    ap.add_argument("--psu-catalog", help="comma-separated PSU sizes the caller stocks, e.g. 550,650,750")
    ap.add_argument("--rules", help="override rules JSON (default data/rules.v1.json)")
    ap.add_argument("--final", action="store_true", help="publication check: strict fields, incomplete = exit 3")
    ap.add_argument("--publish-gate", action="store_true", help="input is an our-pick.v1 page")
    ap.add_argument("--context-gate", action="store_true", help="print a needs-input.v1 result")
    ap.add_argument("--today", help="date for the price-age check (default: today)")
    ap.add_argument("--max-price-age-days", type=int, help="publish gate: oldest acceptable price date")
    ap.add_argument("--awacy", help="override anti-cheat snapshot (default data/awacy-snapshot.json)")
    args = ap.parse_args(argv)

    try:
        rules = load_json(Path(args.rules)) if args.rules else None
        bands = load_json(Path(args.bands)) if args.bands else None
        awacy = load_json(Path(args.awacy)) if args.awacy else None
        if args.context_gate:
            result = context_gate(args.use_case, args.band, args.workload, rules=rules, bands=bands)
            _emit(result)
            return EXIT_OK if result["status"] == "ok" else EXIT_BAD_INPUT
        if not args.input:
            raise BadInput("an input file (or -) is required")
        if args.input == "-":
            data = loads(sys.stdin.buffer.read().decode("utf-8"))
        else:
            data = load_json(Path(args.input))
        catalog = _parse_catalog(args.psu_catalog) if args.psu_catalog is not None else None
        if args.publish_gate:
            result = publish_gate(data, today=args.today, max_age_days=args.max_price_age_days,
                                  bands=bands, catalog=catalog, rules=rules, awacy=awacy)
        else:
            result = check(data, use_case=args.use_case, band=args.band, catalog=catalog,
                           rules=rules, bands=bands, final=args.final, today=args.today, awacy=awacy)
    except (OSError, UnicodeDecodeError, ValueError, BadInput, KeyError, TypeError) as e:
        sys.stderr.write(f"pc_check: bad input: {e}\n")
        return EXIT_BAD_INPUT
    _emit(result)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
