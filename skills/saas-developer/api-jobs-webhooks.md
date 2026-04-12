# API Design and Background Jobs

Reference file for the `saas-developer` skill. Covers tenant-scoped API endpoints, background job processing per tenant, webhook delivery systems.

## 3. Tenant-Scoped API Design

### FastAPI Router with Tenant Dependency

```python
# api/v1/projects.py
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Annotated

from middleware.tenant_context import resolve_tenant, get_current_tenant_id
from models.project import Project
from db.session import get_db

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

# ---- Pydantic schemas ----
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None

class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str | None
    tenant_id: str
    created_at: str

    model_config = {"from_attributes": True}

class PaginatedResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


# ---- Endpoints ----
@router.get("", response_model=PaginatedResponse)
async def list_projects(
    tenant: Annotated[dict, Depends(resolve_tenant)],
    db: Annotated[any, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    List projects for the current tenant.
    tenant_id filtering is automatic via the ORM event listener,
    but we explicitly include it in the count query for clarity.
    """
    tenant_id = get_current_tenant_id()
    offset = (page - 1) * page_size

    total = db.query(Project).filter(Project.tenant_id == tenant_id).count()
    items = (
        db.query(Project)
        .filter(Project.tenant_id == tenant_id)
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    tenant: Annotated[dict, Depends(resolve_tenant)],
    db: Annotated[any, Depends(get_db)],
):
    """Create a project. tenant_id is auto-injected by TenantModel."""
    project = Project(name=body.name, description=body.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    tenant: Annotated[dict, Depends(resolve_tenant)],
    db: Annotated[any, Depends(get_db)],
):
    """
    Get a single project. HARD-RULE: validate tenant ownership on the
    resource itself, not just at the API boundary.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Defense in depth: explicit ownership check even though ORM filter exists
    if project.tenant_id != get_current_tenant_id():
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    tenant: Annotated[dict, Depends(resolve_tenant)],
    db: Annotated[any, Depends(get_db)],
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == get_current_tenant_id(),
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
```

### Bulk Operations with Tenant Boundary Enforcement

```python
# api/v1/bulk.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/bulk", tags=["bulk"])

class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=100)

@router.post("/projects/delete", status_code=200)
async def bulk_delete_projects(
    body: BulkDeleteRequest,
    tenant: Annotated[dict, Depends(resolve_tenant)],
    db: Annotated[any, Depends(get_db)],
):
    """
    Bulk delete: ALWAYS scope by tenant_id to prevent cross-tenant deletion.
    Never trust the client's ID list alone.
    """
    tenant_id = get_current_tenant_id()

    # Only delete rows that belong to this tenant
    deleted = (
        db.query(Project)
        .filter(Project.id.in_(body.ids), Project.tenant_id == tenant_id)
        .delete(synchronize_session="fetch")
    )
    db.commit()

    if deleted != len(body.ids):
        # Some IDs were invalid or belonged to another tenant — log but don't reveal
        logger.warning(
            f"Bulk delete: requested {len(body.ids)}, deleted {deleted} "
            f"for tenant {tenant_id}"
        )

    return {"deleted": deleted}
```

## 4. Background Jobs

### Celery with Tenant Context Propagation

```python
# tasks/base.py
from celery import Celery, Task
import contextvars
from middleware.tenant_context import _tenant_var, get_current_tenant_id

app = Celery("saas")

class TenantTask(Task):
    """
    Base task class that propagates tenant_id through the Celery
    message headers. Every task that touches tenant data MUST use this.
    """

    def apply_async(self, args=None, kwargs=None, **options):
        # Inject tenant_id into message headers
        headers = options.get("headers", {})
        try:
            headers["tenant_id"] = get_current_tenant_id()
        except RuntimeError:
            # Allow tasks without tenant context (system tasks)
            pass
        options["headers"] = headers
        return super().apply_async(args, kwargs, **options)

    def __call__(self, *args, **kwargs):
        # Restore tenant context on the worker side
        tenant_id = self.request.get("tenant_id")
        if tenant_id:
            token = _tenant_var.set(tenant_id)
            try:
                return super().__call__(*args, **kwargs)
            finally:
                _tenant_var.reset(token)
        return super().__call__(*args, **kwargs)


# Set as default task class
app.Task = TenantTask


# ---- Example tasks ----
@app.task(bind=True)
def generate_report(self, report_type: str):
    """Runs in tenant context automatically via TenantTask."""
    tenant_id = get_current_tenant_id()
    # All DB queries scoped to this tenant
    data = db.query(Order).filter(Order.status == "completed").all()
    # ... generate report ...


@app.task(bind=True)
def bulk_import(self, file_key: str, row_count: int):
    """Long-running import — uses tenant context for storage + DB."""
    tenant_id = get_current_tenant_id()
    file_data = storage.download(f"tenant-{tenant_id}/imports/{file_key}")
    # ... process rows ...
```

