---
name: hostinger-hosting
description: Use when managing websites on Hostinger hosting — hPanel navigation, WordPress staging environment, LiteSpeed Cache configuration, PHP version management, SSH access (port 65002), DNS zone editor, SSL/TLS certificates, email setup (IMAP/SMTP settings, SPF/DKIM/DMARC), backup and restore, Hostinger CDN, Node.js deployment, cron jobs, Git integration, file manager, database management, migration to/from Hostinger, or troubleshooting Hostinger-specific errors (500, SSL loops, upload limits). ALSO covers the programmatic arm — the Hostinger REST API and the official hostinger-api-mcp server (scoped binaries, HOSTINGER_API_TOKEN, cache purge, theme/plugin deploy, DNS) for automating anything the console does by hand.
disambiguation: The Hostinger PLATFORM — hPanel, staging, LiteSpeed, PHP versions, host-level limits, and Hostinger's own API/MCP. Administering the WordPress application itself, on any host, is wordpress-admin.
---

# Hostinger Hosting

## Overview

Hostinger uses a custom control panel (hPanel, not cPanel), LiteSpeed web server, and NVMe storage. This skill covers hPanel navigation, WordPress-specific features, performance, SSH/developer tools, DNS, backups, SSL, email, security, troubleshooting, and migration.

## hPanel Navigation

### Main Sidebar
- **Home** — Hosting plans, domains, VPS, services overview
- **Websites** — Manage existing sites, add new, migrate
- **Domains** — Domain settings, DNS zone, purchase
- **Emails** — Email services (Hostinger Email, Titan Email)
- **Billing** — Subscriptions, invoices, payment methods

### Per-Website Dashboard Sidebar
- **Dashboard** — Resource usage overview
- **WordPress** — Overview, auto-updates, plugins, themes, staging, security
- **Files** — File Manager, FTP Accounts
- **Databases** — MySQL Databases, phpMyAdmin, Remote MySQL
- **Security** — SSL, Force HTTPS, malware scanner, IP manager
- **Performance** — CDN, object cache, LiteSpeed
- **Advanced** — PHP Configuration, DNS Zone Editor, Cron Jobs, SSH Access, GIT, .htaccess editor, Hotlink Protection, Activity Logs

**AI assistant (Kodee):** Built into hPanel, can toggle maintenance mode, flush caches, tweak LiteSpeed, run migrations.

## WordPress Features

### Staging Environment

**Availability:** Business plan or higher.

**Create:** Websites > Dashboard > WordPress > Staging > Create staging. Enter subdomain name, wait a few minutes.

- Creates full copy (files + database) on a subdomain
- Production and staging are independent (safe to modify)
- **Publish:** Click three-dots menu > Publish (replaces live with staging)
- **Revert:** Option to revert after publishing
- **Limitations:** No multisite support. Only works for domains (not subdomains). External nameservers require manual A record.

### Object Cache

**Based on LiteSpeed Memcached (LSMCD)**, not Redis on shared hosting. Business plan or higher.

**Enable:** hPanel > WordPress > Overview > Core section > toggle Object Cache.

### PHP Version Management

**Location:** Advanced > PHP Configuration.

Select version from dropdown (minimum 8.2 recommended). **PHP Options tab** for: `upload_max_filesize`, `post_max_size`, `max_execution_time`, `memory_limit`.

### Auto-Updates

**Location:** WordPress > Security. Separate toggles for core, plugins, and themes.

### Malware Scanner

Built into hPanel: Websites > Dashboard > Security. Scans for harmful files and suspicious code.

## Performance

### LiteSpeed Web Server

All Hostinger hosting runs LiteSpeed. LiteSpeed Cache for WordPress (LSCWP) plugin pre-installed. Features: page caching, image optimization, CSS/JS minification, lazy load, database optimization. OPcache enabled by default.

### Hostinger CDN

**Availability:** Business plan or higher.

**Enable:** Dashboard > search CDN > Enable. Domain must point to Hostinger nameservers. Auto-resizes/compresses images (WebP). Up to 40% performance improvement.

### Resource Limits

**Web Hosting:**

| Parameter | Single | Premium | Business |
|-----------|--------|---------|----------|
| Websites | 1 | 3 | 50 |
| Storage (NVMe) | 10 GB | 20 GB | 50 GB |
| Bandwidth | 100 GB | Unlimited | Unlimited |
| CPU Cores | 1 | 1 | 2 |
| RAM | 1 GB | 2 GB | 3 GB |
| PHP Workers | 25 | 40 | 60 |
| PHP Memory | 1024 MB | 1536 MB | 2048 MB |
| Email Accounts | 1 total | 2/website | 5/website |

**Cloud Hosting:**

| Parameter | Startup | Professional | Enterprise |
|-----------|---------|--------------|-----------|
| Websites | 100 | 100 | 100 |
| Storage (NVMe) | 100 GB | 200 GB | 300 GB |
| CPU Cores | 4 | 5 | 6 |
| RAM | 4 GB | 6 GB | 12 GB |
| PHP Workers | 100 | 200 | 300 |
| PHP Memory | 3072 MB | 6144 MB | 12288 MB |

### Compression & Protocols

- **Brotli** enabled by default (GZIP as fallback)
- **HTTP/2** and **HTTP/3 (QUIC)** supported via LiteSpeed

## SSH & Developer Tools

### SSH Access

**Availability:** Premium plan and above (NOT Single).

**Port:** `65002` (custom, not standard 22)

```bash
ssh u123456789@185.x.x.x -p 65002
```

**Enable:** Advanced > SSH Access > Enable. Username: `u{account_number}`. Password: same as FTP password. SSH key auth supported.

### WP-CLI

Available via SSH. Full command set accessible after connecting.

### Git Integration

**Location:** Advanced > GIT.

- Supports public and private repos
- Configure: Repository Address, Branch, Install Path (default: `/public_html`)
- Webhook support for GitHub continuous deployment
- **Limitation:** Deploys files only — no build steps

### Composer

Available via SSH for PHP dependency management.

### Node.js

**Availability:** Business and Cloud plans. Deploy manually or from GitHub. Configured via hPanel.

### Cron Jobs

**Location:** Advanced > Cron Jobs.

Two types: **PHP** (for .php files) and **Custom** (for scripts with special characters, use .sh file). Timezone: UTC+0.

## DNS Management

### DNS Zone Editor

**Location:** Advanced > DNS Zone Editor (domain must use Hostinger nameservers).

**Default Hostinger nameservers:** `ns1.dns-parking.com`, `ns2.dns-parking.com`

### Supported Records

| Record | Purpose |
|--------|---------|
| A | Domain to IPv4 |
| AAAA | Domain to IPv6 |
| CNAME | Alias to another domain |
| MX | Mail server |
| TXT | SPF, DKIM, verification tokens |
| SRV | Service location |
| CAA | SSL certificate authority auth |

**Default TTL:** 14400 seconds (4 hours).

### Cloudflare Integration

Update nameservers at Domains > select domain > Change Nameservers. Then manage DNS in Cloudflare, not hPanel. **SSL mode must be "Full" or "Full (Strict)"** to avoid redirect loops.

### Email DNS Records

```
SPF (TXT):    v=spf1 include:_spf.mail.hostinger.com ~all
DKIM (CNAME): Auto-configured for Hostinger Email
DMARC (TXT):  v=DMARC1; p=none; rua=mailto:dmarc@yourdomain.com
MX:           mx1.hostinger.com (priority 5), mx2.hostinger.com (priority 10)
```

**Only one SPF record per domain.** Only one email provider per domain at a time.

## Backup & Restore

| Plan | Frequency | Retention |
|------|-----------|-----------|
| Premium | Weekly | 6 weeks |
| Business | Daily | 7 days |
| Cloud | Daily | 7 days |

**Location:** Files > Backups.

- Generate on-demand backups (files, database, or both)
- Download or restore from backup date
- Can restore files and database separately
- Restoration overwrites current files/database (10-15 min for large sites)

## SSL/TLS

### Free SSL (Let's Encrypt)

Auto-installed on all websites. Lifetime free with auto-renewal. Domain-validated (DV).

**Custom SSL:** Uninstall free cert first, then Import SSL (paste cert, private key, CA bundle).

### Force HTTPS

**Method 1:** hPanel > Security > SSL > toggle "Force HTTPS"

**Method 2:** .htaccess:
```apache
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
```

## Email

### Server Settings

**Hostinger Email:**

| Protocol | Server | Port |
|----------|--------|------|
| IMAP | imap.hostinger.com | 993 (SSL) |
| POP3 | pop.hostinger.com | 995 (SSL) |
| SMTP | smtp.hostinger.com | 465 (SSL) or 587 (STARTTLS) |

