# Linux platform notes (kernel, Mesa, Wi-Fi, Secure Boot)

Research base: `docs/research/2026-09-27-pc-builder-os-research.md` sections 3 and 5. Rules:
`pc-builder/data/rules.v1.json` `os.kernel_minimums` and `os.wifi`. These rules run only when the build's `os` is
`linux` or `steamos`.

## Kernel and Mesa minimums

| Platform | Minimum | Severity | Label |
|---|---|---|---|
| AMD RDNA4 (RX 9050/9060/9070) | kernel 6.12 (6.13+ recommended), Mesa 25.0 | HARD | I |
| Intel Arc B-series (B570/B580) | kernel 6.12 (Xe driver) | HARD | I |
| Intel Xe3 (Panther Lake) graphics (`cpu.igpu_arch: xe3`) | kernel 6.17 | HARD | I |
| Ryzen 9000 | kernel 6.10 recommended (RAPL) | WARN | I |
| Arrow Lake iGPU | kernel 6.14 (weak source) | WARN | I |

SteamOS 3.8 ships kernel 6.16 [V], and the checker uses it when a SteamOS build gives no kernel. Ubuntu 26.04 LTS
ships 7.0 [I]; Mesa 26.2 was released 5 Aug 2026 [I]. A kernel or Mesa value that does not parse as a version is
`OS_KERNEL_UNVERIFIED` ("verify"), never a guess. RDNA4 is recognised from the model (RX 9xxx) and Arc B-series
from "Arc B…" when `gpu.arch` is absent.

## Wi-Fi and Bluetooth

| Chip | Status | Rule |
|---|---|---|
| MediaTek MT7927 (Filogic 380; on 15+ flagship boards including the ASUS X870E Hero) | No working Linux Bluetooth; Wi-Fi partial; patches not merged as of 19 Mar 2026 [V] | HARD: fit an Intel card |
| Realtek RTL8922AE (rtw89) | Regression on kernels 6.18+, no fix yet [V] | WARN |
| MediaTek MT7925 | Supported upstream [I] | known good |
| Intel AX2xx, BE2xx | The safe choice [I] | known good |
| Anything else | Unknown | WARN "verify" |

## Secure Boot and vendor software

- NVIDIA drivers need MOK enrolment at first boot under Secure Boot [I]; AMD's in-tree driver needs no signing step.
- RGB and fan tools (iCUE, Armoury Crate, L-Connect) are Windows-only; OpenRGB is partial [I].

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: rtw89-mt7927-fixes
    source_url: https://ratatoskr.run/linux-wireless/2026/06/17168565/t
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RTL8922AE regression on 6.18+ unfixed; MT7927 patches unmerged as of 19 Mar 2026."
  - kind: date_review
    subject: linux-kernel-mesa-minimums
    review_by: 2026-12-27
-->
