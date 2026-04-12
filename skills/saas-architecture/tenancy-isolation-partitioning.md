# Multi-Tenancy, Isolation, and Data Partitioning

Reference file for the `saas-architecture` skill. Covers multi-tenancy models (silo/pool/bridge), tenant isolation patterns, and data partitioning strategies.

## Overview

SaaS applications serve multiple tenants from a single deployment. Every architectural decision — data isolation, billing, feature gating, API limits — must be tenant-aware from day one. Retrofitting multi-tenancy is orders of magnitude harder than building it in. This skill covers the full stack of SaaS patterns: tenancy models, data isolation, billing integration, entitlements, metering, and operational safety.

## HARD-RULEs

1. **Every database query in a multi-tenant pool MUST include tenant_id filtering** — a missing WHERE clause leaks data across tenants. Use row-level security policies or ORM query filters as a safety net, never rely on application code alone.
2. **Never store tenant-specific secrets in application config** — use a secrets manager (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager) with tenant-scoped access policies. Config files and environment variables are shared across tenants.
3. **Always implement tenant context validation at the middleware level, not in individual handlers** — a single handler that forgets to check tenant context creates a cross-tenant vulnerability. Middleware enforces the invariant once.
4. **Never delete tenant data synchronously during offboarding** — queue for async deletion with a configurable grace period (minimum 30 days) and full audit trail. Synchronous deletion is irreversible, unauditable, and blocks request handling.

## Multi-Tenancy Models

### Decision Matrix

| Factor | Silo (Dedicated) | Bridge (Hybrid) | Pool (Shared) |
|--------|-------------------|------------------|----------------|
| **Data isolation** | Strongest — separate DB/infra per tenant | Strong — separate schema or database, shared compute | Weakest — row-level isolation only |
| **Cost per tenant** | Highest — dedicated resources | Medium — shared compute, isolated data | Lowest — fully shared |
| **Operational complexity** | High — N deployments to manage | Medium — shared app, isolated data | Low — single deployment |
| **Noisy neighbor risk** | None — isolated resources | Low — shared compute only | High — shared everything |
| **Onboarding speed** | Slow — provision infrastructure | Medium — create schema/DB | Fast — insert row |
| **Compliance fit** | Regulated industries, healthcare, finance | Enterprise customers with data residency needs | SMB, self-service SaaS |
| **Best for** | <50 large enterprise tenants | 50-500 mid-market tenants | 500+ self-service tenants |

### Database Isolation Strategies

| Strategy | Isolation | Cost | Migrations | Use When |
|----------|-----------|------|------------|----------|
| Database-per-tenant | Strongest | Highest | Run per DB (slow) | Regulated industries, <100 tenants |
| Schema-per-tenant | Strong | Medium | Run per schema | Mid-market, need data isolation without infra cost |
| Row-level (shared tables) | Row-level | Lowest | Single migration | Self-service SaaS, 1000+ tenants |
| Hybrid (pool + silo) | Mixed | Variable | Mixed | Large tenants get silo, small tenants share pool |

### Hybrid Model (Recommended for Growth)

Start with pool (row-level isolation), offer silo upgrades for enterprise:

```python
# tenant_router.py — Route tenants to their database
from enum import Enum

class IsolationModel(Enum):
    POOL = "pool"        # Shared database, row-level isolation
    BRIDGE = "bridge"    # Shared compute, dedicated database
    SILO = "silo"        # Dedicated everything

class TenantRouter:
    """Routes database connections based on tenant isolation model."""

    def __init__(self, default_engine, tenant_registry):
        self.default_engine = default_engine
        self.tenant_registry = tenant_registry
        self._engine_cache = {}

    def get_engine(self, tenant_id: str):
        tenant = self.tenant_registry.get(tenant_id)
        if not tenant:
            raise TenantNotFoundError(tenant_id)

        if tenant.isolation_model == IsolationModel.POOL:
            return self.default_engine

        # Bridge/Silo tenants have dedicated connection strings
        if tenant_id not in self._engine_cache:
            self._engine_cache[tenant_id] = create_engine(
                tenant.database_url,
                pool_size=tenant.pool_size or 5,
                pool_pre_ping=True,
            )
        return self._engine_cache[tenant_id]
```

## Tenant Isolation

### Tenant Context Middleware (HARD-RULE: Must Be Middleware-Level)

```python
# middleware/tenant_context.py
import contextvars
from functools import wraps
from flask import request, g, abort

# Thread-safe tenant context using contextvars
_tenant_ctx: contextvars.ContextVar[str] = contextvars.ContextVar('tenant_id')

def get_current_tenant_id() -> str:
    """Get tenant_id from context. Raises if not set."""
    try:
        return _tenant_ctx.get()
    except LookupError:
        raise RuntimeError("Tenant context not set — middleware missing or bypassed")

class TenantMiddleware:
    """Extract and validate tenant_id on every request.

    Sources (in priority order):
    1. JWT claim 'tenant_id'
    2. X-Tenant-ID header (for service-to-service)
    3. API key lookup
    """

    def __init__(self, app, tenant_registry):
        self.app = app
        self.tenant_registry = tenant_registry
        app.before_request(self._set_tenant_context)
        app.teardown_request(self._clear_tenant_context)

    def _set_tenant_context(self):
        # Skip tenant resolution for public endpoints
        if request.endpoint in ('health', 'metrics', 'auth.login'):
            return

        tenant_id = self._resolve_tenant_id()
        if not tenant_id:
            abort(401, description="Tenant identification required")

        tenant = self.tenant_registry.get(tenant_id)
        if not tenant or not tenant.is_active:
            abort(403, description="Tenant not found or suspended")

        _tenant_ctx.set(tenant_id)
        g.tenant_id = tenant_id
        g.tenant = tenant

    def _resolve_tenant_id(self) -> str | None:
        # 1. From JWT
        if hasattr(g, 'jwt_claims') and 'tenant_id' in g.jwt_claims:
            return g.jwt_claims['tenant_id']
        # 2. From header (service-to-service with mTLS)
        if request.headers.get('X-Tenant-ID'):
            return request.headers['X-Tenant-ID']
        # 3. From API key
        api_key = request.headers.get('X-API-Key')
        if api_key:
            return self.tenant_registry.tenant_for_api_key(api_key)
        return None

    def _clear_tenant_context(self, exception=None):
        _tenant_ctx.set(None)
```

### PostgreSQL Row-Level Security (RLS)

RLS is the database-level safety net. Even if application code has a bug, RLS prevents cross-tenant access:

```sql
-- Enable RLS on all tenant-scoped tables
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE ROW LEVEL SECURITY;  -- Applies to table owner too

-- Policy: tenant can only see their own rows
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Set tenant context at connection/transaction start
-- (called from application middleware before any query)
SET LOCAL app.current_tenant_id = 'tenant-uuid-here';

-- Apply to all tenant tables
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'tenant_id'
        AND table_schema = 'public'
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.current_tenant_id'')::uuid)',
            tbl
        );
    END LOOP;
END $$;
```

### SQLAlchemy Query Filter (Application-Level Safety Net)

```python
# models/base.py — Automatic tenant filtering on all queries
from sqlalchemy import event
from sqlalchemy.orm import Query

class TenantScopedQuery(Query):
    """Automatically appends tenant_id filter to every query."""

    def get(self, ident):
        # Override get() to include tenant filter
        obj = super().get(ident)
        if obj and hasattr(obj, 'tenant_id'):
            if obj.tenant_id != get_current_tenant_id():
                return None  # Deny cross-tenant access
        return obj

# SQLAlchemy 2.0 event-based approach
@event.listens_for(db.session, "do_orm_execute")
def _add_tenant_filter(execute_state):
    """Inject tenant_id filter into every SELECT automatically."""
    if execute_state.is_select and not execute_state.execution_options.get("skip_tenant_filter"):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantMixin,
                TenantMixin.tenant_id == get_current_tenant_id(),
                include_aliases=True,
            )
        )

class TenantMixin:
    """Mixin for all tenant-scoped models."""
    tenant_id = db.Column(
        db.String(36), nullable=False, index=True
    )

    @staticmethod
    def before_insert(mapper, connection, target):
        if not target.tenant_id:
            target.tenant_id = get_current_tenant_id()

# Usage — tenant_id is automatically filtered and set
class Order(db.Model, TenantMixin):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Numeric(10, 2))
    # tenant_id inherited from TenantMixin
```

## Data Partitioning

### PostgreSQL Partition-by-List on tenant_id

For high-volume tables (events, audit logs, usage records):

```sql
-- Partitioned table by tenant_id
CREATE TABLE usage_events (
    id          BIGSERIAL,
    tenant_id   UUID NOT NULL,
    event_type  TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, id)
) PARTITION BY LIST (tenant_id);

-- Create partition for a specific tenant
CREATE TABLE usage_events_tenant_abc123
    PARTITION OF usage_events
    FOR VALUES IN ('abc123-uuid-here');

-- Default partition catches all others (pool tenants)
CREATE TABLE usage_events_default
    PARTITION OF usage_events DEFAULT;

-- Automate partition creation on tenant provisioning
CREATE OR REPLACE FUNCTION create_tenant_partition(
    p_tenant_id UUID,
    p_table_name TEXT
) RETURNS VOID AS $$
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES IN (%L)',
        p_table_name || '_tenant_' || replace(p_tenant_id::text, '-', ''),
        p_table_name,
        p_tenant_id
    );
END;
$$ LANGUAGE plpgsql;
```

### Shard Mapping & Tenant Metadata Store

```python
# services/tenant_registry.py
from dataclasses import dataclass
from enum import Enum
import redis
import json

@dataclass
class TenantMetadata:
    tenant_id: str
    name: str
    isolation_model: str      # pool | bridge | silo
    database_url: str | None  # None for pool tenants
    shard_key: str | None     # For sharded pool setups
    region: str               # Data residency region
    plan_id: str
    is_active: bool
    created_at: str

class TenantRegistry:
    """Tenant metadata store with Redis cache for fast lookups."""

    def __init__(self, db_session, redis_client: redis.Redis):
        self.db = db_session
        self.redis = redis_client
        self.cache_ttl = 300  # 5 minutes

    def get(self, tenant_id: str) -> TenantMetadata | None:
        # Check cache first
        cached = self.redis.get(f"tenant:{tenant_id}")
        if cached:
            return TenantMetadata(**json.loads(cached))

        # DB fallback
        row = self.db.execute(
            "SELECT * FROM tenants WHERE tenant_id = :tid AND is_active = true",
            {"tid": tenant_id}
        ).fetchone()

        if not row:
            return None

        tenant = TenantMetadata(**dict(row._mapping))
        self.redis.setex(
            f"tenant:{tenant_id}", self.cache_ttl, json.dumps(tenant.__dict__)
        )
        return tenant

    def invalidate(self, tenant_id: str):
        self.redis.delete(f"tenant:{tenant_id}")
```

### Migration Patterns

| Strategy | Migration Approach | Tooling |
|----------|-------------------|---------|
| Row-level (pool) | Single Alembic migration, one run | Standard Alembic |
| Schema-per-tenant | Loop over schemas, run migration per schema | Custom Alembic runner |
| Database-per-tenant | Loop over databases, run migration per DB | Alembic + connection swapping |

```python
# migrations/multi_tenant_runner.py
def run_migrations_for_all_tenants(alembic_cfg, tenant_registry):
    """Run Alembic migrations across all tenant databases/schemas."""
    tenants = tenant_registry.list_all()

    for tenant in tenants:
        if tenant.isolation_model == "pool":
            continue  # Pool tenants share one migration

        if tenant.isolation_model == "bridge":
            # Schema-per-tenant: switch search_path
            with engine.connect() as conn:
                conn.execute(text(f"SET search_path TO tenant_{tenant.tenant_id}"))
                command.upgrade(alembic_cfg, "head")

        elif tenant.isolation_model == "silo":
            # Database-per-tenant: swap connection
            alembic_cfg.set_main_option("sqlalchemy.url", tenant.database_url)
            command.upgrade(alembic_cfg, "head")
```

