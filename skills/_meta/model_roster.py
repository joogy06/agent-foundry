"""model_roster.py - which model serves each tier of the seat registry. DATA ONLY.

#291 design section 3.1. This file holds nothing but literal assignments: no imports, no
functions, no I/O. It sits beside seat_model.py and codex_model.py, at the same trust level
as seat_model.ROLE_TABLE (installed harness code, never read from cwd, env or a project).

THE TIERS
  CLAUDE_MAIN           the protected Claude seats: code_reviewer, consultant_main, arbiter,
                        escalation
  CLAUDE_SUPPORT        consultant_support, and the avengers declared arbiters that use it
  CLAUDE_BENCHED        family tokens refused on every Claude path (seat_model.is_benched)
  CLAUDE_MAIN_ELIGIBLE  the capability floor for the protected seats
  CODEX_STD             the codex std tier: consultant_main and arbiter at every size, the
                        light/medium code_reviewer, and codex_model's std fallbacks (rev 4)
  CODEX_SUPPORT         the codex support tier: the consultant_support codex row (#302). HISTORY
                        rows before rev 3 carry no `codex_support`; every reader treats a missing
                        one as that row's `codex_std`, which is what served support then

  CODEX_TOP_ROLES       the codex seats RESERVED for the TOP tier (rev 4, the astra reserve): a
                        role name serves TOP at every size; "role@complex" serves TOP only when the
                        seat is complex (or the user asked), and CODEX_STD otherwise. Every other
                        protected codex seat is a CODEX_STD literal. seat_model checks its
                        ROLE_TABLE against this field at import (fail closed).

  AGY_FAMILY            the ONE Gemini model family agy may serve (rev 6: "argon"). seat_model
                        builds its agy family rule from it (gemini-<v>-<family>-<level>) and
                        refuses every other family - flash, pro and non-Google slugs - on every
                        agy path. HISTORY rows before rev 6 carry no `agy_family`; every reader
                        treats a missing one as "flash", which is what served then
  AGY_HARNESS_VERSION   the agy version used when no agy roster cache is readable (the harness
                        literal gemini-<version>-<family>-<level>)
  AGY_LEVEL_BY_SIZE     the agy LEVEL a sized call serves (rev 7): {size: level}. When a call
                        resolves a size (--size, --user-request or .forge/size, exactly as the
                        codex seats do), every agy role serves the level its size maps to, and
                        --user-request serves "high". With no size the role row's level stands
                        (consultant_main / arbiter high, consultant_support medium). For agy the
                        level is part of the model slug, so the size picks WHICH MODEL serves.
                        HISTORY rows before rev 7 carry no `agy_level_by_size` (unsized then)

The codex TOP tier is not here: it auto-follows the vendor roster (seat_model / codex_model).
The agy VERSION is not here either: within AGY_FAMILY it auto-follows the newest listed version.

HOW TO SWAP (the runbook, docs/model-roster-swap.md, has the full procedure)
  Move CLAUDE_MAIN, CLAUDE_SUPPORT and CLAUDE_BENCHED together in ONE edit (a codex swap moves
  CODEX_STD and/or CODEX_SUPPORT; a reserve change moves CODEX_TOP_ROLES and seat_model.ROLE_TABLE
  together; an agy family swap moves AGY_FAMILY and AGY_HARNESS_VERSION together; an agy level
  change moves AGY_LEVEL_BY_SIZE), bump REVISION, and append a HISTORY entry whose values equal
  the new live values. seat_model checks the
  invariants when it is imported and raises SeatModelError when one fails, so a bad edit
  stops every importer (fail closed) instead of serving a model the roster forbids.
  To revert, restore earlier values as a NEW revision; never rewrite or drop a HISTORY row.
"""

