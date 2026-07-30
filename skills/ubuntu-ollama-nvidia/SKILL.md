---
name: ubuntu-ollama-nvidia
description: Use when setting up NVIDIA GPUs, CUDA, container toolkit, or Ollama on Ubuntu 24.04 LTS — driver installation (proprietary vs open kernel module), CUDA toolkit, cuDNN, NVIDIA Container Toolkit for Docker, Ollama installation and model management, GPU monitoring (nvidia-smi), vGPU basics, multi-GPU configuration, and troubleshooting. Part of the ubuntu-* skill family.
family: ubuntu
applies_when: os_family == debian
---

# Ubuntu 24.04 LTS -- NVIDIA GPU & Ollama Administration

Companion skill to `ubuntu-server-admin` covering GPU compute and local LLM workloads on Ubuntu Server 24.04.4 LTS (Noble Numbat). See also: `ubuntu-docker-host`, `ubuntu-monitoring`.

<HARD-RULE>
Kernel updates can break NVIDIA drivers. Pin your kernel or hold the driver package before `apt upgrade` on production GPU nodes. Always have out-of-band access (IPMI/iLO, console) before driver changes.
```bash
sudo apt-mark hold nvidia-driver-560 linux-image-$(uname -r) linux-headers-$(uname -r)
```
</HARD-RULE>

<HARD-RULE>
Secure Boot requires MOK (Machine Owner Key) enrollment for NVIDIA DKMS modules. If you skip MOK enrollment at the blue boot screen, the driver will NOT load. Re-trigger with `sudo dpkg-reconfigure nvidia-dkms-560` then reboot and complete enrollment.
</HARD-RULE>

---

## 1. NVIDIA Driver Installation

```bash
# Recommended: auto-detect and install
sudo apt update && ubuntu-drivers list
sudo ubuntu-drivers install              # recommended driver
sudo ubuntu-drivers install nvidia:560   # specific version
sudo reboot

# Alternative: PPA for latest branches
sudo add-apt-repository ppa:graphics-drivers/ppa -y && sudo apt update
sudo apt install nvidia-driver-560 -y && sudo reboot

# Open kernel module (Turing+ / RTX 20xx and newer)
sudo apt install nvidia-driver-560-open -y
cat /proc/driver/nvidia/version   # confirms "Open Module" if active
```

| Architecture | Proprietary | nvidia-open |
|---|---|---|
| Maxwell / Pascal (GTX 10xx) | Supported | NOT supported |
| Turing (RTX 20xx / T4) | Supported | Supported |
| Ampere (RTX 30xx / A100) | Supported | Recommended |
| Ada Lovelace (RTX 40xx / L40) | Supported | Recommended |
| Hopper / Blackwell (H100/B200) | Supported | Required |

```bash
# Blacklist nouveau (ubuntu-drivers does this automatically; manual installs need it)
sudo tee /etc/modprobe.d/blacklist-nouveau.conf > /dev/null <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF
sudo update-initramfs -u && sudo reboot

# Verify installation
nvidia-smi                            # GPU info, driver + CUDA version
cat /proc/driver/nvidia/version       # kernel module details
dkms status                           # DKMS module state
lsmod | grep nvidia                   # loaded modules

# DKMS rebuild after kernel update
sudo dkms autoinstall && sudo reboot

# Secure Boot check
mokutil --sb-state
# If driver fails after install: reboot -> blue MOK Manager -> Enroll MOK -> enter password
```

---

## 2. CUDA Toolkit

<HARD-RULE>
Do NOT install CUDA from Ubuntu's default repos (`nvidia-cuda-toolkit`) -- it is outdated. Always use NVIDIA's official repository.
</HARD-RULE>

```bash
# Add NVIDIA CUDA repo (Ubuntu 24.04)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb && sudo apt update

# Install (also installs driver if missing)
sudo apt install cuda-toolkit -y          # latest
sudo apt install cuda-toolkit-12-6 -y     # specific version

# Environment variables -- add system-wide
sudo tee /etc/profile.d/cuda.sh > /dev/null <<'EOF'
export PATH=/usr/local/cuda/bin${PATH:+:${PATH}}
export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
EOF
source /etc/profile.d/cuda.sh

# Verify
nvcc --version
ls -la /usr/local/cuda   # symlink to active version

# Multiple versions side-by-side
sudo apt install cuda-toolkit-12-4 cuda-toolkit-12-6 -y
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
# Install from NVIDIA CUDA repo (added in section 2)
sudo apt install libcudnn9-cuda-12 libcudnn9-dev-cuda-12 -y
dpkg -l | grep cudnn   # verify version
# cuDNN 9.x pairs with CUDA 12.x; cuDNN 8.x with CUDA 11.x/12.x (legacy)
```

---

## 4. NVIDIA Container Toolkit

