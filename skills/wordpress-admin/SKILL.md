---
name: wordpress-admin
description: Use when administering WordPress sites — wp-config.php configuration, security hardening, performance optimization (object cache, page cache, CDN), user roles and capabilities, database maintenance and cleanup, backup and migration (WP-CLI search-replace), debugging (WP_DEBUG, error logs, white screen of death), multisite network setup, cron system configuration, auto-updates, or troubleshooting WordPress errors.
disambiguation: The WordPress APPLICATION on any host — wp-config, hardening, caching, users, plugins. Hostinger's own control panel and platform features are hostinger-hosting.
---

# WordPress Admin

## Overview

WordPress site administration covering wp-config.php, security hardening, performance tuning, user management, database maintenance, backups, migration, debugging, multisite, cron, and updates. For theme/plugin/block development, see `wordpress-developer`. For WooCommerce store code, see `woocommerce-developer`.

## wp-config.php Critical Settings

### Database & URLs

```php
define('DB_NAME', 'database_name');
define('DB_USER', 'database_user');
define('DB_PASSWORD', 'database_password');
define('DB_HOST', 'localhost');           // Can be IP, socket, or host:port
define('DB_CHARSET', 'utf8mb4');
$table_prefix = 'wp_';                   // Change for security (e.g., 'xk9f_')

define('WP_SITEURL', 'https://example.com');  // Overrides DB value
define('WP_HOME', 'https://example.com');     // Overrides DB value
```

### Debug Settings

```php
// Production:
define('WP_DEBUG', false);

// Development/Staging:
define('WP_DEBUG', true);
define('WP_DEBUG_LOG', true);             // Logs to wp-content/debug.log
define('WP_DEBUG_DISPLAY', false);        // Don't show errors on screen
define('SCRIPT_DEBUG', true);             // Use unminified core JS/CSS
define('SAVEQUERIES', true);              // Log queries to $wpdb->queries (NEVER on production)
```

### Memory Limits

```php
define('WP_MEMORY_LIMIT', '256M');        // Frontend (default: 40M)
define('WP_MAX_MEMORY_LIMIT', '512M');    // Admin/backend (default: 256M)
```

Cannot exceed server's php.ini `memory_limit`.

### File System

```php
define('FS_METHOD', 'direct');            // Skip FTP prompt
define('DISALLOW_FILE_EDIT', true);       // Disable theme/plugin editor in admin
define('DISALLOW_FILE_MODS', true);       // Disable ALL file mods (editor + install/update)
```

### Security Keys & Salts

```php
// Generate at: https://api.wordpress.org/secret-key/1.1/salt/
// Or: wp config shuffle-salts
// Changing salts forces all users to re-login
define('AUTH_KEY',         'unique-phrase');
define('SECURE_AUTH_KEY',  'unique-phrase');
define('LOGGED_IN_KEY',    'unique-phrase');
define('NONCE_KEY',        'unique-phrase');
define('AUTH_SALT',        'unique-phrase');
define('SECURE_AUTH_SALT', 'unique-phrase');
define('LOGGED_IN_SALT',   'unique-phrase');
define('NONCE_SALT',       'unique-phrase');
```

### Auto-Updates

```php
define('AUTOMATIC_UPDATER_DISABLED', true);  // Kill ALL auto-updates
define('WP_AUTO_UPDATE_CORE', 'minor');      // true (all), false (none), 'minor' (default)
```

### Cron

```php
define('DISABLE_WP_CRON', true);          // Disable pseudo-cron (use server cron instead)
define('ALTERNATE_WP_CRON', true);        // Alternative cron method for problematic hosts
```

Server cron replacement:
```bash
*/5 * * * * cd /path/to/wordpress && wp cron event run --due-now > /dev/null 2>&1
```

### SSL & HTTPS

```php
define('FORCE_SSL_ADMIN', true);
```

### Post Revisions & Trash

