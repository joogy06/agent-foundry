#!/usr/bin/env python3
"""secrets-scan.py — cross-platform pre-push secrets scanner.

Stdlib-only Python re-implementation of `secrets-scan.sh` with full feature
parity. Runs on Python 3.10+ on Linux, macOS, and Windows. Patterns,
allowlists, severity tiers, exit codes, and CLI flags match the bash version
exactly — either implementation can be wired to the pre-push hook.

Categories:
    CRITICAL  live API keys, PEM private keys, AWS creds, JWTs
    HIGH      inline password/token assignments (non-placeholder)
    MEDIUM    real emails, internal hostnames        (advisory)
    LOW       non-RFC1918 IPv4                       (advisory)

Usage:
    python3 scripts/secrets-scan.py                   # scan $PWD
    python3 scripts/secrets-scan.py C:\\repo           # scan target tree
    python3 scripts/secrets-scan.py --quiet           # silent unless blocking
    python3 scripts/secrets-scan.py --verbose         # full hit list
    python3 scripts/secrets-scan.py --strict          # MEDIUM/LOW also block

Exit codes:
    0 — clean OR only advisory hits in default mode
    1 — CRITICAL or HIGH hit found (review required)
    2 — script error
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INCLUDE_EXTS = {
    ".md", ".py", ".sh", ".bash", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".ps1", ".cmd", ".bat",
    ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    # Credential-bearing file types. Their absence meant the CRITICAL
    # "PEM private-key headers" rule could not fire on the file types private
    # keys actually use — the rule was aimed exclusively at keys PASTED INTO
    # source, and blind to the committed key file itself. Found while freezing
    # the hook contract for #250: the fixture staged a .pem and nothing blocked.
    ".pem", ".key", ".crt", ".cer", ".der", ".p12", ".pfx", ".jks", ".keystore",
    ".ppk", ".pub", ".asc", ".gpg", ".kdbx", ".ovpn", ".netrc", ".htpasswd",
}
INCLUDE_GLOBS = ("*.env", "*.env.example", "*.env.template", "*.example", "*.template")

# Extensionless credential filenames. `should_scan` keys on the suffix, so these
# are invisible to it — `id_rsa` is the single most likely name for a leaked
# private key and has no extension at all.
INCLUDE_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", "_netrc", ".pgpass", ".htpasswd", "credentials", "authorized_keys",
}
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", ".venv", "venv", ".env.d",
}
MAX_FILE_BYTES = 5 * 1024 * 1024  # skip files > 5 MB (likely binary/data dumps)

# Paths that are themselves detector documentation — they CONTAIN the
# pattern strings as part of their content. Skip during scan.
DETECTOR_DOCS_RE = re.compile(
    r"(skills/publish-to-github|docs/plans/_review|"
    # a redaction unit test must contain secret-SHAPED literals to prove the redactor removes them; same category as the scanner's own source
    # tests/secrets-scan: the scanner-parity suite must contain credential-SHAPED literals to test the scanner
    r"tests/lineage-extract-static/unit/test_redact\.py|tests/secrets-scan/|"
    r"lineage-extract-static/scripts/redact\.py|"
    r"scripts/secrets[-_]scan|\.git/hooks/pre-push)"
)

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------


class Check(NamedTuple):
    severity: str          # CRITICAL | HIGH | MEDIUM | LOW
    name: str
    pattern: re.Pattern[str]
    allowlist: tuple[re.Pattern[str], ...]
    line_anchor: str = ""  # "" = line, "file" = report filenames only, "^" = anchor at line start


def _re(pat: str) -> re.Pattern[str]:
    return re.compile(pat)


def _allow(*pats: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in pats)


CHECKS: tuple[Check, ...] = (
    # ----- CRITICAL ---------------------------------------------------------

    Check(
        "CRITICAL", "live API key shapes",
        _re(
            r"(sk-[a-zA-Z0-9]{20}"
            r"|sk-(proj|svcacct|ant|live|test)-[a-zA-Z0-9_-]{20}"
            r"|ghp_[a-zA-Z0-9]{20}|gho_[a-zA-Z0-9]{20}|ghs_[a-zA-Z0-9]{20}|ghu_[a-zA-Z0-9]{20}"
            r"|github_pat_[a-zA-Z0-9_]{20}"
            r"|xox[abprs]-[a-zA-Z0-9-]{20}"
            r"|AIza[A-Za-z0-9_-]{30}"
            r"|sk_live_[a-zA-Z0-9]{20}|pk_live_[a-zA-Z0-9]{20}|rk_live_[a-zA-Z0-9]{20}"
            r"|sk_test_[a-zA-Z0-9]{20,}"
            r"|whsec_[a-zA-Z0-9]{20}|nrak-[a-zA-Z0-9]{20}|hf_[a-zA-Z0-9]{20})"
        ),
        _allow(
            r"(<|>|example|placeholder|YOUR_|YOURKEY|EXAMPLE|REDACTED|XXX|"
            r"\.\.\.|fake|TEST_|DUMMY|sample|abcdef|012345|deadbeef)",
        ),
    ),

    Check(
        "CRITICAL", "PEM private-key headers",
        _re(r"^-----BEGIN (RSA|OPENSSH|EC|PGP|DSA|ENCRYPTED|ED25519) PRIVATE KEY( BLOCK)?-----"),
        _allow(),
        line_anchor="file",
    ),

    Check(
        "CRITICAL", "AWS credentials",
        _re(
            r"(\bAKIA[0-9A-Z]{16}\b"
            r"|aws_secret_access_key\s*=\s*[\"']?[A-Za-z0-9/+=]{30,}[\"']?)"
        ),
        _allow(
            r"(example|placeholder|YOUR_|REDACTED|XXX|AKIAEXAMPLE|AKIAIOSFODNN7|AKIA[X]{16})",
        ),
    ),

    Check(
        "CRITICAL", "JWT shapes",
        _re(r"\beyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\b"),
        _allow(),
    ),

    # ----- HIGH -------------------------------------------------------------

    Check(
        "CRITICAL", "WooCommerce REST consumer key/secret",
        # ck_/cs_ are 40-hex WooCommerce REST credentials. Added 2026-07-25 after a
        # cross-project report: the SAME consumer key was embedded in two repos, so
        # rotation broke whichever copy was forgotten. Previously UNDETECTED here —
        # an earlier grep for "ck_" matched `check_password` in an allowlist, not a
        # real rule, so these sailed through every scan.
        _re(r"\b(ck|cs)_[0-9a-fA-F]{32,}\b"),
        _allow(
            r"(example|placeholder|YOUR_|REDACTED|XXX|sample|0{32}|x{32}|f{32})",
        ),
    ),

    Check(
        "CRITICAL", "PostgreSQL password exposure",
        _re(
            r"(PGPASSWORD\s*[:=]\s*[\"']?[^\s\"'#`]{6,}"
            r"|postgres(?:ql)?://[^:\s]+:[^@\s]{6,}@)"
        ),
        _allow(
            # Placeholder / template forms.
            r"(example|placeholder|YOUR_|REDACTED|XXX|CHANGEME|<[^>]*>|\$\{|\$[A-Z_]+|"
            r"password@|:password|sample|dummy"
            # Well-known FAKE passwords that appear in docs and test fixtures. Without
            # these the check fires on its own test suite (legacy-code-intel's
            # test_redaction.py asserts PGPASSWORD *is* redacted) and on
            # docker-compose docs — a CRITICAL that cries wolf trains people to reach
            # for --no-verify, which is strictly worse than no check.
            r"|hunter2|devpass|mypgpass|testpass|secret123|changeme|letmein|passw0rd"
            # Compose/doc-style host:port targets that are self-evidently non-prod.
            r"|@(db|database|postgres|localhost|127\.0\.0\.1|host\.docker\.internal):"
            r"|localhost:5432/postgres\b)",
        ),
    ),

    Check(
        "HIGH", "inline password/token assignments",
        _re(
            r"(password|passwd|pwd|secret|token|api_key)\s*[:=]\s*"
            r"[\"']?" + r"[A-Za-z0-9._/@!#$%^&*+=~:?|-]{12,}" + r"[\"']?"
        ),
        _allow(
            # Doc/placeholder values
            r"(example|test|fake|REDACTED|<.*>|placeholder|your-|YOUR_|MY_|TODO|XXX|"
            r"\.\.\.|=\s*\"\"|=\s*''|=\s*\$\{|[:=]\s*\$[A-Za-z_]|EXAMPLE|PLACEHOLDER|"
            r"description:|^\s*#|^\s*//|FOO|BAR|BAZ|"
            r"password=password|password=passwd|password=user|password=pass$|"
            r"kwargs|: str$|: str =|: Optional|"
            r"password_field|password_hash|token_env|token_name|token_field|"
            r"password_policy|password_minimum|secret_name|secret_key:|secret_id:|"
            r"hashed_password|password_required|password_required_actions|"
            r"change_password|reset_password|require_password|password_expiry|"
            r"password_strength|encrypt_password|password_validator|"
            r"secret_word|secret_phrase|FIXME|REPLACE-WITH)",
            # Env-var idioms
            r"(os\.environ|os\.getenv|getenv\(|environ\[|process\.env)",
            # Reference to a named UPPER_SNAKE constant, optionally via a ternary.
            # Assigning a bare UPPER_SNAKE name is a pointer, never a literal — and if the
            # constant itself held a credential, its own definition line is what the
            # CRITICAL live-key checks (and this check) would flag. Allowing the
            # REFERENCE does not weaken detection of the DEFINITION.
            r"[:=]\s*[A-Z][A-Z0-9_]{2,}\b(\s*(if|else)\b|\s*$|\s*[,)\]])",
            # Method-call assignments
            r"([:=]\s*passwordPrompt\(|[:=]\s*secrets\.token_(urlsafe|hex|bytes)\(|"
            r"[:=]\s*secrets\.choice|[:=]\s*[a-zA-Z_][a-zA-Z0-9_.]*\([^)]*\)\s*[,;]?\s*$|"
            r"[:=]\s*[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z0-9_]+\(|"
            r"[:=]\s*_[a-z_]+\.|[:=]\s*request\.|[:=]\s*self\.|"
            r"[:=]\s*input\(|[:=]\s*getpass\()",
            # CLI placeholder flags + tutorial passwords
            r"(--secret=[a-z][a-z0-9_-]+|--password=[a-z][a-z0-9_-]+|"
            r"StrongAdm1n|P@ss|Pa55|admin123|test123|password123|qwerty|hunter2|letmein|"
            r"client_id|client_secret\s*=\s*\$|access_key\s*=\s*\$|"
            r"password_prompt|prompt_password|encrypt\(|hash_password|verify_password|check_password|"
            r"token://|changeme|Welcome1|keystorePass|secret_value_here|password-here|app-password-here)",
            # Method-call references + access patterns
            r"(getAccessToken\(|authService\.|token_resp\.|\.access_token|\.getToken\(|"
            r"tokens?\s+(are|will be|should|must|stored|read|comes|never)|"
            r"password\s+(is|will|should|must|requires|stored|read|never)|"
            r"^\s*\#\s|secret:\s*foundry|secret:\s*test|"
            r"secret_key:\s*'?(test|example|<|YOUR)|"
            r"access_token\s*=\s*[a-zA-Z_].*\.json|access_token\s*=\s*token_|"
            r"hash:\s*['\"]\$2[aby]\$|argon2id|bcrypt|scrypt)",
            # TypeScript / language type annotations
            r"(token:\s*vscode\.|token:\s*CancellationToken|:\s*CancellationToken|"
            r":\s*[A-Z][a-zA-Z0-9_]*Token\b|:\s*Token\s*[,;)]|"
            r":\s*Promise<|:\s*string\b|:\s*number\b|:\s*boolean\b|:\s*any\b|"
            r":\s*[A-Z][a-zA-Z0-9_]*\s*\||:\s*Optional\[|:\s*Awaitable\[|"
            r"param\s+token\b|@param\s+\{|^\s*\*\s*@param)",
        ),
    ),

    Check(
        "HIGH", "bearer tokens",
        _re(r"[Bb]earer\s+[A-Za-z0-9_.-]{20,}"),
        _allow(
            r"(example|<token>|<TOKEN>|YOUR_TOKEN|REDACTED|\.\.\.|XXX|placeholder|"
            r"EXAMPLE|description|Bearer\s+\$|Bearer\s+\{|"
            r"Authorization:\s+Bearer\s+\$|Bearer\s+<)",
        ),
    ),

    # ----- MEDIUM (advisory) -----------------------------------------------

    Check(
        "MEDIUM", "real-looking emails",
        _re(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(com|net|org|io|co|app|dev|ai|me|us|gov|edu|cloud)"),
        _allow(
            r"(@example\.|@test\.|@domain\.|@yourdomain|@company\.|@contoso\.|@acme\.|"
            r"@my-?org|@your-?org|@placeholder|noreply@|users\.noreply\.github\.com|"
            r"git@github\.com|GIT_TOKEN@|@localhost|@yourcompany|"
            r"@gmail\.com.*Co-Authored|john@|jane@|alice@|bob@|"
            r"admin@example|admin@yourdomain|admin@localhost|root@localhost|"
            r"user@example|foo@|bar@|baz@|@\.\.\.|smtp\.|imap\.|"
            r"user@host|user@server|@anthropic\.com|noreply@anthropic|"
            r"@local\.dev|@\$|me@me|test@|email@|dev@local|@youruser|@you\.|@unique-)",
            r"(\.example\.(com|org|net)\b|prod\.db\.com|"
            r"@forestb\.example|@proxy\.example|@server\.example|"
            r"@corp\.example|@host\.example)",
        ),
    ),

    Check(
        "MEDIUM", "internal hostnames",
        _re(r"\b[a-z0-9][a-z0-9-]{2,}\.(internal|corp|intranet)\b"),
        _allow(
            r"(example|placeholder|your-|<host>|REPLACE|host\.docker\.internal|"
            r"\.corp\.local\b|\.corp\.net\b|\.corp\.example|"
            r"(payment-gateway|grafana|api|wiki|idp|sso|dc01|cognos|tenant|portal|registry)"
            r"\.(internal|corp))",
        ),
    ),

    # ----- LOW (advisory) --------------------------------------------------

    Check(
        "LOW", "non-RFC1918 IPs",
        _re(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
        _allow(
            # RFC1918 + loopback + link-local + RFC5737 doc + CGNAT + multicast
            r"(\b10\.|\b172\.(1[6-9]|2[0-9]|3[01])\.|\b192\.168\.|\b127\.|"
            r"\b0\.0\.0\.0\b|\b255\.|\b169\.254\.|"
            r"\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.|"
            r"\b192\.0\.2\.|\b198\.51\.100\.|\b203\.0\.113\.|"
            r"\b224\.|\b239\.|\b240\.)",
            # Well-known public DNS providers in tutorial docs
            r"(\b1\.1\.1\.1\b|\b1\.0\.0\.1\b|\b8\.8\.8\.8\b|\b8\.8\.4\.4\b|"
            r"\b9\.9\.9\.9\b|\b149\.112\.112\.112\b|"
            r"\b208\.67\.222\.222\b|\b208\.67\.220\.220\b|"
            r"\b76\.76\.2\.0\b|\b94\.140\.14\.14\b)",
            # X.509 OIDs + version strings + CIS-style control identifiers
            r"(\b1\.3\.6\.1|\b2\.5\.[0-9]+\.|\b2\.16\.840|\b0\.9\.2342|"
            r"\bversion\s+[0-9]+\.[0-9]+\.[0-9]+|"
            r"\bv[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\b|"
            r"\bCIS\s+[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|"
            r"\b[A-Z][a-zA-Z]+\s+[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\+?|"
            r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\+|"
            r"~+[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)",
        ),
    ),
)

# ---------------------------------------------------------------------------
# File traversal
# ---------------------------------------------------------------------------


def should_scan(path: Path) -> bool:
    """Which files are opened at all.

    #239: this diverged from the bash scanner in a way no output comparison could
    show. bash passes `--include='*.env*'` to grep — a TRAILING wildcard, so it
    reads `creds.env.txt` and `.env.local`. This matched `*.env` suffix-exactly and
    skipped both, while the bash arm scanned them. A file one scanner never opens
    cannot produce a finding to compare.

    Reconciled toward the WIDER behaviour deliberately: for a secrets scanner,
    reading a file that turns out to be clean costs a few milliseconds, while
    skipping one that is not costs a leaked credential.
    """
    if path.suffix.lower() in INCLUDE_EXTS:
        return True
    name = path.name
    if name in INCLUDE_NAMES or name.lower() in INCLUDE_NAMES:
        return True                        # extensionless credential filenames
    if ".env" in name:                     # matches bash's --include='*.env*'
        return True
    for pat in INCLUDE_GLOBS:
        if path.match(pat) or name.endswith(pat.lstrip("*")):
            return True
    return False


def iter_staged_files(root: Path):
    """Yield (path, content) for files STAGED in git — the pre-commit surface.

    Shares the exact same CHECKS as the full scan, so the commit-time hook and the
    push-time gate can never drift apart. Deleted paths are skipped; content is read
    from the INDEX (`git show :path`), not the worktree, so what is scanned is what
    is actually about to be committed."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return
    for rel in (l.strip() for l in out.splitlines() if l.strip()):
        full = root / rel
        if not should_scan(full):
            continue
        try:
            blob = subprocess.run(["git", "-C", str(root), "show", f":{rel}"],
                                  capture_output=True, check=True).stdout
            if len(blob) > MAX_FILE_BYTES:
                continue
            yield full, blob.decode("utf-8", errors="replace")
        except (OSError, subprocess.CalledProcessError):
            continue


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            full = Path(dirpath) / fn
            if not should_scan(full):
                continue
            try:
                if full.stat().st_size > MAX_FILE_BYTES:
                    continue
                content = full.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            yield full, content


