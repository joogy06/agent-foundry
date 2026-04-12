#!/usr/bin/env bash
# verify-integrity.sh — M10 npm package integrity verification.
#
# Usage: verify-integrity.sh <pkg-name> <version>
# Looks up the expected integrity hash in .github/bridge-integrity.lock and
# compares it against `npm view <pkg>@<version> dist.integrity`.
#
# Fails the workflow (exit 1) on any mismatch.

set -euo pipefail
PKG="${1:?usage: verify-integrity.sh <pkg> <version>}"
VER="${2:?usage: verify-integrity.sh <pkg> <version>}"

LOCK=".github/bridge-integrity.lock"
[ -f "$LOCK" ] || { echo "integrity lock missing: $LOCK" >&2; exit 1; }

EXPECTED="$(awk -v key="${PKG}@${VER}" '$1 == key { print $2; exit }' "$LOCK")"
if [ -z "$EXPECTED" ]; then
  echo "verify-integrity: no entry for ${PKG}@${VER} in $LOCK" >&2
  exit 1
fi

ACTUAL="$(npm view "${PKG}@${VER}" dist.integrity 2>/dev/null || true)"
if [ -z "$ACTUAL" ]; then
  echo "verify-integrity: npm view returned no integrity for ${PKG}@${VER}" >&2
  exit 1
fi

if [ "$EXPECTED" != "$ACTUAL" ]; then
  echo "verify-integrity: MISMATCH for ${PKG}@${VER}" >&2
  echo "  expected: $EXPECTED" >&2
  echo "  actual:   $ACTUAL" >&2
  exit 1
fi

echo "verify-integrity: OK ${PKG}@${VER}"
