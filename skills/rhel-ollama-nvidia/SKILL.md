---
name: rhel-ollama-nvidia
description: Use when setting up NVIDIA GPUs, CUDA, container toolkit, or Ollama on RHEL 9 (and AlmaLinux/Rocky 9) — driver installation via NVIDIA repo or ELRepo, CUDA toolkit, cuDNN, NVIDIA Container Toolkit for Podman and Docker, Ollama installation and model management, GPU monitoring (nvidia-smi), vGPU basics, multi-GPU configuration, SELinux considerations, and troubleshooting. Part of the rhel-* skill family.
---

# RHEL 9 -- NVIDIA GPU & Ollama Administration

Companion skill to `rhel-server-admin` covering GPU compute and local LLM workloads on Red Hat Enterprise Linux 9.x (and compatible: AlmaLinux 9, Rocky Linux 9, Oracle Linux 9). See also: `rhel-docker-host`, `rhel-monitoring`.

<HARD-RULE>
Kernel updates can break NVIDIA drivers. Use `dnf versionlock` to pin your kernel and driver packages before `dnf update` on production GPU nodes. Always have out-of-band access (IPMI/iLO, console) before driver changes.
```bash
sudo dnf install python3-dnf-plugin-versionlock
sudo dnf versionlock add nvidia-driver-latest-dkms kernel-$(uname -r) kernel-devel-$(uname -r) kernel-headers-$(uname -r)
dnf versionlock list
```
</HARD-RULE>

<HARD-RULE>
Never disable SELinux to fix GPU issues. If SELinux blocks GPU access, create a targeted policy module or set the correct boolean -- do not set `SELINUX=disabled`. See Troubleshooting section 10 for specific GPU-related SELinux fixes.
</HARD-RULE>

<HARD-RULE>
Secure Boot requires MOK (Machine Owner Key) enrollment for DKMS-built NVIDIA modules. If you skip MOK enrollment at the blue boot screen, the driver will NOT load. Re-trigger with `sudo dkms autoinstall` then reboot and complete enrollment. Alternatively, disable Secure Boot in BIOS if permitted by your security policy.
</HARD-RULE>

---

## 1. NVIDIA Driver Installation

### Prerequisites

```bash
# Verify RHEL 9 version and kernel
cat /etc/redhat-release
uname -r

# Install required build dependencies
sudo dnf install kernel-devel-$(uname -r) kernel-headers-$(uname -r) gcc make dkms -y

# EPEL is needed for dkms and some dependencies
sudo dnf install epel-release -y                          # AlmaLinux/Rocky
# For RHEL:
# sudo dnf install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm

# Enable CodeReady Builder / CRB (needed for some development headers)
sudo dnf config-manager --set-enabled crb                  # AlmaLinux/Rocky
# RHEL: sudo subscription-manager repos --enable codeready-builder-for-rhel-9-x86_64-rpms
```

### Method A: NVIDIA CUDA Repository (Recommended)

```bash
# Add NVIDIA CUDA repo for RHEL 9
sudo dnf config-manager --add-repo \
  https://developer.download.nvidia.com/compute/cuda/repos/rhel9/x86_64/cuda-rhel9.repo

# Install latest driver (DKMS -- rebuilds on kernel update)
sudo dnf module install nvidia-driver:latest-dkms -y

# Or install specific branch
sudo dnf module install nvidia-driver:560-dkms -y

# Precompiled kmod (no DKMS, no kernel-devel needed -- but tied to specific kernel)
sudo dnf module install nvidia-driver:latest -y
```

### Method B: ELRepo kmod-nvidia

```bash
# Add ELRepo (provides precompiled kmod packages)
sudo dnf install https://www.elrepo.org/elrepo-release-9.el9.elrepo.noarch.rpm -y
sudo rpm --import https://www.elrepo.org/RPM-GPG-KEY-elrepo.org

# Install precompiled driver (kmod -- tied to stock RHEL kernel)
sudo dnf install kmod-nvidia -y
# ELRepo kmod rebuilds are published within days of new RHEL kernels
```

| Method | Pros | Cons |
|---|---|---|
| NVIDIA repo DKMS | Rebuilds for any kernel, latest drivers | Needs kernel-devel, gcc, build time |
| NVIDIA repo kmod | No build tools needed, fast | Only NVIDIA-shipped kernels |
| ELRepo kmod | Tracks RHEL stock kernels, simple | Slight delay after kernel releases |

### Blacklist Nouveau

```bash
# The NVIDIA repo packages usually handle this, but verify/force:
sudo tee /etc/modprobe.d/blacklist-nouveau.conf > /dev/null <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF

# Rebuild initramfs and reboot
sudo dracut --force && sudo reboot
```

### Verify Installation

```bash
nvidia-smi                            # GPU info, driver + CUDA runtime version
cat /proc/driver/nvidia/version       # kernel module details
lsmod | grep nvidia                   # loaded modules (nvidia, nvidia_drm, nvidia_modeset, nvidia_uvm)
dkms status                           # DKMS module state (if DKMS method)

# Secure Boot check
mokutil --sb-state
# If driver fails after install: reboot -> blue MOK Manager -> Enroll MOK -> enter password set during dkms install
```

| Architecture | Proprietary | nvidia-open |
|---|---|---|
| Maxwell / Pascal (GTX 10xx) | Supported | NOT supported |
| Turing (RTX 20xx / T4) | Supported | Supported |
| Ampere (RTX 30xx / A100) | Supported | Recommended |
| Ada Lovelace (RTX 40xx / L40) | Supported | Recommended |
| Hopper / Blackwell (H100/B200) | Supported | Required |

```bash
# Open kernel module variant (Turing+ only)
sudo dnf module install nvidia-driver:latest-dkms --setopt=nvidia-driver.default_stream=open -y
```

---

## 2. CUDA Toolkit

<HARD-RULE>
Do NOT install CUDA from EPEL or default RHEL repos -- use NVIDIA's official CUDA repository. The repo was added in section 1 Method A; if you used ELRepo for the driver, add the CUDA repo now.
</HARD-RULE>

```bash
# Ensure NVIDIA CUDA repo is present
sudo dnf config-manager --add-repo \
  https://developer.download.nvidia.com/compute/cuda/repos/rhel9/x86_64/cuda-rhel9.repo

# Install CUDA toolkit (does NOT reinstall the driver if already present)
sudo dnf install cuda-toolkit -y              # latest
sudo dnf install cuda-toolkit-12-6 -y         # specific version

# Environment variables -- add system-wide
sudo tee /etc/profile.d/cuda.sh > /dev/null <<'EOF'
export PATH=/usr/local/cuda/bin${PATH:+:${PATH}}
export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
EOF
source /etc/profile.d/cuda.sh

# Verify
nvcc --version
ls -la /usr/local/cuda                        # symlink to active version

# Multiple versions side-by-side
sudo dnf install cuda-toolkit-12-4 cuda-toolkit-12-6 -y
# Switch: update the symlink
sudo rm /usr/local/cuda && sudo ln -s /usr/local/cuda-12.4 /usr/local/cuda
# Or per-session: export PATH=/usr/local/cuda-12.6/bin:$PATH
```

| CUDA Version | Minimum Driver | Notes |
|---|---|---|
| 12.6.x | 560.28+ | Current recommended |
| 12.4.x | 550.54+ | Widely deployed |
| 12.2.x | 535.86+ | LTS-friendly |
| 11.8.x | 520.61+ | Legacy workloads |

Full matrix: https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/

---

## 3. cuDNN

```bash
# Install from NVIDIA CUDA repo (added in section 1/2)
sudo dnf install libcudnn9-cuda-12 libcudnn9-devel-cuda-12 -y
rpm -qa | grep cudnn                          # verify version

# cuDNN 9.x pairs with CUDA 12.x
# cuDNN 8.x pairs with CUDA 11.x/12.x (legacy workloads)

# If packages not found, ensure the CUDA repo is enabled:
dnf repolist | grep cuda
```

---

## 4. NVIDIA Container Toolkit

Works with both Podman (RHEL default) and Docker on RHEL 9.

### Installation

```bash
# Add the NVIDIA Container Toolkit repo
curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
  sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo

sudo dnf install nvidia-container-toolkit -y
```

### Podman Integration (CDI -- Container Device Interface)

```bash
# Generate CDI specification for NVIDIA GPUs
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml

# Verify CDI devices are visible
nvidia-ctk cdi list

# Run container with GPU access via CDI
podman run --rm --device nvidia.com/gpu=all \
  nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi

# Specific GPU
podman run --rm --device nvidia.com/gpu=0 \
  nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi

# Rootless Podman with GPU (CDI works rootless out of the box)
nvidia-ctk cdi generate --output=$HOME/.config/containers/cdi/nvidia.yaml
podman run --rm --device nvidia.com/gpu=all \
  nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi
```

<HARD-RULE>
On RHEL 9, Podman uses CDI (`--device nvidia.com/gpu=all`) for GPU access, NOT the `--gpus` flag. The `--gpus` flag is Docker-specific. Regenerate CDI specs after driver upgrades: `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`.
</HARD-RULE>

### Docker Integration

```bash
# If Docker CE is installed (see rhel-docker-host)
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Test
docker run --rm --gpus all nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi

# Specific GPUs
docker run --rm --gpus '"device=0,1"' nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi
```

### Docker Compose GPU Reservation

```yaml
services:
  cuda-app:
    image: nvcr.io/nvidia/cuda:12.6.3-base-ubi9
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all            # or 1, 2, etc.
              capabilities: [gpu]
            # Alternative: device_ids: ["0", "1"]
```

---

## 5. Ollama -- Local LLM Serving

### Installation (Recommended)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version && systemctl status ollama

# Open firewall if needed for network access
sudo firewall-cmd --permanent --add-port=11434/tcp
sudo firewall-cmd --reload
```

### Manual Installation with Systemd

```bash
sudo curl -L https://ollama.com/download/ollama-linux-amd64.tgz -o /tmp/ollama.tgz
sudo tar -xzf /tmp/ollama.tgz -C /usr
sudo useradd -r -s /sbin/nologin -m -d /usr/share/ollama ollama
sudo usermod -aG video ollama
sudo usermod -aG render ollama                 # needed for some GPU access on RHEL

sudo tee /etc/systemd/system/ollama.service > /dev/null <<'EOF'
[Unit]
Description=Ollama Service
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="HOME=/usr/share/ollama"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Environment="OLLAMA_HOST=0.0.0.0:11434"
# Environment="OLLAMA_MODELS=/data/ollama/models"
# Environment="OLLAMA_NUM_PARALLEL=4"
# Environment="OLLAMA_MAX_LOADED_MODELS=2"

[Install]
WantedBy=default.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now ollama
```

### Model Management

```bash
ollama pull llama3.1:8b                        # download
ollama pull llama3.1:70b-instruct-q4_K_M       # quantised variant
ollama list                                     # list downloaded
ollama show llama3.1:8b                         # model details
ollama rm llama3.1:8b                           # delete
ollama cp llama3.1:8b my-llama                  # copy/alias
ollama run llama3.1:8b "Summarise: ..."         # interactive
```

### Custom Modelfiles

```bash
OLLAMA_WORK=$(mktemp -d /tmp/ollama-XXXXXXXXXX)
cat > "$OLLAMA_WORK/Modelfile" <<'EOF'
FROM llama3.1:8b
PARAMETER temperature 0.7
PARAMETER num_ctx 8192
SYSTEM """You are a DevOps assistant specialising in RHEL. Be concise, provide copy-paste commands."""
EOF
ollama create devops-assistant -f "$OLLAMA_WORK/Modelfile"
```

### API Usage (localhost:11434)

```bash
# Generate
curl -s http://localhost:11434/api/generate -d '{"model":"llama3.1:8b","prompt":"Explain SELinux"}'
# Chat (non-streaming)
curl -s http://localhost:11434/api/chat -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"What is LVM?"}],"stream":false}'
# List models / health check
curl -s http://localhost:11434/api/tags | python3 -m json.tool
curl -s http://localhost:11434/
```

### Environment Variables

Set in `/etc/systemd/system/ollama.service` `[Service]` section, then `sudo systemctl daemon-reload && sudo systemctl restart ollama`.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `127.0.0.1:11434` | Bind address (`0.0.0.0:11434` for network) |
| `OLLAMA_MODELS` | `~/.ollama/models` | Model storage path |
| `OLLAMA_NUM_PARALLEL` | `1` | Concurrent request slots per model |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Max models in VRAM simultaneously |
| `OLLAMA_KEEP_ALIVE` | `5m` | Time to keep model loaded after last request |
| `OLLAMA_NUM_GPU` | auto (all) | GPU layers to offload (0 = CPU only) |
| `OLLAMA_FLASH_ATTENTION` | `0` | Set `1` to enable flash attention |
| `OLLAMA_MAX_QUEUE` | `512` | Max queued requests before rejecting |

### VRAM Requirements (Approximate)

| Model Size | Q4_K_M | Q5_K_M | FP16 |
|---|---|---|---|
| 7-8B | ~5 GB | ~6 GB | ~16 GB |
| 13B | ~8 GB | ~10 GB | ~26 GB |
| 34B | ~20 GB | ~24 GB | ~68 GB |
| 70B | ~40 GB | ~48 GB | ~140 GB |

Models exceeding VRAM partially offload to CPU RAM (slower). Set `OLLAMA_NUM_GPU=0` for full CPU inference.

---

## 6. Ollama + Podman / Docker

### Podman (RHEL Default)

```bash
# Run Ollama container with GPU via CDI
podman run -d --name ollama \
  --device nvidia.com/gpu=all \
  -p 11434:11434 \
  -v ollama-data:/root/.ollama \
  --restart always \
  docker.io/ollama/ollama

podman exec ollama ollama pull llama3.1:8b
podman exec ollama ollama run llama3.1:8b "Hello"
```

### Podman Quadlet (Systemd-Managed Container)

Create `/etc/containers/systemd/ollama.container`:

```ini
[Unit]
Description=Ollama LLM Server (Podman)
After=network-online.target

[Container]
Image=docker.io/ollama/ollama:latest
PublishPort=11434:11434
Volume=ollama-data.volume:/root/.ollama
AddDevice=nvidia.com/gpu=all
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_NUM_PARALLEL=4

[Service]
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

Create `/etc/containers/systemd/ollama-data.volume`:

```ini
[Volume]
```

```bash
sudo systemctl daemon-reload
sudo systemctl start ollama
systemctl status ollama
```

### Docker Compose (with Open WebUI)

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: [ollama-data:/root/.ollama]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - OLLAMA_HOST=0.0.0.0:11434
      - OLLAMA_NUM_PARALLEL=4
    restart: unless-stopped

  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    ports: ["3000:8080"]
    volumes: [open-webui-data:/app/backend/data]
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
    depends_on: [ollama]
    restart: unless-stopped

volumes:
  ollama-data:
  open-webui-data:
```

```bash
# Firewall for Open WebUI
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload
```

---

## 7. GPU Monitoring

```bash
# One-shot / continuous
nvidia-smi
watch -n1 nvidia-smi

# CSV query (scriptable)
nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw \
  --format=csv,noheader,nounits

# Device monitoring stream / process monitoring
nvidia-smi dmon -s pucvmet -d 5
nvidia-smi pmon -d 5

# Persistent mode (reduces cold-start latency on headless servers)
sudo nvidia-smi -pm 1
sudo systemctl enable --now nvidia-persistenced

# Power management
nvidia-smi -q -d POWER                        # query limits
sudo nvidia-smi -pl 250                       # set cap (watts)

# nvtop -- interactive GPU process monitor (from EPEL)
sudo dnf install nvtop -y && nvtop
```

### Prometheus GPU Metrics (dcgm-exporter)

```bash
# With Podman (CDI)
podman run -d --name dcgm-exporter \
  --device nvidia.com/gpu=all \
  -p 9400:9400 \
  nvcr.io/nvidia/k8s/dcgm-exporter:3.3.8-3.6.1-ubi9

# With Docker
docker run -d --name dcgm-exporter --gpus all -p 9400:9400 \
  nvcr.io/nvidia/k8s/dcgm-exporter:3.3.8-3.6.1-ubi9

curl -s localhost:9400/metrics | head -20

# Add to /etc/prometheus/prometheus.yml:
#   - job_name: 'gpu'
#     static_configs:
#       - targets: ['localhost:9400']

# Open firewall for Prometheus scraping
sudo firewall-cmd --permanent --add-port=9400/tcp
sudo firewall-cmd --reload
```

---

## 8. Multi-GPU Configuration

```bash
# CUDA_VISIBLE_DEVICES -- restrict which GPUs are visible
export CUDA_VISIBLE_DEVICES=0                  # only GPU 0
export CUDA_VISIBLE_DEVICES=0,2                # GPUs 0 and 2
export CUDA_VISIBLE_DEVICES=""                 # CPU only

# For Ollama: set in systemd service
# Environment="CUDA_VISIBLE_DEVICES=0,1"
# sudo systemctl daemon-reload && sudo systemctl restart ollama
# Ollama auto-splits layers across visible GPUs when model exceeds single-GPU VRAM

# Per-process GPU memory
nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv

# P2P topology (NVLink = highest bandwidth)
nvidia-smi topo --matrix
```

<HARD-RULE>
`nvidia-smi --gpu-reset -i <N>` terminates ALL processes on that GPU without warning. Only use on idle/development GPUs, never on production inference without coordination.
</HARD-RULE>

---

## 9. vGPU Basics

NVIDIA vGPU shares a physical GPU across multiple VMs with hardware isolation.

- **Supported GPUs**: Data Centre cards only (A100, A30, L40, L4) -- consumer GPUs do NOT support vGPU
- **Licensing**: Requires NVIDIA AI Enterprise or vGPU Software license (no free tier)
- **Hypervisors**: KVM/QEMU (RHEL), Proxmox VE, VMware vSphere, Citrix
- **Profiles**: Fixed-size slices (e.g., A100-4C = 4 GB per vGPU)

```bash
# KVM/RHEL high-level steps:
# 1. Install NVIDIA vGPU host driver (from NVIDIA Licensing Portal, not standard driver)
# 2. Enable IOMMU in /etc/default/grub:
#    GRUB_CMDLINE_LINUX="... intel_iommu=on iommu=pt"     # Intel
#    GRUB_CMDLINE_LINUX="... amd_iommu=on iommu=pt"       # AMD
#    sudo grub2-mkconfig -o /boot/grub2/grub.cfg && sudo reboot
# 3. Create mdev devices, assign profiles to VMs via libvirt

