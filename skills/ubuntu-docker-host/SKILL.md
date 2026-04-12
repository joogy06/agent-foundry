---
name: ubuntu-docker-host
description: Use when setting up and managing Docker CE on Ubuntu 24.04 LTS — installation from official repo, storage drivers (overlay2), daemon.json configuration, networking (bridge, macvlan, host), Docker Compose V2, container logging, private registry, resource limits, rootless mode, and security best practices. Part of the ubuntu-* skill family.
---

# Docker CE on Ubuntu Server 24.04 LTS

Companion skill to `ubuntu-server-admin` (parent). For Dockerfile patterns, cross-platform quoting, and container design, see `docker-admin`.

<HARD-RULE>
Never run `docker system prune -a --volumes` without explicit user confirmation. This permanently removes all stopped containers, unused images, and named volumes — including database data.
</HARD-RULE>

<HARD-RULE>
Never expose the Docker daemon TCP socket (2375/2376) without TLS mutual auth. An unprotected socket grants root-equivalent access to the host.
</HARD-RULE>

---

## 1. Installation

```bash
# Remove distro-packaged Docker remnants
sudo apt remove -y docker.io docker-doc docker-compose podman-docker containerd runc 2>/dev/null
# Prerequisites and GPG key
sudo apt update && sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
# Add repo (Noble)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu noble stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
# Install Docker CE + plugins
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
# Post-install
sudo usermod -aG docker $USER && newgrp docker
sudo systemctl enable --now docker
docker version && docker compose version && docker run --rm hello-world
```

<HARD-RULE>
Adding a user to the `docker` group grants root-equivalent privileges. Only add trusted users. For untrusted workloads, use rootless Docker (Section 6).
</HARD-RULE>

---

## 2. daemon.json

Config: `/etc/docker/daemon.json`

```json
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5", "compress": "true" },
  "default-address-pools": [
    { "base": "172.20.0.0/16", "size": 24 },
    { "base": "172.21.0.0/16", "size": 24 }
  ],
  "dns": ["10.0.1.1", "1.1.1.1"],
  "live-restore": true,
  "userland-proxy": false,
  "default-ulimits": { "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 } },
  "metrics-addr": "127.0.0.1:9323"
}
```

Validate and apply: `sudo dockerd --validate && sudo systemctl restart docker`

| Option | Purpose |
|--------|---------|
| `log-opts` | Cap per-container logs (5 x 20 MB = 100 MB max) |
| `default-address-pools` | Custom bridge subnets — avoid corporate LAN clashes |
| `live-restore` | Containers survive daemon restarts/upgrades |
| `userland-proxy: false` | iptables/nftables forwarding — lower overhead |
| `metrics-addr` | Prometheus scrape endpoint (bind 127.0.0.1) |

**Syslog alternative:** `{ "log-driver": "syslog", "log-opts": { "syslog-address": "udp://10.0.1.20:514", "tag": "docker/{{.Name}}" } }`

**Insecure registry (lab only):** `"insecure-registries": ["registry.home.lab:5000"]`

<HARD-RULE>
Never use `insecure-registries` in production. Always configure TLS. Insecure transport exposes images and credentials to network sniffing.
</HARD-RULE>

---

## 3. Networking

**Bridge** — always create named networks (default bridge lacks DNS resolution):
```bash
docker network create --driver bridge --subnet 172.25.0.0/24 --gateway 172.25.0.1 app-net
docker run -d --name web --network app-net -p 8080:80 nginx:alpine
docker run --rm --network app-net alpine ping web   # resolves by name
```