### Fair Queue Routing (Prevent Tenant Starvation)

```python
# tasks/routing.py
"""
Route tasks to queues based on tenant plan tier.
Enterprise tenants get dedicated queues.
Starter/Pro tenants share queues with weighted fair scheduling.
"""

app.conf.task_routes = {
    "tasks.generate_report": {"queue": "reports"},
    "tasks.bulk_import": {"queue": "imports"},
    "tasks.send_email": {"queue": "notifications"},
}

class TenantQueueRouter:
    """Dynamic queue routing based on tenant tier."""

    # Per-tier rate limits (tasks per minute)
    TIER_RATE_LIMITS = {
        "starter": 10,
        "pro": 50,
        "enterprise": 500,
    }

    def route_for_task(self, name, args, kwargs, task_id, **kw):
        headers = kw.get("headers", {})
        tenant_id = headers.get("tenant_id")
        if not tenant_id:
            return {"queue": "default"}

        tenant = tenant_registry.get(tenant_id)
        plan = tenant.get("plan_id", "starter")

        if plan == "enterprise":
            # Dedicated queue per enterprise tenant
            return {"queue": f"enterprise-{tenant_id[:8]}"}

        # Shared queue with rate limiting via Celery rate_limit
        return {
            "queue": f"{plan}-tasks",
            "rate_limit": f"{self.TIER_RATE_LIMITS[plan]}/m",
        }

app.conf.task_routes = [TenantQueueRouter()]


# ---- Worker configuration for fair scheduling ----
# celeryconfig.py
worker_prefetch_multiplier = 1     # Fetch one task at a time (prevents hoarding)
task_acks_late = True              # Ack after completion (enables redelivery)
worker_concurrency = 4             # Per worker
task_time_limit = 300              # 5-minute hard limit
task_soft_time_limit = 270         # Soft limit triggers SoftTimeLimitExceeded
```

### Dead Letter Handling Per Tenant

```python
# tasks/dead_letter.py
from celery.signals import task_failure, task_retry

@task_failure.connect
def on_task_failure(sender, task_id, exception, args, kwargs, traceback, einfo, **kw):
    """Log failed tasks per tenant for visibility and retry management."""
    tenant_id = sender.request.get("tenant_id", "system")

    dead_letter = DeadLetterEntry(
        tenant_id=tenant_id,
        task_name=sender.name,
        task_id=task_id,
        args=str(args),
        kwargs=str(kwargs),
        exception_type=type(exception).__name__,
        exception_message=str(exception),
        traceback=str(einfo),
        created_at=datetime.utcnow(),
        retry_count=sender.request.retries,
    )
    db.add(dead_letter)
    db.commit()

    # Alert tenant admin if critical task fails
    if sender.name in CRITICAL_TASKS:
        notification_service.send(
            tenant_id=tenant_id,
            template="task_failure",
            task_name=sender.name,
            error=str(exception),
        )
```

## 5. Webhook Delivery System

### Webhook Registration and Event Dispatch

```python
# models/webhook.py
from sqlalchemy import Column, Integer, String, JSON, Boolean, DateTime
from models.base import TenantModel
import secrets

class WebhookEndpoint(TenantModel):
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True)
    url = Column(String(2048), nullable=False)
    description = Column(String(500))
    signing_secret = Column(String(64), nullable=False)
    subscribed_events = Column(JSON, default=list)  # ["project.created", "task.completed"]
    is_active = Column(Boolean, default=True)
    failure_count = Column(Integer, default=0)
    last_delivery_at = Column(DateTime)

    @classmethod
    def create_for_tenant(cls, tenant_id: str, url: str, events: list[str], description: str = ""):
        return cls(
            tenant_id=tenant_id,
            url=url,
            description=description,
            signing_secret=secrets.token_hex(32),
            subscribed_events=events,
        )


class WebhookDelivery(TenantModel):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True)
    endpoint_id = Column(Integer, nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(20), default="pending")  # pending, delivered, failed
    status_code = Column(Integer)
    attempts = Column(Integer, default=0)
    next_retry_at = Column(DateTime)
    error_message = Column(String(1000))
    delivered_at = Column(DateTime)
```

### Dispatch with Exponential Backoff and HMAC Signing

