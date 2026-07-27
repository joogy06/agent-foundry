# Install Guides by OS

OS-aware install instructions for each tool in the env-adoption inventory. Detected via `/etc/os-release` (Linux) or `uname` (macOS).

## Codex CLI

| OS Family | Install Command |
|-----------|----------------|
| RHEL/AlmaLinux/Rocky | `npm install -g @openai/codex-cli` |
| Ubuntu/Debian | `npm install -g @openai/codex-cli` |
| macOS | `npm install -g @openai/codex-cli` |

Post-install: `codex --version` to verify. Configure at `~/.codex/config.toml`.

## Antigravity CLI (agy)

| OS Family | Install Command |
|-----------|----------------|
| All | `agy install` / `agy update` (binary at `~/.local/bin/agy`) — see the `antigravity-cli` skill for the full procedure |

Auth: via the Antigravity account; config lives under `~/.antigravity/`. `agy` authenticates itself — there is NO API-key env var and NO `GOOGLE_CLOUD_PROJECT` prefix at the call layer. Headless single-prompt usage is `agy -p "<prompt>"` (plain-text stdout); see the `antigravity-cli` skill.

## GitHub CLI (gh)

| OS Family | Install Command |
|-----------|----------------|
| RHEL/AlmaLinux | `sudo dnf install gh` |
| Ubuntu/Debian | `sudo apt install gh` (or via official repo: `https://github.com/cli/cli/blob/trunk/docs/install_linux.md`) |
| macOS | `brew install gh` |

Post-install: `gh auth login` to authenticate.

## GitHub Copilot CLI

| OS Family | Install Command |
|-----------|----------------|
| All | `gh extension install github/gh-copilot` |

Requires `gh` to be installed and authenticated first.

## Docker

| OS Family | Install Command |
|-----------|----------------|
| RHEL/AlmaLinux | `sudo dnf install docker-ce docker-ce-cli containerd.io` (from Docker repo) |
| Ubuntu/Debian | `sudo apt install docker-ce docker-ce-cli containerd.io` (from Docker repo) |
| macOS | `brew install --cask docker` |

Post-install: Add user to docker group (`sudo usermod -aG docker $USER`) to avoid sudo requirement.

## Python 3

| OS Family | Install Command |
|-----------|----------------|
| RHEL/AlmaLinux | `sudo dnf install python3` |
| Ubuntu/Debian | `sudo apt install python3` |
| macOS | `brew install python3` (or use system Python on newer macOS) |

## Git

| OS Family | Install Command |
|-----------|----------------|
| RHEL/AlmaLinux | `sudo dnf install git` |
| Ubuntu/Debian | `sudo apt install git` |
| macOS | `xcode-select --install` (or `brew install git`) |