SCHEMA = "model-roster.v1"
REVISION = 8                    # monotonic; bumped by every swap
CLAUDE_MAIN = "opus"            # protected seats: code_reviewer, consultant_main, arbiter, escalation
CLAUDE_SUPPORT = "sonnet"       # consultant_support (and avengers declared arbiters that use it)
CLAUDE_BENCHED = frozenset({"fable"})   # refused at dispatch on every Claude path (family token)
CLAUDE_MAIN_ELIGIBLE = frozenset({"fable", "opus"})  # capability floor for the protected seats (data, not logic)
CODEX_STD = "gpt-6.1-sol"       # codex std tier (consultant_main, arbiter, light/medium code_reviewer)
CODEX_SUPPORT = "gpt-6.1-terra"  # codex support tier (consultant_support)
CODEX_TOP_ROLES = ("code_reviewer@complex", "escalation")  # the TOP reserve (rev 4)
AGY_FAMILY = "argon"            # the ONLY Gemini family agy may serve (rev 6)
AGY_HARNESS_VERSION = "4"       # the version used when no agy roster cache is readable
AGY_LEVEL_BY_SIZE = {"light": "low", "medium": "medium", "complex": "high"}  # agy level per task size (rev 7)
HISTORY = (
    {"rev": 1, "at": "2026-09-14", "claude_main": "fable", "claude_support": "opus",
     "codex_std": "gpt-5.6-sol", "benched": (), "reason": "S081 baseline"},
    {"rev": 2, "at": "2026-09-23", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-5.6-sol", "benched": ("fable",),
     "reason": "User: no Fable at any seat until a newer Fable ships; Opus 5.5 is better (#291)"},
    {"rev": 3, "at": "2026-09-24", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-6-sol", "codex_support": "gpt-5.6-terra", "benched": ("fable",),
     "reason": "User (#302 U1/U2): codex standard is the sol tier (gpt-6-sol); terra serves "
               "consultant_support for model diversity"},
    {"rev": 4, "at": "2026-09-27", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-6-sol", "codex_support": "gpt-5.6-terra", "benched": ("fable",),
     "codex_top_roles": ("code_reviewer@complex", "escalation"),
     "reason": "User (astra-reserve U1-U4): astra reserved: escalation + complex review; "
               "consultant_main/arbiter -> codex std (Sol @ xhigh). Sol is ~1/5 of astra's price and "
               "positioned level on coding and reasoning; never measured head-to-head as a reviewer, "
               "which is why complex review keeps astra"},
    {"rev": 5, "at": "2026-10-04", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-6.1-sol", "codex_support": "gpt-5.6-terra", "benched": ("fable",),
     "codex_top_roles": ("code_reviewer@complex", "escalation"),
     "reason": "User: gpt-6.1-sol is listed in codex (the vendor's latest workhorse; gpt-6-sol is now "
               "'previous generation') - replace sol 6 with 6.1 on the std tier"},
    {"rev": 6, "at": "2026-10-21", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-6.1-sol", "codex_support": "gpt-5.6-terra", "benched": ("fable",),
     "codex_top_roles": ("code_reviewer@complex", "escalation"), "agy_family": "argon",
     "reason": "User: Gemini 4 Argon replaces flash as agy's family (#365 eval: argon 63/63, flash 3.8 "
               "53/63 with tool-reaching no-shows); agy family becomes roster data (#367)"},
    {"rev": 7, "at": "2026-10-21", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-6.1-sol", "codex_support": "gpt-5.6-terra", "benched": ("fable",),
     "codex_top_roles": ("code_reviewer@complex", "escalation"), "agy_family": "argon",
     "agy_level_by_size": {"light": "low", "medium": "medium", "complex": "high"},
     "reason": "User: agy serves Argon only, the level chosen by task complexity (light -> low, "
               "medium -> medium, complex -> high; no size -> the role's level) (#367 WP-C)"},
    {"rev": 8, "at": "2026-10-29", "claude_main": "opus", "claude_support": "sonnet",
     "codex_std": "gpt-6.1-sol", "codex_support": "gpt-6.1-terra", "benched": ("fable",),
     "codex_top_roles": ("code_reviewer@complex", "escalation"), "agy_family": "argon",
     "agy_level_by_size": {"light": "low", "medium": "medium", "complex": "high"},
     "reason": "User: update every seat to the latest iteration; gpt-6.1-terra is listed (priority 3, "
               "API-supported, medium offered) and replaces gpt-5.6-terra on the codex support tier"},
)