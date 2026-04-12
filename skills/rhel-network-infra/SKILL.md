---
name: rhel-network-infra
description: Use when configuring network infrastructure services on RHEL 9 (and AlmaLinux/Rocky 9) — BIND DNS server, dnsmasq, Kea/ISC DHCP server, chrony NTP, VLAN routing with nmcli, IP forwarding, NAT with nftables/firewalld, and network troubleshooting tools. Part of the rhel-* skill family.
---

# Red Hat Enterprise Linux 9 — Network Infrastructure Services

Companion skill for DNS, DHCP, NTP, routing, and network diagnostics on RHEL 9.x (and compatible: AlmaLinux 9, Rocky Linux 9). For base system administration, see parent skill `rhel-server-admin`.

<HARD-RULE>
Always verify the RHEL version before applying advice. Packages, paths, and SELinux contexts differ between major releases.
```bash
cat /etc/redhat-release
cat /etc/os-release
getenforce
```
</HARD-RULE>

<HARD-RULE>
Never modify `/etc/resolv.conf` directly on systems managed by NetworkManager. Use `nmcli connection modify` to set DNS, or configure `/etc/NetworkManager/conf.d/` drop-ins.
</HARD-RULE>

<HARD-RULE>
After every firewalld rule change, run `sudo firewall-cmd --reload`. Runtime-only rules are lost on reboot — always use `--permanent`.
</HARD-RULE>

---

## 1. BIND DNS Server

### Installation

```bash
sudo dnf install bind bind-utils
sudo systemctl enable --now named
sudo firewall-cmd --permanent --add-service=dns
sudo firewall-cmd --reload
```

### Main Configuration — `/etc/named.conf`

```bash
options {
    listen-on port 53 { 127.0.0.1; 10.0.1.0/24; };
    listen-on-v6 port 53 { ::1; };
    directory       "/var/named";
    dump-file       "/var/named/data/cache_dump.db";
    statistics-file "/var/named/data/named_stats.txt";
    allow-query     { localhost; 10.0.0.0/8; 192.168.0.0/16; };
    allow-transfer  { none; };
    recursion yes;
    allow-recursion { localhost; 10.0.0.0/8; };

    forwarders {
        1.1.1.1;
        8.8.8.8;
    };
    forward only;

    dnssec-validation auto;

    managed-keys-directory "/var/named/dynamic";
    pid-file "/run/named/named.pid";
    session-keyfile "/run/named/session.key";
};

logging {
    channel default_log {
        file "/var/named/data/named.log" versions 3 size 5m;
        severity info;
        print-time yes;
        print-severity yes;
        print-category yes;
    };
    category default { default_log; };
    category queries { default_log; };
};

# ACLs
acl "trusted" {
    10.0.1.0/24;
    10.0.2.0/24;
    localhost;
};

zone "home.lab" IN {
    type master;
    file "home.lab.zone";
    allow-update { none; };
};

zone "1.0.10.in-addr.arpa" IN {
    type master;
    file "10.0.1.rev";
    allow-update { none; };
};
```

### Forward Zone File — `/var/named/home.lab.zone`

```
$TTL 86400
@   IN  SOA ns1.home.lab. admin.home.lab. (
            2026032301  ; Serial (YYYYMMDDNN)
            3600        ; Refresh
            1800        ; Retry
            604800      ; Expire
            86400 )     ; Minimum TTL

    IN  NS  ns1.home.lab.

ns1         IN  A   10.0.1.10
gateway     IN  A   10.0.1.1
server01    IN  A   10.0.1.50
server02    IN  A   10.0.1.51
nas         IN  A   10.0.1.100
www         IN  CNAME server01.home.lab.
```

### Reverse Zone File — `/var/named/10.0.1.rev`

```
$TTL 86400
@   IN  SOA ns1.home.lab. admin.home.lab. (
            2026032301  ; Serial
            3600
            1800
            604800
            86400 )

    IN  NS  ns1.home.lab.

10  IN  PTR ns1.home.lab.
1   IN  PTR gateway.home.lab.
50  IN  PTR server01.home.lab.
51  IN  PTR server02.home.lab.
100 IN  PTR nas.home.lab.
```

### SELinux for BIND

<HARD-RULE>
BIND runs as the `named_t` SELinux type. Zone files must be in `/var/named` with context `named_zone_t`. Always use `restorecon` after creating or moving zone files.
</HARD-RULE>

