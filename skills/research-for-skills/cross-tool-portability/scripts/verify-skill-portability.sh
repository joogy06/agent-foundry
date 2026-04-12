#!/usr/bin/env bash
# verify-skill-portability.sh
#
# Validates a SKILL.md file against the cross-tool portability rules.
# Use this on every cross-tool skill before publishing.
#
# Rules enforced:
#   1. Frontmatter contains ONLY `name` and `description` (no extra keys)
#   2. `name` matches ^[a-z0-9-]+$
#   3. `name` is ≤64 chars
#   4. `description` is a single string (not multi-line, not list)
#   5. `description` is ≤1024 chars
#   6. `description` leads with "Use when" or similar trigger language
#   7. SKILL.md body is <500 lines
#   8. All `references/<file>.md` links from SKILL.md resolve to existing files
#   9. Anti-patterns table present (`## Anti-patterns` heading)
#
# Exit codes:
#   0 — clean (all rules pass)
#   1 — file not found / unreadable
#   2 — frontmatter parse error
#   3 — frontmatter rule violation (extra keys, bad name/description)
#   4 — body too long
#   5 — broken intra-skill link
#   6 — missing anti-patterns table
#
# Usage:
#   bash verify-skill-portability.sh <path/to/SKILL.md>
#   bash verify-skill-portability.sh ~/.claude/skills/my-skill/SKILL.md

set -o errexit
set -o nounset
set -o pipefail

