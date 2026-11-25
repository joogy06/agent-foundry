---
name: proxmox-security-ops
description: Proxmox VE security and operations - users, realms (PAM, PVE, LDAP, Active Directory, OpenID Connect SSO), roles, ACL paths, API tokens with privilege separation, 2FA/MFA (TOTP, WebAuthn, recovery keys), the PVE firewall (datacenter, node, guest and VNet levels, security groups, IPsets, policies, nftables, lockout), ACME Let's Encrypt and custom pveproxy certificates, enterprise vs no-subscription vs test repositories, the subscription nag, updates, the pve8to9 major upgrade, metric servers (InfluxDB, Graphite), notification targets and matchers, SMART and ZFS alerts, fail2ban and hardening. Use for permission denied, locked out of 8006, or upgrade questions.
---

# Proxmox Security and Operations

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: proxmox-ve-release
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Proxmox VE 9.2 released 2026-05-21 (arm64 2026-08-05), Debian 13 Trixie, kernel 7.0; no PVE 10 announced on the roadmap."
  - kind: external_fact
    subject: pve8to9-upgrade
    source_url: https://pve.proxmox.com/wiki/Upgrade_from_8_to_9
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Needs PVE 8.4.1+, pve8to9 --full, Ceph Squid 19.2 first; bookworm->trixie with deb822 .sources; apt dist-upgrade; cgroup v1 removed; apt modernize-sources after."
  - kind: external_fact
    subject: pve-repos-and-access
    source_url: https://pve.proxmox.com/pve-docs/chapter-sysadmin.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Repos pve-enterprise, pve-no-subscription, pve-test in deb822 .sources for trixie; Ceph Tentacle 20.2 recommended (EOL 2027-11), Squid 19.2 EOL 2026-09; API tokens privsep by default; firewall disabled by default; notifications.cfg matchers/targets (sendmail, smtp, gotify, webhook)."
-->

## Overview

A Proxmox host is root on every guest it runs, so its management plane is the highest-value target in the rack. Keep the web UI and API (port 8006) and SSH off untrusted networks, give people and automation the least privilege that works, keep the repositories and upgrades clean, and make sure failures reach a human.

Labels: **[V]** checked against pve.proxmox.com docs on 2026-09-27; **[I]** inferred, so re-verify. Current: **PVE 9.2** (2026-05-21) on Debian 13 Trixie [V]; no PVE 10 on the roadmap [V].

## When to use

- Adding users, groups, realms, roles, ACLs, API tokens or TFA; "permission check failed" errors.
- Enabling or debugging the PVE firewall; locked out of `https://<host>:8006`.
- Certificates, repositories, subscription nag, `apt` updates, the 8 to 9 major upgrade.
- Wiring metrics, notifications, SMART and ZFS alerts; a hardening review.