```bash
# Check named SELinux booleans
getsebool -a | grep named

# Allow named to write master zones (for dynamic updates)
sudo setsebool -P named_write_master_zones 1

# Restore context on zone files
sudo restorecon -Rv /var/named/

# If using a custom log directory
sudo semanage fcontext -a -t named_log_t "/var/named/data(/.*)?"
sudo restorecon -Rv /var/named/data/
```

### Validate and Test

```bash
# Check config syntax
sudo named-checkconf
sudo named-checkzone home.lab /var/named/home.lab.zone
sudo named-checkzone 1.0.10.in-addr.arpa /var/named/10.0.1.rev

# Restart after changes
sudo systemctl restart named

# Test resolution
dig @127.0.0.1 server01.home.lab
dig @127.0.0.1 -x 10.0.1.50
dig @127.0.0.1 home.lab AXFR     # zone transfer (should be refused)
```

### Split-Horizon DNS

Add views in `/etc/named.conf` to serve different answers for internal vs external clients:

```bash
view "internal" {
    match-clients { 10.0.0.0/8; 192.168.0.0/16; localhost; };
    recursion yes;

    zone "example.com" IN {
        type master;
        file "example.com.internal.zone";
    };
};

view "external" {
    match-clients { any; };
    recursion no;

    zone "example.com" IN {
        type master;
        file "example.com.external.zone";
    };
};
```

### DNSSEC Basics

```bash
# Generate zone-signing key (ZSK) and key-signing key (KSK)
cd /var/named
sudo dnssec-keygen -a ECDSAP256SHA256 home.lab
sudo dnssec-keygen -a ECDSAP256SHA256 -f KSK home.lab

# Sign the zone
sudo dnssec-signzone -A -3 $(head -c 1000 /dev/random | sha1sum | cut -b 1-16) \
  -N INCREMENT -o home.lab -t home.lab.zone

# Update named.conf to use the signed zone file
# file "home.lab.zone.signed";

sudo restorecon -Rv /var/named/
sudo systemctl restart named
```

---

## 2. dnsmasq — Lightweight DNS/DHCP

### Installation and Basic Config

```bash
sudo dnf install dnsmasq
sudo systemctl enable --now dnsmasq
sudo firewall-cmd --permanent --add-service=dns --add-service=dhcp
sudo firewall-cmd --reload
```

### Configuration — `/etc/dnsmasq.conf`

```ini
# Interface binding
interface=ens18
bind-interfaces

# DNS settings
domain=home.lab
local=/home.lab/
expand-hosts

# Upstream DNS
server=1.1.1.1
server=8.8.8.8

# DNS cache
cache-size=1000

# DHCP range
dhcp-range=10.0.1.100,10.0.1.200,255.255.255.0,12h

# Default gateway and DNS for DHCP clients
dhcp-option=option:router,10.0.1.1
dhcp-option=option:dns-server,10.0.1.10

# Static leases
dhcp-host=aa:bb:cc:dd:ee:01,nas,10.0.1.100
dhcp-host=aa:bb:cc:dd:ee:02,printer,10.0.1.101

# Additional hosts (acts like /etc/hosts entries)
addn-hosts=/etc/dnsmasq.hosts

# Logging
log-queries
log-dhcp
log-facility=/var/log/dnsmasq.log
```

### Coexistence with systemd-resolved

On some RHEL 9 minimal installs, `systemd-resolved` may be present:

```bash
# Check if resolved is running
systemctl is-active systemd-resolved

# If dnsmasq should be the sole DNS, disable resolved
sudo systemctl stop systemd-resolved
sudo systemctl disable systemd-resolved
sudo rm -f /etc/resolv.conf
echo "nameserver 127.0.0.1" | sudo tee /etc/resolv.conf

# Or configure NetworkManager to skip resolved
# /etc/NetworkManager/conf.d/no-resolved.conf
# [main]
# dns=none
```

```bash
# Validate and restart
sudo dnsmasq --test
sudo systemctl restart dnsmasq
journalctl -u dnsmasq -f
```

---

## 3. Kea DHCP Server (Modern Replacement)

### Installation from EPEL

```bash
sudo dnf install epel-release
sudo dnf install kea

# Kea installs multiple services
# kea-dhcp4 — DHCPv4 server
# kea-dhcp6 — DHCPv6 server
# kea-dhcp-ddns — Dynamic DNS updates
# kea-ctrl-agent — REST API

sudo systemctl enable --now kea-dhcp4
sudo firewall-cmd --permanent --add-service=dhcp
sudo firewall-cmd --reload
```

### DHCPv4 Config — `/etc/kea/kea-dhcp4.conf`

```json
{
    "Dhcp4": {
        "interfaces-config": {
            "interfaces": [ "ens18" ]
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/dhcp4.leases"
        },
        "valid-lifetime": 43200,
        "renew-timer": 21600,
        "rebind-timer": 37800,

        "subnet4": [
            {
                "subnet": "10.0.1.0/24",
                "pools": [ { "pool": "10.0.1.100 - 10.0.1.200" } ],
                "option-data": [
                    { "name": "routers", "data": "10.0.1.1" },
                    { "name": "domain-name-servers", "data": "10.0.1.10" },
                    { "name": "domain-name", "data": "home.lab" },
                    { "name": "domain-search", "data": "home.lab" }
                ],
                "reservations": [
                    {
                        "hw-address": "aa:bb:cc:dd:ee:01",
                        "ip-address": "10.0.1.100",
                        "hostname": "nas"
                    },
                    {
                        "hw-address": "aa:bb:cc:dd:ee:02",
                        "ip-address": "10.0.1.101",
                        "hostname": "printer"
                    }
                ]
            }
        ],

        "loggers": [
            {
                "name": "kea-dhcp4",
                "output-options": [
                    { "output": "/var/log/kea/kea-dhcp4.log" }
                ],
                "severity": "INFO"
            }
        ]
    }
}
```

### Validate and Monitor

```bash
# Syntax check
kea-dhcp4 -t /etc/kea/kea-dhcp4.conf

sudo systemctl restart kea-dhcp4
journalctl -u kea-dhcp4 -f

# View leases
cat /var/lib/kea/dhcp4.leases
```

### Kea HA (Hot Standby)

Add to `kea-dhcp4.conf` on both nodes:

```json
"hooks-libraries": [
    {
        "library": "/usr/lib64/kea/hooks/libdhcp_lease_cmds.so"
    },
    {
        "library": "/usr/lib64/kea/hooks/libdhcp_ha.so",
        "parameters": {
            "high-availability": [{
                "this-server-name": "server1",
                "mode": "hot-standby",
                "peers": [
                    { "name": "server1", "url": "http://10.0.1.50:8000/", "role": "primary" },
                    { "name": "server2", "url": "http://10.0.1.51:8000/", "role": "standby" }
                ]
            }]
        }
    }
]
```

---

## 4. ISC DHCP Server (Legacy)

<HARD-RULE>
ISC DHCP (dhcpd) reached end-of-life in 2022. Use Kea for new deployments. This section covers maintenance and migration only.
</HARD-RULE>

### Installation

```bash
sudo dnf install dhcp-server
sudo systemctl enable --now dhcpd
sudo firewall-cmd --permanent --add-service=dhcp
sudo firewall-cmd --reload
```

### Configuration — `/etc/dhcp/dhcpd.conf`

```bash
authoritative;
default-lease-time 43200;
max-lease-time 86400;

option domain-name "home.lab";
option domain-name-servers 10.0.1.10;

subnet 10.0.1.0 netmask 255.255.255.0 {
    range 10.0.1.100 10.0.1.200;
    option routers 10.0.1.1;
    option broadcast-address 10.0.1.255;

    host nas {
        hardware ethernet aa:bb:cc:dd:ee:01;
        fixed-address 10.0.1.100;
    }
}
```

### SELinux for DHCP

```bash
# dhcpd runs as dhcpd_t
getsebool -a | grep dhcp
# Lease file context
ls -Z /var/lib/dhcpd/dhcpd.leases

sudo systemctl restart dhcpd
journalctl -u dhcpd -f

# View leases
cat /var/lib/dhcpd/dhcpd.leases
```

### Migration Path: ISC DHCP to Kea

1. Export current leases and reservations from `/etc/dhcp/dhcpd.conf`
2. Translate subnet/pool/host declarations to Kea JSON format (see Section 3)
3. Install Kea, test with `-t` flag, run both in parallel briefly
4. Stop and disable dhcpd, enable kea-dhcp4
5. Verify clients receive leases from Kea

---

## 5. NTP with chrony

### Configuration — `/etc/chrony.conf`

```bash
# Public NTP pools
pool 2.rhel.pool.ntp.org iburst

# Or specific servers
server time1.google.com iburst
server time2.google.com iburst

# Allow LAN clients to sync from this server
allow 10.0.1.0/24
allow 192.168.0.0/16

# Serve time even when not synchronized (stratum 10 fallback)
local stratum 10

# Record rate of drift
driftfile /var/lib/chrony/drift

# Enable kernel RTC sync
rtcsync

# Log
logdir /var/log/chrony
log measurements statistics tracking

# Security: step clock only on first 3 updates
makestep 1.0 3
```

### Service Management

