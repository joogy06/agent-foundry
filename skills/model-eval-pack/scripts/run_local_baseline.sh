#!/usr/bin/env bash
# Local-model baseline flow: one command per (model, hardware) setup; every run lands in the same
# CSVs and is compared against the earlier ones. Run ON the serving host, with the server started.
#
#   run_local_baseline.sh <profile> ["notes"] [extra local_bench.py args...]
#   e.g. run_local_baseline.sh 2gpu-q4kxl-256k "2x RTX 5060 Ti, UD-Q4_K_XL"
#
# BENCH_OUT  results directory (default ~/local-bench/results); keep it the same across runs so the
#            LiveCodeBench problem manifest, and so the problems, stay the same.
# BENCH_URL  server base URL (default http://127.0.0.1:8080/v1)
# BENCH_SUITES  default coding,longctx,parallel,lcb
set -euo pipefail
profile="${1:?usage: run_local_baseline.sh <profile> [notes] [extra args]}"; shift
notes="${1:-}"; [ $# -gt 0 ] && shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${BENCH_OUT:-$HOME/local-bench/results}"
url="${BENCH_URL:-http://127.0.0.1:8080/v1}"
health="$(curl -s -m 5 "${url%/v1}/health" || true)"
case "$health" in
  *'"loaded": true'*|*'"loaded":true'*) ;;
  *) echo "server at $url is not ready (health: ${health:-no answer}); start it first" >&2; exit 2 ;;
esac
mkdir -p "$out"
log="$out/run-$(date +%Y%m%dT%H%M%S)-$profile.log"
echo "profile=$profile out=$out log=$log"
python3 "$here/local_bench.py" --profile "$profile" --notes "$notes" --base-url "$url" --out "$out" \
  --suites "${BENCH_SUITES:-coding,longctx,parallel,lcb}" "$@" 2>&1 | tee "$log"
echo
python3 "$here/local_bench.py" --compare --out "$out"
