# Refresh procedure

The pc-* skills are only as current as `data/rules.v1.json` and `data/budget-bands.uk.v1.json`. Both
carry `as_of`, `stale_after_days` and `block_after_days`, and `pc_check.py` enforces them:

| Data | WARN after | `--final` / `--publish-gate` blocked after |
|---|---|---|
| Rules (`RULES_DATA_STALE`) | 120 days | 180 days |
| Budget bands (`BANDS_DATA_STALE`) | 90 days | 120 days |
| Anti-cheat snapshot (`AWACY_DATA_STALE`, Linux/SteamOS builds only) | 30 days | 60 days |

A part the tables do not know is `NOT_IN_RULES_DATA`. Socket, chipset, CPU family and PSU/connector
standards block `--final`; an unknown GPU model is a WARN to verify, and is never mapped to a known card.

**Never refresh from memory.** A model's training data lags reality by 1-2 years, which is exactly the
gap this procedure exists to close. Every new fact comes from a live source, found with the
`web-research` skill (or an equivalent live search), and is recorded with its V/S/I label and URL.

## Quarterly checklist

Run it every quarter, and whenever `RULES_DATA_STALE` or a `NOT_IN_RULES_DATA` finding appears. These
items come from the research doc's "Re-verify quarterly" list (`docs/research/2026-09-27-pc-builder-research.md`):

- [ ] ROCm versions and Windows support.
- [ ] Ollama on RDNA4 on Windows.
- [ ] DLSS/FSR/XeSS frame generation.
- [ ] RTX 50 Super status.
- [ ] Intel Arc B770 status.
- [ ] The Zen 7 socket (AM5 upgrade promise).
- [ ] LGA1954 lifespan and launch.
- [ ] The SPL PSU tier list's update date.
- [ ] AGESA minimums for new Ryzen SKUs.
- [ ] DDR5/GDDR7 pricing context.
- [ ] TechPowerUp relative-performance figures.
- [ ] NVIDIA power-connector guidance and minimum system PSU figures.
- [ ] CMA price-transparency guidance (CMA209).
- [ ] UK budget bands against live prices (every 90 days, faster than the rest).
- [ ] New CPU, GPU, chipset or socket launches since `as_of`, and new PSU or connector standards (a
  successor to ATX 3.1 or 12V-2x6).

OS items (from `docs/research/2026-09-27-pc-builder-os-research.md`, "Re-verify quarterly"):

- [ ] The anti-cheat list: run `python3 scripts/refresh_awacy.py` (monthly at least; the snapshot warns at 30 days).
  It downloads Are We Anti-Cheat Yet's `games.json`, keeps name and status, stamps `as_of`, and refuses a truncated
  download. Never copy game names into `rules.v1.json`.
- [ ] SteamOS NVIDIA status and the desktop policy (`os.steamos`).
- [ ] The NVIDIA Linux driver branch and DX12 performance (`os.drivers`).
- [ ] Kernel and Mesa minimums for new launches (Zen 6, the RDNA successor, Nova Lake) (`os.kernel_minimums`).
- [ ] rtw89 and MT7927 fixes (`os.wifi`).
- [ ] Steam Survey Linux share.
- [ ] Distro end-of-life dates (`os.distros`; the Fedora and Pop!_OS dates are estimates).
- [ ] Game Pass and Xodus on Linux.
- [ ] Anti-cheat changes in new CoD and Battlefield titles.

## Adding a new generation (e.g. a new CPU family, GPU series, chipset or socket)

1. **Research.** Use the `web-research` skill for the vendor pages (specs, sockets, chipsets, memory,
   iGPU, box cooler, TBP, maker PSU minimum and power arrangements) and independent measurements. Label
   each fact V (read on the source), S (search excerpt) or I (inference), with its URL. Add the facts to
   the research doc (a dated addendum), not straight into code.
2. **Rules data (next version).** Edit `data/rules.v1.json` and bump `version`: a new minor version for
   added rows, and a new major version (and a `rules.v2.json` if the shape changes) for a changed rule.
   Add the platform rows (`sockets`, `chipsets`, `cpu_families` with aliases, `cpu_family_from_model`,
   `igpu_rules`, `x8_gpus`, `gpu_tiers`, `bios_minimums`, `memory_official`) with a `source` on each new
   rule. Keep the schema in step (`schemas/build.v1.json` `x-canonical-values`).
3. **Tests first.** Add a failing test per new fact in `tests/` (e.g. the new family resolves, the new
   F-SKU has no iGPU, the new chipset is no longer `NOT_IN_RULES_DATA`), then make it pass. Run
   `python3 -m unittest discover -s tests`.
4. **Bump `as_of`** (and `review_by`) in the data files you re-verified. Only a file you actually
   re-verified gets a new date.
5. **Skill text and anchors.** Update the tables in the child skills' `references/`, and the FRESHNESS
   anchors (`verified_on`, `review_by`). Validate them with `python3 ~/.claude/skills/_meta/freshness.py lint <file>`.
6. **Install** and confirm the installed copy matches the repo.

A part that is not yet researched stays `NOT_IN_RULES_DATA`. Recommend it only after this loop, never
by analogy with its predecessor.

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: date_review
    subject: pc-builder-quarterly-refresh
    review_by: 2026-12-27
-->
