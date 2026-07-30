---
name: docker-compose-patterns
description: Use when writing advanced Docker Compose configurations — profiles, extends and inheritance, YAML anchors and merge keys, health-dependent startup (depends_on conditions), multi-environment configs (override files, env substitution), secrets and configs, GPU access, init containers pattern, sidecar patterns, development vs production configs, npm/Node.js Compose workflows, watch mode, and Compose file specification reference. Part of the docker-* skill family. OS-agnostic.
family: docker
---

# Docker Compose Advanced Patterns

Parent skill: `docker-fundamentals`. Basic Compose structure (services, volumes, networks, commands) is covered in `docker-admin` -- this skill covers **advanced** patterns only.

<HARD-RULE>
Never use the `latest` tag in production compose files. Pin every image to a specific version (e.g., `postgres:16-alpine`, `redis:7.2-alpine`). `latest` is mutable -- a redeploy can silently pull a breaking change.
</HARD-RULE>

<HARD-RULE>
Always define healthchecks for any service used in a `depends_on` condition. Without a healthcheck, `condition: service_healthy` will fail at startup. The healthcheck must be defined on the dependency, not the dependent.
</HARD-RULE>

<HARD-RULE>
Secrets passed via `environment:` or `env_file:` are visible in `docker inspect` output. For sensitive values (passwords, API keys, tokens), use file-based secrets mounted into the container instead.
</HARD-RULE>

---

## 1. Profiles

Profiles define optional services that only start when explicitly activated.

```yaml
services:
  app:
    image: myapp:1.2.0
    ports: ["8080:8080"]
  db:
    image: postgres:16-alpine
  pgadmin:
    image: dpage/pgadmin4:8.4
    profiles: [debug]
    ports: ["5050:80"]
  prometheus:
    image: prom/prometheus:v2.51.0
    profiles: [monitoring]
  node-exporter:
    image: prom/node-exporter:v1.7.0
    profiles: [debug, monitoring]       # starts with either profile
```

```bash
docker compose --profile debug up -d
docker compose --profile debug --profile monitoring up -d
docker compose up -d                    # starts only app + db (no profiles)
```

Services with no `profiles` key always start. A profiled service starts when at least one of its profiles is active.

---

## 2. Extends and Inheritance

```yaml
# common.yaml -- shared base
services:
  base-web:
    init: true
    restart: unless-stopped
    deploy:
      resources:
        limits: { memory: 512M, cpus: "1.0" }
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
```

```yaml
# compose.yaml
services:
  api:
    extends:
      file: common.yaml
      service: base-web
    image: myapi:2.1.0
    ports: ["8080:8080"]
  worker:
    extends:
      file: common.yaml
      service: base-web
    image: myworker:2.1.0
  worker-high-priority:
    extends:
      service: worker                   # same-file extends
    deploy:
      resources:
        limits: { memory: 2G, cpus: "2.0" }
```

**Limitations:** Cannot extend a service that uses `depends_on`, `volumes_from`, or `links`. Top-level `networks`/`volumes` are not inherited.

---

## 3. YAML Anchors and Merge Keys

Anchors (`&`), aliases (`*`), and merge keys (`<<:`) reduce duplication. Top-level `x-` keys are ignored by Compose and serve as anchor targets.

```yaml
x-common-env: &common-env
  TZ: UTC
  LOG_LEVEL: info

x-healthcheck: &healthcheck
  interval: 30s
  timeout: 5s
  retries: 3

x-deploy: &deploy
  resources:
    limits: { memory: 512M, cpus: "1.0" }

services:
  api:
    image: myapi:3.0.0
    environment: { <<: *common-env, API_PORT: "8080" }
    healthcheck:
      <<: *healthcheck
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
    deploy: *deploy
  worker:
    image: myworker:3.0.0
    environment: { <<: *common-env, WORKER_CONCURRENCY: "4" }
    healthcheck:
      <<: *healthcheck
      test: ["CMD", "curl", "-f", "http://localhost:9090/health"]
    deploy:
      <<: *deploy
      resources:
        limits: { memory: 1G, cpus: "2.0" }    # override nested key
```

**Anchors vs extends:** Anchors are pure YAML (work anywhere). `extends` is Compose-specific but supports cross-file inheritance.

---

## 4. Health-Dependent Startup

```yaml
services:
  db:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d appdb"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s
  redis:
    image: redis:7.2-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
  migrations:
    image: myapp:2.0.0
    command: ["python", "manage.py", "migrate"]
    depends_on:
      db: { condition: service_healthy }
  app:
    image: myapp:2.0.0
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
      migrations: { condition: service_completed_successfully }
```

