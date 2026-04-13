#!/usr/bin/env bash
# discover.sh — Fast knowledge source discovery for the knowledge-grounding skill.
#
# Usage:
#   discover.sh discover [--force] [--remote] [--silent] [--json]
#   discover.sh status
#   discover.sh get <jq-path>
#
# State files:
#   ~/.claude/state/sources.json                           (persistent: what sources exist)
#   $XDG_RUNTIME_DIR/knowledge-grounding/session-<id>.json (volatile: reachability, auth)
#
# Designed to complete local scan in under 3 seconds.
# Remote probes are LAZY — only run with --remote flag or on first query that needs them.

set -euo pipefail

# -- constants ----------------------------------------------------------------

SOURCES_FILE="$HOME/.claude/state/sources.json"
CONFIG_FILE="$HOME/.knowledge-grounding.yaml"
WIKI_REGISTRY="$HOME/.wiki-registry.yaml"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
SESSION_DIR="$RUNTIME_DIR/knowledge-grounding"
STALENESS_HOURS=24
DNS_CANARY_HOST="dns.google"
DNS_CANARY_TIMEOUT=1

# -- helpers ------------------------------------------------------------------

die()     { printf 'knowledge-grounding: %s\n' "$1" >&2; exit 1; }
now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

session_id() {
  printf '%s' "${CLAUDE_SESSION_ID:-${FORGE_SESSION_ID:-ppid-$$}}"
}

session_file() {
  printf '%s/session-%s.json' "$SESSION_DIR" "$(session_id)"
}