Requires Docker Engine (see `ubuntu-docker-host`).

```bash
# Install
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install nvidia-container-toolkit -y

# Configure Docker runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Test
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi

# Specific GPUs
docker run --rm --gpus '"device=0,1"' nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi
```

Docker Compose GPU reservation:
```yaml
services:
  cuda-app:
    image: nvidia/cuda:12.6.3-base-ubuntu24.04
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

```bash
# Install (recommended)
curl -fsSL https://ollama.com/install.sh | sh
ollama --version && systemctl status ollama
```

Manual installation with systemd service:
```bash
sudo curl -L https://ollama.com/download/ollama-linux-amd64 -o /usr/local/bin/ollama
sudo chmod +x /usr/local/bin/ollama
sudo useradd -r -s /bin/false -m -d /usr/share/ollama ollama
sudo usermod -aG video ollama

sudo tee /etc/systemd/system/ollama.service > /dev/null <<'EOF'
[Unit]
Description=Ollama Service
After=network-online.target
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
ollama pull llama3.1:8b                   # download
ollama pull llama3.1:70b-instruct-q4_K_M  # quantised variant
ollama list                                # list downloaded
ollama show llama3.1:8b                    # model details
ollama rm llama3.1:8b                      # delete
ollama cp llama3.1:8b my-llama             # copy/alias
ollama run llama3.1:8b "Summarise: ..."    # interactive
```

### Custom Modelfiles

```bash
OLLAMA_WORK=$(mktemp -d /tmp/ollama-XXXXXXXXXX)
cat > "$OLLAMA_WORK/Modelfile" <<'EOF'
FROM llama3.1:8b
PARAMETER temperature 0.7
PARAMETER num_ctx 8192
SYSTEM """You are a DevOps assistant. Be concise, provide copy-paste commands."""
EOF
ollama create devops-assistant -f "$OLLAMA_WORK/Modelfile"
```

### API Usage (localhost:11434)

```bash
# Generate
curl -s http://localhost:11434/api/generate -d '{"model":"llama3.1:8b","prompt":"Explain RAID"}'
# Chat (non-streaming)
curl -s http://localhost:11434/api/chat -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"What is swap?"}],"stream":false}'
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

## 6. Ollama + Docker

```bash
# Run Ollama container with GPU
docker run -d --name ollama --gpus all -p 11434:11434 \
  -v ollama-data:/root/.ollama --restart unless-stopped ollama/ollama

docker exec ollama ollama pull llama3.1:8b
docker exec ollama ollama run llama3.1:8b "Hello"
```

Compose with Open WebUI:
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
nvidia-smi -q -d POWER                    # query limits
sudo nvidia-smi -pl 250                   # set cap (watts)

# nvtop -- interactive GPU process monitor
sudo apt install nvtop -y && nvtop
```

### Prometheus GPU Metrics (dcgm-exporter)

```bash
docker run -d --name dcgm-exporter --gpus all -p 9400:9400 \
  nvcr.io/nvidia/k8s/dcgm-exporter:3.3.8-3.6.1-ubuntu22.04
curl -s localhost:9400/metrics | head -20
# Add to /etc/prometheus/prometheus.yml:
#   - job_name: 'gpu'
#     static_configs:
#       - targets: ['localhost:9400']
```

---

## 8. Multi-GPU Configuration

```bash
# CUDA_VISIBLE_DEVICES -- restrict which GPUs are visible
export CUDA_VISIBLE_DEVICES=0          # only GPU 0
export CUDA_VISIBLE_DEVICES=0,2        # GPUs 0 and 2
export CUDA_VISIBLE_DEVICES=""         # CPU only

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

- **Supported GPUs**: Data Centre cards only (A100, A30, L40) -- consumer GPUs do NOT support vGPU
- **Licensing**: Requires NVIDIA AI Enterprise or vGPU Software license (no free tier)
- **Hypervisors**: Proxmox VE (community), VMware vSphere, Citrix, KVM/QEMU
- **Profiles**: Fixed-size slices (e.g., A100-4C = 4 GB per vGPU)

```bash
# Proxmox/KVM high-level steps:
# 1. Install NVIDIA vGPU host driver (from NVIDIA Licensing Portal, not standard driver)
# 2. Enable IOMMU: intel_iommu=on iommu=pt (or amd_iommu=on)
# 3. Create mdev devices, assign profiles to VMs

ls /sys/class/mdev_bus/*/mdev_supported_types/   # list available profiles
nvidia-smi vgpu                                   # list active vGPU instances

# Alternative: full GPU passthrough (no license needed, 1 GPU = 1 VM)
# Consumer GPUs (RTX 3090/4090) work with passthrough only
```

---

## 10. Troubleshooting

### Driver Mismatch After Kernel Update

