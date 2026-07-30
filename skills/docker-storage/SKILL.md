---
name: docker-storage
description: Use when managing Docker storage — volumes (named, anonymous), bind mounts, tmpfs mounts, volume drivers, backup and restore strategies, storage drivers (overlay2), disk usage management, data-only containers, volume plugins, and storage performance tuning. Part of the docker-* skill family. OS-agnostic.
family: docker
---

# Docker Storage

OS-agnostic Docker storage management. For core Docker concepts, see parent skill `docker-fundamentals`. For Compose patterns including volume declarations, see `docker-compose-patterns`. For OS-specific storage configuration, see `ubuntu-docker-host` or `rhel-docker-host`.

<HARD-RULE>
Volume deletion is permanent. `docker volume rm` and `docker volume prune` destroy data irreversibly. There is no recycle bin, no undo. Always back up volumes before removing them. Double-check volume names before any destructive operation.
</HARD-RULE>

<HARD-RULE>
Never store database data in the container's writable layer. Always use a named volume or bind mount for database files (PostgreSQL data dir, MySQL data dir, etc.). The writable layer is lost when the container is removed, uses the slower storage driver, and cannot be shared or backed up cleanly.
</HARD-RULE>

<HARD-RULE>
Bind mounts expose host filesystem paths directly to the container. A container with a bind mount to `/` or `/etc` can read and modify critical host files. Never bind-mount sensitive host directories into untrusted containers. Prefer named volumes when host path access is not required.
</HARD-RULE>

---

## Storage Types Comparison

| Feature | Named Volume | Bind Mount | tmpfs Mount |
|---|---|---|---|
| Managed by Docker | Yes | No | No (memory-backed) |
| Host location | `/var/lib/docker/volumes/` | Any host path | RAM only |
| Pre-populated from image | Yes | No (host overwrites) | No |
| Supports volume drivers | Yes | No | No |
| Shareable between containers | Yes | Yes | No |
| Survives container removal | Yes | Yes (host files remain) | No |
| Performance | Near-native | Native | Fastest (RAM) |
| Portability | High (Docker-managed) | Low (host-path dependent) | N/A |
| Use case | Persistent app data, DBs | Source code (dev), config | Secrets, scratch space |

**When to use each:**
- **Named volumes** — production databases, persistent application data, anything that must survive container lifecycle. Default choice.
- **Bind mounts** — development workflows (live code reload), sharing specific host files, host-level config.
- **tmpfs mounts** — sensitive data that must never touch disk (secrets, tokens), temporary scratch space, ephemeral caches.

---

## Named Volumes

```bash
# Create, list, inspect
docker volume create mydata
docker volume create --label project=webapp --label env=prod mydata
docker volume ls
docker volume ls --filter label=project=webapp
docker volume ls --filter dangling=true          # not attached to any container
docker volume inspect mydata

# Mount at run time
docker run -d --name db -v mydata:/var/lib/postgresql/data postgres:16
docker run -d --name db --mount source=mydata,target=/var/lib/postgresql/data postgres:16

# Read-only mount
docker run -d -v mydata:/data:ro myapp
docker run -d --mount source=mydata,target=/data,readonly myapp

# Anonymous volume (Docker generates random name)
docker run -d -v /var/lib/data myapp

# Remove
docker volume rm mydata
docker volume prune
docker volume prune --filter label=env=dev
```

### Pre-Populating Volumes from Images

When a named volume is mounted to a directory that already has content in the image, Docker copies that content into the volume on first mount (volume must be empty). This does not work with bind mounts.

```bash
docker volume create app-config
docker run -d -v app-config:/app/default-config myapp
docker run --rm -v app-config:/data alpine ls -la /data   # verify
```

---

## Bind Mounts

```bash
# -v syntax: source:target[:options]
docker run -d -v /host/path:/container/path myapp
docker run -d -v /host/path:/container/path:ro myapp
docker run -d -v "$(pwd)/src":/app/src myapp

# --mount syntax (recommended — fails if source missing, catches errors early)
docker run -d --mount type=bind,source=/host/path,target=/container/path myapp
docker run -d --mount type=bind,source=/host/path,target=/container/path,readonly myapp

# Combine read-only config with read-write data
docker run -d -v /host/config:/app/config:ro -v /host/data:/app/data myapp
```

Key difference: `-v` auto-creates the host directory if missing. `--mount` errors out. Prefer `--mount` in scripts and production.

### Consistency Options (macOS Docker Desktop)

On macOS, bind mounts go through a virtualization layer. These flags tune consistency vs performance (no effect on Linux):

```bash
docker run -v $(pwd):/app:consistent myapp    # default, full consistency, slowest
docker run -v $(pwd):/app:cached myapp        # host authoritative, brief stale reads in container
docker run -v $(pwd):/app:delegated myapp     # container authoritative, fastest
```

---

## tmpfs Mounts

Stored in host memory only. Data never touches disk and is lost when the container stops.

```bash
# Basic
docker run -d --tmpfs /tmp myapp
docker run -d --mount type=tmpfs,target=/tmp myapp

# With size limit and permissions
docker run -d --mount type=tmpfs,target=/run/secrets,tmpfs-size=64m,tmpfs-mode=0700 myapp

# Multiple tmpfs mounts
docker run -d --tmpfs /tmp:size=100m --tmpfs /run/secrets:size=10m,mode=0700 myapp

# Use cases: secrets (never on disk), scratch space, ephemeral cache
docker run -d \
  --mount type=tmpfs,target=/run/secrets,tmpfs-size=1m,tmpfs-mode=0700 \
  --mount type=tmpfs,target=/tmp/scratch,tmpfs-size=512m \
  myapp
```

---

## Volume Drivers

### Local Driver with NFS, CIFS, tmpfs

```bash
# NFS volume
docker volume create --driver local \
  --opt type=nfs \
  --opt o=addr=192.168.1.100,rw,nfsvers=4 \
  --opt device=:/export/data \
  nfs-data

# CIFS/SMB volume
docker volume create --driver local \
  --opt type=cifs \
  --opt o=addr=192.168.1.100,username=user,password=pass,file_mode=0644,dir_mode=0755 \
  --opt device=//192.168.1.100/share \
  cifs-data

# tmpfs volume (named, Docker-managed)
docker volume create --driver local \
  --opt type=tmpfs --opt device=tmpfs --opt o=size=256m \
  tmpfs-vol

docker run -d -v nfs-data:/data myapp
```

### Third-Party Volume Drivers

```bash
# Install plugins
docker plugin install rexray/ebs                 # AWS EBS
docker plugin install portworx/px-dev            # Portworx
docker plugin install netapp/trident             # NetApp Trident
docker plugin ls

# Create and use volume with third-party driver
docker volume create --driver rexray/ebs --opt size=100 --opt volumeType=gp3 ebs-volume
docker run -d -v ebs-volume:/data myapp
```

### NFS Volume in Compose

```yaml
services:
  app:
    image: myapp
    volumes:
      - nfs-data:/data

volumes:
  nfs-data:
    driver: local
    driver_opts:
      type: nfs
      o: addr=192.168.1.100,rw,nfsvers=4
      device: ":/export/data"
```

---

## Backup and Restore

### Volume to/from Tar Archive

```bash
# Backup named volume
docker run --rm -v mydata:/source:ro -v $(pwd):/backup \
  alpine tar czf /backup/mydata-$(date +%Y%m%d-%H%M%S).tar.gz -C /source .

# Backup using --volumes-from
docker run --rm --volumes-from db_container:ro -v $(pwd):/backup \
  alpine tar czf /backup/db-backup.tar.gz -C /var/lib/postgresql/data .

# Restore into a new volume
docker volume create mydata-restored
docker run --rm -v mydata-restored:/target -v $(pwd):/backup:ro \
  alpine sh -c "tar xzf /backup/mydata-20250101-120000.tar.gz -C /target"
docker run --rm -v mydata-restored:/data alpine ls -la /data   # verify
```

### Database Backup (pg_dump / mysqldump)

```bash
# PostgreSQL
docker exec db pg_dump -U postgres -d mydb > mydb-$(date +%Y%m%d).sql
docker exec db pg_dump -U postgres -Fc mydb > mydb-$(date +%Y%m%d).dump
docker exec -i new_db psql -U postgres -d mydb < mydb-20250101.sql
docker exec -i new_db pg_restore -U postgres -d mydb < mydb-20250101.dump

# MySQL / MariaDB
docker exec db mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" mydb > mydb-$(date +%Y%m%d).sql
docker exec db mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" --all-databases > all-dbs.sql
docker exec -i new_db mysql -u root -p"$MYSQL_ROOT_PASSWORD" mydb < mydb-20250101.sql
```

### Rsync Pattern (Incremental)

