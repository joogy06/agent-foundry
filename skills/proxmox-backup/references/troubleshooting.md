# Backup failures: symptoms and fixes

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pbs-gc-and-fingerprint
    source_url: https://pbs.proxmox.com/docs/maintenance.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Prune frees metadata only; GC sweep deletes chunks older than 24h5m; PVE PBS storage pins the server TLS fingerprint."
-->

Labels: **[V]** checked against Proxmox docs on 2026-09-27; **[I]** inferred or field experience, so re-verify. Read the task log first (Datacenter > Tasks, or `/var/log/vzdump/` and the job's task entry) [I].

| Symptom | Likely cause | Fix |
|---|---|---|
| Guest shows a `backup` lock after a failed or killed job; "VM is locked (backup)" | vzdump died before cleanup | Confirm no vzdump process for that ID (`ps aux \| grep vzdump`), then `qm unlock <vmid>` / `pct unlock <ctid>` for **that ID only** [I] |
| "certificate validation failed" / fingerprint mismatch after PBS cert renewal | PVE storage pins the old fingerprint [V: fingerprint option] | On PBS `proxmox-backup-manager cert info`; on PVE `pvesm set <storage> --fingerprint <new>` [I]. With a publicly trusted cert, the fingerprint can be dropped [I] |
| Datastore full; backups fail with ENOSPC | Prune ran but GC did not, or GC cutoff not yet passed | Run prune, then GC; space from chunks returns only after the 24h5m cutoff [V]. Emergency: delete snapshots of disposable groups, run GC, add capacity; never delete chunk files by hand [I] |
| `qmp command 'backup' failed` / `got timeout` | Target slow or unreachable, guest I/O stall, or an old QEMU after upgrade (VM not restarted) | Check network to PBS, enable fleecing on fast local storage [V option], restart the VM onto the new QEMU in a window [I] |
| Guest agent freeze times out; Windows VSS errors | Agent not running or a VSS writer hangs | Check the agent service in the guest; test `qm guest cmd <vmid> fsfreeze-status` [I]; fix the writer or disable freeze for that VM (`agent: 1,freeze-fs=0`; `freeze-fs-on-backup` is the deprecated alias) as a last resort [V] |
| Container snapshot backup fails | A mount point's storage cannot snapshot | Exclude it (`backup=0`) or use suspend/stop mode for that CT [V: all volumes must support snapshots] |
| Job did not run after downtime | Schedule missed | Enable `repeat-missed` on the job [V] |
| Backup "succeeded" but verify fails later | Bit rot or disk errors on the datastore | Check `zpool status`/SMART on PBS; `resync-corrupt` on the sync job from a good copy [V option]; take a fresh backup [I] |
| Sync job deletes things off-site | `remove-vanished` enabled | Turn it off on the ransomware-fallback copy [I] |
