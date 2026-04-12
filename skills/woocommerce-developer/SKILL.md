---
name: woocommerce-developer
description: Use when building or modifying WooCommerce themes, customizing checkout or product pages, working with WooCommerce hooks and templates, integrating payment gateways, using the WooCommerce REST API, or writing any PHP code that touches WooCommerce. Includes mandatory security patterns.
---

# WooCommerce Developer

## Overview

WooCommerce powers 36%+ of all online stores. This skill covers template customization, hooks/filters, REST API, checkout (block and classic), performance, analytics integration, and **mandatory security patterns**. Every code pattern must follow the security rules in this skill — no exceptions.

## Template System

### Override Hierarchy

WooCommerce templates live in `wp-content/plugins/woocommerce/templates/`. Override by copying to your theme:

```
yourtheme/woocommerce/single-product.php          → Single product page
yourtheme/woocommerce/archive-product.php          → Shop/category pages
yourtheme/woocommerce/cart/cart.php                 → Cart page
yourtheme/woocommerce/checkout/form-checkout.php    → Classic checkout
yourtheme/woocommerce/content-product.php           → Product card in loops
```

**Rules:**
- Copy the template file, don't modify the plugin original
- Keep the `@version` docblock comment — WooCommerce warns when templates are outdated
- Prefer hooks over template overrides when possible (less maintenance)
- **Block checkout** (default since WC 8.3+) does NOT use `form-checkout.php` — it uses the block editor

### Block vs Classic

| Feature | Block-Based (New Default) | Classic (Shortcode) |
|---------|--------------------------|---------------------|
| Cart | `<!-- wp:woocommerce/cart -->` | `[woocommerce_cart]` |
| Checkout | `<!-- wp:woocommerce/checkout -->` | `[woocommerce_checkout]` |
| Customization | Slot/Fill API, Inner Blocks, Additional Fields API | PHP hooks and filters |
| Template file | Not used (block renders) | `woocommerce/checkout/form-checkout.php` |

**Recommendation:** New stores should use block checkout. Existing stores with heavy classic customization may keep classic until migration is practical.

## Key Hooks

See `hooks-reference.md` for the complete hook map. Most important:

### Product Page

| Hook | Location | Priority |
|------|----------|----------|
| `woocommerce_before_single_product_summary` | Before title/price area | 10 |
| `woocommerce_single_product_summary` | Title, price, excerpt, add-to-cart | 5-60 |
| `woocommerce_after_single_product_summary` | Tabs, related products | 10-15 |
| `woocommerce_product_tabs` (filter) | Add/remove/reorder product tabs | 10 |

### Checkout

| Hook | Location |
|------|----------|
| `woocommerce_before_checkout_form` | Before entire form |
| `woocommerce_checkout_before_customer_details` | Before billing/shipping fields |
| `woocommerce_checkout_fields` (filter) | Add/remove/reorder checkout fields |
| `woocommerce_checkout_order_processed` | After order created, before payment |

### Order Processing

| Hook | When |
|------|------|
| `woocommerce_new_order` | Order created |
| `woocommerce_order_status_changed` | Any status transition |
| `woocommerce_payment_complete` | Payment received |
| `woocommerce_order_status_completed` | Order marked complete |

## REST API (v3)

**Base URL:** `https://yoursite.com/wp-json/wc/v3/`

| Endpoint | Methods | Auth Required |
|----------|---------|---------------|
| `/products` | GET, POST, PUT, DELETE | Yes |
| `/products/{id}/variations` | GET, POST, PUT, DELETE | Yes |
| `/orders` | GET, POST, PUT, DELETE | Yes |
| `/customers` | GET, POST, PUT, DELETE | Yes |
| `/coupons` | GET, POST, PUT, DELETE | Yes |
| `/reports/sales` | GET | Yes |

**Auth methods:** Consumer key/secret (query string or Basic Auth), Application Passwords (WP 5.6+), OAuth 1.0a.

**Batch operations:** `POST /products/batch` with `create`, `update`, `delete` arrays. Max 100 objects per batch.

**Rate limits:** Store API default 25 requests per 10 seconds. REST API has no built-in limit (server-dependent).

## HPOS (High-Performance Order Storage)

WooCommerce moved from `wp_posts`/`wp_postmeta` to dedicated order tables (`wp_wc_orders`, `wp_wc_orders_meta`). **HPOS is now the default.**

**Rules:**
- Use `wc_get_order()` and `$order->get_*()` methods — NEVER query `wp_posts` for orders
- Use `wc_get_orders()` instead of `WP_Query` for order queries
- Use `$order->update_meta_data()` / `$order->get_meta()` for custom order data
- Run compatibility check before enabling: `wp wc hpos status`

## Security (MANDATORY)

### The Iron Rule

**Every piece of WooCommerce code MUST follow these patterns. No exceptions. No shortcuts.**

### Input Sanitization — Which Function When

| Context | Function | Example |
|---------|----------|---------|
| Plain text | `sanitize_text_field()` | Names, addresses |
| Email | `sanitize_email()` | Customer email |
| URL | `esc_url_raw()` (for DB) / `esc_url()` (for output) | Return URLs |
| Integer | `absint()` or `intval()` | Product IDs, quantities |
| Textarea | `sanitize_textarea_field()` | Order notes |
| HTML (limited) | `wp_kses_post()` | Rich text descriptions |
| Filename | `sanitize_file_name()` | Uploads |

