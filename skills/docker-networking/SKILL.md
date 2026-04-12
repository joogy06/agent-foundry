---
name: docker-networking
description: Use when configuring Docker container networking — bridge networks, overlay networks, macvlan, host networking, DNS resolution between containers, published ports, network isolation, container-to-container communication, load balancing with Docker, IPv6, custom network drivers, and network troubleshooting. Part of the docker-* skill family. OS-agnostic.
---

# Docker Networking

OS-agnostic Docker networking. For core Docker concepts, see parent skill `docker-fundamentals`. For OS-specific setup, see `ubuntu-docker-host` or `rhel-docker-host`.

<HARD-RULE>
The default bridge network does NOT provide automatic DNS resolution between containers. Containers on the default bridge can only communicate by IP address, not by name. Always create user-defined bridge networks for multi-container applications. This is the single most common Docker networking mistake.
</HARD-RULE>

<HARD-RULE>
By default, `-p 8080:80` binds to `0.0.0.0` — every interface on the host, including public-facing ones. In production, always bind to a specific IP: `-p 127.0.0.1:8080:80` for localhost-only, or `-p 10.0.0.5:8080:80` for a specific interface. Unintentionally exposing services to the internet is a critical security risk.
</HARD-RULE>

---

## 1. Network Drivers Overview

| Driver | Scope | DNS | Use Case |
|---|---|---|---|
| `bridge` (default) | Single host | No auto DNS | Isolated single-host containers (not recommended for multi-container) |
| User-defined `bridge` | Single host | Yes | Standard multi-container apps, development, production single-host |
| `host` | Single host | N/A | Maximum network performance, no port mapping overhead |
| `none` | Single host | No | Complete network isolation, security-sensitive workloads |
| `macvlan` | Single host | No | Containers need real LAN IPs, legacy app integration |
| `ipvlan` | Single host | No | Similar to macvlan but works when promiscuous mode is blocked |
| `overlay` | Multi-host | Yes | Docker Swarm services, multi-host container communication |

### Default Bridge vs User-Defined Bridge

| Feature | Default `bridge` | User-Defined Bridge |
|---|---|---|
| DNS resolution by name | No (IP only) | Yes (automatic) |
| Network aliases | No | Yes |
| Automatic isolation | No (all containers share it) | Yes (per-network) |
| Connect/disconnect live | No | Yes |
| `--link` support | Yes (legacy) | Not needed (use DNS) |
| Configurable | Limited | Full (subnet, gateway, MTU) |

```bash
# List all networks
docker network ls

# Inspect a network
docker network inspect bridge

# See which containers are on a network
docker network inspect mynet --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'
```

---

## 2. User-Defined Bridge Networks

### Creating Networks

```bash
# Basic creation
docker network create mynet

# With specific subnet and gateway
docker network create \
  --driver bridge \
  --subnet 172.20.0.0/16 \
  --gateway 172.20.0.1 \
  mynet

# With IP range (allocatable range within subnet)
docker network create \
  --driver bridge \
  --subnet 172.20.0.0/16 \
  --ip-range 172.20.10.0/24 \
  --gateway 172.20.0.1 \
  mynet

# Internal network (no external/internet access)
docker network create --internal backend

# With custom MTU and other options
docker network create \
  --driver bridge \
  --opt com.docker.network.bridge.name=br-mynet \
  --opt com.docker.network.driver.mtu=9000 \
  mynet
```

### Connecting Containers

```bash
# Run container on a specific network
docker run -d --name web --network mynet nginx:alpine

# Run with a static IP
docker run -d --name db --network mynet --ip 172.20.0.100 postgres:16-alpine

# Connect a running container to an additional network
docker network connect mynet existing-container

# Connect with a specific IP
docker network connect --ip 172.20.0.50 mynet existing-container

# Disconnect from a network
docker network disconnect mynet existing-container
```

### DNS Resolution and Network Aliases

```bash
# Containers on user-defined bridges automatically resolve each other by name
docker network create app-net
docker run -d --name api --network app-net myapi:latest
docker run -d --name web --network app-net myweb:latest

# From 'web', 'api' resolves to the api container's IP:
# curl http://api:8080/health   <-- works automatically

# Network aliases — multiple names for one container
docker run -d --name api-v2 --network app-net --network-alias api myapi:v2

# Multiple containers with the same alias = round-robin DNS (basic load balancing)
docker run -d --name api-1 --network app-net --network-alias api myapi:latest
docker run -d --name api-2 --network app-net --network-alias api myapi:latest
docker run -d --name api-3 --network app-net --network-alias api myapi:latest
# Requests to 'api' rotate across api-1, api-2, api-3
```

### Compose Networking

```yaml
# compose.yaml — Compose creates a default network automatically
# named <project>_default. All services join it.
services:
  web:
    image: nginx:alpine
    networks:
      - frontend
      - backend
  api:
    image: myapi:latest
    networks:
      backend:
        aliases:
          - api-service
  db:
    image: postgres:16-alpine
    networks:
      - backend

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true    # no external access
    ipam:
      config:
        - subnet: 172.28.0.0/16
          gateway: 172.28.0.1
```

---

## 3. Host Networking

```bash
# Container shares the host's network namespace — no port mapping needed
docker run -d --network host nginx:alpine
# Nginx is now directly on host port 80

# Check — container has no separate IP
docker inspect --format '{{.NetworkSettings.IPAddress}}' <container>
# Returns empty string — it uses the host's IP
```

### When to Use Host Networking

| Scenario | Recommendation |
|---|---|
| Maximum network performance | Use host — eliminates NAT overhead |
| Application binds to many dynamic ports | Use host — avoids mapping hundreds of ports |
| Network monitoring / packet capture | Use host — sees all host traffic |
| Standard web apps | Use bridge — isolation is more important than marginal performance |

### Limitations

- No port mapping (`-p` is ignored) — container binds directly to host ports
- No network isolation — container sees all host network interfaces
- Port conflicts with host services or other host-mode containers
- Does not work on Docker Desktop for Mac/Windows (runs inside a VM)
- Cannot connect to user-defined bridge networks simultaneously

---

## 4. Macvlan Networks

Macvlan gives each container its own MAC address and a real IP on the physical network. Other devices on the LAN can reach containers directly.

<HARD-RULE>
Macvlan requires the parent network interface to be in promiscuous mode (`ip link set eth0 promisc on`). Many cloud providers, virtual switches, and WiFi adapters block promiscuous mode. Verify support before choosing macvlan. If blocked, use ipvlan (L2 mode) instead — it shares the parent's MAC and does not require promiscuous mode.
</HARD-RULE>

### Basic Macvlan

```bash
# Enable promiscuous mode on parent interface
sudo ip link set eth0 promisc on

# Create macvlan network
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  macnet

# Run container with a LAN IP
docker run -d --name web --network macnet --ip 192.168.1.50 nginx:alpine
# Container is reachable at 192.168.1.50 from any device on the LAN
```

### 802.1q Trunk Mode (VLAN Tagging)

```bash
# Create macvlan on a VLAN-tagged sub-interface
docker network create -d macvlan \
  --subnet=10.10.20.0/24 \
  --gateway=10.10.20.1 \
  -o parent=eth0.20 \
  macvlan20

docker network create -d macvlan \
  --subnet=10.10.30.0/24 \
  --gateway=10.10.30.1 \
  -o parent=eth0.30 \
  macvlan30

# Containers on different VLANs
docker run -d --name web --network macvlan20 --ip 10.10.20.10 nginx
docker run -d --name db --network macvlan30 --ip 10.10.30.10 postgres:16
```

### Host-to-Macvlan Container Communication

The host cannot directly communicate with its own macvlan containers (by design — macvlan filters traffic between parent and sub-interfaces). Workaround:

```bash
# Create a macvlan sub-interface on the host
sudo ip link add macvlan-shim link eth0 type macvlan mode bridge
sudo ip addr add 192.168.1.200/32 dev macvlan-shim
sudo ip link set macvlan-shim up

# Add route to container subnet via the shim
sudo ip route add 192.168.1.50/32 dev macvlan-shim
```

### Ipvlan (Alternative)

```bash
# L2 mode — like macvlan but shares parent MAC (no promiscuous mode needed)
docker network create -d ipvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  -o ipvlan_mode=l2 \
  ipvlan-net

# L3 mode — routing-based, no broadcast, better for large-scale
docker network create -d ipvlan \
  --subnet=10.10.0.0/24 \
  -o parent=eth0 \
  -o ipvlan_mode=l3 \
  ipvlan-l3
```