**Macvlan** — containers get their own LAN IP, no port mapping:
```bash
docker network create -d macvlan \
  --subnet=10.0.1.0/24 --gateway=10.0.1.1 --ip-range=10.0.1.200/29 \
  -o parent=ens18 lan-net
docker run -d --name pihole --network lan-net --ip 10.0.1.200 pihole/pihole
# Host-to-macvlan shim (required for host to reach macvlan containers)
sudo ip link add macvlan-shim link ens18 type macvlan mode bridge
sudo ip addr add 10.0.1.199/32 dev macvlan-shim
sudo ip link set macvlan-shim up
sudo ip route add 10.0.1.200/29 dev macvlan-shim
```

**Host** — shares host network stack, no isolation, best throughput:
`docker run -d --network host --name monitoring prometheus/prometheus`

**Port binding:** `-p 8080:80` (all interfaces), `-p 10.0.1.50:8080:80` (specific IP), `-p 127.0.0.1:8080:80` (localhost only), `-p 53:53/udp`

<HARD-RULE>
Docker bypasses UFW/iptables by default. Published ports are network-accessible even if UFW blocks them. Bind to specific IPs or set `"iptables": false` in daemon.json and manage rules manually.
</HARD-RULE>

**IPv6:** add to daemon.json: `{ "ipv6": true, "fixed-cidr-v6": "fd00:dead:beef::/48" }`

---

## 4. Docker Compose V2

Use `docker compose` (space, not hyphen). Preferred filename: `compose.yaml`.

```yaml
services:
  app:
    image: myapp:${APP_VERSION:-latest}
    build: { context: ., dockerfile: Dockerfile }
    ports: ["8080:8080"]
    env_file: [.env]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits: { memory: 1G, cpus: "2.0" }
    restart: unless-stopped
    init: true
    volumes: [app-data:/data, ./config:/app/config:ro]
    networks: [frontend, backend]
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_DB: myapp, POSTGRES_USER: myapp, POSTGRES_PASSWORD_FILE: /run/secrets/db_password }
    secrets: [db_password]
    volumes: [pg-data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
      interval: 10s
      retries: 5
    restart: unless-stopped
    networks: [backend]
  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    restart: unless-stopped
    networks: [backend]
volumes:
  app-data:
  pg-data:
networks:
  frontend: { driver: bridge }
  backend: { driver: bridge, internal: true }
secrets:
  db_password: { file: ./secrets/db_password.txt }
```

**Profiles** — optional services excluded from default `up`:
```yaml
  debug-tools:
    image: nicolaka/netshoot
    profiles: [debug]
    network_mode: "service:app"
```
`docker compose --profile debug up -d`

**Overrides:** `compose.override.yaml` auto-loads in dev. Production: `docker compose -f compose.yaml -f compose.prod.yaml up -d`

**Env precedence** (highest first): `run -e` > shell env > `.env` > `env_file` > Dockerfile `ENV`

---

## 5. Storage

| Feature | Named Volumes | Bind Mounts |
|---------|--------------|-------------|
| Managed by Docker | Yes | No |
| Pre-populated from image | Yes | No |
| Use case | Databases, persistent data | Config files, dev source |

```bash
docker volume create mydata
docker volume inspect mydata       # path: /var/lib/docker/volumes/mydata/_data
docker volume prune                # dangling only
docker volume prune -a             # all unused
docker system df -v                # disk usage per image/container/volume
docker container prune             # stopped containers
docker image prune -a              # all unused images
docker builder prune               # build cache
```

**Moving data-root** to a larger disk — add `{ "data-root": "/mnt/docker-data" }` to daemon.json:
```bash
sudo systemctl stop docker
sudo rsync -aP /var/lib/docker/ /mnt/docker-data/
sudo systemctl start docker
```

<HARD-RULE>
When changing `data-root`, stop Docker completely before moving data. Rsync on a live Docker data directory causes corruption.
</HARD-RULE>

---

## 6. Security

### Rootless Docker
```bash
sudo apt install -y uidmap dbus-user-session
dockerd-rootless-setuptool.sh install   # run as target user, NOT root
echo 'export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock' >> ~/.bashrc
sudo loginctl enable-linger $USER       # daemon survives logout
```
Limitations: no ports <1024 (fix: `sysctl net.ipv4.ip_unprivileged_port_start=80`), no macvlan/host networking.

