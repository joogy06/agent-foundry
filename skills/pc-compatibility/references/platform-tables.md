# Platform tables

Human-readable view of `pc-builder/data/rules.v1.json` `platforms`. The JSON is the source the checker
reads; if the two disagree, the JSON wins and this file needs an update. Labels: V read on the source,
S search excerpt, I inference. Research base: `docs/research/2026-09-27-pc-builder-research.md`.

## Sockets

| Socket | Memory | Chipsets | Upgrade horizon | Source |
|---|---|---|---|---|
| AM4 | DDR4 only | A320, B350, X370, B450, X470, A520, B550, X570 | End of line | [V] https://www.amd.com/en/products/processors/chipsets/am4.html |
| AM5 | DDR5 only | A620, B650, B650E, X670, X670E, B840, B850, X870, X870E | Support through 2029; promise upgrades only to Zen 6 (Olympic Ridge, expected 2027). Zen 7 socket disputed | [V] https://en.wikipedia.org/wiki/Socket_AM5 |
| LGA1700 | DDR4 **or** DDR5, per board | H610, B660, H670, Q670, Z690, W680, B760, H770, Z790 | End of line (12th-14th gen) | [V] https://en.wikipedia.org/wiki/LGA_1700 |
| LGA1851 | DDR5 only | H810, B860, Q870, Z890, W880 | No CPU upgrade path; LGA1954 next (Q1 2027) | [V] https://en.wikipedia.org/wiki/LGA_1851 |

Chipset lists for LGA1700 and LGA1851 come from the Wikipedia socket pages [V]: Z690 and Z890 support CPU overclocking with 4 DIMMs; B860 overclocks memory only.

## AM4 chipsets

| Chipset | GPU slot | CPU M.2 | Chipset lanes | Notes |
|---|---|---|---|---|
| X570 | 4.0 | 4.0 | 4.0 | No Ryzen 1000/2000 |
| B550 | 4.0 | 4.0 | 3.0 | No Ryzen 1000/2000 |
| A520 | 3.0 | 3.0 | 3.0 | No Ryzen 1000/2000 |
| 300/400-series | 3.0 | 3.0 | 3.0 | Ryzen 5000 on X370/B350/A320 needs a Selective Beta BIOS |

Source: [V] https://www.amd.com/en/products/processors/chipsets/am4.html

## AM5 chipsets

| Chipset | GPU slot | CPU M.2 | CPU overclocking |
|---|---|---|---|
| X870E | 5.0 x16 or x8+x8 | 5.0 x4 | yes |
| X870 | 5.0 | 5.0 x4 | yes |
| B850 | 4.0 (5.0 optional per board) | 5.0 x4 | yes |
| B840 | 4.0 x16 | 4.0 x4 | **no** |
| X670E | 5.0 | 5.0 | yes |
| X670 | 4.0 | 5.0 | yes |
| A620 | 4.0 x16 | 4.0 x4 | **no** |
| B650E | 5.0 [I] | 5.0 [I] | not stated |
| B650 | not stated | 5.0 optional [I] | not stated |

Source: [V] https://www.amd.com/en/products/processors/chipsets/am5.html (B650/B650E have dropped off the page).

## Integrated graphics (iGPU)

The DB `cpu.igpu` field wins; these rules (`platforms.igpu_rules`, first match) fill a gap and flag a contradiction.

| CPUs | iGPU | Class | Source |
|---|---|---|---|
| Ryzen 7000/9000 desktop, non-F (9600X, 7600, 9800X3D) | yes, RDNA 2, 2 CUs | display and office, not gaming [I] | [V] AMD 9600X/7600 pages; Wikipedia Ryzen list |
| Ryzen 7000/9000 F SKUs (7500F) | no: "Discrete Graphics Card Required" | - | [V] AMD 7500F page |
| Ryzen 8000G (8700G 780M, 8600G 760M) | yes | light gaming [I] | [V] AMD 8700G/8600G pages |
| Ryzen 5000 without G (5600X) | no: "Discrete Graphics Card Required" | - | [V] AMD 5600X page |
| Ryzen 5000G (5600G) | yes, Vega | display and office [I] | [S] AMD; [V] Wikipedia Ryzen list |
| Intel F and KF SKUs (14600KF, 265KF) | no: "F - No integrated graphics" | - | [V] Wikipedia Raptor Lake suffix legend, Arrow Lake table |
| Other LGA1700/LGA1851 desktop SKUs (14900K UHD 770, 285K) | yes | display and office [I] | [V] Intel 14900K spec (Wayback); Arrow Lake table |

## Chipsets that cannot overclock a K/X CPU

A620, B840, H610, H810, B660, B760, H670, H770, B860.

## Intel platform notes

- i9-14900K: DDR5-5600 or DDR4-3200; 20 lanes (1x16+4 or 2x8+4). [V] https://www.intel.com/content/www/us/en/products/sku/236773/intel-core-i9-processor-14900k-36m-cache-up-to-6-00-ghz/specifications.html
- H610: 2 DIMMs, no CPU M.2. Raptor Lake on 600-series: "a BIOS update may be required". [V] https://en.wikipedia.org/wiki/LGA_1700
- Z790: a Gen5 M.2 can take 4 lanes and drop the GPU to x8 [I].
- LGA1851: 20 PCIe 5.0 lanes (x16 GPU + x4 M.2) plus 4 PCIe 4.0 lanes. H810: no Gen5 M.2, 2 DIMMs. 285K DDR5-6400; 200S Plus DDR5-7200 and needs a BIOS update on existing 800-series boards [I]. [V] https://en.wikipedia.org/wiki/LGA_1851