sources_age_hours() {
  if [ ! -f "$SOURCES_FILE" ]; then
    echo 999
    return
  fi
  local mtime now
  mtime=$(stat -c %Y "$SOURCES_FILE" 2>/dev/null || stat -f %m "$SOURCES_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  echo $(( (now - mtime) / 3600 ))
}

# Read a YAML value using yq (if available) or grep fallback.
# $1 = file, $2 = yq path
yaml_val() {
  local file="$1" path="$2"
  if command -v yq >/dev/null 2>&1; then
    yq eval "$path" "$file" 2>/dev/null || echo ""
  else
    echo ""
  fi
}

# -- internet canary ----------------------------------------------------------

check_internet() {
  # 1-second timeout DNS lookup — not HTTP, not curl. Fast and reliable.
  if command -v host >/dev/null 2>&1; then
    timeout "$DNS_CANARY_TIMEOUT" host -W "$DNS_CANARY_TIMEOUT" "$DNS_CANARY_HOST" >/dev/null 2>&1 && echo "true" || echo "false"
  elif command -v nslookup >/dev/null 2>&1; then
    timeout "$DNS_CANARY_TIMEOUT" nslookup -timeout="$DNS_CANARY_TIMEOUT" "$DNS_CANARY_HOST" >/dev/null 2>&1 && echo "true" || echo "false"
  elif command -v dig >/dev/null 2>&1; then
    timeout "$DNS_CANARY_TIMEOUT" dig +time="$DNS_CANARY_TIMEOUT" +tries=1 "$DNS_CANARY_HOST" >/dev/null 2>&1 && echo "true" || echo "false"
  else
    # No DNS tool available — assume unreachable
    echo "false"
  fi
}

# -- wiki discovery -----------------------------------------------------------

discover_wikis() {
  # Returns JSON array of wiki source objects
  local wikis="[]"

  # 1. Scan ~/.wiki-registry.yaml
  if [ -f "$WIKI_REGISTRY" ] && command -v yq >/dev/null 2>&1; then
    local wiki_names
    wiki_names=$(yq eval '.wikis | keys | .[]' "$WIKI_REGISTRY" 2>/dev/null) || wiki_names=""
    for name in $wiki_names; do
      local wpath wmode wcount wdesc wauto
      wpath=$(yq eval ".wikis.${name}.path" "$WIKI_REGISTRY" 2>/dev/null || echo "")
      wmode=$(yq eval ".wikis.${name}.mode" "$WIKI_REGISTRY" 2>/dev/null || echo "unknown")
      wcount=$(yq eval ".wikis.${name}.page_count" "$WIKI_REGISTRY" 2>/dev/null || echo "0")
      wdesc=$(yq eval ".wikis.${name}.description" "$WIKI_REGISTRY" 2>/dev/null || echo "")

      # Check for auto_consult from .wiki-link in bound projects
      wauto="false"
      local bound_projects
      bound_projects=$(yq eval ".wikis.${name}.bound_projects[]" "$WIKI_REGISTRY" 2>/dev/null) || bound_projects=""
      for bp in $bound_projects; do
        if [ -f "${bp}/.wiki-link" ]; then
          local ac
          ac=$(yq eval '.auto_consult' "${bp}/.wiki-link" 2>/dev/null || echo "false")
          if [ "$ac" = "true" ]; then
            wauto="true"
            break
          fi
        fi
      done

      # Compute freshness from last_accessed
      local freshness
      freshness=$(yq eval ".wikis.${name}.last_accessed" "$WIKI_REGISTRY" 2>/dev/null || echo "unknown")

      if [ -n "$wpath" ] && [ "$wpath" != "null" ] && [ -d "$wpath" ]; then
        wikis=$(printf '%s' "$wikis" | jq --arg id "wiki_${name}" \
          --arg path "$wpath" \
          --argjson auto_consult "$wauto" \
          --argjson page_count "${wcount:-0}" \
          --arg freshness "$freshness" \
          --arg desc "$wdesc" \
          '. + [{
            id: $id,
            type: "wiki",
            path: $path,
            auto_consult: $auto_consult,
            page_count: $page_count,
            freshness: $freshness,
            description: $desc,
            query_via: "wiki skill (grep)"
          }]')
      fi
    done
  fi

  # 2. Scan CWD + parents for .wiki-link files
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    if [ -f "${dir}/.wiki-link" ] && command -v yq >/dev/null 2>&1; then
      local link_wiki
      link_wiki=$(yq eval '.wiki' "${dir}/.wiki-link" 2>/dev/null || echo "")
      if [ -n "$link_wiki" ] && [ "$link_wiki" != "null" ]; then
        # Check if already discovered via registry
        local already
        already=$(printf '%s' "$wikis" | jq --arg id "wiki_${link_wiki}" '[.[] | select(.id == $id)] | length')
        if [ "$already" = "0" ]; then
          local link_path link_auto
          link_path=$(yq eval '.path' "${dir}/.wiki-link" 2>/dev/null || echo "")
          link_auto=$(yq eval '.auto_consult' "${dir}/.wiki-link" 2>/dev/null || echo "false")
          [ "$link_auto" != "true" ] && link_auto="false"
          if [ -n "$link_path" ] && [ "$link_path" != "null" ] && [ -d "$link_path" ]; then
            wikis=$(printf '%s' "$wikis" | jq --arg id "wiki_${link_wiki}" \
              --arg path "$link_path" \
              --argjson auto_consult "$link_auto" \
              '. + [{
                id: $id,
                type: "wiki",
                path: $path,
                auto_consult: $auto_consult,
                page_count: 0,
                freshness: "unknown",
                query_via: "wiki skill (grep)"
              }]')
          fi
        fi
      fi
    fi
    # Also check for embedded .wiki/ directory
    if [ -d "${dir}/.wiki" ]; then
      local edir_name
      edir_name=$(basename "$dir")
      local already
      already=$(printf '%s' "$wikis" | jq --arg id "wiki_embedded_${edir_name}" '[.[] | select(.id == $id)] | length')
      if [ "$already" = "0" ]; then
        wikis=$(printf '%s' "$wikis" | jq --arg id "wiki_embedded_${edir_name}" \
          --arg path "${dir}/.wiki" \
          '. + [{
            id: $id,
            type: "wiki",
            path: $path,
            auto_consult: false,
            page_count: 0,
            freshness: "unknown",
            query_via: "wiki skill (grep)"
          }]')
      fi
    fi
    dir=$(dirname "$dir")
  done

  printf '%s' "$wikis"
}

# -- local docs discovery -----------------------------------------------------

