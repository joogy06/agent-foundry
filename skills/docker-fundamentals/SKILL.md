---
name: docker-fundamentals
description: Use when working with Docker containers — core concepts, CLI commands, image management, container lifecycle, Dockerfile patterns, BuildKit features, multi-stage builds, layer caching optimization, health checks, restart policies, resource limits, npm/Node.js Docker patterns, Python Docker patterns, .dockerignore, debugging and troubleshooting containers. Parent skill for the docker-* skill family. OS-agnostic — for OS-specific setup see ubuntu-docker-host or rhel-docker-host.
family: docker
disambiguation: Core local usage — CLI, image and container lifecycle, Dockerfile patterns, BuildKit. Running builds inside CI pipelines is docker-cicd.
---

# Docker Fundamentals

OS-agnostic Docker core concepts and patterns. For OS-specific installation and setup, see `ubuntu-docker-host` or `rhel-docker-host`. For Compose patterns, see `docker-compose-patterns`. For operational gotchas and cross-platform issues, see `docker-admin`.

<HARD-RULE>
Never run containers as root in production. Always specify a non-root USER in Dockerfiles. Root in a container is root on the host if the container escapes.
</HARD-RULE>

<HARD-RULE>
Never store secrets in Dockerfiles, build args, or image layers. Use Docker secrets, environment variables at runtime, or mount secret files. Secrets baked into images are extractable by anyone with image access.
</HARD-RULE>

---

## Container Lifecycle

```bash
# Create and start
docker run -d --name myapp -p 8080:8080 myimage:latest
docker run -it --rm ubuntu:24.04 bash          # interactive, auto-remove

# Lifecycle commands
docker start|stop|restart|pause|unpause <container>
docker kill <container>                         # SIGKILL (immediate)
docker stop -t 30 <container>                   # SIGTERM, wait 30s, then SIGKILL

# Inspect
docker ps                                       # running containers
docker ps -a                                    # all containers
docker inspect <container>                      # full JSON details
docker logs <container>                         # stdout/stderr
docker logs -f --tail 100 <container>           # follow last 100 lines
docker logs --since 1h <container>              # last hour
docker top <container>                          # running processes
docker stats                                    # live resource usage
docker stats --no-stream                        # snapshot

# Execute in running container
docker exec -it <container> bash
docker exec -it <container> sh                  # if bash not available
docker exec <container> env                     # check environment

# Copy files
docker cp <container>:/path/file ./local
docker cp ./local <container>:/path/file

# Remove
docker rm <container>
docker rm -f <container>                        # force (kills first)
```

### Restart Policies

```bash
docker run -d --restart=unless-stopped myapp    # restart unless manually stopped
docker run -d --restart=on-failure:5 myapp      # restart on failure, max 5 times
docker run -d --restart=always myapp            # always restart
docker run -d --restart=no myapp                # never restart (default)

# Update restart policy on running container
docker update --restart=unless-stopped <container>
```

| Policy | On Crash | On Docker Restart | On Manual Stop |
|---|---|---|---|
| `no` | No | No | N/A |
| `on-failure[:N]` | Yes (up to N) | No | N/A |
| `always` | Yes | Yes | Yes |
| `unless-stopped` | Yes | Yes | No |

---

## Image Management

```bash
# List and inspect
docker images                                   # local images
docker images -a                                # include intermediates
docker image inspect <image>
docker image history <image>                    # layer breakdown

# Pull and push
docker pull nginx:1.27-alpine
docker tag myapp:latest registry.example.com/myapp:v1.2.3
docker push registry.example.com/myapp:v1.2.3

# Remove
docker rmi <image>
docker image prune                              # remove dangling images
docker image prune -a                           # remove all unused images

# Save and load (offline transfer)
docker save myapp:latest | gzip > myapp.tar.gz
docker load < myapp.tar.gz

# Export/import container filesystem (loses metadata)
docker export <container> > container.tar
docker import container.tar myimage:imported
```

### Image Tagging Strategy

```bash
# Semantic versioning + latest
docker tag myapp:latest myapp:1.0.0
docker tag myapp:latest myapp:1.0
docker tag myapp:latest myapp:1

# Git SHA for traceability
docker tag myapp:latest myapp:$(git rev-parse --short HEAD)

# Environment tags
docker tag myapp:latest myapp:staging
docker tag myapp:v1.2.3 myapp:production
```

---

## Dockerfile Patterns

### Basic Structure

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS base

# Metadata
LABEL maintainer="team@example.com"
LABEL version="1.0.0"

# Install OS dependencies
RUN apk add --no-cache tini curl

# Create non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Set working directory
WORKDIR /app

# Copy dependency files first (layer caching)
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci --production

# Copy application code
COPY --chown=appuser:appgroup . .

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

# Switch to non-root user
USER appuser

# Use tini as PID 1 (proper signal handling)
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
```

### Multi-Stage Builds

```dockerfile
# syntax=docker/dockerfile:1

# Stage 1: Build
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Production
FROM node:22-alpine AS production
RUN apk add --no-cache tini
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
USER app
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/server.js"]
```

### Python Multi-Stage

```dockerfile
# syntax=docker/dockerfile:1

# Stage 1: Build with pip
FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production
FROM python:3.12-slim AS production
RUN groupadd -r app && useradd -r -g app app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY --chown=app:app . .
USER app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:create_app()"]
```

### Go Multi-Stage (Scratch Final)

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /server .

FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /server /server
ENTRYPOINT ["/server"]
```

---

## BuildKit Features

<HARD-RULE>
Always use BuildKit. It's the default in Docker 23.0+. For older versions, set `DOCKER_BUILDKIT=1`. BuildKit provides better caching, parallel builds, and secret mounting.
</HARD-RULE>

```bash
# Enable BuildKit (if not default)
export DOCKER_BUILDKIT=1

# Build with progress output
docker build --progress=plain -t myapp .

# Build specific stage
docker build --target builder -t myapp:build .

# Pass build arguments
docker build --build-arg NODE_ENV=production -t myapp .
```

### Secret Mounting (Never Bake Secrets)

```dockerfile
# Mount secret at build time — never stored in layers
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci --production

# Usage:
# docker build --secret id=npmrc,src=$HOME/.npmrc -t myapp .
```

### Cache Mounts (Faster Rebuilds)

```dockerfile
# Cache apt packages across builds
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update && apt-get install -y curl

# Cache npm packages
RUN --mount=type=cache,target=/root/.npm \
    npm ci --production

# Cache pip packages
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Cache Go modules
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
```

### Bind Mounts at Build Time

```dockerfile
# Mount source code without COPY (useful for linting/testing stages)
RUN --mount=type=bind,source=.,target=/src \
    cd /src && npm run lint
```

---

## Layer Caching Optimization

### Principles

1. **Order by change frequency** — put rarely-changing instructions first
2. **Separate dependency install from code copy** — dependencies change less often
3. **Combine RUN commands** — fewer layers = smaller image, but balance with caching
4. **Use .dockerignore** — exclude files that invalidate cache unnecessarily

### Node.js Layer Caching

```dockerfile
# GOOD: Dependencies cached separately from code
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# BAD: Any code change invalidates npm install cache
COPY . .
RUN npm ci
```

### Cache Busting

```dockerfile
# Force re-fetch of packages (useful for security updates)
ARG CACHE_BUST=1
RUN apt-get update && apt-get upgrade -y
```

---

## .dockerignore

```
# Version control
.git
.gitignore

# Dependencies (rebuild in container)
node_modules
__pycache__
*.pyc
.venv
vendor

# Build artifacts
dist
build
*.egg-info

# IDE and editor
.vscode
.idea
*.swp
*.swo

# Docker files (don't need to be in context)
Dockerfile*
docker-compose*
.dockerignore

# Environment and secrets
.env
.env.*
*.key
*.pem

# Documentation and tests (usually not needed in production image)
docs
tests
test
*.md
LICENSE

# OS files
.DS_Store
Thumbs.db
```

---

## npm / Node.js Docker Patterns

### npm ci vs npm install

```dockerfile
# ALWAYS use npm ci in Docker (deterministic, faster, respects lockfile)
RUN npm ci --production

# npm install modifies lockfile — creates inconsistent builds
# RUN npm install  # DON'T USE IN DOCKERFILES
```

### Handling node_modules Correctly

```dockerfile
# 1. .dockerignore must exclude node_modules
#    (prevents host node_modules from overwriting container's)

# 2. For development with bind mounts, use anonymous volume:
# docker run -v $(pwd):/app -v /app/node_modules myapp:dev
# This prevents host node_modules from shadowing container's
```

### Node.js Production Best Practices

```dockerfile
FROM node:22-alpine

# Don't run as root
RUN addgroup -S app && adduser -S app -G app

# Set production environment
ENV NODE_ENV=production

WORKDIR /app

# Install production deps only
COPY package.json package-lock.json ./
RUN npm ci --production --ignore-scripts && npm cache clean --force

# Copy app code
COPY --chown=app:app . .

USER app

# Use exec form (proper signal handling)
CMD ["node", "server.js"]
```

### TypeScript Build Pattern

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci
COPY src ./src
RUN npm run build
RUN npm prune --production

FROM node:22-alpine
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
ENV NODE_ENV=production
USER app
CMD ["node", "dist/index.js"]
```

---

## Python Docker Patterns

### pip with Virtual Environment

```dockerfile
FROM python:3.12-slim
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

### Poetry

```dockerfile
FROM python:3.12-slim AS builder
RUN pip install poetry
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY . .
CMD ["gunicorn", "-w", "4", "app:app"]
```

---

## Health Checks

```dockerfile
# HTTP health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# TCP port check (no curl needed)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD nc -z localhost 5432 || exit 1

# Custom script
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD /app/healthcheck.sh
```

```bash
# Check health status
docker inspect --format='{{.State.Health.Status}}' <container>
docker inspect --format='{{json .State.Health}}' <container> | jq

# Health status values: starting, healthy, unhealthy
```

---

## Resource Limits

```bash
# Memory limits
docker run -d --memory=512m --memory-swap=1g myapp
docker run -d --memory=512m --memory-swap=-1 myapp    # unlimited swap

# CPU limits
docker run -d --cpus=1.5 myapp                        # 1.5 CPU cores
docker run -d --cpu-shares=512 myapp                   # relative weight (default 1024)
docker run -d --cpuset-cpus="0,1" myapp                # pin to specific CPUs

# Combined
docker run -d --memory=1g --cpus=2 --pids-limit=100 myapp

# Update limits on running container
docker update --memory=1g --cpus=2 <container>
```

---

## Debugging and Troubleshooting

### Container Won't Start

```bash
# Check logs (even for stopped containers)
docker logs <container>

# Check exit code
docker inspect --format='{{.State.ExitCode}}' <container>

# Run interactively to debug
docker run -it --entrypoint sh myapp

# Override entrypoint
docker run -it --entrypoint /bin/bash myapp

# Check what's in the image
docker run --rm -it myapp ls -la /app
docker run --rm -it myapp cat /app/config.yml
```

### Debugging Running Container

```bash
# Shell into container
docker exec -it <container> sh

# Check processes
docker top <container>

# Check resource usage
docker stats <container> --no-stream

# Check networking
docker exec <container> cat /etc/hosts
docker exec <container> cat /etc/resolv.conf
docker exec <container> wget -qO- http://other-service:8080/health

# File system diff (what changed since image was created)
docker diff <container>

# Inspect full config
docker inspect <container> | jq '.[0].NetworkSettings'
docker inspect <container> | jq '.[0].Mounts'
```

### Debug with Ephemeral Container

```bash
# Attach debug tools to a running container (Docker 25+)
docker debug <container>

# Or use a sidecar approach
docker run -it --rm --pid=container:<container> --net=container:<container> \
  nicolaka/netshoot
```

### Image Analysis

```bash
# Check image layers and sizes
docker history --human --no-trunc myapp

# Explore image filesystem
docker run --rm -it myapp sh -c "find / -type f -size +1M 2>/dev/null | head -20"

# Use dive for interactive layer inspection
# docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock wagoodman/dive myapp
```

---

## System Maintenance

```bash
# Disk usage overview
docker system df
docker system df -v                              # verbose

# Clean up
docker system prune                              # dangling images + stopped containers
docker system prune -a                           # ALL unused images
docker system prune -a --volumes                 # include volumes (DESTRUCTIVE)

# Targeted cleanup
docker container prune                           # stopped containers
docker image prune -a                            # unused images
docker volume prune                              # unused volumes
docker network prune                             # unused networks
docker builder prune                             # build cache
```

<HARD-RULE>
`docker system prune -a --volumes` removes ALL unused volumes including named data volumes. Always verify with `docker volume ls` before pruning. Data loss is irreversible.
</HARD-RULE>

---

## Environment Variables and Configuration

```bash
# Pass environment variables
docker run -e DATABASE_URL=postgres://... myapp
docker run --env-file .env myapp

# Read from host environment
docker run -e HOME myapp                         # passes host's $HOME value
```

```dockerfile
# Dockerfile defaults (overridable at runtime)
ENV NODE_ENV=production
ENV PORT=3000

# ARG is build-time only (not available at runtime)
ARG VERSION=latest
LABEL version=$VERSION
```

---

## Exec Form vs Shell Form

```dockerfile
# EXEC FORM (preferred) — runs directly, proper signal handling
CMD ["node", "server.js"]
ENTRYPOINT ["python", "app.py"]

# SHELL FORM — runs via /bin/sh -c, no direct signals
CMD node server.js
ENTRYPOINT python app.py

# Shell form is needed for:
RUN echo "hello" > /tmp/test              # shell features (redirection)
RUN apt-get update && apt-get install -y curl  # shell features (&&)
```

| | Exec Form | Shell Form |
|---|---|---|
| Signal handling | Direct (PID 1) | Goes to shell (PID 1 is sh) |
| Variable expansion | No `$VAR` expansion | `$VAR` expanded by shell |
| Use for CMD/ENTRYPOINT | Yes (preferred) | Avoid |
| Use for RUN | When no shell features needed | When shell features needed |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running containers as root (no USER directive) | Container escape gives host root access; violates CIS Docker Benchmark | Add USER directive in Dockerfile; use rootless Docker mode for defense in depth |
| Using shell form for CMD/ENTRYPOINT | PID 1 is the shell, not your process; signals (SIGTERM) are not forwarded; graceful shutdown fails | Use exec form (JSON array): `CMD ["node", "server.js"]` instead of `CMD node server.js` |
| Installing packages without cleaning cache in same layer | Package manager cache (apt lists, pip cache) bloats image by hundreds of MB | Chain install and cleanup in one RUN: `apt-get install -y pkg && rm -rf /var/lib/apt/lists/*` |
| No .dockerignore file | Build context includes node_modules, .git, secrets, logs; slow builds, large images, leaked credentials | Create .dockerignore mirroring .gitignore plus .git, .env, and build artifacts |
| Not using multi-stage builds | Final image contains compilers, build tools, source code; 1GB+ images that should be 100MB | Use multi-stage: build in one stage, copy only artifacts to a slim runtime stage |

---

## Related Skills

| Topic | Skill |
|---|---|
| Docker networking (bridge, overlay, DNS) | `docker-networking` |
| Volumes, bind mounts, storage drivers | `docker-storage` |
| Image scanning, rootless, CIS benchmark | `docker-security` |
| CI/CD, multi-platform builds, registries | `docker-cicd` |
| Advanced Compose patterns | `docker-compose-patterns` |
| Compose basics, cross-platform, AD mapping | `docker-admin` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |
