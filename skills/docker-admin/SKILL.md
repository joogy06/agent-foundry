---
name: docker-admin
description: Use when working with Docker containers, Compose files, Dockerfiles, container networking, volume mounts, cross-platform issues (Windows/Linux/PowerShell quoting), package installation in containers, Centrify/AD user mapping, or container security. Covers build patterns, entrypoint scripts, stateless design, and production operations.
---

# Docker Admin

## Overview

Docker container administration: Compose V2, Dockerfile best practices, cross-platform gotchas, security, and production patterns. This skill covers the tricky parts — quoting across shells, Windows mount issues, AD user mapping, and patterns that prevent 3am incidents.

## Docker Compose (V2)

**Use `docker compose` (space, not hyphen).** `docker-compose` (V1) is deprecated.

### Compose File Structure

```yaml
# compose.yaml (preferred name, also accepts docker-compose.yml)
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        NODE_ENV: production
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=${DATABASE_URL}
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
    volumes:
      - app-data:/data
      - ./config:/app/config:ro
    networks:
      - backend

  db:
    image: postgres:16-alpine
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend

volumes:
  app-data:
  db-data:

networks:
  backend:
    driver: bridge
```

### Key Compose Features

| Feature | Syntax | Use Case |
|---------|--------|----------|
| **Profiles** | `profiles: [debug]` → `docker compose --profile debug up` | Optional services (monitoring, debug tools) |
| **Watch** | `develop: watch:` block | Hot reload for development |
| **Include** | `include: - path: ./db/compose.yaml` | Modular compose files |
| **Override** | `docker-compose.override.yml` (auto-loaded) | Dev overrides without editing main file |
| **Depends_on conditions** | `condition: service_healthy` | Wait for real readiness, not just start |

### Environment Variable Precedence (highest → lowest)

1. `docker compose run -e VAR=val`
2. Shell environment
3. `.env` file in project directory
4. `env_file` in compose
5. Dockerfile `ENV`

**Default values:** `${VAR:-default}` (use default if unset), `${VAR:?error}` (fail if unset)

## Dockerfile Best Practices

### Multi-Stage Build (Standard Pattern)

```dockerfile
# Stage 1: Build
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --production=false
COPY . .
RUN npm run build

# Stage 2: Production
FROM node:22-alpine AS production
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
USER appuser
EXPOSE 8080
HEALTHCHECK CMD wget -q --spider http://localhost:8080/health || exit 1
ENTRYPOINT ["node", "dist/server.js"]
```

### Layer Caching Rules

```dockerfile
# GOOD: Dependencies first (rarely change), code second (often changes)
COPY package*.json ./
RUN npm ci
COPY . .

# BAD: Code change invalidates npm ci cache
COPY . .
RUN npm ci
```

### BuildKit Features

```dockerfile
# Cache mount (persist package manager cache between builds)
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y python3

# Build secret (never stored in image layers)
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) npm ci

# Heredoc (multi-line scripts without \)
RUN <<EOF
  apt-get update
  apt-get install -y curl git
  rm -rf /var/lib/apt/lists/*
EOF
```

**Enable BuildKit:** `DOCKER_BUILDKIT=1` or set in Docker daemon config (default in Docker 23.0+).

### Base Image Selection

| Image | Size | Use Case |
|-------|------|----------|
| `scratch` | 0 MB | Static Go/Rust binaries |
| `distroless` | 2-20 MB | No shell, maximum security |
| `alpine` | 5 MB | Small, has shell/apk, musl libc (compatibility issues possible) |
| `*-slim` | 50-80 MB | Balanced — glibc, minimal packages |
| Full (debian/ubuntu) | 100-300 MB | When you need everything |

**Pin versions:** Use `node:22.5-alpine` not `node:latest`. For maximum reproducibility, pin by digest: `node@sha256:abc123...`

## Entrypoint Patterns

### Init Process (Always Use)

Containers need an init process to reap zombie processes and forward signals:

