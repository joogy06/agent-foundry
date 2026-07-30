---
name: rhel-docker-host
description: Use when setting up and managing containers on RHEL 9 (and AlmaLinux/Rocky 9) — Podman (rootless and rootful), Docker CE installation, Buildah, Skopeo, container networking (podman network, macvlan), Quadlet systemd integration, pod management, Compose with podman-compose, private registry, SELinux container contexts, and security best practices. Part of the rhel-* skill family.
family: rhel
applies_when: os_family == rhel
disambiguation: Standing up containers on RHEL — Podman rootless and rootful, Docker CE, Buildah, Skopeo, SELinux. Network topology itself is docker-networking.
---

# Container Host on RHEL 9 — Podman, Buildah, Skopeo, Docker CE

Companion skill to `rhel-server-admin` (parent). Podman is the default container runtime on RHEL 9. Docker CE is optional and requires the upstream docker-ce repo. For Dockerfile patterns and cross-platform design, see `docker-admin`.

<HARD-RULE>
Podman is the native container engine on RHEL 9. Always prefer Podman unless the user explicitly requires Docker CE. Podman is daemonless, rootless by default, and CLI-compatible with Docker.
</HARD-RULE>

<HARD-RULE>
Never run `podman system prune -a --volumes` or `docker system prune -a --volumes` without explicit user confirmation. This permanently removes all stopped containers, unused images, and named volumes — including database data.
</HARD-RULE>

<HARD-RULE>
Always use SELinux volume labels (`:Z` or `:z`) when bind-mounting host directories into containers on RHEL 9. Without them, SELinux denials will silently break container access to mounted paths.
- `:Z` — private unshared label (single container only)
- `:z` — shared label (multiple containers can access)
</HARD-RULE>

---

## 1. Podman — Installation and Rootless Setup

Podman is pre-installed on RHEL 9 minimal. Verify or install:

```bash
podman --version && podman info
sudo dnf install -y podman buildah skopeo podman-compose containernetworking-plugins
# Rootless — verify subuid/subgid ranges; if missing, add them
grep $USER /etc/subuid /etc/subgid
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER
podman system migrate
sudo loginctl enable-linger $USER   # containers survive logout
```

```bash
# Core operations
podman run -d --name web -p 8080:80 docker.io/library/nginx:alpine
podman ps -a && podman logs -f --tail 200 web && podman exec -it web /bin/sh
podman stop web && podman rm web
podman run -d --name app --memory 512m --cpus 1.5 --pids-limit 100 myapp:latest
# Volume with SELinux label (:Z = private, :z = shared)
podman run -d --name db -v /srv/pgdata:/var/lib/postgresql/data:Z \
  -e POSTGRES_PASSWORD=secret docker.io/library/postgres:16-alpine
# Named volumes — rootless: ~/.local/share/containers/storage/volumes/
podman volume create mydata && podman volume ls
```

<HARD-RULE>
In rootless mode, ports below 1024 require a sysctl change — do not default to rootful just for low ports:
```bash
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/99-unprivileged-ports.conf
```
</HARD-RULE>

<HARD-RULE>
Always use fully qualified image names (e.g., `docker.io/library/nginx:alpine`) in Podman. Unlike Docker, Podman does not default to Docker Hub — it searches registries listed in `/etc/containers/registries.conf` in order.
</HARD-RULE>

---

## 2. Podman Pods

Pods group containers sharing network/IPC/PID namespaces (like Kubernetes pods). Ports go on the pod, not individual containers.

```bash
podman pod create --name webapp -p 8080:80 -p 5432:5432
podman run -d --pod webapp --name web docker.io/library/nginx:alpine
podman run -d --pod webapp --name db -e POSTGRES_PASSWORD=secret \
  docker.io/library/postgres:16-alpine
# Containers share localhost — web can reach db at localhost:5432
podman pod ps && podman pod stop webapp && podman pod rm webapp -f
# Generate/deploy Kubernetes YAML
podman generate kube webapp > webapp.yaml
podman play kube webapp.yaml        # deploy
podman play kube webapp.yaml --down # tear down
```