```php
define('WP_POST_REVISIONS', 5);           // Limit revisions (false = disable, true = unlimited)
define('AUTOSAVE_INTERVAL', 300);         // Seconds (default: 60)
define('EMPTY_TRASH_DAYS', 15);           // Default: 30. 0 = disable trash
```

### Caching

```php
define('WP_CACHE', true);                 // Required by most caching plugins

// Redis object cache:
define('WP_REDIS_HOST', '127.0.0.1');
define('WP_REDIS_PORT', 6379);
define('WP_REDIS_PREFIX', 'wp_site1_');
```

### Multisite

```php
define('WP_ALLOW_MULTISITE', true);       // Step 1: enables Network Setup screen
// After setup, add:
define('MULTISITE', true);
define('SUBDOMAIN_INSTALL', false);       // false = subdirectory, true = subdomain
define('DOMAIN_CURRENT_SITE', 'example.com');
define('PATH_CURRENT_SITE', '/');
```

## Security Hardening

### File Permissions

| Path | Permission |
|------|-----------|
| Directories | 755 |
| Files | 644 |
| wp-config.php | 440 or 400 |

```bash
find /path/to/wordpress -type d -exec chmod 755 {} \;
find /path/to/wordpress -type f -exec chmod 644 {} \;
chmod 400 /path/to/wordpress/wp-config.php
```

### .htaccess Security (Apache)

```apache
# Protect wp-config.php
<Files wp-config.php>
Order Allow,Deny
Deny from all
</Files>

# Disable directory listing
Options -Indexes

# Block PHP execution in uploads
<Directory /path/to/wp-content/uploads>
<Files "*.php">
Order Allow,Deny
Deny from all
</Files>
</Directory>

# Block sensitive files
<FilesMatch "^(readme\.html|license\.txt|xmlrpc\.php)$">
Order Allow,Deny
Deny from all
</FilesMatch>

# Block author enumeration
RewriteEngine On
RewriteCond %{QUERY_STRING} ^author=([0-9]+) [NC]
RewriteRule .* - [F,L]
```

### Nginx Security

```nginx
location ~* wp-config\.php { deny all; }
location ~* /wp-content/uploads/.*\.php$ { deny all; }
location = /xmlrpc.php { deny all; access_log off; log_not_found off; }
location ~* (readme\.html|license\.txt) { deny all; }
if ($args ~* "author=\d+") { return 403; }
autoindex off;
```

### Disable XML-RPC

```php
add_filter('xmlrpc_enabled', '__return_false');
add_filter('wp_headers', function($h) { unset($h['X-Pingback']); return $h; });
remove_action('wp_head', 'rsd_link');
```

### Hide WordPress Version

```php
remove_action('wp_head', 'wp_generator');
add_filter('the_generator', '__return_empty_string');
add_filter('style_loader_src', function($src) { return $src ? esc_url(remove_query_arg('ver', $src)) : false; }, 9999);
add_filter('script_loader_src', function($src) { return $src ? esc_url(remove_query_arg('ver', $src)) : false; }, 9999);
```

### Security Headers

```php
add_action('send_headers', function() {
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: SAMEORIGIN');
    header('Referrer-Policy: strict-origin-when-cross-origin');
    header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
    header('Strict-Transport-Security: max-age=31536000; includeSubDomains; preload');
});
```

### Restrict REST API

```php
add_filter('rest_authentication_errors', function($result) {
    if (true === $result || is_wp_error($result)) return $result;
    if (!is_user_logged_in()) {
        return new WP_Error('rest_not_logged_in', 'Authentication required.', array('status' => 401));
    }
    return $result;
});
```

**Warning:** Breaks Contact Form 7, oEmbed, some themes. More targeted: restrict only `/wp/v2/users`.

## Performance Optimization

### Object Caching (Redis/Memcached)

Drop-in file: `wp-content/object-cache.php`. Use Redis Object Cache plugin.

