# Cluster operations: links, QDevice, node removal, recovery

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-pvecm-docs
    source_url: https://pve.proxmox.com/pve-docs/chapter-pvecm.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Admin guide 9.2.12: pvecm create/add --linkN; delnode after power-off; cleanup /etc/pve/nodes/<node>, known_hosts, rules, authorized_keys; separate-without-reinstall via pmxcfs -l; pvecm expected 1 when not quorate; QDevice setup/remove; LACP for corosync needs bond-lacp-rate fast."
-->

Labels: [V] = Proxmox admin guide 9.2.12, checked 2026-09-27; [I] = inferred, re-verify.

## Before creating a cluster

- All nodes on the same PVE version, time synced, final hostname and IP set, SSH (TCP 22) open between nodes [V].
- Joining node: no guests with VMIDs that could clash; its `/etc/pve` config is replaced by the cluster's [I]. Back up anything local first.
- Corosync network: dedicated 1 Gbit NIC is enough; latency under 5 ms; above ~10 ms with more than 3 nodes is unlikely to work [V].
- New clusters on 9.2 use `token_coefficient` 125 ms [V].

## Links and redundancy

```bash
pvecm create prod --link0 10.10.10.1,priority=15 --link1 10.20.20.1,priority=20   # link1 preferred [V]
pvecm add 10.10.10.1 --link0 10.10.10.2 --link1 10.20.20.2
```

- Add links to an existing cluster by editing `/etc/pve/corosync.conf` (copy, edit, increment `config_version`, move into place) [I]; disarm HA first.
- A second link on a different switch beats a bond; bonds for corosync: avoid balance-rr/xor/tlb/alb; active-backup may not fail over as expected; LACP needs `bond-lacp-rate fast` both sides [V].

## QDevice

```bash
# external host (Debian/Raspberry Pi/VM on OTHER hardware)
apt install corosync-qnetd
# every cluster node
apt install corosync-qdevice
pvecm qdevice setup <qnetd-ip>        # from one node; needs root SSH to the qnetd host [I]
pvecm status                           # expect Qdevice vote, Expected votes 3 for 2 nodes
```

- Supported for even node counts; for odd counts it provides N-1 votes and becomes almost a single point of failure [V].
- If adding a node later, remove the QDevice, add the node, re-add the QDevice when the count is even [I].

## Removing a node (permanently)

1. Migrate or remove all guests; back up local data [V].
2. Delete replication jobs that involve the node (`pvesr list`, `pvesr delete <job>`) [V: requirement; I: commands].
3. Remove the QDevice if configured [V].
4. Ceph: destroy its OSDs one at a time waiting for `HEALTH_OK`, then MDS, MON, MGR, then `ceph osd crush remove <node>` [V].
5. **Power it off** and ensure it cannot boot back into the network with its config [V].
6. From a remaining node: `pvecm delnode <node>`; ignore `cs_err_not_exist` [V].
7. Clean up: `/etc/pve/nodes/<node>`, HA rules referencing it, the key in `/etc/pve/priv/authorized_keys`, and `pvecm updatecerts` if a node with the same name/IP rejoins later [V].
8. To rejoin the same machine: reinstall PVE, then `pvecm add` [V].

Separating a node **without** reinstall (not recommended) [V]: remove any QDevice, give it its own storage first, then `systemctl stop pve-cluster corosync`, `pmxcfs -l`, `rm /etc/pve/corosync.conf`, `rm -r /etc/corosync/*`, `killall pmxcfs`, `systemctl start pve-cluster`; then `pvecm delnode <node>` from the cluster (use `pvecm expected 1` there only if it lost quorum); finally on the separated node `rm /var/lib/corosync/*` [V].

## Lost quorum and split brain

| Situation | Action |
|---|---|
| One node of 3 down | Nothing: still quorate. Fix the node |
| Majority down, you must start guests now | On ONE survivor, after confirming the others are really off: `pvecm expected 1` [V]; this is temporary until corosync restarts [I] |
| Corosync will not start (bad config) | Fix `/etc/corosync/corosync.conf` identically on all nodes, restart `corosync` [V] |
| Two partitions both believe they are primary (with votequorum this only happens after someone lowered `expected`) | Stop guests on one side; power that side off; let the other side regain quorum; bring nodes back one by one; compare `/etc/pve` changes made during the split [I] |
| Node keeps fencing (rebooting) | Check corosync link loss in `journalctl -u corosync`; disarm HA while fixing the network [I] |

Never set `expected 1` on two sides at once: each becomes writable and their `/etc/pve` diverges [I].

## Useful reads [I]

`pvecm status`, `corosync-quorumtool -s`, `corosync-cfgtool -s`, `journalctl -u corosync -u pve-cluster -b`, `ls -l /etc/pve/nodes`.
