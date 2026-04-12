---
name: rhel-web-servers
description: Use when configuring web servers on RHEL 9 (and AlmaLinux/Rocky 9) — Nginx, Apache (httpd), Caddy setup and tuning, virtual hosts, SSL/TLS certificates, Let's Encrypt/certbot, reverse proxy patterns, load balancing, HTTP/2/3, security headers, SELinux booleans for web services, and performance optimization. Part of the rhel-* skill family.
---

# Red Hat Enterprise Linux 9 — Web Server Administration

Child of `rhel-server-admin`. Covers Nginx, Apache (httpd), and Caddy on RHEL 9.x (and compatible: AlmaLinux 9, Rocky Linux 9, Oracle Linux 9) — installation, virtual hosts, reverse proxying, SSL/TLS, SELinux integration, security headers, and performance tuning.

<HARD-RULE>
Always verify the RHEL version before applying advice. Package names, config paths, and available modules differ between major releases.
```bash
cat /etc/redhat-release
cat /etc/os-release
uname -r
```
</HARD-RULE>

<HARD-RULE>
Never expose a web server to the internet without TLS. Use Let's Encrypt (free) or a proper CA certificate. Self-signed certs are acceptable only for internal/development use.
</HARD-RULE>

<HARD-RULE>
After every config change, test the configuration before reloading. A bad reload can take a production site offline.
- Apache (httpd): `sudo httpd -t`
- Nginx: `sudo nginx -t`
- Caddy: `caddy validate --config /etc/caddy/Caddyfile`
</HARD-RULE>

<HARD-RULE>
SELinux is enforcing by default on RHEL 9. Never set SELinux to permissive or disabled on production systems to "fix" a web server issue. Instead, use the correct booleans, file contexts, and port labels. Check `audit2why` and `audit2allow` to diagnose denials.
</HARD-RULE>

---

## 1. Nginx

### Installation

```bash
# Option A: From EPEL (stable, community-maintained)
sudo dnf install epel-release -y
sudo dnf install nginx -y

# Option B: Official Nginx repo (mainline — latest features)
sudo tee /etc/yum.repos.d/nginx.repo <<'EOF'
[nginx-mainline]
name=nginx mainline repo
baseurl=https://nginx.org/packages/mainline/rhel/$releasever/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
EOF
sudo dnf install nginx -y

# Enable and start
sudo systemctl enable --now nginx

# Verify
sudo nginx -t
systemctl status nginx
curl -I http://localhost
```

Key paths on RHEL 9:
- Main config: `/etc/nginx/nginx.conf`
- Site configs: `/etc/nginx/conf.d/*.conf` (no sites-available/sites-enabled pattern)
- Default log: `/var/log/nginx/access.log`, `/var/log/nginx/error.log`
- Web root: `/usr/share/nginx/html` (default), use `/var/www/html` for custom sites
- PID file: `/run/nginx.pid`

### Firewall

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
sudo firewall-cmd --list-services
```

### Server Block (Virtual Host)

Create `/etc/nginx/conf.d/example.com.conf`:

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
# Create web root and set SELinux context
sudo mkdir -p /var/www/example.com/html
sudo chown -R nginx:nginx /var/www/example.com
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/example.com(/.*)?"
sudo restorecon -Rv /var/www/example.com

# Test and reload
sudo nginx -t && sudo systemctl reload nginx
```

### SELinux for Nginx

```bash
# Key booleans — check current state
getsebool -a | grep httpd

# Allow Nginx to make outbound network connections (reverse proxy)
sudo setsebool -P httpd_can_network_connect on

# Allow Nginx to relay to upstream servers (load balancing)
sudo setsebool -P httpd_can_network_relay on

# Allow Nginx to connect to databases
sudo setsebool -P httpd_can_network_connect_db on

# Allow Nginx to send email (contact forms)
sudo setsebool -P httpd_can_sendmail on

# Allow Nginx to read user home directories (~user URLs)
sudo setsebool -P httpd_enable_homedirs on

# Non-standard port — add SELinux port label
sudo semanage port -a -t http_port_t -p tcp 8443
sudo semanage port -l | grep http_port_t

# File context for custom web root
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/www(/.*)?"
sudo restorecon -Rv /srv/www

# Writable directory (uploads, caches)
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/www/example.com/uploads(/.*)?"
sudo restorecon -Rv /var/www/example.com/uploads

# Diagnose SELinux denials
sudo ausearch -m avc -ts recent
sudo ausearch -m avc -ts recent | audit2why
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

Requires SELinux boolean: `sudo setsebool -P httpd_can_network_connect on`

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

    # Modern TLS config (see section 4 for cipher details)
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
    include /etc/nginx/conf.d/security-headers.inc;

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
    worker_connections 4096;        # per worker (default 1024 is too low for busy sites)
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

---

## 2. Apache (httpd)

### Installation

```bash
sudo dnf install httpd mod_ssl -y
sudo systemctl enable --now httpd

