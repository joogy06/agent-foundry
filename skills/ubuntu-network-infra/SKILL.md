---
name: ubuntu-network-infra
description: Use when configuring network infrastructure services on Ubuntu 24.04 LTS — BIND9 DNS server, dnsmasq, Kea/ISC DHCP server, NTP with chrony/timesyncd, VLAN routing, IP forwarding, NAT, and network troubleshooting tools. Part of the ubuntu-* skill family.
---

# Ubuntu Server 24.04 LTS — Network Infrastructure

Companion skill to `ubuntu-server-admin` covering DNS, DHCP, NTP, routing, and network diagnostics on Ubuntu Server 24.04.4 LTS (Noble Numbat). For core system administration (packages, users, SSH, firewall, disks), see the parent skill.

<HARD-RULE>
Always verify the Ubuntu version before applying advice. Package names, config paths, and default behaviors differ between releases.
```bash
lsb_release -a   # or cat /etc/os-release
```
</HARD-RULE>

<HARD-RULE>
Network infrastructure changes can lock you out of remote servers. Always keep a separate SSH session open and use `netplan try` (120s auto-rollback) when changing IP/routing. For DNS/DHCP changes, validate config syntax before restarting services.
</HARD-RULE>

---

## 1. BIND9 DNS Server

### Installation

```bash
sudo apt install bind9 bind9-utils bind9-dnsutils
sudo systemctl enable --now named
```

Config directory: `/etc/bind/`
Key files: `named.conf`, `named.conf.options`, `named.conf.local`, `named.conf.default-zones`

### named.conf.options — Caching Forwarder with ACLs

```bash
# /etc/bind/named.conf.options
acl "trusted" {
    10.0.0.0/8;
    192.168.0.0/16;
    172.16.0.0/12;
    localhost;
};

options {
    directory "/var/cache/bind";

    recursion yes;
    allow-recursion { trusted; };
    allow-query { trusted; };
    allow-transfer { none; };

    forwarders {
        1.1.1.1;
        8.8.8.8;
    };
    forward only;

    dnssec-validation auto;
    listen-on { any; };
    listen-on-v6 { none; };

    querylog yes;
};
```

### Forward Zone

Add to `/etc/bind/named.conf.local`:
```bash
zone "home.lab" {
    type master;
    file "/etc/bind/zones/db.home.lab";
    allow-update { none; };
};
```

Create `/etc/bind/zones/db.home.lab`:
```bash
sudo mkdir -p /etc/bind/zones
```

```
$TTL    604800
@       IN      SOA     ns1.home.lab. admin.home.lab. (
                        2024031501  ; Serial (YYYYMMDDNN)
                        3600        ; Refresh
                        1800        ; Retry
                        604800      ; Expire
                        86400 )     ; Negative Cache TTL

; Name servers
@       IN      NS      ns1.home.lab.

; A records
ns1     IN      A       10.0.1.10
gw      IN      A       10.0.1.1
web01   IN      A       10.0.1.50
db01    IN      A       10.0.1.60
app01   IN      A       10.0.1.70

; CNAME records
www     IN      CNAME   web01.home.lab.
mail    IN      CNAME   web01.home.lab.

; MX record
@       IN      MX  10  mail.home.lab.
```

<HARD-RULE>
Always increment the SOA serial number when editing zone files. BIND will not propagate changes to secondaries if the serial is not incremented. Use YYYYMMDDNN format.
</HARD-RULE>

### Reverse Zone (PTR Records)

Add to `/etc/bind/named.conf.local`:
```bash
zone "1.0.10.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/db.10.0.1";
    allow-update { none; };
};
```

Create `/etc/bind/zones/db.10.0.1`:
```
$TTL    604800
@       IN      SOA     ns1.home.lab. admin.home.lab. (
                        2024031501  ; Serial
                        3600        ; Refresh
                        1800        ; Retry
                        604800      ; Expire
                        86400 )     ; Negative Cache TTL

@       IN      NS      ns1.home.lab.

1       IN      PTR     gw.home.lab.
10      IN      PTR     ns1.home.lab.
50      IN      PTR     web01.home.lab.
60      IN      PTR     db01.home.lab.
70      IN      PTR     app01.home.lab.
```

### Split-Horizon DNS (Internal vs External Views)

Replace zone declarations in `/etc/bind/named.conf.local`:
```bash
view "internal" {
    match-clients { trusted; };
    recursion yes;

    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.internal";
    };
};

view "external" {
    match-clients { any; };
    recursion no;

    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.external";
    };
};
```

### Logging

Add to `/etc/bind/named.conf.local`:
```bash
logging {
    channel query_log {
        file "/var/log/named/query.log" versions 3 size 10m;
        severity info;
        print-time yes;
        print-category yes;
    };
    channel default_log {
        file "/var/log/named/default.log" versions 3 size 10m;
        severity warning;
        print-time yes;
    };
    category queries { query_log; };
    category default { default_log; };
};
```

```bash
sudo mkdir -p /var/log/named
sudo chown bind:bind /var/log/named
```

### DNSSEC Basics (Signing a Zone)

```bash
# Generate zone-signing key (ZSK) and key-signing key (KSK)
cd /etc/bind/zones
sudo dnssec-keygen -a ECDSAP256SHA256 -n ZONE home.lab
sudo dnssec-keygen -a ECDSAP256SHA256 -n ZONE -f KSK home.lab

# Include keys in zone file — add at bottom of db.home.lab:
# $INCLUDE "Khome.lab.+013+NNNNN.key"
# $INCLUDE "Khome.lab.+013+MMMMM.key"

# Sign the zone
sudo dnssec-signzone -A -3 $(head -c 1000 /dev/urandom | sha1sum | cut -b 1-16) \
  -N INCREMENT -o home.lab -t db.home.lab

# Update named.conf.local to point to db.home.lab.signed
```

### Management Commands

```bash
# Validate config before restart
sudo named-checkconf
sudo named-checkzone home.lab /etc/bind/zones/db.home.lab

# Reload without restart
sudo rndc reload
sudo rndc reload home.lab           # reload single zone
sudo rndc flush                     # clear cache
sudo rndc querylog on               # toggle query logging
sudo rndc status                    # server status

# Service management
sudo systemctl restart named
sudo systemctl status named
journalctl -u named -f              # follow logs
```

---

## 2. dnsmasq — Lightweight DNS/DHCP

Ideal for small networks, lab environments, and container hosts where a full BIND9 + Kea stack is overkill.

```bash
sudo apt install dnsmasq
sudo systemctl enable --now dnsmasq
```

<HARD-RULE>
Ubuntu 24.04 runs systemd-resolved on port 53 by default. You must disable the stub listener before dnsmasq can bind to port 53:
```bash
sudo sed -i 's/#DNSStubListener=yes/DNSStubListener=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved
sudo rm /etc/resolv.conf
echo "nameserver 127.0.0.1" | sudo tee /etc/resolv.conf
```
</HARD-RULE>

Config: `/etc/dnsmasq.conf` (or drop-ins in `/etc/dnsmasq.d/`)

```bash
# /etc/dnsmasq.d/local.conf

# Listen only on LAN interface
interface=ens18
bind-interfaces

# Upstream DNS
server=1.1.1.1
server=8.8.8.8

# Local domain
domain=home.lab
local=/home.lab/
expand-hosts

# DNS cache size (default 150)
cache-size=1000

# Local host records (instead of editing /etc/hosts)
address=/nas.home.lab/10.0.1.20
address=/printer.home.lab/10.0.1.30

# DHCP range — 10.0.1.100-200, 12h lease
dhcp-range=10.0.1.100,10.0.1.200,12h

# Static reservations
dhcp-host=aa:bb:cc:dd:ee:01,server01,10.0.1.50
dhcp-host=aa:bb:cc:dd:ee:02,server02,10.0.1.60

# DHCP options
dhcp-option=option:router,10.0.1.1
dhcp-option=option:dns-server,10.0.1.10
dhcp-option=option:domain-search,home.lab
dhcp-option=option:ntp-server,10.0.1.10

# Logging
log-queries
log-dhcp
log-facility=/var/log/dnsmasq.log
```

```bash
# Validate and restart
dnsmasq --test
sudo systemctl restart dnsmasq
```

---

## 3. Kea DHCP Server

Kea is the modern replacement for ISC DHCP, actively developed and the recommended choice on Ubuntu 24.04.

### Installation

```bash
sudo apt install kea-dhcp4-server kea-dhcp6-server kea-admin
sudo systemctl enable --now kea-dhcp4-server
```

### DHCPv4 Configuration

Config: `/etc/kea/kea-dhcp4.conf` (JSON format)

```json
{
    "Dhcp4": {
        "interfaces-config": {
            "interfaces": ["ens18"]
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases4.csv",
            "lfc-interval": 3600
        },
        "valid-lifetime": 43200,
        "renew-timer": 21600,
        "rebind-timer": 37800,
        "option-data": [
            { "name": "domain-name-servers", "data": "10.0.1.10, 1.1.1.1" },
            { "name": "domain-name", "data": "home.lab" },
            { "name": "domain-search", "data": "home.lab" },
            { "name": "ntp-servers", "data": "10.0.1.10" }
        ],
        "subnet4": [
            {
                "id": 1,
                "subnet": "10.0.1.0/24",
                "pools": [
                    { "pool": "10.0.1.100 - 10.0.1.200" }
                ],
                "option-data": [
                    { "name": "routers", "data": "10.0.1.1" }
                ],
                "reservations": [
                    {
                        "hw-address": "aa:bb:cc:dd:ee:01",
                        "ip-address": "10.0.1.50",
                        "hostname": "server01"
                    },
                    {
                        "hw-address": "aa:bb:cc:dd:ee:02",
                        "ip-address": "10.0.1.60",
                        "hostname": "server02"
                    }
                ]
            },
            {
                "id": 2,
                "subnet": "10.0.100.0/24",
                "pools": [
                    { "pool": "10.0.100.100 - 10.0.100.200" }
                ],
                "option-data": [
                    { "name": "routers", "data": "10.0.100.1" }
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

### Kea Management

```bash
# Validate config
kea-dhcp4 -t /etc/kea/kea-dhcp4.conf

# Service control
sudo systemctl restart kea-dhcp4-server
sudo systemctl status kea-dhcp4-server
journalctl -u kea-dhcp4-server -f

# View leases
cat /var/lib/kea/kea-leases4.csv

# Log directory
sudo mkdir -p /var/log/kea
sudo chown _kea:_kea /var/log/kea
```

### Kea High Availability (Hot Standby)

Add to the `Dhcp4` object in both primary and standby servers:

```json
"hooks-libraries": [
    {
        "library": "/usr/lib/x86_64-linux-gnu/kea/hooks/libdhcp_lease_cmds.so"
    },
    {
        "library": "/usr/lib/x86_64-linux-gnu/kea/hooks/libdhcp_ha.so",
        "parameters": {
            "high-availability": [{
                "this-server-name": "primary",
                "mode": "hot-standby",
                "heartbeat-delay": 10000,
                "max-response-delay": 60000,
                "max-unacked-clients": 0,
                "peers": [
                    {
                        "name": "primary",
                        "url": "http://10.0.1.10:8000/",
                        "role": "primary"
                    },
                    {
                        "name": "standby",
                        "url": "http://10.0.1.11:8000/",
                        "role": "standby"
                    }
                ]
            }]
        }
    }
]
```

---

## 4. ISC DHCP Server (Legacy)

<HARD-RULE>
ISC DHCP (isc-dhcp-server) reached end-of-life in 2022 and receives no security updates. Use Kea for all new deployments. This section exists only to assist with migration from existing installations.
</HARD-RULE>

### Minimal Legacy Config Reference

Config: `/etc/dhcp/dhcpd.conf`

```bash
sudo apt install isc-dhcp-server
# Set interface in /etc/default/isc-dhcp-server:
# INTERFACESv4="ens18"
```

```
default-lease-time 43200;
max-lease-time 86400;
authoritative;

option domain-name "home.lab";
option domain-name-servers 10.0.1.10, 1.1.1.1;

subnet 10.0.1.0 netmask 255.255.255.0 {
    range 10.0.1.100 10.0.1.200;
    option routers 10.0.1.1;

    host server01 {
        hardware ethernet aa:bb:cc:dd:ee:01;
        fixed-address 10.0.1.50;
    }
}
```

### Migration Path to Kea

1. Export current leases: `cat /var/lib/dhcp/dhcpd.leases`
2. Convert `dhcpd.conf` subnet/host declarations to Kea JSON `subnet4` and `reservations` format
3. Install Kea and configure — validate with `kea-dhcp4 -t`
4. Stop ISC DHCP, start Kea: `sudo systemctl stop isc-dhcp-server && sudo systemctl start kea-dhcp4-server`
5. Monitor `/var/log/kea/kea-dhcp4.log` for client assignments
6. Purge legacy: `sudo apt purge isc-dhcp-server`

---

## 5. NTP — Time Synchronization

### chrony (Recommended for Servers)

```bash
sudo apt install chrony
sudo systemctl enable --now chronyd
```

Config: `/etc/chrony/chrony.conf`

```bash
# Use Ubuntu NTP pool
pool ntp.ubuntu.com        iburst maxsources 4
pool 0.ubuntu.pool.ntp.org iburst maxsources 2
pool 1.ubuntu.pool.ntp.org iburst maxsources 2

# Record rate of system clock drift
driftfile /var/lib/chrony/chrony.drift

# Allow NTP clients on LAN
allow 10.0.0.0/8
allow 192.168.0.0/16

# Serve time even when not synchronized (useful for isolated LANs)
local stratum 10

# Step the clock on startup if off by more than 1 second
makestep 1.0 3

# Enable kernel time synchronization
rtcsync

# Log tracking, measurements, and statistics
logdir /var/log/chrony
log tracking measurements statistics
```

```bash
# Management commands
chronyc sources -v           # show NTP sources with details
chronyc tracking             # current sync status
chronyc clients              # list NTP clients (if serving time)
chronyc makestep             # force immediate time correction

sudo systemctl restart chronyd
```

### systemd-timesyncd (Simple Client-Only)

Already installed and active by default on Ubuntu 24.04. Suitable for machines that only need to sync time, not serve it.

```bash
# Check status
timedatectl status
timedatectl timesync-status

# Configure NTP servers: /etc/systemd/timesyncd.conf
[Time]
NTP=10.0.1.10
FallbackNTP=ntp.ubuntu.com 0.ubuntu.pool.ntp.org

# Apply
sudo systemctl restart systemd-timesyncd
```

**When to use which:** Use `chrony` on any server that provides NTP to LAN clients or requires precise time (database servers, log aggregators). Use `timesyncd` on simple workstations or VMs that just need to keep time accurate.

---

## 6. Routing, NAT, and VLANs

### IP Forwarding

<HARD-RULE>
Enabling IP forwarding turns your server into a router. Only enable this on designated gateway/router machines, never on application servers. Misconfigured forwarding with public-facing interfaces can create an open relay.
</HARD-RULE>

```bash
# Enable immediately (non-persistent)
sudo sysctl -w net.ipv4.ip_forward=1
sudo sysctl -w net.ipv6.conf.all.forwarding=1

# Persistent — /etc/sysctl.d/99-ip-forward.conf
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1

# Apply
sudo sysctl --system

# Verify
sysctl net.ipv4.ip_forward
```

### Static Routes via Netplan

```yaml
# /etc/netplan/01-static.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens18:
      addresses:
        - 10.0.1.1/24
      routes:
        - to: default
          via: 10.0.0.1
        - to: 10.0.200.0/24
          via: 10.0.1.254
          metric: 100
        - to: 172.16.0.0/16
          via: 10.0.1.253
```

```bash
sudo netplan try     # apply with 120s rollback safety
sudo netplan apply
ip route show        # verify
```

### NAT / Masquerade with nftables

For a gateway server that shares its internet connection with LAN clients.

```bash
# /etc/nftables.conf
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        iif "lo" accept
        ct state established,related accept
        ct state invalid drop
        tcp dport 22 accept                          # SSH
        udp dport { 67, 68 } accept                  # DHCP
        tcp dport 53 accept                          # DNS
        udp dport 53 accept                          # DNS
        udp dport 123 accept                         # NTP
        icmp type echo-request accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        iifname "ens19" oifname "ens18" accept       # LAN -> WAN
        ct state established,related accept           # return traffic
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}

table ip nat {
    chain postrouting {
        type nat hook postrouting priority 100;
        oifname "ens18" masquerade                   # NAT outbound on WAN
    }

    chain prerouting {
        type nat hook prerouting priority -100;
        # Port forward: external:8080 -> internal web server
        iifname "ens18" tcp dport 8080 dnat to 10.0.1.50:80
    }
}
```

```bash
sudo systemctl enable --now nftables
sudo nft list ruleset                # verify
```

### VLAN Routing Between Subnets

Gateway server with VLAN trunk on `ens18`, routing between VLAN 10, 20, and 30:

```yaml
# /etc/netplan/02-vlans.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens18:
      dhcp4: false
  vlans:
    vlan10:
      id: 10
      link: ens18
      addresses:
        - 10.0.10.1/24
    vlan20:
      id: 20
      link: ens18
      addresses:
        - 10.0.20.1/24
    vlan30:
      id: 30
      link: ens18
      addresses:
        - 10.0.30.1/24
```

With IP forwarding enabled, the server will route between all three VLANs automatically. Use nftables to restrict inter-VLAN traffic:

```bash
# Add to nftables forward chain to block VLAN 30 (IoT) from reaching VLAN 10 (servers)
nft add rule inet filter forward iifname "vlan30" oifname "vlan10" drop
```

### Policy-Based Routing Basics

Route traffic from VLAN 20 out a different WAN gateway:

```yaml
# /etc/netplan/03-policy-routing.yaml
network:
  version: 2
  ethernets:
    ens19:
      addresses:
        - 203.0.113.2/24
      routes:
        - to: default
          via: 203.0.113.1
          table: 100
      routing-policy:
        - from: 10.0.20.0/24
          table: 100
          priority: 100
```

```bash
# Verify routing tables
ip rule show
ip route show table 100
```

---

## 7. Network Troubleshooting

### DNS Diagnostics

```bash
# dig — most detailed DNS tool
dig home.lab                         # A record query
dig @10.0.1.10 home.lab              # query specific server
dig home.lab MX                      # MX records
dig home.lab ANY +noall +answer      # all record types, clean output
dig -x 10.0.1.50                     # reverse lookup (PTR)
dig home.lab +trace                  # trace delegation path
dig home.lab +short                  # just the answer
dig @10.0.1.10 home.lab AXFR        # zone transfer (test security)

# host — quick lookups
host web01.home.lab
host 10.0.1.50                       # reverse lookup

# nslookup — interactive or one-shot
nslookup web01.home.lab 10.0.1.10

# systemd-resolve integration
resolvectl query web01.home.lab
resolvectl status                    # show DNS config per interface
resolvectl statistics                # cache hit/miss stats
```

### Packet Capture with tcpdump

```bash
# Install
sudo apt install tcpdump

# Capture DNS traffic
sudo tcpdump -i ens18 port 53 -n

# Capture DHCP traffic
sudo tcpdump -i ens18 port 67 or port 68 -n -v

# Capture all traffic to/from a host
sudo tcpdump -i ens18 host 10.0.1.50 -n

# Write to file for Wireshark analysis
sudo tcpdump -i ens18 -w /tmp/capture.pcap -c 1000

# Read capture file
tcpdump -r /tmp/capture.pcap -n

# Capture with packet content (ASCII)
sudo tcpdump -i ens18 port 80 -A -s 0
```

### Socket and Connection Analysis

```bash
# ss — socket statistics (replaces netstat)
ss -tlnp                            # TCP listening sockets with PIDs
ss -ulnp                            # UDP listening sockets with PIDs
ss -tnp                             # established TCP connections
ss -s                               # summary statistics
ss -tnp state established '( dport = :443 )'   # filter by dest port