```bash
docker run --rm -v mydata:/source:ro -v /backup/mydata:/dest \
  alpine sh -c "apk add --no-cache rsync && rsync -av /source/ /dest/"
```

### Automated Backup Script

```bash
#!/usr/bin/env bash
# backup-volumes.sh — back up all volumes labeled backup=true
set -euo pipefail
BACKUP_DIR="/backup/docker-volumes"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"

for vol in $(docker volume ls --filter label=backup=true -q); do
  echo "Backing up volume: $vol"
  docker run --rm -v "$vol":/source:ro -v "$BACKUP_DIR":/backup \
    alpine tar czf "/backup/${vol}-${TIMESTAMP}.tar.gz" -C /source .
done

find "$BACKUP_DIR" -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete
echo "Backup complete. Removed archives older than $RETENTION_DAYS days."
```

---

## Storage Drivers

Storage drivers control how image layers and the container writable layer are stored on disk.

```bash
docker info --format '{{.Driver}}'               # check current driver
docker info | grep -A5 "Storage Driver"          # detailed info
```

### overlay2 (Recommended)

Default and recommended for all supported Linux distributions.

```jsonc
// /etc/docker/daemon.json
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.size=20G"    // per-container writable layer limit (optional, xfs + pquota only)
  ]
}
```

### Storage Driver Selection

| Driver | Backing Filesystem | Status |
|---|---|---|
| `overlay2` | xfs (d_type=true), ext4 | Recommended, default |
| `fuse-overlayfs` | any | Rootless mode only |
| `btrfs` | btrfs | If btrfs already in use |
| `zfs` | zfs | If zfs already in use |
| `vfs` | any | No copy-on-write, testing only |
| `devicemapper` | direct-lvm | Deprecated |
| `aufs` | ext4, xfs | Deprecated, removed in recent kernels |

```bash
# Verify xfs d_type support (required for overlay2 on xfs)
xfs_info /var/lib/docker | grep ftype    # ftype=1 = supported

# Changing storage driver resets all images/containers — plan carefully
sudo systemctl stop docker
# Edit /etc/docker/daemon.json
sudo systemctl start docker
```

---

## Disk Usage Management

```bash
# Overview
docker system df
docker system df -v                              # detailed

# Find largest images
docker images --format "{{.Repository}}:{{.Tag}}\t{{.Size}}" | sort -k2 -h

# Check a specific volume's size
docker run --rm -v mydata:/data alpine du -sh /data

# Docker root directory breakdown
du -sh /var/lib/docker/{overlay2,volumes,image,buildkit}/
```

### Pruning Strategies

```bash
# Conservative: dangling images + stopped containers
docker system prune

# Moderate: all unused images
docker system prune -a

# Aggressive: unused images + volumes (DESTRUCTIVE)
docker system prune -a --volumes

# Targeted
docker image prune -a --filter "until=24h"
docker volume prune --filter label=env=dev
docker builder prune --keep-storage 5GB
docker builder prune --filter until=72h
```

### Disk Monitoring

```bash
#!/usr/bin/env bash
# check-docker-disk.sh — alert when Docker partition is full
THRESHOLD=80
USAGE=$(df /var/lib/docker --output=pcent | tail -1 | tr -d ' %')
if [ "$USAGE" -gt "$THRESHOLD" ]; then
  echo "Docker disk usage at ${USAGE}% — consider pruning" | \
    mail -s "Docker Disk Warning" ops@example.com
fi
```

---

## Volumes in Compose

### Named Volumes, External Volumes, Driver Options

```yaml
services:
  postgres:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: secret

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    command: redis-server --appendonly yes

volumes:
  pgdata:
  redisdata:
    labels:
      backup: "true"

  # External volume (must exist: docker volume create shared-data)
  shared-data:
    external: true

  # NFS driver options
  nfs-data:
    driver: local
    driver_opts:
      type: nfs
      o: addr=192.168.1.100,rw,nfsvers=4
      device: ":/export/data"

  # tmpfs driver options
  tmpfs-scratch:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=256m,uid=1000
```

### Shared Volumes and Bind Mounts in Compose

```yaml
services:
  writer:
    image: myapp-writer
    volumes:
      - shared-uploads:/uploads

  reader:
    image: nginx:alpine
    volumes:
      - shared-uploads:/usr/share/nginx/html/uploads:ro

  app:
    build: .
    volumes:
      # Short syntax bind mounts
      - ./src:/app/src
      - ./config:/app/config:ro
      # Long syntax (recommended)
      - type: bind
        source: ./src
        target: /app/src
      # Anonymous volume to protect node_modules from bind mount override
      - /app/node_modules

volumes:
  shared-uploads:
```