---

## 3. Quadlet — Modern systemd Integration

Quadlet replaces the deprecated `podman generate systemd`. Place unit files in:
- **Rootful:** `/etc/containers/systemd/`
- **Rootless:** `~/.config/containers/systemd/`

```ini
# /etc/containers/systemd/webapp.container
[Unit]
Description=Web Application Container
After=network-online.target
[Container]
Image=docker.io/library/nginx:alpine
ContainerName=webapp
PublishPort=8080:80
Volume=/srv/webapp/html:/usr/share/nginx/html:ro,Z
Environment=TZ=America/New_York
AutoUpdate=registry
Network=app-net.network
[Service]
Restart=always
TimeoutStartSec=120
[Install]
WantedBy=multi-user.target default.target
```

```ini
# /etc/containers/systemd/myapp.pod
[Pod]
PodName=myapp
PublishPort=8080:80
PublishPort=5432:5432
```

```ini
# /etc/containers/systemd/app-net.network
[Network]
Subnet=172.25.0.0/24
Gateway=172.25.0.1
```

Reference pod from .container with `Pod=myapp.pod`, network with `Network=app-net.network`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now webapp.service
journalctl -u webapp.service -f
# Rootless: systemctl --user daemon-reload && systemctl --user enable --now webapp.service
# Verify Quadlet generation
/usr/libexec/podman/quadlet --dryrun          # rootful
/usr/libexec/podman/quadlet --user --dryrun   # rootless
# Auto-update (containers with AutoUpdate=registry)
sudo podman auto-update --dry-run
sudo podman auto-update
sudo systemctl enable --now podman-auto-update.timer
```

<HARD-RULE>
Always prefer Quadlet (.container/.pod/.network files) over `podman generate systemd` for new deployments. The legacy command is deprecated and will be removed in a future Podman release.
</HARD-RULE>

---

## 4. Buildah — Building OCI Images

Buildah builds OCI-compliant images without a daemon and without requiring a Dockerfile.

```bash
# Build from Containerfile (familiar workflow)
buildah bud -t myapp:v1 -f Containerfile .
# Equivalent: podman build -t myapp:v1 -f Containerfile .

# Build interactively (no Dockerfile needed)
ctr=$(buildah from docker.io/library/alpine:3.20)
buildah run $ctr -- apk add --no-cache python3 py3-pip
buildah copy $ctr ./app /opt/app
buildah config --workingdir /opt/app --cmd '["python3", "main.py"]' --port 8080 $ctr
buildah commit $ctr myapp:v1 && buildah rm $ctr

# Build from scratch (minimal image, no base OS)
ctr=$(buildah from scratch)
buildah copy $ctr ./mystaticbinary /app
buildah config --entrypoint '["/app"]' $ctr
buildah commit $ctr myapp:minimal && buildah rm $ctr

# Push
buildah push myapp:v1 docker://registry.home.lab:5000/myapp:v1
```

---

## 5. Skopeo — Inspect and Copy Images

Skopeo works with remote images without pulling to local storage.

```bash
skopeo inspect docker://docker.io/library/nginx:alpine
skopeo list-tags docker://docker.io/library/nginx
# Copy between registries (no local pull)
skopeo copy docker://docker.io/library/nginx:alpine \
  docker://registry.home.lab:5000/nginx:alpine
# Mirror entire repo (all tags)
skopeo sync --src docker --dest docker \
  docker.io/library/nginx registry.home.lab:5000/mirror/nginx
