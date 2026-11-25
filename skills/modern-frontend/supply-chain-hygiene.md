# Frontend supply-chain hygiene

Reference file for the `modern-frontend` skill. Covers lockfile discipline, exact pins, a
minimal-dependency policy, `npm audit` and `osv-scanner` in CI, npm provenance, a Renovate
cadence, no runtime CDN, and Subresource Integrity (SRI). Written for a security-sensitive SPA
(admin consoles, anything that holds a session able to approve or grant), and applicable to any
npm-based front end.

## Contents

- 1. The threat in one paragraph
- 2. Lockfile discipline
- 3. Exact pins and install settings
- 4. Minimal-dependency policy
- 5. Vulnerability scanning in CI
- 6. Provenance and signatures
- 7. Update cadence (Renovate)
- 8. No runtime CDN
- 9. Subresource Integrity
- 10. CI pipeline sketch
- 11. Anti-patterns

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: npm-12-install-policy
    source_url: https://docs.npmjs.com/cli/v12/using-npm/config
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "npm 12.2: allowScripts policy in package.json with npm approve-scripts, strict-allow-scripts, allow-git default none, min-release-age in days (read from @npmcli/config definitions in npm 12.2.1)."
  - kind: external_fact
    subject: osv-scanner
    source_url: https://github.com/google/osv-scanner/releases
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "osv-scanner v2.7.0 released 2026-10-12; v2 CLI uses 'osv-scanner scan source'."
  - kind: external_fact
    subject: npm-incidents-2025
    source_url: https://aws.amazon.com/blogs/security/defending-against-supply-chain-attacks-like-chalk-debug-and-the-shai-hulud-worm
    verified_on: 2026-10-26
    review_by: 2027-10-26
    claim: "2025-09-08: phished maintainer account published malicious chalk, debug and 16 other packages; from 2025-09-14 the Shai-Hulud worm republished hundreds of packages with stolen npm tokens."
  - kind: external_fact
    subject: vite-no-builtin-sri
    source_url: https://vite.dev/config/build-options
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "Vite 8.3.5 has no built-in SRI option (none in its config typings); SRI needs a plugin or post-build step."
  - kind: external_fact
    subject: pnpm-minimum-release-age
    source_url: https://pnpm.io/settings
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "pnpm minimumReleaseAge (minutes) available since pnpm 10.16; current pnpm 12.15.0."
-->

## 1. The threat in one paragraph

Every package in the tree runs with the page's full authority: it can read the DOM, call the API
with the user's cookie, and alter what an approve button sends. Install scripts run with the
developer's or CI runner's authority. On 2025-09-08 a phished maintainer account pushed malicious
versions of 18 very widely used packages (`chalk`, `debug`, `ansi-styles` and others) carrying a
crypto-wallet hijacker; from 2025-09-14 the self-propagating "Shai-Hulud" worm used stolen npm
tokens to republish hundreds of packages with a secret-stealing install script. Teams that
installed within hours of publish were hit; teams with pinned lockfiles, blocked install scripts
and a release-age delay were not. The controls below are ordered by how much of that risk they remove per unit of effort.

## 2. Lockfile discipline

- Commit the lockfile (`package-lock.json`, `pnpm-lock.yaml`, or `yarn.lock`); one package manager
  per repo, enforced with the `packageManager` field in `package.json`.
- CI installs with the frozen command: `npm ci` (fails if `package.json` and the lockfile
  disagree), `pnpm install --frozen-lockfile`, `yarn install --immutable`.
- Review lockfile diffs in pull requests: new transitive packages, changed `resolved` hosts (must be
  the official registry), and removed `integrity` fields are all red flags.
- `npm install <pkg>` only on a developer branch that goes through review; never in CI or in a
  Dockerfile step.

## 3. Exact pins and install settings

`.npmrc` for the project:

```ini
save-exact=true          # package.json gets "1.2.3", not "^1.2.3"
min-release-age=3        # npm: resolve only versions published at least 3 days ago
strict-allow-scripts=true  # npm 12: an install script not approved in package.json "allowScripts" fails the install
engine-strict=true
audit-level=high
```