---

## Data-Only Containers (Legacy Pattern)

This pattern predates named volumes. Still encountered in older projects.

```bash
# Legacy: create a container that is never started, only holds volume definitions
docker create --name db-data -v /var/lib/postgresql/data postgres:16 /bin/true
docker run -d --name db --volumes-from db-data postgres:16
docker run --rm --volumes-from db-data -v $(pwd):/backup alpine \
  tar czf /backup/db-data.tar.gz -C /var/lib/postgresql/data .
```

**Modern alternative** — named volumes are simpler, explicitly named, and do not require a stopped container:

```bash
docker volume create pgdata
docker run -d --name db -v pgdata:/var/lib/postgresql/data postgres:16
docker run --rm -v pgdata:/source:ro -v $(pwd):/backup alpine \
  tar czf /backup/pgdata.tar.gz -C /source .
```

---

## Performance

### Storage Driver Performance (overlay2)

- **Read-heavy** — excellent; reads go directly to image layers via the overlay filesystem.
- **Write-heavy** — first write to a file triggers copy-up from lower layer; subsequent writes are fast.
- **Many layers** — overlay2 handles many layers efficiently (no 128-layer limit of the old overlay driver).

### Volume Mount Performance

- **Linux** — named volumes and bind mounts have near-native filesystem performance.
- **macOS Docker Desktop** — bind mounts go through a virtualization layer. Use VirtioFS (default in recent Docker Desktop). Avoid syncing large `node_modules`; use anonymous volumes: `docker run -v $(pwd):/app -v /app/node_modules myapp`.
- **Windows Docker Desktop** — WSL 2 backend recommended. Store project files inside WSL 2 filesystem.

### I/O Tuning

```bash
# Block I/O weight (relative, 10-1000, default 500)
docker run -d --blkio-weight 300 myapp
docker run -d --blkio-weight 800 myapp

# Device read/write rate limits
docker run -d --device-read-bps /dev/sda:10mb --device-write-bps /dev/sda:10mb myapp

# Device IOPS limits
docker run -d --device-read-iops /dev/sda:1000 --device-write-iops /dev/sda:1000 myapp
```

### Performance Checklist

| Workload | Recommended Storage | Avoid |
|---|---|---|
| Production database | Named volume on SSD/NVMe | Container writable layer, NFS |
| Application logs | Docker logging driver (stdout) | Volume or writable layer files |
| Dev live-reload | Bind mount + anonymous vol for deps | Named volume (no host sync) |
| Shared static assets | Named volume or NFS volume | Bind mount (not portable) |
| Secrets at runtime | tmpfs mount | Bind mount, volume, env vars in logs |
| Build cache | BuildKit cache mount | Copying into image layer |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using bind mounts for database data in production | No Docker-managed lifecycle; no easy backup/restore; host path dependencies break portability | Use named volumes for persistent data; bind mounts only for development live-reload |
| Never pruning unused volumes | Orphaned volumes accumulate gigabytes of disk; `docker system df` shows growing volume waste | Schedule `docker volume prune` in maintenance windows; monitor disk usage with alerts |
| Storing application logs in writable container layer | Container removal loses logs; writable layer uses copy-on-write which is slow; disk fills up | Use Docker logging drivers (stdout/stderr) or mount a log volume; ship to centralized logging |
| Using anonymous volumes for important data | Cannot be easily identified, backed up, or migrated; lost when container is removed with `-v` flag | Always use named volumes for data that needs to persist; name them descriptively |
| Writing temp files to container filesystem without tmpfs | Disk I/O for temp files is slow through overlay2; temp data persists unnecessarily | Use `--tmpfs /tmp` for temporary scratch space; faster and automatically cleaned |

---

## Related Skills

| Topic | Skill |
|---|---|
| Core Docker CLI, Dockerfile, lifecycle | `docker-fundamentals` |
| Bridge, overlay, DNS, network security | `docker-networking` |
| Image scanning, rootless, secrets, CIS | `docker-security` |
| CI/CD pipelines, registries, multi-arch | `docker-cicd` |
| Compose patterns, profiles, overrides | `docker-compose-patterns` |
| Cross-platform Docker admin, AD mapping | `docker-admin` |
| Docker on Ubuntu 24.04 | `ubuntu-docker-host` |
| Podman/Docker on RHEL 9 | `rhel-docker-host` |
