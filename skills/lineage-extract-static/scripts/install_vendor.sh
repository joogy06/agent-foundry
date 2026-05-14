#!/usr/bin/env bash
# install_vendor.sh — download Cytoscape vendor files for air-gap-safe rendering.
#
# Component: install_vendor (WP-7 in S033 — infrastructure, no contract entry).
#
# Downloads cytoscape.min.js + cytoscape-cose-bilkent + dagre to
# ~/.claude/skills/visual-companion/templates/vendor/. These are reused by
# the lineage-extract-static renderer (and visual-companion's graph-cytoscape
# template, intent-map-render's D2 emitter, etc.).
#
# Already-vendored files are skipped (curl --skip-existing semantics).
# Run with --force to re-download.
#
# Usage:
#   bash install_vendor.sh           # Download missing files
#   bash install_vendor.sh --force   # Re-download all files
#   bash install_vendor.sh --check   # Report status without downloading

set -euo pipefail

VENDOR_DIR="${HOME}/.claude/skills/visual-companion/templates/vendor"

# Pinned versions (per design §13.1 — bump deliberately + re-test + history entry)
CYTOSCAPE_VERSION="3.28.1"
DAGRE_VERSION="0.8.5"
COSE_BILKENT_VERSION="4.1.0"

CYTOSCAPE_URL="https://unpkg.com/cytoscape@${CYTOSCAPE_VERSION}/dist/cytoscape.min.js"
DAGRE_URL="https://unpkg.com/dagre@${DAGRE_VERSION}/dist/dagre.min.js"
COSE_BILKENT_URL="https://unpkg.com/cytoscape-cose-bilkent@${COSE_BILKENT_VERSION}/cytoscape-cose-bilkent.js"

CYTOSCAPE_OUT="${VENDOR_DIR}/cytoscape.min.js"
DAGRE_OUT="${VENDOR_DIR}/dagre.min.js"
COSE_BILKENT_OUT="${VENDOR_DIR}/cytoscape-cose-bilkent.js"

MODE="install"
if [ "${1:-}" = "--force" ]; then
    MODE="force"
elif [ "${1:-}" = "--check" ]; then
    MODE="check"
fi

mkdir -p "${VENDOR_DIR}"

report_status() {
    local path="$1"
    local label="$2"
    local url="$3"
    if [ -f "${path}" ]; then
        local size
        size=$(stat -c%s "${path}" 2>/dev/null || stat -f%z "${path}" 2>/dev/null || echo 0)
        echo "  [present] ${label}: ${path} (${size} bytes)"
    else
        echo "  [missing] ${label}: would download from ${url}"
    fi
}

download_one() {
    local url="$1"
    local path="$2"
    local label="$3"

    if [ "${MODE}" = "check" ]; then
        report_status "${path}" "${label}" "${url}"
        return 0
    fi

    if [ "${MODE}" = "install" ] && [ -f "${path}" ]; then
        echo "  [skip] ${label}: already present at ${path}"
        return 0
    fi

    echo "  [fetch] ${label}: downloading from ${url}"
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "${url}" -o "${path}.tmp.$$"; then
            echo "  [fail] ${label}: curl failed for ${url}" >&2
            rm -f "${path}.tmp.$$"
            return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -q "${url}" -O "${path}.tmp.$$"; then
            echo "  [fail] ${label}: wget failed for ${url}" >&2
            rm -f "${path}.tmp.$$"
            return 1
        fi
    else
        echo "  [fail] Neither curl nor wget available; cannot download" >&2
        return 1
    fi

    # Verify file is non-empty
    if [ ! -s "${path}.tmp.$$" ]; then
        echo "  [fail] ${label}: downloaded file is empty" >&2
        rm -f "${path}.tmp.$$"
        return 1
    fi

    # Atomic rename
    mv -f "${path}.tmp.$$" "${path}"
    local size
    size=$(stat -c%s "${path}" 2>/dev/null || stat -f%z "${path}" 2>/dev/null || echo 0)
    echo "  [ok]   ${label}: ${size} bytes saved to ${path}"
}

echo "lineage-extract-static / visual-companion vendor installer"
echo "Vendor dir: ${VENDOR_DIR}"
echo "Mode: ${MODE}"
echo ""

failed=0
download_one "${CYTOSCAPE_URL}" "${CYTOSCAPE_OUT}" "cytoscape@${CYTOSCAPE_VERSION}" || failed=$((failed + 1))
download_one "${DAGRE_URL}" "${DAGRE_OUT}" "dagre@${DAGRE_VERSION}" || failed=$((failed + 1))
download_one "${COSE_BILKENT_URL}" "${COSE_BILKENT_OUT}" "cose-bilkent@${COSE_BILKENT_VERSION}" || failed=$((failed + 1))

echo ""
if [ "${failed}" -gt 0 ]; then
    echo "Done with ${failed} failures. Air-gap rendering will fall back to Mermaid-only output for any missing vendor files."
    exit 2
fi

if [ "${MODE}" = "check" ]; then
    echo "Done (check mode — no downloads performed)."
else
    echo "Done. Cytoscape vendor files installed at ${VENDOR_DIR}/"
fi
exit 0
