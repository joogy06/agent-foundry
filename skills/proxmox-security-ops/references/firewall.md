# PVE firewall reference

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-firewall
    source_url: https://pve.proxmox.com/pve-docs/chapter-pve-firewall.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Firewall disabled by default; zones host/VM/VNet, directions IN/OUT/FORWARD; cluster.fw, host.fw, <VMID>.fw, /etc/pve/sdn/firewall/<vnet>.fw; management/blacklist/ipfilter-net* IPSets; local_network alias; default allows from management to 8006/22/5900-5999/3128/60000-60050 plus corosync 5405-5412; nftables proxmox-firewall tech preview, not suited for production, needed for FORWARD and VNet rules; guests restart after switching."
-->

Labels: **[V]** checked against the PVE firewall chapter on 2026-09-27; **[I]** inferred or common practice, so re-verify. Bridge, VLAN and SDN **layout** is `proxmox-networking`; all **filtering** is here.

## Model

- Distributed: config lives in pmxcfs, and `pve-firewall` on each node renders iptables rules locally. IPv4 and IPv6 are filtered by the same rules [V].
- **Zones** [V]: *Host* (datacenter and node rules; node rules take precedence), *VM/CT* (IN and OUT only), *VNet* (FORWARD only, nftables backend only).
- **Directions** [V]: `IN`, `OUT`, `FORWARD`. FORWARD rules are ignored by the stock iptables `pve-firewall`.
- Services per node: `pve-firewall` (rules) and `pvefw-logger` (NFLOG) [V].

## Files [V]

| File | Holds |
|---|---|
| `/etc/pve/firewall/cluster.fw` | `[OPTIONS]` (global `enable`, `policy_in`, `policy_out`, `ebtables`, log rate), `[RULES]`, `[group <name>]` security groups, `[IPSET <name>]`, `[ALIASES]` |
| `/etc/pve/nodes/<node>/host.fw` | Node options (`enable`, log levels, `nf_conntrack_*`, `tcpflags`, `protection_synflood`, `nftables`, `ndp`) and node rules |
| `/etc/pve/firewall/<vmid>.fw` | Guest options (`enable`, `policy_in/out`, `dhcp`, `ndp`, `radv`, `macfilter` default 1, `ipfilter`, log levels), rules, IPSets, aliases |
| `/etc/pve/sdn/firewall/<vnet>.fw` | VNet `enable`, `policy_forward`, FORWARD rules (nftables only) |

Guests need **three** switches: datacenter `enable: 1`, guest `.fw` `enable: 1`, and `firewall=1` on each NIC [V: per-NIC flag required].

Set the NIC flag with the GUI (VM > Hardware > Network Device > Firewall) or by re-sending the **whole** existing `net0` string: `qm set --net0` replaces the entire definition, and an omitted MAC, bridge, `tag` or rate is lost or regenerated [I, qm netN property string, 2026-09-27]:

```bash
qm config <vmid> | grep '^net0'      # e.g. net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,tag=20
qm set <vmid> --net0 'virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,tag=20,firewall=1'   # same string + firewall=1
```
Containers: same rule for `pct set <ctid> --net0` (it also carries `name`, `ip`, `gw`) [I].

## Rule syntax [V]

```text
[RULES]
DIRECTION ACTION [OPTIONS]
DIRECTION MACRO(ACTION) [OPTIONS]
|DIRECTION ACTION [OPTIONS]            # leading | = disabled
GROUP <security-group>                 # guest/host includes a group
```

- Actions: `ACCEPT`, `DROP`, `REJECT` [V].
- Options: `-source`/`-dest` (IP, range `a-b`, comma list, `+ipset`, alias), `-p`/`-proto`, `-dport`/`-sport` (names, numbers, `80:85`, lists), `-i`/`-iface` (`net0` style for guests), `-icmp-type`, `-log <level>` [V].
- Do not mix IPv4 and IPv6 in one address list [V].
- Macros (`SSH`, `HTTP`, `HTTPS`, `DNS`, `Ping`, `Ceph`, ...): list with `pvesh get /cluster/firewall/macros` [I].
- Rules are evaluated top to bottom; first match wins; then the policy applies [I].

## Default host rules (policy DROP or REJECT) [V]

Still allowed for every node: loopback, established connections, IGMP, and **from `management`**: TCP 8006 (GUI/API), 5900-5999 (VNC console), 3128 (SPICE), 22 (SSH), 60000-60050 (migration); corosync UDP 5405-5412 and multicast on the cluster network.
Dropped but not logged: invalid TCP state, non-corosync broadcast/multicast, Windows/NetBIOS noise (135, 137-139, 445), UPnP 1900, port 43, UDP from source port 53 [V].

Ports Proxmox uses [V]: 8006 TCP, 5900-5999 TCP, 3128 TCP, 22 TCP, 111 UDP (rpcbind), 25 TCP outgoing (mail), 5405-5412 UDP (corosync), 60000-60050 TCP (migration). Add Ceph (`Ceph` macro) and PBS (8007 outbound) as needed [I].

## Standard IPSets and aliases [V]