```bash
# Symptom: "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver"
dkms status                                         # check if module built for current kernel
sudo apt install --reinstall nvidia-driver-560       # reinstall
sudo dkms autoinstall && sudo reboot                # or rebuild DKMS
# Preventive: sudo apt-mark hold linux-image-$(uname -r) nvidia-driver-560
```

### CUDA Out of Memory

```bash
nvidia-smi                                          # check what's using VRAM
# Reduce context: PARAMETER num_ctx 2048 in Modelfile
# Use smaller quant: ollama pull llama3.1:8b-instruct-q4_0
# Partial offload: Environment="OLLAMA_NUM_GPU=20" in service file
# Kill orphans:
sudo kill -9 $(nvidia-smi --query-compute-apps=pid --format=csv,noheader)
```

### Ollama Model Loading Failures

```bash
df -h /usr/share/ollama                   # check disk space (models are large)
ollama rm llama3.1:8b && ollama pull llama3.1:8b   # re-pull corrupted model
journalctl -u ollama -n 50 --no-pager     # check logs
journalctl -u ollama -f                   # follow live
```

### GPU Fallen Off the Bus

```bash
# Symptom: "GPU has fallen off the bus" in dmesg, nvidia-smi shows ERR!
# Causes: overheating, PSU issues, faulty riser, PCIe errors
dmesg | grep -i -E "nvidia|gpu|pci|error"
sudo nvidia-smi --gpu-reset -i 0          # attempt recovery; reboot if fails
# Persistent: reseat GPU, check PSU wattage, verify PCIe slot
```

### Thermal Throttling

```bash
# Symptom: clock drops, "SW Thermal Slowdown" in nvidia-smi -q -d PERFORMANCE
watch -n2 'nvidia-smi --query-gpu=index,temperature.gpu,clocks.current.sm,power.draw --format=csv,noheader'
sudo nvidia-smi -pl 200                   # reduce power cap
nvidia-smi -q -d FAN                      # check fans (server GPUs are passive)
```

### Quick Diagnostic Script

```bash
#!/usr/bin/env bash
echo "=== Driver ===" && nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo "NOT LOADED"
echo "=== GPUs ===" && nvidia-smi -L 2>/dev/null || echo "None detected"
echo "=== CUDA ===" && nvcc --version 2>/dev/null || echo "nvcc not in PATH"
echo "=== DKMS ===" && dkms status 2>/dev/null
echo "=== Ollama ===" && ollama --version 2>/dev/null && systemctl is-active ollama 2>/dev/null
echo "=== Docker GPU ===" && docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi 2>/dev/null && echo "OK" || echo "FAILED"
echo "=== Temps ===" && nvidia-smi --query-gpu=index,temperature.gpu --format=csv 2>/dev/null
echo "=== Kernel ===" && uname -r
echo "=== Secure Boot ===" && mokutil --sb-state 2>/dev/null || echo "mokutil N/A"
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Installing NVIDIA drivers from Ubuntu's default repo without checking GPU compatibility | Default repo drivers may not support your GPU generation; blank screen on reboot | Use NVIDIA's official PPA or .run installer; verify driver version against GPU compatibility matrix |
| Not disabling nouveau before NVIDIA driver installation | nouveau and NVIDIA drivers conflict; system may boot to black screen or have unstable graphics | Add `blacklist nouveau` to /etc/modprobe.d/; run `update-initramfs -u`; reboot before installing NVIDIA drivers |
| Assuming Ollama uses GPU without verification | Ollama falls back to CPU silently if CUDA is not detected; inference is 10-50x slower | Check `ollama ps` for GPU usage; verify with `nvidia-smi` that CUDA processes appear; check Ollama logs for CUDA init |
| Loading 70B parameter models on consumer GPUs (8-16GB VRAM) | Model does not fit; constant GPU-CPU memory swapping; appears frozen or extremely slow | Match model size to VRAM: 7B needs ~4GB, 13B needs ~8GB, 70B needs ~40GB; use quantized versions (Q4_K_M) to reduce VRAM |
| Running Ollama in Docker without NVIDIA Container Toolkit | Container has no GPU access; all inference runs on CPU inside container despite host having GPU | Install nvidia-container-toolkit; add `--gpus all` flag (Docker) or `--device nvidia.com/gpu=all` (Podman) |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core Ubuntu administration | `ubuntu-server-admin` |
| Web servers (Nginx, Apache, Caddy) | `ubuntu-web-servers` |
| Databases (PostgreSQL, MySQL, Redis) | `ubuntu-databases` |
| Docker / containers | `ubuntu-docker-host` |
| File sharing (NFS, Samba, ZFS) | `ubuntu-file-storage` |
| DNS, DHCP, NTP | `ubuntu-network-infra` |
| Prometheus, Grafana, logging | `ubuntu-monitoring` |
