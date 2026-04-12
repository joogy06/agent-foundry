# WP-CLI Command Reference

## Installation

```bash
curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
chmod +x wp-cli.phar && sudo mv wp-cli.phar /usr/local/bin/wp
wp cli update  # Self-update
```

## Core

```bash
wp core download                                    # Download WP core
wp core install --url=X --title=X --admin_user=X --admin_password=X --admin_email=X
wp core update                                      # Update to latest
wp core update --version=6.8.1 --force              # Specific version
wp core update-db                                   # Run DB upgrade after core update
wp core version                                     # Show WP version
wp core verify-checksums                            # Verify core file integrity
wp core is-installed                                # Check if installed
```

## Plugins

```bash
wp plugin list                                      # List all plugins
wp plugin list --status=active --format=table       # Active plugins only
wp plugin install <slug> --activate                 # Install and activate
wp plugin activate <slug>                           # Activate
wp plugin deactivate <slug>                         # Deactivate
wp plugin deactivate --all                          # Deactivate all (emergency)
wp plugin delete <slug>                             # Delete
wp plugin update --all                              # Update all
wp plugin update --all --dry-run                    # Preview updates
wp plugin verify-checksums --all                    # Verify integrity (wp.org plugins)
wp plugin auto-updates enable <slug>                # Enable auto-updates
wp plugin auto-updates status                       # Check auto-update status
```

## Themes

```bash
wp theme list                                       # List all themes
wp theme install <slug> --activate                  # Install and activate
wp theme activate <slug>                            # Activate
wp theme update --all                               # Update all
wp theme delete <slug>                              # Delete
```

## Database

```bash
wp db export backup.sql                             # Export database
wp db export --tables=wp_posts,wp_postmeta dump.sql # Export specific tables
wp db import backup.sql                             # Import database
wp db query "SELECT..."                             # Run arbitrary SQL
wp db search <string>                               # Search DB content
wp db optimize                                      # OPTIMIZE all tables
wp db repair                                        # REPAIR all tables
wp db size --tables                                 # Per-table sizes
wp db tables                                        # List all tables
wp db check                                         # Check table integrity
wp db prefix                                        # Show table prefix
```

## Search-Replace (Migration)

```bash
wp search-replace 'https://old.com' 'https://new.com' --dry-run --precise --all-tables
wp search-replace 'https://old.com' 'https://new.com' --precise --all-tables
wp search-replace 'old.com' 'new.com' --export=migrated.sql --precise --all-tables
```

**Key flags:** `--precise` (handles serialized data), `--all-tables`, `--dry-run`, `--export=file.sql`.

## Posts & Content

```bash
wp post list --post_type=page --format=table        # List pages
wp post create --post_title="X" --post_status=publish --post_type=post
wp post update <id> --post_title="New Title"        # Update post
wp post delete <id> --force                         # Permanent delete
wp post generate --count=10                         # Generate test posts
wp post meta get <id> <key>                         # Get meta
wp post meta update <id> <key> <value>              # Update meta
```

## Users

```bash
wp user list                                        # List users
wp user list --role=administrator                   # List admins
wp user create bob bob@example.com --role=editor --user_pass=X
wp user update <id> --user_pass=newpassword         # Change password
wp user update <id> --role=editor                   # Change role
wp user delete <id> --reassign=1                    # Delete, reassign content
wp user add-cap <id> manage_options                 # Add capability
wp user remove-cap <id> manage_options              # Remove capability
wp user list-caps <id>                              # List capabilities
wp super-admin list                                 # List super admins (multisite)
wp super-admin add <username>                       # Grant super admin
```

## Options

```bash
wp option get <key>                                 # Get option value
wp option update <key> <value>                      # Update option
wp option delete <key>                              # Delete option
wp option list --search="*transient*"               # Search options
```

## Cache & Transients

```bash
wp cache flush                                      # Flush object cache
wp transient delete --expired                       # Delete expired transients
wp transient delete --all                           # Delete all transients
```

## Rewrites

```bash
wp rewrite flush                                    # Regenerate rewrite rules
wp rewrite structure '/%postname%/'                 # Set permalink structure
wp rewrite list --format=table                      # List current rules
```

## Cron

```bash
wp cron event list                                  # List all scheduled events
wp cron event run --due-now                         # Run all due events
wp cron event run <hook>                            # Run specific hook
wp cron event delete <hook>                         # Delete scheduled event
wp cron schedule list                               # List available schedules
wp cron test                                        # Test WP-Cron spawning
```

## Scaffold

```bash
wp scaffold plugin <slug>                           # Generate plugin boilerplate
wp scaffold post-type <slug> --plugin=myplugin      # Generate CPT code
wp scaffold taxonomy <slug> --plugin=myplugin       # Generate taxonomy code
wp scaffold child-theme <slug> --parent_theme=flavor
wp scaffold block <slug> --plugin=myplugin          # Generate block code
wp scaffold _s <theme-slug>                         # Generate starter theme
```

## Config

```bash
wp config set WP_DEBUG true --raw                   # Set constant in wp-config.php
wp config get WP_DEBUG                              # Read constant
wp config list                                      # List all constants
wp config shuffle-salts                             # Regenerate security salts
```

## Maintenance & Misc

```bash
wp maintenance-mode activate                        # Enable maintenance mode
wp maintenance-mode deactivate                      # Disable
wp eval 'phpinfo();'                                # Execute PHP inline
wp eval-file script.php                             # Execute PHP file
wp shell                                            # Interactive PHP shell
wp export --dir=/path/                              # WXR XML export
wp import file.xml --authors=create                 # WXR import
wp language core update                             # Update translations
wp media regenerate --yes                           # Regenerate thumbnails
wp comment delete $(wp comment list --status=spam --format=ids) --force  # Delete spam

# Multisite
wp site list                                        # List all sites
wp site create --slug=newsite --title="New Site"    # Create site
wp --url=site2.example.com plugin list              # Run on specific site
wp plugin activate myplugin --network               # Network activate
```

## Output Helpers (for custom commands)

```
WP_CLI::log()       — standard output
WP_CLI::success()   — green success message
WP_CLI::warning()   — yellow warning
WP_CLI::error()     — red error (exits by default)
WP_CLI::line()      — raw line output
WP_CLI::debug()     — only shown with --debug flag
```