```bash
sudo systemctl enable --now chronyd
sudo firewall-cmd --permanent --add-service=ntp
sudo firewall-cmd --reload
```

### Monitoring with chronyc

```bash
# Check sync status
chronyc tracking

# List sources with detail
chronyc sources -v
chronyc sourcestats

# Check NTP clients connected to this server
chronyc clients

# Force immediate sync
sudo chronyc makestep

# Check if chrony is serving time
chronyc activity

# Verify time accuracy
timedatectl status
timedatectl timesources     # RHEL 9.2+
```

---

## 6. Routing, NAT, and VLANs

### Enable IP Forwarding

```bash
# Temporary
sudo sysctl -w net.ipv4.ip_forward=1

# Permanent — create /etc/sysctl.d/99-ip-forward.conf
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
```

```bash
sudo sysctl --system
sysctl net.ipv4.ip_forward     # verify
```

### Static Routes via nmcli

```bash
# Add a static route
sudo nmcli connection modify "ens18" +ipv4.routes "10.0.2.0/24 10.0.1.254"
sudo nmcli connection modify "ens18" +ipv4.routes "10.0.3.0/24 10.0.1.254 100"  # metric 100
sudo nmcli connection up "ens18"

# View routes
ip route show
ip route get 10.0.2.50

# Remove a static route
sudo nmcli connection modify "ens18" -ipv4.routes "10.0.2.0/24 10.0.1.254"
sudo nmcli connection up "ens18"
```

### NAT / Masquerade with firewalld

```bash
# Enable masquerade on external zone
sudo firewall-cmd --permanent --zone=public --add-masquerade

# Port forwarding (DNAT)
sudo firewall-cmd --permanent --zone=public \
  --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=10.0.1.50

# Forward all traffic for an internal subnet
sudo firewall-cmd --permanent --zone=internal --add-source=10.0.1.0/24
sudo firewall-cmd --permanent --zone=public --add-masquerade

sudo firewall-cmd --reload
sudo firewall-cmd --zone=public --query-masquerade
```

### Direct nftables NAT (Advanced)

```bash
# /etc/nftables/nat.nft
table ip nat {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        tcp dport 8080 dnat to 10.0.1.50:80
    }
    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;
        oifname "ens18" masquerade
    }
}
```

```bash
sudo nft -f /etc/nftables/nat.nft
sudo nft list ruleset
```

### VLAN Routing

```bash
# Create VLAN interfaces on the router host
sudo nmcli connection add type vlan con-name vlan10 ifname ens18.10 dev ens18 id 10 \
  ipv4.addresses 10.0.10.1/24 ipv4.method manual

sudo nmcli connection add type vlan con-name vlan20 ifname ens18.20 dev ens18 id 20 \
  ipv4.addresses 10.0.20.1/24 ipv4.method manual

sudo nmcli connection up vlan10
sudo nmcli connection up vlan20

# With IP forwarding enabled, the host now routes between VLANs
# Add firewall rules to control inter-VLAN traffic
sudo firewall-cmd --permanent --zone=internal --add-interface=ens18.10
sudo firewall-cmd --permanent --zone=internal --add-interface=ens18.20
sudo firewall-cmd --reload
```

### Policy Routing (Source-Based Routing)

Use when different source subnets should use different gateways:

```bash
# Create a custom routing table
echo "100 isp2" | sudo tee -a /etc/iproute2/rt_tables

# Add rules and routes via nmcli
sudo nmcli connection modify "ens19" ipv4.routing-rules "priority 100 from 10.0.2.0/24 table 100"
sudo nmcli connection modify "ens19" ipv4.routes "0.0.0.0/0 10.0.2.1 table=100"
sudo nmcli connection up "ens19"

# Verify
ip rule show
ip route show table 100
```

---

## 7. Network Troubleshooting

### DNS Diagnostics — `dig` and `nslookup`

```bash
# Forward lookup
dig server01.home.lab @10.0.1.10
dig +short server01.home.lab

# Reverse lookup
dig -x 10.0.1.50

# Trace delegation path
dig +trace example.com

# Query specific record types
dig home.lab MX
dig home.lab NS
dig home.lab SOA
dig home.lab AXFR @10.0.1.10    # zone transfer

# Check DNSSEC
dig +dnssec example.com
```

### Socket Statistics — `ss`

```bash
ss -tlnp                         # TCP listeners with process names
ss -ulnp                         # UDP listeners
ss -s                            # summary statistics
ss -tnp state established        # active connections
ss -tnp dst 10.0.1.50            # connections to a specific host
ss -tnp sport = :443             # connections from port 443
```

### Packet Capture — `tcpdump`

