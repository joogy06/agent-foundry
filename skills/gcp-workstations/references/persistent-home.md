# Persistent Home

GCP Workstations decouples the user's home directory from the running workstation instance. This section documents what survives, what doesn't, and the implications for an AI dev environment.

## What persists

| Path | Persists across stop/start? | Persists across delete-workstation? | Notes |
|---|---|---|---|
| `/home/<user>` (== `$HOME`) | YES | YES | The persistent disk is the unit of persistence; lives independently of the workstation instance |
| Files inside `$HOME` (anywhere) | YES | YES | Same as above |
| `~/.claude/`, `~/.gemini/`, `~/.copilot/`, `~/.config/gh/` | YES | YES | All AI CLI configs survive |
| `~/.npm/`, `~/.cargo/`, `~/.npm-global/`, `~/.local/` | YES | YES | User-installed package caches |
| Git repos under `$HOME` | YES | YES | |
| Customised `~/.bashrc`, `~/.profile`, `~/.gitconfig` | YES | YES | |

## What does NOT persist

| Path | Status |
|---|---|
| `/var` | LOST on restart |
| `/tmp` | LOST on restart |
| `/etc` | LOST on restart |
| `/usr` (including `/usr/local`) | LOST on restart |
| `/root` (if you run as root) | LOST on restart |
| Hidden caches outside `$HOME` (e.g. `/root/.cache`) | LOST on restart |
| Anything `apt install`ed at runtime | LOST on restart |

## Implications

### #1: Bake everything important into the custom image

Anything you want available after restart must be in the Dockerfile. Build once, restart often.

```dockerfile
# In scripts/Dockerfile.ai-dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsecret-1-0 chrony git curl jq python3 pipx vim tmux gh \
 && rm -rf /var/lib/apt/lists/*
```

NOT this:

```bash
# Inside the workstation
sudo apt install some-tool   # GONE on next restart
```

### #2: Watch for tools that store state outside $HOME

Some tools default to caches outside `$HOME`:

| Tool | Bad default | Workaround |
|---|---|---|
| Many Python tools | `/root/.cache/pip` | `pip install --user` (puts caches in `~/.local`) or set `XDG_CACHE_HOME=$HOME/.cache` |
| `pipx` | `~/.local/pipx` | already in `$HOME`, fine |
| Docker (DinD) | `/var/lib/docker` | Configure `data-root` to a path inside `$HOME`, or use a separate persistent disk |
| `tmpfile` for big builds | `/tmp` | Use `$HOME/tmp` |
| `/var/cache/apt` | `/var/cache/apt` | Bake `apt install` into Dockerfile, don't install at runtime |

Audit any tool that creates files outside `$HOME` and either:
1. Configure it to write to `$HOME`
2. Bake the result into the image instead of generating at runtime

### #3: Persistent disk size matters

GCP Workstations attaches a persistent disk for `$HOME`. Default is 200 GB pd-ssd in this skill's recommendation. Tune via:

```bash
gcloud workstations configs update ai-dev-config \
  --pd-disk-size=500 \    # GB
  --pd-disk-type=pd-ssd \
  --cluster=... --region=...
```

200 GB is comfortable for most dev workflows. If you store large datasets locally, bump it.

### #4: Persistent disk lives across workstation deletes

Deleting `my-station` does NOT delete the persistent disk by default. The disk hangs around as an unattached resource and can be reattached to a new workstation.

To delete the disk:

```bash
gcloud workstations workstations delete my-station \
  --cluster=... --config=... --region=... \
  --delete-storage   # explicit flag to delete the disk
```

Without `--delete-storage`, you keep paying for the disk. Audit unattached disks periodically:

```bash
gcloud compute disks list --filter='-users:*'
```

### #5: Snapshots are your friend

The persistent disk supports GCE disk snapshots. Take periodic snapshots to protect against accidental file deletion:

```bash
gcloud compute disks snapshot <disk-name> \
  --snapshot-names=ai-dev-$(date +%Y%m%d) \
  --zone=us-central1-a
```

Automate via Compute Engine resource policies (snapshot schedules).

## Quick verification on a fresh workstation

Run these commands on the running workstation to confirm what's persistent:

```bash
echo "test-$(date +%s)" > ~/persistence-test.txt
echo "test-$(date +%s)" > /tmp/persistence-test.txt
echo "test-$(date +%s)" | sudo tee /var/persistence-test.txt
echo "test-$(date +%s)" | sudo tee /etc/persistence-test.txt

# Stop and start
gcloud workstations stop my-station ...
gcloud workstations start my-station ...

# Check
cat ~/persistence-test.txt        # SHOULD survive
cat /tmp/persistence-test.txt    # GONE
cat /var/persistence-test.txt    # GONE
cat /etc/persistence-test.txt    # GONE
```

## Anti-patterns

| Don't | Why |
|---|---|
| `apt install` at runtime | Lost on restart |
| Store databases/big files in `/var` | Lost on restart |
| Customise `/etc/hosts` at runtime | Lost on restart. Use a startup script or bake into image. |
| Forget `--delete-storage` when deleting workstations | Pays for disk forever |
| Skip snapshots | One `rm -rf` and your dev env is gone |
| Assume `$HOME` is a tmpfs | It's a real disk; treat normally |