ok() { printf "  [OK]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err() { printf "  [ERR]  %s\n" "$1" >&2; }

# 0. usage
if [ "$#" -ne 1 ]; then
  err "usage: $0 <path/to/SKILL.md>"
  exit 1
fi

SKILL_MD="$1"
if [ ! -f "$SKILL_MD" ]; then
  err "file not found: $SKILL_MD"
  exit 1
fi

SKILL_DIR="$(cd "$(dirname "$SKILL_MD")" && pwd)"

printf "verify-skill-portability.sh\n"
printf "  target: %s\n" "$SKILL_MD"
printf "  dir   : %s\n\n" "$SKILL_DIR"

ERRORS=0

# 1. extract frontmatter (between first two --- lines)
printf "1) extracting frontmatter\n"
FRONTMATTER="$(awk '/^---$/{c++; next} c==1{print}' "$SKILL_MD")"
if [ -z "$FRONTMATTER" ]; then
  err "no frontmatter found (need YAML between --- delimiters at top of file)"
  exit 2
fi
ok "frontmatter extracted ($(echo "$FRONTMATTER" | wc -l) lines)"
echo

# 2. check that frontmatter has ONLY `name` and `description` keys
printf "2) frontmatter keys check\n"
KEYS="$(echo "$FRONTMATTER" | grep -oE '^[a-zA-Z][a-zA-Z0-9_-]*:' | tr -d ':' | sort -u || true)"
EXPECTED_KEYS="description
name"
ACTUAL_KEYS="$(echo "$KEYS" | sort -u)"

if [ "$ACTUAL_KEYS" = "$EXPECTED_KEYS" ]; then
  ok "frontmatter contains only 'name' and 'description'"
else
  err "frontmatter has unexpected keys"
  printf "    expected: name, description\n"
  printf "    actual  : %s\n" "$(echo "$ACTUAL_KEYS" | tr '\n' ',' | sed 's/,$//')"
  EXTRA="$(comm -23 <(echo "$ACTUAL_KEYS") <(echo "$EXPECTED_KEYS"))"
  if [ -n "$EXTRA" ]; then
    err "extra keys present (REMOVE THESE):"
    echo "$EXTRA" | sed 's/^/      /'
  fi
  ERRORS=$((ERRORS + 1))
fi
echo

# 3. extract name and description values
printf "3) name and description values\n"
NAME="$(echo "$FRONTMATTER" | grep -E '^name:' | head -1 | sed 's/^name:[[:space:]]*//' | sed 's/^"//; s/"$//' || true)"
DESC="$(echo "$FRONTMATTER" | grep -E '^description:' | head -1 | sed 's/^description:[[:space:]]*//' | sed 's/^"//; s/"$//' || true)"

if [ -z "$NAME" ]; then
  err "no 'name' field found"
  ERRORS=$((ERRORS + 1))
else
  ok "name: $NAME"
fi
if [ -z "$DESC" ]; then
  err "no 'description' field found"
  ERRORS=$((ERRORS + 1))
else
  DESC_LEN=${#DESC}
  ok "description: ${DESC_LEN} chars"
fi
echo

# 4. name pattern + length
printf "4) name validation\n"
if [ -n "$NAME" ]; then
  if echo "$NAME" | grep -qE '^[a-z0-9-]+$'; then
    ok "name matches ^[a-z0-9-]+$"
  else
    err "name contains invalid characters (must match ^[a-z0-9-]+$): '$NAME'"
    ERRORS=$((ERRORS + 1))
  fi
  if [ "${#NAME}" -le 64 ]; then
    ok "name length OK (${#NAME} ≤ 64)"
  else
    err "name too long: ${#NAME} chars (max 64)"
    ERRORS=$((ERRORS + 1))
  fi
fi
echo

# 5. description checks
printf "5) description validation\n"
if [ -n "$DESC" ]; then
  if [ "${#DESC}" -le 1024 ]; then
    ok "description length OK (${#DESC} ≤ 1024)"
  else
    err "description too long: ${#DESC} chars (max 1024)"
    ERRORS=$((ERRORS + 1))
  fi
  # Single line check (no embedded newlines after grep -E ^description: head -1)
  if echo "$DESC" | grep -qE 'use when|use this skill when' -i; then
    ok "description leads with trigger language ('Use when ...')"
  else
    warn "description does not lead with 'Use when ...' — may not trigger reliably"
  fi
fi
echo

# 6. body length (after second ---)
printf "6) body length\n"
BODY_LINES=$(awk '/^---$/{c++; next} c==2{print}' "$SKILL_MD" | wc -l)
TOTAL_LINES=$(wc -l < "$SKILL_MD")
ok "body: $BODY_LINES lines (total file: $TOTAL_LINES lines)"
if [ "$BODY_LINES" -lt 500 ]; then
  ok "body under 500 lines"
else
  err "body is $BODY_LINES lines (max 500). Move content to references/*.md"
  ERRORS=$((ERRORS + 1))
fi
echo

# 7. intra-skill links
printf "7) intra-skill link resolution\n"
LINKS="$(grep -oE '\(references/[a-z0-9_./-]+\.md\)' "$SKILL_MD" | tr -d '()' | sort -u || true)"
if [ -z "$LINKS" ]; then
  warn "no references/*.md links found in SKILL.md (acceptable if skill has no references/)"
else
  BROKEN=0
  for link in $LINKS; do
    if [ -f "$SKILL_DIR/$link" ]; then
      ok "$link resolves"
    else
      err "$link is BROKEN (file does not exist)"
      BROKEN=$((BROKEN + 1))
      ERRORS=$((ERRORS + 1))
    fi
  done
  if [ "$BROKEN" -eq 0 ]; then
    ok "all $(echo "$LINKS" | wc -l) reference links resolve"
  fi
fi
echo

# 8. anti-patterns table
printf "8) anti-patterns table\n"
if grep -qE '^## Anti-patterns' "$SKILL_MD"; then
  ok "anti-patterns section present"
else
  err "no '## Anti-patterns' section found"
  ERRORS=$((ERRORS + 1))
fi
echo

# 9. summary
printf "Summary\n"
if [ "$ERRORS" -eq 0 ]; then
  ok "PASS: $SKILL_MD is portable across Claude Code, Gemini CLI, Codex CLI, and (via AGENTS.md) GitHub Copilot CLI"
  exit 0
else
  err "FAIL: $ERRORS error(s) found"
  exit 3
fi
