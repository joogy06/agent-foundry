#!/usr/bin/env python3
"""
publish_prep.py — Generic engine for preparing a public-safe staging directory.

Reads its rules from a config file (JSON). The config defines:
  - which directories to exclude when copying skills/, agents/, and commands/
  - which strings to scrub from individual files (find/replace)
  - which patterns to grep for as forbidden leak indicators
  - optional paths to bundle into staging (README, docs)

Live ~/.claude/ tree is NEVER modified. Everything happens in
/tmp/claude-skills-public-<timestamp>/. Re-runnable and stateless.

Config file resolution order (first match wins):
    --config <path>
    $PUBLISH_CONFIG environment variable
    ~/.claude/publish-config.json
    ./publish-config.json

Usage:
    python3 publish_prep.py                       # use default config location
    python3 publish_prep.py --config /path/to.json
    python3 publish_prep.py --exclude skills/foo  # additional one-shot exclusion
    python3 publish_prep.py --verify DIR          # grep an existing staging dir
    python3 publish_prep.py --validate-config     # parse + validate config and exit

This script is generic and contains no project-specific strings. All
project-specific scrub rules live in the user's private config file
(default: ~/.claude/publish-config.json), which is NEVER published.
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


# --- Configuration --------------------------------------------------------

CLAUDE_HOME = Path(os.environ.get('CLAUDE_HOME', str(Path.home() / '.claude')))

DEFAULT_CONFIG_PATHS = [
    Path(os.environ.get('PUBLISH_CONFIG', '/dev/null')),
    Path.home() / '.claude' / 'publish-config.json',
    Path.home() / '.codex' / 'publish-config.json',
    Path.home() / '.gemini' / 'publish-config.json',
    Path.cwd() / 'publish-config.json',
]

# Include PID for sub-second uniqueness — two runs in the same second
# won't collide on the staging dir path.
TIMESTAMP = time.strftime('%Y-%m-%dT%H-%M-%S') + f'-{os.getpid()}'
STAGING_DIR_DEFAULT = Path('/tmp') / f'claude-skills-public-{TIMESTAMP}'

# Pattern-level exclusions ALWAYS applied (not user-configurable — these are
# never appropriate to publish)
ALWAYS_EXCLUDE_PATTERNS = [
    '*.before-*',
    '*.bak',
    '*.bak.*',                # timestamped forensic backups (e.g. file.bak.20260520T132009Z
                              # produced by the wiki skill's hash-verified-writes HARD-RULE)
    '.DS_Store',
    'Thumbs.db',
    '__pycache__',
    '.pytest_cache',
    '*.pyc',
    '*.pyo',
    '*.tmp',
    '*.swp',
    '*.swo',
]

GITIGNORE_DEFAULT = """# Private / local-only content — never publish
**/*.before-*
**/*.bak
**/*.bak.*

# OS noise
.DS_Store
Thumbs.db

# Python
__pycache__/
*.pyc
*.pyo
*.pyd

# Editors
.vscode/
.idea/
*.swp
*.swo
*~

# Logs and temporary files
*.log
*.tmp

# Build artifacts
dist/
build/
*.egg-info/
"""


# --- Extended security scan patterns --------------------------------------
# Each entry: (severity, category, regex, description).
# These run only when --extended-scan is passed. They produce WARNINGS, not
# errors — the user reviews each finding and decides whether to add to the
# config or accept as a false positive.

EXTENDED_SCAN_PATTERNS = [
    # Critical — secrets and credentials
    ('critical', 'anthropic-api-key',     r'sk-ant-[a-zA-Z0-9_-]{20,}',                               'Anthropic API key'),
    ('critical', 'openai-api-key',        r'(?<!ant)sk-[a-zA-Z0-9]{20,}',                            'OpenAI-style API key'),
    ('critical', 'stripe-live',           r'(?:sk|pk)_live_[a-zA-Z0-9]{24,}',                        'Stripe live key'),
    ('critical', 'github-pat-classic',    r'ghp_[a-zA-Z0-9]{36}',                                    'GitHub PAT (classic)'),
    ('critical', 'github-pat-fine',       r'github_pat_[a-zA-Z0-9_]{82}',                            'GitHub PAT (fine-grained)'),
    ('critical', 'slack-bot',             r'xoxb-[0-9]+-[0-9]+-[a-zA-Z0-9]{24}',                     'Slack bot token'),
    ('critical', 'slack-user',            r'xoxp-[0-9]+-[0-9]+-[0-9]+-[a-f0-9]{32}',                 'Slack user token'),
    ('critical', 'google-api-key',        r'AIza[a-zA-Z0-9_-]{35}',                                  'Google API key'),
    ('critical', 'aws-access-key',        r'AKIA[A-Z0-9]{16}',                                       'AWS access key ID'),
    ('critical', 'rsa-private-key',       r'-----BEGIN RSA PRIVATE KEY-----',                        'RSA private key block'),
    ('critical', 'openssh-private',       r'-----BEGIN OPENSSH PRIVATE KEY-----',                    'OpenSSH private key block'),
    ('critical', 'ec-private-key',        r'-----BEGIN EC PRIVATE KEY-----',                         'EC private key block'),
    ('critical', 'pgp-private-key',       r'-----BEGIN PGP PRIVATE KEY BLOCK-----',                  'PGP private key block'),
    ('critical', 'jwt-token',             r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}', 'JWT token'),

    # High — likely sensitive
    ('high', 'bearer-literal',            r'[Bb]earer\s+[A-Za-z0-9._-]{20,}',                        'Literal bearer token'),
    ('high', 'aws-secret',                r'aws_secret_access_key.{0,4}[=:].{0,4}[A-Za-z0-9/+=]{40}', 'AWS secret access key'),
    ('high', 'db-conn-string',            r'(?:postgres|mysql|mongodb)://[^/\s]+:[^/\s]+@',          'DB connection string with creds'),
    ('high', 'gcp-service-account',       r'[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com',       'GCP service account email'),

    # Medium — context-dependent
    ('medium', 'real-email',              r'[a-zA-Z0-9._%+-]+@(?!example\.|test\.|contoso\.|company\.|domain\.|localhost|noreply@|users\.noreply)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', 'Email outside reserved domains'),
    ('medium', 'internal-tld',            r'[a-zA-Z0-9-]+\.(?:internal|corp|local|lan|home\.arpa)\b', 'Internal/private TLD'),

    # Low — informational
    ('low', 'phone-e164',                 r'\+[1-9][0-9]{8,14}\b',                                   'Phone (E.164)'),
]


def _is_public_ipv4(s):
    """True if s is a real public IPv4 (not RFC1918, loopback, link-local, test-net)."""
    try:
        parts = [int(p) for p in s.split('.')]
        if len(parts) != 4 or any(p < 0 or p > 255 for p in parts):
            return False
        a, b = parts[0], parts[1]
        if a == 10: return False                              # 10.0.0.0/8
        if a == 172 and 16 <= b <= 31: return False           # 172.16.0.0/12
        if a == 192 and b == 168: return False                # 192.168.0.0/16
        if a == 127: return False                             # 127.0.0.0/8
        if a == 169 and b == 254: return False                # 169.254.0.0/16
        if a == 0 or a == 255: return False                   # 0.0.0.0/8, broadcast
        if a == 198 and b == 51: return False                 # 198.51.100.0/24 TEST-NET-2
        if a == 203 and b == 0: return False                  # 203.0.113.0/24 TEST-NET-3
        if a == 192 and b == 0: return False                  # 192.0.0.0/24, 192.0.2.0/24
        if a == 224 or a == 239: return False                 # multicast
        if a == 100 and 64 <= b <= 127: return False          # 100.64.0.0/10 CGNAT
        return True
    except (ValueError, IndexError):
        return False


IPV4_REGEX = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')


# --- Terminal formatting --------------------------------------------------

def _colour(text, code):
    if not sys.stdout.isatty():
        return text
    return f'\033[{code}m{text}\033[0m'


def red(t):    return _colour(t, '31')
def green(t):  return _colour(t, '32')
def yellow(t): return _colour(t, '33')
def cyan(t):   return _colour(t, '36')
def bold(t):   return _colour(t, '1')


def header(text):
    print()
    print(bold(cyan('─' * 72)))
    print(bold(cyan(f' {text}')))
    print(bold(cyan('─' * 72)))


# --- Config loading -------------------------------------------------------

def find_config(explicit_path=None):
    """Resolve which config file to use. Returns Path or None."""
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            print(red(f'Config not found: {p}'), file=sys.stderr)
            sys.exit(1)
        return p
    for p in DEFAULT_CONFIG_PATHS:
        if p.exists() and p.is_file():
            return p
    return None


def load_config(path):
    """Load and validate the JSON config file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(red(f'Failed to parse config {path}:'), file=sys.stderr)
        print(red(f'  Line {e.lineno}, column {e.colno}: {e.msg}'), file=sys.stderr)
        print(red('  Check for: trailing commas, missing quotes, mismatched braces'), file=sys.stderr)
        sys.exit(1)

    # Validate top-level structure
    if not isinstance(data, dict):
        print(red('Config root must be an object'), file=sys.stderr)
        sys.exit(1)

    if data.get('version') != 1:
        print(red(f'Unsupported config version: {data.get("version")} (expected 1)'),
              file=sys.stderr)
        sys.exit(1)

    # Validate sections
    data.setdefault('exclusions', [])
    # Normalise: strip trailing slashes so "skills/foo/" matches "skills/foo"
    data['exclusions'] = [e.rstrip('/') for e in data['exclusions']]
    data.setdefault('scrubs', [])
    data.setdefault('forbidden_patterns', [])
    data.setdefault('bundle_files', [])
    data.setdefault('source', {})

    # Validate source structure (null -> empty dict; wrong type -> error;
    # subdirs must be a list of strings, not a bare string).
    if data['source'] is None:
        data['source'] = {}
    if not isinstance(data['source'], dict):
        print(red('source must be an object'), file=sys.stderr)
        sys.exit(1)
    if 'subdirs' in data['source']:
        if not isinstance(data['source']['subdirs'], list):
            print(red('source.subdirs must be a list (e.g. ["skills", "agents", "commands"])'),
                  file=sys.stderr)
            sys.exit(1)
        for i, sd in enumerate(data['source']['subdirs']):
            if not isinstance(sd, str):
                print(red(f'source.subdirs[{i}] must be a string'), file=sys.stderr)
                sys.exit(1)

    data.setdefault('extended_scan_ignore', [])
    if not isinstance(data['extended_scan_ignore'], list):
        print(red('extended_scan_ignore must be a list'), file=sys.stderr)
        sys.exit(1)
    for i, entry in enumerate(data['extended_scan_ignore']):
        if not isinstance(entry, dict):
            print(red(f'extended_scan_ignore[{i}] must be an object'), file=sys.stderr)
            sys.exit(1)
        has_file = 'file' in entry
        has_pattern = 'file_pattern' in entry
        if has_file == has_pattern:
            print(red(f'extended_scan_ignore[{i}] needs exactly one of "file" or "file_pattern"'),
                  file=sys.stderr)
            sys.exit(1)
        cats = entry.get('categories')
        if cats != '*' and not isinstance(cats, list):
            print(red(f'extended_scan_ignore[{i}].categories must be a list or "*"'),
                  file=sys.stderr)
            sys.exit(1)

    if not isinstance(data['exclusions'], list):
        print(red('exclusions must be a list'), file=sys.stderr)
        sys.exit(1)
    if not isinstance(data['scrubs'], list):
        print(red('scrubs must be a list'), file=sys.stderr)
        sys.exit(1)
    if not isinstance(data['forbidden_patterns'], list):
        print(red('forbidden_patterns must be a list'), file=sys.stderr)
        sys.exit(1)

    for i, scrub in enumerate(data['scrubs']):
        if 'file' not in scrub:
            print(red(f'scrubs[{i}] missing "file"'), file=sys.stderr)
            sys.exit(1)
        if 'replacements' not in scrub or not isinstance(scrub['replacements'], list):
            print(red(f'scrubs[{i}] missing "replacements" list'), file=sys.stderr)
            sys.exit(1)
        for j, r in enumerate(scrub['replacements']):
            if 'find' not in r or 'replace' not in r:
                print(red(f'scrubs[{i}].replacements[{j}] needs "find" and "replace"'),
                      file=sys.stderr)
                sys.exit(1)

    return data


# --- Filesystem helpers ---------------------------------------------------

def should_exclude(rel_path, exclusions):
    """Return True if a relative path should be excluded from the copy.
    Combines config exclusions with always-exclude patterns."""
    rel_str = str(rel_path)

    # Direct directory or file match against config exclusions
    for excl in exclusions:
        if rel_str == excl or rel_str.startswith(excl + '/'):
            return True

    # Pattern match on any path component (always-exclude patterns)
    for part in rel_path.parts:
        for pattern in ALWAYS_EXCLUDE_PATTERNS:
            if fnmatch.fnmatch(part, pattern):
                return True

    return False


def copy_tree_with_exclusions(src_root, staging_root, source_root, exclusions):
    """Walk src_root and copy to staging_root, skipping excluded paths.
    source_root is the directory we're computing relative paths from."""
    copied = []
    skipped = []
    for root, dirs, files in os.walk(src_root):
        rel_root = Path(root).relative_to(source_root)

        # Filter subdirectories in-place
        dirs_to_remove = []
        for d in sorted(dirs):
            rel_d = rel_root / d
            if should_exclude(rel_d, exclusions):
                skipped.append(str(rel_d) + '/')
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)

        # Copy files
        for f in sorted(files):
            rel_f = rel_root / f
            if should_exclude(rel_f, exclusions):
                skipped.append(str(rel_f))
                continue

            src_file = Path(root) / f
            dst_file = staging_root / rel_f
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            if src_file.is_symlink():
                link_target = os.readlink(str(src_file))
                if dst_file.exists():
                    dst_file.unlink()
                os.symlink(link_target, str(dst_file))
            else:
                shutil.copy2(src_file, dst_file)
            copied.append(str(rel_f))

    return copied, skipped


# --- Scrub engine ---------------------------------------------------------

def apply_scrubs(staging_root, scrubs):
    """Apply find/replace rules to staged files. Returns list of results.
    Skips binary or non-UTF-8 files with a warning rather than crashing."""
    results = []
    for scrub in scrubs:
        relpath = scrub['file']
        replacements = scrub['replacements']
        file_path = staging_root / relpath

        if not file_path.exists():
            results.append({
                'file': relpath,
                'status': 'missing',
                'notes': [],
            })
            continue

        try:
            original = file_path.read_text(encoding='utf-8')
        except UnicodeDecodeError as e:
            results.append({
                'file': relpath,
                'status': 'binary-skipped',
                'notes': [f'binary or non-UTF-8 file, skipped: {e}'],
            })
            continue
        modified = original

        # Longest-first ordering
        sorted_reps = sorted(replacements, key=lambda r: -len(r['find']))
        notes = []
        for r in sorted_reps:
            count = modified.count(r['find'])
            if count == 0:
                notes.append(f"NOT FOUND: {r['find']!r}")
                continue
            modified = modified.replace(r['find'], r['replace'])
            notes.append(f"{count}× {r['find']!r} → {r['replace']!r}")

        if modified != original:
            file_path.write_text(modified, encoding='utf-8')
            results.append({
                'file': relpath,
                'status': 'modified',
                'notes': notes,
            })
        else:
            results.append({
                'file': relpath,
                'status': 'no-change',
                'notes': notes,
            })

    return results


# --- Bundle external files ------------------------------------------------

def bundle_files(staging_root, bundle_specs):
    """Copy external files (e.g. README, docs) into the staging dir.

    For directory sources, recursively copies files but SKIPS:
      - Hidden files (names starting with `.`)
      - Underscore-prefixed files (names starting with `_`)

    This filter is intentional: hidden files typically carry editor/OS state
    (`.DS_Store`, `.git*`, `.vscode`) and `_*` is reserved for internal
    sentinels. To bundle an individual hidden file (e.g. `.env.example`),
    use a file source instead of a directory source.

    As a safety check, each source path is resolved and a warning is
    emitted if it falls outside the user's home directory — this catches
    typos like `~/../../etc/passwd` that would otherwise silently bundle
    system files. The bundle still proceeds (warning, not error) because
    the user may legitimately want to bundle from /etc, /var, etc.
    """
    copied = []
    missing = []
    for spec in bundle_specs:
        src_path = Path(os.path.expanduser(spec['source'])).resolve()

        # Path-containment safety check: warn if the source resolves
        # outside the user's home directory.
        try:
            src_path.relative_to(Path.home())
        except ValueError:
            print(yellow(f'  ⚠ bundle source resolves outside ~/: {spec["source"]} -> {src_path}'))
            print(yellow('    (continuing — this may be intentional, but verify the path)'))

        dst_rel = spec['dest']
        dst_path = staging_root / dst_rel

        if not src_path.exists():
            missing.append(spec['source'])
            continue

        if src_path.is_dir():
            # Recursive copy — skips hidden/underscore files (see docstring).
            for root, dirs, files in os.walk(src_path):
                rel = Path(root).relative_to(src_path)
                target_dir = dst_path / rel
                target_dir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    if f.startswith('.') or f.startswith('_'):
                        continue
                    shutil.copy2(Path(root) / f, target_dir / f)
                    copied.append(str(Path(dst_rel) / rel / f))
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied.append(dst_rel)

    return copied, missing


# --- Verification ---------------------------------------------------------

def verify_staging(staging_root, forbidden_patterns):
    """Grep the staging dir for forbidden patterns. Uses fixed-string matching
    (-F) so patterns containing regex metacharacters work correctly. Strict
    return code checking (0 = match, 1 = no match, anything else = error).
    """
    findings = []
    if not forbidden_patterns:
        return findings
    try:
        for pattern in forbidden_patterns:
            result = subprocess.run(
                ['grep', '-rnF', '--exclude-dir=.git', '--', pattern, str(staging_root)],
                capture_output=True, text=True, check=False,
            )
            # grep returns 0 = found, 1 = not found, 2+ = error
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    findings.append((pattern, line))
            elif result.returncode == 1:
                pass  # no match
            else:
                # grep error — treat as a critical failure of the verify step
                raise RuntimeError(
                    f'grep failed for pattern {pattern!r}: '
                    f'returncode={result.returncode}, stderr={result.stderr.strip()}'
                )
    except FileNotFoundError:
        return None
    return findings


def _is_finding_ignored(finding, ignore_rules):
    """Return True if a finding matches any allowlist rule."""
    file_path = finding['file']
    category = finding['category']
    for rule in ignore_rules:
        # Match file (either exact or pattern)
        if 'file' in rule:
            if rule['file'] != file_path:
                continue
        elif 'file_pattern' in rule:
            if not fnmatch.fnmatch(file_path, rule['file_pattern']):
                continue
        else:
            continue  # Malformed; skip
        # File matched; check category
        cats = rule.get('categories', [])
        if cats == '*':
            return True
        if isinstance(cats, list) and category in cats:
            return True
    return False


def run_extended_scan(staging_root, ignore_rules=None, max_file_size=10 * 1024 * 1024):
    """Walk the staging dir and apply extended security patterns.
    Returns a list of findings, each: dict(severity, category, description, file, line, match).
    Skips files larger than max_file_size to avoid OOM on accidental large files.
    Filters out findings matching any rule in ignore_rules.
    """
    if ignore_rules is None:
        ignore_rules = []
    findings = []
    compiled = [(s, c, re.compile(p), d) for (s, c, p, d) in EXTENDED_SCAN_PATTERNS]

    for root, dirs, files in os.walk(staging_root):
        # Skip .git if user has already initialised the staging dir
        dirs[:] = [d for d in dirs if d != '.git']

        for f in files:
            file_path = Path(root) / f
            try:
                if file_path.is_symlink():
                    target = os.readlink(str(file_path))
                    target_resolved = Path(target) if Path(target).is_absolute() else (file_path.parent / target)
                    try:
                        target_resolved = target_resolved.resolve()
                        if not str(target_resolved).startswith(str(staging_root)):
                            findings.append({
                                'severity': 'medium',
                                'category': 'dangling-symlink',
                                'description': 'Symlink points outside staging directory',
                                'file': str(file_path.relative_to(staging_root)),
                                'line': 0,
                                'match': f'-> {target}',
                            })
                    except (OSError, RuntimeError):
                        pass
                    continue

                size = file_path.stat().st_size
                if size > max_file_size:
                    findings.append({
                        'severity': 'low',
                        'category': 'large-file',
                        'description': f'File larger than {max_file_size // (1024 * 1024)} MB',
                        'file': str(file_path.relative_to(staging_root)),
                        'line': 0,
                        'match': f'{size} bytes',
                    })
                    continue
            except OSError:
                continue

            # Read file as text; skip binary files quietly
            try:
                content = file_path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue

            # Apply each compiled pattern
            for severity, category, regex, description in compiled:
                for m in regex.finditer(content):
                    line_no = content.count('\n', 0, m.start()) + 1
                    findings.append({
                        'severity': severity,
                        'category': category,
                        'description': description,
                        'file': str(file_path.relative_to(staging_root)),
                        'line': line_no,
                        'match': m.group()[:80],
                    })

            # IPv4 needs special handling (regex finds candidates, function decides)
            for m in IPV4_REGEX.finditer(content):
                if _is_public_ipv4(m.group()):
                    line_no = content.count('\n', 0, m.start()) + 1
                    findings.append({
                        'severity': 'medium',
                        'category': 'public-ipv4',
                        'description': 'Non-RFC1918 / non-test-net IPv4',
                        'file': str(file_path.relative_to(staging_root)),
                        'line': line_no,
                        'match': m.group(),
                    })

    # Apply allowlist — filter out findings that match any ignore rule
    if ignore_rules:
        findings = [f for f in findings if not _is_finding_ignored(f, ignore_rules)]
    return findings


# --- Main -----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Create a clean staging directory for publishing ~/.claude/skills/, ~/.claude/agents/, and ~/.claude/commands/ to public github.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--config', metavar='PATH',
                        help='Path to publish-config.json (overrides default lookup)')
    parser.add_argument('--exclude', action='append', default=[], metavar='PATH',
                        help='Additional one-shot exclusion (repeatable). Relative to source.')
    parser.add_argument('--verify', metavar='DIR',
                        help='Grep an existing staging directory and exit')
    parser.add_argument('--validate-config', action='store_true',
                        help='Parse and validate the config file, then exit')
    parser.add_argument('--staging-dir', metavar='PATH',
                        help='Custom staging directory (default: /tmp/claude-skills-public-<ts>)')
    parser.add_argument(
        '--extended-scan', action='store_true',
        help='After verify, run extended security scan (regex patterns from checks/security-patterns.md). '
             'Findings are warnings, not errors.'
    )
    parser.add_argument(
        '--no-extended-scan', action='store_true',
        help='Skip extended scan even if config has extended_scan_default: true (future).'
    )
    args = parser.parse_args()

    # --- Standalone verify mode ---
    if args.verify:
        config_path = find_config(args.config)
        if not config_path:
            print(red('No config file found — cannot determine forbidden patterns'),
                  file=sys.stderr)
            return 1
        config = load_config(config_path)
        header(f'Verifying {args.verify}')
        findings = verify_staging(Path(args.verify), config['forbidden_patterns'])
        if findings is None:
            print(red('  grep not available'))
            return 1
        if not findings:
            print(green('  ✓ Clean — no forbidden strings found'))
            return 0
        print(red(f'  ✗ {len(findings)} leaks remaining:'))
        for pattern, line in findings:
            print(f'    [{pattern}] {line}')
        return 1

    # --- Locate and load config ---
    config_path = find_config(args.config)
    if not config_path:
        print(red('No publish-config.json found. Searched these locations:'), file=sys.stderr)
        for p in DEFAULT_CONFIG_PATHS:
            if str(p) != '/dev/null':
                print(red(f'  - {p}'), file=sys.stderr)
        print(file=sys.stderr)
        print(red('To get started:'), file=sys.stderr)
        print(red('  1. Copy the example template:'), file=sys.stderr)
        print(red('       cp ~/.claude/skills/publish-to-github/templates/publish-config.example.json \\'),
              file=sys.stderr)
        print(red('          ~/.claude/publish-config.json'), file=sys.stderr)
        print(red('  2. Edit it to match your skills/exclusions/scrubs.'), file=sys.stderr)
        print(red('  3. Re-run this script.'), file=sys.stderr)
        return 1

    config = load_config(config_path)

    if args.validate_config:
        print(green(f'✓ Config valid: {config_path}'))
        print(f'  exclusions:         {len(config["exclusions"])}')
        print(f'  scrubs:             {len(config["scrubs"])}')
        print(f'  forbidden patterns: {len(config["forbidden_patterns"])}')
        print(f'  bundle files:       {len(config["bundle_files"])}')
        print(f'  extended-scan ignore rules: {len(config.get("extended_scan_ignore", []))}')

        # Path existence checks (warnings only, not errors)
        warnings = []
        source_root_v = Path(
            os.path.expanduser(config['source'].get('root', str(CLAUDE_HOME)))
        ).resolve()
        if not source_root_v.exists():
            warnings.append(f'source.root not found: {source_root_v}')
        for sd in config['source'].get('subdirs', ['skills', 'agents', 'commands']):
            if not (source_root_v / sd).exists():
                warnings.append(f'source subdir not found: {source_root_v / sd}')
        for scrub in config['scrubs']:
            target = source_root_v / scrub['file']
            if not target.exists():
                warnings.append(f"scrub target not found: {scrub['file']}")
        for spec in config['bundle_files']:
            src = Path(os.path.expanduser(spec['source'])).resolve()
            if not src.exists():
                warnings.append(f"bundle source not found: {spec['source']}")

        if warnings:
            print()
            print(yellow(f'  ⚠ {len(warnings)} path warnings:'))
            for w in warnings:
                print(yellow(f'    - {w}'))
        return 0

    # --- Resolve source root ---
    source_root = Path(
        os.path.expanduser(config['source'].get('root', str(CLAUDE_HOME)))
    ).resolve()
    source_subdirs = config['source'].get('subdirs', ['skills', 'agents', 'commands'])

    # --- Resolve staging dir ---
    staging_dir = Path(args.staging_dir) if args.staging_dir else STAGING_DIR_DEFAULT

    # --- Build exclusion list ---
    exclusions = list(config['exclusions'])
    exclusions.extend(args.exclude)

    header('publish_prep.py — staging mode')
    print(f'  Config:        {config_path}')
    print(f'  Source root:   {source_root}')
    print(f'  Source subdirs:{source_subdirs}')
    print(f'  Staging dir:   {staging_dir}')
    print()
    print('  Exclusions from config:')
    for excl in config['exclusions']:
        print(f'    - {excl}')
    if args.exclude:
        print('  Additional --exclude:')
        for excl in args.exclude:
            print(f'    - {excl}')
    print()
    print('  Always-excluded patterns:')
    for pat in ALWAYS_EXCLUDE_PATTERNS:
        print(f'    - {pat}')

    # --- Reset staging dir ---
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    # --- Phase 1: copy source subdirs ---
    header('Phase 1: copy source subdirs (with exclusions)')
    total_copied = 0
    total_skipped = 0
    for subdir in source_subdirs:
        src = source_root / subdir
        if not src.exists():
            print(yellow(f'  SKIP: {src} does not exist'))
            continue
        copied, skipped = copy_tree_with_exclusions(
            src, staging_dir, source_root, exclusions
        )
        total_copied += len(copied)
        total_skipped += len(skipped)
        print(f'  {subdir}: {len(copied)} files copied, {len(skipped)} excluded')

        excluded_dirs = sorted({s for s in skipped if s.endswith('/')})
        for ed in excluded_dirs:
            print(yellow(f'    - {ed}'))
        excluded_files = [s for s in skipped if not s.endswith('/')]
        if excluded_files:
            shown = excluded_files[:5]
            for ef in shown:
                print(yellow(f'    - {ef}'))
            if len(excluded_files) > 5:
                print(yellow(f'    - ...and {len(excluded_files) - 5} more'))

    # --- Phase 2: scrubs ---
    header('Phase 2: scrub embedded private content')
    scrub_results = apply_scrubs(staging_dir, config['scrubs'])
    for r in scrub_results:
        if r['status'] == 'modified':
            print(green(f'  ✓ {r["file"]}'))
            for n in r['notes']:
                print(f'      {n}')
        elif r['status'] == 'no-change':
            print(f'  = {r["file"]} (no changes)')
        elif r['status'] == 'missing':
            print(yellow(f'  ? {r["file"]} (missing in staging — excluded?)'))
        elif r['status'] == 'binary-skipped':
            print(yellow(f'  ! {r["file"]} (binary, skipped)'))
            for n in r['notes']:
                print(f'      {n}')

    # --- Phase 3: bundle external files ---
    header('Phase 3: bundle external files (README, docs, etc.)')
    if config['bundle_files']:
        copied_bundle, missing_bundle = bundle_files(staging_dir, config['bundle_files'])
        for b in copied_bundle:
            print(green(f'  + {b}'))
        for m in missing_bundle:
            print(yellow(f'  SKIP: {m} not found'))
    else:
        print('  (no bundle files configured)')
        copied_bundle = []

    # --- Phase 3b: re-apply scrubs to bundled files ---
    # Scrubs in Phase 2 only see files copied in Phase 1 (source.subdirs).
    # Run scrubs again now so rules targeting bundled files (e.g. "CLAUDE.md"
    # at staging root) can take effect.
    bundle_only_scrubs = [
        s for s in config['scrubs']
        if (staging_dir / s['file']).exists()
        and not any(
            s['file'].startswith(sd + '/') or s['file'] == sd
            for sd in config['source'].get('subdirs', ['skills', 'agents', 'commands'])
        )
    ]
    if bundle_only_scrubs:
        header('Phase 3b: re-apply scrubs to bundled files')
        rerun = apply_scrubs(staging_dir, bundle_only_scrubs)
        for r in rerun:
            if r['status'] == 'modified':
                print(green(f'  ✓ {r["file"]}'))
                for n in r['notes']:
                    print(f'      {n}')
            elif r['status'] == 'no-change':
                print(f'  = {r["file"]} (no changes)')

    # --- Phase 4: write .gitignore ---
    header('Phase 4: write .gitignore')
    gitignore_content = config.get('gitignore') or GITIGNORE_DEFAULT
    # Augment with config exclusions so users who clone and re-run still respect them
    gitignore_content = gitignore_content.rstrip() + '\n\n# Config-driven exclusions\n'
    for excl in config['exclusions']:
        gitignore_content += f'{excl}/\n'
    (staging_dir / '.gitignore').write_text(gitignore_content, encoding='utf-8')
    print(green('  + .gitignore'))

    # --- Phase 5: verify ---
    header('Phase 5: verify staging is clean')
    findings = verify_staging(staging_dir, config['forbidden_patterns'])
    verify_status = 'clean'
    if findings is None:
        print(red('  ✗ grep not available — cannot verify staging is clean'))
        print(red('    Install grep, or set PUBLISH_SKIP_VERIFY=1 to bypass at your own risk.'))
        if os.environ.get('PUBLISH_SKIP_VERIFY') == '1':
            print(yellow('    PUBLISH_SKIP_VERIFY=1 set, continuing without verify (UNSAFE)'))
            verify_status = 'skipped-unsafe'
        else:
            verify_status = 'failed-no-grep'
    elif not findings:
        print(green(f'  ✓ Clean — zero matches for {len(config["forbidden_patterns"])} forbidden patterns'))
    else:
        print(red(f'  ✗ {len(findings)} leaks remaining:'))
        for pattern, line in findings:
            print(f'    [{pattern}] {line}')
        verify_status = 'leaks'

    # --- Phase 5b: extended security scan (optional) ---
    if args.extended_scan:
        header('Phase 5b: extended security scan')
        scan_findings = run_extended_scan(staging_dir, config.get('extended_scan_ignore', []))
        if not scan_findings:
            ignore_count = len(config.get('extended_scan_ignore', []))
            if ignore_count > 0:
                print(green(f'  ✓ No extended-scan findings (allowlist: {ignore_count} rules active)'))
            else:
                print(green('  ✓ No extended-scan findings'))
        else:
            by_severity = {'critical': [], 'high': [], 'medium': [], 'low': []}
            for f in scan_findings:
                by_severity[f['severity']].append(f)
            for sev in ['critical', 'high', 'medium', 'low']:
                items = by_severity[sev]
                if not items:
                    continue
                color = red if sev == 'critical' else (yellow if sev in ('high', 'medium') else None)
                label = f'  [{sev.upper()}] {len(items)} findings'
                print(color(label) if color else label)
                for f in items[:10]:
                    print(f"    {f['file']}:{f['line']}  {f['category']}  {f['match']!r}")
                if len(items) > 10:
                    print(f"    ...and {len(items) - 10} more {sev} findings")
            print()
            print(yellow(f'  Extended scan found {len(scan_findings)} potential issues. '
                         'Review each and either add to config (forbidden_patterns/scrubs/exclusions) '
                         'or accept as false positive.'))

    # --- Summary ---
    header('Summary')
    print(f'  Staging directory: {bold(str(staging_dir))}')
    print(f'  Files copied:      {total_copied}')
    print(f'  Files excluded:    {total_skipped}')
    print(f'  Scrubs applied:    {sum(1 for r in scrub_results if r["status"] == "modified")}')
    print(f'  Files bundled:     {len(copied_bundle)}')
    print(f'  Verify:            {green(verify_status) if verify_status == "clean" else red(verify_status)}')

    if verify_status not in ('clean', 'skipped-unsafe'):
        print()
        print(red('  ⚠  Staging directory was not verified — refusing to report success.'))
        return 1

    if verify_status == 'leaks':
        print()
        print(red('  ⚠  Staging directory has leaks — review above before publishing.'))
        return 1

    print()
    print(green('  Staging is ready. Next steps:'))
    print()
    print(f'    {bold("cd " + str(staging_dir))}')
    print(f'    {bold("git init -b main")}')
    print(f'    {bold("git add .")}')
    print(f'    {bold("git commit -m \"Initial commit: Claude Code skills, agents, and commands\"")}')
    print()
    print('    # Create the repo on github.com, then:')
    print(f'    {bold("git remote add origin git@github.com:YOURNAME/REPONAME.git")}')
    print(f'    {bold("git push -u origin main")}')
    print()
    print('  To re-verify later:')
    print(f'    python3 publish_prep.py --verify {staging_dir}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
