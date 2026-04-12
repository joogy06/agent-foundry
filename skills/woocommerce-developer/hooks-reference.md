# WooCommerce Hooks Reference

Complete hook map for WooCommerce development. Organized by page/context.

## Single Product Page

### Actions (in display order)

| Hook | Default Priority | What Hooks In |
|------|-----------------|---------------|
| `woocommerce_before_single_product` | 10 | Notices/alerts |
| `woocommerce_before_single_product_summary` | 10 | Product image gallery (`woocommerce_show_product_images`) |
| `woocommerce_single_product_summary` | 5 | Title (`woocommerce_template_single_title`) |
| | 10 | Rating (`woocommerce_template_single_rating`) |
| | 10 | Price (`woocommerce_template_single_price`) |
| | 20 | Short description (`woocommerce_template_single_excerpt`) |
| | 30 | Add to cart form (`woocommerce_template_single_add_to_cart`) |
| | 40 | Product meta (SKU, categories, tags) |
| | 50 | Sharing links |
| `woocommerce_after_single_product_summary` | 10 | Product tabs (description, reviews, attributes) |
| | 15 | Related products |
| `woocommerce_after_single_product` | — | After product wrapper |

### Key Filters

| Filter | Purpose | Example Use |
|--------|---------|-------------|
| `woocommerce_product_tabs` | Add/remove/reorder tabs | Add "FPS Benchmarks" tab |
| `woocommerce_get_price_html` | Modify price display | Add "from £X/mo with Klarna" |
| `woocommerce_product_get_image` | Modify product image output | Add badges/overlays |
| `woocommerce_available_variation` | Modify variation data sent to JS | Add custom fields to variations |
| `woocommerce_add_to_cart_validation` | Validate before adding to cart | Custom validation rules |
| `woocommerce_product_single_add_to_cart_text` | Change "Add to cart" button text | "Build This PC" |

## Shop / Category / Archive Pages

### Actions

| Hook | Purpose |
|------|---------|
| `woocommerce_before_shop_loop` | Before product grid (result count, ordering dropdown) |
| `woocommerce_before_shop_loop_item` | Before each product card |
| `woocommerce_before_shop_loop_item_title` | Before product title (image hooks here) |
| `woocommerce_shop_loop_item_title` | Product title |
| `woocommerce_after_shop_loop_item_title` | After title (rating, price) |
| `woocommerce_after_shop_loop_item` | After product card (add to cart button) |
| `woocommerce_after_shop_loop` | After product grid (pagination) |

### Key Filters

| Filter | Purpose |
|--------|---------|
| `woocommerce_product_query` | Modify main product query |
| `loop_shop_per_page` | Products per page |
| `loop_shop_columns` | Grid columns |
| `woocommerce_catalog_orderby` | Sort options in dropdown |
| `woocommerce_get_catalog_ordering_args` | Default sort order |

## Cart Page

### Actions

| Hook | Purpose |
|------|---------|
| `woocommerce_before_cart` | Before cart table |
| `woocommerce_before_cart_table` | Inside cart form, before table |
| `woocommerce_cart_contents` | After cart item rows |
| `woocommerce_after_cart_table` | After cart table |
| `woocommerce_cart_collaterals` | Cart totals area |
| `woocommerce_after_cart` | After entire cart |
| `woocommerce_proceed_to_checkout` | Proceed to checkout button area |

### Key Filters

| Filter | Purpose |
|--------|---------|
| `woocommerce_cart_item_name` | Modify item name in cart |
| `woocommerce_cart_item_price` | Modify displayed price |
| `woocommerce_cart_item_quantity` | Modify quantity input |
| `woocommerce_cart_item_subtotal` | Modify line subtotal |
| `woocommerce_add_to_cart_fragments` | Update cart fragments via AJAX |

## Checkout Page (Classic)

### Actions

