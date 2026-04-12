---
name: wordpress-developer
description: Use when developing WordPress themes, plugins, or blocks — theme.json configuration, block themes, classic themes, child themes, plugin architecture, custom post types, taxonomies, Gutenberg block development, WordPress REST API custom endpoints, WP-CLI commands, hooks/filters system, enqueueing assets, internationalization, or writing any PHP/JS code that targets WordPress core APIs.
---

# WordPress Developer

## Overview

WordPress powers 40%+ of the web. This skill covers theme development (block and classic), plugin architecture, Gutenberg blocks, REST API, hooks system, WP-CLI, coding standards, and security patterns. All code must follow WordPress coding standards and security rules in this skill.

## Theme Development

### Block vs Classic Themes

| Feature | Block Theme (2026 Default) | Classic Theme |
|---------|---------------------------|---------------|
| Required files | `style.css` + `templates/index.html` | `style.css` + `index.php` |
| Templates | HTML with block markup | PHP files |
| Configuration | `theme.json` | `functions.php` + Customizer |
| Full Site Editing | Yes | No |
| Directory structure | `/templates/`, `/parts/`, `/patterns/` | Root PHP files |

**Use block themes** for new projects. Use classic when: legacy plugin compatibility, complex PHP-driven templates, or existing large codebases.

### theme.json (Schema Version 3)

```json
{
  "$schema": "https://schemas.wp.org/trunk/theme.json",
  "version": 3,
  "settings": {
    "appearanceTools": true,
    "useRootPaddingAwareAlignments": true,
    "color": { "palette": [{ "slug": "primary", "color": "#1a1a2e", "name": "Primary" }] },
    "typography": { "fontFamilies": [], "fontSizes": [], "fluid": true },
    "spacing": { "units": ["px", "rem", "%"] },
    "layout": { "contentSize": "840px", "wideSize": "1200px" }
  },
  "styles": {
    "color": { "background": "var(--wp--preset--color--primary)" },
    "elements": { "link": { "color": { "text": "var(--wp--preset--color--accent)" } } },
    "blocks": { "core/paragraph": { "typography": { "lineHeight": "1.8" } } }
  },
  "customTemplates": [{ "name": "full-width", "title": "Full Width", "postTypes": ["page"] }],
  "templateParts": [{ "name": "header", "title": "Header", "area": "header" }],
  "patterns": ["pattern-slug-from-directory"]
}
```

**CSS custom properties:** Presets become `var(--wp--preset--{category}--{slug})`. Custom values become `var(--wp--custom--{key})`.

### Template Hierarchy

```
Front Page:  front-page -> home / page -> index
Single Post: single-{type}-{slug} -> single-{type} -> single -> singular -> index
Page:        custom-template -> page-{slug} -> page-{id} -> page -> singular -> index
Category:    category-{slug} -> category-{id} -> category -> archive -> index
CPT Archive: archive-{post_type} -> archive -> index
Search:      search -> index
404:         404 -> index
```

### Child Themes

**Block child theme:** `style.css` (with `Template: parent-folder-name`) + `theme.json`. Override parent design tokens in child `theme.json`.

**Classic child theme — enqueue parent styles:**
```php
add_action( 'wp_enqueue_scripts', function() {
    wp_enqueue_style( 'parent-style', get_template_directory_uri() . '/style.css' );
} );
```

### functions.php

Hook `add_theme_support()` to `after_setup_theme`. Common supports: `title-tag`, `post-thumbnails`, `custom-logo`, `html5`, `editor-styles`, `responsive-embeds`, `wp-block-styles`, `align-wide`. Register nav menus with `register_nav_menus()`. Register widget areas on `widgets_init`. Prefix all functions with theme slug.

## Plugin Development

### Plugin Header

```php
<?php
/*
 * Plugin Name:       My Plugin
 * Description:       Short description.
 * Version:           1.0.0
 * Requires at least: 6.6
 * Requires PHP:      8.2
 * Author:            Author Name
 * License:           GPL v2 or later
 * Text Domain:       my-plugin
 * Requires Plugins:  woocommerce
 */
```

### Lifecycle Hooks

```php
// Activation — create tables, add options, flush rewrites
register_activation_hook( __FILE__, function() {
    myplugin_register_cpt();
    flush_rewrite_rules();
} );

// Deactivation — remove temp data, unschedule crons, do NOT delete user data
register_deactivation_hook( __FILE__, function() {
    wp_clear_scheduled_hook( 'myplugin_daily_hook' );
} );

// Uninstall — use uninstall.php (preferred over register_uninstall_hook)
```

