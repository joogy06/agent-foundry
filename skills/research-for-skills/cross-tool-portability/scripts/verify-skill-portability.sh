#!/usr/bin/env bash
# verify-skill-portability.sh
#
# Validates a SKILL.md file against the cross-tool portability rules.
# Use this on every cross-tool skill before publishing.
#
# Rules enforced:
#   1. Every top-level frontmatter key is a specification key or a Claude Code
#      key. The list is READ from skill_audit.py at run time (the audit's own
#      tables); this script holds no copy of it. Custom data goes under
#      `metadata:` as quoted strings.
#   2. `name` matches ^[a-z0-9-]+$
#   3. `name` is ≤64 chars
#   4. `description` is a single string (not multi-line, not list)
#   5. `description` is within the specification limit (warning over the
#      audit's limit)
#   6. `description` does not open with "Use when" (subject first)
#   7. SKILL.md body is <500 lines
#   8. All `references/<file>.md` links from SKILL.md resolve to existing files
#   9. Anti-patterns table present (`## Anti-patterns` heading, any letter case)
#
# The full standard is `skill_audit.py audit --only <name> --strict`; run it
# after this script.
#
# Exit codes:
#   0 — clean (all rules pass)
#   1 — file not found / unreadable
#   2 — frontmatter parse error
#   3 — rule violation (unknown key, bad name/description, body too long,
#       broken link, missing anti-patterns table)
#   7 — skill_audit.py (the key list) not found or unreadable
#
# Environment:
#   SKILL_AUDIT_PY — path to skill_audit.py, when it is not at
#                    <skills>/_meta/skill_audit.py beside this skill
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

# The audit's tables are the one list of legal keys and limits. `pwd -P` so a
# linked skill directory still resolves to the tree that holds _meta/.
SKILLS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
AUDIT_PY="${SKILL_AUDIT_PY:-$SKILLS_ROOT/_meta/skill_audit.py}"

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

# 2. every top-level key is on the audit's list (read here, never copied)
printf "2) frontmatter keys check\n"
READ_AUDIT='
import importlib.util, sys
spec = importlib.util.spec_from_file_location("skill_audit", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules["skill_audit"] = mod
spec.loader.exec_module(mod)
print("spec " + " ".join(mod.SPEC_KEYS))
print("claude_code " + " ".join(mod.CLAUDE_CODE_KEYS))
print("description_max %d" % mod.DESCRIPTION_SPEC_MAX_CHARS)
print("description_limit %d" % mod.DESCRIPTION_LIMIT)
'
if ! AUDIT_DATA="$(python3 -c "$READ_AUDIT" "$AUDIT_PY" 2>/dev/null)"; then
  err "cannot read the key list from skill_audit.py: $AUDIT_PY"
  err "set SKILL_AUDIT_PY to its path; no key is accepted without the list"
  exit 7
fi
audit_row() { echo "$AUDIT_DATA" | sed -n "s/^$1 //p" | tr ' ' '\n' | LC_ALL=C sort -u; }
SPEC_LIST="$(audit_row spec)"
CC_LIST="$(audit_row claude_code)"
DESC_MAX="$(audit_row description_max)"
DESC_LIMIT="$(audit_row description_limit)"
if [ -z "$SPEC_LIST" ] || [ -z "$CC_LIST" ] || [ -z "$DESC_MAX" ] || [ -z "$DESC_LIMIT" ]; then
  err "skill_audit.py gave no key list: $AUDIT_PY"
  exit 7
fi
ALLOWED_LIST="$(printf '%s\n%s\n' "$SPEC_LIST" "$CC_LIST" | LC_ALL=C sort -u)"
ACTUAL_KEYS="$(echo "$FRONTMATTER" | grep -oE '^[a-zA-Z_][a-zA-Z0-9_-]*[[:space:]]*:' | tr -d ': \t' | LC_ALL=C sort -u || true)"

UNKNOWN="$(LC_ALL=C comm -23 <(echo "$ACTUAL_KEYS") <(echo "$ALLOWED_LIST"))"
CC_USED="$(LC_ALL=C comm -12 <(echo "$ACTUAL_KEYS") <(echo "$CC_LIST"))"
if [ -z "$UNKNOWN" ]; then
  ok "every top-level key is a specification key or a Claude Code key"
else
  err "frontmatter has keys that are neither specification nor Claude Code keys:"
  echo "$UNKNOWN" | sed 's/^/      /' >&2
  err "custom data goes under 'metadata:' as quoted strings, for example:"
  printf "      metadata:\n        %s: \"...\"\n" "$(echo "$UNKNOWN" | head -1)" >&2
  ERRORS=$((ERRORS + 1))
fi
if [ -n "$CC_USED" ]; then
  warn "Claude Code key(s): $(echo "$CC_USED" | tr '\n' ' ')— read by Claude Code only; claude.ai upload and the Skills API accept specification keys only"
fi
echo

# 3. extract name and description values
printf "3) name and description values\n"
NAME="$(echo "$FRONTMATTER" | grep -E '^name:' | head -1 | sed 's/^name:[[:space:]]*//' | sed 's/^"//; s/"$//' || true)"
DESC="$(echo "$FRONTMATTER" | grep -E '^description:' | head -1 | sed 's/^description:[[:space:]]*//' | sed 's/^"//; s/"$//' | sed "s/^'//; s/'\$//" || true)"

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
  if [ "${#DESC}" -le "$DESC_MAX" ]; then
    ok "description length OK (${#DESC} ≤ $DESC_MAX)"
  else
    err "description too long: ${#DESC} chars (max $DESC_MAX)"
    ERRORS=$((ERRORS + 1))
  fi
  if [ "${#DESC}" -gt "$DESC_LIMIT" ]; then
    warn "description is ${#DESC} chars — the audit's limit is $DESC_LIMIT (aim for about 200)"
  fi
  # Single line check (no embedded newlines after grep -E ^description: head -1)
  if echo "$DESC" | grep -qiE '^use[[:space:]]+when'; then
    err "description opens with 'Use when' — open with the subject, then what the skill does, then when to use it"
    ERRORS=$((ERRORS + 1))
  else
    ok "description does not open with 'Use when'"
  fi
  if ! echo "$DESC" | grep -qiE '(^|[^a-z])when([^a-z]|$)'; then
    warn "description never says when to use the skill — add the situations that call for it"
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
if grep -qiE '^## Anti-patterns' "$SKILL_MD"; then
  ok "anti-patterns section present"
else
  err "no '## Anti-patterns' section found"
  ERRORS=$((ERRORS + 1))
fi
echo

# 9. summary
printf "Summary\n"
if [ "$ERRORS" -eq 0 ]; then
  ok "PASS: $SKILL_MD is portable across Claude Code, Antigravity CLI (agy), Codex CLI, and (via AGENTS.md) GitHub Copilot CLI"
  printf "  next, the full standard: python3 %s audit --root %s --only %s --strict\n" "$AUDIT_PY" "$(dirname "$SKILL_DIR")" "$(basename "$SKILL_DIR")"
  exit 0
else
  err "FAIL: $ERRORS error(s) found"
  exit 3
fi
