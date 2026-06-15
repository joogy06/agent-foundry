---
name: docker-security
description: Use when hardening Docker deployments — image scanning (Trivy, Scout, Snyk), rootless Docker, user namespaces, seccomp profiles, AppArmor/SELinux integration, image signing (Sigstore cosign, Notation — Docker Content Trust retired 2025), secrets management, read-only containers, Linux capability dropping, CIS Docker Benchmark, supply chain security, and runtime security monitoring. Part of the docker-* skill family. OS-agnostic.
---

# Docker Security

OS-agnostic Docker security hardening. For core Docker concepts and Dockerfile patterns, see `docker-fundamentals`. For OS-specific host hardening, see `ubuntu-docker-host` or `rhel-docker-host`.

<HARD-RULE>
Never run the Docker daemon with `--privileged` by default. The `--privileged` flag disables all security mechanisms (seccomp, AppArmor, capability dropping) and gives the container full access to the host. Use granular `--cap-add` for specific capabilities instead.
</HARD-RULE>

<HARD-RULE>
Never expose the Docker socket (`/var/run/docker.sock`) without TLS authentication. An unprotected socket grants root-equivalent access to the host. If remote API access is required, configure TLS mutual authentication with client certificates.
</HARD-RULE>

<HARD-RULE>
Secrets passed as environment variables are visible in `docker inspect`, `docker exec env`, `/proc/*/environ`, and image history if set during build. Use Docker secrets (Swarm), BuildKit secret mounts, or external vault integration instead.
</HARD-RULE>

---

## 1. Image Security

### Scanning with Trivy

```bash
# Install Trivy (universal)
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

# Scan a local image
trivy image myapp:latest

# Scan with severity filter
trivy image --severity HIGH,CRITICAL myapp:latest

# Scan and fail CI if critical vulnerabilities found
trivy image --exit-code 1 --severity CRITICAL myapp:latest

# Scan a Dockerfile for misconfigurations
trivy config Dockerfile

# Scan filesystem (source code dependencies)
trivy fs --scanners vuln,secret,misconfig .

# Generate JSON report
trivy image --format json --output report.json myapp:latest

# Ignore unfixed vulnerabilities
trivy image --ignore-unfixed myapp:latest

# Scan with SBOM output
trivy image --format spdx-json --output sbom.json myapp:latest
```

### Docker Scout

```bash
# Enable Docker Scout (Docker Desktop or CLI plugin)
docker scout quickview myapp:latest

# Full CVE analysis
docker scout cves myapp:latest

# Compare two image versions
docker scout compare --to myapp:v1.0.0 myapp:v1.1.0

# Recommendations for base image updates
docker scout recommendations myapp:latest

# SBOM generation
docker scout sbom myapp:latest
```

### Snyk Container Scanning

```bash
# Authenticate
snyk auth

# Scan image
snyk container test myapp:latest

# Scan and monitor (continuous tracking)
snyk container monitor myapp:latest

# Scan with severity threshold
snyk container test --severity-threshold=high myapp:latest

# Scan Dockerfile for best practices
snyk container test --file=Dockerfile myapp:latest
```

### Choosing Secure Base Images

```dockerfile
# BEST: Distroless — no shell, no package manager, minimal attack surface
FROM gcr.io/distroless/static-debian12        # Go/Rust static binaries
FROM gcr.io/distroless/base-debian12          # C/C++ with glibc
FROM gcr.io/distroless/java21-debian12        # Java apps
FROM gcr.io/distroless/nodejs22-debian12      # Node.js apps
FROM gcr.io/distroless/python3-debian12       # Python apps

# GOOD: Alpine — small (~5MB), uses musl libc
FROM node:22-alpine
FROM python:3.12-alpine

# ACCEPTABLE: Slim — Debian with non-essential packages removed
FROM node:22-slim
FROM python:3.12-slim

# AVOID: Full images — large, many unnecessary packages
# FROM node:22        # ~350MB more attack surface
# FROM ubuntu:24.04   # general-purpose, not optimized for containers
```

### Pinning Image Digests

```dockerfile
# BAD: Tags are mutable — "latest" or even "1.27" can change underneath you
FROM nginx:1.27-alpine

# GOOD: Pin to digest for reproducible, tamper-proof builds
FROM nginx:1.27-alpine@sha256:a5127daff3d6f4a3ed1db3...

# Find digest
# docker inspect --format='{{index .RepoDigests 0}}' nginx:1.27-alpine
# docker pull nginx:1.27-alpine && docker images --digests nginx
```

### SBOM Generation and Provenance

```bash
# Generate SBOM with Trivy
trivy image --format spdx-json --output sbom.spdx.json myapp:latest
trivy image --format cyclonedx --output sbom.cdx.json myapp:latest

# Generate SBOM with syft
syft myapp:latest -o spdx-json > sbom.spdx.json
syft myapp:latest -o cyclonedx-json > sbom.cdx.json

# Build with provenance attestation (BuildKit)
docker buildx build --provenance=true --sbom=true -t myapp:latest .

# Inspect attestations
docker buildx imagetools inspect myapp:latest --format '{{json .Provenance}}'
docker buildx imagetools inspect myapp:latest --format '{{json .SBOM}}'
```