discover_local_docs() {
  # Returns JSON array of local doc source objects
  local docs="[]"

  # Scan CWD for project documentation
  local cwd="$PWD"
  local has_project_md="false"
  local has_history_md="false"
  local has_component_docs="false"
  local has_docs_dir="false"

  [ -f "${cwd}/PROJECT.md" ] && has_project_md="true"
  [ -f "${cwd}/history.md" ] && has_history_md="true"
  [ -d "${cwd}/docs/components" ] && has_component_docs="true"
  [ -d "${cwd}/docs" ] && has_docs_dir="true"

  if [ "$has_project_md" = "true" ] || [ "$has_docs_dir" = "true" ]; then
    docs=$(printf '%s' "$docs" | jq --arg path "$cwd" \
      --argjson has_project_md "$has_project_md" \
      --argjson has_history_md "$has_history_md" \
      --argjson has_component_docs "$has_component_docs" \
      '. + [{
        id: "project_docs",
        type: "local_docs",
        path: $path,
        has_project_md: $has_project_md,
        has_history_md: $has_history_md,
        has_component_docs: $has_component_docs,
        query_via: "Read/Grep tools"
      }]')
  fi

  # Scan configured doc_paths from config
  if [ -f "$CONFIG_FILE" ] && command -v yq >/dev/null 2>&1; then
    local doc_paths
    doc_paths=$(yq eval '.doc_paths[]' "$CONFIG_FILE" 2>/dev/null) || doc_paths=""
    local idx=0
    for dp in $doc_paths; do
      # Expand globs
      local expanded
      expanded=$(ls -d $dp 2>/dev/null) || expanded=""
      for epath in $expanded; do
        if [ -d "$epath" ] || [ -f "$epath" ]; then
          local eid="doc_path_${idx}"
          idx=$((idx + 1))
          docs=$(printf '%s' "$docs" | jq --arg id "$eid" \
            --arg path "$epath" \
            '. + [{
              id: $id,
              type: "local_docs",
              path: $path,
              query_via: "Read/Grep tools"
            }]')
        fi
      done
    done
  fi

  # Scan configured shared drives
  if [ -f "$CONFIG_FILE" ] && command -v yq >/dev/null 2>&1; then
    local sd_count
    sd_count=$(yq eval '.shared_drives | length' "$CONFIG_FILE" 2>/dev/null) || sd_count="0"
    local i=0
    while [ "$i" -lt "${sd_count:-0}" ]; do
      local sd_path sd_label
      sd_path=$(yq eval ".shared_drives[$i].path" "$CONFIG_FILE" 2>/dev/null || echo "")
      sd_label=$(yq eval ".shared_drives[$i].label" "$CONFIG_FILE" 2>/dev/null || echo "")
      if [ -n "$sd_path" ] && [ "$sd_path" != "null" ] && [ -d "$sd_path" ]; then
        docs=$(printf '%s' "$docs" | jq --arg id "shared_drive_${i}" \
          --arg path "$sd_path" \
          --arg label "$sd_label" \
          '. + [{
            id: $id,
            type: "shared_drive",
            path: $path,
            label: $label,
            query_via: "Read/Grep tools"
          }]')
      fi
      i=$((i + 1))
    done
  fi

  printf '%s' "$docs"
}

# -- enterprise endpoint discovery (config-only) ------------------------------