### Output Escaping — Every Echo Must Escape

| Context | Function |
|---------|----------|
| HTML content | `esc_html()` |
| HTML attributes | `esc_attr()` |
| URLs in href/src | `esc_url()` |
| JavaScript strings | `esc_js()` |
| Translation + escape | `esc_html__()`, `esc_attr__()` |

**Rule:** If it came from user input, database, or external source → escape it on output. Always.

### Database Queries — Always Prepare

```php
// CORRECT
$results = $wpdb->get_results(
    $wpdb->prepare(
        "SELECT * FROM {$wpdb->prefix}wc_orders WHERE customer_id = %d AND status = %s",
        $customer_id,
        $status
    )
);

// NEVER — SQL injection vulnerability
$results = $wpdb->get_results("SELECT * FROM wp_wc_orders WHERE customer_id = $customer_id");
```

### Nonce Verification

**Every form submission and AJAX handler MUST verify a nonce.**

```php
// In form:
wp_nonce_field('my_action', 'my_nonce');

// In handler:
if (!wp_verify_nonce($_POST['my_nonce'], 'my_action')) {
    wp_die('Security check failed');
}

// AJAX handler:
check_ajax_referer('my_action', 'nonce');
```

### Capability Checks

```php
// Before any admin/privileged action:
if (!current_user_can('manage_woocommerce')) {
    wp_die('Unauthorized');
}
```

### Payment Security

- **NEVER store raw card numbers, CVVs, or full card data** — PCI DSS violation
- Use tokenization (Stripe, PayPal handle this)
- Store only: last 4 digits, card brand, expiry month/year, token reference
- Payment forms: use hosted iframes or redirect (never direct POST to your server)
- SCA (Strong Customer Authentication) required for UK/EU transactions

### Code Review Checklist

Before any WooCommerce code is committed, verify:

- [ ] All `$_GET`/`$_POST`/`$_REQUEST` values sanitized before use
- [ ] All output escaped with appropriate `esc_*()` function
- [ ] All DB queries use `$wpdb->prepare()` with placeholders
- [ ] All form handlers verify nonces
- [ ] All privileged actions check `current_user_can()`
- [ ] No hardcoded API keys, secrets, or passwords
- [ ] No `eval()`, `extract()`, `unserialize()` on user data
- [ ] File uploads validate type, size, and use `wp_handle_upload()`
- [ ] REST API endpoints check permissions in `permission_callback`
- [ ] No raw card data stored anywhere

## Performance

### Cart Fragments (Biggest WooCommerce Performance Issue)

WooCommerce loads `wc-cart-fragments.js` on every page — fires AJAX on every load to update cart count. Adds 300-800ms to every page.

**Fix:** Disable on non-cart pages:
```php
add_action('wp_enqueue_scripts', function() {
    if (!is_cart() && !is_checkout()) {
        wp_dequeue_script('wc-cart-fragments');
    }
});
```

**Trade-off:** Cart count in header won't update dynamically on those pages. Implement custom lightweight cart count if needed.

### Query Optimization

- Use `wc_get_products()` instead of `WP_Query` for products (HPOS-compatible)
- Use `wc_get_orders()` instead of `get_posts()` for orders
- Limit related products to 4 (`woocommerce_output_related_products_args` filter)
- Use transients for expensive queries (product counts, aggregations)

### Caching Exclusions

Never cache: cart, checkout, my-account pages. WooCommerce sets `DONOTCACHEPAGE` constant on these. Ensure your caching plugin respects it.

## Analytics Integration (GA4)

**Recommended method:** GTM4WP plugin → Google Tag Manager → GA4

### E-commerce Event Mapping

| WooCommerce Action | GA4 Event | Key Parameters |
|-------------------|-----------|----------------|
| Product page view | `view_item` | item_id, item_name, price |
| Add to cart | `add_to_cart` | item_id, quantity, value |
| Remove from cart | `remove_from_cart` | item_id, quantity |
| View cart | `view_cart` | items[], value |
| Begin checkout | `begin_checkout` | items[], value, coupon |
| Purchase | `purchase` | transaction_id, value, tax, shipping, items[] |

### Clarity Integration

Install via official WordPress plugin or add tracking script to `header.php`. Tag purchases with custom tags: `window.clarity("set", "order_id", orderId)`

## Version Requirements (2026)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| PHP | 8.2 | 8.2+ |
| WordPress | 6.6 | Latest |
| WooCommerce | 9.x | Latest stable |
| MySQL | 5.7 / MariaDB 10.4 | 8.0+ / 10.6+ |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Query `wp_posts` for orders | Breaks with HPOS. Use `wc_get_orders()` |
| Use `WP_Query` for products | Use `wc_get_products()` for forward compatibility |
| Echo unsanitized user input | XSS vulnerability. Always escape output |
| Skip nonce verification | CSRF vulnerability. Every form/AJAX needs it |
| Store card data in order meta | PCI DSS violation. Use tokenization |
| Override templates when hooks suffice | Templates need maintenance on WC updates; hooks don't |
| Leave cart fragments on all pages | 300-800ms performance hit per page |
| Use `extract()` or `eval()` | Security vulnerabilities. Never use with user data |
| Hardcode API keys in theme files | Use `wp_options` or environment variables |
| Skip capability checks on admin actions | Privilege escalation vulnerability |
