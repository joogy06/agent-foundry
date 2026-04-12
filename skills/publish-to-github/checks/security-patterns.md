# Extended Security Patterns

This file lists patterns the `publish-to-github` skill workflow checks for, beyond
what `publish_prep.py`'s `forbidden_patterns` config catches. These are heuristics —
they produce **warnings**, not errors. The user reviews each finding and decides how
to handle it.

The script itself only greps for the patterns defined in your `~/.claude/publish-config.json`
under `forbidden_patterns`. The skill workflow runs additional checks on top of that.

---

## How the skill applies these checks

After running `publish_prep.py` and confirming it reports "clean", Claude (following
this skill's workflow) runs additional grep passes against the staging directory.
Each finding is reported as a warning with severity, pattern name, and the matching line.

The user reviews the findings and chooses:
- **Add to `forbidden_patterns`** — the pattern should always block publish
- **Add a `scrub` rule** — the specific occurrence should be replaced
- **Add an `exclusion`** — the entire file should not be published
- **Accept** — the match is a false positive (e.g. a documentation example)

---

## Pattern catalog

### Critical — block publish

| Category | Pattern (regex) | What it catches |
|---|---|---|
| Anthropic API key | `sk-ant-[a-zA-Z0-9_-]{20,}` | Real Anthropic keys |
| OpenAI API key | `sk-[a-zA-Z0-9]{20,}` (non-`sk-ant`) | Real OpenAI keys |
| Stripe live key | `(sk\|pk)_live_[a-zA-Z0-9]{24,}` | Live Stripe keys |
| GitHub PAT (classic) | `ghp_[a-zA-Z0-9]{36}` | Classic GitHub personal access tokens |
| GitHub PAT (fine) | `github_pat_[a-zA-Z0-9_]{82}` | Fine-grained PATs |
| Slack bot token | `xoxb-[0-9]+-[0-9]+-[a-zA-Z0-9]{24}` | Slack bot OAuth tokens |
| Slack user token | `xoxp-[0-9]+-[0-9]+-[0-9]+-[a-f0-9]{32}` | Slack user OAuth tokens |
| Google API key | `AIza[a-zA-Z0-9_-]{35}` | Google Cloud API keys |
| AWS access key | `AKIA[A-Z0-9]{16}` | AWS access key IDs |
| AWS secret access | `aws_secret_access_key.{0,4}[=:].{0,4}[A-Za-z0-9/+=]{40}` | AWS secret access keys |
| Google OAuth token | `ya29\.[a-zA-Z0-9_-]+` | Google OAuth bearer tokens |
| JWT token | `eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}` | JSON Web Tokens (often bearer tokens) |
| Private key (RSA) | `-----BEGIN RSA PRIVATE KEY-----` | RSA private key blocks |
| Private key (OpenSSH) | `-----BEGIN OPENSSH PRIVATE KEY-----` | OpenSSH private key blocks |
| Private key (EC) | `-----BEGIN EC PRIVATE KEY-----` | Elliptic curve private keys |
| Private key (PGP) | `-----BEGIN PGP PRIVATE KEY BLOCK-----` | PGP private key blocks |
| DSA private key | `-----BEGIN DSA PRIVATE KEY-----` | DSA private keys |

### High — strongly recommend review

| Category | Pattern | What it catches |
|---|---|---|
| Bearer token (literal) | `[Bb]earer\s+[A-Za-z0-9._-]{20,}` | Literal bearer tokens in code/docs |
| Generic password assignment | `(?i)(password\|passwd\|pwd)\s*[=:]\s*['\"][^'\"]{8,}['\"]` | Hard-coded passwords (excluding `changeme`, `xxx`, `your-password`) |
| Database connection string | `postgres://[^/\s]+:[^/\s]+@` or `mysql://[^/\s]+:[^/\s]+@` | DB URLs with embedded credentials |
| AWS ARN with account | `arn:aws:[a-z0-9-]+:[a-z0-9-]*:[0-9]{12}:` | AWS resource ARNs containing real 12-digit account IDs |
| GCP service account | `[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com` | GCP service account emails |

### Medium — likely worth reviewing

| Category | Pattern | What it catches |
|---|---|---|
| Real email addresses | `[a-zA-Z0-9._%+-]+@(?!example\\.com\|example\\.org\|example\\.net\|test\\..+\|contoso\\.com\|company\\.com\|domain\\.com\|localhost)[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}` | Emails outside RFC 2606 reserved domains |
| Public IPv4 | `(?<![0-9.])(?!10\\.\|172\\.(1[6-9]\|2[0-9]\|3[01])\\.\|192\\.168\\.\|127\\.\|169\\.254\\.\|0\\.\|255\\.\|198\\.51\\.100\\.\|203\\.0\\.113\\.)([0-9]{1,3}\\.){3}[0-9]{1,3}` | Non-RFC1918, non-test-net IPs |
| Internal hostnames | `[a-zA-Z0-9-]+\.(internal\|corp\|local\|lan\|home\\.arpa)\b` | Common private TLDs |
| Workplace domains | Match the user's known employer domains (configurable) | Internal enterprise domains |

### Low — informational warnings

| Category | Pattern | What it catches |
|---|---|---|
| Phone numbers (E.164) | `\+[1-9][0-9]{8,14}\b` | International phone format |
| Phone numbers (NA) | `\b[2-9][0-9]{2}-[2-9][0-9]{2}-[0-9]{4}\b` | North American format |
| Credit card numbers | `\b(?:[0-9]{4}[\s-]?){3}[0-9]{4}\b` | Could be CC, could be UUIDs — review |
| MAC addresses | `\b([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b` | Hardware identifiers |

### File-level warnings

| Check | Threshold | Why |
|---|---|---|
| Large files | >1 MB | Likely shouldn't be in a docs repo; check intent |
| Binary files | non-text content type | Binaries don't belong in skills (other than legitimate logos/images) |
| Executable bit set | files with `+x` outside `scripts/` | Unexpected executables |
| Dangling symlinks | symlinks resolving outside the staging dir | Privacy and reproducibility risk |

---

## What this list does NOT catch

These require human judgement and cannot be reliably grep-detected:

1. **Implicit business fingerprints** — currency symbols, country names, channel mixes,
   demographic targeting, premium/budget positioning. The SKILL.md file might describe
   business strategy in ways that uniquely identify your business without naming it.

2. **Tone of voice and writing style** — your personal phrasing patterns can identify
   you across "anonymous" content.

3. **Code paths that reference internal services** — `https://jira.mycompany.com/foo`
   would be caught by the email/hostname rules above, but `/api/internal-service/v3/`
   alone might not.

4. **Specific technical opinions or controversial takes** — anything that could embarrass
   you, your employer, or your clients.

5. **Customer or client names in case studies** — "We worked with Acme Corp on..."
   is a leak that no regex catches.

**Manual review of every skill file before publishing remains essential.**

---

## Extending these patterns

To add your own patterns:

1. Decide whether the pattern is critical (block publish), or warning (notify user).
2. If critical: add it to your `~/.claude/publish-config.json` under `forbidden_patterns`.
3. If a warning: add a row to this file's pattern catalog and mention it in the skill
   workflow's "extended security scan" step.

To customise the list of "reserved" email domains and IP ranges that should NOT trigger
warnings, add them to `~/.claude/publish-config.json` under a new `safe_patterns` key
(future enhancement — not yet implemented in the script).

---

## Pattern test corpus

Each pattern in this file should have a positive and negative test case to prevent
regex regression. Test corpus lives at `checks/test-corpus/` (not yet implemented;
contribution welcome).
