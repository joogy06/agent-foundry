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

## Headless Storefront (Store API)

When a decoupled front-end (see `modern-frontend`) renders the storefront,
**WooCommerce stays authoritative for all commerce invariants**; the front-end
renders and collects input. This section defines the WooCommerce side.

**Store API vs admin REST — pick by caller.**
- **Store API** (`/wp-json/wc/store/v1/...`) — the **customer-facing**
  cart/checkout API. Public, nonce-protected, session-aware. This is what a
  storefront uses for products, cart, and checkout.
- **Admin REST v3** (`/wp-json/wc/v3/...`, consumer key/secret) — the
  **back-office** API (order management, product CRUD, reports). It is NOT for
  the browser: its keys are admin credentials and must live server-side only.
- A storefront that reaches for admin REST to render a cart is a security bug
  waiting to happen — use the Store API.

**Cart, session & nonce — SAME-ORIGIN by default.** The Store API keeps cart
state in a session tied to cookies and a `Nonce` header. **Reverse-proxy /
rewrite the storefront's Store-API calls to the WordPress origin** so those
cookies stay **first-party**. A cross-domain decoupled front-end (front-end on
one domain, WordPress on another) breaks cart persistence: third-party cookies
are blocked by CORS credential rules and by Safari ITP, so the shopper's cart
silently empties. Same-origin proxying is the default pattern, not an
optimization.

**Checkout boundary — what must stay WooCommerce-owned.** Payment
authorization, tax calculation, inventory/stock decrement, coupon validation,
and order totals are computed and enforced by WooCommerce. The front-end submits
the order through the Store API and renders the result — it never computes a
price, tax, or "in stock" verdict it then trusts. Never let the client be the
source of truth for money or stock.

**Price & stock freshness.** Cache product data for speed, but treat cached
price/stock as display-only and **re-validate at add-to-cart and at checkout**
against WooCommerce — the authoritative check happens server-side, so a stale
cached price cannot be honored.

**Webhook-driven revalidation.** Fire WooCommerce webhooks (product / order
updated) to the front-end's revalidation endpoint so static/ISR product pages
refresh on price/stock change; tag by product ID to revalidate only affected
routes.

**Boundary:** commerce invariants (cart/session, checkout, payment/tax/inventory
authority) stay here; the storefront UI and rendering live in `modern-frontend`;
experience and journey decisions live in `audience-experience-design`.

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

### Feed Generation at Scale

Large catalogues (10k+ products) break when a product feed (Google Shopping, Meta, or an AI-crawler product feed) is built synchronously on a page request — PHP `max_execution_time` and memory limits kill it mid-run.

- Generate feeds with **Action Scheduler** (bundled with WooCommerce) in chunked batches (200-500 products each), never in one request. Paginate with `wc_get_products()` and free objects between batches.
- Guard each batch: cap peak memory, and avoid loading full product objects when only feed fields are needed.
- **Cache the artifact, not the request** — write the finished feed to a static file (or object storage) and serve that; regenerate off-peak via a real system cron / Action Scheduler, not on the visitor's request.
- Write to a temp file and atomically rename so a crawler never reads a half-written feed.

### Search Offload

Default WordPress search is a `LIKE` scan on `wp_posts`; adding WooCommerce attribute/meta search layers on `meta_query` joins. Both degrade badly past a few thousand products or with high-cardinality attributes.

- Offload to an external index — **ElasticPress** (Elasticsearch/OpenSearch) or **Algolia** — once search/filter latency or relevance is the bottleneck.
- Keep **WooCommerce as the source of truth**; treat the index as a rebuildable projection re-synced on product save/delete. Never let the index hold authoritative price or order data.
- **Security:** store index API keys in environment variables or `wp_options`, never in theme files or committed code; for any client-side calls use a scoped search-only key (e.g. Algolia's search-only API key), never the admin key.
- For high-cardinality *attribute filtering* specifically (not free-text search), see `woocommerce-faceted-navigation` — the facet layer covers the `wc_product_attributes_lookup` boundary and when to reach for an external index.

## Analytics Integration (GA4)

**Recommended method:** GTM4WP plugin → Google Tag Manager → GA4

*To design and run experiments on these events (A/B testing, sample-size and statistical-validity guards, cache-safe variation delivery), see `ecommerce-cro-experimentation` — it references this event-mapping table rather than duplicating it.*

### E-commerce Event Mapping

| WooCommerce Action | GA4 Event | Key Parameters |
|-------------------|-----------|----------------|
| Product page view | `view_item` | item_id, item_name, price |
| Add to cart | `add_to_cart` | item_id, quantity, value |
| Remove from cart | `remove_from_cart` | item_id, quantity |
| View cart | `view_cart` | items[], value |
| Begin checkout | `begin_checkout` | items[], value, coupon |
| Shipping method chosen | `add_shipping_info` | items[], value, shipping_tier |
| Payment method chosen | `add_payment_info` | items[], value, payment_type |
| Purchase | `purchase` | transaction_id, value, tax, shipping, items[] |

#### ⚠️ Express wallets break this funnel — instrument them explicitly

**An Apple Pay / Google Pay / Shop Pay / PayPal express purchase started from the product or cart
page never passes through the checkout page, so `begin_checkout`, `add_shipping_info` and
`add_payment_info` never fire.** Only `add_to_cart` (sometimes not even that) and `purchase` do.

This matters more than it sounds: **wallets are roughly 65% of mobile conversions.** A funnel
readout built on the table above will show those buyers appearing at `purchase` out of nowhere, and
will compute a checkout-completion rate that is **silently wrong for about two-thirds of mobile
orders** — usually presenting as an implausibly low `begin_checkout` → `purchase` rate that gets
"fixed" by optimising a checkout page most mobile buyers never see.

| Do | Why |
|----|-----|
| Fire `begin_checkout` **when the express-wallet sheet opens**, not only on the checkout page | Restores the funnel's entry event for wallet buyers |
| Stamp every checkout + purchase event with a `checkout_type` parameter (`classic` \| `express_wallet`) and register it as a custom dimension | Lets you segment the two funnels instead of averaging them into nonsense |
| Set `payment_type` on `add_payment_info` (`Apple Pay`, `Google Pay`, `PayPal`, `card`) | The only way to size the wallet share you are missing |
| Analyse classic and express funnels **separately** | They have different step counts; a blended completion rate describes neither |
| QA on a **real mobile device** with a live wallet | Wallet sheets frequently do not fire in desktop emulation or GTM Preview |

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
