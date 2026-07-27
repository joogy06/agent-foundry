#!/usr/bin/env bash
# load-secrets.sh — deliver secrets from ~/.secrets/ into the process environment.
#
#   source load-secrets.sh <project>     # loads common.env then <project>.env
#
# Storage is ~/.secrets/<project>.env (0600). This script is the DELIVERY half:
# it exports those values for the current process only.
#
# PRECEDENCE: a variable already set in the real environment WINS over the file.
# That is deliberate — it keeps one-off overrides, CI injection and container env
# working without editing files.
#
# This is plaintext-at-rest, not a secret manager. See references/storage-standard.md.

_ls_die() { echo "load-secrets: $*" >&2; return 1; }

load_secrets() {
  local project="${1:-}"
  local dir="${SECRETS_DIR:-$HOME/.secrets}"
  [ -n "$project" ] || { _ls_die "usage: load_secrets <project>"; return 1; }
  [ -d "$dir" ]     || { _ls_die "no $dir (mkdir -p $dir && chmod 700 $dir)"; return 1; }

  # Warn loudly on a world/group-readable secrets dir rather than silently proceeding.
  local dmode; dmode=$(stat -c '%a' "$dir" 2>/dev/null || stat -f '%Lp' "$dir" 2>/dev/null)
  [ "$dmode" = "700" ] || echo "load-secrets: WARNING $dir is mode $dmode, expected 700" >&2

  # Snapshot the REAL environment first. Precedence: real env > <project>.env >
  # common.env. Without this, a value exported from common.env would look
  # "already set" and wrongly block <project>.env from overriding it.
  local _ls_pre; _ls_pre=$(export -p | sed -n 's/^declare -x \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p;s/^export \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p')
  local f loaded=0
  for f in "$dir/common.env" "$dir/$project.env"; do
    [ -f "$f" ] || continue
    local fmode; fmode=$(stat -c '%a' "$f" 2>/dev/null || stat -f '%Lp' "$f" 2>/dev/null)
    [ "$fmode" = "600" ] || echo "load-secrets: WARNING $f is mode $fmode, expected 600" >&2

    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in ''|'#'*) continue ;; esac
      line="${line#export }"
      local key="${line%%=*}" val="${line#*=}"
      case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac   # skip malformed keys
      # strip one layer of matching quotes
      case "$val" in \"*\") val="${val#\"}"; val="${val%\"}" ;; \'*\') val="${val#\'}"; val="${val%\'}" ;; esac
      # real env wins
      # skip only if the key came from the REAL environment, not from a file we loaded
      if ! printf '%s\n' "$_ls_pre" | grep -qx -- "$key"; then export "$key=$val"; fi
    done < "$f"
    loaded=$((loaded+1))
  done

  [ "$loaded" -gt 0 ] || { _ls_die "no secrets files for '$project' in $dir"; return 1; }
  return 0
}

# Allow both `source load-secrets.sh proj` and `. load-secrets.sh; load_secrets proj`
if [ -n "${1:-}" ]; then load_secrets "$1"; fi