| Condition | Meaning | Use Case |
|---|---|---|
| `service_started` | Container started (default) | No health dependency |
| `service_healthy` | Healthcheck passing | DBs, caches, APIs |
| `service_completed_successfully` | Exited with code 0 | Migrations, seed scripts |

### Healthcheck Quick Reference

| Service | test command |
|---|---|
| PostgreSQL | `["CMD-SHELL", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]` |
| MySQL/MariaDB | `["CMD", "mysqladmin", "ping", "-h", "localhost"]` |
| Redis | `["CMD", "redis-cli", "ping"]` |
| MongoDB | `["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]` |
| Elasticsearch | `["CMD-SHELL", "curl -sf http://localhost:9200/_cluster/health"]` (start_period: 30s) |
| RabbitMQ | `["CMD", "rabbitmq-diagnostics", "check_port_connectivity"]` |
| HTTP app | `["CMD", "curl", "-f", "http://localhost:8080/health"]` |
| gRPC | `["CMD", "/bin/grpc_health_probe", "-addr=:50051"]` |

---

## 5. Multi-Environment Configuration

Use `compose.override.yaml` (auto-loaded) for dev overrides and named files for other environments.

```yaml
# compose.yaml -- base                    # compose.override.yaml -- auto-loaded dev
services:                                  # services:
  app:                                     #   app:
    image: myapp:2.0.0                     #     build: { context: ., target: dev }
    environment:                           #     volumes: [".:/app", "/app/node_modules"]
      NODE_ENV: production                 #     ports: ["8080:8080", "9229:9229"]
  db:                                      #     environment: { NODE_ENV: development }
    image: postgres:16-alpine              #   db:
                                           #     ports: ["5432:5432"]
```

```yaml
# compose.prod.yaml -- production overrides (explicit -f)
services:
  app:
    deploy: { replicas: 3, resources: { limits: { memory: 1G, cpus: "2.0" } } }
    restart: unless-stopped
    read_only: true
    tmpfs: [/tmp]
```

```bash
docker compose up -d                                        # dev (auto-loads override)
docker compose -f compose.yaml -f compose.prod.yaml up -d   # prod (skips override)
docker compose -f compose.yaml -f compose.prod.yaml config   # verify merged result
```

### Environment Variable Substitution

```yaml
services:
  app:
    image: ${REGISTRY:-docker.io}/myapp:${APP_VERSION:?APP_VERSION must be set}
    environment:
      DB_HOST: ${DB_HOST:-db}
      LOG_LEVEL: ${LOG_LEVEL:-info}
```

| Syntax | Behavior |
|---|---|
| `${VAR:-default}` | Value of VAR, or `default` if unset/empty |
| `${VAR-default}` | Value of VAR, or `default` if unset (empty kept) |
| `${VAR:?error}` | Value of VAR, or error+abort if unset/empty |

### .env and env_file

```bash
# .env -- auto-loaded by Compose for interpolation in compose.yaml
COMPOSE_PROJECT_NAME=myproject
APP_VERSION=2.0.0
```

```yaml
services:
  app:
    env_file:                           # loads vars INTO the container
      - .env.common
      - .env.${ENVIRONMENT:-dev}
```

**Precedence (highest first):** CLI `-e` > shell env > `.env` file > `env_file` > Dockerfile `ENV`.

---

## 6. Secrets and Configs

```yaml
services:
  app:
    image: myapp:2.0.0
    secrets: [db_password, api_key]
    environment:
      DB_PASSWORD_FILE: /run/secrets/db_password
      API_KEY_FILE: /run/secrets/api_key
  db:
    image: postgres:16-alpine
    secrets: [db_password]
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    file: ./secrets/db_password.txt
  api_key:
    file: ./secrets/api_key.txt
```

Secrets mount read-only at `/run/secrets/<name>`. Many official images (PostgreSQL, MySQL, MariaDB) natively support `*_FILE` env vars.

```yaml
# Configs -- mount configuration files
services:
  nginx:
    image: nginx:1.27-alpine
    configs:
      - source: nginx_conf
        target: /etc/nginx/nginx.conf
        mode: 0444
configs:
  nginx_conf:
    file: ./nginx/nginx.conf
```

---

## 7. GPU Access

```yaml
services:
  ml-training:
    image: pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all                # or count: 1, or device_ids: ["0","2"]
              capabilities: [gpu]
```