# Export to archive / OCI layout
skopeo copy docker://docker.io/library/alpine:3.20 docker-archive:/tmp/alpine.tar:alpine:3.20
skopeo delete docker://registry.home.lab:5000/myapp:old
# Auth stored in ${XDG_RUNTIME_DIR}/containers/auth.json
podman login docker.io && podman login registry.home.lab:5000
```

---

## 6. Docker CE — Optional Installation

Docker CE is NOT default on RHEL 9. Only install when explicitly required.

```bash
sudo dnf remove -y podman-docker runc 2>/dev/null
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
# AlmaLinux/Rocky: use centos repo instead
# sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER && newgrp docker
```

**daemon.json** (`/etc/docker/daemon.json`):
```json
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5", "compress": "true" },
  "default-address-pools": [{ "base": "172.20.0.0/16", "size": 24 }],
  "live-restore": true,
  "userland-proxy": false
}
```

**Coexistence notes:** Podman and Docker use separate storage — images are not shared. Remove `podman-docker` before installing Docker CE. Podman socket (`sudo systemctl enable --now podman.socket`) can emulate the Docker socket for tools expecting `DOCKER_HOST`.

<HARD-RULE>
Never expose the Docker daemon TCP socket (2375/2376) without TLS mutual auth. An unprotected socket grants root-equivalent access to the host. Adding a user to the `docker` group also grants root-equivalent privileges — only add trusted users.
</HARD-RULE>

---

## 7. Networking

```bash
# Named bridge network (DNS resolution by container name)
podman network create --subnet 172.25.0.0/24 --gateway 172.25.0.1 app-net
podman run -d --name web --network app-net -p 8080:80 docker.io/library/nginx:alpine
podman run -d --name api --network app-net myapi:latest
# web can reach api by name: curl http://api:8080
podman network connect app-net existing-container
podman network disconnect app-net existing-container

# Macvlan — containers get their own LAN IP, no port mapping
podman network create -d macvlan --subnet=10.0.1.0/24 --gateway=10.0.1.1 \
  --ip-range=10.0.1.200/29 -o parent=ens18 lan-net
podman run -d --name pihole --network lan-net --ip 10.0.1.200 docker.io/pihole/pihole
# Host-to-macvlan shim (required for host to reach macvlan containers)
sudo ip link add macvlan-shim link ens18 type macvlan mode bridge
sudo ip addr add 10.0.1.199/32 dev macvlan-shim && sudo ip link set macvlan-shim up
sudo ip route add 10.0.1.200/29 dev macvlan-shim

# Host networking — shares host network stack, no isolation
podman run -d --network host --name monitoring docker.io/prom/prometheus

# Port binding: -p 8080:80 (all), -p 10.0.1.50:8080:80 (specific IP), -p 127.0.0.1:8080:80 (local), -p 53:53/udp
```

```bash
# Firewall — RHEL uses firewalld, NOT ufw
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload && sudo firewall-cmd --list-all
# Rootful Podman creates nftables rules; rootless uses slirp4netns/pasta (no firewall changes)
```

<HARD-RULE>
RHEL 9 uses `firewall-cmd` (firewalld), NOT `ufw`. Always manage host firewall rules through firewalld. Verify rootful Podman nftables rules with `sudo nft list ruleset`.
</HARD-RULE>

---

## 8. Compose

```bash
# podman-compose (native)
sudo dnf install -y podman-compose
podman-compose up -d && podman-compose ps && podman-compose logs -f app
# Docker Compose via Podman socket
sudo systemctl enable --now podman.socket      # rootful
systemctl --user enable --now podman.socket     # rootless
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock
docker compose up -d
```

RHEL compose keys: use fully qualified images, add `:z`/`:Z` to bind-mount volumes, use named volumes for data (no label needed).

```yaml
# compose.yaml
services:
  app:
    image: docker.io/library/node:20-alpine
    ports: ["8080:3000"]
    volumes: [./src:/app/src:ro,z, app-data:/app/data]
    depends_on:
      postgres: { condition: service_healthy }
    restart: unless-stopped
  postgres:
    image: docker.io/library/postgres:16-alpine
    environment: { POSTGRES_DB: myapp, POSTGRES_USER: myapp, POSTGRES_PASSWORD: changeme }
    volumes: [pg-data:/var/lib/postgresql/data]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U myapp"], interval: 10s, retries: 5 }
    restart: unless-stopped