discover_endpoints() {
  # Returns JSON array of enterprise endpoint sources (from config, NOT probed)
  local endpoints="[]"

  if [ ! -f "$CONFIG_FILE" ] || ! command -v yq >/dev/null 2>&1; then
    printf '%s' "$endpoints"
    return
  fi

  # Confluence
  local conf_url
  conf_url=$(yq eval '.endpoints.confluence.url' "$CONFIG_FILE" 2>/dev/null || echo "")
  if [ -n "$conf_url" ] && [ "$conf_url" != "null" ]; then
    local conf_auth conf_spaces
    conf_auth=$(yq eval '.endpoints.confluence.auth' "$CONFIG_FILE" 2>/dev/null || echo "unknown")
    conf_spaces=$(yq eval '.endpoints.confluence.spaces | @json' "$CONFIG_FILE" 2>/dev/null || echo "[]")
    [ "$conf_spaces" = "null" ] && conf_spaces="[]"
    endpoints=$(printf '%s' "$endpoints" | jq --arg url "$conf_url" \
      --arg auth "$conf_auth" \
      --argjson spaces "$conf_spaces" \
      '. + [{
        id: "confluence_main",
        type: "confluence",
        url: $url,
        auth_method: $auth,
        spaces: $spaces,
        configured: true,
        probed: false,
        query_via: "confluence-rest-api skill"
      }]')
  fi

  # Jira
  local jira_url
  jira_url=$(yq eval '.endpoints.jira.url' "$CONFIG_FILE" 2>/dev/null || echo "")
  if [ -n "$jira_url" ] && [ "$jira_url" != "null" ]; then
    local jira_auth jira_projects
    jira_auth=$(yq eval '.endpoints.jira.auth' "$CONFIG_FILE" 2>/dev/null || echo "unknown")
    jira_projects=$(yq eval '.endpoints.jira.projects | @json' "$CONFIG_FILE" 2>/dev/null || echo "[]")
    [ "$jira_projects" = "null" ] && jira_projects="[]"
    endpoints=$(printf '%s' "$endpoints" | jq --arg url "$jira_url" \
      --arg auth "$jira_auth" \
      --argjson projects "$jira_projects" \
      '. + [{
        id: "jira_platform",
        type: "jira",
        url: $url,
        auth_method: $auth,
        projects: $projects,
        configured: true,
        probed: false,
        query_via: "jira-rest-api skill"
      }]')
  fi

  # Vector store
  local vec_url
  vec_url=$(yq eval '.endpoints.vector_store.url' "$CONFIG_FILE" 2>/dev/null || echo "")
  if [ -n "$vec_url" ] && [ "$vec_url" != "null" ]; then
    local vec_type vec_colls
    vec_type=$(yq eval '.endpoints.vector_store.type' "$CONFIG_FILE" 2>/dev/null || echo "unknown")
    vec_colls=$(yq eval '.endpoints.vector_store.collections | @json' "$CONFIG_FILE" 2>/dev/null || echo "[]")
    [ "$vec_colls" = "null" ] && vec_colls="[]"
    endpoints=$(printf '%s' "$endpoints" | jq --arg url "$vec_url" \
      --arg engine "$vec_type" \
      --argjson collections "$vec_colls" \
      '. + [{
        id: "vector_store",
        type: "vector_store",
        engine: $engine,
        url: $url,
        collections: $collections,
        configured: true,
        probed: false,
        query_via: "research-vectorization skill"
      }]')
  fi

  printf '%s' "$endpoints"
}

# -- discover (main operation) ------------------------------------------------