---

## 2. Image Signing

**Current guidance (verified 2026-06-10):** sign and verify images with **Sigstore cosign** (keyless or key-based) or **Notation** (Notary Project / Notary v2), and pin base images by digest. **Docker Content Trust (DCT) is RETIRED** — Docker announced its retirement in 2025; see the legacy reference at the end of this section for the timeline.

<!-- FRESHNESS:v1
anchors:
  - kind: status_snapshot
    subject: image-signing-landscape
    verified_against: "DCT retired (DOI certs expiring since 2025-08, no new registries since 2025-09-30, data deletion 2028-03-31); cosign and Notation are the recommended replacements"
    verified_on: "2026-06-10"
  - kind: retirement
    subject: docker-content-trust
    retire_on: "2028-03-31"
volatility: medium
-->

### cosign (Sigstore) — primary recommendation

```bash
# Install cosign
go install github.com/sigstore/cosign/v2/cmd/cosign@latest
# Or download a release binary: https://github.com/sigstore/cosign/releases

# ALWAYS sign by digest, not tag — tags are mutable
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' myregistry.example.com/myapp:v1.0.0)

# Sign image (keyless — uses your OIDC identity, records to the Rekor transparency log)
cosign sign "$DIGEST"

# Sign image with a key pair (air-gapped / no-OIDC environments)
cosign generate-key-pair
cosign sign --key cosign.key "$DIGEST"

# Verify a key-based signature
cosign verify --key cosign.pub myregistry.example.com/myapp:v1.0.0

# Verify a keyless signature (pin BOTH identity and issuer)
cosign verify --certificate-identity user@example.com \
  --certificate-oidc-issuer https://accounts.google.com \
  myregistry.example.com/myapp:v1.0.0

# Keyless in CI (e.g., GitHub Actions OIDC) — verify the workflow identity
cosign verify \
  --certificate-identity-regexp '^https://github.com/myorg/myapp/\.github/workflows/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  myregistry.example.com/myapp:v1.0.0
```

### Notation (Notary Project / Notary v2)

```bash
# Install notation — see https://notaryproject.dev for current releases
# Generate a test key + self-signed cert (production: use a CA-issued cert
# or a KMS plugin — Azure Key Vault, AWS Signer, HashiCorp Vault)
notation cert generate-test --default "myorg.example.com"

# Sign (by digest)
notation sign registry.example.com/myapp@sha256:abc123...

# List signatures on an artifact
notation ls registry.example.com/myapp@sha256:abc123...

# Configure a trust policy, then verify
notation policy import trustpolicy.json
notation verify registry.example.com/myapp@sha256:abc123...
```

Notation is spec-driven (OCI signatures attached in the registry), supports multiple signatures per artifact, and integrates with enterprise PKI/KMS — it is the natural DCT successor for organizations with existing certificate infrastructure. cosign keyless is the lower-friction choice for OIDC-centric (CI-driven) workflows.

### Docker Content Trust (RETIRED — legacy reference)

> **RETIRED.** Docker announced the retirement of Docker Content Trust in 2025 (announced 2025; verify current status):
>
> - **2025-08-08** — the oldest Docker Official Image (DOI) DCT signing certificates began expiring. With `DOCKER_CONTENT_TRUST=1` set, DOI pulls fail; `docker trust inspect` also fails for DOI.
> - **2025-09-30** — DCT can no longer be enabled on new registries.
> - **2028-03-31** — all DCT trust data will be permanently deleted and the feature removed.
>
> Upstream **Notary v1 is unmaintained**, and fewer than 0.05% of Docker Hub pulls used DCT. Docker's official recommendation is to migrate to **Sigstore cosign or Notation** (above). Do NOT set `DOCKER_CONTENT_TRUST=1` in new setups — and **unset it where present** to avoid pull failures.

The commands below are retained ONLY for auditing/decommissioning legacy DCT estates (e.g., a private registry still running Notary v1):

```bash
# Find lingering DCT enablement (remove it — causes pull failures since 2025-08)
env | grep DOCKER_CONTENT_TRUST
unset DOCKER_CONTENT_TRUST

# Inspect remaining trust data on a legacy private registry
docker trust inspect --pretty registry.example.com/myapp

# Inventory local signing keys before key destruction
docker trust key list

# Revoke trust data for a tag during decommissioning
docker trust revoke registry.example.com/myapp:v1.0.0
```

---

## 3. Rootless Docker

```bash
# Install rootless Docker (run as non-root user, NOT as root)
dockerd-rootless-setuptool.sh install

# Verify rootless mode
docker info --format '{{.SecurityOptions}}'
# Should include "rootless"

# Start/stop rootless daemon
systemctl --user start docker
systemctl --user stop docker
systemctl --user enable docker    # auto-start on login

# Enable lingering (keep services running after logout)
sudo loginctl enable-linger $(whoami)
```

### Rootless Configuration

```bash
# Rootless Docker stores data in user home
# Default: ~/.local/share/docker

# Set custom data root
mkdir -p ~/.config/docker
cat > ~/.config/docker/daemon.json <<'EOF'
{
  "data-root": "/data/docker-rootless"
}
EOF
```

### Rootless Limitations

| Feature | Rootless Support | Workaround |
|---|---|---|
| Binding ports < 1024 | No (by default) | `sysctl net.ipv4.ip_unprivileged_port_start=0` or use `slirp4netns` port driver |
| `--net=host` | Limited | Use `slirp4netns` (default) or `pasta` |
| AppArmor | No | Use rootless + user namespaces instead |
| Overlay network (Swarm) | No | Use alternative orchestration |
| cgroup v1 resource limits | No | Migrate to cgroup v2 |
| Ping | No (by default) | `sysctl net.ipv4.ping_group_range="0 2147483647"` |
| NFS/FUSE mounts in containers | Limited | Bind mount from host |

### When to Use Rootless

- **Use rootless** for development environments, CI runners, multi-tenant hosts, and anywhere the daemon itself should not run as root.
- **Use rootful with hardening** for production workloads needing privileged ports, overlay networking, or AppArmor/SELinux enforcement.

---

## 4. User Namespaces

User namespaces remap container UID/GID ranges so that root (UID 0) inside the container maps to an unprivileged user on the host.

### Enable userns-remap

```bash
# Create subordinate UID/GID ranges
sudo usermod --add-subuids 100000-165535 dockremap
sudo usermod --add-subgids 100000-165535 dockremap

# Or manually edit
# /etc/subuid: dockremap:100000:65536
# /etc/subgid: dockremap:100000:65536

# Configure daemon
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "userns-remap": "default"
}
EOF

# "default" creates a dockremap user automatically
# Or specify a user: "userns-remap": "myuser"

# Restart Docker
sudo systemctl restart docker

# Verify — root in container should map to high UID on host
docker run --rm alpine id
# uid=0(root) gid=0(root) — but host sees UID 100000
```

### Volume Permission Implications

```bash
# With userns-remap, container UID 0 maps to host UID 100000
# Volumes must be owned by the remapped UID on the host

# Example: container writes as UID 1000 -> host UID 101000
sudo chown -R 101000:101000 /data/myapp

# To find the mapped UID:
# Container UID + subordinate UID start = host UID
# 1000 + 100000 = 101000

# Disable userns-remap per container (requires daemon-level setting)
docker run --userns=host myapp    # runs without remapping
```

---

## 5. Container Hardening

### Non-Root USER in Dockerfile

```dockerfile
# Create user and group
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Own application files
COPY --chown=appuser:appgroup . /app

# Switch to non-root user (do this LAST, after all root-required operations)
USER appuser
```

### Read-Only Root Filesystem

```bash
# Run with read-only filesystem
docker run -d --read-only myapp

# Containers often need tmpfs for temporary files
docker run -d --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --tmpfs /run:rw,noexec,nosuid \
  myapp

# With writable volume for data
docker run -d --read-only \
  --tmpfs /tmp \
  -v appdata:/app/data \
  myapp
```

### Dropping Capabilities

```bash
# Drop ALL capabilities, then add only what is needed
docker run -d \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  myapp

# Common capabilities to add back selectively:
#   NET_BIND_SERVICE  — bind ports < 1024
#   CHOWN             — change file ownership
#   SETUID/SETGID     — change process UID/GID
#   DAC_OVERRIDE      — bypass file permission checks (avoid if possible)
#   SYS_PTRACE        — needed for debugging tools (never in production)

# List current container capabilities
docker exec <container> cat /proc/1/status | grep -i cap

# Decode capability hex
capsh --decode=00000000a80425fb
```

### No-New-Privileges

```bash
# Prevent privilege escalation via setuid/setgid binaries
docker run -d --security-opt=no-new-privileges myapp

# This blocks:
#   - setuid binaries (su, sudo, ping)
#   - setgid binaries
#   - Any process from gaining more privileges than its parent
```

### Disable Inter-Container Communication

```bash
# Default: containers on the same bridge can communicate
# Disable at daemon level
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "icc": false
}
EOF
sudo systemctl restart docker

# With icc=false, containers must use explicit --link or user-defined networks
# User-defined networks provide DNS-based discovery and automatic isolation
```

### Combined Hardened Run

```bash
docker run -d \
  --name secure-app \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --security-opt=no-new-privileges \
  --security-opt=apparmor=docker-default \
  --memory=512m \
  --cpus=1 \
  --pids-limit=100 \
  --user 1000:1000 \
  --restart=unless-stopped \
  --health-cmd="curl -f http://localhost:8080/health || exit 1" \
  --health-interval=30s \
  myapp:v1.0.0@sha256:abc123...
```

---

## 6. Seccomp Profiles

Seccomp (Secure Computing) filters restrict which Linux syscalls a container can make.

### Default Profile

```bash
# Docker applies a default seccomp profile that blocks ~44 dangerous syscalls
# including: mount, reboot, clock_settime, init_module, delete_module, etc.

# Verify seccomp is active
docker info --format '{{.SecurityOptions}}'

# Run with default profile (explicit)
docker run --security-opt seccomp=unconfined myapp    # DANGEROUS: disables seccomp
docker run --security-opt seccomp=default myapp       # explicit default (Docker 20.10+)
```

### Custom Seccomp Profile

```bash
# Generate default profile as starting point
docker run --rm -it alpine cat /proc/1/status | grep Seccomp

# Create custom profile
cat > seccomp-strict.json <<'PROFILE'
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "defaultErrnoRet": 1,
  "architectures": [
    "SCMP_ARCH_X86_64",
    "SCMP_ARCH_AARCH64"
  ],
  "syscalls": [
    {
      "names": [
        "accept", "accept4", "access", "bind", "brk", "chdir",
        "chmod", "chown", "close", "connect", "dup", "dup2", "dup3",
        "epoll_create", "epoll_create1", "epoll_ctl", "epoll_wait",
        "epoll_pwait", "execve", "exit", "exit_group", "faccessat",
        "fchmod", "fchown", "fcntl", "fstat", "fstatfs", "futex",
        "getcwd", "getdents64", "getegid", "geteuid", "getgid",
        "getpid", "getppid", "getuid", "ioctl", "listen", "lseek",
        "lstat", "madvise", "memfd_create", "mkdir", "mmap", "mprotect",
        "munmap", "nanosleep", "newfstatat", "open", "openat",
        "pipe", "pipe2", "poll", "ppoll", "pread64", "pwrite64",
        "read", "readlink", "recvfrom", "recvmsg", "rename",
        "rt_sigaction", "rt_sigprocmask", "rt_sigreturn",
        "sched_getaffinity", "sched_yield", "select", "sendmsg",
        "sendto", "set_robust_list", "set_tid_address", "setgid",
        "setgroups", "setsockopt", "setuid", "shutdown", "sigaltstack",
        "socket", "stat", "statfs", "symlink", "tgkill", "umask",
        "uname", "unlink", "wait4", "write", "writev"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
PROFILE

# Apply custom profile
docker run -d --security-opt seccomp=seccomp-strict.json myapp
```

### Profiling Syscalls (Build a Minimal Profile)

```bash
# Use strace to discover which syscalls your app actually uses
docker run --rm --security-opt seccomp=unconfined \
  strace -c -f myapp 2>&1 | tail -30

# Or use OCI seccomp BPF logging to generate a profile
# https://github.com/containers/oci-seccomp-bpf-hook
```

---

## 7. AppArmor / SELinux

### AppArmor (Debian/Ubuntu)

```bash
# Docker applies "docker-default" AppArmor profile automatically
# Check current profile
docker inspect --format='{{.AppArmorProfile}}' <container>

# Run with specific profile
docker run -d --security-opt apparmor=docker-default myapp

# Run without AppArmor (not recommended)
docker run -d --security-opt apparmor=unconfined myapp

# Load custom AppArmor profile
sudo apparmor_parser -r -W /etc/apparmor.d/docker-myapp
docker run -d --security-opt apparmor=docker-myapp myapp
```

### Custom AppArmor Profile Example

```
# /etc/apparmor.d/docker-myapp
#include <tunables/global>

profile docker-myapp flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>

  # Allow network access
  network inet tcp,
  network inet udp,
  network inet6 tcp,

  # Allow reading application files
  /app/** r,
  /app/node_modules/** mr,

  # Allow tmp writes
  /tmp/** rw,

  # Deny sensitive paths
  deny /etc/shadow r,
  deny /etc/passwd w,
  deny /proc/*/mem rw,
  deny /sys/firmware/** r,

  # Deny mount operations
  deny mount,
  deny umount,

  # Deny raw socket access
  deny network raw,
  deny network packet,
}
```

### SELinux (RHEL/Fedora/CentOS)

```bash
# Check SELinux status
getenforce                    # Enforcing, Permissive, or Disabled
sestatus                      # detailed status

# Docker volume SELinux labels
docker run -v /host/data:/data:Z myapp     # :Z = private (single container)
docker run -v /host/data:/data:z myapp     # :z = shared (multiple containers)

# The :Z flag relabels the volume with the container's exact SELinux label
# The :z flag relabels the volume with a shared label

# Check container SELinux context
docker inspect --format='{{.ProcessLabel}}' <container>
ps -eZ | grep docker

# Custom SELinux type for container process
docker run -d --security-opt label=type:svirt_apache_t myapp

# Disable SELinux confinement for a container (not recommended)
docker run -d --security-opt label=disable myapp
```

### When to Use Which

| System | AppArmor | SELinux |
|---|---|---|
| Ubuntu/Debian | Default, simpler profiles | Available but not default |
| RHEL/CentOS/Fedora | Not default | Default, mandatory |
| Complexity | Path-based, easier to write | Label-based, steeper learning curve |
| Granularity | File path rules | Process + file + network labels |
| Docker default profile | Yes (`docker-default`) | Yes (automatic labeling) |
| Recommendation | Use where available | Use where it is the OS default |