volumes: { app-data: {}, pg-data: {} }
```

---

## 9. Registry Configuration and Private Registry

### registries.conf

```toml
# /etc/containers/registries.conf
unqualified-search-registries = ["docker.io", "quay.io", "registry.home.lab:5000"]

[[registry]]
location = "registry.home.lab:5000"
insecure = false
[[registry.mirror]]
location = "mirror.home.lab:5000"
```

<HARD-RULE>
Never set `insecure = true` for a registry in production. Always configure TLS. Insecure transport exposes images and credentials to network sniffing.
</HARD-RULE>

### Deploying a Private Registry

```bash
sudo mkdir -p /opt/registry/{data,certs,auth}
openssl req -newkey rsa:4096 -nodes \
  -keyout /opt/registry/certs/registry.key \
  -x509 -days 3650 -out /opt/registry/certs/registry.crt \
  -subj "/CN=registry.home.lab" \
  -addext "subjectAltName=DNS:registry.home.lab,IP:10.0.1.50"
sudo dnf install -y httpd-tools
htpasswd -Bbn admin 'S3cur3P@ss' > /opt/registry/auth/htpasswd
sudo podman run -d --name registry -p 5000:5000 \
  -v /opt/registry/data:/var/lib/registry:Z \
  -v /opt/registry/certs:/certs:ro,Z -v /opt/registry/auth:/auth:ro,Z \
  -e REGISTRY_HTTP_TLS_CERTIFICATE=/certs/registry.crt \
  -e REGISTRY_HTTP_TLS_KEY=/certs/registry.key \
  -e REGISTRY_AUTH=htpasswd -e REGISTRY_AUTH_HTPASSWD_REALM="Registry Realm" \
  -e REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd \
  -e REGISTRY_STORAGE_DELETE_ENABLED=true docker.io/library/registry:2
# Trust cert on RHEL clients (NOT /usr/local/share/ca-certificates like Ubuntu)
sudo cp /opt/registry/certs/registry.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
podman login registry.home.lab:5000
podman tag myapp:latest registry.home.lab:5000/myapp:v1.0 && podman push registry.home.lab:5000/myapp:v1.0
```

For production, deploy as a Quadlet .container unit (Section 3 pattern).

---

## 10. Security

**Rootless (default):** Container UID 0 maps to high host UID via user namespaces. Verify: `podman unshare cat /proc/self/uid_map`.

**SELinux:** Volume labels `:Z`/`:z` auto-relabel host paths. Manual: `sudo chcon -Rt container_file_t /srv/webapp/`. Audit denials: `sudo ausearch -m AVC -ts recent`.

```bash
# Hardened container
podman run -d --name secure-app \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --cap-add NET_BIND_SERVICE \
  --security-opt=no-new-privileges:true \
  --security-opt label=type:container_t \
  --pids-limit 100 --memory 512m --cpus 1.0 --user 1001:1001 \
  myapp:latest