**Not for:** bridge, VLAN and SDN design (`proxmox-networking`); cluster, corosync and HA (`proxmox-cluster-ha`); backup encryption keys and PBS permissions (`proxmox-backup`); guest OS hardening (the guest's own skill). Obey the `proxmox-admin` guardrails: firewall, repository and upgrade changes are host-wide, so show the plan and ask first on a shared host.

## Access control

Depth and command recipes: [references/access-control.md](references/access-control.md).

| Piece | Rule |
|---|---|
| Realms | `pam` (Linux users, includes `root@pam`), `pve` (built-in store), LDAP, Active Directory, OpenID Connect; configured in `/etc/pve/domains.cfg` [V]. LDAP/AD users and groups sync with `pveum realm sync` [V] |
| Users | Named personal accounts; keep `root@pam` for break-glass with TFA [I] |
| Roles | Built-ins such as `Administrator`, `PVEAdmin`, `PVEVMAdmin`, `PVEVMUser`, `PVEAuditor`; custom via `pveum role add` [V] |
| ACLs | Role + user/group/token on a path: `/`, `/vms/<id>`, `/storage/<id>`, `/pool/<name>`, `/nodes/<node>`, `/access`, `/sdn`, `/mapping` [V/I]. Propagate flag inherits downward [V] |
| Pools | Group guests and storage so one ACL covers them [V] |
| API tokens | Privilege-separated by default: effective rights = user ∩ token ACLs [V]. Set an expiry; the secret shows **once** [V]. Header `PVEAPIToken=USER@REALM!TOKENID=UUID` [V]. Console/terminal endpoints need a user, not a token [V] |
| TFA | TOTP, WebAuthn, recovery keys, Yubico OTP; realms can enforce TFA [V]. Lockout after failed attempts; `pveum user tfa unlock <user>` [V] |

```bash
pveum user token add ci@pve deploy --privsep 1 --expire <epoch>       # [V] flags; expire [V]
pveum acl modify /vms/123 --token 'ci@pve!deploy' --role PVEVMUser    # [V] pattern
pveum user permissions ci@pve                                         # [V]
```

## Firewall

Full reference (zones, rule syntax, default rules, IPSets, guest recipes, logging, nftables, recovery): [references/firewall.md](references/firewall.md).

- **Disabled by default**; enable at Datacenter (`/etc/pve/firewall/cluster.fw`, `enable: 1`) [V]. Levels: datacenter, node (`/etc/pve/nodes/<node>/host.fw`), guest (`/etc/pve/firewall/<vmid>.fw`, plus `firewall=1` on the NIC) [V/I].
- Once enabled, inbound defaults to DROP except loopback, established, and **management** hosts to 8006, 22, 5900-5999, 3128, 60000-60050, plus corosync on the cluster network [V].
- Put remote admin sources in the **`management` IPSet** before enabling; it opens GUI, SSH, VNC and SPICE for them, and already contains the cluster network [V]. The auto-detected `local_network` is also allowed, so on a public subnet narrow it in `[ALIASES]` first [V]. Keep an SSH session open while enabling [V]. Guests also need `firewall=1` on each NIC; set it in the GUI, since `qm set --net0` replaces the whole NIC definition [I].
- **Security groups** are reusable rule sets at datacenter level [V]; **IPSets** are named address groups (`+name`) [V]; `blacklist` IPSet drops everywhere [V]; `ipfilter-net<N>` stops guest IP spoofing, but list the VM's addresses before `ipfilter: 1` or its traffic drops [V].
- The nftables `proxmox-firewall` is still a **tech preview**, "not suited for production" (`nftables: 1`); FORWARD and VNet rules work only there [V].
- Check with `pve-firewall compile` / `pve-firewall status`, then `pve-firewall localnet` to see what "local network" was detected [V].

## Certificates

- ACME per cluster account: `pvenode acme account register <name> <mail>`; try Let's Encrypt **staging** first [V].
- `http-01` needs public port 80 on the node and nothing else listening there; otherwise `dns-01` with an acme.sh DNS plugin [V].
- Domains per node under Node > Certificates or `pvenode config`; renewal is automatic [V]. `pvenode acme cert order` [I].
- No ACME: upload a CA-signed cert; it lands in `/etc/pve/local/pveproxy-ssl.pem` + `.key` (key without passphrase) [V]; CLI `pvenode cert set` [I].

## Repositories, updates and upgrades

Commands and the upgrade runbook: [references/updates-and-upgrades.md](references/updates-and-upgrades.md).

| Repo | Use [V] |
|---|---|
| `pve-enterprise` (`enterprise.proxmox.com`) | Default; needs a subscription key; most tested |
| `pve-no-subscription` | Free; fine for labs and many small sites |
| `pve-test` | Pre-release; testing only |

- PVE 9 uses deb822 `.sources` files in `/etc/apt/sources.list.d/` [V]. Ceph: Tentacle 20.2 recommended, Squid 19.2 EOL 2026-09 [V].
- The "No valid subscription" dialog is a notice, not a lock. Patching `proxmoxlib.js` to hide it is overwritten by updates; buying a subscription or accepting the dialog are the clean options [I].
- Update with `apt update && apt full-upgrade` (same as `dist-upgrade`) or the GUI; plain `apt upgrade` can leave a partial, broken state [V].
- **8 to 9**: be on 8.4.1+, run `pve8to9 --full` until clean, upgrade Ceph to Squid first, move **every** active source (Debian, PVE, Ceph) from bookworm to trixie, `apt update` and `apt policy` show no bookworm left, `apt dist-upgrade` (abort if it proposes removing `proxmox-ve`), reboot, then `apt modernize-sources` [V]. Clusters: one node at a time. Also check custom roles (`VM.Monitor` is gone) and `/etc/sysctl.conf` (no longer read) [V].

## Monitoring and alerts

Detail: [references/monitoring-and-hardening.md](references/monitoring-and-hardening.md).

- **Metric servers** (Datacenter > Metric Server, `/etc/pve/status.cfg`): Graphite (UDP 2003 default) or InfluxDB (UDP, or HTTP(S) v2 API with a token) [V].
- **Notifications** (`/etc/pve/notifications.cfg`, secrets in `/etc/pve/priv/notifications.cfg`): **targets** sendmail, SMTP, Gotify, webhook; **matchers** route by `match-severity`, `match-field` (e.g. `type=vzdump`, `fencing`, `replication`, `package-updates`) and `match-calendar` [V].
- `smartd` is on by default and mails root; ZFS `zed` mails `ZED_EMAIL_ADDR` (root) [V]. Set root@pam's email so these reach a person [V].

## Anti-patterns

| Don't | Why |
|---|---|
| Expose 8006 or SSH to the internet | The management plane owns every guest; use VPN or a jump host |
| Enable the firewall without the `management` IPSet or an open SSH session | Locks you out of the node |
| Share `root@pam` or its password across people and scripts | No audit trail; one leak is total |
| API tokens with privsep off "to make it work" | The token inherits all the user's rights |
| Tokens without expiry | Abandoned automation keeps access |
| `apt upgrade` or mixed Debian/Proxmox releases | Partial upgrade, broken package state [V] |
| Enterprise repo without a subscription | `apt update` fails with 401 |
| Skip `pve8to9 --full` or upgrade all cluster nodes at once | Surprises hit the whole cluster |
| Patch the subscription nag in JS | Breaks or reverts on update |
| Notifications with no working mail target | SMART, ZFS and backup failures go unseen |
| Upgrade a major version without a tested backup of guests and host config | No way back (see `proxmox-backup`) |