ls /sys/class/mdev_bus/*/mdev_supported_types/             # list available profiles
nvidia-smi vgpu                                             # list active vGPU instances

# Alternative: full GPU passthrough (no license needed, 1 GPU = 1 VM)
# Consumer GPUs (RTX 3090/4090) work with passthrough only
# Requires IOMMU groups + vfio-pci stub driver
```

---

## 10. Troubleshooting

### Driver Mismatch After Kernel Update

```bash
# Symptom: "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver"
dkms status                                              # check if module built for current kernel
sudo dnf install kernel-devel-$(uname -r) kernel-headers-$(uname -r) -y
sudo dkms autoinstall && sudo reboot                     # rebuild DKMS modules

# If using kmod (precompiled) -- reinstall
sudo dnf reinstall kmod-nvidia -y && sudo reboot

# Preventive: lock kernel and driver versions
sudo dnf versionlock add kernel-$(uname -r) nvidia-driver-latest-dkms
dnf versionlock list
# Remove lock when ready to upgrade
sudo dnf versionlock delete kernel-$(uname -r)
```

### CUDA Out of Memory

```bash
nvidia-smi                                               # check what is using VRAM
# Reduce context: PARAMETER num_ctx 2048 in Modelfile
# Use smaller quant: ollama pull llama3.1:8b-instruct-q4_0
# Partial offload: Environment="OLLAMA_NUM_GPU=20" in service file
# Kill orphaned GPU processes:
sudo kill -9 $(nvidia-smi --query-compute-apps=pid --format=csv,noheader)
```

### SELinux Denials Blocking GPU Access

```bash
# Symptom: nvidia-smi works as root but containers/services fail with permission denied
# Check for AVC denials
sudo ausearch -m AVC --start recent | grep nvidia
sudo sealert -a /var/log/audit/audit.log | grep -A 20 nvidia

# Generate and apply a targeted policy module
sudo ausearch -m AVC -ts recent | audit2allow -M nvidia_local
sudo semodule -i nvidia_local.pp

# Common boolean for container GPU access
sudo setsebool -P container_use_devices 1

# Verify SELinux context on device nodes
ls -laZ /dev/nvidia*
# Expected type: nvidia_device_t or chr_file (depends on policy)

# If Ollama service is blocked
sudo ausearch -m AVC -c ollama | audit2allow -M ollama_gpu
sudo semodule -i ollama_gpu.pp

# Nuclear option for diagnosis ONLY (revert immediately after):
# sudo setenforce 0   # permissive -- logs but doesn't block
# Test, collect AVCs, then: sudo setenforce 1
```

<HARD-RULE>
After every SELinux policy change, run `sudo setenforce 1` and test again to confirm the fix works in enforcing mode. Never leave a production system in permissive mode.
</HARD-RULE>

### GPU Fallen Off the Bus

```bash
# Symptom: "GPU has fallen off the bus" in dmesg, nvidia-smi shows ERR!
# Causes: overheating, PSU issues, faulty riser, PCIe errors
dmesg | grep -i -E "nvidia|gpu|pci|error"
sudo nvidia-smi --gpu-reset -i 0                        # attempt recovery; reboot if fails
# Persistent: reseat GPU, check PSU wattage, verify PCIe slot, check PCIe AER errors
sudo lspci -vv -s $(lspci | grep -i nvidia | awk '{print $1}') | grep -i "lnk"
```

### Thermal Throttling

```bash
# Symptom: clock drops, "SW Thermal Slowdown" in nvidia-smi -q -d PERFORMANCE
watch -n2 'nvidia-smi --query-gpu=index,temperature.gpu,clocks.current.sm,power.draw --format=csv,noheader'
sudo nvidia-smi -pl 200                                  # reduce power cap
nvidia-smi -q -d FAN                                     # check fans (server GPUs are passive)
# Server chassis: verify BMC fan profile, check air baffles and airflow
```

### Ollama Model Loading Failures

```bash
df -h /usr/share/ollama                         # check disk space (models are large)
ollama rm llama3.1:8b && ollama pull llama3.1:8b # re-pull corrupted model
journalctl -u ollama -n 50 --no-pager           # check logs
journalctl -u ollama -f                         # follow live
```

### Nouveau Still Loaded After Blacklisting

```bash
# Verify nouveau is not loaded
lsmod | grep nouveau
# If still loaded, ensure blacklist is in initramfs
sudo dracut --omit-drivers nouveau --force
sudo reboot
# Confirm
lsmod | grep nouveau        # should return nothing
lsmod | grep nvidia          # should show nvidia modules
```

### Quick Diagnostic Script

```bash
#!/usr/bin/env bash
echo "=== OS ===" && cat /etc/redhat-release
echo "=== Kernel ===" && uname -r
echo "=== Secure Boot ===" && mokutil --sb-state 2>/dev/null || echo "mokutil N/A"
echo "=== SELinux ===" && getenforce
echo "=== Nouveau ===" && lsmod | grep nouveau && echo "WARNING: nouveau loaded!" || echo "Not loaded (good)"
echo "=== Driver ===" && nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo "NOT LOADED"
echo "=== GPUs ===" && nvidia-smi -L 2>/dev/null || echo "None detected"
echo "=== CUDA ===" && nvcc --version 2>/dev/null || echo "nvcc not in PATH"
echo "=== DKMS ===" && dkms status 2>/dev/null || echo "dkms not installed"
echo "=== Ollama ===" && ollama --version 2>/dev/null && systemctl is-active ollama 2>/dev/null
echo "=== Podman GPU ===" && podman run --rm --device nvidia.com/gpu=all nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi 2>/dev/null && echo "OK" || echo "FAILED or not configured"
echo "=== Docker GPU ===" && docker run --rm --gpus all nvcr.io/nvidia/cuda:12.6.3-base-ubi9 nvidia-smi 2>/dev/null && echo "OK" || echo "FAILED or not installed"
echo "=== Temps ===" && nvidia-smi --query-gpu=index,temperature.gpu --format=csv 2>/dev/null
echo "=== GPU SELinux AVCs ===" && sudo ausearch -m AVC --start recent 2>/dev/null | grep -c nvidia && echo "denial(s) found" || echo "None"
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Installing NVIDIA drivers from RHEL repo instead of NVIDIA's official repo | RHEL repo drivers are often outdated; miss CUDA compatibility; fail with newer GPU models | Use NVIDIA's official CUDA repo or ELRepo for latest supported drivers; verify compatibility matrix first |
| Not blacklisting nouveau before installing NVIDIA drivers | nouveau conflicts with NVIDIA driver; system boots to black screen or falls back to software rendering | Blacklist nouveau in /etc/modprobe.d/ and rebuild initramfs before installing NVIDIA drivers |
| Running Ollama without GPU verification | Ollama silently falls back to CPU mode; inference is 10-50x slower; user assumes GPU is working | Verify GPU detection with `ollama ps` and `nvidia-smi`; check Ollama logs for CUDA initialization |
| Loading models larger than VRAM without understanding offloading | Model partially loads, runs extremely slowly with constant GPU-CPU memory swapping; appears frozen | Check model size vs available VRAM; use quantized models (Q4_K_M, Q5_K_M) to fit in VRAM; monitor with nvidia-smi |
| Not setting NVIDIA Container Toolkit for containerized inference | Docker/Podman containers cannot access GPU; inference falls back to CPU inside container | Install nvidia-container-toolkit; configure runtime in daemon.json (Docker) or use --device nvidia.com/gpu (Podman) |

---

## Related Skills

| Workload | Skill |
|---|---|
| RHEL core administration (parent) | `rhel-server-admin` |
| Docker / Podman containers | `rhel-docker-host` |
| Prometheus, Grafana, logging | `rhel-monitoring` |
| Web servers (Nginx, Apache, Caddy) | `rhel-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| File sharing (NFS, Samba) | `rhel-file-storage` |
| DNS, DHCP, NTP | `rhel-network-infra` |
