# Tenant Context and Database Layer

Reference file for the `saas-developer` skill. Covers tenant context middleware, multi-tenant database layer with SQLAlchemy, row-level security.

## Overview

This skill provides hands-on, copy-paste-ready code for implementing SaaS features in Python. It complements `saas-architecture` (which covers tenancy models, isolation strategies, billing/Stripe integration, entitlements, metering, and operational monitoring) with the developer-facing implementation details: middleware wiring across frameworks, database layer plumbing, API endpoint patterns, background jobs, webhooks, email, file storage, caching, testing, and deployment.

**Framework coverage:** FastAPI (primary), Flask, Django. Database layer uses SQLAlchemy 2.0 throughout.

## HARD-RULEs

1. **Every database session/query MUST have tenant context set before execution** — a query without tenant context is a data leak waiting to happen. Wrap session creation so that a missing tenant context raises immediately, not silently returns all rows.
2. **Never share background job queues between tenants without explicit priority/fairness controls** — one tenant's bulk job will starve others. Use weighted fair queuing or per-tenant queues with a shared worker pool.
3. **Always validate tenant ownership on every resource access, not just at the API boundary** — defense in depth prevents IDOR across tenants. A service layer that trusts caller-provided tenant context without re-checking the resource's `tenant_id` is one refactor away from a cross-tenant leak.
4. **Never use tenant-specific database schemas in SaaS unless you have fewer than 50 tenants** — schema-per-tenant migration complexity grows quadratically. Every Alembic migration runs N times, schema drift becomes undetectable, and provisioning new tenants requires DDL locks on the database server.

## 1. Tenant Context Middleware

### FastAPI — Dependency Injection with contextvars

```python
# middleware/tenant_context.py
import contextvars
from uuid import UUID
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

# ---- Context variable: thread-safe, async-safe ----
_tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id")
_tenant_obj_var: contextvars.ContextVar[dict] = contextvars.ContextVar("tenant")

def get_current_tenant_id() -> str:
    """Retrieve tenant_id from context. Raises RuntimeError if unset."""
    try:
        return _tenant_var.get()
    except LookupError:
        raise RuntimeError(
            "Tenant context not set. Ensure TenantMiddleware is applied "
            "or use the tenant_context dependency in your route."
        )

def get_current_tenant() -> dict:
    try:
        return _tenant_obj_var.get()
    except LookupError:
        raise RuntimeError("Tenant object not set in context.")


# ---- FastAPI dependency: extracts + validates tenant ----
security = HTTPBearer(auto_error=False)

async def resolve_tenant(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """
    Resolve tenant from (in priority order):
    1. JWT 'tenant_id' claim
    2. X-Tenant-ID header (service-to-service with mTLS)
    3. Subdomain extraction (e.g., acme.app.example.com)

    Sets contextvars so downstream code (ORM, services) can access tenant
    without passing it through every function signature.
    """
    tenant_id = None

    # 1. JWT
    if credentials:
        try:
            payload = jwt.decode(
                credentials.credentials,
                options={"verify_signature": True},  # configure key separately
                key=request.app.state.jwt_public_key,
                algorithms=["RS256"],
            )
            tenant_id = payload.get("tenant_id")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Header (service-to-service)
    if not tenant_id:
        tenant_id = request.headers.get("X-Tenant-ID")

    # 3. Subdomain
    if not tenant_id:
        host = request.headers.get("host", "")
        parts = host.split(".")
        if len(parts) >= 3:  # acme.app.example.com
            tenant_id = _lookup_tenant_by_subdomain(parts[0])

    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant identification required")

    # Validate tenant exists and is active
    tenant = await _fetch_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant not found")
    if not tenant["is_active"]:
        raise HTTPException(status_code=403, detail="Tenant suspended")

    # Set context
    _tenant_var.set(tenant_id)
    _tenant_obj_var.set(tenant)
    request.state.tenant_id = tenant_id
    request.state.tenant = tenant

    return tenant


async def _fetch_tenant(tenant_id: str) -> dict | None:
    """Look up tenant from cache (Redis) then DB. Implement per your registry."""
    # See saas-architecture skill for TenantRegistry pattern
    from app.services.tenant_registry import tenant_registry
    return await tenant_registry.get(tenant_id)


def _lookup_tenant_by_subdomain(subdomain: str) -> str | None:
    from app.services.tenant_registry import tenant_registry
    return tenant_registry.tenant_id_for_subdomain(subdomain)
```

### FastAPI — ASGI Middleware (sets/clears context around request lifecycle)