| Hook | Purpose |
|------|---------|
| `woocommerce_before_checkout_form` | Before form (login notice, coupon) |
| `woocommerce_checkout_before_customer_details` | Before billing/shipping columns |
| `woocommerce_before_checkout_billing_form` | Before billing fields |
| `woocommerce_after_checkout_billing_form` | After billing fields |
| `woocommerce_before_checkout_shipping_form` | Before shipping fields |
| `woocommerce_after_checkout_shipping_form` | After shipping fields |
| `woocommerce_checkout_before_order_review` | Before order summary |
| `woocommerce_review_order_before_payment` | Before payment methods |
| `woocommerce_review_order_after_payment` | After payment methods |
| `woocommerce_after_checkout_form` | After entire checkout form |

### Key Filters

| Filter | Purpose | Common Use |
|--------|---------|------------|
| `woocommerce_checkout_fields` | Add/remove/reorder ALL checkout fields | Remove company field, add custom fields |
| `woocommerce_billing_fields` | Modify billing fields only | Make phone optional |
| `woocommerce_shipping_fields` | Modify shipping fields only | Add delivery instructions |
| `woocommerce_default_address_fields` | Modify shared billing/shipping fields | Reorder postcode/city |

### Checkout Field Structure

```php
// Add a custom checkout field
add_filter('woocommerce_checkout_fields', function($fields) {
    $fields['billing']['billing_delivery_notes'] = [
        'type'     => 'textarea',
        'label'    => 'Delivery Notes',
        'required' => false,
        'priority' => 120,
        'class'    => ['form-row-wide'],
    ];
    return $fields;
});

// Save the field to order meta
add_action('woocommerce_checkout_update_order_meta', function($order_id) {
    if (!empty($_POST['billing_delivery_notes'])) {
        $order = wc_get_order($order_id);
        $order->update_meta_data('_delivery_notes', sanitize_textarea_field($_POST['billing_delivery_notes']));
        $order->save();
    }
});
```

## Order Processing

### Actions (Lifecycle Order)

| Hook | When | Common Use |
|------|------|------------|
| `woocommerce_new_order` | Order first created | Initialize custom data |
| `woocommerce_checkout_order_processed` | After order created, before payment | Validation, external API calls |
| `woocommerce_payment_complete` | Payment received | Send to fulfillment, trigger external systems |
| `woocommerce_order_status_changed` | Any status transition | Logging, notifications |
| `woocommerce_order_status_{from}_to_{to}` | Specific transition | e.g., `pending_to_processing` |
| `woocommerce_order_status_processing` | Order moved to processing | Fulfillment trigger |
| `woocommerce_order_status_completed` | Order marked complete | Post-purchase emails, review requests |
| `woocommerce_order_refunded` | Refund processed | Update external systems |

## Email Hooks

| Hook | Purpose |
|------|---------|
| `woocommerce_email_header` | Email header area |
| `woocommerce_email_order_details` | Order details in email |
| `woocommerce_email_before_order_table` | Before order table |
| `woocommerce_email_after_order_table` | After order table |
| `woocommerce_email_footer` | Email footer area |
| `woocommerce_email_classes` (filter) | Register custom email classes |

## REST API Hooks

| Hook | Purpose |
|------|---------|
| `woocommerce_rest_insert_product_object` | After product created/updated via API |
| `woocommerce_rest_insert_shop_order_object` | After order created/updated via API |
| `woocommerce_rest_prepare_product_object` | Modify product API response |
| `woocommerce_rest_check_permissions` | Custom permission logic |

## Deprecated Hooks (Avoid)

| Deprecated Hook | Replacement |
|----------------|-------------|
| `woocommerce_add_order_item_meta` | `woocommerce_checkout_create_order_line_item` |
| `woocommerce_process_shop_order_meta` | Direct order object manipulation |
| `woocommerce_update_option` | `woocommerce_update_options` |
| `add_to_cart_fragments` | `woocommerce_add_to_cart_fragments` |

## Block Checkout Extensibility

Block checkout does NOT use PHP hooks. Instead:

| Method | Purpose |
|--------|---------|
| **Slot/Fill API** | Insert React components into checkout slots |
| **Inner Blocks** | Add custom blocks inside checkout |
| **Additional Fields API** | Add form fields to checkout (WC 8.9+) |
| **ExtensionCartUpdate** | Modify cart data from checkout blocks |
| **wc/store API filters** | Server-side data modification |

Block checkout customization requires JavaScript/React — not PHP.