## BIOS / AGESA minimums

| CPU | Board | Minimum | Label |
|---|---|---|---|
| Ryzen 5000 | X370, B350, A320 | Selective Beta BIOS | V |
| Ryzen 9000 | 600-series AM5 | AGESA 1.2.0.0 | I https://videocardz.com/newz/msi-releases-agesa-1-2-0-0-bios-for-amd-x670-b650-a620-improvements-for-ryzen-9000-cpus-and-geforce-rtx-40-gpus |
| 9850X3D | AM5 | AGESA 1.2.8.0 | I https://www.gigabyte.com/us/Press/News/2363 |
| 9950X3D2 (Apr 2026) | AM5 | AGESA 1.3.0.0a | I https://www.gigabyte.com/press/news/2374 |
| Core 13th/14th gen | 600-series | BIOS update may be required | V |
| Core Ultra 200S Plus | existing 800-series | BIOS update | I |

## Official memory speeds

| CPU | 2 DIMMs | 4 DIMMs | Practical target |
|---|---|---|---|
| Ryzen 9000 (9800X3D page) | 5600 | 3600 | DDR5-6000 CL30 at 1:1; often 6200-6400 at 1:1 [I] |
| Ryzen 8000G | 5200 | 3600 | 6000-6400 (the iGPU gains from bandwidth) |
| Arrow Lake (200S) | 6400 | - | CUDIMM makes 8000+ practical |
| 200S Plus | 7200 [I] | - | - |
| Raptor Lake | 5600 | - | - |

Sources: [V] https://www.amd.com/en/products/processors/desktops/ryzen/9000-series/amd-ryzen-7-9800x3d.html, [I] https://www.igorslab.de/en/amd-ryzen-9000-x3d-ram-reference-guide-8200-21-vs-6400-11-2r-vs-1r-optimized-vs-expo-vs-jedec-in-synthetics-and-gaming/2/

## APU GPU lanes

| APU | Usable lanes | GPU link | Source |
|---|---|---|---|
| 8700G, 8600G | 16 (8700G) | x8 at 4.0 | [V] https://www.amd.com/en/products/processors/desktops/ryzen/8000-series/amd-ryzen-7-8700g.html, [I] https://www.techspot.com/review/2796-amd-ryzen-8700g/ |
| 8500G, 8300G | 10 (8500G) | **x4** at 4.0 | as above |

## GPU PCIe links

| Card | Link |
|---|---|
| RTX 5050, 5060, 5060 Ti | 5.0 x8 [V] https://en.wikipedia.org/wiki/GeForce_RTX_50_series |
| RTX 4060, 4060 Ti | 4.0 x8 |
| RX 7600 | 4.0 x8 |
| Arc B570, B580 | 4.0 x8 |
| RX 9060 XT | 5.0 **x16** [V] https://www.amd.com/en/products/graphics/desktops/radeon/9000-series/amd-radeon-rx-9060xt.html |

Measured loss (8 GB RTX 5060 Ti):
- ComputerBase, 27 games at 1440p: 5.0 = 59.4 fps vs 4.0 = 55.8 fps (-6%); 1% lows -7%; eight titles -9% or worse. [V] https://www.tomshardware.com/pc-components/gpus/nvidia-rtx-5060-ti-8gb-loses-up-to-10-percent-performance-when-using-pcie-4-0
- PCIe 3.0 once VRAM overflows: Veilguard 27 fps with 9 fps 1% lows; 4.0 gave +22% average and +111% on lows. [V] https://www.techspot.com/review/3004-nvidia-rtx-5060-ti-pcie-benchmark/
- Little effect when VRAM is not exceeded.

## Physical sizes

| Item | Size |
|---|---|
| ATX board | 305 x 244 mm |
| mATX board | 244 x 244 mm |
| ITX board | 170 x 170 mm |
| E-ATX board | 305 x 330 mm |
| ATX PSU | 150 x 86 x 140 mm |
| SFX PSU | 125 x 63.5 x 100 mm |
| SFX-L PSU | 125 x 63.5 x 130 mm |

An SFX unit fits an ATX case with a bracket; an ATX unit does not fit an SFX-only case. LGA1851 coolers use the LGA1700 mount holes. GPU length/thickness and cooler height/radiator checks compare the caller's product dimensions with the case's published clearances [I].

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: cpu-igpu-presence-rules
    source_url: https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-5-7500f.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "iGPU table: Ryzen 7000/9000 non-F yes (2-CU RDNA 2); F SKUs no; 8000G yes (780M/760M); Ryzen 5000 non-G no, 5000G yes; Intel F/KF no, other LGA1700/LGA1851 desktop yes. New SKUs may break the suffix rules."
  - kind: external_fact
    subject: agesa-minimums
    source_url: https://www.gigabyte.com/press/news/2374
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "AGESA minimums as tabulated (Ryzen 9000 on 600-series 1.2.0.0; 9850X3D 1.2.8.0; 9950X3D2 1.3.0.0a)."
  - kind: external_fact
    subject: zen7-socket
    source_url: https://www.techpowerup.com/351994/amd-confirms-am5-compatibility-with-olympic-ridge-desktop-zen-6
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Zen 6 confirmed for AM5; Zen 7 socket disputed."
  - kind: external_fact
    subject: lga1954-lifespan
    source_url: https://en.wikipedia.org/wiki/LGA_1954
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "LGA1954 expected Q1 2027."
-->