# Custom seccomp profile
podman run --security-opt seccomp=/path/to/custom-seccomp.json myapp
# Generate seccomp from actual syscalls
sudo dnf install -y oci-seccomp-bpf-hook
podman run --annotation io.containers.trace-syscall=of:/tmp/seccomp.json myapp
# Image signing — configure /etc/containers/policy.json
podman push --sign-by admin@example.com registry.home.lab:5000/myapp:v1
# Rootful user namespace isolation — /etc/containers/containers.conf
# [containers]
# userns = "auto"
```

---

## 11. Maintenance

```bash
podman system df -v                          # disk usage
podman container prune -f && podman image prune -f
podman image prune -a -f && podman volume prune -f
podman builder prune -f --keep-storage=5G
```

### Automated Cleanup (systemd timer)

```ini
# /etc/systemd/system/podman-cleanup.service
[Unit]
Description=Podman resource cleanup
[Service]
Type=oneshot
ExecStart=/usr/bin/podman container prune -f --filter "until=72h"
ExecStart=/usr/bin/podman image prune -f --filter "until=168h"
```

```ini
# /etc/systemd/system/podman-cleanup.timer
[Unit]
Description=Daily Podman cleanup
[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

`sudo systemctl enable --now podman-cleanup.timer`

### Backup and Updates

```bash
# Volume backup via helper container
podman run --rm -v myvolume:/source:ro -v /backup:/dest:Z \
  docker.io/library/alpine tar czf /dest/myvolume-$(date +%Y%m%d).tar.gz -C /source .
# App-level dump (preferred for databases)
podman exec postgres pg_dumpall -U myapp > /backup/pg-dump-$(date +%Y%m%d).sql
# Update container tools
sudo dnf update -y podman buildah skopeo && podman system migrate
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Disk usage | `podman system df -v` |
| Networks / volumes | `podman network ls` / `podman volume ls` |
| Live stats | `podman stats` |
| Follow logs | `podman logs -f --tail 200 <ctr>` |
| Shell in | `podman exec -it <ctr> bash` |
| Build image | `podman build -t myapp:v1 .` |
| Inspect remote | `skopeo inspect docker://docker.io/library/nginx:alpine` |
| Copy registries | `skopeo copy docker://src docker://dest` |
| K8s YAML | `podman generate kube <pod>` |
| Quadlet dry-run | `/usr/libexec/podman/quadlet --dryrun` |
| Auto-updates | `podman auto-update --dry-run` |
| SELinux denials | `sudo ausearch -m AVC -ts recent` |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Installing Docker CE from docker.io repo without removing Podman first | Package conflicts between Docker and Podman; broken container runtime; confused CLI behavior | Choose one: Podman (default RHEL) or Docker CE; remove the other cleanly; do not mix runtimes |
| Running Podman containers as root by default | Loses the key security advantage of Podman's rootless mode; container escape gives root access | Use rootless Podman (`podman --user`); root only when host resources (ports < 1024, specific devices) require it |
| Not using Quadlet for systemd service management | Manual `podman generate systemd` output drifts from container config; updates require regeneration | Use Quadlet (.container, .volume, .network files in /etc/containers/systemd/); declarative and auto-updating |
| Ignoring SELinux labels on bind mounts | SELinux denials block container access to host directories; admins disable SELinux instead of fixing labels | Use `:z` (shared) or `:Z` (private) suffix on bind mounts; or set correct SELinux context with `chcon` |
| Not configuring container log rotation | Container logs grow unbounded; /var fills up; all containers on the host stop working | Set log driver options: `--log-opt max-size=10m --log-opt max-file=3` in daemon.json or per container |

---

## Related Skills

| Workload | Skill |
|----------|-------|
| Core RHEL admin | `rhel-server-admin` |
| Dockerfile patterns, cross-platform | `docker-admin` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MariaDB, Redis) | `rhel-databases` |
| NFS, Samba, Stratis | `rhel-file-storage` |
| Prometheus, Grafana, monitoring | `rhel-monitoring` |
| Networking, VPN, load balancing | `rhel-network-infra` |
| GPU passthrough, Ollama | `rhel-ollama-nvidia` |
| Core Docker concepts, BuildKit, Dockerfiles | `docker-fundamentals` |
| Docker networking deep dive | `docker-networking` |
| Volumes, storage drivers | `docker-storage` |
| Image scanning, security hardening | `docker-security` |
| CI/CD pipelines, multi-platform builds | `docker-cicd` |
| Advanced Compose patterns | `docker-compose-patterns` |
