# WordPress Hooks Reference

## Front-End Load Order

```
1.  muplugins_loaded        — after must-use plugins load
2.  plugins_loaded          — after all active plugins load
3.  setup_theme             — before theme init
4.  after_setup_theme       — first theme hook (add_theme_support, register_nav_menus)
5.  init                    — primary init (register CPTs, taxonomies, shortcodes; user authenticated)
6.  widgets_init            — register sidebars/widget areas
7.  wp_loaded               — WordPress fully initialized
8.  parse_request           — modify HTTP request
9.  send_headers            — customize HTTP headers
10. pre_get_posts           — modify WP_Query before execution
11. template_redirect       — before template selection (use for redirects)
12. wp_enqueue_scripts      — enqueue frontend scripts/styles
13. wp_head                 — output in <head>
14. the_content (filter)    — filter post content
15. loop_start / loop_end   — bracket the Loop
16. wp_footer               — output before </body>
17. shutdown                — last hook before PHP terminates
```

## Admin Load Order

```
1.  plugins_loaded
2.  setup_theme / after_setup_theme
3.  init
4.  admin_init              — register settings, check capabilities
5.  admin_menu              — register admin menus/pages
6.  current_screen          — identify active admin page
7.  load-{$page_hook}       — page-specific logic
8.  admin_enqueue_scripts   — enqueue admin scripts (receives $hook_suffix)
9.  admin_notices           — display admin notifications
10. admin_footer
11. shutdown
```

## Content & Data Hooks

| Hook | Type | When |
|------|------|------|
| `save_post` | Action | After post save (ID, post, update flag) |
| `save_post_{$post_type}` | Action | After specific post type save |
| `wp_insert_post` | Action | After post insert/update |
| `before_delete_post` | Action | Before permanent post deletion |
| `delete_post` | Action | After permanent post deletion |
| `wp_trash_post` / `untrash_post` | Action | Trash/restore |
| `transition_post_status` | Action | Any status change (new, old, post) |
| `{$new_status}_{$post_type}` | Action | Specific status + type combo |
| `add_meta_boxes` | Action | Register meta boxes |
| `updated_option` | Action | After any option update |
| `update_option_{$option}` | Action | After specific option update |
| `user_register` | Action | New user created |
| `wp_login` / `wp_logout` | Action | Auth events |
| `comment_post` | Action | After comment creation |
| `rest_api_init` | Action | Register REST routes |

## Useful Filters

| Filter | Purpose | Key Args |
|--------|---------|----------|
| `the_title` | Modify post title | title, post_id |
| `the_content` | Modify post content | content |
| `the_excerpt` | Modify post excerpt | excerpt |
| `body_class` | Add/remove body CSS classes | classes |
| `post_class` | Add/remove post CSS classes | classes, class, post_id |
| `wp_nav_menu_items` | Modify nav menu HTML | items, args |
| `upload_mimes` | Allowed MIME types | mimes |
| `cron_schedules` | Add custom cron intervals | schedules |
| `manage_{$post_type}_posts_columns` | Admin list table columns | columns |
| `pre_get_posts` | Modify main query | WP_Query |
| `posts_where` / `posts_join` | Custom SQL in queries | where/join, query |
| `wp_mail` | Modify outgoing email | args array |
| `login_redirect` | Redirect after login | redirect_to, requested, user |
| `template_include` | Override template selection | template path |
| `wp_handle_upload_prefilter` | Validate uploads before save | file array |
| `the_password_form` | Custom password-protected form | output |
| `excerpt_length` | Excerpt word count | length |
| `excerpt_more` | Excerpt "read more" text | more_string |