---

## 8. Secrets Management

### Docker Secrets (Swarm Mode)

```bash
# Create a secret
echo "s3cr3t_pa55w0rd" | docker secret create db_password -
docker secret create tls_cert /path/to/cert.pem

# List and inspect
docker secret ls
docker secret inspect db_password

# Use in a service
docker service create \
  --name mydb \
  --secret db_password \
  postgres:16

# Secret is mounted at /run/secrets/db_password inside the container
# Application reads it:
# password = open('/run/secrets/db_password').read().strip()
```

### BuildKit Secret Mounts (Build-Time)

```dockerfile
# syntax=docker/dockerfile:1

# Secret is available during build but NEVER stored in any layer
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) \
    npm ci --production

# For .npmrc or pip.conf
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci --production

# Multiple secrets
RUN --mount=type=secret,id=aws_key \
    --mount=type=secret,id=aws_secret \
    aws s3 cp s3://bucket/data /app/data
```

```bash
# Pass secrets during build
docker build \
  --secret id=npm_token,src=$HOME/.npm_token \
  --secret id=npmrc,src=$HOME/.npmrc \
  -t myapp .

# From environment variable
echo "$NPM_TOKEN" | docker build --secret id=npm_token -t myapp .
```

### Environment Variable Risks

```bash
# BAD: Secrets in ENV are exposed everywhere
docker run -e DB_PASSWORD=secret123 myapp

# Visible via inspect
docker inspect <container> --format='{{.Config.Env}}'
# Output: [DB_PASSWORD=secret123 ...]

# Visible inside container
docker exec <container> env | grep DB_PASSWORD

# Visible in /proc
docker exec <container> cat /proc/1/environ | tr '\0' '\n'
```

### External Vault Integration Patterns

```bash
# HashiCorp Vault — agent sidecar pattern
docker run -d \
  --name vault-agent \
  -v vault-secrets:/secrets \
  -e VAULT_ADDR=https://vault.example.com:8200 \
  hashicorp/vault agent -config=/etc/vault/agent.hcl

docker run -d \
  --name myapp \
  -v vault-secrets:/secrets:ro \
  myapp

# Application reads /secrets/db-password written by vault-agent

# AWS Secrets Manager — init container pattern
docker run --rm \
  -v app-secrets:/secrets \
  -e AWS_DEFAULT_REGION=us-east-1 \
  amazon/aws-cli secretsmanager get-secret-value \
    --secret-id prod/myapp/db --query SecretString \
    --output text > /secrets/db_password

docker run -d -v app-secrets:/secrets:ro myapp
```

---

## 9. Network Security

### Internal Networks

```bash
# Create internal network — no external/internet access
docker network create --internal isolated_net

# Containers on internal networks can talk to each other
# but cannot reach the internet or be reached from outside
docker run -d --network isolated_net --name backend myapp
docker run -d --network isolated_net --name db postgres:16

# Multi-network pattern: frontend talks to internet AND backend
docker network create frontend_net
docker network create --internal backend_net

docker run -d --network frontend_net --name web nginx
docker network connect backend_net web                    # web on both networks
docker run -d --network backend_net --name api myapi      # api on internal only
docker run -d --network backend_net --name db postgres:16  # db on internal only
```

### Encrypted Overlay Networks (Swarm)

```bash
# Create encrypted overlay (IPsec encryption for data plane)
docker network create --driver overlay --opt encrypted secure_overlay

# All traffic between nodes on this network is encrypted via IPsec
docker service create --network secure_overlay --name myservice myapp
```

### TLS for Docker Daemon

```bash
# Generate CA and server certificates
openssl genrsa -aes256 -out ca-key.pem 4096
openssl req -new -x509 -days 365 -key ca-key.pem -sha256 -out ca.pem

openssl genrsa -out server-key.pem 4096
openssl req -new -key server-key.pem -subj "/CN=docker-host" -out server.csr

echo subjectAltName = DNS:docker-host,IP:192.168.1.100 > extfile.cnf
echo extendedKeyUsage = serverAuth >> extfile.cnf
openssl x509 -req -days 365 -sha256 -in server.csr \
  -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
  -out server-cert.pem -extfile extfile.cnf

# Generate client certificates
openssl genrsa -out key.pem 4096
openssl req -new -key key.pem -subj "/CN=client" -out client.csr
echo extendedKeyUsage = clientAuth > extfile-client.cnf
openssl x509 -req -days 365 -sha256 -in client.csr \
  -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
  -out cert.pem -extfile extfile-client.cnf

# Configure daemon for TLS
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "tls": true,
  "tlsverify": true,
  "tlscacert": "/etc/docker/certs/ca.pem",
  "tlscert": "/etc/docker/certs/server-cert.pem",
  "tlskey": "/etc/docker/certs/server-key.pem",
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
}
EOF

# Client usage
docker --tlsverify \
  --tlscacert=ca.pem --tlscert=cert.pem --tlskey=key.pem \
  -H=tcp://docker-host:2376 ps
```

### Restricting Published Ports

```bash
# Bind to specific interface (not 0.0.0.0)
docker run -d -p 127.0.0.1:8080:8080 myapp           # localhost only
docker run -d -p 192.168.1.100:8080:8080 myapp        # specific interface

# Default daemon binding (affects all published ports)
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "ip": "127.0.0.1"
}
EOF

# Docker bypasses iptables/firewalld for port publishing
# Use DOCKER-USER chain for firewall rules that survive restarts
sudo iptables -I DOCKER-USER -i eth0 -j DROP
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 443 -j ACCEPT
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 80 -j ACCEPT
```

---

## 10. CIS Docker Benchmark

The CIS Docker Benchmark provides consensus security configuration guidelines. Use `docker-bench-security` for automated checking.

### Automated Scanning

```bash
# Run docker-bench-security
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -e DOCKER_CONTENT_TRUST=$DOCKER_CONTENT_TRUST \
  -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /usr/lib/systemd:/usr/lib/systemd:ro \
  -v /etc:/etc:ro \
  docker/docker-bench-security

# Note: older CIS benchmark versions include a "Content trust enabled"
# check (DOCKER_CONTENT_TRUST=1). DCT is retired (announced 2025) — treat
# that check as obsolete; satisfy the signing intent with cosign/Notation
# verification gates instead (see Section 2).

# Output JSON report
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /etc:/etc:ro \
  -l docker_bench_security \
  docker/docker-bench-security -l /dev/stdout 2>/dev/null
```

### Key CIS Recommendations

**Host Configuration:**

| # | Recommendation | How |
|---|---|---|
| 1.1.1 | Use a separate partition for containers | Mount `/var/lib/docker` on dedicated partition |
| 1.1.3 | Audit Docker daemon | `auditctl -w /usr/bin/dockerd -k docker` |
| 1.1.4 | Audit Docker files | `auditctl -w /var/lib/docker -k docker` |
| 1.1.5 | Audit docker.sock | `auditctl -w /var/run/docker.sock -k docker` |
| 1.1.7 | Audit Docker config | `auditctl -w /etc/docker -k docker` |

**Daemon Configuration:**

| # | Recommendation | How |
|---|---|---|
| 2.1 | Restrict network traffic between containers | `"icc": false` in daemon.json |
| 2.2 | Set logging level to info | `"log-level": "info"` in daemon.json |
| 2.3 | Allow Docker to make iptables changes | `"iptables": true` (default) |
| 2.5 | Do not use insecure registries | Ensure `"insecure-registries"` is empty |
| 2.6 | Setup a centralized log driver | `"log-driver": "syslog"` or `"json-file"` with rotation |
| 2.8 | Enable user namespace support | `"userns-remap": "default"` |
| 2.11 | Use authorization plugin | `"authorization-plugins": ["auth-plugin"]` |
| 2.14 | Enable live restore | `"live-restore": true` |
| 2.17 | Do not use Swarm if not needed | `docker swarm leave --force` |

**Container Runtime:**

| # | Recommendation | How |
|---|---|---|
| 5.1 | Do not disable AppArmor | Never use `--security-opt apparmor=unconfined` |
| 5.2 | Verify SELinux if applicable | Use `:Z` or `:z` on volumes |
| 5.3 | Restrict Linux capabilities | `--cap-drop=ALL --cap-add=...` |
| 5.4 | Do not use privileged containers | Never use `--privileged` |
| 5.7 | Do not map privileged ports | Avoid mapping to ports < 1024 unless necessary |
| 5.10 | Limit memory | `--memory=512m` |
| 5.12 | Mount root filesystem read-only | `--read-only` |
| 5.15 | Do not share host process namespace | Never use `--pid=host` |
| 5.16 | Do not share host IPC namespace | Never use `--ipc=host` |
| 5.25 | Restrict container from gaining privileges | `--security-opt=no-new-privileges` |
| 5.26 | Check container health | Define HEALTHCHECK in Dockerfile |
| 5.28 | Use PIDs limit | `--pids-limit=100` |
| 5.31 | Do not mount Docker socket | Never mount `/var/run/docker.sock` |

### daemon.json CIS-Aligned Configuration

```json
{
  "icc": false,
  "log-level": "info",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "5"
  },
  "storage-driver": "overlay2",
  "live-restore": true,
  "userland-proxy": false,
  "no-new-privileges": true,
  "userns-remap": "default",
  "seccomp-profile": "/etc/docker/seccomp-default.json",
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 65536,
      "Soft": 32768
    },
    "nproc": {
      "Name": "nproc",
      "Hard": 4096,
      "Soft": 2048
    }
  }
}
```

---

## 11. Runtime Security

### Falco (Runtime Threat Detection)

```bash
# Run Falco in a container (OS-agnostic — recommended)
# For host-level installation, see ubuntu-docker-host or rhel-docker-host
docker run -d --name falco \
  --privileged \
  -v /var/run/docker.sock:/host/var/run/docker.sock:ro \
  -v /proc:/host/proc:ro \
  -v /dev:/host/dev \
  -v /etc:/host/etc:ro \
  falcosecurity/falco:latest
```

### Custom Falco Rules

```yaml
# /etc/falco/falco_rules.local.yaml

# Detect shell spawned in container
- rule: Shell Spawned in Container
  desc: Detect shell execution in a container
  condition: >
    spawned_process and container and
    proc.name in (bash, sh, zsh, dash, ash, csh, ksh, fish)
  output: >
    Shell spawned in container
    (container=%container.name command=%proc.cmdline user=%user.name image=%container.image.repository)
  priority: WARNING

# Detect crypto mining processes
- rule: Detect Cryptominer
  desc: Detect known cryptominer process names
  condition: >
    spawned_process and container and
    (proc.name in (xmrig, minerd, minergate, cpuminer, ethminer) or
     proc.cmdline contains "stratum+tcp" or
     proc.cmdline contains "stratum+ssl" or
     proc.cmdline contains "cryptonight")
  output: >
    Cryptominer detected in container
    (container=%container.name command=%proc.cmdline image=%container.image.repository)
  priority: CRITICAL

# Detect sensitive file access
- rule: Read Sensitive File in Container
  desc: Detect reads to sensitive files
  condition: >
    open_read and container and
    fd.name in (/etc/shadow, /etc/sudoers, /root/.ssh/authorized_keys, /root/.bash_history)
  output: >
    Sensitive file read in container
    (container=%container.name file=%fd.name command=%proc.cmdline)
  priority: ERROR
```

### Audit Logging

```bash
# Enable audit rules for Docker
sudo tee /etc/audit/rules.d/docker.rules <<'EOF'
-w /usr/bin/dockerd -p rwxa -k docker
-w /var/lib/docker -p rwxa -k docker
-w /etc/docker -p rwxa -k docker
-w /lib/systemd/system/docker.service -p rwxa -k docker
-w /lib/systemd/system/docker.socket -p rwxa -k docker
-w /var/run/docker.sock -p rwxa -k docker
-w /etc/default/docker -p rwxa -k docker
-w /etc/docker/daemon.json -p rwxa -k docker
EOF

sudo systemctl restart auditd

# Query audit logs
sudo ausearch -k docker --start today
```

### Container Behavior Monitoring

```bash
# Monitor container events in real time
docker events --filter type=container

# Monitor with formatting
docker events --filter type=container \
  --format '{{.Time}} {{.Action}} {{.Actor.Attributes.name}} {{.Actor.Attributes.image}}'

# Monitor specific actions
docker events --filter event=start --filter event=die --filter event=oom

# Check for containers running as root
docker ps -q | xargs -I{} docker inspect --format '{{.Name}}: User={{.Config.User}}' {}

# Detect containers without resource limits
docker ps -q | xargs -I{} docker inspect \
  --format '{{.Name}}: Memory={{.HostConfig.Memory}} CPUs={{.HostConfig.NanoCpus}}' {}
```

---

## 12. Supply Chain Security

### Trusted Base Images

```bash
# Use Docker Official Images (library/*)
docker pull nginx              # docker.io/library/nginx — Docker Official
docker pull python:3.12-slim   # Docker Official

# Use Docker Verified Publisher images
docker pull bitnami/postgresql

# Check image provenance/attestations (do NOT use `docker trust inspect` —
# DCT is retired and it fails for Docker Official Images since 2025-08)
docker buildx imagetools inspect nginx --format '{{json .Provenance}}'
docker scout quickview nginx

# Pin by digest regardless of signing tooling
docker inspect --format='{{index .RepoDigests 0}}' nginx

# Never pull from unverified third-party registries in production
```

### Dockerfile Linting with Hadolint

```bash
# Run hadolint
docker run --rm -i hadolint/hadolint < Dockerfile

# With ignore rules
docker run --rm -i hadolint/hadolint \
  --ignore DL3008 --ignore DL3009 < Dockerfile

# .hadolint.yaml configuration
cat > .hadolint.yaml <<'EOF'
ignored:
  - DL3008    # Pin apt package versions
  - DL3009    # Delete apt lists

trustedRegistries:
  - docker.io
  - gcr.io
  - ghcr.io

override:
  error:
    - DL3001  # Do not use "last" tag
    - DL3002  # Do not use setuid/setgid in RUN
  warning:
    - DL3042  # Avoid cache dir with pip
EOF

docker run --rm -i -v $(pwd)/.hadolint.yaml:/.config/hadolint.yaml \
  hadolint/hadolint < Dockerfile
```

### Key Hadolint Rules

| Rule | Description |
|---|---|
| DL3000 | Use absolute WORKDIR |
| DL3001 | Do not use `apt-get dist-upgrade` |
| DL3002 | Last USER should not be root |
| DL3003 | Use WORKDIR instead of `cd` |
| DL3006 | Always tag image in FROM |
| DL3007 | Using `latest` is prone to errors |
| DL3008 | Pin versions in `apt-get install` |
| DL3018 | Pin versions in `apk add` |
| DL3025 | Use JSON notation for CMD/ENTRYPOINT |
| DL3059 | Multiple consecutive RUN — consider consolidation |
| DL4006 | Set `SHELL` option `-o pipefail` before RUN with pipe |

### CI Scanning Gates

```yaml
# GitHub Actions — scan and gate
name: Container Security
on: push

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4  # pin to SHA in production

      - name: Lint Dockerfile
        uses: hadolint/hadolint-action@v3  # pin to SHA in production
        with:
          dockerfile: Dockerfile

      - name: Build image
        run: docker build -t myapp:${{ github.sha }} .

      - name: Trivy vulnerability scan
        uses: aquasecurity/trivy-action@v0.24.0  # pin to SHA in production
        with:
          image-ref: myapp:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'

      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v3  # pin to SHA in production
        if: always()
        with:
          sarif_file: 'trivy-results.sarif'
```

```yaml
# GitLab CI — scan and gate
container_scan:
  stage: test
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker build -t myapp:${CI_COMMIT_SHA} .
    - |
      docker run --rm \
        -v /var/run/docker.sock:/var/run/docker.sock \
        aquasec/trivy image \
        --exit-code 1 \
        --severity HIGH,CRITICAL \
        myapp:${CI_COMMIT_SHA}
  allow_failure: false
```

### SLSA Provenance

```bash
# Build with SLSA provenance (BuildKit)
docker buildx build \
  --provenance=mode=max \
  --sbom=true \
  --push \
  -t registry.example.com/myapp:v1.0.0 .

# Verify provenance
docker buildx imagetools inspect registry.example.com/myapp:v1.0.0 \
  --format '{{json .Provenance.SLSA}}'

# Using SLSA GitHub Generator for container images
# Generates SLSA Level 3 provenance in GitHub Actions
# See: https://github.com/slsa-framework/slsa-github-generator

# Verify with slsa-verifier
slsa-verifier verify-image registry.example.com/myapp:v1.0.0 \
  --source-uri github.com/myorg/myapp \
  --source-tag v1.0.0
```

---

## Quick Reference: Security Checklist

```
BUILD TIME:
  [ ] Multi-stage builds to minimize final image
  [ ] Distroless or minimal base image
  [ ] Image digest pinning in FROM
  [ ] Non-root USER instruction
  [ ] BuildKit secret mounts (no secrets in layers)
  [ ] COPY --chown for proper file ownership
  [ ] hadolint in CI pipeline
  [ ] Trivy/Scout/Snyk scan gate in CI

RUNTIME:
  [ ] --cap-drop=ALL with selective --cap-add
  [ ] --read-only with tmpfs where needed
  [ ] --security-opt=no-new-privileges
  [ ] --memory and --cpus limits set
  [ ] --pids-limit set
  [ ] --user (non-root) or USER in Dockerfile
  [ ] Health checks defined
  [ ] Seccomp profile active (default or custom)
  [ ] AppArmor/SELinux not disabled

INFRASTRUCTURE:
  [ ] Docker daemon TLS enabled (if remote API)
  [ ] icc=false or user-defined networks
  [ ] Published ports bound to specific interfaces
  [ ] Image signing with cosign or Notation + digest pinning (Docker Content Trust retired 2025 — unset DOCKER_CONTENT_TRUST)
  [ ] Centralized logging configured
  [ ] Audit rules for Docker files and socket
  [ ] Runtime monitoring (Falco or equivalent)
  [ ] docker-bench-security run regularly
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running containers with `--privileged` flag | Disables all security boundaries; container has full host access; equivalent to running on bare metal | Use specific capabilities (`--cap-add`) for only what is needed; never use --privileged in production |
| Using images from untrusted registries without verification | Supply chain attacks; malicious layers; cryptominers in base images | Pin images by digest, not tag; sign/verify with cosign or Notation (Docker Content Trust retired 2025 — do not rely on it); scan with Trivy/Scout |
| Mounting Docker socket into containers | Any container with socket access can create privileged containers; full host compromise | Use Docker-in-Docker (dind) with TLS for CI; or use socket proxy with read-only API access |
| Storing secrets in environment variables | Visible in `docker inspect`, process listing, and container logs | Use Docker secrets, tmpfs-mounted files, or external secret managers (Vault, AWS SM) |
| Not setting read-only root filesystem | Attackers can modify binaries, plant backdoors, or write malware inside the container | Use `--read-only` flag; mount specific writable directories as tmpfs for temp files |

---

## Related Skills

| Topic | Skill |
|---|---|
| Core Docker concepts, Dockerfile patterns, BuildKit | `docker-fundamentals` |
| Bridge, overlay, DNS, multi-host networking | `docker-networking` |
| Volumes, bind mounts, storage drivers | `docker-storage` |
| CI/CD pipelines, multi-platform builds, registries | `docker-cicd` |
| Compose patterns and advanced orchestration | `docker-compose-patterns` |
| Operational admin, cross-platform, AD mapping | `docker-admin` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |
| Python authentication and security patterns | `python-auth-security` |