```php
// Core cache functions:
wp_cache_set($key, $data, $group, $expire);
wp_cache_get($key, $group);
wp_cache_delete($key, $group);
wp_cache_flush();
```

```bash
wp redis status / enable / disable / flush
```

### Page Caching

Full-page caching serves static HTML. Requires `define('WP_CACHE', true);` in wp-config. Drop-in: `wp-content/advanced-cache.php`. Options: WP Super Cache, WP Rocket, server-level (Varnish, Nginx FastCGI, LiteSpeed).

### Database Cleanup

```sql
-- Orphaned postmeta:
DELETE pm FROM wp_postmeta pm LEFT JOIN wp_posts p ON p.ID = pm.post_id WHERE p.ID IS NULL;

-- All revisions:
DELETE FROM wp_posts WHERE post_type = 'revision';

-- Auto-drafts:
DELETE FROM wp_posts WHERE post_status = 'auto-draft';

-- Spam comments:
DELETE FROM wp_comments WHERE comment_approved = 'spam';

-- Find large autoloaded options (keep total under 1MB):
SELECT option_name, LENGTH(option_value) AS size FROM wp_options WHERE autoload = 'yes' ORDER BY size DESC LIMIT 20;

-- Total autoload size:
SELECT SUM(LENGTH(option_value)) AS autoload_size FROM wp_options WHERE autoload = 'yes';
```

```bash
wp transient delete --expired    # Clean expired transients
wp db optimize                   # OPTIMIZE all tables
```

### Image Optimization

- WordPress 5.8+ supports WebP natively, 6.5+ supports AVIF
- Native lazy loading (`loading="lazy"`) added automatically since WP 5.5
- Custom sizes: `add_image_size('custom-thumb', 400, 300, true);`
- Regenerate: `wp media regenerate --yes`

### Heartbeat API Control

```php
add_filter('heartbeat_settings', function($s) { $s['interval'] = 60; return $s; }); // 15-120 seconds
// Disable on frontend:
add_action('init', function() { if (!is_admin()) wp_deregister_script('heartbeat'); }, 1);
```

### Script Optimization

```php
// Defer/async (WP 6.3+):
wp_enqueue_script('handle', $src, array(), '1.0', array('strategy' => 'defer', 'in_footer' => true));

// Conditionally dequeue unused plugin assets:
add_action('wp_enqueue_scripts', function() {
    if (!is_page('contact')) { wp_dequeue_style('contact-form-7'); wp_dequeue_script('contact-form-7'); }
}, 100);
```

### GZIP/Brotli (.htaccess)

```apache
<IfModule mod_deflate.c>
    AddOutputFilterByType DEFLATE text/html text/plain text/xml text/css text/javascript
    AddOutputFilterByType DEFLATE application/javascript application/json application/xml
</IfModule>
```

### Browser Caching (.htaccess)

```apache
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresByType image/jpeg "access plus 1 year"
    ExpiresByType image/png "access plus 1 year"
    ExpiresByType image/webp "access plus 1 year"
    ExpiresByType text/css "access plus 1 month"
    ExpiresByType application/javascript "access plus 1 month"
    ExpiresByType font/woff2 "access plus 1 year"
    ExpiresByType text/html "access plus 0 seconds"
</IfModule>
```

## User Roles & Capabilities

### Default Roles

| Role | Key Capabilities |
|------|-----------------|
| **Administrator** | All capabilities (manage_options, install_plugins, edit_users, etc.) |
| **Editor** | Manage all content (edit_others_posts, manage_categories, moderate_comments) |
| **Author** | Publish own posts (publish_posts, upload_files, delete_published_posts) |
| **Contributor** | Write drafts (edit_posts, delete_posts) — cannot publish or upload |
| **Subscriber** | Read only (read) |
| **Super Admin** | Multisite: all caps + manage_network, manage_sites, manage_network_* |

### Custom Roles

