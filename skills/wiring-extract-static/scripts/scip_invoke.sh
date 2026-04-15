#!/usr/bin/env bash
# scip_invoke.sh — subprocess wrapper for SCIP language indexers.
#
# Usage:
#     scip_invoke.sh <language> <project_dir> <output_index_path> [timeout_seconds]
#
# Exit codes:
#     0   indexer ran and produced the index file
#     10  indexer not found on PATH (caller records status=skipped)
#     11  indexer timed out (caller records status=failed with "timeout")
#     12  indexer crashed (caller records status=failed with captured stderr)
#     13  bad invocation
#
# This wrapper never writes anywhere outside $output_index_path. It captures
# stderr on failure and writes it to "${output_index_path}.err" for the
# caller to include in the manifest gap/error list.

set -u

language="${1:-}"
project_dir="${2:-}"
output_path="${3:-}"
timeout_s="${4:-120}"

if [[ -z "$language" || -z "$project_dir" || -z "$output_path" ]]; then
    echo "usage: scip_invoke.sh <language> <project_dir> <output_index_path> [timeout_seconds]" >&2
    exit 13
fi

case "$language" in
    python)
        indexer="scip-python"
        args=(index --output "$output_path")
        ;;
    typescript)
        indexer="scip-typescript"
        args=(index --output "$output_path")
        ;;
    javascript)
        indexer="scip-typescript"
        args=(index --infer-tsconfig --output "$output_path")
        ;;
    *)
        echo "scip_invoke: unsupported language $language" >&2
        exit 13
        ;;
esac

if ! command -v "$indexer" >/dev/null 2>&1; then
    echo "scip_invoke: $indexer not installed" >&2
    exit 10
fi

mkdir -p "$(dirname "$output_path")"
err_log="${output_path}.err"

# timeout may not be available everywhere; fall back to a foreground run if so
if command -v timeout >/dev/null 2>&1; then
    timeout --preserve-status "${timeout_s}s" "$indexer" "${args[@]}" \
        --cwd "$project_dir" 2> "$err_log"
    rc=$?
    # timeout returns 124 on timeout
    if [[ $rc -eq 124 ]]; then
        echo "scip_invoke: $indexer timed out after ${timeout_s}s" >&2
        exit 11
    fi
else
    (cd "$project_dir" && "$indexer" "${args[@]}") 2> "$err_log"
    rc=$?
fi

if [[ $rc -ne 0 ]]; then
    echo "scip_invoke: $indexer exited with $rc" >&2
    exit 12
fi

# Success path: err_log is empty or irrelevant; keep for the caller to inspect if desired.
exit 0