| Name | Effect |
|---|---|
| `management` (datacenter) | Sources allowed to reach GUI, SSH, VNC, SPICE on hosts. The **cluster network is added automatically**, which is why local-LAN admins keep access and remote admins get locked out |
| `blacklist` (datacenter) | Dropped by every host and guest firewall |
| `ipfilter-net<N>` (guest) | Outbound from that NIC must come from these IPs (anti-spoofing); `ipfilter: 1` creates them implicitly with the MAC-derived link-local address and, for CTs, the configured IPs |
| `local_network` alias | Auto-detected host network (`pve-firewall localnet`); override in `[ALIASES]` on a single public host |
| `cluster_network` alias | Corosync network; used for the automatic cluster rules |

## Enable without locking yourself out

1. Keep an SSH session open on every node [V]; know your out-of-band console path [I].
2. `pve-firewall localnet` — confirm the detected local network [V]. Proxmox allows cluster access (API, SSH, corosync) from this `local_network` automatically, so the `management` IPSet does **not** fence it off [V].
3. **Host on a public or shared subnet**: the detected network may include other people's addresses. Narrow it before enabling, as the docs advise for a single public host [V, pve-firewall docs, 2026-09-27]:
   ```ini
   # /etc/pve/firewall/cluster.fw
   [ALIASES]
   local_network 203.0.113.10   # this host's own IP (clusters: the cluster network only [I])
   ```
   If the firewall is **already** on, add your own admin address to `management` (step 4) first, or the narrowed alias can cut your session [I]. Rerun `pve-firewall localnet` and check it now reports the narrowed value [I].
4. Add remote admin/VPN ranges to `[IPSET management]` [V].
5. Datacenter `enable: 1` with `policy_in: DROP`, `policy_out: ACCEPT` [I: typical].
6. `pve-firewall compile` (shows errors), `pve-firewall status` [V].
7. From a **new** session, open the GUI and SSH from an allowed source, and check that an address outside `management` (and outside the narrowed `local_network`) is refused. Only then close the old one [I].
8. Recovery from the console: `pve-firewall stop` [V], or `enable: 0` in `cluster.fw` [I]. On a cluster, the stopped node re-enables at the next service start, so fix the rule in `cluster.fw` [I].

## Guest recipes

```ini
# /etc/pve/firewall/cluster.fw
[group web]
IN HTTP(ACCEPT)
IN HTTPS(ACCEPT)

[IPSET admins]
192.0.2.0/24

# /etc/pve/firewall/<vmid>.fw
[OPTIONS]
enable: 1
policy_in: DROP

[RULES]
GROUP web
IN SSH(ACCEPT) -source +admins
IN Ping(ACCEPT)
```

- **Anti-spoofing (`ipfilter`)** is a separate step, not part of this recipe: once `ipfilter: 1` is set (or an `ipfilter-net0` IPSet exists), outbound traffic from a source IP not in the set is dropped. For a **VM** the implicit set holds only the MAC-derived IPv6 link-local address, so its normal IPv4/IPv6 traffic stops [V]. Define the addresses first, then enable:
  ```ini
  [IPSET ipfilter-net0]
  192.0.2.10
  2001:db8::10
  ```
  Containers also get their configured IPs implicitly [V]. DHCP VMs need a reserved address [I].
- IPv6 guests: keep `ndp: 1` (default); allow `radv: 1` only on guests that are routers [V].
- DHCP clients behind `policy_in: DROP`: set `dhcp: 1` on the guest [V].
- Inter-guest traffic on the same bridge passes through both guests' firewalls; filter at the destination guest [I].
- FTP needs the `ip_conntrack_ftp` / `nf_conntrack_ftp` helper module (`nf_conntrack_helpers` host option) [V].
- Suricata IPS: `ips: 1` and `ips_queues` in the guest `.fw` after installing suricata and `nfnetlink_queue` [V].

## Host hardening options [V]

`tcpflags: 1` (drop illegal flag combos), `protection_synflood: 1` (+ `_rate`, `_burst`), `nosmurfs`, `nf_conntrack_max`, `nf_conntrack_tcp_timeout_established`, `log_level_in/out`, `smurf_log_level`, `tcp_flags_log_level`.

## Logging

- Off by default; set `log_level_in`/`log_level_out` in host or guest options, then Firewall > Log [V].
- Per-rule logging: append `-log <level>` [V].
- Log line: `VMID LOGID CHAIN TIMESTAMP POLICY: PACKET_DETAILS`; VMID 0 is the host [V].
- Active ruleset: `iptables-save` (iptables backend) or `nft list ruleset` (nftables) [V/I].

## nftables backend (`proxmox-firewall`)

- **Tech preview; the docs say not suited for production** [V].
- `apt install proxmox-firewall`, then `nftables: 1` in `host.fw` (Host > Firewall > Options); **restart all running guests** after switching either way [V]. Check `systemctl status proxmox-firewall` [V].
- Needed for FORWARD rules (host as router/NAT) and SDN VNet firewalls [V].
- Differences [V]: no `fwbrX` bridges for Linux bridges; guest REJECT becomes DROP; NDP/RA/DHCP options always create rules; guest rules are evaluated even for tracked connections.

## Other layers

- `/etc/default/pveproxy` `ALLOW_FROM` / `DENY_FROM` / `POLICY` restrict who reaches 8006 independently of the firewall; `LISTEN_IP` binds the GUI to one address; restart `pveproxy` after changes [V].
- Upstream network ACLs (router, VLAN) still matter: the PVE firewall protects the host and guests, not the management VLAN design (`proxmox-networking`) [I].