# ---------------------------------------------------------------------------
# Scan engine
# ---------------------------------------------------------------------------


def scan(root: Path, source=None):
    """Return dict of severity -> list of (category_name, [(rel_path, lineno, line)]).

    `source` is a callable(root) yielding (path, content); defaults to the full
    worktree walk. `iter_staged_files` swaps in the git index for pre-commit use."""
    source = source or iter_files
    results: dict[str, list[tuple[str, list[tuple[str, int, str]]]]] = {
        s: [] for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    }

    for check in CHECKS:
        hits: list[tuple[str, int, str]] = []
        for path, content in source(root):
            rel = path.relative_to(root)
            rel_str = str(rel).replace("\\", "/")
            if DETECTOR_DOCS_RE.search(rel_str):
                continue

            if check.line_anchor == "file":
                # `Pattern.search(string[, pos[, endpos]])` — the second argument is
                # POS, not flags. This read `search(content, re.MULTILINE)`, and
                # re.MULTILINE is the integer 8, so it started at offset 8 AND never
                # applied MULTILINE. A `^`-anchored pattern can then never match:
                # the only file-anchored rule, CRITICAL "PEM private-key headers",
                # was INERT and could not fire on any file, ever. The bash scanner
                # caught the same content via grep, so the two disagreed in the
                # opposite direction from #239 — and the rule-name parity guard
                # could not see it, because the rule was PRESENT, just dead.
                # Scan line by line with the anchor doing its job.
                if any(check.pattern.search(line) for line in content.splitlines()):
                    if not any(a.search(content) for a in check.allowlist):
                        hits.append((rel_str, 0, "<file contains pattern>"))
                continue

            for lineno, line in enumerate(content.splitlines(), 1):
                if check.pattern.search(line):
                    if any(a.search(line) for a in check.allowlist):
                        continue
                    hits.append((rel_str, lineno, line.strip()[:200]))

        if hits:
            results[check.severity].append((check.name, hits))

    return results


# ---------------------------------------------------------------------------
# CLI / reporting
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-platform pre-push secrets scanner.",
        epilog="Exit codes: 0=clean/advisory-only, 1=blocking hit, 2=script error.",
    )
    parser.add_argument("root", nargs="?", default=os.getcwd(),
                        help="Directory to scan (default: cwd).")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Silent unless a blocking hit is found.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print all hits, not just first 10 per category.")
    parser.add_argument("--staged", action="store_true",
                        help="scan only files staged in git (pre-commit surface), "
                             "reading content from the index rather than the worktree")
    parser.add_argument("--strict", action="store_true",
                        help="Promote MEDIUM/LOW to blocking.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        return 2

    results = scan(root, source=iter_staged_files if args.staged else None)

    total_hits = 0
    severity_counts = {s: 0 for s in results}
    for severity, categories in results.items():
        for _, hits in categories:
            severity_counts[severity] += len(hits)
            total_hits += len(hits)

    blocking = (
        args.strict
        or severity_counts["CRITICAL"] > 0
        or severity_counts["HIGH"] > 0
    )

    if args.quiet and not blocking:
        return 0

    if total_hits == 0:
        print(f"[OK] secrets-scan clean: {root}")
        return 0

    # Print findings, severity order
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        for name, hits in results[severity]:
            print()
            print(f"[{severity}] {name} ({len(hits)} hit(s))")
            shown = hits if args.verbose else hits[:10]
            for rel, lineno, line in shown:
                if lineno == 0:
                    print(f"./{rel}: {line}")
                else:
                    print(f"./{rel}:{lineno}:{line}")
            if not args.verbose and len(hits) > 10:
                print(f"  ...(+{len(hits) - 10} more — pass --verbose to see all)")

    # Summary to stderr
    print("", file=sys.stderr)
    print("[secrets-scan summary]", file=sys.stderr)
    if severity_counts["CRITICAL"]:
        print(f"  CRITICAL: {severity_counts['CRITICAL']}", file=sys.stderr)
    if severity_counts["HIGH"]:
        print(f"  HIGH:     {severity_counts['HIGH']}", file=sys.stderr)
    if severity_counts["MEDIUM"]:
        print(f"  MEDIUM:   {severity_counts['MEDIUM']} (advisory — does not block)", file=sys.stderr)
    if severity_counts["LOW"]:
        print(f"  LOW:      {severity_counts['LOW']} (advisory — does not block)", file=sys.stderr)
    print(f"  scanned:  {root}", file=sys.stderr)

    if blocking:
        print(
            "[!] BLOCKING — review above. "
            + ("Override (use only when certain): git commit --no-verify"
               if args.staged else
               "Override (use only when certain): git push --no-verify"),
            file=sys.stderr,
        )
        return 1

    print("[OK] only advisory hits — push allowed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
