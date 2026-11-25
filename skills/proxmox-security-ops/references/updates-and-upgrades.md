# Repositories, updates and major upgrades

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve8to9-upgrade
    source_url: https://pve.proxmox.com/wiki/Upgrade_from_8_to_9
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "PVE 8.4.1+ required; pve8to9 --full; Ceph Squid 19.2 before upgrade; bookworm->trixie; pve-enterprise.sources deb822; apt dist-upgrade; cgroup v1 removed (systemd <=230 containers unsupported); Veeam broken for QEMU machine >=10.0; possible NIC renames; LVM thin repair; apt modernize-sources."
  - kind: external_fact
    subject: pve-repositories
    source_url: https://pve.proxmox.com/pve-docs/chapter-sysadmin.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "pve-enterprise at enterprise.proxmox.com/debian/pve; pve-no-subscription and pve-test at download.proxmox.com/debian/pve; suite trixie; keyring /usr/share/keyrings/proxmox-archive-keyring.gpg; apt full-upgrade, not apt upgrade."
-->

Labels: **[V]** checked against pve.proxmox.com on 2026-09-27; **[I]** inferred, so re-verify.

## Repository files (PVE 9, deb822)

```text
# /etc/apt/sources.list.d/pve-enterprise.sources   [V]
Types: deb
URIs: https://enterprise.proxmox.com/debian/pve
Suites: trixie
Components: pve-enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg

# /etc/apt/sources.list.d/proxmox.sources   (no-subscription)   [V]
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
```

- `pve-test`: same URI, `Components: pve-test` — test hosts only [V].
- Ceph repos: `ceph-tentacle` (20.2, recommended, EOL 2027-11) or `ceph-squid` (19.2, EOL 2026-09), components `enterprise` / `no-subscription` / `test` [V].
- Debian `debian.sources` needs `non-free-firmware` for CPU microcode [V].
- GUI: Node > Updates > Repositories shows and toggles these, and warns about missing or mixed repos [I].
- Without a subscription, **disable** the enterprise entries (Ceph too) or `apt update` returns 401 errors [I].

## Subscription nag

- The login dialog appears without an active key on the node. It blocks nothing [I].
- Options: a subscription (also buys enterprise repo and support), or click through. Scripts that patch `proxmoxlib.js` are overwritten by `proxmox-widget-toolkit` updates and are unsupported [I]. Do not add them to automation.

## Routine updates

```bash
apt update
apt full-upgrade        # [V] never plain 'apt upgrade' (partial/broken state)
pveversion -v           # [I] confirm versions
```

- Reboot when a new `proxmox-kernel-*` is installed; migrate or shut down guests first on a cluster [I].
- Cluster: one node at a time; keep all nodes on the same version as far as possible [I].
- Subscribe the notification matcher to `type=package-updates` so pending updates reach a human [V field].
- Unattended updates for PVE packages are risky; unattended **security** updates for Debian only are a choice some sites make [I].

## Major upgrade: 8 to 9 runbook

Pre-flight [V unless marked]:
1. Be on **PVE 8.4.1 or newer** (`apt full-upgrade` on 8 first).
2. Hyper-converged Ceph: upgrade Ceph to **Squid 19.2** first.
3. `pve8to9 --full`; fix every FAIL and review every WARN; rerun until clean.
4. Tested backups of every guest and the host config (`proxmox-backup`) [I].
5. Out-of-band console (IPMI/iKVM/physical): interface names can change [V].
6. Container check: systemd ≤ 230 guests (CentOS 7, Ubuntu 16.04) do not run, since cgroup v1 is removed [V].
7. Third-party backup tools: Veeam was broken for QEMU machine version ≥ 10.0 at the time of the guide [V]; check your vendor.
8. Custom roles and API tokens: `VM.Monitor` no longer exists; PVE 9 adds `VM.GuestAgent.*` and `VM.Replicate` [V: PVE 9 privilege list]. Re-grant what automation needs [I].
9. Move settings out of `/etc/sysctl.conf` into `/etc/sysctl.d/NN-name.conf`: PVE 9's systemd-sysctl no longer reads it (EVPN `rp_filter`, IP forwarding) [V].
10. External storage plugins must be updated for PVE 9 by their authors [V].

Upgrade [V: Upgrade_from_8_to_9 wiki, 2026-09-27, unless marked]:
```bash
# 1. Inventory EVERY active source first; a mix of bookworm and trixie breaks the upgrade
grep -rn '' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | grep -v ':#'   # [I]

# 2. Debian base: sources.list, any Debian .list, and debian.sources if it exists
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list
#    /etc/apt/sources.list.d/debian.sources: edit Suites: to trixie trixie-updates / trixie-security   [I]

# 3. PVE: write pve-enterprise.sources (or proxmox.sources, no-subscription) as in
#    "Repository files" above, then REMOVE the old pve-enterprise.list / any pve-no-subscription .list
#    so each repo is defined once

# 4. Ceph (installed or not, if a ceph.list exists): write /etc/apt/sources.list.d/ceph.sources
#    URIs: https://enterprise.proxmox.com/debian/ceph-squid (Components: enterprise) or
#          http://download.proxmox.com/debian/ceph-squid   (Components: no-subscription)
#    Suites: trixie; Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg; then remove ceph.list

# 5. Check before upgrading
apt update                                   # no errors
apt policy                                   # every entry trixie; no bookworm left, no duplicates
grep -rn bookworm /etc/apt/sources.list /etc/apt/sources.list.d/ | grep -v ':#'   # [I] expect nothing

# 6. Upgrade
apt dist-upgrade        # may take up to ~60 minutes; answer config prompts carefully
reboot
```

- Read the dist-upgrade summary before answering yes. If it says `You are attempting to remove the meta-package 'proxmox-ve'!`, answer **no**: the repositories are wrong [V]. Any other unexpected removal of `pve-*`, `proxmox-*`, `ceph*` or `qemu-server` also means stop and recheck step 1-5 [I].

Post [V/I]:
- Force-reload the web UI (browser cache) [V].
- `apt modernize-sources` converts remaining `.list` files [V].
- LVM-thin pools may need `lvconvert --repair` [V].
- LVM/LVM-thin guest volumes: run `/usr/share/pve-manager/migrations/pve-lvm-disable-autoactivation` when `pve8to9` suggests it; strongly recommended on shared LVM [V].
- Remove the `systemd-boot` meta-package when `pve8to9` says so (unless you set up systemd-boot by hand); `proxmox-boot-tool` manages booting [V].
- Ceph Squid 19.2.6 / Tentacle 20.2.4 raise HEALTH_ERR for keys using the `aes` method (CVE-2025-30156); services keep running; rotate the keys as the guide describes [V].
- Keep re-running `pve8to9` during and after the upgrade [V].
- Clusters: finish every node before using new features [V].

The PBS 3 to 4 upgrade follows the same pattern with its own checker (`pbs3to4`) [I]; read the PBS upgrade wiki before starting.