```php
// Add (only call once — on plugin activation):
add_role('content_manager', 'Content Manager', array(
    'read' => true, 'edit_posts' => true, 'edit_others_posts' => true,
    'publish_posts' => true, 'upload_files' => true, 'manage_categories' => true,
));

// Modify existing role:
$role = get_role('editor');
$role->add_cap('manage_options');
$role->remove_cap('manage_options');

// Per-user:
$user = new WP_User($user_id);
$user->add_cap('manage_options');
```

```bash
wp role create content_manager "Content Manager"
wp cap add content_manager edit_posts publish_posts upload_files
wp user set-role user123 editor
wp user add-role user123 author   # Multiple roles supported
wp user list-caps user123
```

## Backup & Migration

### Backup

```bash
# Database:
wp db export backup-$(date +%Y%m%d).sql

# Files:
tar -czf site-backup-$(date +%Y%m%d).tar.gz /path/to/wordpress/

# Content only:
tar -czf content-backup.tar.gz /path/to/wordpress/wp-content/
```

### Migration (Search-Replace)

**ALWAYS use WP-CLI** — handles serialized data correctly. NEVER use raw SQL search-replace.

```bash
# Dry run first:
wp search-replace 'https://old-domain.com' 'https://new-domain.com' --dry-run --precise --all-tables

# Execute:
wp search-replace 'https://old-domain.com' 'https://new-domain.com' --precise --all-tables

# Export to file instead of modifying in-place:
wp search-replace 'old.com' 'new.com' --export=migrated.sql --precise --all-tables
```

### Migration Checklist

1. Back up source (database + files)
2. Export: `wp db export`
3. Copy files to new server
4. Create new DB and user
5. Import: `wp db import`
6. Search-replace: `wp search-replace 'old-url' 'new-url' --precise --all-tables`
7. Update wp-config.php (DB creds, salts)
8. Fix permissions (755 dirs, 644 files)
9. Flush permalinks: `wp rewrite flush`
10. Flush caches: `wp cache flush`
11. Test all functionality
12. Update DNS

## Debugging

### Debug Log

Default location: `wp-content/debug.log`

```php
error_log('Debug: ' . print_r($data, true));  // Write to debug.log
```

Protect in .htaccess:
```apache
<Files debug.log>
Order Allow,Deny
Deny from all
</Files>
```

### White Screen of Death (WSOD)

1. Enable WP_DEBUG in wp-config.php
2. Increase memory: `define('WP_MEMORY_LIMIT', '256M');`
3. Deactivate plugins: `wp plugin deactivate --all`
4. Switch to default theme: `wp theme activate twentytwentyfour`
5. Check PHP error log
6. Verify core files: `wp core verify-checksums`
7. WP 5.2+ has recovery mode — check email for recovery link

### 500 Internal Server Error

1. Check `wp-content/debug.log`
2. Rename `.htaccess` to test rewrite rules
3. Increase PHP memory
4. Deactivate plugins
5. Check PHP error log

### Database Connection Error

1. Verify DB credentials in wp-config.php
2. Test: `mysql -u dbuser -p -h localhost dbname`
3. Check MySQL is running: `systemctl status mysql`
4. Repair: `define('WP_ALLOW_REPAIR', true);` then visit `/wp-admin/maint/repair.php` (remove after!)

### Stuck Maintenance Mode

Delete `.maintenance` file in WordPress root.

### Useful Debug Commands

```bash
wp core verify-checksums                    # Check core integrity
wp plugin verify-checksums --all            # Check plugin integrity
wp option get siteurl                       # Verify site URL
wp option get home                          # Verify home URL
wp cron test                                # Test cron functionality
wp eval 'phpinfo();' | grep error_log       # Find PHP error log path
```

## Cron System

### Scheduling