**uninstall.php:**
```php
<?php
if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) { die; }
delete_option( 'myplugin_settings' );
$wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}myplugin_table" );
```

### Custom Post Types & Taxonomies

```php
add_action( 'init', function() {
    register_post_type( 'book', array(
        'labels'       => array( 'name' => 'Books', 'singular_name' => 'Book' ),
        'public'       => true,
        'has_archive'  => true,
        'show_in_rest' => true,  // REQUIRED for block editor
        'supports'     => array( 'title', 'editor', 'thumbnail', 'excerpt', 'custom-fields' ),
        'rewrite'      => array( 'slug' => 'books' ),
        'menu_icon'    => 'dashicons-book',
        'template'     => array( array( 'core/paragraph', array( 'placeholder' => 'Add summary...' ) ) ),
    ) );

    register_taxonomy( 'genre', 'book', array(
        'labels'            => array( 'name' => 'Genres', 'singular_name' => 'Genre' ),
        'hierarchical'      => true,  // true = categories-like, false = tags-like
        'show_in_rest'      => true,  // REQUIRED for block editor
        'show_admin_column' => true,
        'rewrite'           => array( 'slug' => 'genre' ),
    ) );
} );
```

### Settings API

```php
add_action( 'admin_init', function() {
    register_setting( 'myplugin_group', 'myplugin_option', array(
        'type'              => 'string',
        'sanitize_callback' => 'sanitize_text_field',
        'default'           => '',
    ) );
    add_settings_section( 'myplugin_section', 'Settings', null, 'myplugin-settings' );
    add_settings_field( 'myplugin_field', 'API Key', 'myplugin_field_cb', 'myplugin-settings', 'myplugin_section' );
} );
```

### Admin Menus

```php
add_action( 'admin_menu', function() {
    add_menu_page( 'My Plugin', 'My Plugin', 'manage_options', 'myplugin', 'myplugin_page_cb', 'dashicons-admin-generic', 80 );
    add_submenu_page( 'myplugin', 'Settings', 'Settings', 'manage_options', 'myplugin-settings', 'myplugin_settings_cb' );
} );
// Convenience: add_options_page() (under Settings), add_management_page() (under Tools)
```

**Standard positions:** 2=Dashboard, 5=Posts, 10=Media, 20=Pages, 25=Comments, 60=Appearance, 65=Plugins, 70=Users, 75=Tools, 80=Settings.

## Block Editor (Gutenberg)

### Scaffold & Build

```bash
npx @wordpress/create-block my-block        # Full plugin with block
wp-scripts start                             # Dev mode with watch
wp-scripts build                             # Production build
```

### block.json

```json
{
  "$schema": "https://schemas.wp.org/trunk/block.json",
  "apiVersion": 3,
  "name": "myplugin/my-block",
  "title": "My Block",
  "category": "widgets",
  "icon": "smiley",
  "description": "A custom block.",
  "keywords": ["example"],
  "attributes": {
    "content": { "type": "string", "default": "" }
  },
  "supports": { "html": false, "align": true, "color": { "background": true, "text": true } },
  "editorScript": "file:./index.js",
  "editorStyle": "file:./index.css",
  "style": "file:./style-index.css",
  "render": "file:./render.php",
  "viewScript": "file:./view.js"
}
```

Blocks registered via `block.json` get lazy-loaded assets (only enqueued when block is on page).

### Dynamic vs Static Blocks

**Static:** `save()` returns JSX stored in DB. For content that doesn't change without manual edit.
**Dynamic:** `save()` returns `null`, server renders on each request via `render` PHP file or `render_callback`. Use for: content that updates without post edit, external data, markup that should change everywhere.

### InnerBlocks

```jsx
import { InnerBlocks } from '@wordpress/block-editor';
// edit(): <InnerBlocks allowedBlocks={['core/paragraph']} template={[['core/heading']]} templateLock="all" />
// save(): <InnerBlocks.Content />
```

### Block Variations

```js
wp.blocks.registerBlockVariation( 'core/embed', {
    name: 'custom-embed',
    title: 'Custom Embed',
    attributes: { providerNameSlug: 'custom' },
    scope: [ 'inserter' ],
} );
```

## REST API

### Custom Endpoints

```php
add_action( 'rest_api_init', function() {
    register_rest_route( 'myplugin/v1', '/items/(?P<id>\d+)', array(
        'methods'             => 'GET',
        'callback'            => 'myplugin_get_item',
        'permission_callback' => '__return_true',  // REQUIRED since WP 5.5
        'args' => array(
            'id' => array(
                'required'          => true,
                'validate_callback' => function( $param ) { return is_numeric( $param ); },
                'sanitize_callback' => 'absint',
            ),
        ),
    ) );
} );

function myplugin_get_item( WP_REST_Request $request ) {
    $id = $request->get_param( 'id' );
    return new WP_REST_Response( $data, 200 );  // or WP_Error
}
```

**Auth methods:** Cookie + nonce (same-origin), Application Passwords (Basic Auth over HTTPS, WP 5.6+), OAuth 1.0a, JWT (plugin).

**Namespace format:** `vendor/v{version}` (e.g., `myplugin/v1`).

**Default endpoints:** `/wp-json/wp/v2/posts`, `/pages`, `/media`, `/comments`, `/categories`, `/tags`, `/users`, `/types`, `/taxonomies`, `/settings`, `/search`.

## Hooks System

See `hooks-reference.md` for the complete hook load order and tables.

**Actions** execute code at specific points (return nothing). **Filters** modify data and return it.

```php
add_action( 'init', 'my_function', 10, 1 );     // hook, callback, priority, args
add_filter( 'the_content', 'my_filter', 10, 1 );
remove_action( 'init', 'my_function', 10 );      // priority must match
```

**Priority:** lower = earlier. Default 10. Use 1-9 for "before default", 11+ for "after default".

### Most Critical Hooks

| Hook | Type | When/Purpose |
|------|------|-------------|
| `after_setup_theme` | Action | Theme init: `add_theme_support()`, `register_nav_menus()` |
| `init` | Action | Register CPTs, taxonomies, shortcodes. User is authenticated. |
| `wp_enqueue_scripts` | Action | Enqueue frontend scripts/styles |
| `admin_enqueue_scripts` | Action | Enqueue admin scripts (receives `$hook_suffix`) |
| `admin_init` | Action | Register settings, check capabilities |
| `admin_menu` | Action | Register admin menus/pages |
| `rest_api_init` | Action | Register REST routes |
| `save_post` | Action | After post save (receives `$post_id`, `$post`, `$update`) |
| `pre_get_posts` | Action | Modify WP_Query before execution |
| `the_content` | Filter | Filter post content before display |
| `the_title` | Filter | Filter post title |
| `body_class` | Filter | Modify body CSS classes |
| `upload_mimes` | Filter | Allowed MIME types for uploads |
| `cron_schedules` | Filter | Add custom cron intervals |

## Enqueueing Assets

```php
add_action( 'wp_enqueue_scripts', function() {
    wp_enqueue_style( 'mytheme-style', get_stylesheet_uri(), array(), '1.0.0' );
    wp_enqueue_script( 'mytheme-script', get_template_directory_uri() . '/js/app.js',
        array(), '1.0.0', array( 'strategy' => 'defer', 'in_footer' => true ) );

    wp_localize_script( 'mytheme-script', 'myData', array(
        'ajaxUrl' => admin_url( 'admin-ajax.php' ),
        'nonce'   => wp_create_nonce( 'my_nonce' ),
    ) );
} );

// Script modules (WP 6.5+):
wp_enqueue_script_module( 'myplugin-module', plugins_url( 'js/module.js', __FILE__ ) );
```

**Script loading strategies (WP 6.3+):** `'strategy' => 'defer'` or `'strategy' => 'async'` in args array.

## Database Access ($wpdb)

```php
global $wpdb;

// ALWAYS use prepare() for user input — placeholders: %d (int), %s (string), %f (float), %i (identifier)
$results = $wpdb->get_results( $wpdb->prepare(
    "SELECT * FROM {$wpdb->posts} WHERE post_author = %d AND post_status = %s", $author_id, 'publish'
) );

$wpdb->insert( $wpdb->prefix . 'custom_table', array( 'name' => $name ), array( '%s' ) );
$wpdb->update( $wpdb->prefix . 'custom_table', array( 'value' => $val ), array( 'id' => $id ), array( '%s' ), array( '%d' ) );
$wpdb->delete( $wpdb->prefix . 'custom_table', array( 'id' => $id ), array( '%d' ) );
```

## WP-CLI Quick Reference

See `wp-cli-reference.md` for full command list.