```python
# services/webhook_dispatcher.py
import hmac
import hashlib
import json
import time
from datetime import datetime, timedelta
import httpx

class WebhookDispatcher:
    """
    Delivers webhook events to tenant-configured endpoints.
    Retry schedule: 1m, 5m, 30m, 2h, 24h (5 retries max).
    Auto-disables endpoint after 10 consecutive failures.
    """

    RETRY_DELAYS_SECONDS = [60, 300, 1800, 7200, 86400]
    MAX_CONSECUTIVE_FAILURES = 10
    DELIVERY_TIMEOUT = 30  # seconds

    def dispatch_event(self, tenant_id: str, event_type: str, payload: dict):
        """Fan out event to all active endpoints subscribed to this event type."""
        endpoints = (
            db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.is_active == True,
            )
            .all()
        )

        for endpoint in endpoints:
            if event_type not in endpoint.subscribed_events:
                continue

            delivery = WebhookDelivery(
                tenant_id=tenant_id,
                endpoint_id=endpoint.id,
                event_type=event_type,
                payload=self._build_payload(event_type, payload, endpoint),
            )
            db.add(delivery)
            db.commit()

            # Queue for async delivery
            deliver_webhook.apply_async(
                args=[delivery.id],
                countdown=0,
            )

    def _build_payload(self, event_type: str, data: dict, endpoint) -> dict:
        return {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": data,
        }

    @staticmethod
    def sign_payload(payload_bytes: bytes, secret: str) -> str:
        """HMAC-SHA256 signature for webhook verification."""
        return "sha256=" + hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def verify_signature(payload_bytes: bytes, secret: str, received_sig: str) -> bool:
        expected = WebhookDispatcher.sign_payload(payload_bytes, secret)
        return hmac.compare_digest(expected, received_sig)


@app.task(bind=True, max_retries=5)
def deliver_webhook(self, delivery_id: int):
    """Attempt webhook delivery with exponential backoff."""
    delivery = db.query(WebhookDelivery).get(delivery_id)
    endpoint = db.query(WebhookEndpoint).get(delivery.endpoint_id)

    if not endpoint.is_active:
        delivery.status = "skipped"
        db.commit()
        return

    payload_bytes = json.dumps(delivery.payload).encode("utf-8")
    signature = WebhookDispatcher.sign_payload(payload_bytes, endpoint.signing_secret)

    try:
        response = httpx.post(
            endpoint.url,
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Webhook-Event": delivery.event_type,
                "X-Webhook-Delivery-ID": str(delivery.id),
                "X-Webhook-Timestamp": delivery.payload.get("timestamp", ""),
                "User-Agent": "SaaSApp-Webhook/1.0",
            },
            timeout=WebhookDispatcher.DELIVERY_TIMEOUT,
        )

        delivery.status_code = response.status_code
        delivery.attempts += 1

        if response.status_code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.utcnow()
            endpoint.failure_count = 0
            endpoint.last_delivery_at = datetime.utcnow()
        else:
            raise httpx.HTTPStatusError(
                f"Webhook returned {response.status_code}",
                request=response.request,
                response=response,
            )

    except Exception as e:
        delivery.attempts += 1
        delivery.error_message = str(e)[:1000]
        endpoint.failure_count += 1

        # Auto-disable after too many consecutive failures
        if endpoint.failure_count >= WebhookDispatcher.MAX_CONSECUTIVE_FAILURES:
            endpoint.is_active = False
            delivery.status = "failed"
            notification_service.send(
                tenant_id=delivery.tenant_id,
                template="webhook_endpoint_disabled",
                endpoint_url=endpoint.url,
            )
        elif self.request.retries < self.max_retries:
            delay = WebhookDispatcher.RETRY_DELAYS_SECONDS[self.request.retries]
            delivery.status = "retrying"
            delivery.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
            db.commit()
            raise self.retry(countdown=delay, exc=e)
        else:
            delivery.status = "failed"

    db.commit()
```

### Webhook Testing Endpoint

```python
# api/v1/webhooks.py
@router.post("/webhooks/test/{endpoint_id}")
async def test_webhook(
    endpoint_id: int,
    tenant: Annotated[dict, Depends(resolve_tenant)],
    db: Annotated[any, Depends(get_db)],
):
    """Send a test event to a webhook endpoint so tenants can verify their setup."""
    endpoint = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.tenant_id == get_current_tenant_id(),
    ).first()
    if not endpoint:
        raise HTTPException(404, "Webhook endpoint not found")

    test_payload = {
        "event": "webhook.test",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": {"message": "This is a test webhook delivery."},
    }

    dispatcher = WebhookDispatcher()
    payload_bytes = json.dumps(test_payload).encode("utf-8")
    signature = dispatcher.sign_payload(payload_bytes, endpoint.signing_secret)

    try:
        response = httpx.post(
            endpoint.url,
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Webhook-Event": "webhook.test",
                "User-Agent": "SaaSApp-Webhook/1.0",
            },
            timeout=10,
        )
        return {
            "success": response.status_code < 300,
            "status_code": response.status_code,
            "response_body": response.text[:500],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
```

