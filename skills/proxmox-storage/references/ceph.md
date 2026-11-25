# Hyperconverged Ceph on Proxmox VE

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-ceph-release
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.2 (2026-05-21) ships Ceph Squid 19.2.3 and Tentacle 20.2.1; pveceph install on a Ceph-free node defaults to Tentacle; existing clusters stay on their release. PVE 9.0 and 9.1 shipped Squid 19.2.3."
  - kind: external_fact
    subject: pve-ceph-sizing
    source_url: https://pve.proxmox.com/pve-docs/chapter-pveceph.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "At least 3 (preferably identical) nodes; 3 monitors; one OSD per physical disk; no hardware RAID; >=12 OSDs recommended; 8 GiB RAM per OSD recommended (4 GiB default); 10 Gbps+ dedicated, 25 Gbps+ for NVMe; size 3/min_size 2, never min_size 1."
-->

Labels: [V] = Proxmox admin guide 9.2.12 or roadmap, checked 2026-09-27; [I] = inferred, re-verify.

## Release

- PVE 9.2 offers **Squid 19.2.3** and **Tentacle 20.2.1**; new installs default to Tentacle, existing clusters stay pinned to their release until you upgrade Ceph deliberately [V 2026-09-27].
- Upgrade Ceph one major release at a time, following the Proxmox wiki upgrade guide for that pair, with `ceph -s` at `HEALTH_OK` first [I].
- Tentacle adds the FastEC erasure-code path; it needs `require_osd_release tentacle` [V].

## Sizing checklist

| Item | Minimum | Recommended |
|---|---|---|
| Nodes | 3 | 3+ identical; 4+ lets a node fail and still re-replicate to 3, if capacity allows (below) [I] |
| Monitors / managers | 3 MON, 1 MGR | 3 MON, 2+ MGR (standby) [I] |
| OSDs | one per physical disk [V] | 12+ spread evenly [V] |
| RAM | 4 GiB per OSD (default target) [V] | 8 GiB per OSD + MON/MGR/MDS + guests + headroom for recovery [V] |
| CPU | 1 thread per Ceph service [V] | 4-6 threads per high-end NVMe OSD [V] |
| Network | 10 Gbps dedicated [V] | 25 Gbps+ for NVMe; separate public and cluster networks [V] |
| Disks | no HW RAID [V] | Enterprise SSD/NVMe with PLP [I] |

Usable capacity with `size 3` is raw/3. There is no single safe fill level: after losing one of N equal hosts the survivors hold N/(N-1) of the data, and backfill stops at `backfillfull_ratio` (default 0.90; `nearfull` 0.85, `full` 0.95) [V 2026-09-27: Ceph health checks]. So the fullest OSD must stay below about 0.85 x (N-1)/N: roughly 64% with 4 equal hosts, 68% with 5 [I 2026-09-27: arithmetic from the defaults]. Size for your largest failure domain and watch the fullest OSD (`ceph osd df tree`), not the cluster average [I]. For example, 4 nodes at 80% would need about 107% on the survivors. With 3 nodes, a lost node leaves nowhere to re-create the third copy: the pool runs degraded until it returns [I].

## Networks

- **Public network**: clients (PVE nodes) to MON/OSD.
- **Cluster network** (optional, recommended): OSD replication and heartbeat; can be moved to separate hardware [V].
- Neither may be the corosync link: recovery traffic starves corosync and breaks quorum [V].
- Full-mesh (no switch) works for 3-5 nodes; PVE 9 SDN fabrics (OpenFabric/OSPF) can build it [V]. See `proxmox-networking`.

## Setup commands [V unless marked]

```bash
pveceph install --repository no-subscription [--version tentacle|squid]   # [I] check `pveceph help install`
pveceph init --network 10.10.10.0/24 [--cluster-network 10.10.20.0/24]   # initial setup only; a re-run ignores most options
pveceph mon create                                # on 3 nodes
pveceph mgr create
ceph-volume lvm zap /dev/<disk> --destroy         # only for a reused disk: destroys data
pveceph osd create /dev/<disk> [--db_dev /dev/<nvme>]
pveceph pool create vm-pool --add_storages --pg_autoscale_mode on   # size 3 / min_size 2 default
pveceph fs create --add-storage                   # CephFS (needs an MDS first: pveceph mds create)
```

## Pools

- Replicated `size 3`, `min_size 2`; never `min_size 1` (writes accepted on a single copy) [V].
- `pveceph pool create` defaults to `--pg_autoscale_mode warn`: it only warns about a bad PG count [V 2026-09-27: pveceph(1)]. Pass `--pg_autoscale_mode on` (or `pveceph pool set <pool> --pg_autoscale_mode on`) if you want it resized, then set a target ratio or size so it sizes early [V]; otherwise plan `pg_num` yourself and act on the warnings [I].
- Erasure-coded pools (`pveceph pool create --erasure-coding k=2,m=1`) save space but need more nodes than k+m and have higher latency [I; min_size rules V]; keep RBD metadata on a replicated pool [I].

## Operations

| Task | Command / rule |
|---|---|
| Health | `ceph -s`, `ceph health detail`, `ceph osd tree`, `ceph df` |
| Node maintenance | Scope the flag to that host: `ceph osd set-group noout <node>`, reboot, then `ceph osd unset-group noout <node>` and confirm with `ceph health detail` that no noout flag is left [V 2026-09-27: Ceph OSD troubleshooting]. A global `ceph osd set noout` also stops unrelated failed OSDs being marked out; keep it for whole-cluster shutdowns [V] |
| Failed OSD | Check free space first: `ceph osd df tree`, every OSD well below `nearfull` (85%) [V]. `ceph osd out <id>`, then wait until its data has re-replicated (`ceph -s` shows no degraded or misplaced PGs, the OSD shows 0 PGs) [V]. A dead OSD's PGs recover from other copies, but health stays WARN while it is down, so do not wait for `HEALTH_OK` [I 2026-09-27]. Then `ceph osd ok-to-stop <id>`, `pveceph stop --service osd.<id>`, `pveceph osd destroy <id> --cleanup` [V 2026-09-27: pveceph guide], replace disk, recreate |
| Memory target | `ceph config set osd osd_memory_target 8G` [V] |
| Remove a node | destroy its OSDs one by one, waiting for recovery to finish (no degraded PGs) each time, then MDS, MON, MGR, then `ceph osd crush remove <node>` [V] |

Never destroy more OSDs at once than the pool's redundancy allows, and never while the cluster is recovering [I].