**Titan Email (premium add-on):**

| Protocol | Server | Port |
|----------|--------|------|
| IMAP | imap.titan.email | 993 (SSL) |
| POP3 | pop.titan.email | 995 (SSL) |
| SMTP | smtp.titan.email | 465 (SSL) or 587 (STARTTLS) |

### Email Limits Per Plan

Single: 1 total. Premium: 2/website. Business: 5/website. Cloud: 10/website.

### Features

Aliases, forwarding, catch-all, webmail (Hostinger Mail Web App). Compatible with Gmail, Outlook, Apple Mail via IMAP/SMTP.

## Security

- 24/7 server monitoring, firewall, mod_security, Suhosin PHP hardening
- WordPress malware scanner (hPanel > Security)
- DDoS protection (RTBH filtering)
- IP blocking (Advanced > IP Manager)
- Directory password protection
- Hotlink protection (Advanced > Hotlink Protection)
- Activity/access logs
- 2FA for hPanel login
- WAF on managed WordPress plans
- ISO/IEC 27001:2022 certified

## Troubleshooting

### 500 Internal Server Error

1. Rename `.htaccess` to `.htaccess_backup`
2. Increase PHP memory: Advanced > PHP Configuration > PHP Options > memory_limit
3. Disable plugins via File Manager (rename `wp-content/plugins` to `plugins_disabled`)
4. Check file permissions (755 dirs, 644 files)
5. Re-upload WordPress core files
6. Check error logs

### Database Connection Error

1. Verify wp-config.php credentials (DB_HOST is `localhost` on shared hosting)
2. Check database exists: Databases > MySQL Databases
3. Verify user privileges
4. Check if database size limit reached

### SSL Issues

- **ERR_SSL_PROTOCOL_ERROR:** Clear browser cache, check in incognito, use SSL Checker tool
- **Mixed content:** Update HTTP links to HTTPS, use Really Simple SSL plugin
- **Redirect loop:** Rename .htaccess, verify `siteurl`/`home` in wp_options are HTTPS, if Cloudflare set SSL to "Full"/"Full (Strict)"
- **Certificate not showing:** Wait for DNS propagation (up to 48h)

### Upload Size Limits

Change via: Advanced > PHP Configuration > PHP Options > `upload_max_filesize` and `post_max_size`. `post_max_size` must be larger than `upload_max_filesize`.

### Email Deliverability

- Verify SPF, DKIM, DMARC records are set correctly
- Only ONE SPF record per domain (combine if using multiple services)
- DKIM must be CNAME (not TXT)
- Wait 24h for DNS propagation
- Test with mail-tester.com or mxtoolbox.com

## Migration

### Automatic Migration Tool

**Location:** Websites > Add website > Migrate website.

**Supported:** WordPress (single-site), Joomla, cPanel/WHM. **NOT supported:** WordPress Multisite, Blogger, Shopify, Squarespace.

Provide domain name + admin credentials. Hostinger handles the rest.

**What migrates:** Files, database, .htaccess. **Does NOT migrate:** Cron jobs, DNS records, custom SSL, FTP accounts, email.

### DNS Cutover Process

1. Complete migration first (do NOT change DNS yet)
2. Preview with temporary URL / SkipDNS tool
3. Change nameservers: Domains > DNS/Nameservers > "Use Hostinger nameservers"
4. Wait 24-48h for propagation
5. Install SSL certificate
6. Verify all functionality

### Manual Migration

1. Export source DB (phpMyAdmin or mysqldump)
2. Download source files (FTP/SFTP)
3. Create new DB on Hostinger (Databases > MySQL Databases)
4. Import DB via phpMyAdmin
5. Upload files to `public_html`
6. Update wp-config.php: DB_NAME, DB_USER, DB_PASSWORD, DB_HOST (`localhost`)
7. Update `siteurl`/`home` in wp_options if domain changed
8. Follow DNS cutover process

## Programmatic Access — API and MCP

> **Everything above this section is the console.** Hostinger also has a REST API and an official
> MCP server, so most of what this skill describes as "click here in hPanel" has a scriptable
> equivalent. **Reach for the API when the task repeats, must be verifiable, or runs in a
> deploy pipeline; reach for hPanel when the task is one-off or exploratory.**

### Which surface for which task

| Task | Surface | Why |
|---|---|---|
| Purge CDN / website cache after a deploy | **API** | Must run on every deploy; a forgotten manual purge ships stale CSS to every visitor |
| Deploy a theme or plugin | **API** | Repeatable, and the response is checkable — FTP silently succeeds on partial uploads |
| DNS record changes | **API** | Reviewable as a diff; the zone editor has no history |
| Read PHP version / limits / info | **API** | Cheap to assert in CI against what the code expects |
| Create staging, first-time SSL, plan changes | **hPanel** | One-off, and the console is the documented path |
| Anything you cannot yet name the endpoint for | **hPanel** | Do not guess endpoints — see the verification rule below |

### Authentication

Token: **hPanel → Profile → Account Information → API → Generate token**, with an explicit expiry.

```bash
# ~/.secrets/<project>.env  (0600, never in a repo)
export HOSTINGER_API_TOKEN="..."
```

`HOSTINGER_API_TOKEN` is the current variable and **always takes precedence — when it is set, no
OAuth code runs at all.** `API_TOKEN` is a deprecated alias scheduled for removal; do not write it
into new config. OAuth 2.0 + PKCE is available interactively (`--login` / `--logout`, credentials at
`~/.config/hostinger-mcp/credentials.json`) but **is not supported in `--http` mode**, so any
headless or piped use needs the token.

### MCP server — verified against a real account (2026-09-29, `hostinger-api-mcp` 2.4.0)

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: tool_version
    subject: hostinger-api-mcp
    verified_against: 2.4.0
    verified_on: 2026-09-29
  - kind: date_review
    subject: hostinger-mcp-surface
    review_by: 2026-12-29
-->

```bash
npx -y -p hostinger-api-mcp@2.4.0 hostinger-hosting-mcp   # or npm install -g; engines: node >= 20
```

**What the server actually serves (enumerated over stdio, `tools/list`):** every binary — the unified
`hostinger-api-mcp` and each scoped one (`hostinger-hosting-mcp`, `-wordpress-`, `-dns-`, …) — exposes
the same **three meta-tools**, not one tool per endpoint:

| Tool | Does |
|---|---|
| `search` | Finds API operations by keyword (`{"query": "clear website cache", "limit": 5}`) and returns each one's operation name and `inputSchema`. Needs no token. |
| `execute` | Runs one operation: `{"operation": "<name from search>", "params": {…flat path/query/body params…}}` |
| `multi-execute` | Up to 20 operations in order, stopping at the first failure; `"$steps.<i>.<path>"` feeds an earlier result into a later step |

So the old "48 / 35 / 281 tools, stay under the ~100-tool host ceiling" advice is obsolete: tool count
is 3 whichever binary you run. The scoped binaries still matter as **least privilege** — each limits
which operations `search` / `execute` can reach — so a site operator still takes `hostinger-hosting-mcp`
(+ `-wordpress-`, `-dns-` as needed), not the unified server. Always `search` for the operation name
rather than hard-coding one: names changed between releases (see the table below).

Transport is stdio by default; `--http [--host H] [--port P]` streams over HTTP and **requires the
token**. A hosted remote endpoint also exists (`claude mcp add --transport http hostinger
https://mcp.hostinger.com`) — it sends your account traffic through Hostinger's endpoint rather than
your own process, which is a trust decision, not just a convenience one.

### Operations worth knowing (names as served by 2.4.0)

