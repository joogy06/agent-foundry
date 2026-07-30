---
name: ubuntu-web-servers
description: Use when configuring web servers on Ubuntu 24.04 LTS — Nginx, Apache, Caddy setup and tuning, virtual hosts, SSL/TLS certificates, Let's Encrypt/certbot, reverse proxy patterns, load balancing, HTTP/2/3, security headers, and performance optimization. Part of the ubuntu-* skill family.
family: ubuntu
applies_when: os_family == debian
---

# Ubuntu Server 24.04 LTS — Web Server Administration

Child of `ubuntu-server-admin`. Covers Nginx, Apache, and Caddy on Ubuntu 24.04.4 LTS (Noble Numbat) — installation, virtual hosts, reverse proxying, SSL/TLS, security headers, and performance tuning.

<HARD-RULE>
Always verify the Ubuntu version before applying advice. Package names, config paths, and module availability differ between releases.
```bash
lsb_release -a   # or cat /etc/os-release
```
</HARD-RULE>

<HARD-RULE>
Never expose a web server to the internet without TLS. Use Let's Encrypt (free) or a proper CA certificate. Self-signed certs are acceptable only for internal/development use.
</HARD-RULE>

<HARD-RULE>
After every config change, test the configuration before reloading. A bad reload can take a production site offline.
- Nginx: `sudo nginx -t`
- Apache: `sudo apachectl configtest`
- Caddy: `caddy validate --config /etc/caddy/Caddyfile`
</HARD-RULE>

---

## 1. Nginx

### Installation

```bash
# Install from Ubuntu repos (stable, well-tested)
sudo apt update && sudo apt install nginx -y
sudo systemctl enable --now nginx

# Verify
sudo nginx -t
systemctl status nginx
curl -I http://localhost
```

Key paths on 24.04:
- Main config: `/etc/nginx/nginx.conf`
- Site configs: `/etc/nginx/sites-available/` and `/etc/nginx/sites-enabled/`
- Default log: `/var/log/nginx/access.log`, `/var/log/nginx/error.log`
- Web root: `/var/www/html`

### Server Block (Virtual Host)

Create `/etc/nginx/sites-available/example.com`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;
    root /var/www/example.com/html;
    index index.html index.htm;

    access_log /var/log/nginx/example.com.access.log;
    error_log  /var/log/nginx/example.com.error.log;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

```bash
# Enable site and reload
sudo ln -s /etc/nginx/sites-available/example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Reverse Proxy

```nginx
server {
    listen 80;
    server_name app.example.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";   # WebSocket support
        proxy_read_timeout 90s;
        proxy_buffering off;
    }
}
```

### Load Balancing

```nginx
upstream backend_pool {
    least_conn;                         # or: ip_hash, round-robin (default)
    server 10.0.1.10:8080 weight=3;
    server 10.0.1.11:8080;
    server 10.0.1.12:8080 backup;       # used only when others are down
}

server {
    listen 80;
    server_name lb.example.com;

    location / {
        proxy_pass http://backend_pool;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### SSL Termination (with certbot certificate)

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name example.com www.example.com;
    root /var/www/example.com/html;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # Modern TLS config
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # OCSP stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/example.com/chain.pem;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # Security headers (see section 5)
    include /etc/nginx/snippets/security-headers.conf;

    location / {
        try_files $uri $uri/ =404;
    }
}

# HTTP -> HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;
}
```

### Worker Tuning

Edit `/etc/nginx/nginx.conf`:

```nginx
worker_processes auto;              # one per CPU core
worker_rlimit_nofile 65536;

events {
    worker_connections 4096;        # per worker (default 768 is too low)
    multi_accept on;
    use epoll;
}

http {
    keepalive_timeout 65;
    keepalive_requests 1000;
    client_max_body_size 64m;       # max upload size
    server_tokens off;              # hide Nginx version
}
```

### Rate Limiting

```nginx
# Define zone in http block (/etc/nginx/nginx.conf)
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;
}

# Apply in server/location blocks
location /api/ {
    limit_req zone=api burst=20 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8080;
}

location /login {
    limit_req zone=login burst=3 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8080;
}
```

### Caching (Static Assets and Proxy Cache)

```nginx
# Static asset caching — inside a server block
location ~* \.(jpg|jpeg|png|gif|ico|svg|css|js|woff2|woff|ttf)$ {
    expires 30d;
    add_header Cache-Control "public, no-transform";
    access_log off;
}

# Proxy cache — define in http block
http {
    proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=app_cache:10m
                     max_size=1g inactive=60m use_temp_path=off;
}

