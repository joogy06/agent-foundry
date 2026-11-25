# Use-case profiles

Research base: `docs/research/2026-09-27-pc-builder-research.md` section D (profiles are [I] engineering
guidance). The checker's minimums are in `pc-builder/data/rules.v1.json` `use_cases`; this file explains
them. No prices anywhere: the band a build sits in is decided from live prices.

| Profile id | Build guidance | Checker minimums (RAM / VRAM / cores) | What not to pay for |
|---|---|---|---|
| `school` | APU, or a non-F Ryzen 7000/9000 or Intel CPU (the iGPU drives the display), 16 GB, 1 TB SSD | 16 GB / - / - | A discrete GPU, RGB |
| `office` | 8000G-class APU (the 780M iGPU is enough), or any Ryzen 7000/9000 non-F or non-F Intel CPU: its iGPU is enough for display and office work. 16 to 32 GB | 16 GB / - / - | A discrete GPU |
| `media` | APU or entry GPU; low noise matters | 16 GB / - / - | Gaming-class GPU |
| `esports` | 6-core + 9060 XT-class GPU (1080p high refresh) | 32 GB / 12 GB preferred (INFO, not a floor) / 6 | An 8-core-plus flagship CPU |
| `aaa-1080p` | RX 9060 XT or RTX 5060 Ti 16 GB | 32 GB / 16 GB / 6 | 8 GB cards |
| `aaa-1440p` | RX 9070 / RTX 5070 with a 9700X or 9800X3D | 32 GB / 12 GB / 8 | A workstation CPU |
| `aaa-4k` | RTX 5080 / 5090 | 32 GB / 16 GB / 8 | Anything that starves the GPU budget |
| `streaming` | GPU encoder (NVENC/QSV/AMF); 8 cores only when encoding on the CPU (`workload.encoding_mode: cpu`) | 32 GB / 12 GB / 8 if CPU encoding | - |
| `creator` | 12-16 cores, 64 GB, 16 GB+ VRAM; NVIDIA for Resolve/Blender/V-Ray/Redshift/Octane | 64 GB / 16 GB / 12 | RGB, gaming-only extras |
| `dev` | 8 cores, 32 to 64 GB, 2 TB | 32 GB / - / 8 | A high-end GPU unless the work needs one |
| `local-ai` | VRAM is the gate; NVIDIA unless inference-only and Linux-first | 32 GB [I] / 12 GB / - | CPU cores over VRAM |
| `workstation` | ECC: AM5 support is board-dependent; W880 on LGA1851 | - / - / - | Consumer gaming extras |

## Memory capacity rule of thumb (2026 pricing moves it)

- 16 GB for office and school.
- 32 GB for gaming and development.
- 64 GB+ for creator work.

## Balance rules the checker enforces (`UC_BALANCE`)

- Gaming profiles (`esports`, `aaa-*`, `streaming`): an enthusiast CPU (`cpu.tier`) with an entry GPU warns.
- Productivity profiles (`creator`, `dev`, `workstation`): an enthusiast or workstation-AI GPU with an entry CPU warns, unless GPU compute is the workload (use `local-ai` for that case).

## Budget bands (data)

Default bands are in `pc-builder/data/budget-bands.uk.v1.json` (ids `under-500`, `500-800`,
`800-1200`, `1200-2000`, `2000-plus`; each with a `typical` build). They are VAT-inclusive, for a full
tower, with no OS or monitor, and the caller overrides them. Read the file; do not copy band edges into
page copy.
