# Monitoring, notifications and hardening

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-notifications-metrics
    source_url: https://pve.proxmox.com/pve-docs/chapter-notifications.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Targets sendmail, smtp (mode insecure|starttls|tls), gotify, webhook; matchers match-severity, match-field, match-calendar; event types package-updates, fencing, replication, vzdump; metric servers Graphite (UDP 2003) and InfluxDB (UDP or HTTP v2 API) in /etc/pve/status.cfg; smartd scans every 30 min and mails root; ZED_EMAIL_ADDR in /etc/zfs/zed.d/zed.rc."
-->

Labels: **[V]** checked against pve.proxmox.com on 2026-09-27; **[I]** inferred, so re-verify.

## Notifications

Config: `/etc/pve/notifications.cfg`; secrets (passwords, tokens) in `/etc/pve/priv/notifications.cfg` [V].

| Target | Notes [V] |
|---|---|
| `sendmail` | Local MTA (postfix by default); queues and retries |
| `smtp` | Direct relay; `mode insecure|starttls|tls`; **no** queue or retry |
| `gotify` | Self-hosted push; honours the HTTP proxy setting |
| `webhook` | Any HTTP endpoint (ntfy, Discord, Slack, Matrix); body templates with `{{ secrets.token }}` |

Matchers decide which events reach which targets [V]:

```ini
matcher: critical
        match-severity error,warning
        target mail-admins
        target phone

matcher: backups
        match-field exact:type=vzdump
        target mail-admins
```

Event types include `package-updates` (info), `fencing` (error), `replication` (error), `vzdump` (info on success, error on failure) [V]. Test each target from the GUI ("Test") [I]. Keep one matcher that sends **all errors** somewhere a human looks [I].

## Metric servers

- Datacenter > Metric Server, saved in `/etc/pve/status.cfg` [V].
- Graphite: UDP by default, port 2003, path `proxmox` [V].
- InfluxDB: UDP (v1 line protocol) or `influxdbproto http|https` for the v2 API with org, bucket and token; InfluxDB 1.8 exposes a compatible v2 endpoint [V]. Adjust `max-body-size` if large clusters drop batches [V].
- Grafana on top; the Prometheus route uses the community `prometheus-pve-exporter` against an API token with `PVEAuditor` [I].

## Disk health

- `smartd` is active by default, scans `/dev/sd*` and `/dev/nvme*` every 30 minutes, and mails root [V]. Check with `smartctl -a /dev/<disk>` [V].
- ZFS: `zfs-zed` installed by default; `ZED_EMAIL_ADDR="root"` in `/etc/zfs/zed.d/zed.rc` [V]. Mails to root go to root@pam's configured email [V].
- Set root@pam's email (Datacenter > Permissions > Users) and send a test mail; otherwise both channels are silent [I].
- Schedule ZFS scrubs (Debian ships a monthly scrub cron) and watch `zpool status` in monitoring [I]. Pool design is `proxmox-storage`.

## Hardening checklist [I unless marked]

| Area | Action |
|---|---|
| Network exposure | Management (8006, 22, 3128, 5900-5999) on a dedicated VLAN or behind VPN; never port-forward 8006 |
| Firewall | Datacenter firewall on with `management` IPSet [V]; guest firewalls for internet-facing guests |
| Accounts | Personal accounts + groups; `root@pam` for break-glass with TFA and recovery keys |
| Automation | API tokens with privsep, least-privilege ACLs, expiry [V] |
| SSH | Keys only (`PasswordAuthentication no`); keep root key login for cluster tooling, which needs it between nodes |
| Certificates | ACME [V], or an uploaded CA cert in `/etc/pve/local/pveproxy-ssl.pem` [V], so admins notice a real TLS warning |
| GUI reach | `/etc/default/pveproxy` `ALLOW_FROM`/`DENY_FROM`/`POLICY`, `LISTEN_IP` to bind one address [V]; restart `pveproxy` |
| Updates | Correct repo, `apt full-upgrade` routinely [V], kernel reboots scheduled |
| Guests | Unprivileged LXC by default (`proxmox-lxc`); Secure Boot/vTPM where the guest supports it (`proxmox-vm`) |
| Logs | Ship `journalctl` and `/var/log/pve/tasks` to central logging; review failed logins |
| Backups | Encrypted, off-host, restore-tested (`proxmox-backup`) |
| fail2ban | Optional; PVE 8+/Debian 12+ has no rsyslog, so use `backend = systemd` with a journal match on `pvedaemon` "authentication failure" lines, not `/var/log/daemon.log`; less needed if 8006 is not exposed |
| Services | Disable unused ones (`rpcbind` if no NFS) after checking storage needs |