# Use in location block
location / {
    proxy_cache app_cache;
    proxy_cache_valid 200 302 10m;
    proxy_cache_valid 404 1m;
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503;
    add_header X-Cache-Status $upstream_cache_status;
    proxy_pass http://127.0.0.1:8080;
}
```

### Access and Error Logs

```nginx
# Custom log format
http {
    log_format detailed '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent" '
                        'rt=$request_time urt=$upstream_response_time';

    access_log /var/log/nginx/access.log detailed;
}

# Per-site logging
server {
    access_log /var/log/nginx/example.com.access.log detailed;
    error_log  /var/log/nginx/example.com.error.log warn;
}

# Disable logging for health checks
location /health {
    access_log off;
    return 200 "ok";
}
```

---

## 2. Apache

### Installation

```bash
sudo apt update && sudo apt install apache2 -y
sudo systemctl enable --now apache2

# Verify
sudo apachectl configtest
systemctl status apache2
curl -I http://localhost
```

Key paths on 24.04:
- Main config: `/etc/apache2/apache2.conf`
- Site configs: `/etc/apache2/sites-available/` and `/etc/apache2/sites-enabled/`
- Module configs: `/etc/apache2/mods-available/` and `/etc/apache2/mods-enabled/`
- Logs: `/var/log/apache2/access.log`, `/var/log/apache2/error.log`

### Enable/Disable Modules and Sites

```bash
# Modules
sudo a2enmod rewrite proxy proxy_http ssl headers expires
sudo a2dismod autoindex status
sudo systemctl restart apache2

# Sites
sudo a2ensite example.com.conf
sudo a2dissite 000-default.conf
sudo apachectl configtest && sudo systemctl reload apache2
```

### Virtual Host

Create `/etc/apache2/sites-available/example.com.conf`:

```apache
<VirtualHost *:80>
    ServerName example.com
    ServerAlias www.example.com
    DocumentRoot /var/www/example.com/html
    ErrorLog ${APACHE_LOG_DIR}/example.com.error.log
    CustomLog ${APACHE_LOG_DIR}/example.com.access.log combined

    <Directory /var/www/example.com/html>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
```

### Reverse Proxy (mod_proxy)

```bash
sudo a2enmod proxy proxy_http proxy_wstunnel
```

```apache
<VirtualHost *:80>
    ServerName app.example.com

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3000/
    ProxyPassReverse / http://127.0.0.1:3000/

    # WebSocket support
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) ws://127.0.0.1:3000/$1 [P,L]

    RequestHeader set X-Forwarded-Proto "http"
</VirtualHost>
```

### mod_rewrite Common Patterns

```apache
# Force HTTPS
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# Remove www
RewriteCond %{HTTP_HOST} ^www\.(.+)$ [NC]
RewriteRule ^ https://%1%{REQUEST_URI} [L,R=301]

# Clean URLs (e.g., PHP frameworks)
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^ index.php [L]
```

### .htaccess Patterns

```apache
# Block access to sensitive files
<FilesMatch "\.(env|git|htpasswd|ini|log|bak|sql)$">
    Require all denied
</FilesMatch>

# Custom error pages
ErrorDocument 404 /404.html
ErrorDocument 500 /500.html

# Password-protect a directory
AuthType Basic
AuthName "Restricted Area"
AuthUserFile /etc/apache2/.htpasswd
Require valid-user
```

```bash
# Create htpasswd file
sudo apt install apache2-utils
sudo htpasswd -c /etc/apache2/.htpasswd admin
```

### MPM Tuning (Event vs Prefork)

```bash
# Check current MPM
apachectl -V | grep MPM

# Switch to event MPM (preferred for performance; incompatible with mod_php)
sudo a2dismod mpm_prefork
sudo a2enmod mpm_event
sudo systemctl restart apache2
```

Tune `/etc/apache2/mods-available/mpm_event.conf`:

```apache
<IfModule mpm_event_module>
    StartServers             3
    MinSpareThreads         75
    MaxSpareThreads        250
    ThreadsPerChild         25
    MaxRequestWorkers      400
    MaxConnectionsPerChild 10000
</IfModule>
```

Use prefork only when `mod_php` is required (legacy apps). For modern PHP, use `php-fpm` with event MPM.

### mod_security Basics

```bash
sudo apt install libapache2-mod-security2
sudo a2enmod security2
sudo systemctl restart apache2

# Enable OWASP Core Rule Set
sudo cp /etc/modsecurity/modsecurity.conf-recommended /etc/modsecurity/modsecurity.conf
sudo sed -i 's/SecRuleEngine DetectionOnly/SecRuleEngine On/' /etc/modsecurity/modsecurity.conf
sudo systemctl restart apache2
```

---

## 3. Caddy

### Installation

```bash
# Official Caddy repo (24.04)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy -y
sudo systemctl enable --now caddy
```

Key paths:
- Config: `/etc/caddy/Caddyfile`
- Data (certs): `/var/lib/caddy/.local/share/caddy`
- Logs: `journalctl -u caddy`

### Caddyfile Syntax — File Server

```caddyfile
example.com {
    root * /var/www/example.com/html
    file_server
    encode gzip zstd

    log {
        output file /var/log/caddy/example.com.access.log
    }
}
```

Caddy obtains and renews TLS certificates automatically via Let's Encrypt when a public domain name is used. No manual certbot setup needed.

### Reverse Proxy

```caddyfile
app.example.com {
    reverse_proxy 127.0.0.1:3000 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
    }
}
```

### Multi-Site with Security Headers

```caddyfile
(security_headers) {
    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
        -Server
    }
}

example.com {
    import security_headers
    root * /var/www/example.com
    file_server
}

api.example.com {
    import security_headers
    reverse_proxy 127.0.0.1:8080
}
```

```bash
# Validate and reload
caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

---

## 4. SSL/TLS with Let's Encrypt (certbot)

### Installation

```bash
# Certbot via snap (recommended on 24.04)
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

### Obtain Certificate — Nginx Plugin

```bash
# Automatic: modifies Nginx config to add SSL
sudo certbot --nginx -d example.com -d www.example.com

# Certificate-only (no config changes)
sudo certbot certonly --nginx -d example.com -d www.example.com
```

### Obtain Certificate — Apache Plugin

```bash
sudo certbot --apache -d example.com -d www.example.com
```

### Obtain Certificate — Standalone (No Web Server Running)

```bash
# Temporarily binds to port 80 — stop any running web server first
sudo certbot certonly --standalone -d example.com -d www.example.com
```

### Obtain Certificate — Webroot (Web Server Keeps Running)

```bash
sudo certbot certonly --webroot -w /var/www/example.com/html -d example.com -d www.example.com
```

For the webroot method, Nginx needs to serve `.well-known/acme-challenge/`:

```nginx
location /.well-known/acme-challenge/ {
    root /var/www/example.com/html;
}
```

### Auto-Renewal

Certbot's snap package installs a systemd timer automatically:

```bash
# Verify timer is active
systemctl list-timers | grep certbot

# Manual renewal test
sudo certbot renew --dry-run

# Post-renewal hook to reload web server
# Create /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
#!/bin/bash
systemctl reload nginx
```

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

### Self-Signed Certificate (Internal / Dev Use)

```bash
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/selfsigned.key \
  -out /etc/ssl/certs/selfsigned.crt \
  -subj "/C=US/ST=Local/L=Local/O=Dev/CN=internal.example.com"

# Generate DH params (optional, for older TLS configs)
sudo openssl dhparam -out /etc/ssl/certs/dhparam.pem 2048
```

### TLS 1.2/1.3 Cipher Configuration (Nginx)

```nginx
# Modern config (TLS 1.3 only — highest security, drops older clients)
ssl_protocols TLSv1.3;
ssl_prefer_server_ciphers off;

# Intermediate config (TLS 1.2 + 1.3 — recommended for most sites)
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
ssl_prefer_server_ciphers off;

# Session resumption
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:10m;
ssl_session_tickets off;

# OCSP stapling
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/letsencrypt/live/example.com/chain.pem;
resolver 1.1.1.1 8.8.8.8 valid=300s;
```

---

## 5. Security Headers

### Nginx — Reusable Snippet

Create `/etc/nginx/snippets/security-headers.conf`:

```nginx
# HSTS — enforce HTTPS for 2 years, include subdomains
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

# Prevent MIME-type sniffing
add_header X-Content-Type-Options "nosniff" always;

# Clickjacking protection
add_header X-Frame-Options "SAMEORIGIN" always;

# Referrer policy
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# Content Security Policy (adjust per application)
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none';" always;

# Permissions policy (disable unused browser features)
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;
```

Include in any server block:

```nginx
server {
    # ...
    include /etc/nginx/snippets/security-headers.conf;
}
```

### Apache

```apache
<IfModule mod_headers.c>
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';"
    Header always set Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()"
</IfModule>
```

```bash
sudo a2enmod headers
sudo apachectl configtest && sudo systemctl reload apache2
```

<HARD-RULE>
HSTS with `preload` is irreversible in practice. Once your domain is on the HSTS preload list, browsers will refuse plain HTTP for years. Only add `preload` when you are certain the entire domain (including all subdomains) will remain HTTPS permanently.
</HARD-RULE>

### Verify Headers

```bash
curl -I https://example.com
# Or use: https://securityheaders.com
```

---

## 6. Performance

### Gzip Compression (Nginx)

Add to `/etc/nginx/nginx.conf` in the `http` block:

```nginx
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 5;
gzip_min_length 256;
gzip_types
    text/plain
    text/css
    text/javascript
    application/javascript
    application/json
    application/xml
    application/rss+xml
    image/svg+xml
    font/woff2;
```

### Brotli Compression (Nginx)

```bash
sudo apt install libnginx-mod-brotli
```

```nginx
brotli on;
brotli_comp_level 6;
brotli_types
    text/plain
    text/css
    text/javascript
    application/javascript
    application/json
    application/xml
    image/svg+xml
    font/woff2;
```

### Gzip Compression (Apache)

```bash
sudo a2enmod deflate
```

```apache
<IfModule mod_deflate.c>
    AddOutputFilterByType DEFLATE text/html text/plain text/css
    AddOutputFilterByType DEFLATE application/javascript application/json
    AddOutputFilterByType DEFLATE application/xml image/svg+xml
</IfModule>
```

### Static File Caching (Apache)

```bash
sudo a2enmod expires
```

```apache
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresByType image/jpeg "access plus 30 days"
    ExpiresByType image/png "access plus 30 days"
    ExpiresByType image/svg+xml "access plus 30 days"
    ExpiresByType text/css "access plus 7 days"
    ExpiresByType application/javascript "access plus 7 days"
    ExpiresByType font/woff2 "access plus 30 days"
</IfModule>
```

### Keepalive Tuning (Nginx)

```nginx
http {
    keepalive_timeout 65;           # how long idle connections stay open
    keepalive_requests 1000;        # max requests per connection

    # Upstream keepalive (for reverse proxy to backends)
    upstream backend {
        server 127.0.0.1:8080;
        keepalive 32;               # persistent connections to backend
    }

    server {
        location / {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";   # required for upstream keepalive
        }
    }
}
```

### Connection Limits (Nginx)

```nginx
# Define zone in http block
http {
    limit_conn_zone $binary_remote_addr zone=addr:10m;
    limit_conn_zone $server_name zone=server:10m;
}

# Apply in server block
server {
    limit_conn addr 100;            # max 100 connections per IP
    limit_conn server 10000;        # max 10k connections per vhost
    limit_conn_status 503;
}
```

### Quick Performance Test

```bash
# Install Apache Bench (bundled with apache2-utils)
sudo apt install apache2-utils

# 1000 requests, 50 concurrent
ab -n 1000 -c 50 https://example.com/

# Or use wrk for more realistic benchmarks
sudo apt install wrk
wrk -t4 -c100 -d30s https://example.com/
```

---

## UFW Rules for Web Servers

```bash
# Allow HTTP + HTTPS
sudo ufw allow 'Nginx Full'        # or: sudo ufw allow 80,443/tcp

# If running Apache instead
sudo ufw allow 'Apache Full'

# Caddy uses the same ports
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Verify
sudo ufw status verbose
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using self-signed certificates in production | Browser warnings scare users; search engines penalize; no trust chain validation | Use Let's Encrypt with certbot for free auto-renewing certificates; set up cron for renewal |
| Not enabling HTTP/2 on Nginx | HTTP/1.1 multiplexing limitations cause slower page loads; modern browsers expect HTTP/2 | Add `http2` to listen directive; requires SSL; verify with `curl --http2` |
| Serving application files through PHP/Python directly instead of Nginx static serving | Application processes tied up serving CSS/JS/images; 10x slower than web server direct serving | Configure Nginx `location /static/` to serve files directly; proxy only dynamic requests to application |
| Default Nginx worker_connections (512) on production servers | Connection limit hit during traffic spikes; 502 errors for users; server appears down despite low CPU | Set `worker_connections` to 2048-4096; set `worker_processes auto`; tune based on expected concurrent connections |
| No security headers on responses | Vulnerable to XSS, clickjacking, MIME sniffing; fails security scans | Add headers: X-Content-Type-Options, X-Frame-Options, Content-Security-Policy, Strict-Transport-Security |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (users, SSH, firewall, disks) | `ubuntu-server-admin` |
| Databases (PostgreSQL, MySQL, Redis) | `ubuntu-databases` |
| Docker / containers | `ubuntu-docker-host` |
| Monitoring (Prometheus, Grafana) | `ubuntu-monitoring` |
| DNS, DHCP, NTP | `ubuntu-network-infra` |