| Operation | Inputs | Verified on a shared-hosting account? |
|---|---|---|
| `hosting_websites_list` | — | **Yes** (2026-09-29, read-only): returned the account's websites |
| `hosting_cache_clear-website` | `username`, `domain`, `directory` | **Yes, via the REST API** (a consumer project's cron purges LiteSpeed + CDN after deploys, 2026-09-24/25). Also purges the Hostinger CDN when CDN is on — the fix for "CDN is manual-purge only". Was `hosting_clearWebsiteCacheV1` in older releases. |
| `hosting_php_info` | `username`, `domain` | Listed; not yet called |
| `hosting_deploy-wordpress-theme` | `domain`, `slug`, `themePath` (a LOCAL directory), `activate` | **Yes, with a proven rollback** (2026-09-30, on a non-production site — see the recipe below). `hosting_deploy-wordpress-plugin` (`domain`, `slug`, `pluginPath`) has the same shape; not called. |
| `hosting_deploy-static-website` · `hosting_websites_deploy-static-site-archive` | `domain`, `archivePath` / `username`, `domain`, `archive_path` | Listed; not yet called |
| `hosting_import-wordpress-website` | per `search` | Listed; "may take a while" — treat as async |

### Theme deploy with a proven rollback (verified 2026-09-30)

Run this on a **non-production** site first (a temporary `*.hostingersite.com` site on the same
account is ideal); production gets it only after the recipe has passed there.

| Step | Operation (binary) | Check |
|---|---|---|
| 0. Record the current state | `wordpress_installations_list` {`domain`} gives the install `id` (= `software`) and `username`; `wordpress_themes_list-installed` {`username`, `software`} (wordpress) | note the theme with `status: active`; fetch the homepage |
| 1. Deploy + activate | `hosting_deploy-wordpress-theme` {`domain`, `slug`, `themePath`, `activate: true`} (hosting) | returns per-file results; `list-installed` shows the new theme active; the homepage serves it |
| 2. **Roll back** | `wordpress_themes_activate` {`username`, `software`, `theme`: the recorded original} (wordpress) | `list-installed` shows the original active; the homepage serves it again |
| 3. Clean up (optional) | `wordpress_themes_uninstall` {`username`, `software`, `themes`: [slug]} (wordpress) | the slug is gone from `list-installed` |

Observed behaviour: the deploy uploads the files through a staging directory with a random suffix
(`<slug>-XXXXXXXX`) and then installs the theme under `<slug>`. Activate and uninstall answer
`"Request accepted"`, so they are ASYNCHRONOUS: re-read `list-installed` (and the page) before
treating a step as done. Deploying replaces the theme's files, so rolling back by re-activating the
previous theme only works when the new theme has a NEW slug; redeploying an existing slug overwrites
it and needs a copy of the old files to go back.

### HARD-RULE — verify the surface against the account, never against the marketing

**Hostinger's own pages disagree with each other about what the API covers.** The MCP tutorial page
describes the scope as VPS, domains, DNS and billing *only* — no shared hosting, no WordPress, no
files, no cache. The repository README described 48 hosting tools and 35 WordPress tools including
cache purge and theme deploys — and the 2.4.0 server serves neither shape: it serves three meta-tools
(above). **The server's own `tools/list` and `search` are the only authority**, and the disagreement
is the point:

- **Never tell a user a Hostinger capability exists because a docs page or a blog post said so.**
  Confirm it against *their* account and *their* plan, and say plainly when you have not.
- **Plan and product gate the surface.** `hostinger-vps-mcp` is useless on shared hosting;
  `hostinger-agency-hosting-mcp` needs an Agency plan. A tool being listed is not a tool you can call.
- **A live-looking MCP endpoint can return empty for every query.** Observed in the wild on a
  Hostinger-generated `llms.txt` advertising a store MCP that answered `[]` to everything. Absence
  of results is not proof of an empty account — it may be an unprovisioned or wrong endpoint.
  Distinguish *"queried, genuinely empty"* from *"queried, got nothing back"* before reporting either.

### Anti-patterns specific to the API

| Don't | Why |
|---|---|
| Install the unified server by default | It reaches every operation on the account; take the scoped binary for the task (least privilege) |
| Hard-code an operation name from docs or memory | Names change between releases (`hosting_clearWebsiteCacheV1` → `hosting_cache_clear-website`); `search` first |
| Put the token in `.mcp.json`, `wp-config.php` or any repo file | It is an account-wide credential. `~/.secrets/<project>.env` at 0600, referenced as `${HOSTINGER_API_TOKEN}` |
| Generate a token with no expiry | Hostinger asks for one; an immortal token is an immortal breach |
| Use `API_TOKEN` in new config | Deprecated alias, scheduled for removal |
| Assume the API replaces FTP deploys before testing a rollback | Verify you can restore the previous theme *before* making the API the deploy path |
| Rely on OAuth in a scripted context | Not supported in `--http` mode, and interactive login cannot run headless |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Change DNS before migration completes | Visitors see broken/empty site |
| Use standard SSH port 22 | Hostinger uses port 65002 |
| Create multiple SPF records | Only one SPF per domain; combine them |
| Set DKIM as TXT record | Must be CNAME on Hostinger |
| Ignore PHP memory limits per plan | Cannot exceed plan maximum regardless of wp-config |
| Skip staging for major updates | No easy rollback on shared hosting |
| Use Cloudflare "Flexible" SSL mode | Causes redirect loops with Hostinger |
| Attempt multisite migration with auto tool | Not supported; must migrate manually |