### User Namespace Remapping
Add `{ "userns-remap": "default" }` to daemon.json. Maps container UID 0 to unprivileged host UID via `/etc/subuid` and `/etc/subgid`.

### Container Hardening
```bash
docker run -d --name secure-app \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --cap-add NET_BIND_SERVICE \
  --security-opt=no-new-privileges:true \
  --security-opt=seccomp=/etc/docker/seccomp-default.json \
  --pids-limit 100 --memory 512m --cpus 1.0 --user 1001:1001 \
  myapp:latest
```
Compose: `read_only: true`, `tmpfs: [/tmp:size=64m]`, volumes for writable paths only.

### Content Trust and Scanning
```bash
export DOCKER_CONTENT_TRUST=1           # enforce signed images
docker scout cves myapp:latest          # built-in scanner
trivy image --severity HIGH,CRITICAL myapp:latest   # open-source scanner
```

---

## 7. Private Registry

```bash
sudo mkdir -p /opt/registry/{data,certs,auth}
# Self-signed TLS cert
openssl req -newkey rsa:4096 -nodes \
  -keyout /opt/registry/certs/registry.key \
  -x509 -days 3650 -out /opt/registry/certs/registry.crt \
  -subj "/CN=registry.home.lab" \
  -addext "subjectAltName=DNS:registry.home.lab,IP:10.0.1.50"
# Auth
docker run --rm --entrypoint htpasswd httpd:2 -Bbn admin 'S3cur3P@ss' \
  > /opt/registry/auth/htpasswd
```

```yaml
# /opt/registry/compose.yaml
services:
  registry:
    image: registry:2
    ports: ["5000:5000"]
    environment:
      REGISTRY_HTTP_TLS_CERTIFICATE: /certs/registry.crt
      REGISTRY_HTTP_TLS_KEY: /certs/registry.key
      REGISTRY_AUTH: htpasswd
      REGISTRY_AUTH_HTPASSWD_REALM: "Registry Realm"
      REGISTRY_AUTH_HTPASSWD_PATH: /auth/htpasswd
      REGISTRY_STORAGE_DELETE_ENABLED: "true"
    volumes:
      - /opt/registry/data:/var/lib/registry
      - /opt/registry/certs:/certs:ro
      - /opt/registry/auth:/auth:ro
    restart: unless-stopped
```

```bash
# Trust self-signed cert on clients
sudo cp /opt/registry/certs/registry.crt /usr/local/share/ca-certificates/registry.crt
sudo update-ca-certificates && sudo systemctl restart docker
# Push workflow
docker login registry.home.lab:5000
docker tag myapp:latest registry.home.lab:5000/myapp:v1.0
docker push registry.home.lab:5000/myapp:v1.0
# Garbage collection (stop or set read-only first)
docker exec registry bin/registry garbage-collect /etc/docker/registry/config.yml --dry-run
docker exec registry bin/registry garbage-collect /etc/docker/registry/config.yml
```

---

## 8. Logging and Monitoring

| Driver | Use Case |
|--------|----------|
| `json-file` | Default. `/var/lib/docker/containers/`. Supports `docker logs`. |
| `journald` | systemd journal: `journalctl CONTAINER_NAME=myapp` |
| `syslog` | Forward to remote syslog server |
| `fluentd` | Forward to Fluentd/Fluent Bit |
| `none` | Disable (containers logging internally) |

```bash
docker logs <container> --tail 100 -f --since "2h"
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"
```

**ctop** (interactive container TUI):
```bash
sudo wget -qO /usr/local/bin/ctop \
  https://github.com/bcicen/ctop/releases/latest/download/ctop-linux-amd64
sudo chmod +x /usr/local/bin/ctop
```

**Prometheus** metrics at `127.0.0.1:9323/metrics` (set in daemon.json). For per-container CPU/memory/network, add cAdvisor:
```yaml
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    ports: ["127.0.0.1:8080:8080"]
    volumes: [/:/rootfs:ro, /var/run:/var/run:ro, /sys:/sys:ro, /var/lib/docker:/var/lib/docker:ro]
```

---

## 9. Maintenance

**Updating Docker CE:**
```bash
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
# With live-restore enabled, containers keep running during daemon restart
```

**Automated cleanup** (systemd timer):
```ini
# /etc/systemd/system/docker-cleanup.service
[Unit]
Description=Docker resource cleanup
[Service]
Type=oneshot
ExecStart=/usr/bin/docker container prune -f --filter "until=72h"
ExecStart=/usr/bin/docker image prune -f --filter "until=168h"
ExecStart=/usr/bin/docker builder prune -f --keep-storage=5G
```
```ini
# /etc/systemd/system/docker-cleanup.timer
[Unit]
Description=Daily Docker cleanup
[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true
RandomizedDelaySec=600
[Install]
WantedBy=timers.target
```
`sudo systemctl enable --now docker-cleanup.timer`

**Volume backup:**
```bash
# Tar via helper container
docker run --rm -v myvolume:/source:ro -v /backup:/dest \
  alpine tar czf /dest/myvolume-$(date +%Y%m%d).tar.gz -C /source .
# App-level dump (preferred for databases)
docker exec postgres pg_dumpall -U myapp > /backup/pg-dump-$(date +%Y%m%d).sql
# Restore
docker volume create myvolume-restored
docker run --rm -v myvolume-restored:/target -v /backup:/src:ro \
  alpine tar xzf /src/myvolume-20260323.tar.gz -C /target
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Disk usage | `docker system df -v` |
| Networks / volumes | `docker network ls` / `docker volume ls` |
| Live stats | `docker stats` |
| Follow logs | `docker logs -f --tail 200 <container>` |
| Shell in | `docker exec -it <container> bash` |
| Validate config | `sudo dockerd --validate` |
| Scan CVEs | `docker scout cves <image>` / `trivy image <image>` |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Installing Docker from Ubuntu's default apt repo (docker.io) | Outdated version; missing features (BuildKit improvements, compose v2 plugin); inconsistent with documentation | Install from Docker's official apt repository (download.docker.com); follows Docker's release cadence |
| Adding users to docker group without understanding the security implication | Docker group membership is equivalent to root access; any group member can mount host filesystem | Understand the risk; use rootless Docker mode for development; restrict docker group to trusted users only |
| Not configuring Docker log driver limits | Default json-file driver with no rotation; container logs fill /var/lib/docker; disk full crashes all containers | Set in daemon.json: `{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}` |
| Using Docker's default bridge network for everything | No DNS resolution between containers; must use IP addresses; no network isolation between applications | Create custom bridge networks per application stack; containers resolve each other by name automatically |
| Not enabling live restore in daemon.json | Docker daemon restart kills all running containers; maintenance window required for any Docker update | Set `"live-restore": true` in daemon.json; containers continue running during daemon restart |

---

## Related Skills

| Workload | Skill |
|----------|-------|
| Core Ubuntu admin | `ubuntu-server-admin` |
| Dockerfile patterns, cross-platform | `docker-admin` |
| Web servers (Nginx, Caddy) | `ubuntu-web-servers` |
| Prometheus, Grafana | `ubuntu-monitoring` |
| GPU passthrough | `ubuntu-ollama-nvidia` |
| Core Docker concepts, BuildKit, Dockerfiles | `docker-fundamentals` |
| Docker networking deep dive | `docker-networking` |
| Volumes, storage drivers | `docker-storage` |
| Image scanning, security hardening | `docker-security` |
| CI/CD pipelines, multi-platform builds | `docker-cicd` |
| Advanced Compose patterns | `docker-compose-patterns` |