```php
// Recurring:
if (!wp_next_scheduled('my_daily_hook')) {
    wp_schedule_event(time(), 'daily', 'my_daily_hook');
}
add_action('my_daily_hook', 'my_function');

// One-time:
wp_schedule_single_event(time() + 3600, 'my_one_time_hook');

// Unschedule:
wp_clear_scheduled_hook('my_daily_hook');

// Custom interval:
add_filter('cron_schedules', function($s) {
    $s['every_5_min'] = array('interval' => 300, 'display' => 'Every 5 Minutes');
    return $s;
});
```

**Built-in schedules:** `hourly` (3600s), `twicedaily` (43200s), `daily` (86400s), `weekly` (604800s).

### Server Cron (Recommended for Production)

```bash
# Disable WP pseudo-cron:
define('DISABLE_WP_CRON', true);

# Add to crontab:
*/5 * * * * cd /path/to/wordpress && /usr/local/bin/wp cron event run --due-now > /dev/null 2>&1
```

## Multisite

### Setup Types

- **Subdirectory** (example.com/site2): Works on existing installs, no wildcard DNS needed
- **Subdomain** (site2.example.com): Requires wildcard DNS (`*.example.com`) and wildcard SSL

Cannot switch between types after setup.

### Key Points

- Network Admin manages: Sites, Users, Themes, Plugins, Settings
- Network-activated plugins apply to all sites
- Per-site admins cannot install plugins/themes
- **Must-use plugins** (`wp-content/mu-plugins/`): Always active, cannot be deactivated
- `sunrise.php`: Loaded early for domain mapping (requires `define('SUNRISE', true);`)

```bash
wp site list                                        # List sites
wp site create --slug=newsite --title="New Site"    # Create site
wp --url=site2.example.com plugin list              # Run on specific site
wp plugin activate myplugin --network               # Network activate
```

## Auto-Update Configuration

```php
// Granular filter control:
add_filter('allow_major_auto_core_updates', '__return_true');     // Enable major core updates
add_filter('auto_update_plugin', '__return_true');                // Enable all plugin auto-updates
add_filter('auto_update_theme', '__return_true');                 // Enable all theme auto-updates

// Selective plugin auto-updates:
add_filter('auto_update_plugin', function($update, $item) {
    return in_array($item->slug, array('akismet', 'wordfence'), true);
}, 10, 2);
```

```bash
wp plugin auto-updates enable akismet wordfence
wp plugin auto-updates disable contact-form-7
wp theme auto-updates enable flavor
```

### Update Best Practices

1. Always back up before updating
2. Test on staging first
3. Update order: core -> plugins -> themes
4. One plugin at a time (easier debugging)
5. Check PHP compatibility before major core updates
6. Monitor error logs after updating

## WordPress Table Structure

| Table | Purpose |
|-------|---------|
| `wp_posts` | All content: posts, pages, CPTs, revisions, nav menus, attachments |
| `wp_postmeta` | Post metadata (custom fields) |
| `wp_options` | Site settings, plugin settings, widgets |
| `wp_users` | User accounts |
| `wp_usermeta` | User metadata (roles, capabilities, preferences) |
| `wp_terms` | Taxonomy terms |
| `wp_term_taxonomy` | Links terms to taxonomies |
| `wp_term_relationships` | Links posts to terms |
| `wp_termmeta` | Term metadata |
| `wp_comments` | Comments |
| `wp_commentmeta` | Comment metadata |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Leave WP_DEBUG true on production | Exposes errors to visitors |
| Use raw SQL for search-replace | Breaks serialized data |
| Skip backups before updates | No recovery path |
| Leave `WP_ALLOW_REPAIR` enabled | Anyone can access repair page |
| Set 777 permissions | Full access to everyone — major security risk |
| Keep unused plugins installed | Attack surface, even when deactivated |
| Ignore autoloaded options bloat | Slows every page load |
| Use WP pseudo-cron on high-traffic sites | Adds latency to random visitor requests |
| Edit core files directly | Lost on next update |
| Use same DB prefix on multiple installs | Shared DB = shared vulnerabilities |