Requires NVIDIA driver + Container Toolkit + Docker nvidia runtime. Verify: `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`.

---

## 8. Development Patterns

### Watch Mode (Compose Watch)

```yaml
services:
  web:
    build: { context: ., target: development }
    ports: ["3000:3000"]
    develop:
      watch:
        - action: sync                  # copy files, no rebuild
          path: ./src
          target: /app/src
          ignore: ["**/*.test.ts"]
        - action: sync+restart          # copy + restart container
          path: ./config
          target: /app/config
        - action: rebuild               # full image rebuild
          path: ./package.json
```

```bash
docker compose watch
```

### Node.js Dev with Hot Reload

```yaml
services:
  app:
    build: { context: ., target: development }
    volumes:
      - .:/app
      - /app/node_modules               # anonymous volume prevents host override
    ports: ["3000:3000", "9229:9229"]
    command: ["npx", "nodemon", "--inspect=0.0.0.0:9229", "src/index.ts"]
```

The anonymous volume `/app/node_modules` prevents the host bind mount from overwriting platform-specific native modules (e.g., `esbuild`, `sharp`).

### Python Dev with Hot Reload

```yaml
services:
  api:
    build: { context: ., target: development }
    volumes: [".:/app"]
    ports: ["8000:8000"]
    command: ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0"]
```

---

## 9. Init Container Pattern

Use `service_completed_successfully` for tasks that must finish before the app starts.

```yaml
services:
  db:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d appdb"]
      interval: 5s
      timeout: 3s
      retries: 10
  db-migrate:
    image: myapp:2.0.0
    command: ["python", "manage.py", "migrate", "--noinput"]
    depends_on:
      db: { condition: service_healthy }
  db-seed:
    image: myapp:2.0.0
    command: ["python", "manage.py", "loaddata", "fixtures/reference.json"]
    depends_on:
      db-migrate: { condition: service_completed_successfully }
  app:
    image: myapp:2.0.0
    depends_on:
      db: { condition: service_healthy }
      db-seed: { condition: service_completed_successfully }
    ports: ["8080:8080"]
```

---

## 10. Sidecar Patterns

```yaml
services:
  # --- Log collector sidecar (shared volume) ---
  app:
    image: myapp:2.0.0
    volumes: [app-logs:/var/log/app]
  log-collector:
    image: fluent/fluent-bit:3.0
    volumes: ["app-logs:/var/log/app:ro", "./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro"]

  # --- Reverse proxy sidecar ---
  api:
    image: myapp:2.0.0
    expose: ["8080"]                    # no host port -- only through nginx
  nginx:
    image: nginx:1.27-alpine
    ports: ["443:443", "80:80"]
    volumes: ["./nginx.conf:/etc/nginx/nginx.conf:ro"]
    depends_on:
      api: { condition: service_healthy }

  # --- Debug sidecar (shared network namespace) ---
  debug:
    image: nicolaka/netshoot:v0.13
    profiles: [debug]
    network_mode: "service:app"         # shares app's network stack
    stdin_open: true
    tty: true

  # --- Build + serve (shared volume, init pattern) ---
  builder:
    image: node:22-alpine
    command: ["npm", "run", "build"]
    volumes: [".:/app", "assets:/app/dist"]
    working_dir: /app
  static-server:
    image: nginx:1.27-alpine
    volumes: ["assets:/usr/share/nginx/html:ro"]
    depends_on:
      builder: { condition: service_completed_successfully }

volumes:
  app-logs:
  assets:
```

---

## 11. Networking in Compose

```yaml
services:
  api:
    image: myapi:2.0.0
    networks: [frontend, backend]       # accessible from both
  web:
    image: nginx:1.27-alpine
    networks: [frontend]                # cannot reach db
    ports: ["80:80"]
  db:
    image: postgres:16-alpine
    networks: [backend]

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true                      # no external/internet access
```

**Aliases:** `networks: { backend: { aliases: [db, postgres] } }` -- service reachable by multiple names.

**External networks (cross-project):** Project A creates `networks: { shared: { name: shared-network } }`. Project B joins with `networks: { shared: { external: true, name: shared-network } }`.

---

## 12. Resource Limits

```yaml
services:
  app:
    image: myapp:2.0.0
    deploy:
      resources:
        limits: { memory: 512M, cpus: "1.0" }
        reservations: { memory: 256M, cpus: "0.5" }
      restart_policy: { condition: on-failure, delay: 5s, max_attempts: 3 }
    restart: unless-stopped
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
    pids_limit: 200
```