- Exact pins make `package.json` say what the lockfile says, so an accidental `npm install` cannot
  float a version.
- **Install scripts** are the most common payload path. npm 12 gates them with an `allowScripts`
  policy in `package.json` (approve per package and version with `npm approve-scripts`; explicit
  denials allowed); `strict-allow-scripts=true` turns an unreviewed script into a failed install
  instead of a warning. On older npm, or as a blunt rule, `ignore-scripts=true` and run the few
  needed build scripts by name. pnpm: `onlyBuiltDependencies` allowlist.
- npm 12 also refuses git dependencies by default (`allow-git=none`); keep it that way.
- Use a **release-age delay** so a version must have been public for a few days before it is
  installed: npm `min-release-age` (days), pnpm `minimumReleaseAge` (minutes), Renovate
  `minimumReleaseAge`. The September 2025 compromises were detected and pulled within hours.

## 4. Minimal-dependency policy

A written rule, checked in review:

| Question before adding a package | Reject or reconsider when |
|---|---|
| Can the platform do it? (`fetch`, `Intl`, `URL`, `crypto.randomUUID`, `structuredClone`, `<dialog>`) | Yes |
| Is it under ~50 lines to own? (debounce, a shortcut hook, a small formatter) | Yes |
| How many transitive dependencies does it add? | More than a handful for a small feature |
| Maintenance: last release, open security issues, number of maintainers, 2FA / trusted publishing | Abandoned, single unverified maintainer for a security-relevant package |
| Does it run in the auth or approval path? | Then it needs a higher bar and a named owner |
| Install scripts? | Present without a clear need |

Keep a `DEPENDENCIES.md` (or comments in `package.json` via a tool) stating why each direct
dependency exists; remove what is unused (`npx knip` or `depcheck` in CI).

## 5. Vulnerability scanning in CI

| Tool | Data source | Use |
|---|---|---|
| `npm audit --omit=dev --audit-level=high` | GitHub Advisory Database via the registry | Fast gate on production dependencies |
| `osv-scanner` (Google) | OSV.dev, aggregates GitHub, npm and other advisories | Lockfile scan in CI and on a schedule; also covers the Python side of the repo |
| GitHub Dependabot alerts or similar | GitHub Advisory Database | Notification, not a gate |

- Gate pull requests on **high and critical** vulnerabilities in production dependencies; report
  the rest. Development-only findings (test runners, linters) are triaged, not gating.
- Run the same scan on a **schedule** (daily or weekly) on the default branch: new advisories
  arrive for code that has not changed.
- Allowlist a finding only with an expiry date and a reason (not reachable, no fix yet), in a
  committed file the scanner reads.

## 6. Provenance and signatures

- `npm audit signatures` verifies registry signatures and, where present, provenance attestations
  of installed packages; run it in CI after `npm ci`.
- **npm provenance** links a published version to the public CI run and source commit that built
  it (Sigstore). Prefer dependencies that publish with provenance, especially in the auth path.
- If you publish packages: publish from CI with trusted publishing (OIDC, no long-lived npm
  token) and provenance, and require 2FA for maintainers.
- Provenance proves where a package was built, not that its code is benign; it narrows who could
  have published it.

## 7. Update cadence (Renovate)

Updates are a security control: stale pins accumulate known vulnerabilities. Batch them so review
stays possible.

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", ":pinAllExceptPeerDependencies"],
  "schedule": ["before 6am on monday"],
  "minimumReleaseAge": "3 days",
  "internalChecksFilter": "strict",
  "prCreation": "not-pending",
  "lockFileMaintenance": { "enabled": true, "schedule": ["before 6am on the first day of the month"] },
  "vulnerabilityAlerts": { "enabled": true, "schedule": ["at any time"], "minimumReleaseAge": null },
  "packageRules": [
    { "matchUpdateTypes": ["minor", "patch"], "matchDepTypes": ["devDependencies"], "groupName": "dev deps (non-major)" },
    { "matchUpdateTypes": ["major"], "dependencyDashboardApproval": true }
  ]
}
```

- `config:best-practices` already includes `security:minimumReleaseAgeNpm` (3 days); the explicit
  setting above keeps the intent visible.
- Weekly batch for routine updates; security fixes at any time.
- Majors wait for approval on the dependency dashboard and get a changelog read.
- Monthly lockfile maintenance refreshes transitive dependencies within the pinned ranges.
- CI (tests, typecheck, scans, bundle-size budget) must pass before any merge; no automerge for
  packages in the auth path.

## 8. No runtime CDN

The built bundle, fonts, icons and polyfills are served from the app's own origin.

- A third-party script host is a party that can change your code at any time; a CSP of
  `script-src 'self'` (see `spa-auth-webauthn`) makes the rule enforceable.
- Self-host web fonts (download and serve; no Google Fonts link at runtime for an internal
  console).
- No `<script src="https://cdn…">` for analytics, error reporting or feature flags in an admin
  console; if a vendor SDK is needed, bundle it from npm (it goes through the lockfile and scans)
  and send data to a first-party endpoint.
- Air-gapped or LAN-only deployments need this anyway: a runtime CDN fails closed when the network
  does.

## 9. Subresource Integrity

SRI (`integrity="sha384-…"` on `<script>` and `<link rel="stylesheet">`) makes the browser refuse
a file whose hash does not match.

- For **cross-origin** resources it is essential; with §8 there should be none.
- For **same-origin** hashed assets it adds protection against tampering between the build and the
  browser (a compromised static host, CDN cache poisoning in front of the app). It is cheap to add.
- Vite does not emit `integrity` attributes by default (dated in the FRESHNESS block); add them
  with a maintained build plugin or a post-build step that hashes the files referenced by
  `index.html` and writes the attributes, and pin that tool exactly.
- `modulepreload` links in `index.html` can carry `integrity`; chunks loaded later by dynamic
  `import()` cannot be covered by attributes. The only browser mechanism for them is the
  `integrity` map in an import map, which is an inline script and so needs its hash in
  `script-src`. Know that limit: SRI on the HTML tags covers the entry and preloaded chunks, not
  every lazily loaded chunk.
- Note `crossorigin` must be set consistently on tags that carry `integrity`.

## 10. CI pipeline sketch

```yaml
# .github/workflows/frontend.yml (excerpt)
jobs:
  build:
    runs-on: ubuntu-latest
    permissions: { contents: read }
    steps:
      - uses: actions/checkout@<full-commit-sha>            # pin actions by SHA, not tag
      - uses: actions/setup-node@<full-commit-sha>
        with: { node-version-file: .nvmrc, cache: npm }
      - run: npm ci                                          # frozen; install-script policy from .npmrc
      - run: npm audit signatures
      - run: npm audit --omit=dev --audit-level=high
      - run: osv-scanner scan source --lockfile package-lock.json
      - run: npm run typecheck && npm test -- --run
      - run: npm run build
      - run: node scripts/check-dist.mjs                     # no inline scripts, no external hosts, SRI present
```

`check-dist.mjs` greps `dist/index.html` for `<script>` without `src`, for `http(s)://` hosts other
than your own, and for tags missing `integrity`.

## 11. Anti-patterns

| Don't | Why | Do instead |
|---|---|---|
| `npm install` in CI or a Dockerfile | Resolves new versions at build time; lockfile ignored | `npm ci` (frozen) |
| Caret ranges in `package.json` with no lockfile review | Any compromised minor lands on next install | `save-exact`, reviewed lockfile diffs |
| Installing a version hours after publish | The window in which most malicious releases are live | Release-age delay (3+ days) |
| Allowing all install scripts | The common payload path | npm `allowScripts` policy with `strict-allow-scripts`, or `ignore-scripts` + explicit allowlist |
| A package for something the platform does | More code with your session's authority | Platform API or a few owned lines |
| `<script src>` from a CDN in an admin console | A third party can change your code | Self-host; `script-src 'self'` |
| Permanent audit ignores | Reachable vulnerabilities hide forever | Allowlist with expiry and reason |
| Automerging majors | Breaking or hostile changes ship unread | Dashboard approval for majors |