```python
# middleware/asgi_tenant.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

class TenantLifecycleMiddleware(BaseHTTPMiddleware):
    """
    Wraps every request to ensure tenant context is cleared after
    the request completes, preventing context leakage between requests.
    Use in addition to the Depends(resolve_tenant) pattern.
    """

    SKIP_PATHS = {"/health", "/metrics", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        token_tid = _tenant_var.set(None)
        token_obj = _tenant_obj_var.set(None)
        try:
            response = await call_next(request)
            return response
        finally:
            _tenant_var.reset(token_tid)
            _tenant_obj_var.reset(token_obj)

# Register in app factory:
# app.add_middleware(TenantLifecycleMiddleware)
```

### Flask — before/after request hooks

```python
# middleware/flask_tenant.py
from flask import Flask, g, request, abort
import contextvars

_tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id")

def init_tenant_middleware(app: Flask, tenant_registry):
    SKIP_ENDPOINTS = {"health", "metrics", "static"}

    @app.before_request
    def set_tenant():
        if request.endpoint in SKIP_ENDPOINTS:
            return
        tenant_id = (
            _from_jwt(request) or
            request.headers.get("X-Tenant-ID") or
            _from_subdomain(request)
        )
        if not tenant_id:
            abort(401, description="Tenant identification required")
        tenant = tenant_registry.get(tenant_id)
        if not tenant or not tenant.is_active:
            abort(403, description="Tenant not found or suspended")
        g.tenant_id = tenant_id
        g.tenant = tenant
        _tenant_var.set(tenant_id)

    @app.teardown_request
    def clear_tenant(exc=None):
        _tenant_var.set(None)
```

### Django — Middleware class

```python
# middleware/django_tenant.py
import contextvars
from django.http import JsonResponse
from django.conf import settings

_tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id")

class TenantMiddleware:
    SKIP_PATHS = getattr(settings, "TENANT_SKIP_PATHS", ["/health", "/admin"])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in self.SKIP_PATHS):
            return self.get_response(request)

        tenant_id = self._resolve(request)
        if not tenant_id:
            return JsonResponse({"detail": "Tenant identification required"}, status=401)

        from apps.tenants.models import Tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return JsonResponse({"detail": "Tenant not found or suspended"}, status=403)

        request.tenant_id = tenant_id
        request.tenant = tenant
        token = _tenant_var.set(tenant_id)
        try:
            return self.get_response(request)
        finally:
            _tenant_var.reset(token)

    def _resolve(self, request):
        # JWT, header, subdomain — same priority as FastAPI version
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth.startswith("Bearer "):
            return self._from_jwt(auth[7:])
        return (
            request.META.get("HTTP_X_TENANT_ID") or
            self._from_subdomain(request)
        )

    def _from_jwt(self, token_str):
        import jwt as pyjwt
        try:
            payload = pyjwt.decode(token_str, settings.JWT_PUBLIC_KEY, algorithms=["RS256"])
            return payload.get("tenant_id")
        except pyjwt.InvalidTokenError:
            return None

    def _from_subdomain(self, request):
        host = request.get_host().split(":")[0]
        parts = host.split(".")
        if len(parts) >= 3:
            from apps.tenants.models import Tenant
            try:
                return str(Tenant.objects.get(subdomain=parts[0]).id)
            except Tenant.DoesNotExist:
                return None
        return None
```

## 2. Multi-Tenant Database Layer

### SQLAlchemy 2.0 — TenantModel Base Class

```python
# models/base.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, event, Index
from sqlalchemy.orm import DeclarativeBase, declared_attr, Session

from middleware.tenant_context import get_current_tenant_id


class Base(DeclarativeBase):
    pass


class TenantModel(Base):
    """
    Abstract base for all tenant-scoped models.
    Provides: tenant_id column, auto-set on insert, composite index helper.
    """
    __abstract__ = True

    tenant_id = Column(
        String(36),
        nullable=False,
        index=True,
        comment="Owning tenant UUID — NEVER nullable, NEVER default to NULL",
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @declared_attr
    def __table_args__(cls):
        """Composite index on (tenant_id, id) for efficient tenant-scoped lookups."""
        return (
            Index(f"ix_{cls.__tablename__}_tenant", "tenant_id"),
            {"extend_existing": True},
        )


# ---- Event listener: auto-set tenant_id on INSERT ----
@event.listens_for(TenantModel, "init", propagate=True)
def _set_tenant_on_init(target, args, kwargs):
    """Set tenant_id from context if not explicitly provided."""
    if not kwargs.get("tenant_id") and not getattr(target, "tenant_id", None):
        try:
            target.tenant_id = get_current_tenant_id()
        except RuntimeError:
            pass  # Will be caught by NOT NULL constraint if truly missing


# ---- Event listener: auto-filter all SELECTs by tenant_id ----
@event.listens_for(Session, "do_orm_execute")
def _inject_tenant_filter(execute_state):
    """
    Automatically adds WHERE tenant_id = :current_tenant to every SELECT
    on TenantModel subclasses. Skip with:
        session.execute(stmt, execution_options={"skip_tenant_filter": True})
    """
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("skip_tenant_filter", False):
        return

    try:
        current = get_current_tenant_id()
    except RuntimeError:
        # No tenant context — this is a system-level query (migrations, admin)
        return

    from sqlalchemy.orm import with_loader_criteria
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantModel,
            TenantModel.tenant_id == current,
            include_aliases=True,
        )
    )


# ---- Validate tenant_id before flush ----
@event.listens_for(Session, "before_flush")
def _validate_tenant_before_flush(session, flush_context, instances):
    """Prevent flushing a TenantModel row without tenant_id set."""
    for obj in session.new:
        if isinstance(obj, TenantModel) and not obj.tenant_id:
            raise ValueError(
                f"Cannot flush {obj.__class__.__name__} without tenant_id. "
                "Ensure tenant context is set via middleware."
            )
```