---

## 13. Production Patterns

```yaml
services:
  app:
    image: myapp:2.0.0
    read_only: true
    tmpfs: ["/tmp:size=100M"]
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    cap_add: [NET_BIND_SERVICE]
    user: "1001:1001"
    init: true
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    deploy:
      resources:
        limits: { memory: 512M, cpus: "1.0" }
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
```

**Rolling updates (Swarm):** `deploy: { replicas: 3, update_config: { parallelism: 1, delay: 10s, failure_action: rollback, order: start-first } }`

---

## 14. Full Stack Example -- Node.js + PostgreSQL + Redis

Combines secrets, healthchecks, init containers, profiles, anchors, watch mode, and multi-environment overrides.

```yaml
# compose.yaml -- production base
x-restart: &restart { restart: unless-stopped }

services:
  app:
    <<: *restart
    build: { context: ., target: production }
    ports: ["8080:8080"]
    environment: { NODE_ENV: production, DB_HOST: db, REDIS_URL: "redis://redis:6379" }
    secrets: [db_password]
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
      migrations: { condition: service_completed_successfully }
    init: true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 15s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits: { memory: 512M, cpus: "1.0" }
  db:
    <<: *restart
    image: postgres:16-alpine
    environment: { POSTGRES_DB: appdb, POSTGRES_USER: app, POSTGRES_PASSWORD_FILE: /run/secrets/db_password }
    secrets: [db_password]
    volumes: [db-data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d appdb"]
      interval: 5s
      timeout: 3s
      retries: 10
  redis:
    <<: *restart
    image: redis:7.2-alpine
    command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
  migrations:
    build: { context: ., target: production }
    command: ["node", "dist/migrate.js"]
    secrets: [db_password]
    depends_on:
      db: { condition: service_healthy }
  pgadmin:
    image: dpage/pgadmin4:8.4
    profiles: [tools]
    ports: ["5050:80"]
    environment: { PGADMIN_DEFAULT_EMAIL: dev@local.dev, PGADMIN_DEFAULT_PASSWORD: admin }

volumes:
  db-data:
secrets:
  db_password:
    file: ./secrets/db_password.txt
```

```yaml
# compose.override.yaml -- dev overrides (auto-loaded)
services:
  app:
    build: { context: ., target: development }
    volumes: [".:/app", "/app/node_modules"]
    ports: ["3000:3000", "9229:9229"]
    environment: { NODE_ENV: development, DATABASE_URL: "postgresql://dev:devpass@db:5432/devdb" }
    restart: "no"
    develop:
      watch:
        - action: sync
          path: ./src
          target: /app/src
        - action: rebuild
          path: ./package.json
  db:
    ports: ["5432:5432"]
  redis:
    ports: ["6379:6379"]
```

```bash
docker compose up -d                       # dev (auto-loads override)
docker compose --profile tools up -d       # dev + pgadmin
docker compose watch                       # hot reload
docker compose -f compose.yaml up -d       # prod (skips override)
docker compose down -v && docker compose up -d  # reset DB
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `depends_on` without health checks | Service starts before dependency is actually ready; connection errors on startup | Use `depends_on` with `condition: service_healthy` and define proper HEALTHCHECK in each service |
| Duplicating configuration across compose files | Drift between environments; a fix in dev compose is missed in prod compose | Use YAML anchors, extends, or override files (docker-compose.override.yml) for environment differences |
| Hardcoding secrets in compose files | Secrets in version control; anyone with repo access can extract credentials | Use Docker secrets, .env files (gitignored), or external secret managers; never commit credentials |
| Not setting resource limits (memory, CPU) | One runaway container consumes all host resources; brings down all services | Set `mem_limit` and `cpus` for every service; tune based on observed usage |
| Using bind mounts for database data in production | Host filesystem performance varies; no snapshot/backup integration; data loss on host failure | Use named volumes for database data; bind mounts only for development hot-reload scenarios |

---

## Related Skills

| Topic | Skill |
|---|---|
| Docker core concepts, Dockerfile, CLI, builds | `docker-fundamentals` |
| Basic Compose structure, cross-platform issues | `docker-admin` |
| Docker networking (bridge, overlay, DNS) | `docker-networking` |
| Volumes, bind mounts, storage drivers | `docker-storage` |
| Image scanning, rootless, security hardening | `docker-security` |
| CI/CD, multi-platform builds, registries | `docker-cicd` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |
