#!/usr/bin/env bash
# secrets-scan.sh — Pre-push real-secrets scanner.
#
# Scans a tree for high-confidence secret patterns and prints findings.
# CRITICAL/HIGH hits cause exit 1 (blocks pre-push hooks).
# MEDIUM/LOW hits print as advisory but exit 0 (skill content is
# largely tutorial-style and contains many doc-example hostnames,
# emails, IPs; those should not block routine pushes).
#
# Categories:
#   CRITICAL  live API keys, PEM private-key headers, AWS creds, JWTs
#   HIGH      inline password/token assignments with non-placeholder values
#   MEDIUM    real-looking emails, internal hostnames        (advisory)
#   LOW       non-RFC1918 IPv4 addresses                     (advisory)
#
# Built-in allowlist covers:
#   - detector docs in publish-to-github + this script itself
#   - tutorial password placeholders (changeme, Welcome1, keystorePass, etc.)
#   - code idioms (os.environ.get, authService.getAccessToken, token_resp.json)
#   - example domains (example.com, contoso.com, acme.*, *.noreply.github.com)
#   - git@github.com SSH URL (not an email)
#   - Docker convention (host.docker.internal)
#   - mDNS / file-path .local matches
#   - well-known public DNS (Cloudflare 1.1.1.1, Google 8.8.8.8, Quad9 9.9.9.9)
#   - RFC5737 documentation IPv4 ranges
#   - X.509 OIDs misread as IPs
#
# Usage:
#   bash scripts/secrets-scan.sh                  # scan $PWD
#   bash scripts/secrets-scan.sh /path/to/repo    # scan specific tree
#   bash scripts/secrets-scan.sh --quiet          # silent unless findings
#   bash scripts/secrets-scan.sh --verbose        # print all hits, not just heads
#   bash scripts/secrets-scan.sh --strict         # MEDIUM/LOW also block
#
# Exit codes:
#   0 — clean OR only MEDIUM/LOW (advisory) hits in default mode
#   1 — CRITICAL or HIGH hit found (review required)
#   2 — script error (bad args, missing dir, etc.)

set -uo pipefail

# ----- Arg parsing --------------------------------------------------------

QUIET=0
VERBOSE=0
STRICT=0
ROOT=""
for arg in "$@"; do
    case "$arg" in
        --quiet|-q) QUIET=1 ;;
        --verbose|-v) VERBOSE=1 ;;
        --strict) STRICT=1 ;;
        --help|-h)
            sed -n '2,40p' "$0"
            exit 0 ;;
        -*)
            echo "ERROR: unknown flag: $arg" >&2
            exit 2 ;;
        *) ROOT="$arg" ;;
    esac
done
ROOT="${ROOT:-$PWD}"

if [[ ! -d "$ROOT" ]]; then
    echo "ERROR: $ROOT is not a directory" >&2
    exit 2
fi

cd "$ROOT" || exit 2

# Get absolute path to this script so we can exclude it (it contains the
# patterns it greps for).
SELF="$(realpath "$0" 2>/dev/null || readlink -f "$0" 2>/dev/null || echo "$0")"

# ----- File-type filter (passed to every grep) ----------------------------

INCLUDES=(
    --include='*.md' --include='*.py' --include='*.sh' --include='*.bash'
    --include='*.json' --include='*.yaml' --include='*.yml' --include='*.toml'
    --include='*.ini' --include='*.cfg' --include='*.conf'
    --include='*.ps1' --include='*.cmd' --include='*.bat'
    --include='*.js' --include='*.ts' --include='*.tsx' --include='*.jsx'
    --include='*.mjs' --include='*.cjs'
    --include='*.env*' --include='*.example' --include='*.template'
)
EXCLUDES_DIR=(
    --exclude-dir='.git' --exclude-dir='node_modules'
    --exclude-dir='__pycache__' --exclude-dir='.pytest_cache'
    --exclude-dir='dist' --exclude-dir='build' --exclude-dir='.venv'
    --exclude-dir='venv' --exclude-dir='.env.d'
)

# Skills directories whose SKILL.md / references are themselves the
# detector documentation (they contain pattern strings as content).
# tests/lineage-extract-static/unit/test_redact.py: a redaction unit test must contain secret-SHAPED literals to prove the redactor removes them; same category as the scanner's own source
DETECTOR_DOCS_RE='(skills/publish-to-github|docs/plans/_review|scripts/secrets-scan\.sh|\.git/hooks/pre-push|tests/lineage-extract-static/unit/test_redact\.py|tests/secrets-scan/|lineage-extract-static/scripts/redact\.py)'

# ----- Findings trackers --------------------------------------------------

CRITICAL_HIT=0
HIGH_HIT=0
MEDIUM_HIT=0
LOW_HIT=0
TOTAL_HITS=0

report() {
    # $1 = severity, $2 = category, $3 = hits text
    local sev="$1" cat="$2" hits="$3"
    [[ -z "$hits" ]] && return 0
    local count
    count=$(printf '%s\n' "$hits" | wc -l)
    TOTAL_HITS=$((TOTAL_HITS + count))
    case "$sev" in
        CRITICAL) CRITICAL_HIT=$((CRITICAL_HIT + count)) ;;
        HIGH)     HIGH_HIT=$((HIGH_HIT + count)) ;;
        MEDIUM)   MEDIUM_HIT=$((MEDIUM_HIT + count)) ;;
        LOW)      LOW_HIT=$((LOW_HIT + count)) ;;
    esac
    if [[ $QUIET -eq 0 ]]; then
        echo ""
        echo "[$sev] $cat ($count hit(s))"
        echo "$hits" | { if [[ $VERBOSE -eq 1 ]]; then cat; else head -10; fi; }
        if [[ $VERBOSE -eq 0 && $count -gt 10 ]]; then
            echo "  ...(+$((count - 10)) more — pass --verbose to see all)"
        fi
    fi
}

qgrep() { grep "$@" 2>/dev/null || true; }

filter_detector_docs() {
    qgrep -vE "$DETECTOR_DOCS_RE"
}

# --- content-only allowlist (S074, #210) --------------------------------------
# grep emits `./path:12:content`, so `grep -vE` against that stream matches the PATH
# as well as the content. Two consequences, both verified rather than reasoned about:
#
#   1. FALSE NEGATIVE (the security hole): a real credential in a file under tests/
#      satisfied an allowlist rule meant for the word "test" appearing in code, and was
#      silently dropped. One secret in src/settings.py and tests/settings.py -> bash
#      reported 1 hit, secrets-scan.py reported 2. The pre-push hook runs THIS scanner.
#   2. INERT ANCHORS: every ^-anchored allowlist arm (`^\s*#`, `^\s*//`) could never
#      match, because the line starts with "./path:12:" and not with whitespace. A
#      commented-out credential was reported by bash and correctly exempted by python.
#
# exclude_content strips the `path:line:` prefix, applies the allowlist to the content
# alone, and re-emits the ORIGINAL line so reporting is unchanged. This is what the
# file's own "MUST stay in lockstep with secrets-scan.py" comment always intended.
exclude_content() {
    local pat="$1" line content
    while IFS= read -r line; do
        content=${line#*:}       # drop "./path:"
        content=${content#*:}    # drop "12:"
        printf '%s' "$content" | grep -qE "$pat" || printf '%s\n' "$line"
    done
}

# ===========================================================================
# CRITICAL
# ===========================================================================

# --- Live API keys ---
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "(sk-[a-zA-Z0-9]{20}|sk-(proj|svcacct|ant|live|test)-[a-zA-Z0-9_-]{20}|ghp_[a-zA-Z0-9]{20}|gho_[a-zA-Z0-9]{20}|ghs_[a-zA-Z0-9]{20}|ghu_[a-zA-Z0-9]{20}|github_pat_[a-zA-Z0-9_]{20}|xox[abprs]-[a-zA-Z0-9-]{20}|AIza[A-Za-z0-9_-]{30}|sk_live_[a-zA-Z0-9]{20}|pk_live_[a-zA-Z0-9]{20}|rk_live_[a-zA-Z0-9]{20}|sk_test_[a-zA-Z0-9]{20,}|whsec_[a-zA-Z0-9]{20}|nrak-[a-zA-Z0-9]{20}|hf_[a-zA-Z0-9]{20})" . \
    | filter_detector_docs \
    | exclude_content "(<|>|example|placeholder|YOUR_|YOURKEY|EXAMPLE|REDACTED|XXX|\.\.\.|fake|TEST_|DUMMY|sample|abcdef|012345|deadbeef)" )
report CRITICAL "live API key shapes" "$hits"

# --- PEM private-key headers (5-dash framing at column 0) ---
hits=$(qgrep -rln "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    -E "^-----BEGIN (RSA|OPENSSH|EC|PGP|DSA|ENCRYPTED|ED25519) PRIVATE KEY( BLOCK)?-----" . \
    | filter_detector_docs )
report CRITICAL "PEM private-key headers" "$hits"

# --- AWS credentials ---
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "(\bAKIA[0-9A-Z]{16}\b|aws_secret_access_key\s*=\s*[\"']?[A-Za-z0-9/+=]{30,}[\"']?)" . \
    | filter_detector_docs \
    | exclude_content "(example|placeholder|YOUR_|REDACTED|XXX|AKIAEXAMPLE|AKIAIOSFODNN7|AKIA[X]{16})" )
report CRITICAL "AWS credentials" "$hits"

# --- JWTs (3-segment eyJ...) ---
hits=$(qgrep -rEon "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "\beyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\b" . \
    | filter_detector_docs )
report CRITICAL "JWT shapes" "$hits"

# --- WooCommerce REST consumer key/secret ---
# PORTED FROM THE PYTHON SCANNER 2026-07-30 (#239). It had existed only there
# since 2026-07-25, and pre-commit runs python while PRE-PUSH RUNS THIS FILE —
# so the rule did not run at push time in any repo on this host. A credential
# committed with --no-verify, or committed before the rule was written, reached
# a remote through a gate that reported PASS.
#
# Bitterly apt: the python rule's own comment records that it was added after
# the same consumer key turned up in two repos having "sailed through every
# scan". On this arm it still was.
#
# ck_/cs_ are 40-hex WooCommerce REST credentials. Pattern and allowlist are
# byte-for-byte the python ones; test_scanner_parity.py asserts the rule-name
# sets match, because a corpus comparison cannot see a rule neither side runs.
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "\b(ck|cs)_[0-9a-fA-F]{32,}\b" . \
    | filter_detector_docs \
    | exclude_content "(example|placeholder|YOUR_|REDACTED|XXX|sample|0{32}|x{32}|f{32})" )
report CRITICAL "WooCommerce REST consumer key/secret" "$hits"

# --- PostgreSQL password exposure ---
# Ported alongside the WooCommerce rule (#239) — same gap, same reason.
#
# The allowlist is deliberately generous about well-known FAKE passwords
# (hunter2, changeme, devpass …). Without them the check fires on its own test
# fixtures and on docker-compose docs, and a CRITICAL that cries wolf trains
# people to reach for --no-verify — strictly worse than no check at all.
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "(PGPASSWORD\s*[:=]\s*[\"']?[^[:space:]\"'#\`]{6,}|postgres(ql)?://[^:[:space:]]+:[^@[:space:]]{6,}@)" . \
    | filter_detector_docs \
    | exclude_content "(example|placeholder|YOUR_|REDACTED|XXX|CHANGEME|<[^>]*>|\\\$\{|\\\$[A-Z_]+|password@|:password|sample|dummy|hunter2|devpass|mypgpass|testpass|secret123|changeme|letmein|passw0rd|@(db|database|postgres|localhost|127\.0\.0\.1|host\.docker\.internal):|localhost:5432/postgres\b)" )
report CRITICAL "PostgreSQL password exposure" "$hits"

# ===========================================================================
# HIGH
# ===========================================================================

# --- Inline password/token assignments with non-placeholder values ---
# Allowlist captures: env-var idioms (os.environ.get / getenv / process.env),
# method calls (.getAccessToken(), authService.*, token_resp.json(), .access_token),
# placeholder/tutorial values (changeme*, Welcome1!, keystorePass, secret_value_here,
# password-here, app-password-here, kwargs/type-annotation patterns), design tokens
# (token://...), shell var interpolation ($VAR, ${VAR}), and references to a named
# UPPER_SNAKE constant (`token = RATIFICATION_ARBITER` is a pointer, not a literal —
# the constant's own DEFINITION line is what the checks must catch). Parity with the
# same arm in secrets-scan.py; the two implementations MUST stay in lockstep.
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "(password|passwd|pwd|secret|token|api_key)\s*[:=]\s*[\"']?[A-Za-z0-9._/@!#\$%^&*+=~:?|-]{12,}[\"']?" . \
    | filter_detector_docs \
    | exclude_content "(example|test|fake|REDACTED|<.*>|placeholder|your-|YOUR_|MY_|TODO|XXX|\.\.\.|=\s*\"\"|=\s*''|=\s*\\\$\{|[:=]\s*\\\$[A-Za-z_]|os\.environ|os\.getenv|getenv\(|environ\[|process\.env|EXAMPLE|PLACEHOLDER|description:|^\s*#|^\s*//|FOO|BAR|BAZ|password=password|password=passwd|password=user|password=pass$|kwargs|: str$|: str =|: Optional|password_field|password_hash|token_env|token_name|token_field|password_policy|password_minimum|secret_name|secret_key:|secret_id:|hashed_password|password_required|password_required_actions|change_password|reset_password|require_password|password_expiry|password_strength|encrypt_password|password_validator|secret_word|secret_phrase|FIXME|REPLACE-WITH)" \
    | exclude_content "(token://|changeme|Welcome1|keystorePass|secret_value_here|password-here|app-password-here|=\s*os\.environ|=\s*os\.getenv|getAccessToken\(|authService\.|token_resp\.|\.access_token|\.getToken\(|tokens?\s+(are|will be|should|must|stored|read|comes|never)|password\s+(is|will|should|must|requires|stored|read|never)|^\s*\#\s|secret:\s*foundry|secret:\s*test|secret_key:\s*'?(test|example|<|YOUR)|access_token\s*=\s*[a-zA-Z_].*\.json|access_token\s*=\s*token_|hash:\s*['\"]\$2[aby]\$|argon2id|bcrypt|scrypt)" \
    | exclude_content "([:=]\s*passwordPrompt\(|[:=]\s*secrets\.token_(urlsafe|hex|bytes)\(|[:=]\s*secrets\.choice|[:=]\s*[a-zA-Z_][a-zA-Z0-9_.]*\([^)]*\)\s*[,;]?\s*$|[:=]\s*[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z0-9_]+\(|[:=]\s*_[a-z_]+\.|[:=]\s*request\.|[:=]\s*self\.|--secret=[a-z][a-z0-9_-]+|--password=[a-z][a-z0-9_-]+|StrongAdm1n|P@ss|Pa55|admin123|test123|password123|qwerty|hunter2|letmein|client_id|client_secret\s*=\s*\\\$|access_key\s*=\s*\\\$|[:=]\s*input\(|[:=]\s*getpass\(|password_prompt|prompt_password|encrypt\(|hash_password|verify_password|check_password)" \
    | exclude_content "([:=]\s*[A-Z][A-Z0-9_]{2,}\b(\s*(if|else)\b|\s*$|\s*[,)\]]))" \
    | exclude_content "(token:\s*vscode\.|token:\s*CancellationToken|:\s*CancellationToken|:\s*[A-Z][a-zA-Z0-9_]*Token\b|:\s*Token\s*[,;)]|:\s*Promise<|:\s*string\b|:\s*number\b|:\s*boolean\b|:\s*any\b|:\s*[A-Z][a-zA-Z0-9_]*\s*\||:\s*Optional\[|:\s*Awaitable\[|param\s+token\b|@param\s+\{|^\s*\*\s*@param)" )
report HIGH "inline password/token assignments" "$hits"

# --- Bearer tokens ---
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "[Bb]earer\s+[A-Za-z0-9_.-]{20,}" . \
    | filter_detector_docs \
    | exclude_content "(example|<token>|<TOKEN>|YOUR_TOKEN|REDACTED|\.\.\.|XXX|placeholder|EXAMPLE|description|Bearer\s+\\\$|Bearer\s+\{|Authorization:\s+Bearer\s+\\\$|Bearer\s+<)" )
report HIGH "bearer tokens" "$hits"

# ===========================================================================
# MEDIUM (advisory)
# ===========================================================================

# --- Real-looking emails ---
hits=$(qgrep -rEon "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(com|net|org|io|co|app|dev|ai|me|us|gov|edu|cloud)" . \
    | filter_detector_docs \
    | exclude_content "(@example\.|@test\.|@domain\.|@yourdomain|@company\.|@contoso\.|@acme\.|@my-?org|@your-?org|@placeholder|noreply@|users\.noreply\.github\.com|git@github\.com|GIT_TOKEN@|@localhost|@yourcompany|@gmail\.com.*Co-Authored|john@|jane@|alice@|bob@|admin@example|admin@yourdomain|admin@localhost|root@localhost|user@example|foo@|bar@|baz@|@\.\.\.|smtp\.|imap\.|user@host|user@server|@anthropic\.com|noreply@anthropic|@local\.dev|@\\\$|me@me|test@|email@|dev@local|@youruser|@you\.|@unique-)" \
    | exclude_content "\.example\.(com|org|net)\b|prod\.db\.com|@forestb\.example|@proxy\.example|@server\.example|@corp\.example|@host\.example" )
report MEDIUM "real-looking emails" "$hits"

# --- Internal hostnames ---
# Skill tutorials commonly reference *.corp.local, host.docker.internal,
# *.internal as documentation examples. Allowlist the common ones.
hits=$(qgrep -rEn "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "\b[a-z0-9][a-z0-9-]{2,}\.(internal|corp|intranet)\b" . \
    | filter_detector_docs \
    | exclude_content "(example|placeholder|your-|<host>|REPLACE|host\.docker\.internal|\.corp\.local\b|\.corp\.net\b|\.corp\.example|(payment-gateway|grafana|api|wiki|idp|sso|dc01|cognos|tenant|portal|registry)\.(internal|corp))" )
report MEDIUM "internal hostnames" "$hits"

# ===========================================================================
# LOW (advisory)
# ===========================================================================

# --- Non-RFC1918 IPv4 addresses ---
hits=$(qgrep -rEon "${INCLUDES[@]}" "${EXCLUDES_DIR[@]}" \
    "\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b" . \
    | filter_detector_docs \
    | qgrep -vE ":(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.|0\.0\.0\.0|255\.|169\.254\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|224\.|239\.|240\.)" \
    | qgrep -vE ":(1\.1\.1\.1|1\.0\.0\.1|8\.8\.8\.8|8\.8\.4\.4|9\.9\.9\.9|149\.112\.112\.112|208\.67\.222\.222|208\.67\.220\.220|76\.76\.2\.0|94\.140\.14\.14|2620:fe::|2606:4700::)\b" \
    | qgrep -vE "(1\.3\.6\.1|2\.5\.[0-9]+\.|2\.16\.840|0\.9\.2342|/[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|version\s+[0-9]+\.[0-9]+\.[0-9]+|v?[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\s*$)" )
report LOW "non-RFC1918 IPs" "$hits"

# ===========================================================================
# Summary + exit
# ===========================================================================

BLOCKING=0
if [[ $STRICT -eq 1 ]] || [[ $CRITICAL_HIT -gt 0 ]] || [[ $HIGH_HIT -gt 0 ]]; then
    BLOCKING=1
fi

# --quiet semantics: print nothing unless we are about to exit 1.
if [[ $QUIET -eq 1 && $BLOCKING -eq 0 ]]; then
    exit 0
fi

if [[ $TOTAL_HITS -eq 0 ]]; then
    echo "[OK] secrets-scan clean: $ROOT"
    exit 0
fi

echo "" >&2
echo "[secrets-scan summary]" >&2
[[ $CRITICAL_HIT -gt 0 ]] && echo "  CRITICAL: $CRITICAL_HIT" >&2
[[ $HIGH_HIT     -gt 0 ]] && echo "  HIGH:     $HIGH_HIT" >&2
[[ $MEDIUM_HIT   -gt 0 ]] && echo "  MEDIUM:   $MEDIUM_HIT (advisory — does not block)" >&2
[[ $LOW_HIT      -gt 0 ]] && echo "  LOW:      $LOW_HIT (advisory — does not block)" >&2
echo "  scanned:  $ROOT" >&2

if [[ $BLOCKING -eq 1 ]]; then
    echo "[!] BLOCKING — review above. Override (use only when certain): git push --no-verify" >&2
    exit 1
fi

echo "[OK] only advisory hits — push allowed." >&2
exit 0
