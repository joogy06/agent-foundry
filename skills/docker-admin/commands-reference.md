# Docker Commands Reference

## Container Lifecycle

| Command | Purpose |
|---------|---------|
| `docker run -d --name c1 image` | Create and start container |
| `docker run -it --rm image bash` | Interactive, remove on exit |
| `docker start/stop/restart c1` | Manage running state |
| `docker kill c1` | Force stop (SIGKILL) |
| `docker rm c1` | Remove stopped container |
| `docker rm -f c1` | Force remove running container |
| `docker pause/unpause c1` | Freeze/unfreeze |
| `docker rename old new` | Rename container |
| `docker update --memory 512m c1` | Update limits on running container |

## Debugging

| Command | Purpose |
|---------|---------|
| `docker logs -f --tail 100 c1` | Stream last 100 log lines |
| `docker logs --since 1h c1` | Logs from last hour |
| `docker exec -it c1 bash` | Shell into running container |
| `docker exec -it c1 sh` | Shell (Alpine/minimal) |
| `docker inspect c1` | Full container metadata (JSON) |
| `docker inspect -f '{{.State.Health}}' c1` | Health status |
| `docker inspect -f '{{.NetworkSettings.IPAddress}}' c1` | Container IP |
| `docker top c1` | Running processes |
| `docker stats` | Live resource usage (CPU, memory, I/O) |
| `docker stats --no-stream` | Snapshot (no live update) |
| `docker diff c1` | Changed files since start |
| `docker cp c1:/path/file ./local` | Copy file from container |
| `docker cp ./local c1:/path/file` | Copy file to container |
| `docker events --filter container=c1` | Real-time events |

## Images

| Command | Purpose |
|---------|---------|
| `docker build -t name:tag .` | Build image |
| `docker build --no-cache -t name:tag .` | Build without cache |
| `docker buildx build --platform linux/amd64,linux/arm64 -t name .` | Multi-platform |
| `docker pull image:tag` | Download image |
| `docker push registry/image:tag` | Upload image |
| `docker tag image:old image:new` | Add tag |
| `docker images` | List local images |
| `docker image ls --filter dangling=true` | Untagged images |
| `docker rmi image:tag` | Remove image |
| `docker save image:tag > file.tar` | Export to tarball |
| `docker load < file.tar` | Import from tarball |
| `docker history image:tag` | Show layer history |
| `docker scout cves image:tag` | Vulnerability scan |
| `docker scout recommendations image:tag` | Base image suggestions |

## Volumes

| Command | Purpose |
|---------|---------|
| `docker volume create vol1` | Create named volume |
| `docker volume ls` | List volumes |
| `docker volume inspect vol1` | Volume details |
| `docker volume rm vol1` | Remove volume |
| `docker volume prune` | Remove unused volumes |
| `-v vol1:/data` | Named volume mount |
| `-v ./host:/data` | Bind mount |
| `-v ./host:/data:ro` | Read-only bind mount |
| `--tmpfs /tmp` | tmpfs mount (RAM, ephemeral) |

## Networks

| Command | Purpose |
|---------|---------|
| `docker network create net1` | Create network |
| `docker network ls` | List networks |
| `docker network inspect net1` | Network details |
| `docker network connect net1 c1` | Attach container |
| `docker network disconnect net1 c1` | Detach container |
| `docker network rm net1` | Remove network |
| `docker network prune` | Remove unused networks |

## System / Cleanup

| Command | Purpose |
|---------|---------|
| `docker system df` | Disk usage summary |
| `docker system df -v` | Detailed disk usage |
| `docker system prune` | Remove stopped containers + dangling images + unused networks |
| `docker system prune -a` | Also remove all unused images (careful!) |
| `docker system prune -a --volumes` | Nuclear option — removes everything unused |
| `docker info` | System-wide info (storage driver, runtime, etc.) |

## Compose (V2)

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start all services (detached) |
| `docker compose up -d --build` | Rebuild then start |
| `docker compose up -d service` | Start one service |
| `docker compose down` | Stop and remove containers + networks |
| `docker compose down -v` | Also remove volumes |
| `docker compose logs -f` | Stream all logs |
| `docker compose logs -f service` | Stream one service |
| `docker compose exec service bash` | Shell into service |
| `docker compose ps` | List running services |
| `docker compose top` | Processes in all services |
| `docker compose pull` | Pull latest images |
| `docker compose build --no-cache` | Rebuild all from scratch |
| `docker compose restart service` | Restart one service |
| `docker compose --profile debug up` | Start with optional profile |
| `docker compose config` | Validate and show resolved compose file |
| `docker compose watch` | Development hot-reload mode |
| `docker compose cp service:/path ./local` | Copy from service |

## Useful Run Flags

| Flag | Purpose |
|------|---------|
| `-d` | Detached (background) |
| `-it` | Interactive + TTY (shell access) |
| `--rm` | Remove container on exit |
| `--name c1` | Name the container |
| `-p 8080:80` | Port mapping (host:container) |
| `-e VAR=val` | Environment variable |
| `--env-file .env` | Env file |
| `-v vol:/path` | Volume mount |
| `--network net1` | Attach to network |
| `--restart unless-stopped` | Restart policy |
| `--init` | Use tini init process |
| `--read-only` | Read-only root filesystem |
| `--cap-drop ALL` | Drop all capabilities |
| `--security-opt=no-new-privileges` | Prevent privilege escalation |
| `--user 1001:1001` | Run as specific UID:GID |
| `--memory 512m` | Memory limit |
| `--cpus 1.5` | CPU limit |