---

## 5. Overlay Networks

Overlay networks span multiple Docker hosts using VXLAN encapsulation. Requires Docker Swarm or an external key-value store.

### Swarm Overlay

```bash
# Initialize Swarm (required for overlay)
docker swarm init --advertise-addr 10.0.0.1

# Create overlay network
docker network create -d overlay myoverlay

# Create service on overlay
docker service create --name web --network myoverlay --replicas 3 nginx:alpine

# Encrypted overlay (data plane encryption — AES-GCM)
docker network create -d overlay --opt encrypted myoverlay-enc
```

### Attachable Overlay (Standalone Containers)

```bash
# By default, overlay networks are only for Swarm services.
# --attachable allows standalone containers to join.
docker network create -d overlay --attachable shared-overlay

# Standalone container joins the overlay
docker run -d --name standalone-app --network shared-overlay myapp:latest
```

### Overlay with Custom Subnet

```bash
docker network create -d overlay \
  --subnet=10.100.0.0/16 \
  --gateway=10.100.0.1 \
  --opt com.docker.network.driver.mtu=1450 \
  production-overlay
```

### Ingress Network

```bash
# The default 'ingress' overlay handles Swarm routing mesh.
# Published ports on any node route to the correct container.
docker service create --name web -p 80:80 --replicas 3 nginx:alpine
# Port 80 on ANY Swarm node reaches one of the 3 replicas.

# Bypass routing mesh (only listen on nodes running the task)
docker service create --name web \
  --publish mode=host,target=80,published=80 \
  --mode global \
  nginx:alpine
```

---

## 6. DNS and Service Discovery

### Embedded DNS Server

Docker runs a built-in DNS server at `127.0.0.11` for all user-defined networks.

```bash
# Check DNS config inside a container
docker exec mycontainer cat /etc/resolv.conf
# nameserver 127.0.0.11
# options ndots:0

# Test name resolution
docker exec mycontainer nslookup api
docker exec mycontainer getent hosts api
```

### DNS Resolution Rules

| What Resolves | Where | How |
|---|---|---|
| Container name | Same user-defined network | Automatic |
| Network alias | Same user-defined network | Automatic |
| Service name | Swarm overlay | Automatic (VIP or DNSRR) |
| Container name | Default bridge | Does NOT resolve |
| External hostnames | All networks | Forwarded to host DNS |

### Custom DNS Configuration

```bash
# Set custom DNS servers for a container
docker run -d --name web \
  --dns 8.8.8.8 \
  --dns 8.8.4.4 \
  nginx:alpine

# Set DNS search domain
docker run -d --name web \
  --dns-search example.com \
  nginx:alpine
# Allows resolving 'api' as 'api.example.com'

# Set custom hostname
docker run -d --name web \
  --hostname web.example.com \
  nginx:alpine

# Add /etc/hosts entries
docker run -d --name web \
  --add-host db:10.0.0.5 \
  --add-host cache:10.0.0.6 \
  nginx:alpine

# host-gateway — resolve to host's IP (Docker 20.10+)
docker run -d --name web \
  --add-host host.docker.internal:host-gateway \
  nginx:alpine
```

### Daemon-Level DNS Config

```json
// /etc/docker/daemon.json
{
  "dns": ["8.8.8.8", "8.8.4.4"],
  "dns-search": ["example.com"],
  "dns-opts": ["timeout:2", "attempts:3"]
}
```

### Swarm Service Discovery Modes

```bash
# VIP mode (default) — single virtual IP, Docker load-balances
docker service create --name api \
  --endpoint-mode vip \
  --replicas 3 \
  myapi:latest
# 'api' resolves to one VIP; Docker handles round-robin behind it

# DNSRR mode — DNS returns all task IPs, client picks
docker service create --name api \
  --endpoint-mode dnsrr \
  --replicas 3 \
  myapi:latest
# 'api' resolves to 3 IPs; client or external LB picks
```

---

## 7. Port Publishing

### Basic Port Mapping

```bash
# Map host port 8080 to container port 80
docker run -d -p 8080:80 nginx:alpine

# Map to localhost only (not exposed externally)
docker run -d -p 127.0.0.1:8080:80 nginx:alpine

# Map to specific host interface
docker run -d -p 10.0.0.5:8080:80 nginx:alpine

# Container port only (random host port assigned)
docker run -d -p 80 nginx:alpine

# Check assigned port
docker port <container>
```

### UDP and Protocol-Specific

```bash
# UDP port
docker run -d -p 5514:514/udp syslog-ng

# TCP and UDP on same port
docker run -d -p 53:53/tcp -p 53:53/udp bind9

# SCTP (Docker 20.10+)
docker run -d -p 3868:3868/sctp diameter-server
```

### Port Ranges

```bash
# Map a range of ports
docker run -d -p 8000-8010:8000-8010 myapp

# Publish all EXPOSEd ports (random host ports)
docker run -d --publish-all myapp
docker run -d -P myapp    # shorthand
```

### Compose Port Syntax

```yaml
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"                    # host:container
      - "443:443"
      - "127.0.0.1:8080:80"       # localhost only
      - "9090-9095:9090-9095"      # range
      - "514:514/udp"              # UDP
      - target: 80                 # long syntax
        published: 8080
        protocol: tcp
        mode: host                 # Swarm: bypass routing mesh
```

### Default Bind Address

```json
// /etc/docker/daemon.json — change default bind from 0.0.0.0
{
  "ip": "127.0.0.1"
}
// Now -p 8080:80 binds to 127.0.0.1:8080 by default
```

---

## 8. Network Isolation

### Internal Networks

```bash
# No outbound internet access — containers can only talk to each other
docker network create --internal isolated-net

docker run -d --name db --network isolated-net postgres:16-alpine
docker run -d --name cache --network isolated-net redis:7-alpine
# db and cache can reach each other, but neither can reach the internet
```

### Network Segmentation Pattern (Frontend / Backend)

```yaml
# compose.yaml — classic three-tier isolation
services:
  proxy:
    image: nginx:alpine
    ports:
      - "80:80"
    networks:
      - frontend

  api:
    image: myapi:latest
    networks:
      - frontend      # reachable by proxy
      - backend        # can reach db

  db:
    image: postgres:16-alpine
    networks:
      - backend        # only reachable by api

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true     # no internet access for db
```

**Result:** `proxy` cannot reach `db` directly. `api` bridges the two networks. `db` has no internet access.

### Inter-Container Communication (ICC)

```json
// /etc/docker/daemon.json — disable ICC on default bridge
{
  "icc": false
}
// Containers on default bridge cannot communicate unless explicitly --link'd
// User-defined networks are unaffected (use network isolation instead)
```

### iptables and Docker

```bash
# Docker manages iptables rules automatically. Key chains:
# DOCKER-USER — insert custom rules here (survives Docker restarts)
# DOCKER — managed by Docker (do not modify)
# DOCKER-ISOLATION-STAGE-1/2 — network isolation

# Block external access to a published port (except from trusted IP)
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 \
  ! -s 10.0.0.0/8 -j DROP

# Block container-to-container across networks
sudo iptables -I DOCKER-USER -i br-abc123 -o br-def456 -j DROP

# Allow established/related connections
sudo iptables -I DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Persist rules
sudo iptables-save > /etc/iptables/rules.v4
```

### Disable Docker's iptables Management

```json
// /etc/docker/daemon.json — NOT recommended unless using external firewall
{
  "iptables": false
}
// You must then manually configure all NAT and forwarding rules
```

---

## 9. Container-to-Container Communication

### Same Network (By Name)

```bash
# Containers on the same user-defined network resolve each other by name
docker network create app-net
docker run -d --name api --network app-net myapi:latest
docker run -d --name web --network app-net myweb:latest

# From web container:
docker exec web curl http://api:8080/health    # resolves 'api' via DNS
docker exec web ping api                        # also works
```

### Cross-Network Communication

```bash
# Container on two networks can bridge communication
docker network create frontend
docker network create backend

docker run -d --name api --network frontend myapi:latest
docker network connect backend api
# 'api' is now on both frontend and backend

docker run -d --name web --network frontend myweb:latest
docker run -d --name db --network backend postgres:16-alpine

# web -> api (via frontend) -> db (via backend)
# web cannot reach db directly
```

### Link (Legacy — Do Not Use)

```bash
# --link is deprecated. Do NOT use in new projects.
# docker run --link db:database myapp    # legacy
# Instead, use user-defined networks (automatic DNS, no ordering dependency)
```

### Container-to-Host Communication

```bash
# From a container, reach the host machine
# Docker Desktop: host.docker.internal (built-in)
# Linux Docker Engine 20.10+:
docker run --add-host host.docker.internal:host-gateway myapp

# Or use the docker0 bridge gateway IP (usually 172.17.0.1)
docker exec mycontainer ip route | grep default
```

---

## 10. IPv6

### Enable IPv6

```json
// /etc/docker/daemon.json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00::/80",
  "ip6tables": true,
  "experimental": true
}
```

```bash
# Restart Docker after editing daemon.json
sudo systemctl restart docker
```

### Dual-Stack User-Defined Network

```bash
# Create a dual-stack network
docker network create \
  --ipv6 \
  --subnet 172.20.0.0/16 \
  --subnet fd00:dead:beef::/48 \
  dualstack-net

# Run container — gets both IPv4 and IPv6 addresses
docker run -d --name web --network dualstack-net nginx:alpine

# Verify
docker inspect web --format '{{range .NetworkSettings.Networks}}IPv4: {{.IPAddress}} IPv6: {{.GlobalIPv6Address}}{{end}}'
```

### IPv6 Port Publishing

```bash
# Publish on IPv6
docker run -d -p "[::1]:8080:80" nginx:alpine        # IPv6 localhost only
docker run -d -p "[::]:8080:80" nginx:alpine          # all IPv6 interfaces
```

### Compose IPv6

```yaml
networks:
  dualstack:
    enable_ipv6: true
    ipam:
      config:
        - subnet: 172.20.0.0/16
        - subnet: fd00:dead:beef::/48
```

---

## 11. Network Troubleshooting

### Inspecting Networks and Container IPs

```bash
# List all networks
docker network ls

# Detailed network info (connected containers, subnet, gateway)
docker network inspect mynet

# Get container's IP address
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container>

# Get all network details for a container
docker inspect -f '{{json .NetworkSettings.Networks}}' <container> | jq

# Which networks is a container on?
docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' <container>

# List containers on a specific network
docker network inspect mynet -f '{{range .Containers}}{{.Name}}: {{.IPv4Address}}{{"\n"}}{{end}}'
```

### DNS Debugging

```bash
# Check resolv.conf inside container
docker exec <container> cat /etc/resolv.conf

# Test name resolution
docker exec <container> nslookup api
docker exec <container> getent hosts api
docker exec <container> dig api    # if dig is installed

# Check /etc/hosts
docker exec <container> cat /etc/hosts

# Verify embedded DNS is working
docker exec <container> nslookup google.com 127.0.0.11

# Common DNS issue: wrong network
docker exec <container> nslookup other-container
# Fails? Check they are on the same user-defined network.
```

### Connectivity Testing

```bash
# Ping between containers
docker exec web ping -c 3 api

# Test TCP connectivity
docker exec web nc -zv api 8080

# HTTP test
docker exec web curl -s -o /dev/null -w "%{http_code}" http://api:8080/health

# Test from host to container
curl http://localhost:8080/health

# Check published port mapping
docker port <container>
```

### Packet Capture (tcpdump)

```bash
# Install tcpdump in a running container (if not present)
docker exec -u root <container> apt-get update && apt-get install -y tcpdump
docker exec -u root <container> apk add tcpdump     # Alpine

# Capture traffic
docker exec <container> tcpdump -i eth0 -n port 80

# Capture and save to host
docker exec <container> tcpdump -i eth0 -w - port 80 > capture.pcap
```

### Netshoot Sidecar (Recommended)

The `nicolaka/netshoot` image includes every network debugging tool — use it as a sidecar without modifying your containers.

```bash
# Attach to a container's network namespace
docker run -it --rm \
  --net container:<target-container> \
  nicolaka/netshoot

# Inside netshoot, you now have:
# tcpdump, curl, dig, nslookup, nmap, iperf3, mtr,
# netstat, ss, ip, iftop, drill, traceroute, and more

# Attach to a container's network AND PID namespace
docker run -it --rm \
  --net container:<target-container> \
  --pid container:<target-container> \
  nicolaka/netshoot

# Attach to host network
docker run -it --rm --net host nicolaka/netshoot

# Capture traffic on a specific network
docker run -it --rm --net mynet nicolaka/netshoot tcpdump -i eth0
```

### iptables Debugging

```bash
# View Docker-managed iptables rules
sudo iptables -L -n -v
sudo iptables -t nat -L -n -v

# Check DOCKER-USER chain (custom rules)
sudo iptables -L DOCKER-USER -n -v

# Check network isolation rules
sudo iptables -L DOCKER-ISOLATION-STAGE-1 -n -v

# Watch rule hit counters in real-time
watch -n 1 'sudo iptables -L DOCKER-USER -n -v'
```

### Common Issues and Fixes

| Problem | Cause | Fix |
|---|---|---|
| Container can't resolve another by name | On default bridge network | Use a user-defined bridge network |
| `curl: (6) Could not resolve host` | Containers on different networks | Connect both to the same network |
| Port published but not reachable | Firewall blocking on host | Check `ufw`/`firewalld`/`iptables` rules |
| Port published but wrong interface | Bound to 0.0.0.0, expected specific IP | Use `-p 10.0.0.5:8080:80` |
| Container can't reach internet | On `--internal` network | Intended. Move to non-internal network if access needed |
| Container can't reach host services | No route to host IP | Use `--add-host host.docker.internal:host-gateway` |
| Macvlan container unreachable from host | Macvlan design (host-to-own-macvlan blocked) | Create macvlan shim interface on host (see section 4) |
| DNS resolution slow (5s delay) | IPv6 DNS query failing, falling back to IPv4 | Set `--dns-opt single-request-reopen` or fix IPv6 config |
| Overlay network not working | Swarm not initialized or ports blocked | Init Swarm; open TCP 2377, TCP/UDP 7946, UDP 4789 |
| Containers on same network can't communicate | `icc=false` in daemon.json | Set `icc: true` or use user-defined networks (unaffected) |

### Network Performance Testing

```bash
# iperf3 between containers
docker run -d --name iperf-server --network mynet networkstatic/iperf3 -s
docker run -it --rm --network mynet networkstatic/iperf3 -c iperf-server

# Measure latency
docker exec web ping -c 100 api | tail -1
# rtt min/avg/max/mdev = 0.030/0.045/0.120/0.015 ms

# Compare bridge vs host network performance
docker run -it --rm --network bridge networkstatic/iperf3 -c <host-ip>
docker run -it --rm --network host networkstatic/iperf3 -c <host-ip>
```

---

## Quick Reference: Network Create Options

```bash
docker network create [OPTIONS] NETWORK

  --driver, -d        Driver (bridge, overlay, macvlan, ipvlan, none)
  --subnet            Subnet in CIDR format (e.g., 172.20.0.0/16)
  --ip-range          Allocatable IP range within subnet
  --gateway           Gateway for the subnet
  --ipv6              Enable IPv6
  --internal          No external connectivity
  --attachable        Allow standalone containers (overlay only)
  --opt, -o           Driver-specific options
  --label             Metadata labels
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using the default bridge network for multi-container apps | No DNS resolution between containers; must use IP addresses; no network isolation | Create custom bridge networks; containers resolve each other by service name automatically |
| Publishing all ports to host with `-p 0.0.0.0:port:port` | Exposes services to all network interfaces including public; bypasses host firewall on some setups | Bind to specific interface: `-p 127.0.0.1:port:port` for local-only; use reverse proxy for external access |
| Using host networking mode for everything | No network isolation; port conflicts between containers; container can access all host services | Use host mode only when performance-critical (raw socket, multicast); default to bridge networks |
| Not creating network aliases for service discovery | Containers reference each other by container name which changes; refactoring breaks connectivity | Use `--network-alias` or Compose service names for stable DNS; decouple container names from service identity |
| Hardcoding container IP addresses | Docker assigns IPs dynamically; IPs change on restart; breaks after any container recreation | Use DNS-based service discovery; never reference container IPs in configuration |

---

## Related Skills

| Topic | Skill |
|---|---|
| Core Docker concepts, CLI, Dockerfile | `docker-fundamentals` |
| Compose, cross-platform, AD mapping | `docker-admin` |
| Volumes, bind mounts, storage drivers | `docker-storage` |
| Image scanning, rootless, CIS benchmark | `docker-security` |
| CI/CD, multi-platform builds, registries | `docker-cicd` |
| Advanced Compose patterns | `docker-compose-patterns` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |
