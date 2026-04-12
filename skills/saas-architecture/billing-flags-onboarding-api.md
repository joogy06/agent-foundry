# Billing, Feature Flags, Onboarding, and API Design

Reference file for the `saas-architecture` skill. Covers subscription/billing integration (Stripe/Paddle), feature flags/entitlements, onboarding flows, and API design patterns.

## Subscription & Billing

### Stripe Integration Architecture

```
Customer Sign-up
    |
    v
[Create Stripe Customer] --> stripe.Customer.create()
    |
    v
[Select Plan] --> Map to Stripe Price ID
    |
    v
[Create Subscription] --> stripe.Subscription.create()
    |                          |
    v                          v
[Webhook: invoice.paid]   [Webhook: customer.subscription.updated]
    |                          |
    v                          v
[Activate tenant]         [Update entitlements]
```

### Core Stripe Objects Mapping

| SaaS Concept | Stripe Object | Notes |
|-------------|---------------|-------|
| Tenant | Customer | 1:1 mapping, store stripe_customer_id on tenant |
| Plan/Tier | Product + Price | Product = "Pro Plan", Price = "$99/mo" |
| Subscription | Subscription | Links Customer to Price(s) |
| Usage-based billing | Meter + MeterEvent | Report usage events, Stripe aggregates |
| One-time charge | Invoice Item | Add to next invoice |
| Trial period | Subscription.trial_end | Built into subscription creation |

### Subscription Management

```python
# services/billing.py
import stripe

class BillingService:
    """Manages Stripe subscriptions and billing lifecycle."""

    PLAN_PRICE_MAP = {
        "starter":    "price_starter_monthly_id",
        "pro":        "price_pro_monthly_id",
        "enterprise": "price_enterprise_monthly_id",
    }

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"tenant_id": tenant_id},
        )
        # Store mapping
        self.db.execute(
            "UPDATE tenants SET stripe_customer_id = :cid WHERE tenant_id = :tid",
            {"cid": customer.id, "tid": tenant_id},
        )
        return customer.id

    def create_subscription(
        self, tenant_id: str, plan: str, trial_days: int = 14
    ) -> stripe.Subscription:
        tenant = self.tenant_registry.get(tenant_id)
        price_id = self.PLAN_PRICE_MAP[plan]

        subscription = stripe.Subscription.create(
            customer=tenant.stripe_customer_id,
            items=[{"price": price_id}],
            trial_period_days=trial_days,
            payment_behavior="default_incomplete",  # Require payment method
            expand=["latest_invoice.payment_intent"],
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
        return subscription

    def change_plan(self, tenant_id: str, new_plan: str) -> stripe.Subscription:
        """Upgrade or downgrade — Stripe prorates automatically."""
        tenant = self.tenant_registry.get(tenant_id)
        subscription = stripe.Subscription.list(
            customer=tenant.stripe_customer_id, status="active", limit=1
        ).data[0]

        new_price_id = self.PLAN_PRICE_MAP[new_plan]

        updated = stripe.Subscription.modify(
            subscription.id,
            items=[{
                "id": subscription["items"]["data"][0].id,
                "price": new_price_id,
            }],
            proration_behavior="create_prorations",
            metadata={"plan": new_plan},
        )
        return updated

    def cancel_subscription(self, tenant_id: str, at_period_end: bool = True):
        """Cancel at period end (default) or immediately."""
        tenant = self.tenant_registry.get(tenant_id)
        subscription = stripe.Subscription.list(
            customer=tenant.stripe_customer_id, status="active", limit=1
        ).data[0]

        if at_period_end:
            stripe.Subscription.modify(
                subscription.id, cancel_at_period_end=True
            )
        else:
            stripe.Subscription.cancel(subscription.id)
```

### Webhook Handling

```python
# webhooks/stripe_handler.py
import stripe
from flask import Blueprint, request, abort

stripe_webhook = Blueprint('stripe_webhook', __name__)

@stripe_webhook.route('/webhooks/stripe', methods=['POST'])
def handle_stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        abort(400, description="Invalid signature")

    handler = WEBHOOK_HANDLERS.get(event.type)
    if handler:
        handler(event.data.object)
    else:
        logger.info(f"Unhandled webhook event: {event.type}")

    return '', 200  # Always return 200 to prevent retries for known events

def _handle_invoice_paid(invoice):
    tenant_id = invoice.subscription_details.metadata.get('tenant_id')
    if not tenant_id:
        tenant_id = invoice.customer_metadata.get('tenant_id')
    billing_repo.record_payment(tenant_id, invoice.id, invoice.amount_paid)
    tenant_service.activate(tenant_id)

def _handle_invoice_payment_failed(invoice):
    tenant_id = _extract_tenant_id(invoice)
    attempt = invoice.attempt_count
    if attempt >= 3:
        tenant_service.suspend(tenant_id, reason="payment_failed")
        notification_service.send(tenant_id, "payment_failed_final")
    else:
        notification_service.send(tenant_id, "payment_failed_retry", attempt=attempt)

def _handle_subscription_deleted(subscription):
    tenant_id = subscription.metadata.get('tenant_id')
    tenant_service.begin_offboarding(tenant_id)  # Async, with grace period

def _handle_customer_subscription_updated(subscription):
    tenant_id = subscription.metadata.get('tenant_id')
    new_plan = subscription.metadata.get('plan')
    entitlement_service.sync_entitlements(tenant_id, new_plan)

WEBHOOK_HANDLERS = {
    'invoice.paid': _handle_invoice_paid,
    'invoice.payment_failed': _handle_invoice_payment_failed,
    'customer.subscription.deleted': _handle_subscription_deleted,
    'customer.subscription.updated': _handle_customer_subscription_updated,
}
```

### Dunning (Failed Payment Recovery)

| Attempt | Timing | Action |
|---------|--------|--------|
| 1st failure | Immediately | Email: "Payment failed, updating card" |
| 2nd failure | +3 days | Email + in-app banner: "Action required" |
| 3rd failure | +7 days | Email: "Final notice — service suspension in 3 days" |
| 4th failure | +10 days | Suspend tenant, restrict to read-only |
| Grace period end | +30 days | Begin offboarding pipeline |

## Feature Flags & Entitlements

### Plan-Based Entitlement Model

```python
# services/entitlements.py
from dataclasses import dataclass, field

@dataclass
class PlanEntitlements:
    plan_id: str
    features: set[str]                    # Boolean feature flags
    limits: dict[str, int]                # Numeric quotas
    rate_limits: dict[str, str]           # API rate limits per endpoint group

PLAN_DEFINITIONS = {
    "starter": PlanEntitlements(
        plan_id="starter",
        features={"basic_reports", "email_support", "api_access"},
        limits={"users": 5, "projects": 10, "storage_gb": 5, "api_calls_daily": 1_000},
        rate_limits={"api": "100/hour", "exports": "10/day"},
    ),
    "pro": PlanEntitlements(
        plan_id="pro",
        features={"basic_reports", "advanced_reports", "api_access",
                  "webhooks", "custom_domains", "priority_support", "sso"},
        limits={"users": 50, "projects": 100, "storage_gb": 50, "api_calls_daily": 50_000},
        rate_limits={"api": "1000/hour", "exports": "100/day"},
    ),
    "enterprise": PlanEntitlements(
        plan_id="enterprise",
        features={"basic_reports", "advanced_reports", "api_access",
                  "webhooks", "custom_domains", "priority_support", "sso",
                  "audit_logs", "data_export", "dedicated_support", "sla_guarantee"},
        limits={"users": -1, "projects": -1, "storage_gb": 500, "api_calls_daily": -1},  # -1 = unlimited
        rate_limits={"api": "10000/hour", "exports": "1000/day"},
    ),
}

class EntitlementService:
    """Check feature access and enforce limits per tenant."""

    def __init__(self, tenant_registry, override_store):
        self.tenant_registry = tenant_registry
        self.override_store = override_store  # Redis or DB for per-tenant overrides

    def has_feature(self, tenant_id: str, feature: str) -> bool:
        # Check per-tenant override first (for beta flags, custom deals)
        override = self.override_store.get_override(tenant_id, feature)
        if override is not None:
            return override

        # Fall back to plan-based entitlement
        tenant = self.tenant_registry.get(tenant_id)
        plan = PLAN_DEFINITIONS.get(tenant.plan_id)
        return feature in plan.features if plan else False

    def check_limit(self, tenant_id: str, resource: str, current_usage: int) -> bool:
        """Returns True if within limit, False if exceeded."""
        tenant = self.tenant_registry.get(tenant_id)
        plan = PLAN_DEFINITIONS.get(tenant.plan_id)
        limit = plan.limits.get(resource, 0)
        if limit == -1:  # Unlimited
            return True
        return current_usage < limit

    def get_rate_limit(self, tenant_id: str, endpoint_group: str) -> str:
        tenant = self.tenant_registry.get(tenant_id)
        plan = PLAN_DEFINITIONS.get(tenant.plan_id)
        return plan.rate_limits.get(endpoint_group, "60/hour")  # Default fallback
```

### Entitlement Middleware

```python
# middleware/entitlements.py
from functools import wraps
from flask import abort, g

def require_feature(feature: str):
    """Decorator: abort 403 if tenant lacks the feature."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not entitlement_service.has_feature(g.tenant_id, feature):
                abort(403, description=f"Feature '{feature}' not available on your plan. Upgrade to access.")
            return f(*args, **kwargs)
        return wrapper
    return decorator

def require_limit(resource: str, usage_fn):
    """Decorator: abort 429 if tenant exceeds resource limit."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            current = usage_fn(g.tenant_id)
            if not entitlement_service.check_limit(g.tenant_id, resource, current):
                abort(429, description=f"Plan limit reached for '{resource}'. Upgrade for more.")
            return f(*args, **kwargs)
        return wrapper
    return decorator

# Usage in route handlers
@api.route('/reports/advanced')
@require_feature('advanced_reports')
def generate_advanced_report():
    ...

@api.route('/projects', methods=['POST'])
@require_limit('projects', lambda tid: Project.query.filter_by(tenant_id=tid).count())
def create_project():
    ...
```

### Feature Flag Integration (LaunchDarkly / Unleash Pattern)

```python
# services/feature_flags.py
class FeatureFlagService:
    """Wraps external feature flag provider with tenant context."""

    def __init__(self, ld_client, entitlement_service):
        self.ld_client = ld_client
        self.entitlement_service = entitlement_service

    def is_enabled(self, tenant_id: str, flag_key: str) -> bool:
        # Layer 1: Entitlement check (plan-based, hard gate)
        if not self.entitlement_service.has_feature(tenant_id, flag_key):
            return False

        # Layer 2: Feature flag check (gradual rollout, A/B test)
        context = {
            "kind": "tenant",
            "key": tenant_id,
            "plan": self.entitlement_service.get_plan(tenant_id),
        }
        return self.ld_client.variation(flag_key, context, default=False)
```

## Onboarding

### Tenant Provisioning Pipeline

```
Sign-up Form
    |
    v
[1. Create Tenant Record] — tenant_id, org name, owner email
    |
    v
[2. Create Stripe Customer] — link stripe_customer_id
    |
    v
[3. Provision Data Store] — depends on isolation model:
    |   Pool:   INSERT into tenants table
    |   Bridge: CREATE SCHEMA tenant_{id}; run migrations
    |   Silo:   CREATE DATABASE; run full migration suite
    |
    v
[4. Seed Default Data] — default roles, settings, example content
    |
    v
[5. Create Admin User] — owner account with admin role
    |
    v
[6. Configure Integrations] — default webhooks, API key, SSO (if enterprise)
    |
    v
[7. Send Welcome Email] — activation link, getting started guide
    |
    v
[8. Emit Event: tenant.provisioned] — for analytics, internal notifications
```

```python
# services/onboarding.py
class TenantProvisioningService:
    """Orchestrates new tenant setup."""

    def provision(self, signup: SignupRequest) -> Tenant:
        tenant_id = str(uuid4())

        # 1. Create tenant record
        tenant = Tenant(
            tenant_id=tenant_id,
            name=signup.org_name,
            plan_id=signup.plan or "starter",
            isolation_model="pool",  # Default; upgrade later
            status="provisioning",
        )
        self.db.add(tenant)
        self.db.flush()  # Get ID without committing

        try:
            # 2. Stripe customer
            stripe_id = self.billing.create_customer(
                tenant_id, signup.email, signup.org_name
            )
            tenant.stripe_customer_id = stripe_id

            # 3. Data store provisioning
            self.data_provisioner.provision(tenant)

            # 4. Seed defaults
            self.seeder.seed_defaults(tenant_id)

            # 5. Create admin user
            admin = self.user_service.create_admin(
                tenant_id, signup.email, signup.name
            )

            # 6. Default API key
            api_key = self.api_key_service.create(
                tenant_id, name="Default", scopes=["read", "write"]
            )

            tenant.status = "active"
            self.db.commit()

            # 7-8. Async: welcome email + event
            self.event_bus.emit("tenant.provisioned", {
                "tenant_id": tenant_id,
                "plan": tenant.plan_id,
                "email": signup.email,
            })

            return tenant

        except Exception as e:
            self.db.rollback()
            self._rollback_provisioning(tenant_id)
            raise ProvisioningError(f"Failed to provision tenant: {e}")

    def _rollback_provisioning(self, tenant_id: str):
        """Best-effort cleanup on provisioning failure."""
        self.data_provisioner.deprovision(tenant_id)
        # Stripe customer remains (idempotent, can retry)
        logger.error(f"Provisioning rollback for tenant {tenant_id}")
```

### Invite-Based Onboarding

```python
# services/invitations.py
class InvitationService:
    def invite_user(self, tenant_id: str, email: str, role: str = "member"):
        token = secrets.token_urlsafe(32)
        invite = Invitation(
            tenant_id=tenant_id,
            email=email,
            role=role,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        self.db.add(invite)
        self.db.commit()

        self.email_service.send_invite(email, tenant_id, token)
        return invite

    def accept_invite(self, token: str) -> User:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invite = Invitation.query.filter_by(
            token_hash=token_hash, accepted=False
        ).first()

        if not invite or invite.expires_at < datetime.utcnow():
            raise InvalidInvitationError()

        user = self.user_service.create(
            tenant_id=invite.tenant_id,
            email=invite.email,
            role=invite.role,
        )
        invite.accepted = True
        self.db.commit()
        return user
```