# Who is using a specific port
sudo ss -tlnp | grep :53
sudo lsof -i :53                    # alternative
```

### Routing Diagnostics

```bash
# Show routing table
ip route show
ip -6 route show

# Show which route a destination will use
ip route get 8.8.8.8
ip route get 10.0.20.5

# Show all routing tables (policy routing)
ip rule show
ip route show table all

# Show ARP / neighbor cache
ip neigh show

# Show interface details
ip addr show
ip -s link show ens18                # interface statistics (errors, drops)
```

### Path Analysis

```bash
# traceroute — trace path to destination
traceroute 8.8.8.8
traceroute -n 10.0.1.50             # skip DNS resolution (faster)
traceroute -T -p 443 example.com    # TCP traceroute to port 443

# mtr — combines ping + traceroute (live updating)
sudo apt install mtr-tiny
mtr 8.8.8.8                         # interactive mode
mtr -r -c 100 8.8.8.8               # report mode, 100 pings
mtr -r -c 50 -n 10.0.1.50           # numeric, no DNS
```

### Infrastructure Port Scanning

```bash
# Install
sudo apt install nmap

# Scan your own subnet for active hosts
nmap -sn 10.0.1.0/24

# Scan a host for open TCP ports
nmap -sT 10.0.1.50

# Service version detection
nmap -sV 10.0.1.50

# Scan specific ports
nmap -p 22,53,80,443 10.0.1.50

# UDP scan (requires root, slow)
sudo nmap -sU -p 53,67,123,161 10.0.1.50

# OS detection
sudo nmap -O 10.0.1.50
```

<HARD-RULE>
Only scan hosts and networks you own or have explicit authorization to test. Unauthorized port scanning may violate laws and policies. Always document scan authorization for audit purposes.
</HARD-RULE>

### Quick Connectivity Checks

```bash
# Ping with count
ping -c 4 10.0.1.1

# Check if a TCP port is open (no nmap needed)
timeout 3 bash -c 'echo > /dev/tcp/10.0.1.50/80' && echo "open" || echo "closed"

# curl for HTTP services
curl -I http://10.0.1.50              # headers only
curl -sv https://web01.home.lab 2>&1 | head -30  # verbose with TLS info

# Test DNS resolution explicitly
dig +short @10.0.1.10 web01.home.lab
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Editing /etc/resolv.conf directly on systems using systemd-resolved | systemd-resolved overwrites manual changes; DNS configuration reverts on next network event | Configure DNS through netplan or `resolvectl`; manage upstream DNS in systemd-resolved.conf |
| Running BIND9 as an open resolver | Becomes a DNS amplification attack vector; abused for DDoS; consumes bandwidth and resources | Restrict recursion to internal networks (`allow-recursion { trusted; };`); block external recursive queries |
| No NTP monitoring on infrastructure servers | Clock drift causes Kerberos auth failures, certificate validation errors, and log timestamp mismatches | Monitor chrony/timesyncd sync status; alert on offset > 100ms; verify NTP source availability regularly |
| Static routes everywhere instead of proper VLAN configuration | Route tables become unmaintainable at scale; topology changes require touching every server | Use VLAN interfaces via netplan; define proper gateway per VLAN; document VLAN assignments and purpose |
| Running DHCP server without IP conflict detection | Rogue DHCP servers or static IP conflicts cause intermittent connectivity; difficult to diagnose | Enable DHCP conflict detection; monitor lease table; use DHCP snooping on managed switches; reserve IPs for infrastructure |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (packages, SSH, firewall, disks) | `ubuntu-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `ubuntu-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `ubuntu-databases` |
| Docker / containers | `ubuntu-docker-host` |
| File sharing (NFS, Samba, ZFS) | `ubuntu-file-storage` |
| Prometheus, Grafana, logging | `ubuntu-monitoring` |
| NVIDIA GPU, Ollama, CUDA | `ubuntu-ollama-nvidia` |
