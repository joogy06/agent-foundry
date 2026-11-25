# Proxmox VE SDN: zones, VNets, IPAM, fabrics

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: pve-sdn-features
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "SDN core installed by default since 8.1; fabrics (OpenFabric, OSPF) in 9.0; status reporting (connected guests, learned IPs/MACs, fabric routes) in 9.1; WireGuard and BGP fabrics, route maps, prefix lists, IPv6 EVPN underlay, multiple EVPN controllers and dry-run in 9.2. Roadmap still lists DHCP IPAM and external IPAM plugins as to-be-stabilised."
-->

Labels: [V] = Proxmox admin guide 9.2.12 or roadmap, checked 2026-09-27; [I] = inferred, re-verify.

## Support status (PVE 9.2) [V]

| Layer | Status |
|---|---|
| Core SDN: zones, VNets, subnets, permissions on `/sdn/...` | Supported |
| IPAM incl. DHCP (dnsmasq) | Tech preview (since 8.1; roadmap: stabilise and extend beyond Simple zones) |
| FRR routing, EVPN controllers, BGP | Tech preview |
| External IPAM/DNS plugins (NetBox, phpIPAM, PowerDNS) | Roadmap item to stabilise |
| Fabrics | Built on FRR, which the guide marks tech preview, so treat as tech preview [I] |

## Prerequisites [V]

- `libpve-network-perl` (installed by default since 8.1) and `ifupdown2`.
- Last line of `/etc/network/interfaces` on every node: `source /etc/network/interfaces.d/*`.
- DHCP: `apt install dnsmasq` then `systemctl disable --now dnsmasq` on every node (SDN starts its own instances).
- EVPN/BGP/fabrics: `apt install frr-pythontools` and `systemctl enable frr.service` on all nodes.

## Zones

| Zone | Does | Spans nodes | Needs |
|---|---|---|---|
| Simple | Isolated bridge per node; with SNAT/routing gives NAT or routed guests | No (local only) | nothing; DHCP works here first |
| VLAN | VNet = VLAN tag on an existing bridge | Yes | VLAN-trunked physical network |
| QinQ | Outer service VLAN + inner VLAN | Yes | Switches with 802.1ad; MTU -4 |
| VXLAN | L2 overlay over UDP between node IPs (peer list or fabric) | Yes, any routed underlay | MTU -50; no encryption |
| EVPN | VXLAN + BGP EVPN control plane, anycast gateway, L3 routing, exit nodes | Yes | FRR, controller, VRF VXLAN ID distinct from VNet IDs |

Decision: most small clusters need only **VLAN zones** on a VLAN-aware bridge; use Simple for a NAT lab network on one node; use VXLAN/EVPN only when nodes have no common L2 or you need multi-tenant routing [I].

## Workflow

1. Datacenter > SDN > Zones: add zone (restrict to nodes if needed; set MTU).
2. VNets: add VNet in the zone (VLAN tag or VXLAN ID); optionally "VLAN aware".
3. Subnets: CIDR, gateway, SNAT, DHCP range (tech preview).
4. SDN overview: **Apply** (9.2: dry-run first) [V]. Config lives in `/etc/pve/sdn/*.cfg`; state in `.running-config` and `.version` [V].
5. Attach guests: `bridge=<vnet-name>` on the NIC.

CLI equivalents go through the API, for example [I]:

```bash
pvesh create /cluster/sdn/zones --zone lab --type vlan --bridge vmbr0
pvesh create /cluster/sdn/vnets --vnet v20 --zone lab --tag 20
pvesh set /cluster/sdn                 # apply pending SDN config
pvesh get /cluster/sdn/zones --pending 1
```

PVE 9.0 added an API endpoint to revert pending SDN changes and the one-shot `pve-sdn-commit` service [V].

## Fabrics

- Routed underlay between nodes; OpenFabric and OSPF since 9.0, WireGuard (encrypted, per-node keys) and BGP (eBGP unnumbered) since 9.2 [V].
- Each node needs a unique router ID (IPv4; OpenFabric also accepts IPv6) [V].
- Typical uses: full-mesh Ceph network for 3-5 nodes without a switch; underlay for VXLAN/EVPN peers [V].
- Status appears in the resource tree (routes, neighbours, interfaces) since 9.1 [V].

## Troubleshooting

| Symptom | Check |
|---|---|
| VNet missing on a node | `source /etc/network/interfaces.d/*` present? Apply ran on all nodes? `cat /etc/network/interfaces.d/sdn` |
| Guests on VLAN VNet cannot talk across nodes | Switch trunk carries the tag; bridge is VLAN-aware |
| VXLAN large packets drop | Guest/VNet MTU not reduced by 50 |
| EVPN routes missing | `vtysh -c "show bgp l2vpn evpn summary"` [I]; FRR enabled on all nodes |
| DHCP gives no lease | dnsmasq installed on every node; subnet has a gateway (9.2 fixed a crash without one) [V] |

Firewall rules for VNets and guests: `proxmox-security-ops`.