## API Design

### Tenant-Scoped API Keys

```python
# models/api_key.py
import secrets, hashlib

class APIKey(db.Model, TenantMixin):
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    key_prefix = db.Column(db.String(8), index=True)    # First 8 chars (for lookup)
    key_hash = db.Column(db.String(64), unique=True)     # SHA-256 hash (stored)
    scopes = db.Column(db.JSON, default=list)             # ["read", "write", "admin"]
    rate_limit_override = db.Column(db.String(20))        # e.g., "500/hour"
    last_used_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    @classmethod
    def create(cls, tenant_id: str, name: str, scopes: list[str]) -> tuple['APIKey', str]:
        """Returns (model, raw_key). Raw key is shown once, never stored."""
        raw_key = f"sk_{secrets.token_urlsafe(32)}"
        key = cls(
            tenant_id=tenant_id,
            name=name,
            key_prefix=raw_key[:8],
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            scopes=scopes,
        )
        return key, raw_key

    @classmethod
    def authenticate(cls, raw_key: str) -> 'APIKey | None':
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        return cls.query.filter_by(key_hash=key_hash, is_active=True).first()
```

### Rate Limiting Per Tenant/Plan

```python
# middleware/rate_limiter.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def tenant_rate_limit_key():
    """Rate limit by tenant, not by IP."""
    return g.tenant_id if hasattr(g, 'tenant_id') else get_remote_address()

limiter = Limiter(
    key_func=tenant_rate_limit_key,
    storage_uri="redis://localhost:6379/1",
    strategy="moving-window",
)

def dynamic_rate_limit():
    """Resolve rate limit from tenant's plan at request time."""
    if hasattr(g, 'tenant_id'):
        return entitlement_service.get_rate_limit(g.tenant_id, "api")
    return "60/hour"  # Unauthenticated fallback

# Apply to API blueprint
@api.before_request
@limiter.limit(dynamic_rate_limit)
def rate_limit_api():
    pass
```

### API Versioning

| Strategy | URL Example | Header Example | Pros | Cons |
|----------|-------------|----------------|------|------|
| URL path | `/api/v1/orders` | - | Explicit, cache-friendly | URL pollution |
| Header | `/api/orders` | `API-Version: 2024-01-15` | Clean URLs | Less discoverable |
| Query param | `/api/orders?v=2` | - | Simple | Ugly, cache issues |

**Recommendation:** URL path versioning for external APIs (`/api/v1/`), date-based header versioning for Stripe-style API stability.

### Per-Tenant Webhook Delivery

```python
# services/webhook_delivery.py
class WebhookDeliveryService:
    """Deliver events to tenant-configured webhook endpoints."""

    MAX_RETRIES = 5
    RETRY_DELAYS = [60, 300, 1800, 7200, 86400]  # 1m, 5m, 30m, 2h, 24h

    def deliver(self, tenant_id: str, event_type: str, payload: dict):
        endpoints = WebhookEndpoint.query.filter_by(
            tenant_id=tenant_id, is_active=True
        ).all()

        for endpoint in endpoints:
            if event_type not in endpoint.subscribed_events:
                continue

            # Sign payload with tenant-specific secret
            signature = hmac.new(
                endpoint.signing_secret.encode(),
                json.dumps(payload).encode(),
                hashlib.sha256
            ).hexdigest()

            delivery = WebhookDelivery(
                tenant_id=tenant_id,
                endpoint_id=endpoint.id,
                event_type=event_type,
                payload=payload,
                signature=f"sha256={signature}",
            )
            self.db.add(delivery)
            self.db.commit()

            # Queue for async delivery with retry
            self.task_queue.enqueue(
                self._attempt_delivery,
                delivery.id,
                retry=self.MAX_RETRIES,
                retry_delays=self.RETRY_DELAYS,
            )

    def _attempt_delivery(self, delivery_id: int):
        delivery = WebhookDelivery.query.get(delivery_id)
        try:
            response = httpx.post(
                delivery.endpoint.url,
                json=delivery.payload,
                headers={
                    "X-Webhook-Signature": delivery.signature,
                    "X-Webhook-Event": delivery.event_type,
                    "X-Webhook-Delivery-ID": str(delivery.id),
                },
                timeout=30,
            )
            delivery.status_code = response.status_code
            delivery.delivered_at = datetime.utcnow()
            delivery.status = "delivered" if response.status_code < 300 else "failed"
        except Exception as e:
            delivery.status = "failed"
            delivery.error = str(e)
        self.db.commit()
```