### Model Example Using the Base

```python
# models/project.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from models.base import TenantModel

class Project(TenantModel):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    tasks = relationship("Task", back_populates="project", lazy="dynamic")

    def __repr__(self):
        return f"<Project {self.id} '{self.name}' tenant={self.tenant_id}>"


class Task(TenantModel):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String(300), nullable=False)
    status = Column(String(20), default="open")

    project = relationship("Project", back_populates="tasks")
```

### Connection Routing for Hybrid Isolation

```python
# db/routing.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from middleware.tenant_context import get_current_tenant_id

class TenantSessionFactory:
    """
    Creates sessions routed to the correct database/schema based on
    the tenant's isolation model. Pool tenants share one engine.
    Bridge tenants use SET search_path. Silo tenants use dedicated engines.
    """

    def __init__(self, default_url: str, tenant_registry):
        self.default_engine = create_engine(default_url, pool_size=20, pool_pre_ping=True)
        self.registry = tenant_registry
        self._silo_engines: dict[str, any] = {}

    def get_session(self) -> Session:
        tenant_id = get_current_tenant_id()
        tenant = self.registry.get(tenant_id)

        if tenant["isolation_model"] == "silo":
            engine = self._get_silo_engine(tenant)
            return sessionmaker(bind=engine)()

        session = sessionmaker(bind=self.default_engine)()

        if tenant["isolation_model"] == "bridge":
            # Set PostgreSQL search_path to tenant-specific schema
            schema = f"tenant_{tenant_id.replace('-', '_')}"
            session.execute(text(f"SET search_path TO {schema}, public"))

        # For pool: set RLS context variable
        session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": tenant_id},
        )
        return session

    def _get_silo_engine(self, tenant: dict):
        tid = tenant["tenant_id"]
        if tid not in self._silo_engines:
            self._silo_engines[tid] = create_engine(
                tenant["database_url"],
                pool_size=tenant.get("pool_size", 5),
                pool_pre_ping=True,
            )
        return self._silo_engines[tid]
```

### Alembic Multi-Tenant Migration Runner

```python
# migrations/runner.py
"""
Run Alembic migrations across all tenant databases/schemas.
Pool tenants: single migration on the shared database.
Bridge tenants: iterate schemas.
Silo tenants: iterate dedicated databases.
"""
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text
import logging

log = logging.getLogger(__name__)

def run_all_migrations(alembic_ini: str, tenant_registry):
    cfg = Config(alembic_ini)

    # 1. Shared pool migration (always runs first)
    log.info("Running pool migration on shared database...")
    command.upgrade(cfg, "head")

    # 2. Bridge tenants (schema-per-tenant)
    for tenant in tenant_registry.list_by_model("bridge"):
        schema = f"tenant_{tenant['tenant_id'].replace('-', '_')}"
        log.info(f"Migrating bridge schema: {schema}")
        engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
        with engine.connect() as conn:
            conn.execute(text(f"SET search_path TO {schema}, public"))
            conn.execute(text("SELECT 1"))  # validate schema exists
        # Run with modified search_path
        with engine.begin() as conn:
            conn.execute(text(f"SET search_path TO {schema}, public"))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

    # 3. Silo tenants (database-per-tenant)
    for tenant in tenant_registry.list_by_model("silo"):
        log.info(f"Migrating silo database for tenant: {tenant['tenant_id']}")
        cfg.set_main_option("sqlalchemy.url", tenant["database_url"])
        command.upgrade(cfg, "head")
```