<HARD-RULE>
Packet captures may contain sensitive data. Save captures to a controlled directory, restrict file permissions, and delete when no longer needed.
</HARD-RULE>

```bash
# Capture DNS traffic
sudo tcpdump -i ens18 port 53 -nn

# Capture DHCP traffic
sudo tcpdump -i ens18 port 67 or port 68 -nn -v

# Save to file for Wireshark analysis
sudo tcpdump -i ens18 -w /tmp/capture.pcap -c 1000

# Filter by host
sudo tcpdump -i ens18 host 10.0.1.50 -nn

# Capture with human-readable output
sudo tcpdump -i ens18 -A port 80 -c 50
```

### Routing Diagnostics

```bash
# View routing table
ip route show
ip -6 route show

# Test path to destination
ip route get 10.0.2.50

# Traceroute
traceroute 10.0.2.50
traceroute -n -T -p 443 example.com    # TCP traceroute

# mtr (combined ping + traceroute)
sudo dnf install mtr
mtr -rw -c 10 example.com              # report mode, wide output
mtr -rw -c 10 --tcp -P 443 example.com # TCP mode
```

### Port Scanning and Service Discovery — `nmap`

```bash
sudo dnf install nmap

# Scan common ports on a host
nmap -sT 10.0.1.50

# Scan specific ports
nmap -p 22,53,80,443 10.0.1.50

# Scan a subnet
nmap -sn 10.0.1.0/24              # ping sweep (host discovery)

# Service version detection
nmap -sV -p 22,53,80 10.0.1.50

# UDP scan (requires root)
sudo nmap -sU -p 53,67,123 10.0.1.50
```

### Connectivity Basics

```bash
# Ping with count and interval
ping -c 4 10.0.1.1
ping -c 4 -i 0.2 10.0.1.1        # fast ping

# ARP / neighbor table
ip neigh show

# Check interface details
ip addr show ens18
ip link show ens18
ethtool ens18                     # link speed, duplex

# DNS resolution check
resolvectl status
resolvectl query server01.home.lab
```

---

## Quick Reference: Ports and Firewall Services

| Service | Port(s) | firewall-cmd service |
|---|---|---|
| DNS | 53/tcp, 53/udp | `dns` |
| DHCP | 67/udp, 68/udp | `dhcp` |
| NTP | 123/udp | `ntp` |
| Kea Control Agent | 8000/tcp | (add port manually) |

```bash
# Open all infra services at once
sudo firewall-cmd --permanent --add-service={dns,dhcp,ntp}
sudo firewall-cmd --reload
```

---

## SELinux Quick Reference for Network Services

| Service | SELinux Type | Key Booleans |
|---|---|---|
| BIND (named) | `named_t` | `named_write_master_zones` |
| ISC DHCP (dhcpd) | `dhcpd_t` | — |
| Kea DHCP | `unconfined_service_t` (EPEL) | — |
| chrony | `chronyd_t` | — |
| dnsmasq | `dnsmasq_t` | `dnsmasq_disable_trans` |

```bash
# Troubleshoot any SELinux denial
sudo ausearch -m AVC --start recent -ts recent
sudo sealert -a /var/log/audit/audit.log
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Editing /etc/resolv.conf manually on systems using NetworkManager | NetworkManager overwrites manual changes on next connection event; DNS configuration reverts silently | Configure DNS through nmcli (`nmcli con mod ... ipv4.dns`) or connection profile files; let NM manage resolv.conf |
| Running BIND DNS without DNSSEC validation | Vulnerable to DNS poisoning and man-in-the-middle attacks; users can be redirected to malicious sites | Enable DNSSEC validation in named.conf (`dnssec-validation auto`); test with `dig +dnssec` |
| No NTP sync monitoring | Clock drift causes Kerberos authentication failures, log timestamp mismatches, and certificate validation errors | Monitor chrony sync with `chronyc tracking`; alert when offset exceeds 100ms; verify NTP source availability |
| Configuring IP forwarding without firewall rules | Server becomes an open router; any network traffic can traverse through it; bypasses network security controls | Enable ip_forward only when needed; restrict with nftables/firewalld zone policies; log forwarded traffic |
| Using static routes instead of proper VLAN routing | Static routes break when network topology changes; maintenance nightmare with 10+ subnets | Use VLAN interfaces (nmcli con add type vlan) with proper gateway configuration; document VLAN assignments |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core RHEL admin (parent skill) | `rhel-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Docker / Podman containers | `rhel-docker-host` |
| File sharing (NFS, Samba) | `rhel-file-storage` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `rhel-ollama-nvidia` |