do_discover() {
  local force=0
  local remote=0
  local silent=0
  local json_out=0

  for arg in "$@"; do
    case "$arg" in
      --force)  force=1 ;;
      --remote) remote=1 ;;
      --silent) silent=1 ;;
      --json)   json_out=1 ;;
      *)        die "unknown flag: $arg" ;;
    esac
  done

  # Skip if manifest is fresh (unless --force)
  local age
  age=$(sources_age_hours)
  if [ "$force" -eq 0 ] && [ "$age" -lt "$STALENESS_HOURS" ] && [ -f "$SOURCES_FILE" ]; then
    # Ensure session file exists even when reusing fresh manifest
    if [ ! -f "$(session_file)" ]; then
      mkdir -p "$SESSION_DIR"
      local manifest_data internet_r
      manifest_data=$(cat "$SOURCES_FILE")
      internet_r=$(printf '%s' "$manifest_data" | jq -r '.internet_reachable')

      local active_s="[]" degraded_s="[]" unavail_s="[]" remote_s="{}"
      for src_id in $(printf '%s' "$manifest_data" | jq -r '.sources | to_entries[] | select(.value.type == "wiki" or .value.type == "local_docs" or .value.type == "shared_drive") | .key'); do
        active_s=$(printf '%s' "$active_s" | jq --arg s "$src_id" '. + [$s]')
      done
      for src_id in $(printf '%s' "$manifest_data" | jq -r '.sources | to_entries[] | select(.value.type == "confluence" or .value.type == "jira" or .value.type == "vector_store") | .key'); do
        remote_s=$(printf '%s' "$remote_s" | jq --arg k "$src_id" '. + {($k): {"reachable": "not-yet-probed", "authenticated": "not-yet-probed"}}')
      done
      if [ "$internet_r" = "true" ]; then
        active_s=$(printf '%s' "$active_s" | jq '. + ["internet"]')
        remote_s=$(printf '%s' "$remote_s" | jq '. + {"internet": {"reachable": true}}')
      else
        unavail_s=$(printf '%s' "$unavail_s" | jq '. + ["internet"]')
        remote_s=$(printf '%s' "$remote_s" | jq '. + {"internet": {"reachable": false}}')
      fi

      local stub_sess
      stub_sess=$(jq -n \
        --arg session_id "$(session_id)" \
        --arg probed_at "$(now_iso)" \
        --argjson remote_status "$remote_s" \
        --argjson active_sources "$active_s" \
        --argjson degraded_sources "$degraded_s" \
        --argjson unavailable_sources "$unavail_s" \
        '{session_id: $session_id, probed_at: $probed_at, remote_status: $remote_status, active_sources: $active_sources, degraded_sources: $degraded_sources, unavailable_sources: $unavailable_sources}')
      printf '%s\n' "$stub_sess" > "$(session_file)"
    fi

    if [ "$silent" -eq 1 ]; then
      return 0
    fi
    if [ "$json_out" -eq 1 ]; then
      local existing sess_data
      existing=$(cat "$SOURCES_FILE")
      if [ -f "$(session_file)" ]; then
        sess_data=$(cat "$(session_file)")
        jq -n --argjson sources "$existing" --argjson session "$sess_data" \
          '{sources: $sources, session: $session}'
      else
        jq -n --argjson sources "$existing" '{sources: $sources}'
      fi
    else
      printf 'Sources manifest is fresh (%dh old, threshold %dh). Use --force to re-probe.\n' "$age" "$STALENESS_HOURS"
    fi
    return 0
  fi

  # -- Local discovery (must be <3 seconds) --

  # Internet canary
  local internet_reachable
  internet_reachable=$(check_internet)

  # Compute grounding mode
  local grounding_mode="full"
  if [ "$internet_reachable" = "false" ]; then
    grounding_mode="internal-only"
  fi

  # Strict airgap from config
  local strict_airgap="false"
  if [ -f "$CONFIG_FILE" ] && command -v yq >/dev/null 2>&1; then
    local sa
    sa=$(yq eval '.strict_airgap' "$CONFIG_FILE" 2>/dev/null || echo "false")
    [ "$sa" = "true" ] && strict_airgap="true"
  fi

  # Discover sources
  local wiki_sources local_sources endpoint_sources
  wiki_sources=$(discover_wikis)
  local_sources=$(discover_local_docs)
  endpoint_sources=$(discover_endpoints)

  # Build sources map from arrays
  local sources_map="{}"
  local all_sources
  all_sources=$(jq -n --argjson w "$wiki_sources" --argjson l "$local_sources" --argjson e "$endpoint_sources" \
    '$w + $l + $e')

  local count
  count=$(printf '%s' "$all_sources" | jq 'length')
  local i=0
  while [ "$i" -lt "$count" ]; do
    local sid src
    sid=$(printf '%s' "$all_sources" | jq -r ".[$i].id")
    src=$(printf '%s' "$all_sources" | jq ".[$i] | del(.id)")
    sources_map=$(printf '%s' "$sources_map" | jq --arg k "$sid" --argjson v "$src" '. + {($k): $v}')
    i=$((i + 1))
  done

  # Add internet source
  sources_map=$(printf '%s' "$sources_map" | jq --argjson reachable "$internet_reachable" \
    '. + {"internet": {"type": "web", "reachable": $reachable, "query_via": "web-research skill"}}')

  # Build manifest
  local manifest
  manifest=$(jq -n \
    --arg last_probed "$(now_iso)" \
    --argjson internet_reachable "$internet_reachable" \
    --arg grounding_mode "$grounding_mode" \
    --argjson strict_airgap "$strict_airgap" \
    --argjson sources "$sources_map" \
    '{
      version: 1,
      last_probed: $last_probed,
      internet_reachable: $internet_reachable,
      grounding_mode: $grounding_mode,
      strict_airgap: $strict_airgap,
      sources: $sources
    }')

  # Write manifest
  mkdir -p "$(dirname "$SOURCES_FILE")"
  printf '%s\n' "$manifest" > "$SOURCES_FILE"

  # -- Session state stub --
  mkdir -p "$SESSION_DIR"

  # Classify sources by remote probing status
  local active_sources degraded_sources unavailable_sources
  active_sources="[]"
  degraded_sources="[]"
  unavailable_sources="[]"

  # Local sources are always active
  for src_id in $(printf '%s' "$manifest" | jq -r '.sources | to_entries[] | select(.value.type == "wiki" or .value.type == "local_docs" or .value.type == "shared_drive") | .key'); do
    active_sources=$(printf '%s' "$active_sources" | jq --arg s "$src_id" '. + [$s]')
  done

  # Remote sources default to "not-yet-probed"
  local remote_status="{}"
  for src_id in $(printf '%s' "$manifest" | jq -r '.sources | to_entries[] | select(.value.type == "confluence" or .value.type == "jira" or .value.type == "vector_store") | .key'); do
    remote_status=$(printf '%s' "$remote_status" | jq --arg k "$src_id" \
      '. + {($k): {"reachable": "not-yet-probed", "authenticated": "not-yet-probed"}}')
  done

  # Internet source
  if [ "$internet_reachable" = "true" ]; then
    active_sources=$(printf '%s' "$active_sources" | jq '. + ["internet"]')
    remote_status=$(printf '%s' "$remote_status" | jq '. + {"internet": {"reachable": true}}')
  else
    unavailable_sources=$(printf '%s' "$unavailable_sources" | jq '. + ["internet"]')
    remote_status=$(printf '%s' "$remote_status" | jq '. + {"internet": {"reachable": false}}')
  fi

  local sess
  sess=$(jq -n \
    --arg session_id "$(session_id)" \
    --arg probed_at "$(now_iso)" \
    --argjson remote_status "$remote_status" \
    --argjson active_sources "$active_sources" \
    --argjson degraded_sources "$degraded_sources" \
    --argjson unavailable_sources "$unavailable_sources" \
    '{
      session_id: $session_id,
      probed_at: $probed_at,
      remote_status: $remote_status,
      active_sources: $active_sources,
      degraded_sources: $degraded_sources,
      unavailable_sources: $unavailable_sources
    }')

  printf '%s\n' "$sess" > "$(session_file)"

  # -- Output --
  if [ "$silent" -eq 1 ]; then
    return 0
  fi

  if [ "$json_out" -eq 1 ]; then
    jq -n --argjson sources "$manifest" --argjson session "$sess" \
      '{sources: $sources, session: $session}'
  else
    # Human-readable summary
    local active_count degraded_count unavail_count
    active_count=$(printf '%s' "$sess" | jq '.active_sources | length')
    degraded_count=$(printf '%s' "$sess" | jq '.degraded_sources | length')
    unavail_count=$(printf '%s' "$sess" | jq '.unavailable_sources | length')

    printf 'Knowledge sources: %d active, %d degraded, %d unavailable\n' \
      "$active_count" "$degraded_count" "$unavail_count"

    if [ "$active_count" -gt 0 ]; then
      local active_list
      active_list=$(printf '%s' "$sess" | jq -r '.active_sources[]' | tr '\n' ', ' | sed 's/,$//')
      printf '  Active:    %s\n' "$active_list"
    fi
    if [ "$degraded_count" -gt 0 ]; then
      local degraded_list
      degraded_list=$(printf '%s' "$sess" | jq -r '.degraded_sources[]' | tr '\n' ', ' | sed 's/,$//')
      printf '  Degraded:  %s\n' "$degraded_list"
    fi
    if [ "$unavail_count" -gt 0 ]; then
      local unavail_list
      unavail_list=$(printf '%s' "$sess" | jq -r '.unavailable_sources[]' | tr '\n' ', ' | sed 's/,$//')
      printf '  Unavail:   %s\n' "$unavail_list"
    fi

    printf 'Grounding mode: %s\n' "$grounding_mode"
    printf 'Strict air-gap: %s\n' "$([ "$strict_airgap" = "true" ] && echo "on" || echo "off")"
  fi
}

# -- status -------------------------------------------------------------------

do_status() {
  if [ ! -f "$SOURCES_FILE" ]; then
    # Auto-discover if manifest missing
    do_discover --silent
  fi

  local manifest sess
  manifest=$(cat "$SOURCES_FILE")
  local sf
  sf="$(session_file)"

  if [ ! -f "$sf" ]; then
    do_discover --silent
  fi
  sess=$(cat "$(session_file)")

  local active_count degraded_count unavail_count
  active_count=$(printf '%s' "$sess" | jq '.active_sources | length')
  degraded_count=$(printf '%s' "$sess" | jq '.degraded_sources | length')
  unavail_count=$(printf '%s' "$sess" | jq '.unavailable_sources | length')

  printf 'Knowledge sources: %d active, %d degraded, %d unavailable\n' \
    "$active_count" "$degraded_count" "$unavail_count"

  # Active details
  if [ "$active_count" -gt 0 ]; then
    printf '  Active:    '
    local first=1
    for src_id in $(printf '%s' "$sess" | jq -r '.active_sources[]'); do
      local stype extra=""
      stype=$(printf '%s' "$manifest" | jq -r ".sources.${src_id}.type // \"unknown\"")
      case "$stype" in
        wiki)
          local pc
          pc=$(printf '%s' "$manifest" | jq -r ".sources.${src_id}.page_count // 0")
          [ "$pc" != "0" ] && [ "$pc" != "null" ] && extra=" (${pc} pages)"
          ;;
        local_docs)
          local hpm
          hpm=$(printf '%s' "$manifest" | jq -r ".sources.${src_id}.has_project_md // false")
          [ "$hpm" = "true" ] && extra=" (PROJECT.md)"
          ;;
      esac
      [ "$first" -eq 1 ] && first=0 || printf ', '
      printf '%s%s' "$src_id" "$extra"
    done
    printf '\n'
  fi

  # Degraded details
  if [ "$degraded_count" -gt 0 ]; then
    printf '  Degraded:  '
    local first=1
    for src_id in $(printf '%s' "$sess" | jq -r '.degraded_sources[]'); do
      local err
      err=$(printf '%s' "$sess" | jq -r ".remote_status.${src_id}.error // \"unknown error\"")
      [ "$first" -eq 1 ] && first=0 || printf ', '
      printf '%s (%s)' "$src_id" "$err"
    done
    printf '\n'
  fi

  # Unavailable details
  if [ "$unavail_count" -gt 0 ]; then
    printf '  Unavail:   '
    local first=1
    for src_id in $(printf '%s' "$sess" | jq -r '.unavailable_sources[]'); do
      [ "$first" -eq 1 ] && first=0 || printf ', '
      printf '%s' "$src_id"
    done
    printf '\n'
  fi

  local gm sa
  gm=$(printf '%s' "$manifest" | jq -r '.grounding_mode')
  sa=$(printf '%s' "$manifest" | jq -r '.strict_airgap')
  printf 'Grounding mode: %s\n' "$gm"
  printf 'Strict air-gap: %s\n' "$([ "$sa" = "true" ] && echo "on" || echo "off")"
}

# -- get (thin jq wrapper) ---------------------------------------------------

do_get() {
  local path="${1:-}"
  [ -z "$path" ] && die "usage: discover.sh get <jq-path>"

  # Route to the right file based on path prefix
  case "$path" in
    session.*|active_sources*|degraded_sources*|unavailable_sources*|remote_status*)
      local sf
      sf="$(session_file)"
      if [ ! -f "$sf" ]; then
        do_discover --silent >/dev/null 2>&1
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
      if [ ! -f "$SOURCES_FILE" ]; then
        do_discover --silent >/dev/null 2>&1
      fi
      if [ ! -f "$SOURCES_FILE" ]; then
        die "sources manifest unavailable"
      fi
      jq -r ".$path" "$SOURCES_FILE"
      ;;
  esac
}

# -- main dispatcher ----------------------------------------------------------

cmd="${1:-discover}"
shift || true

case "$cmd" in
  discover) do_discover "$@" ;;
  status)   do_status "$@" ;;
  get)      do_get "$@" ;;
  *)        die "unknown command: $cmd. Usage: discover.sh {discover|status|get} [flags]" ;;
esac
