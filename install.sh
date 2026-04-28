#!/usr/bin/env bash
# agent-foundry installer — Linux/macOS convenience wrapper.
# Just calls python3 install.py with whatever args you pass.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/install.py" "$@"