```yaml
# Compose (easiest)
services:
  app:
    init: true  # Uses tini

# Or in Dockerfile
ENTRYPOINT ["tini", "--", "node", "server.js"]
```

**Why:** Without init, PID 1 is your app — it won't reap zombie child processes and may not handle SIGTERM correctly.

### Wait-for-Dependencies

```bash
#!/bin/bash
# entrypoint.sh
set -e

# Wait for database
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
  echo "Waiting for database..."
  sleep 2
done

# Run migrations
python manage.py migrate

# Start app
exec "$@"
```

**Key:** `exec "$@"` replaces the shell with the actual process — signals go directly to the app, not the shell.

### Config Generation from Environment

```bash
# Generate config from env vars using envsubst
envsubst < /app/config.template > /app/config.json
exec "$@"
```

## Cross-Platform: Windows Mounts & Quoting

### Volume Mount Paths by Shell

| Shell | Mount Syntax |
|-------|-------------|
| **Bash (Linux/Mac/WSL)** | `-v /home/user/data:/app/data` |
| **PowerShell** | `-v ${PWD}:/app/data` or `-v "C:\Users\user\data:/app/data"` |
| **CMD** | `-v %cd%:/app/data` or `-v C:\Users\user\data:/app/data` |
| **Git Bash (Windows)** | `MSYS_NO_PATHCONV=1 docker run -v //c/Users/user/data:/app/data` |

### Quoting Cheat Sheet

| Task | Bash | PowerShell | CMD |
|------|------|-----------|-----|
| Line continuation | `\` | `` ` `` (backtick) | `^` |
| Variable expansion | `$VAR` or `${VAR}` | `$env:VAR` | `%VAR%` |
| Prevent expansion | `'single quotes'` | `'single quotes'` | Not possible |
| JSON in -e flag | `-e 'CONFIG={"key":"val"}'` | `-e 'CONFIG={\"key\":\"val\"}'` | `-e CONFIG={\"key\":\"val\"}` |
| Multi-line docker run | See below | See below | See below |

```bash
# Bash
docker run -d \
  --name myapp \
  -p 8080:8080 \
  -v ./data:/app/data \
  -e DATABASE_URL="postgresql://user:pass@db:5432/mydb" \
  myimage:latest

# PowerShell
docker run -d `
  --name myapp `
  -p 8080:8080 `
  -v "${PWD}/data:/app/data" `
  -e DATABASE_URL="postgresql://user:pass@db:5432/mydb" `
  myimage:latest

# CMD
docker run -d ^
  --name myapp ^
  -p 8080:8080 ^
  -v %cd%\data:/app/data ^
  -e DATABASE_URL="postgresql://user:pass@db:5432/mydb" ^
  myimage:latest
```

### Windows Bind Mount Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| 10-20x slower file I/O | Bind mount crosses WSL2/Windows filesystem boundary | Store code in WSL2 filesystem (`/home/user/`) not Windows (`/mnt/c/`) |
| Permission denied | Windows UID mapping | Use named volumes, or `chmod` in entrypoint |
| CRLF line endings break scripts | Git on Windows auto-converts | `.gitattributes: * text=auto eol=lf` or `dos2unix` in Dockerfile |
| Path not found | MSYS path translation | `MSYS_NO_PATHCONV=1` prefix or use `//c/` instead of `/c/` |

## Package Installation in Containers

### apt (Debian/Ubuntu)

```dockerfile
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      python3 \
    && rm -rf /var/lib/apt/lists/*
```

### dnf/yum (RHEL/Fedora/Rocky)

```dockerfile
RUN --mount=type=cache,target=/var/cache/dnf \
    dnf install -y --setopt=install_weak_deps=False \
      python3 curl \
    && dnf clean all
```

### apk (Alpine)

```dockerfile
RUN apk add --no-cache \
    python3 curl
```

### npm/pip (Application Dependencies)

```dockerfile
# npm — use ci for reproducible installs
COPY package*.json ./
RUN npm ci --omit=dev

# pip — no cache, specify versions
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

**Rule:** Always `--no-install-recommends` (apt), `--no-cache` (apk), `--omit=dev` (npm), `--no-cache-dir` (pip) to minimize image size.

## Centrify / AD User Mapping

### SSSD Socket Mounting (Recommended)

Mount the host's SSSD socket into the container for AD user resolution:

```yaml
services:
  app:
    volumes:
      - /var/lib/sss/pipes:/var/lib/sss/pipes:ro
      - /var/lib/sss/mc:/var/lib/sss/mc:ro
    # Container needs nsswitch.conf configured for sss
```

### UID/GID Mapping

```dockerfile
# Run as specific AD-mapped UID
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} appgroup && \
    useradd -u ${APP_UID} -g appgroup -m appuser
USER appuser
```

Pass AD user's UID at build or run time: `docker run --user $(id -u):$(id -g) myimage`

### User Namespace Remapping

Docker's `userns-remap` maps container root to an unprivileged host user:

```json
// /etc/docker/daemon.json
{
  "userns-remap": "default"
}
```

## Security Checklist

Every container should pass:

- [ ] **Non-root user** — `USER` directive, never run as root
- [ ] **Read-only filesystem** — `--read-only` + tmpfs for /tmp
- [ ] **No unnecessary capabilities** — `--cap-drop ALL --cap-add` only what's needed
- [ ] **No new privileges** — `--security-opt=no-new-privileges`
- [ ] **Pinned base image** — version tag or digest, not `latest`
- [ ] **No secrets in image** — use build secrets `--mount=type=secret` or runtime secrets
- [ ] **Vulnerability scan** — `docker scout cves` or `trivy image` in CI
- [ ] **Minimal base** — alpine/slim/distroless, not full OS
- [ ] **Health check** — HEALTHCHECK in Dockerfile or compose
- [ ] **Init process** — `init: true` in compose or tini in Dockerfile
- [ ] **No Docker socket mount** — unless absolutely required (security risk)

## Essential Commands

See `commands-reference.md` for the full reference. Quick essentials:

| Task | Command |
|------|---------|
| Build + start | `docker compose up -d --build` |
| View logs | `docker compose logs -f service` |
| Exec into container | `docker compose exec service bash` |
| Stop all | `docker compose down` |
| Stop + remove volumes | `docker compose down -v` |
| Rebuild single service | `docker compose up -d --build service` |
| View resource usage | `docker stats` |
| Scan for vulnerabilities | `docker scout cves image:tag` |
| Clean everything | `docker system prune -a --volumes` |
| Multi-platform build | `docker buildx build --platform linux/amd64,linux/arm64 -t img .` |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Use `docker-compose` (V1) | Deprecated — use `docker compose` (V2) |
| Run as root in containers | Security vulnerability — always use USER |
| Use `latest` tag | Non-reproducible — pin versions |
| Store secrets in ENV or image layers | Visible in inspect/history — use build secrets |
| Use `ENTRYPOINT` shell form | Doesn't handle signals — use exec form `["cmd"]` |
| Skip health checks | Compose can't manage dependencies without them |
| Bind mount Windows paths for performance | 10-20x slower — use WSL2 filesystem or named volumes |
| Install build tools in production image | Bloat + attack surface — use multi-stage builds |
| Use `docker system prune -a` without thinking | Removes ALL unused images including cached layers |
| Mount Docker socket into containers | Root-equivalent access — use alternatives (Docker-in-Docker, Sysbox) |

---

## Related Skills

| Topic | Skill |
|---|---|
| Core Docker concepts, CLI, Dockerfiles, BuildKit | `docker-fundamentals` |
| Docker networking (bridge, overlay, macvlan) | `docker-networking` |
| Volumes, bind mounts, storage drivers | `docker-storage` |
| Image scanning, rootless, CIS benchmark | `docker-security` |
| CI/CD, multi-platform builds, registries | `docker-cicd` |
| Advanced Compose patterns | `docker-compose-patterns` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |
