# Linux and SteamOS builds

Research base: `docs/research/2026-09-27-pc-builder-os-research.md`. Background and who each OS suits:
`pc-builder/references/os-guide.md`.

## Profiles (rules.v1.json `use_cases`)

| Profile | Checker minimums | Build guidance |
|---|---|---|
| `linux-gaming` | 32 GB RAM, 12 GB VRAM, 6 cores; `os` linux or steamos | AMD GPU by default (RDNA4 on kernel 6.12+/Mesa 25.0+); Intel Arc on a budget; NVIDIA with caveats (DX12 slower, MOK under Secure Boot). Intel AX2xx/BE2xx or MT7925 Wi-Fi, never MT7927. Check `buyer.games` |
| `steamos-living-room` | 16 GB RAM, 12 GB VRAM preferred, 6 cores; `os` steamos | AMD graphics (Intel is a community tier, NVIDIA is unsupported); no dual boot; controller-first. Steam Machine reference: Zen 4 6-core, RDNA3 28 CU 8 GB, 16 GB DDR5 [V] |

## Page data (our-pick.v1 `os_disclosures`)

| Field | Content |
|---|---|
| `anti_cheat` | The major Denied/Broken titles by name, from the current snapshot (e.g. Fortnite, Valorant, Apex Legends, Battlefield 6, CoD Warzone, PUBG, Rust, Roblox, GTA Online on 2026-09-27) |
| `game_pass_office` | No PC Game Pass, Xbox app or EA app without workarounds; no Office desktop apps (LibreOffice or Office on the web) |
| `rgb_software` | Windows-only RGB and fan software will not work; OpenRGB is partial |
| `support_scope` | Hardware plus a defined OS scope; the community covers the rest |
| `return_path` | What happens if a must-have game will not run (Consumer Rights Act "as described") |
| `os_description` (SteamOS) | "SteamOS preinstalled (community-supported install)", unless Valve has licensed its marks (`build.valve_licence`) |

The gate blocks a Linux/SteamOS page missing any field (`PUB_OS_DISCLOSURES`), and any "Powered by SteamOS" or
"Steam Machine" wording in the headline, performance class or OS description without a licence
(`PUB_STEAMOS_BRANDING`). The build itself is re-checked in `--final`, so a HARD OS finding (NVIDIA on SteamOS,
MT7927, a kernel below the minimum, a Denied must-have game) also blocks.

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: awacy-anti-cheat-list
    source_url: https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json
    verified_on: 2026-09-27
    review_by: 2026-10-27
    claim: "Example Denied/Broken titles from the 2026-09-27 snapshot; always take the list from data/awacy-snapshot.json."
-->
