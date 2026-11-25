# OS guide: Windows, Linux, SteamOS

Research base: `docs/research/2026-09-27-pc-builder-os-research.md` (labels V and I). Rules:
`data/rules.v1.json` `os`. OS rules run only when a build's `os` is `linux` or `steamos`; an absent `os` means
Windows and nothing changes.

## Who each OS suits

| OS | Suits | Not for |
|---|---|---|
| Windows | Everyone; anti-cheat multiplayer; PC Game Pass; Microsoft Office; vendor RGB apps | - |
| Linux | Buyers already on Linux; developers; Steam libraries that are Supported/Running on Are We Anti-Cheat Yet | Titles Denied or Broken on the anti-cheat snapshot (on 2026-09-27: Fortnite, Valorant, League of Legends, Apex Legends, Battlefield 6, CoD Warzone and Black Ops 6/7, PUBG, Rust, Roblox, GTA Online); Game Pass; Office desktop |
| SteamOS | A controller-first living-room PC on AMD graphics | NVIDIA graphics; dual boot; HDMI-CEC; the same games as Linux |

## Facts

- SteamOS 3.8 went stable on 18 Jun 2026: kernel 6.16, KDE Plasma 6.4.3 on Wayland, HDR and VRR [V].
- Valve allows SteamOS on DIY desktops with AMD or Intel graphics (Arc B-series included); NVIDIA is "in
  development with NVIDIA" and not expected in 2026 [V]. Valve's install FAQ did not render, so there is no
  first-party hardware list.
- Steam Machine (released 29 Jun 2026): Zen 4 6-core, RDNA3 28-CU GPU with 8 GB, 16 GB DDR5 [V].
- Branding: preinstalling the free image is fine. Without a Valve licence, never "Powered by SteamOS" or
  "Steam Machine"; say "SteamOS preinstalled (community-supported install)" and take legal advice before using
  any Valve mark [I].
- Proton: about 90% of ProtonDB titles launch; the Steam Deck has 8,939 Verified and 21,067 Playable titles [I].
- Anti-cheat: the Are We Anti-Cheat Yet list (1,167 games on 2026-09-27: 196 Supported, 276 Running, 640 Broken,
  53 Denied, 2 Planned) is data in `data/awacy-snapshot.json`, refreshed with `scripts/refresh_awacy.py`. It goes
  stale weekly, so the checker warns at 30 days and blocks `--final` at 60.
- Does not work: PC Game Pass installs (Xbox Cloud streaming only; Xodus is experimental); Office desktop apps;
  Windows-only RGB and fan tools (iCUE, Armoury Crate, L-Connect; OpenRGB is partial) [I]. HDR and VRR are mature on
  KDE Plasma Wayland and in gamescope. Frame generation on Linux is unverified.

## Distros

| Distro | Suits | Lifecycle [I] |
|---|---|---|
| Bazzite 44 (Fedora atomic) | beginners, console-like; NVIDIA images available | rolling, tied to Fedora |
| CachyOS (Arch) | enthusiasts; Secure Boot needs sbctl | rolling |
| Fedora 44/45 | general use | about 13 months per release; F45 due 20 Oct 2026 |
| Ubuntu 26.04 LTS (kernel 7.0) | general and office use | 5 years (to Apr 2031), 10 with Pro |
| Pop!_OS 24.04 LTS (COSMIC) | beginners with NVIDIA | follows Ubuntu 24.04 |

The Fedora and Pop!_OS end-of-life dates in the rules data are estimates from these lifecycles; any other distro
is `OS_DISTRO_UNKNOWN` ("verify").

## Disclose in writing before sale (every Linux and SteamOS page)

- The anti-cheat Denied/Broken titles, by name.
- No PC Game Pass, Xbox app or EA app without workarounds; Epic, GOG and Battle.net only via Heroic or Lutris.
- No Microsoft Office desktop apps; offer LibreOffice or Office on the web.
- Windows-only peripheral and RGB software will not work.
- On SteamOS: NVIDIA is unsupported and dual boot is not recommended.
- The support scope: the retailer covers the hardware plus a defined OS scope; the community covers the rest.
- A return path if a must-have game will not run (Consumer Rights Act "as described").

The publish gate enforces this (`PUB_OS_DISCLOSURES`) and blocks unlicensed Valve marks (`PUB_STEAMOS_BRANDING`).

## Could not verify (as of 2026-09-27)

Valve's install FAQ and hardware list; current "Powered by SteamOS" licence terms; the UK Steam Machine price;
ProtonDB headline figures; MT7927 fixes after March 2026; frame generation on Linux; the Arrow Lake kernel minimum;
EA's Javelin plans for Linux. Treat all of these as unknown until verified live.

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: awacy-anti-cheat-list
    source_url: https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json
    verified_on: 2026-09-27
    review_by: 2026-10-27
    claim: "1,167 games: 196 Supported, 276 Running, 640 Broken, 53 Denied, 2 Planned. Snapshot in data/awacy-snapshot.json (30/60-day guard)."
  - kind: external_fact
    subject: steamos-nvidia-and-desktop-policy
    source_url: https://www.club386.com/valve-steamos-diy-pc-nvidia/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "AMD or Intel graphics on DIY SteamOS desktops; NVIDIA not expected in 2026; dual boot not recommended."
  - kind: date_review
    subject: game-pass-on-linux
    review_by: 2026-12-27
  - kind: date_review
    subject: linux-distro-eols
    review_by: 2026-12-27
-->
