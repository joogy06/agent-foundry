#!/usr/bin/env bash
# startup-script.sh — Workstation startup template with use-time secret fetch
#
# Add this to your workstation config or run on first boot inside the workstation.
# Demonstrates the use-time secret fetch pattern from references/secrets-and-security.md.
#
# This is intended to be sourced or run interactively, not invoked from systemd.

set -o errexit
set -o nounset
set -o pipefail

# 1. Verify ADC is available (provided by metadata server on GCP Workstations)
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "WARNING: ADC not available. AI CLIs that use Vertex will fail." >&2
fi

# 2. Set Vertex env vars (these should be in /etc/skel/.bashrc from the Dockerfile,
#    but defaults here as a safety net)
export CLAUDE_CODE_USE_VERTEX="${CLAUDE_CODE_USE_VERTEX:-1}"
export GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI:-1}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
export ANTHROPIC_VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID:-$GOOGLE_CLOUD_PROJECT}"
export ANTHROPIC_VERTEX_REGION="${ANTHROPIC_VERTEX_REGION:-$GOOGLE_CLOUD_LOCATION}"

# 3. Helper function: fetch a secret from Secret Manager at use time
#    Returns the secret value to stdout. NEVER stores it on disk.
secret() {
  local name="${1:?usage: secret <name>}"
  gcloud secrets versions access latest --secret="$name" 2>/dev/null
}

# 4. Pre-fetch tokens for tools that need them at command time.
#    These are exported into a CHILD process only, never written to a file.
#    Use the function inline:
#
#       COPILOT_GITHUB_TOKEN=$(secret copilot-token) copilot -p "..." --allow-all-tools
#       OPENAI_API_KEY=$(secret openai-api-key) codex exec "..."
#
#    DO NOT do this:
#       export COPILOT_GITHUB_TOKEN=$(secret copilot-token)   # leaks via env to all processes
#
# Optional convenience aliases — use only if you accept the trade-off
# (the env var is in the parent shell, exposed to /proc/<pid>/environ)
#
#   alias cop='COPILOT_GITHUB_TOKEN=$(secret copilot-token) copilot'
#   alias cdx='OPENAI_API_KEY=$(secret openai-api-key) codex'

# 5. Sanity-check tool availability
echo "Tool versions:"
claude --version 2>/dev/null | head -1 || echo "  claude: not installed"
gemini --version 2>/dev/null | head -1 || echo "  gemini: not installed"
copilot --version 2>/dev/null | head -1 || echo "  copilot: not installed"
gh --version 2>/dev/null | head -1 || echo "  gh: not installed"

# 6. Sanity-check ADC
echo
echo "ADC token (first 20 chars):"
gcloud auth application-default print-access-token 2>/dev/null | cut -c1-20 || echo "  ADC not available"

# 7. Sanity-check chrony (clock sync)
echo
echo "Clock sync (chrony):"
if command -v chronyc >/dev/null 2>&1; then
  chronyc tracking 2>/dev/null | head -3 || echo "  chrony not running"
else
  echo "  chrony not installed — risk of OAuth 401s, see references/gotchas-and-fixes.md"
fi

echo
echo "Workstation ready. AI CLIs will use Vertex via ADC."
echo "Use 'secret <name>' to fetch a token at command time."
