#!/usr/bin/env bash
# probe.sh — Fast environment capability probe for the env-adoption skill.
#
# Usage:
#   probe.sh check [--inventory-only] [--force] [--silent] [--json]
#   probe.sh get <jq-path>
#   probe.sh setup
#
# State files:
#   ~/.claude/state/inventory.json                  (persistent: tools, versions, tier)
#   $XDG_RUNTIME_DIR/env-adoption/session-<id>.json (volatile: bridge mode, auth, MCP)
#
# Designed to complete in under 3 seconds. Composes with bridge-mode-detect.sh
# (does NOT reimplement its hysteresis logic).

set -euo pipefail

# ── constants ──────────────────────────────────────────────────────────────────

INVENTORY_FILE="$HOME/.claude/state/inventory.json"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
SESSION_DIR="$RUNTIME_DIR/env-adoption"
BRIDGE_DETECT="$HOME/.claude/skills/git-cli-bridge/scripts/bridge-mode-detect.sh"
STALENESS_HOURS=24

# ── helpers ────────────────────────────────────────────────────────────────────

die()  { printf 'env-adoption: %s\n' "$1" >&2; exit 1; }
now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# Session ID: prefer CLAUDE_SESSION_ID or FORGE_SESSION_ID, else derive from PPID.
session_id() {
  printf '%s' "${CLAUDE_SESSION_ID:-${FORGE_SESSION_ID:-ppid-$$}}"
}

session_file() {
  printf '%s/session-%s.json' "$SESSION_DIR" "$(session_id)"
}

inventory_age_hours() {
  if [ ! -f "$INVENTORY_FILE" ]; then
    echo 999
    return
  fi
  local mtime
  mtime=$(stat -c %Y "$INVENTORY_FILE" 2>/dev/null || stat -f %m "$INVENTORY_FILE" 2>/dev/null || echo 0)
  local now
  now=$(date +%s)
  echo $(( (now - mtime) / 3600 ))
}

# ── tool detection ─────────────────────────────────────────────────────────────

detect_tool() {
  # $1 = command name, $2 = version flag (default: --version)
  local cmd="$1"
  local vflag="${2:---version}"
  local installed="false"
  local version="null"

  if command -v "$cmd" >/dev/null 2>&1; then
    installed="true"
    # Extract version with a 2-second timeout
    local raw
    raw=$(timeout 2 "$cmd" $vflag 2>&1 | head -1) || raw=""
    if [ -n "$raw" ]; then
      # Try to extract semver-like pattern (digits.digits.digits or digits.digits)
      version=$(printf '%s' "$raw" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1) || version=""
      if [ -n "$version" ]; then
        version="\"$version\""
      else
        version="null"
      fi
    fi
  fi

  printf '{"installed": %s, "version": %s}' "$installed" "$version"
}

detect_bridge() {
  if [ -x "$BRIDGE_DETECT" ]; then
    printf '{"installed": true}'
  else
    printf '{"installed": false}'
  fi
}

# ── tier computation ───────────────────────────────────────────────────────────

compute_tier() {
  # $1 = inventory JSON string
  local inv="$1"

  local git_ok python3_ok gh_ok codex_ok gemini_ok copilot_ok docker_ok bridge_ok
  git_ok=$(printf '%s' "$inv" | jq -r '.tools.git.installed')
  python3_ok=$(printf '%s' "$inv" | jq -r '.tools.python3.installed')
  gh_ok=$(printf '%s' "$inv" | jq -r '.tools.gh.installed')
  codex_ok=$(printf '%s' "$inv" | jq -r '.tools.codex.installed')
  gemini_ok=$(printf '%s' "$inv" | jq -r '.tools.gemini.installed')
  copilot_ok=$(printf '%s' "$inv" | jq -r '.tools.copilot.installed')
  docker_ok=$(printf '%s' "$inv" | jq -r '.tools.docker.installed')
  bridge_ok=$(printf '%s' "$inv" | jq -r '.tools.bridge.installed')

  # Tier 0: minimal — git + python3
  if [ "$git_ok" != "true" ] || [ "$python3_ok" != "true" ]; then
    printf '0\nminimal'
    return
  fi

  # Tier 2: full — all of tier 1 + copilot + docker + bridge
  if [ "$gh_ok" = "true" ] && [ "$codex_ok" = "true" ] && [ "$gemini_ok" = "true" ] \
     && [ "$copilot_ok" = "true" ] && [ "$docker_ok" = "true" ] && [ "$bridge_ok" = "true" ]; then
    printf '2\nfull'
    return
  fi

  # Tier 1: standard — git + python3 + gh + codex + gemini
  if [ "$gh_ok" = "true" ] && [ "$codex_ok" = "true" ] && [ "$gemini_ok" = "true" ]; then
    printf '1\nstandard'
    return
  fi

  # Falls between 0 and 1 — report as 0 with label
  printf '0\nminimal'
}

# ── check (main operation) ─────────────────────────────────────────────────────

do_check() {
  local inventory_only=0
  local force=0
  local silent=0
  local json_out=0

  for arg in "$@"; do
    case "$arg" in
      --inventory-only) inventory_only=1 ;;
      --force)          force=1 ;;
      --silent)         silent=1 ;;
      --json)           json_out=1 ;;
      *)                die "unknown flag: $arg" ;;
    esac
  done

  # Skip inventory probe if fresh (unless --force)
  local age
  age=$(inventory_age_hours)
  if [ "$force" -eq 0 ] && [ "$age" -lt "$STALENESS_HOURS" ] && [ -f "$INVENTORY_FILE" ]; then
    # Inventory is fresh — read existing
    local inv
    inv=$(cat "$INVENTORY_FILE")
  else
    # Probe all tools
    local claude_j codex_j gemini_j copilot_j gh_j git_j docker_j python3_j bridge_j
    claude_j=$(detect_tool claude)
    codex_j=$(detect_tool codex)
    gemini_j=$(detect_tool gemini)
    copilot_j=$(detect_tool copilot)
    gh_j=$(detect_tool gh)
    git_j=$(detect_tool git)
    docker_j=$(detect_tool docker)
    python3_j=$(detect_tool python3)
    bridge_j=$(detect_bridge)

    # Build inventory JSON
    local inv
    inv=$(jq -n \
      --argjson claude "$claude_j" \
      --argjson codex "$codex_j" \
      --argjson gemini "$gemini_j" \
      --argjson copilot "$copilot_j" \
      --argjson gh "$gh_j" \
      --argjson git "$git_j" \
      --argjson docker "$docker_j" \
      --argjson python3 "$python3_j" \
      --argjson bridge "$bridge_j" \
      --arg last_probed "$(now_iso)" \
      '{
        version: 1,
        last_probed: $last_probed,
        tools: {
          claude: $claude,
          codex: $codex,
          gemini: $gemini,
          copilot: $copilot,
          gh: $gh,
          git: $git,
          docker: $docker,
          python3: $python3,
          bridge: $bridge
        }
      }')

    # Compute tier
    local tier_info tier tier_label
    tier_info=$(compute_tier "$inv")
    tier=$(printf '%s' "$tier_info" | head -1)
    tier_label=$(printf '%s' "$tier_info" | tail -1)

    inv=$(printf '%s' "$inv" | jq --argjson tier "$tier" --arg tier_label "$tier_label" \
      '. + {tier: $tier, tier_label: $tier_label}')

    # Write inventory
    mkdir -p "$(dirname "$INVENTORY_FILE")"
    printf '%s\n' "$inv" > "$INVENTORY_FILE"
  fi

  # Session state (unless --inventory-only)
  local sess=""
  if [ "$inventory_only" -eq 0 ]; then
    mkdir -p "$SESSION_DIR"

    # Bridge mode — compose with bridge-mode-detect.sh
    local bridge_mode="unknown"
    if [ -x "$BRIDGE_DETECT" ]; then
      bridge_mode=$(timeout 3 "$BRIDGE_DETECT" 2>/dev/null) || bridge_mode="unknown"
    fi

    # gh auth status
    local gh_auth=false
    local gh_user="null"
    if command -v gh >/dev/null 2>&1; then
      local gh_status
      gh_status=$(timeout 3 gh auth status 2>&1) || true
      if printf '%s' "$gh_status" | grep -q "Logged in"; then
        gh_auth=true
        gh_user=$(printf '%s' "$gh_status" | grep -oE 'account [^ ]+' | head -1 | sed 's/account //' || echo "")
        if [ -n "$gh_user" ]; then
          gh_user="\"$gh_user\""
        else
          gh_user="null"
        fi
      fi
    fi

    # Codex plugin readiness (check if plugin dir exists)
    local codex_plugin_ready=false
    if [ -d "$HOME/.claude/plugins/cache/codex" ] || \
       ls "$HOME/.claude/plugins/cache/"*codex* >/dev/null 2>&1; then
      codex_plugin_ready=true
    fi

    # Gemini MCP responding — we cannot call MCP from bash, so check if gemini binary works
    local gemini_mcp=false
    if command -v gemini >/dev/null 2>&1; then
      if timeout 2 gemini --version >/dev/null 2>&1; then
        gemini_mcp=true
      fi
    fi

    # Compute capabilities from inventory + session
    local inv_data
    inv_data=$(cat "$INVENTORY_FILE")
    local codex_installed gemini_installed copilot_installed docker_installed bridge_installed
    codex_installed=$(printf '%s' "$inv_data" | jq -r '.tools.codex.installed')
    gemini_installed=$(printf '%s' "$inv_data" | jq -r '.tools.gemini.installed')
    copilot_installed=$(printf '%s' "$inv_data" | jq -r '.tools.copilot.installed')
    docker_installed=$(printf '%s' "$inv_data" | jq -r '.tools.docker.installed')
    bridge_installed=$(printf '%s' "$inv_data" | jq -r '.tools.bridge.installed')

    local triple_model=false codex_challenger=false gemini_analyst=false bridge_fallback=false container_workflows=false
    if [ "$codex_installed" = "true" ] && [ "$gemini_mcp" = "true" ]; then
      triple_model=true
    fi
    [ "$codex_installed" = "true" ] && codex_challenger=true
    [ "$gemini_mcp" = "true" ] && gemini_analyst=true
    [ "$bridge_mode" = "bridge" ] && bridge_fallback=true
    [ "$docker_installed" = "true" ] && container_workflows=true

    sess=$(jq -n \
      --arg session_id "$(session_id)" \
      --arg created "$(now_iso)" \
      --arg bridge_mode "$bridge_mode" \
      --argjson gemini_mcp_responding "$gemini_mcp" \
      --argjson gh_authenticated "$gh_auth" \
      --argjson gh_user "$gh_user" \
      --argjson codex_plugin_ready "$codex_plugin_ready" \
      --argjson triple_model "$triple_model" \
      --argjson codex_challenger "$codex_challenger" \
      --argjson gemini_analyst "$gemini_analyst" \
      --argjson bridge_fallback "$bridge_fallback" \
      --argjson container_workflows "$container_workflows" \
      '{
        session_id: $session_id,
        created: $created,
        bridge_mode: $bridge_mode,
        gemini_mcp_responding: $gemini_mcp_responding,
        gh_authenticated: $gh_authenticated,
        gh_user: $gh_user,
        codex_plugin_ready: $codex_plugin_ready,
        capabilities: {
          triple_model: $triple_model,
          codex_challenger: $codex_challenger,
          gemini_analyst: $gemini_analyst,
          bridge_fallback: $bridge_fallback,
          container_workflows: $container_workflows
        }
      }')

    printf '%s\n' "$sess" > "$(session_file)"
  fi

  # Output
  if [ "$silent" -eq 1 ]; then
    return 0
  fi

  if [ "$json_out" -eq 1 ]; then
    local inv_data
    inv_data=$(cat "$INVENTORY_FILE")
    if [ -n "$sess" ]; then
      jq -n --argjson inventory "$inv_data" --argjson session "$sess" \
        '{inventory: $inventory, session: $session}'
    else
      jq -n --argjson inventory "$inv_data" '{inventory: $inventory}'
    fi
  else
    # Human-readable summary
    local inv_data
    inv_data=$(cat "$INVENTORY_FILE")
    local tier tier_label
    tier=$(printf '%s' "$inv_data" | jq -r '.tier')
    tier_label=$(printf '%s' "$inv_data" | jq -r '.tier_label')

    printf 'Environment: Tier %s (%s)\n' "$tier" "$tier_label"

    # List installed tools
    local tools_line=""
    for tool in claude codex gemini copilot gh git docker python3 bridge; do
      local installed
      installed=$(printf '%s' "$inv_data" | jq -r ".tools.${tool}.installed")
      local version
      version=$(printf '%s' "$inv_data" | jq -r ".tools.${tool}.version // empty")
      if [ "$installed" = "true" ]; then
        if [ -n "$version" ] && [ "$version" != "null" ]; then
          tools_line="${tools_line}  ${tool} ${version}"
        else
          tools_line="${tools_line}  ${tool}"
        fi
      fi
    done
    printf 'Installed:%s\n' "$tools_line"

    # List missing tools
    local missing=""
    for tool in claude codex gemini copilot gh git docker python3 bridge; do
      local installed
      installed=$(printf '%s' "$inv_data" | jq -r ".tools.${tool}.installed")
      if [ "$installed" != "true" ]; then
        missing="${missing} ${tool}"
      fi
    done
    if [ -n "$missing" ]; then
      printf 'Missing:%s\n' "$missing"
    fi

    if [ "$inventory_only" -eq 0 ] && [ -n "$sess" ]; then
      local bm
      bm=$(printf '%s' "$sess" | jq -r '.bridge_mode')
      printf 'Bridge mode: %s\n' "$bm"

      local caps
      caps=$(printf '%s' "$sess" | jq -r '.capabilities | to_entries[] | select(.value == true) | .key' | tr '\n' ', ' | sed 's/,$//')
      if [ -n "$caps" ]; then
        printf 'Capabilities: %s\n' "$caps"
      fi
    fi
  fi
}

# ── get (thin jq wrapper) ─────────────────────────────────────────────────────

do_get() {
  local path="${1:-}"
  [ -z "$path" ] && die "usage: probe.sh get <jq-path>"

  # Route to the right file based on path prefix
  case "$path" in
    session.*|capabilities.*)
      local sf
      sf="$(session_file)"
      if [ ! -f "$sf" ]; then
        # Auto-probe if session state missing
        do_check --silent >/dev/null 2>&1
      fi
      if [ ! -f "$sf" ]; then
        die "session state unavailable"
      fi
      # Strip "session." prefix if present
      local jq_path
      jq_path=$(printf '%s' "$path" | sed 's/^session\.//')
      jq -r ".$jq_path" "$sf"
      ;;
    *)
      if [ ! -f "$INVENTORY_FILE" ]; then
        # Auto-probe if inventory missing
        do_check --inventory-only --silent >/dev/null 2>&1
      fi
      if [ ! -f "$INVENTORY_FILE" ]; then
        die "inventory unavailable"
      fi
      jq -r ".$path" "$INVENTORY_FILE"
      ;;
  esac
}

# ── setup (interactive guided install) ─────────────────────────────────────────

do_setup() {
  # Ensure inventory is current
  do_check --inventory-only --silent

  local inv
  inv=$(cat "$INVENTORY_FILE")
  local tier tier_label
  tier=$(printf '%s' "$inv" | jq -r '.tier')
  tier_label=$(printf '%s' "$inv" | jq -r '.tier_label')

  printf '\n=== Environment Adoption Setup ===\n\n'
  printf 'Current tier: %s (%s)\n\n' "$tier" "$tier_label"

  # Detect OS
  local os_id="unknown"
  if [ -f /etc/os-release ]; then
    os_id=$(grep -E '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
  elif [ "$(uname)" = "Darwin" ]; then
    os_id="macos"
  fi
  local os_family="unknown"
  case "$os_id" in
    rhel|almalinux|rocky|centos|fedora) os_family="rhel" ;;
    ubuntu|debian|pop|mint)             os_family="debian" ;;
    darwin|macos)                        os_family="macos" ;;
    *)                                   os_family="$os_id" ;;
  esac

  printf 'Detected OS: %s (family: %s)\n\n' "$os_id" "$os_family"

  # Check each tool and show install instructions for missing ones
  local any_missing=0
  for tool in codex gemini copilot gh docker; do
    local installed
    installed=$(printf '%s' "$inv" | jq -r ".tools.${tool}.installed")
    if [ "$installed" != "true" ]; then
      any_missing=1
      printf '[ MISSING ] %s\n' "$tool"
      case "$tool" in
        codex)
          printf '  Install: npm install -g @openai/codex-cli\n'
          printf '  Docs: https://github.com/openai/codex\n'
          ;;
        gemini)
          printf '  Install: npm install -g @anthropic-ai/gemini-cli  (or npx -y @anthropic-ai/gemini-cli auth)\n'
          printf '  Docs: https://github.com/google-gemini/gemini-cli\n'
          ;;
        copilot)
          case "$os_family" in
            rhel)   printf '  Install: gh extension install github/gh-copilot\n' ;;
            debian) printf '  Install: gh extension install github/gh-copilot\n' ;;
            macos)  printf '  Install: gh extension install github/gh-copilot\n' ;;
            *)      printf '  Install: gh extension install github/gh-copilot\n' ;;
          esac
          ;;
        gh)
          case "$os_family" in
            rhel)   printf '  Install: sudo dnf install gh\n' ;;
            debian) printf '  Install: sudo apt install gh\n' ;;
            macos)  printf '  Install: brew install gh\n' ;;
            *)      printf '  Install: https://github.com/cli/cli#installation\n' ;;
          esac
          ;;
        docker)
          case "$os_family" in
            rhel)   printf '  Install: sudo dnf install docker-ce docker-ce-cli containerd.io\n' ;;
            debian) printf '  Install: sudo apt install docker-ce docker-ce-cli containerd.io\n' ;;
            macos)  printf '  Install: brew install --cask docker\n' ;;
            *)      printf '  Install: https://docs.docker.com/engine/install/\n' ;;
          esac
          ;;
      esac
      printf '\n'
    fi
  done

  # Bridge setup
  local bridge_installed
  bridge_installed=$(printf '%s' "$inv" | jq -r '.tools.bridge.installed')
  if [ "$bridge_installed" != "true" ]; then
    any_missing=1
    printf '[ MISSING ] bridge (git-cli-bridge)\n'
    printf '  The bridge-mode-detect.sh script is not installed at:\n'
    printf '  %s\n' "$BRIDGE_DETECT"
    printf '  This is part of the git-cli-bridge skill. Install the skill first.\n\n'
  fi

  if [ "$any_missing" -eq 0 ]; then
    printf 'All tools installed. Current tier: %s (%s)\n' "$tier" "$tier_label"
    printf 'Run "probe.sh check --force" to re-probe versions.\n'
  else
    printf 'Install missing tools above, then run "probe.sh check --force" to update inventory.\n'
    printf 'Target: Tier 2 (full) — all tools available.\n'
  fi
}

# ── main dispatcher ────────────────────────────────────────────────────────────

cmd="${1:-check}"
shift || true

case "$cmd" in
  check) do_check "$@" ;;
  get)   do_get "$@" ;;
  setup) do_setup "$@" ;;
  *)     die "unknown command: $cmd. Usage: probe.sh {check|get|setup} [flags]" ;;
esac
