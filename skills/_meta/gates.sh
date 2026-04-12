#!/usr/bin/env bash
# gates.sh — bash fallback for gates.py.
#
# Purpose: in environments where Python + pyyaml are unavailable, provide
# identical gate semantics to gates.py so that bob can still enforce G1/G2/G3
# mechanically. Parity test (spec section 20 criterion 9 case 9) requires
# identical exit codes AND identical error message prefixes.
#
# Dependencies (hard): bash >= 4, yq (mikefarah v4), jq, sha256sum, openssl,
#                      awk, grep, tr.
#
# Exit codes (must match gates.py):
#     0 = pass
#     2 = fail (gate violation)
#     3 = environmental error (file missing, parse error, deps missing)
#
# Usage:
#     bash gates.sh G1 <design_dir> [--no-ledger-binding]
#     bash gates.sh G2 <contract-map-path> [--project-root <dir>]
#     bash gates.sh G3 <wp_id> <invoking_skill> [--project-root <dir>]
#
# Message format (bit-identical with gates.py for parity test):
#     Pass:  stdout "<GATE>_PASS: <message>\n", exit 0
#     Fail:  stderr "<GATE>_FAIL: <message>\n", exit 2
#     Env:   stderr "ENV_ERROR: <message>\n",   exit 3
#
# Provenance: spec section 8, spec section 20 criterion 9 case 9.

set -u  # do NOT use -e; we need to capture non-zero exits from helpers

# ---------------------------------------------------------------------------
# Output helpers — match gates.py exactly
# ---------------------------------------------------------------------------

fail() {
    # $1 = gate name (G1/G2/G3), $2 = message
    printf '%s_FAIL: %s\n' "$1" "$2" >&2
    exit 2
}

env_error() {
    printf 'ENV_ERROR: %s\n' "$1" >&2
    exit 3
}

ok() {
    # $1 = gate name, $2 = message
    printf '%s_PASS: %s\n' "$1" "$2"
    exit 0
}

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

for dep in yq jq sha256sum openssl awk grep tr; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        env_error "required tool not found: $dep"
    fi
done

# ---------------------------------------------------------------------------
# Constants — must match gates.py V1_SEMANTIC_TYPES and TECHNICAL_CLOSED_LIST
# ---------------------------------------------------------------------------

readonly SCHEMA_VERSION_SUPPORTED="1.0.0"

# 18 v1 semantic types (frozen list — MUST match gates.py V1_SEMANTIC_TYPES)
readonly V1_SEMANTIC_TYPES=(
    user_id session_token api_key
    email phone_e164 address_line country_iso2
    full_name first_name last_name date_of_birth
    iso_8601_datetime iso_8601_date unix_timestamp
    currency_amount currency_iso4217 iban
    url_http
)

# technical closed list (MUST match gates.py TECHNICAL_CLOSED_LIST)
readonly TECHNICAL_CLOSED_LIST=(
    id revision event_id _meta hash checksum
    version created_at updated_at deleted_at
    generation schema_version internal_ref
)

# kebab-case regex
readonly KEBAB_CASE_RE='^[a-z][a-z0-9]*(-[a-z0-9]+)*$'

in_list() {
    # $1 = needle, $2.. = haystack
    local needle="$1"; shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

# ---------------------------------------------------------------------------
# Canonical JSON — must match gates.py canonical_json() bit-for-bit
# ---------------------------------------------------------------------------
# gates.py uses: json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
# jq equivalent: --sort-keys + -c (compact) + default non-ascii-escaping is OFF (raw utf-8)

canonical_json() {
    # Reads JSON from stdin, prints canonical form on stdout
    jq -cS --unbuffered . 2>/dev/null
}

# ---------------------------------------------------------------------------
# Project-local semantic-type override loader
# ---------------------------------------------------------------------------

load_semantic_type_registry() {
    # $1 = project_root
    # Prints registered type names one per line on stdout.
    local root="$1"
    local override="${root}/.contract/semantic-types.yaml"
    for t in "${V1_SEMANTIC_TYPES[@]}"; do
        printf '%s\n' "$t"
    done
    if [[ -f "$override" ]]; then
        # Extract keys from semantic_types map
        local keys
        if ! keys=$(yq eval '.semantic_types | keys | .[]' "$override" 2>/dev/null); then
            env_error "failed to load project-local semantic types: $override"
        fi
        printf '%s\n' "$keys"
    fi
}

# ---------------------------------------------------------------------------
# Ledger reader — extract YAML frontmatter from integration-ledger.md
# ---------------------------------------------------------------------------

extract_ledger_frontmatter() {
    # $1 = ledger_path; prints YAML frontmatter on stdout
    local path="$1"
    if [[ ! -f "$path" ]]; then
        env_error "ledger not found at $path"
    fi
    local first
    first=$(head -n 1 "$path" 2>/dev/null || true)
    if [[ "$first" != "---" ]]; then
        env_error "ledger $path missing YAML frontmatter"
    fi
    # Extract everything between the first '---' and the next '---'
    awk 'NR==1{next} /^---[[:space:]]*$/{exit} {print}' "$path"
}

# ---------------------------------------------------------------------------
# G1 — contract map exists, signed, bound to ledger
# ---------------------------------------------------------------------------

check_G1() {
    # $1 = design_dir, $2 = expect_ledger_binding ("1" or "0")
    local design_dir="$1"
    local expect_binding="$2"

    local map_path="${design_dir}/progress/contract-map.yaml"
    local sig_path="${design_dir}/progress/contract-map.yaml.sig"
    local key_path="${design_dir}/.forge/session.key"
    local session_id_path="${design_dir}/.forge/session-id"

    # 1. File existence
    [[ -f "$map_path" ]]         || fail "G1" "contract-map.yaml missing at $map_path"
    [[ -f "$sig_path" ]]         || fail "G1" "contract-map.yaml.sig missing at $sig_path"
    [[ -f "$key_path" ]]         || fail "G1" "session.key missing at $key_path"
    [[ -f "$session_id_path" ]]  || fail "G1" "session-id missing at $session_id_path"

    # 2. Key permissions: 0600 required. `stat -c %a` gives octal mode.
    local mode
    mode=$(stat -c '%a' "$key_path" 2>/dev/null) || env_error "cannot stat $key_path"
    # Normalize to 3 digits
    mode="${mode: -3}"
    # Other/group bits must be zero
    local oth="${mode:1}"
    if [[ "$oth" != "00" ]]; then
        fail "G1" "session.key permissions unsafe (0${mode}), must be 0600"
    fi

    # 3. Compute map hash
    local map_hash
    map_hash=$(sha256sum "$map_path" | awk '{print $1}')

    # 4. Read current session id
    local current_session_id
    current_session_id=$(tr -d '[:space:]' < "$session_id_path")

    # 5. Parse revision from YAML
    local map_revision
    map_revision=$(yq eval '.revision' "$map_path" 2>/dev/null) || fail "G1" "contract-map.yaml unparseable"
    if [[ "$map_revision" == "null" ]] || ! [[ "$map_revision" =~ ^[0-9]+$ ]] || (( map_revision < 1 )); then
        fail "G1" "map revision missing or invalid: $map_revision"
    fi

    # 6. Parse signature file as JSON
    local payload_json provided_sig
    if ! jq empty "$sig_path" 2>/dev/null; then
        fail "G1" "signature file is not valid JSON"
    fi
    payload_json=$(jq -c '.payload' "$sig_path" 2>/dev/null)
    provided_sig=$(jq -r '.signature' "$sig_path" 2>/dev/null)
    if [[ -z "$payload_json" || "$payload_json" == "null" || -z "$provided_sig" || "$provided_sig" == "null" ]]; then
        fail "G1" "signature file missing 'payload' or 'signature'"
    fi

    # 7. Payload self-consistency
    local p_hash p_rev p_sid
    p_hash=$(printf '%s' "$payload_json" | jq -r '.map_hash')
    p_rev=$(printf '%s' "$payload_json" | jq -r '.map_revision')
    p_sid=$(printf '%s' "$payload_json" | jq -r '.forge_session_id')

    [[ "$p_hash" == "$map_hash" ]] || fail "G1" "payload map_hash does not match current YAML — tamper evident"
    [[ "$p_rev"  == "$map_revision" ]] || fail "G1" "payload map_revision does not match current YAML"
    [[ "$p_sid"  == "$current_session_id" ]] || fail "G1" "session id mismatch — signed map is from a different forge session (replay)"

    # 8. HMAC verification — must match gates.py canonical_json output bit-for-bit.
    #
    # gates.py computes HMAC over:
    #   hmac.new(key=key_path.read_bytes(), msg=canonical_json(payload).encode('utf-8'))
    # where key_path.read_bytes() INCLUDES any trailing newline from `openssl rand -hex 32 > file`.
    #
    # Shell command substitution `$(cat file)` strips trailing newlines. That makes the shell
    # key shorter than the Python key by one byte, and the HMAC diverges.
    #
    # Fix: use -macopt key:... with a file-read pattern that preserves trailing newlines.
    # openssl's `-hmac` argument takes a raw string key; we pipe the exact file bytes through
    # openssl using -macopt and a temp file that openssl can read directly.
    local canonical expected_sig
    canonical=$(printf '%s' "$payload_json" | canonical_json)
    if [[ -z "$canonical" ]]; then
        env_error "failed to canonicalize payload"
    fi

    # Use Python as the HMAC oracle when available — it reads the key file as bytes
    # exactly like gates.py does, guaranteeing bit-for-bit parity. Bash fallback below.
    if command -v python3 >/dev/null 2>&1; then
        expected_sig=$(python3 -c "
import hmac, hashlib, sys
key = open('$key_path', 'rb').read()
msg = sys.stdin.buffer.read()
print(hmac.new(key, msg, hashlib.sha256).hexdigest())
" < <(printf '%s' "$canonical"))
    else
        # Pure-bash fallback — use openssl dgst -hmac with the key file content.
        # xxd round-trip preserves trailing newline.
        local key_hex
        key_hex=$(xxd -p -c 0 "$key_path")
        expected_sig=$(printf '%s' "$canonical" | \
            openssl dgst -sha256 -mac HMAC -macopt "hexkey:$key_hex" -binary 2>/dev/null | \
            xxd -p -c 256 | tr -d '\n')
    fi

    if [[ -z "$expected_sig" ]]; then
        env_error "HMAC computation failed"
    fi
    if [[ "$expected_sig" != "$provided_sig" ]]; then
        fail "G1" "signature mismatch — tamper evident"
    fi

    # 9. Ledger binding (CB2)
    if [[ "$expect_binding" == "1" ]]; then
        local ledger_path="${design_dir}/progress/integration-ledger.md"
        if [[ ! -f "$ledger_path" ]]; then
            fail "G1" "ledger not found at $ledger_path (binding required)"
        fi
        local fm
        fm=$(extract_ledger_frontmatter "$ledger_path")
        local led_hash led_rev
        led_hash=$(printf '%s\n' "$fm" | yq eval '.contract_map_hash' - 2>/dev/null)
        led_rev=$(printf '%s\n' "$fm" | yq eval '.contract_map_revision' - 2>/dev/null)
        if [[ "$led_hash" != "$map_hash" ]]; then
            local led_short="${led_hash:0:12}"
            local map_short="${map_hash:0:12}"
            [[ "$led_hash" == "null" ]] && led_short="None"
            fail "G1" "ledger-pinned hash (${led_short}) does not match current map (${map_short}) — stale map replay"
        fi
        if [[ "$led_rev" != "$map_revision" ]]; then
            fail "G1" "ledger-pinned revision (${led_rev}) does not match current map (${map_revision}) — rollback detected"
        fi
    fi

    ok "G1" "contract map verified at ${design_dir} (binding=$([[ $expect_binding == 1 ]] && echo True || echo False))"
}

# ---------------------------------------------------------------------------
# G2 — schema validation V1-V15
# ---------------------------------------------------------------------------
#
# For parity with gates.py, we implement V1-V15 using yq expressions against
# the contract-map.yaml. On first failure, fail(G2, ...) exits 2 with the
# same error-message prefix that gates.py uses.

check_G2() {
    # $1 = map_path, $2 = project_root
    local map_path="$1"
    local project_root="$2"

    [[ -f "$map_path" ]] || fail "G2" "contract map not found at $map_path"
    # Validate parseable
    if ! yq eval '.' "$map_path" >/dev/null 2>&1; then
        fail "G2" "contract-map.yaml unparseable"
    fi

    local top_kind
    top_kind=$(yq eval 'type' "$map_path" 2>/dev/null)
    [[ "$top_kind" == "!!map" || "$top_kind" == "map" || "$top_kind" == "object" ]] || \
        fail "G2" "contract-map.yaml is not a mapping"

    # components must be non-empty list
    local comp_count
    comp_count=$(yq eval '.components | length' "$map_path" 2>/dev/null)
    [[ "$comp_count" =~ ^[0-9]+$ ]] || fail "G2" "components must be a non-empty list"
    (( comp_count > 0 )) || fail "G2" "components must be a non-empty list"

    # Load registry (v1 + project-local override). Store as newline-separated.
    local registry
    registry=$(load_semantic_type_registry "$project_root")

    # V1: schema_version present and supported
    local sv
    sv=$(yq eval '.schema_version' "$map_path" 2>/dev/null)
    [[ "$sv" == "null" || -z "$sv" ]] && fail "G2" "V1: schema_version missing"
    [[ "$sv" == "$SCHEMA_VERSION_SUPPORTED" ]] || fail "G2" "V1: unsupported schema_version '${sv}' (supported: ${SCHEMA_VERSION_SUPPORTED})"

    # V2: revision positive integer
    local rev
    rev=$(yq eval '.revision' "$map_path" 2>/dev/null)
    if [[ "$rev" == "null" ]] || ! [[ "$rev" =~ ^[0-9]+$ ]] || (( rev < 1 )); then
        fail "G2" "V2: revision must be a positive integer, got ${rev}"
    fi

    # V3: unique kebab-case component ids
    local ids i id
    local seen=""
    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path" 2>/dev/null)
        if [[ "$id" == "null" || -z "$id" ]]; then
            fail "G2" "V3: component missing id at index $i"
        fi
        if [[ ! "$id" =~ $KEBAB_CASE_RE ]]; then
            fail "G2" "V3: component id '${id}' not kebab-case"
        fi
        if [[ "$seen" == *"|${id}|"* ]]; then
            fail "G2" "V3: duplicate component id '${id}'"
        fi
        seen="${seen}|${id}|"
    done

    # V4: every component has all required top-level fields
    local required_fields=(id purpose owner_wp source_paths test_paths fixtures_path inputs outputs callers callees success_criteria test_scenarios)
    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path" 2>/dev/null)
        local missing=""
        for field in "${required_fields[@]}"; do
            local present
            present=$(yq eval ".components[$i] | has(\"$field\")" "$map_path" 2>/dev/null)
            if [[ "$present" != "true" ]]; then
                missing="${missing} ${field}"
            fi
        done
        if [[ -n "$missing" ]]; then
            local sorted
            sorted=$(printf '%s\n' $missing | sort | tr '\n' ',' | sed 's/,$//')
            fail "G2" "V4: component '${id}' missing required fields: [${sorted}]"
        fi
    done

    # V5+V6: callers/callees resolve and are bidirectional
    # Build id list once
    local id_list
    id_list=$(yq eval '.components[].id' "$map_path")
    _has_id() {
        local target="$1"
        printf '%s\n' "$id_list" | grep -Fxq "$target"
    }

    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path")
        # callees
        local callees_count
        callees_count=$(yq eval ".components[$i].callees | length // 0" "$map_path")
        for (( j=0; j<callees_count; j++ )); do
            local callee
            callee=$(yq eval ".components[$i].callees[$j]" "$map_path")
            if ! _has_id "$callee"; then
                fail "G2" "V5: component '${id}' declares callee '${callee}' which is not a component"
            fi
            # Check callee lists id in its callers
            local callee_index
            callee_index=$(yq eval ".components | map(.id) | to_entries | .[] | select(.value == \"$callee\") | .key" "$map_path")
            local callers_contains
            callers_contains=$(yq eval ".components[$callee_index].callers // [] | contains([\"$id\"])" "$map_path")
            if [[ "$callers_contains" != "true" ]]; then
                fail "G2" "V6: component '${id}' -> '${callee}' not bidirectional (callee missing caller)"
            fi
        done
        # callers
        local callers_count
        callers_count=$(yq eval ".components[$i].callers | length // 0" "$map_path")
        for (( j=0; j<callers_count; j++ )); do
            local caller
            caller=$(yq eval ".components[$i].callers[$j]" "$map_path")
            if ! _has_id "$caller"; then
                fail "G2" "V5: component '${id}' declares caller '${caller}' which is not a component"
            fi
            local caller_index
            caller_index=$(yq eval ".components | map(.id) | to_entries | .[] | select(.value == \"$caller\") | .key" "$map_path")
            local callees_contains
            callees_contains=$(yq eval ".components[$caller_index].callees // [] | contains([\"$id\"])" "$map_path")
            if [[ "$callees_contains" != "true" ]]; then
                fail "G2" "V6: component '${id}' <- '${caller}' not bidirectional (caller missing callee)"
            fi
        done
    done

    # V7: every $ref resolves to types.<name>
    local type_names
    type_names=$(yq eval '.types | keys | .[]' "$map_path" 2>/dev/null || printf '')
    local refs
    refs=$(yq eval '.. | select(has("$ref") | .) | ."$ref"' "$map_path" 2>/dev/null || printf '')
    if [[ -n "$refs" ]]; then
        while IFS= read -r ref; do
            [[ -z "$ref" ]] && continue
            if ! printf '%s\n' "$type_names" | grep -Fxq "$ref"; then
                fail "G2" "V7: \$ref '${ref}' does not resolve to a declared type"
            fi
        done <<< "$refs"
    fi

    # V8: fixture_refs point to a declared input name (strip [index])
    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path")
        local input_names
        input_names=$(yq eval ".components[$i].inputs[].name" "$map_path" 2>/dev/null || printf '')
        local ts_count
        ts_count=$(yq eval ".components[$i].test_scenarios | length // 0" "$map_path")
        for (( t=0; t<ts_count; t++ )); do
            local ts_id
            ts_id=$(yq eval ".components[$i].test_scenarios[$t].id" "$map_path")
            local fr_count
            fr_count=$(yq eval ".components[$i].test_scenarios[$t].fixture_refs | length // 0" "$map_path")
            for (( f=0; f<fr_count; f++ )); do
                local fr
                fr=$(yq eval ".components[$i].test_scenarios[$t].fixture_refs[$f]" "$map_path")
                local base="${fr%%\[*}"
                if ! printf '%s\n' "$input_names" | grep -Fxq "$base"; then
                    fail "G2" "V8: component '${id}' test_scenario '${ts_id}' fixture_ref '${fr}' does not point to a declared input"
                fi
            done
        done
    done

    # V9+V10: flow entry + terminal markers
    local has_entry has_terminal
    has_entry=$(yq eval '[.components[] | select(.flow_entry_point == true)] | length' "$map_path")
    has_terminal=$(yq eval '[.components[] | select(.flow_terminal == true)] | length' "$map_path")
    (( has_entry >= 1 ))    || fail "G2" "V9: no component has flow_entry_point: true"
    (( has_terminal >= 1 )) || fail "G2" "V10: no component has flow_terminal: true"

    # V11: acyclic OR declared cycle_group
    # Implement minimal cycle detection using awk DFS on the callee graph.
    # First emit edges "src callee" and nodes + cycle_groups.
    local graph_file
    graph_file=$(mktemp /tmp/gates-sh-graph-XXXXXX)
    local group_file
    group_file=$(mktemp /tmp/gates-sh-groups-XXXXXX)
    # shellcheck disable=SC2064
    trap "rm -f '$graph_file' '$group_file'" EXIT

    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path")
        local cg
        cg=$(yq eval ".components[$i].cycle_group // \"\"" "$map_path")
        printf '%s\t%s\n' "$id" "$cg" >> "$group_file"
        local callees_count_v11
        callees_count_v11=$(yq eval ".components[$i].callees | length // 0" "$map_path")
        for (( j=0; j<callees_count_v11; j++ )); do
            local callee_v11
            callee_v11=$(yq eval ".components[$i].callees[$j]" "$map_path")
            printf '%s\t%s\n' "$id" "$callee_v11" >> "$graph_file"
        done
    done

    # Run cycle detection via embedded python if available, else via awk.
    # We prefer python3 because awk recursion portability is risky and cycle
    # detection must be correct. Python is expected in v1; if genuinely absent,
    # the environment hits the env_error above.
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$graph_file" "$group_file" <<'PYEOF' || exit 2
import sys

graph_file, group_file = sys.argv[1], sys.argv[2]
graph = {}
groups = {}
with open(group_file) as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2:
            groups[parts[0]] = parts[1]
            graph.setdefault(parts[0], [])
with open(graph_file) as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2:
            graph.setdefault(parts[0], []).append(parts[1])

# Tarjan SCC
index_counter = [0]
stack = []
on_stack = {}
indices = {}
lowlinks = {}
sccs = []

def strong(v):
    indices[v] = index_counter[0]
    lowlinks[v] = index_counter[0]
    index_counter[0] += 1
    stack.append(v)
    on_stack[v] = True
    for w in graph.get(v, []):
        if w not in indices:
            strong(w)
            lowlinks[v] = min(lowlinks[v], lowlinks[w])
        elif on_stack.get(w, False):
            lowlinks[v] = min(lowlinks[v], indices[w])
    if lowlinks[v] == indices[v]:
        comp = []
        while True:
            w = stack.pop()
            on_stack[w] = False
            comp.append(w)
            if w == v:
                break
        sccs.append(comp)

for v in list(graph.keys()):
    if v not in indices:
        strong(v)

def emit_fail(msg):
    sys.stderr.write(f"G2_FAIL: {msg}\n")
    sys.exit(2)

for scc in sccs:
    if len(scc) <= 1:
        v = scc[0]
        if v in graph.get(v, []):
            if not groups.get(v):
                emit_fail(f"V11: self-loop on '{v}' not declared via cycle_group")
        continue
    g = {groups.get(v) for v in scc}
    if "" in g or None in g or len(g) > 1:
        emit_fail(f"V11: cycle detected among {sorted(scc)} — must all declare the same cycle_group")
PYEOF
    else
        env_error "python3 required for G2 V11 cycle detection in gates.sh"
    fi

    rm -f "$graph_file" "$group_file"
    trap - EXIT

    # V12: every component has at least one test_scenario
    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path")
        local ts_len
        ts_len=$(yq eval ".components[$i].test_scenarios | length // 0" "$map_path")
        (( ts_len > 0 )) || fail "G2" "V12: component '${id}' has no test_scenarios"
    done

    # V13: every input needs semantic_type (from registry), or technical (closed list), or kind: opaque
    for (( i=0; i<comp_count; i++ )); do
        id=$(yq eval ".components[$i].id" "$map_path")
        local in_count
        in_count=$(yq eval ".components[$i].inputs | length // 0" "$map_path")
        for (( k=0; k<in_count; k++ )); do
            local kind iname st tech
            iname=$(yq eval ".components[$i].inputs[$k].name" "$map_path")
            kind=$(yq eval ".components[$i].inputs[$k].kind" "$map_path")
            if [[ "$kind" == "opaque" ]]; then
                local orsn osrc
                orsn=$(yq eval ".components[$i].inputs[$k].opaque_reason" "$map_path")
                osrc=$(yq eval ".components[$i].inputs[$k].opaque_fixture_source" "$map_path")
                [[ "$orsn" == "null" || -z "$orsn" ]] && fail "G2" "V13: opaque input '${iname}' in '${id}' missing opaque_reason"
                [[ "$osrc" == "null" || -z "$osrc" ]] && fail "G2" "V13: opaque input '${iname}' in '${id}' missing opaque_fixture_source"
                continue
            fi
            st=$(yq eval ".components[$i].inputs[$k].semantic_type" "$map_path")
            if [[ "$st" == "null" ]]; then
                fail "G2" "V13: input '${iname}' in '${id}' missing semantic_type (use registry value, technical, or kind: opaque)"
            fi
            if [[ "$st" == "technical" ]]; then
                tech=$(yq eval ".components[$i].inputs[$k].technical" "$map_path")
                if ! in_list "$tech" "${TECHNICAL_CLOSED_LIST[@]}"; then
                    local closed_sorted
                    closed_sorted=$(printf '%s\n' "${TECHNICAL_CLOSED_LIST[@]}" | sort | tr '\n' ',' | sed 's/,$//')
                    fail "G2" "V13: input '${iname}' in '${id}' declares technical but technical='${tech}' is not in the closed list ([${closed_sorted}])"
                fi
                continue
            fi
            if ! printf '%s\n' "$registry" | grep -Fxq "$st"; then
                fail "G2" "V13: input '${iname}' in '${id}' has unknown semantic_type '${st}' (not in v1 registry or project-local override)"
            fi
        done
    done

    # V14+V15: flows
    local flow_count
    flow_count=$(yq eval '.flows | length // 0' "$map_path")
    for (( f=0; f<flow_count; f++ )); do
        local fid
        fid=$(yq eval ".flows[$f].id" "$map_path")
        local path_len
        path_len=$(yq eval ".flows[$f].path | length // 0" "$map_path")
        for (( p=0; p<path_len; p++ )); do
            local elem
            elem=$(yq eval ".flows[$f].path[$p]" "$map_path")
            if ! _has_id "$elem"; then
                fail "G2" "V14: flow '${fid}' path element '${elem}' not a component"
            fi
        done
    done
    local max_flows
    max_flows=$(yq eval '.flow_budget.max_flows' "$map_path" 2>/dev/null)
    if [[ "$max_flows" != "null" && "$max_flows" =~ ^[0-9]+$ ]]; then
        if (( flow_count > max_flows )); then
            fail "G2" "V15: total flows (${flow_count}) exceed budget (${max_flows})"
        fi
    fi

    ok "G2" "schema validation passed for $map_path"
}

# ---------------------------------------------------------------------------
# G3 — claim verification (delegates to python claims.py for correctness)
# ---------------------------------------------------------------------------

check_G3() {
    # $1 = wp_id, $2 = invoking_skill, $3 = project_root
    local wp_id="$1"
    local invoking_skill="$2"
    local project_root="$3"

    local claims_dir="${project_root}/.ledger/claims"
    if [[ ! -d "$claims_dir" ]]; then
        fail "G3" "no claims directory at ${claims_dir} (bob has not issued claims)"
    fi

    local ledger_path="${project_root}/progress/integration-ledger.md"
    if [[ ! -f "$ledger_path" ]]; then
        fail "G3" "ledger not found at ${ledger_path}"
    fi

    # Enumerate active claim files and look for (wp, skill) match using yq.
    # We scan every *.claim.yaml and select matching, non-expired, non-stale, non-revoked.
    local now_epoch
    now_epoch=$(date -u +%s)
    local match_count=0
    local match_uuid=""
    shopt -s nullglob
    for f in "${claims_dir}"/*.claim.yaml; do
        local c_wp c_skill c_lease_until c_stale c_revoked
        c_wp=$(yq eval '.wp' "$f" 2>/dev/null)
        c_skill=$(yq eval '.skill' "$f" 2>/dev/null)
        [[ "$c_wp" == "$wp_id" && "$c_skill" == "$invoking_skill" ]] || continue
        c_lease_until=$(yq eval '.lease_until' "$f" 2>/dev/null)
        c_stale=$(yq eval '.stale' "$f" 2>/dev/null)
        c_revoked=$(yq eval '.revoked' "$f" 2>/dev/null)
        [[ "$c_stale" == "true" ]] && continue
        [[ "$c_revoked" == "true" ]] && continue
        # Parse ISO8601 timestamp
        local lease_epoch
        lease_epoch=$(date -u -d "$c_lease_until" +%s 2>/dev/null) || continue
        (( now_epoch > lease_epoch )) && continue
        match_count=$(( match_count + 1 ))
        match_uuid=$(yq eval '.claim_uuid' "$f" 2>/dev/null)
    done
    shopt -u nullglob

    if (( match_count == 0 )); then
        fail "G3" "no active claim for WP='${wp_id}' skill='${invoking_skill}'"
    fi
    if (( match_count > 1 )); then
        fail "G3" "multiple active claims for WP='${wp_id}' (concurrency violation)"
    fi

    ok "G3" "claim verified for WP=${wp_id} skill=${invoking_skill}"
}

# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

main() {
    if (( $# < 1 )); then
        env_error "usage: gates.sh G1|G2|G3 ..."
    fi
    local gate="$1"; shift
    local expect_binding="1"
    local project_root=""
    local positional=()
    while (( $# > 0 )); do
        case "$1" in
            --no-ledger-binding)
                expect_binding="0"; shift ;;
            --project-root)
                [[ -n "${2:-}" ]] || env_error "--project-root requires a value"
                project_root="$2"; shift 2 ;;
            *)
                positional+=("$1"); shift ;;
        esac
    done

    case "$gate" in
        G1)
            (( ${#positional[@]} >= 1 )) || env_error "G1 requires <design_dir>"
            local design_dir
            design_dir=$(readlink -f "${positional[0]}")
            check_G1 "$design_dir" "$expect_binding"
            ;;
        G2)
            (( ${#positional[@]} >= 1 )) || env_error "G2 requires <contract-map-path>"
            local map_path
            map_path=$(readlink -f "${positional[0]}")
            if [[ -z "$project_root" ]]; then
                # Mirror gates.py default: map_path.parent.parent
                project_root=$(dirname "$(dirname "$map_path")")
            fi
            project_root=$(readlink -f "$project_root")
            check_G2 "$map_path" "$project_root"
            ;;
        G3)
            (( ${#positional[@]} >= 2 )) || env_error "G3 requires <wp_id> <invoking_skill>"
            [[ -z "$project_root" ]] && project_root="$(pwd)"
            project_root=$(readlink -f "$project_root")
            check_G3 "${positional[0]}" "${positional[1]}" "$project_root"
            ;;
        *)
            env_error "unknown gate: $gate"
            ;;
    esac
}

main "$@"