| Command | Purpose |
|---------|---------|
| `wp scaffold plugin <slug>` | Generate plugin boilerplate |
| `wp scaffold post-type <slug>` | Generate CPT registration code |
| `wp scaffold block <slug>` | Generate block boilerplate |
| `wp scaffold child-theme <slug>` | Generate child theme |
| `wp core download / install / update` | Core lifecycle |
| `wp plugin install/activate/deactivate/update` | Plugin management |
| `wp theme install/activate/update` | Theme management |
| `wp db export/import/optimize/query` | Database operations |
| `wp search-replace <old> <new> --precise --all-tables` | Migration search-replace |
| `wp rewrite flush` | Flush permalink rules |
| `wp cache flush` | Flush object cache |
| `wp eval / eval-file / shell` | Execute PHP |

### Custom WP-CLI Commands

```php
if ( defined( 'WP_CLI' ) && WP_CLI ) {
    WP_CLI::add_command( 'myplugin', 'MyPlugin_CLI' );
}
class MyPlugin_CLI {
    /**
     * Syncs data.
     * ## OPTIONS
     * [--dry-run] : Preview without changes.
     * @when after_wp_load
     */
    public function sync( $args, $assoc_args ) {
        $dry = \WP_CLI\Utils\get_flag_value( $assoc_args, 'dry-run', false );
        WP_CLI::success( 'Done.' );
    }
}
```

## Internationalization (i18n)

| Function | Purpose |
|----------|---------|
| `__( $text, $domain )` | Return translation |
| `_e( $text, $domain )` | Echo translation |
| `_x( $text, $context, $domain )` | Translation with context |
| `_n( $singular, $plural, $count, $domain )` | Pluralization |
| `esc_html__()` / `esc_html_e()` | Translate + HTML escape |
| `esc_attr__()` / `esc_attr_e()` | Translate + attribute escape |

Load text domain: `load_plugin_textdomain( 'my-plugin', false, dirname( plugin_basename( __FILE__ ) ) . '/languages' );`

## Security (MANDATORY)

### Input Sanitization

| Context | Function |
|---------|----------|
| Plain text | `sanitize_text_field()` |
| Textarea | `sanitize_textarea_field()` |
| Email | `sanitize_email()` |
| URL (for DB) | `esc_url_raw()` |
| Integer | `absint()` or `intval()` |
| HTML (limited) | `wp_kses_post()` |
| Filename | `sanitize_file_name()` |
| CSS class | `sanitize_html_class()` |

### Output Escaping

| Context | Function |
|---------|----------|
| HTML content | `esc_html()` |
| HTML attributes | `esc_attr()` |
| URLs in href/src | `esc_url()` |
| JavaScript strings | `esc_js()` |
| Inside textarea | `esc_textarea()` |

**Principle:** Sanitize early (input), escape late (output). Escape at the point of output, not earlier.

### Nonces

```php
// Form: wp_nonce_field( 'my_action', 'my_nonce' );
// Verify: wp_verify_nonce( $_POST['my_nonce'], 'my_action' )
// URL: wp_nonce_url( $url, 'my_action' )
// AJAX: check_ajax_referer( 'my_action', 'security' );
```

### Capability Checks

```php
if ( ! current_user_can( 'edit_posts' ) ) { wp_die( 'Unauthorized' ); }
// Post-specific: current_user_can( 'edit_post', $post_id )
// REST API: 'permission_callback' => function() { return current_user_can( 'manage_options' ); }
```

## Coding Standards

- **Naming:** functions/variables: `lowercase_underscores`, classes: `Capitalized_Words`, constants: `UPPERCASE`, files: `lowercase-hyphens.php`
- **Formatting:** Tabs for indentation, Yoda conditions (`'value' === $var`), `array()` long syntax, always use braces, `elseif` not `else if`
- **Quotes:** Single default, double when interpolating
- **Hooks:** Dynamic hooks use interpolation: `do_action( "{$status}_{$type}" )`

## Version Requirements (2026)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| PHP | 7.2.24+ | **8.2+** |
| WordPress | 6.6 | Latest stable |
| MySQL | 5.7 | 8.0+ |
| MariaDB | 10.4 | 10.11+ |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Echo unsanitized input | XSS vulnerability |
| Skip nonce verification | CSRF vulnerability |
| Query DB without `$wpdb->prepare()` | SQL injection |
| Skip `permission_callback` in REST routes | Open API endpoints |
| Use `extract()` or `eval()` on user data | Code injection |
| Hardcode strings without i18n | Not translatable |
| Register CPTs outside `init` hook | Timing issues |
| Omit `show_in_rest` on CPTs/taxonomies | Block editor won't work |
| Use `include` instead of `require_once` | Silent failures, double execution |
| Call `add_role()` on every page load | DB write on every request |