# Verify
sudo httpd -t
systemctl status httpd
curl -I http://localhost
```

Key paths on RHEL 9:
- Main config: `/etc/httpd/conf/httpd.conf`
- Site/module configs: `/etc/httpd/conf.d/*.conf` (no a2ensite/a2enmod on RHEL)
- Module directory: `/etc/httpd/conf.modules.d/`
- Logs: `/var/log/httpd/access_log`, `/var/log/httpd/error_log`
- Web root: `/var/www/html`
- SSL config: `/etc/httpd/conf.d/ssl.conf` (installed by mod_ssl)

### Firewall

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### Virtual Host

Create `/etc/httpd/conf.d/example.com.conf`:

```apache
<VirtualHost *:80>
    ServerName example.com
    ServerAlias www.example.com
    DocumentRoot /var/www/example.com/html
    ErrorLog /var/log/httpd/example.com.error_log
    CustomLog /var/log/httpd/example.com.access_log combined

    <Directory /var/www/example.com/html>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
```

```bash
# Create web root and set SELinux context
sudo mkdir -p /var/www/example.com/html
sudo chown -R apache:apache /var/www/example.com
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/example.com(/.*)?"
sudo restorecon -Rv /var/www/example.com

# Test and reload
sudo httpd -t && sudo systemctl reload httpd
```

### SELinux Booleans for httpd

```bash
# List all httpd-related booleans
getsebool -a | grep httpd

# Allow httpd to connect to network backends (reverse proxy, APIs)
sudo setsebool -P httpd_can_network_connect on

# Allow httpd to relay connections (load balancing)
sudo setsebool -P httpd_can_network_relay on

# Allow httpd to connect to databases
sudo setsebool -P httpd_can_network_connect_db on

# Allow httpd to send mail
sudo setsebool -P httpd_can_sendmail on

# Allow httpd to execute CGI scripts
sudo setsebool -P httpd_enable_cgi on

# Allow httpd to read home directories
sudo setsebool -P httpd_enable_homedirs on

# File contexts
# Read-only web content
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/myapp(/.*)?"
# Read-write content (uploads, caches, sessions)
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/www/example.com/uploads(/.*)?"
# CGI scripts
sudo semanage fcontext -a -t httpd_sys_script_exec_t "/var/www/cgi-bin(/.*)?"
sudo restorecon -Rv /srv/myapp /var/www/example.com/uploads /var/www/cgi-bin

# Diagnose denials
sudo ausearch -m avc -ts recent | audit2why
sudo sealert -a /var/log/audit/audit.log     # requires setroubleshoot-server
```

### Reverse Proxy (mod_proxy)

```bash
# mod_proxy is included in base httpd on RHEL 9
# Verify modules are loaded
httpd -M | grep proxy
```

Create `/etc/httpd/conf.d/app-proxy.conf`:

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

Requires SELinux boolean: `sudo setsebool -P httpd_can_network_connect on`

### mod_rewrite Common Patterns

```apache
# Force HTTPS
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# Remove www
RewriteCond %{HTTP_HOST} ^www\.(.+)$ [NC]
RewriteRule ^ https://%1%{REQUEST_URI} [L,R=301]

# Clean URLs (PHP frameworks)
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^ index.php [L]
```

### MPM Event Tuning

```bash
# Check current MPM (event is default on RHEL 9)
httpd -V | grep MPM

# MPM is set in /etc/httpd/conf.modules.d/00-mpm.conf
# event is loaded by default; prefork needed only for mod_php (legacy)
```

Edit `/etc/httpd/conf.modules.d/00-mpm.conf` if switching, then tune in `/etc/httpd/conf.d/mpm-tuning.conf`:

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

For modern PHP, use `php-fpm` with event MPM instead of mod_php with prefork:

```bash
sudo dnf install php-fpm -y
sudo systemctl enable --now php-fpm
# php-fpm listens on /run/php-fpm/www.sock by default on RHEL 9
```

### mod_security with OWASP CRS

```bash
sudo dnf install mod_security mod_security_crs -y

# Enable the engine
sudo sed -i 's/SecRuleEngine DetectionOnly/SecRuleEngine On/' /etc/httpd/conf.d/mod_security.conf

# Test and restart
sudo httpd -t && sudo systemctl restart httpd

# Check logs for false positives
sudo tail -f /var/log/httpd/modsec_audit.log
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
AuthUserFile /etc/httpd/.htpasswd
Require valid-user
```

```bash
# Create htpasswd file
sudo dnf install httpd-tools -y
sudo htpasswd -c /etc/httpd/.htpasswd admin
```

---

## 3. Caddy

### Installation

```bash
# Option A: Official Caddy COPR repo
sudo dnf install 'dnf-command(copr)' -y
sudo dnf copr enable @caddy/caddy -y
sudo dnf install caddy -y

# Option B: Direct binary from GitHub
curl -o /tmp/caddy.tar.gz -L "https://github.com/caddyserver/caddy/releases/latest/download/caddy_2_linux_amd64.tar.gz"
sudo tar -xzf /tmp/caddy.tar.gz -C /usr/local/bin caddy
sudo chmod +x /usr/local/bin/caddy
# Use the COPR-provided systemd unit or create one

# Enable and start
sudo systemctl enable --now caddy
```

Key paths:
- Config: `/etc/caddy/Caddyfile`
- Data (certs): `/var/lib/caddy/.local/share/caddy`
- Logs: `journalctl -u caddy`

### Firewall

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### SELinux for Caddy

```bash
# Caddy needs network connect for upstream proxying and ACME cert fetching
sudo setsebool -P httpd_can_network_connect on

# If Caddy serves files from a custom directory
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/caddy(/.*)?"
sudo restorecon -Rv /srv/caddy

# If Caddy binds to non-standard ports
sudo semanage port -a -t http_port_t -p tcp 8443

# Caddy's data directory needs correct context
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/lib/caddy(/.*)?"
sudo restorecon -Rv /var/lib/caddy
```

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

# Load balancing across multiple backends
lb.example.com {
    reverse_proxy 10.0.1.10:8080 10.0.1.11:8080 10.0.1.12:8080 {
        lb_policy least_conn
        health_uri /health
        health_interval 10s
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
# Option A: From EPEL (recommended on RHEL 9)
sudo dnf install epel-release -y
sudo dnf install certbot -y

# Install web server plugins
sudo dnf install python3-certbot-nginx -y    # Nginx plugin
sudo dnf install python3-certbot-apache -y   # httpd plugin

# Option B: Via snap (alternative)
sudo dnf install snapd -y
sudo systemctl enable --now snapd
sudo ln -s /var/lib/snapd/snap /snap
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

### Obtain Certificate — Apache (httpd) Plugin

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

```bash
# Certbot from EPEL creates a systemd timer
sudo systemctl enable --now certbot-renew.timer
systemctl list-timers | grep certbot

# Manual renewal test
sudo certbot renew --dry-run

# Post-renewal hook to reload web server
# Create /etc/letsencrypt/renewal-hooks/deploy/reload-webserver.sh
```

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-webserver.sh <<'EOF'
#!/bin/bash
# Reload whichever web server is active
systemctl is-active --quiet nginx && systemctl reload nginx
systemctl is-active --quiet httpd && systemctl reload httpd
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-webserver.sh
```

### Self-Signed Certificate (Internal / Dev Use)

```bash
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/pki/tls/private/selfsigned.key \
  -out /etc/pki/tls/certs/selfsigned.crt \
  -subj "/C=US/ST=Local/L=Local/O=Dev/CN=internal.example.com"

# Generate DH params (optional, for older TLS configs)
sudo openssl dhparam -out /etc/pki/tls/certs/dhparam.pem 2048
```

Note: RHEL 9 uses `/etc/pki/tls/` for certificates, not `/etc/ssl/`.

### TLS 1.2/1.3 Cipher Configuration

RHEL 9 uses system-wide crypto-policies to manage TLS defaults:

```bash
# Check current crypto policy
update-crypto-policies --show         # DEFAULT on fresh installs

# Set stricter policy (TLS 1.2+ only, strong ciphers)
sudo update-crypto-policies --set FUTURE

# Available policies: LEGACY, DEFAULT, FIPS, FUTURE
# Custom sub-policies
sudo update-crypto-policies --set DEFAULT:NO-SHA1

# View what a policy enforces
update-crypto-policies --show
cat /etc/crypto-policies/back-ends/opensslcnf.config
```

Manual TLS config in Nginx (overrides crypto-policy for this service):

```nginx
# Intermediate config (TLS 1.2 + 1.3 — recommended for most sites)
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
ssl_prefer_server_ciphers off;

# Session resumption
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:10m;
ssl_session_tickets off;
```

Manual TLS config in Apache (`/etc/httpd/conf.d/ssl.conf`):

```apache
SSLProtocol -all +TLSv1.2 +TLSv1.3
SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
SSLHonorCipherOrder off
```

---

## 5. Security Headers

### Nginx — Reusable Include

Create `/etc/nginx/conf.d/security-headers.inc`:

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
    include /etc/nginx/conf.d/security-headers.inc;
}
```

### Apache (httpd)

Create `/etc/httpd/conf.d/security-headers.conf`:

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
# mod_headers is loaded by default on RHEL 9 httpd
httpd -M | grep headers
sudo httpd -t && sudo systemctl reload httpd
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
# Brotli module is available from EPEL or must be compiled as a dynamic module
# if using official nginx repo. Check availability:
sudo dnf list available | grep nginx-mod-brotli

# If available:
sudo dnf install nginx-mod-brotli -y
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

### Gzip Compression (Apache httpd)

```bash
# mod_deflate is loaded by default on RHEL 9
httpd -M | grep deflate
```

Create `/etc/httpd/conf.d/compression.conf`:

```apache
<IfModule mod_deflate.c>
    AddOutputFilterByType DEFLATE text/html text/plain text/css
    AddOutputFilterByType DEFLATE application/javascript application/json
    AddOutputFilterByType DEFLATE application/xml image/svg+xml
</IfModule>
```

### Static File Caching (Apache httpd)

Create `/etc/httpd/conf.d/caching.conf`:

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

```bash
# mod_expires is loaded by default on RHEL 9
httpd -M | grep expires
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

### Quick Performance Test

```bash
# Install Apache Bench (bundled with httpd-tools)
sudo dnf install httpd-tools -y

# 1000 requests, 50 concurrent
ab -n 1000 -c 50 https://example.com/

# Or use wrk (build from source on RHEL 9)
sudo dnf install git gcc make -y
git clone https://github.com/wg/wrk.git /tmp/wrk
cd /tmp/wrk && make && sudo cp wrk /usr/local/bin/
wrk -t4 -c100 -d30s https://example.com/
```

---

## Firewall Rules Summary

```bash
# Allow HTTP + HTTPS
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# Custom port (e.g., 8443)
sudo firewall-cmd --permanent --add-port=8443/tcp
sudo firewall-cmd --reload

# Restrict to specific source IP
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/24" port protocol="tcp" port="8080" accept'
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-all
```

---

## SELinux Quick Reference for Web Services

```bash
# Check if SELinux is enforcing
getenforce

# List all httpd booleans and their state
getsebool -a | grep httpd

# Common booleans (use -P to persist across reboots)
sudo setsebool -P httpd_can_network_connect on      # outbound connections
sudo setsebool -P httpd_can_network_relay on         # proxy/relay traffic
sudo setsebool -P httpd_can_network_connect_db on    # database connections
sudo setsebool -P httpd_can_sendmail on              # send email
sudo setsebool -P httpd_enable_cgi on                # CGI execution
sudo setsebool -P httpd_unified on                   # unified httpd handling

# Port labels — allow non-standard ports
sudo semanage port -l | grep http_port_t
sudo semanage port -a -t http_port_t -p tcp 8443
sudo semanage port -a -t http_port_t -p tcp 9090

# File contexts
sudo semanage fcontext -a -t httpd_sys_content_t "/custom/path(/.*)?"
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/custom/uploads(/.*)?"
sudo restorecon -Rv /custom/path /custom/uploads

# Troubleshoot denials
sudo dnf install setroubleshoot-server -y
sudo ausearch -m avc -ts recent
sudo ausearch -m avc -ts recent | audit2why
sudo sealert -a /var/log/audit/audit.log
```

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running Nginx/Apache with default SSL configuration | Weak ciphers, old TLS versions (1.0/1.1); fails SSL Labs scan; vulnerable to BEAST/POODLE attacks | Configure TLS 1.2+ only; use Mozilla SSL Configuration Generator for cipher suite; test with SSL Labs |
| Not setting SELinux booleans for web server features | SELinux blocks legitimate traffic (proxy, network connections, home directories); admins disable SELinux instead of fixing it | Use `setsebool -P` for required booleans (httpd_can_network_connect, etc.); never disable SELinux |
| Hardcoding server IPs in virtual host configurations | Server migration or IP change requires editing every vhost; missed edits cause downtime | Use server names and DNS; bind to 0.0.0.0 or specific interface names; let DNS handle IP resolution |
| No rate limiting or connection limits on public-facing servers | DDoS and brute-force attacks overwhelm the server; legitimate users cannot connect | Configure `limit_req`/`limit_conn` (Nginx) or `mod_ratelimit`/`mod_evasive` (Apache) on all public endpoints |
| Serving static files through application server (Flask, Spring) instead of web server | Application server processes tied up serving images/CSS; 10x slower than Nginx static file serving | Configure Nginx/Apache to serve static files directly; proxy only dynamic requests to the application server |

---

## Related Skills

| Workload | Skill |
|---|---|
| Core system admin (users, SSH, firewall, disks, SELinux) | `rhel-server-admin` |
| Databases (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Docker / containers | `rhel-docker-host` |
| File sharing (NFS, Samba, storage) | `rhel-file-storage` |
| Monitoring (Prometheus, Grafana, logging) | `rhel-monitoring` |
| DNS, DHCP, NTP, networking | `rhel-network-infra` |
| NVIDIA GPU / Ollama | `rhel-ollama-nvidia` |
