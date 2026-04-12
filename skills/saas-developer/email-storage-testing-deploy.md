# Email, Storage, Caching, Testing, and Deployment

Reference file for the `saas-developer` skill. Covers email/notification systems, file storage isolation, caching strategies, testing multi-tenant code, and deployment patterns.

## 6. Email and Notification System

### Tenant-Branded Email Templates

```python
# services/email.py
from dataclasses import dataclass
from jinja2 import Environment, FileSystemLoader
import boto3

@dataclass
class TenantBranding:
    tenant_id: str
    company_name: str
    logo_url: str
    primary_color: str       # hex, e.g., "#2563EB"
    from_name: str           # "Acme Corp via SaaSApp"
    from_email: str          # "notifications@acme.saasapp.com" or custom
    reply_to: str | None
    support_url: str

class TenantEmailService:
    """
    Send branded emails per tenant.
    Uses Jinja2 templates with tenant branding variables.
    Delivery via SES (easily swappable to SendGrid/Postmark).
    """

    def __init__(self):
        self.jinja = Environment(loader=FileSystemLoader("templates/email"))
        self.ses = boto3.client("ses", region_name="us-east-1")

    def send(
        self,
        tenant_id: str,
        to_email: str,
        template_name: str,
        context: dict,
    ):
        branding = self._get_branding(tenant_id)
        template = self.jinja.get_template(f"{template_name}.html")

        html = template.render(
            branding=branding,
            **context,
        )

        self.ses.send_email(
            Source=f"{branding.from_name} <{branding.from_email}>",
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": context.get("subject", "Notification")},
                "Body": {"Html": {"Data": html}},
            },
            ReplyToAddresses=[branding.reply_to] if branding.reply_to else [],
            Tags=[
                {"Name": "tenant_id", "Value": tenant_id},
                {"Name": "template", "Value": template_name},
            ],
        )

    def _get_branding(self, tenant_id: str) -> TenantBranding:
        cached = redis.get(f"branding:{tenant_id}")
        if cached:
            return TenantBranding(**json.loads(cached))
        branding = db.query(TenantBrandingModel).filter_by(tenant_id=tenant_id).first()
        if not branding:
            return self._default_branding(tenant_id)
        result = TenantBranding(
            tenant_id=tenant_id,
            company_name=branding.company_name,
            logo_url=branding.logo_url,
            primary_color=branding.primary_color or "#2563EB",
            from_name=branding.from_name or f"{branding.company_name} via SaaSApp",
            from_email=branding.from_email or f"noreply@{tenant_id}.saasapp.com",
            reply_to=branding.reply_to,
            support_url=branding.support_url or "https://saasapp.com/support",
        )
        redis.setex(f"branding:{tenant_id}", 600, json.dumps(result.__dict__))
        return result

    def _default_branding(self, tenant_id: str) -> TenantBranding:
        return TenantBranding(
            tenant_id=tenant_id,
            company_name="SaaSApp",
            logo_url="https://saasapp.com/logo.png",
            primary_color="#2563EB",
            from_name="SaaSApp",
            from_email="noreply@saasapp.com",
            reply_to=None,
            support_url="https://saasapp.com/support",
        )
```

### Notification Preferences and In-App Notifications

```python
# services/notifications.py
from enum import Enum

class NotificationChannel(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    SLACK = "slack"     # For enterprise tenants

class NotificationService:
    """
    Multi-channel notification with per-user preferences.
    Respects both user preferences and tenant-level settings.
    """

    DEFAULT_PREFERENCES = {
        "task.assigned": [NotificationChannel.EMAIL, NotificationChannel.IN_APP],
        "task.completed": [NotificationChannel.IN_APP],
        "payment.failed": [NotificationChannel.EMAIL],
        "usage.threshold_80": [NotificationChannel.EMAIL, NotificationChannel.IN_APP],
        "webhook.endpoint_disabled": [NotificationChannel.EMAIL],
        "security.login_new_device": [NotificationChannel.EMAIL],
    }

    def send(self, tenant_id: str, template: str, user_id: str = None, **context):
        """
        Send notification to user (or all admins if user_id is None)
        via their preferred channels.
        """
        recipients = self._resolve_recipients(tenant_id, user_id)

        for recipient in recipients:
            channels = self._get_channels(recipient["user_id"], template)

            for channel in channels:
                if channel == NotificationChannel.EMAIL:
                    email_service.send(
                        tenant_id=tenant_id,
                        to_email=recipient["email"],
                        template_name=template,
                        context=context,
                    )
                elif channel == NotificationChannel.IN_APP:
                    self._create_in_app(tenant_id, recipient["user_id"], template, context)
                elif channel == NotificationChannel.SLACK:
                    self._send_slack(tenant_id, recipient, template, context)

    def _create_in_app(self, tenant_id: str, user_id: str, template: str, context: dict):
        notification = InAppNotification(
            tenant_id=tenant_id,
            user_id=user_id,
            notification_type=template,
            title=self._render_title(template, context),
            body=self._render_body(template, context),
            read=False,
        )
        db.add(notification)
        db.commit()

        # Push via WebSocket if user is connected
        ws_manager.push(user_id, {
            "type": "notification",
            "data": {"id": notification.id, "title": notification.title},
        })

    def _get_channels(self, user_id: str, template: str) -> list[NotificationChannel]:
        prefs = db.query(NotificationPreference).filter_by(
            user_id=user_id, notification_type=template
        ).first()
        if prefs:
            return prefs.channels
        return self.DEFAULT_PREFERENCES.get(template, [NotificationChannel.IN_APP])
```

## 7. File Storage Isolation

### S3 with Tenant-Prefixed Keys

```python
# services/storage.py
import boto3
from botocore.exceptions import ClientError
import uuid

class TenantStorageService:
    """
    S3 storage with strict tenant isolation via key prefixes.
    Layout: s3://bucket/tenant-{tenant_id}/{category}/{filename}

    All operations are scoped to the tenant's prefix.
    Pre-signed URLs are generated with tenant validation.
    """

    CATEGORIES = {"uploads", "exports", "avatars", "attachments", "imports"}

    def __init__(self, bucket: str, region: str = "us-east-1"):
        self.s3 = boto3.client("s3", region_name=region)
        self.bucket = bucket

    def _tenant_prefix(self, tenant_id: str) -> str:
        return f"tenant-{tenant_id}"

    def _build_key(self, tenant_id: str, category: str, filename: str) -> str:
        if category not in self.CATEGORIES:
            raise ValueError(f"Invalid category: {category}")
        # Prevent path traversal
        safe_name = filename.replace("..", "").replace("/", "_")
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        return f"{self._tenant_prefix(tenant_id)}/{category}/{unique_name}"

    def upload(
        self,
        tenant_id: str,
        category: str,
        filename: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
        max_size_mb: int = None,
    ) -> str:
        """Upload file and return the S3 key."""
        if max_size_mb and len(file_data) > max_size_mb * 1024 * 1024:
            raise ValueError(f"File exceeds {max_size_mb}MB limit")

        key = self._build_key(tenant_id, category, filename)
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=file_data,
            ContentType=content_type,
            Metadata={"tenant_id": tenant_id},
            ServerSideEncryption="aws:kms",
            # Use tenant-specific KMS key for enterprise tenants:
            # SSEKMSKeyId=encryption_service.get_or_create_key(tenant_id),
        )
        return key

    def generate_presigned_upload_url(
        self,
        tenant_id: str,
        category: str,
        filename: str,
        content_type: str,
        expires_in: int = 3600,
    ) -> dict:
        """Generate a pre-signed URL for direct browser upload."""
        key = self._build_key(tenant_id, category, filename)
        url = self.s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "Metadata": {"tenant_id": tenant_id},
            },
            ExpiresIn=expires_in,
        )
        return {"upload_url": url, "key": key}

    def generate_presigned_download_url(
        self,
        tenant_id: str,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        """
        Generate download URL. CRITICAL: Validate the key belongs to
        this tenant before generating a signed URL.
        """
        # Defense in depth: verify key starts with tenant's prefix
        expected_prefix = self._tenant_prefix(tenant_id)
        if not key.startswith(expected_prefix + "/"):
            raise PermissionError(
                f"Key '{key}' does not belong to tenant {tenant_id}"
            )

        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete(self, tenant_id: str, key: str):
        """Delete a file, with tenant ownership validation."""
        expected_prefix = self._tenant_prefix(tenant_id)
        if not key.startswith(expected_prefix + "/"):
            raise PermissionError(f"Key '{key}' does not belong to tenant {tenant_id}")
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def list_files(self, tenant_id: str, category: str, max_keys: int = 100) -> list[dict]:
        """List files in a tenant's category folder."""
        prefix = f"{self._tenant_prefix(tenant_id)}/{category}/"
        response = self.s3.list_objects_v2(
            Bucket=self.bucket, Prefix=prefix, MaxKeys=max_keys
        )
        return [
            {
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            }
            for obj in response.get("Contents", [])
        ]

    def get_tenant_usage_bytes(self, tenant_id: str) -> int:
        """Calculate total storage used by a tenant (for quota enforcement)."""
        prefix = self._tenant_prefix(tenant_id) + "/"
        total = 0
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                total += obj["Size"]
        return total
```

### Upload Size Limits Per Plan

```python
# middleware/upload_limits.py
PLAN_UPLOAD_LIMITS = {
    "starter":    {"max_file_mb": 10,  "max_storage_gb": 5},
    "pro":        {"max_file_mb": 100, "max_storage_gb": 50},
    "enterprise": {"max_file_mb": 500, "max_storage_gb": 500},
}

async def enforce_upload_limit(
    tenant: dict = Depends(resolve_tenant),
):
    """FastAPI dependency that calculates remaining storage quota."""
    plan = tenant.get("plan_id", "starter")
    limits = PLAN_UPLOAD_LIMITS[plan]
    current_usage = storage_service.get_tenant_usage_bytes(tenant["tenant_id"])
    max_bytes = limits["max_storage_gb"] * 1024 * 1024 * 1024

    if current_usage >= max_bytes:
        raise HTTPException(
            status_code=429,
            detail=f"Storage quota exceeded ({limits['max_storage_gb']}GB). Upgrade your plan.",
        )

    return {
        "max_file_mb": limits["max_file_mb"],
        "remaining_bytes": max_bytes - current_usage,
    }
```

## 8. Caching Strategies

### Redis Key Namespacing

```python
# services/cache.py
import json
from typing import Any
from datetime import timedelta
import redis

class TenantCache:
    """
    Redis cache with tenant-scoped key namespacing.

    Key format: tenant:{tenant_id}:{resource_type}:{resource_key}

    Prevents cross-tenant cache pollution and enables per-tenant
    cache invalidation without affecting other tenants.
    """

    # Per-plan TTL policies
    PLAN_TTL = {
        "starter":    timedelta(minutes=5),
        "pro":        timedelta(minutes=15),
        "enterprise": timedelta(minutes=30),
    }

    def __init__(self, redis_client: redis.Redis, default_ttl: timedelta = timedelta(minutes=10)):
        self.redis = redis_client
        self.default_ttl = default_ttl

    def _key(self, tenant_id: str, resource_type: str, resource_key: str) -> str:
        return f"tenant:{tenant_id}:{resource_type}:{resource_key}"

    def get(self, tenant_id: str, resource_type: str, resource_key: str) -> Any | None:
        raw = self.redis.get(self._key(tenant_id, resource_type, resource_key))
        return json.loads(raw) if raw else None

    def set(
        self,
        tenant_id: str,
        resource_type: str,
        resource_key: str,
        value: Any,
        ttl: timedelta | None = None,
    ):
        key = self._key(tenant_id, resource_type, resource_key)
        serialized = json.dumps(value, default=str)
        self.redis.setex(key, int((ttl or self.default_ttl).total_seconds()), serialized)

    def delete(self, tenant_id: str, resource_type: str, resource_key: str):
        self.redis.delete(self._key(tenant_id, resource_type, resource_key))

    def invalidate_resource_type(self, tenant_id: str, resource_type: str):
        """Invalidate all cached entries of a resource type for a tenant."""
        pattern = f"tenant:{tenant_id}:{resource_type}:*"
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                self.redis.delete(*keys)
            if cursor == 0:
                break

    def invalidate_tenant(self, tenant_id: str):
        """
        Nuclear option: invalidate ALL cache for a tenant.
        Use on plan change, tenant suspension, or data migration.
        """
        pattern = f"tenant:{tenant_id}:*"
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=500)
            if keys:
                self.redis.delete(*keys)
            if cursor == 0:
                break

    def get_or_set(
        self,
        tenant_id: str,
        resource_type: str,
        resource_key: str,
        factory_fn,
        ttl: timedelta | None = None,
    ) -> Any:
        """Cache-aside pattern: return cached value or compute + cache."""
        cached = self.get(tenant_id, resource_type, resource_key)
        if cached is not None:
            return cached
        value = factory_fn()
        self.set(tenant_id, resource_type, resource_key, value, ttl)
        return value


# ---- Plan change hook: invalidate cache ----
def on_plan_change(tenant_id: str, old_plan: str, new_plan: str):
    """Called when a tenant upgrades/downgrades. Clears all tenant cache
    to ensure new entitlements and rate limits take effect immediately."""
    tenant_cache.invalidate_tenant(tenant_id)
    tenant_registry.invalidate(tenant_id)  # Also invalidate tenant metadata cache
```

### Preventing Noisy-Neighbor Cache Eviction

```python
# services/cache_limits.py
"""
Prevent one tenant from filling Redis and evicting other tenants' cache.
Uses Redis memory policies + application-level key counting.
"""

class TenantCacheQuota:
    """Enforce per-tenant cache entry limits to prevent one tenant
    from dominating shared Redis memory."""

    PLAN_MAX_KEYS = {
        "starter":    1_000,
        "pro":        10_000,
        "enterprise": 100_000,
    }

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def check_quota(self, tenant_id: str, plan: str) -> bool:
        """Return True if tenant is within their cache key quota."""
        count = self._count_keys(tenant_id)
        max_keys = self.PLAN_MAX_KEYS.get(plan, 1_000)
        return count < max_keys

    def _count_keys(self, tenant_id: str) -> int:
        """Count keys matching tenant prefix. Uses SCAN, not KEYS."""
        count = 0
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(
                cursor, match=f"tenant:{tenant_id}:*", count=500
            )
            count += len(keys)
            if cursor == 0:
                break
        return count

    def evict_lru(self, tenant_id: str, count: int = 100):
        """Evict oldest keys for a tenant when they hit quota."""
        pattern = f"tenant:{tenant_id}:*"
        keys_with_ttl = []
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=500)
            for key in keys:
                ttl = self.redis.ttl(key)
                keys_with_ttl.append((key, ttl))
            if cursor == 0:
                break

        # Sort by TTL ascending (shortest remaining = oldest)
        keys_with_ttl.sort(key=lambda x: x[1])
        to_delete = [k for k, _ in keys_with_ttl[:count]]
        if to_delete:
            self.redis.delete(*to_delete)
```

## 9. Testing Multi-Tenant Code

### Pytest Fixtures for Tenant Setup/Teardown

```python
# tests/conftest.py
import pytest
from uuid import uuid4
from middleware.tenant_context import _tenant_var
from models.base import Base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = "postgresql://test:test@localhost:5432/saas_test"

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)

@pytest.fixture
def db(engine):
    """Provide a transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def tenant_id():
    """Generate a unique tenant_id for this test."""
    return str(uuid4())

@pytest.fixture
def other_tenant_id():
    """Second tenant for cross-tenant isolation tests."""
    return str(uuid4())

@pytest.fixture
def tenant_context(tenant_id):
    """
    Set tenant context for the duration of the test.
    All ORM queries will be automatically scoped to this tenant.
    """
    token = _tenant_var.set(tenant_id)
    yield tenant_id
    _tenant_var.reset(token)

@pytest.fixture
def tenant_factory(db):
    """Create tenant records in the test database."""
    def _create(tenant_id: str, plan: str = "pro", is_active: bool = True):
        db.execute(
            text("""
                INSERT INTO tenants (tenant_id, name, plan_id, is_active, isolation_model)
                VALUES (:tid, :name, :plan, :active, 'pool')
            """),
            {"tid": tenant_id, "name": f"Test Tenant {tenant_id[:8]}", "plan": plan, "active": is_active},
        )
        db.flush()
        return tenant_id
    return _create
```

### Testing Tenant Isolation (Cross-Tenant Leak Detection)

```python
# tests/test_tenant_isolation.py
import pytest
from models.project import Project
from middleware.tenant_context import _tenant_var

class TestTenantIsolation:
    """
    Verify that tenant data isolation works at every layer.
    These tests catch regressions where a query accidentally omits
    the tenant_id filter.
    """

    def test_query_returns_only_own_tenant_data(
        self, db, tenant_context, other_tenant_id
    ):
        """Projects from other tenants must be invisible."""
        tenant_id = tenant_context

        # Create project for current tenant
        own_project = Project(tenant_id=tenant_id, name="My Project", owner_id=1)
        db.add(own_project)

        # Create project for OTHER tenant (bypass auto-filter)
        other_project = Project(tenant_id=other_tenant_id, name="Other Project", owner_id=2)
        db.add(other_project)
        db.flush()

        # Query should only return current tenant's project
        results = db.query(Project).all()
        assert len(results) == 1
        assert results[0].tenant_id == tenant_id
        assert results[0].name == "My Project"

    def test_get_by_id_rejects_other_tenant(
        self, db, tenant_context, other_tenant_id
    ):
        """Direct ID lookup must not return another tenant's record."""
        other_project = Project(tenant_id=other_tenant_id, name="Secret", owner_id=1)
        db.add(other_project)
        db.flush()

        result = db.query(Project).filter(Project.id == other_project.id).first()
        assert result is None, "Cross-tenant data leak: got another tenant's project by ID"

    def test_insert_auto_sets_tenant_id(self, db, tenant_context):
        """New records must automatically get the current tenant_id."""
        project = Project(name="Auto Tenant", owner_id=1)
        db.add(project)
        db.flush()

        assert project.tenant_id == tenant_context

    def test_insert_without_tenant_context_raises(self, db):
        """Creating a tenant-scoped record without context must fail."""
        _tenant_var.set(None)
        project = Project(name="No Context", owner_id=1)
        db.add(project)
        with pytest.raises(Exception):  # ValueError or IntegrityError
            db.flush()

    def test_bulk_delete_respects_tenant_boundary(
        self, db, tenant_context, other_tenant_id
    ):
        """Bulk operations must never touch another tenant's data."""
        own = Project(tenant_id=tenant_context, name="Mine", owner_id=1)
        other = Project(tenant_id=other_tenant_id, name="Theirs", owner_id=2)
        db.add_all([own, other])
        db.flush()

        # Delete all projects (should only affect current tenant)
        db.query(Project).delete(synchronize_session="fetch")
        db.flush()

        # Switch context to other tenant and verify their data survived
        _tenant_var.set(other_tenant_id)
        results = db.query(Project).all()
        assert len(results) == 1
        assert results[0].name == "Theirs"

    def test_count_is_tenant_scoped(self, db, tenant_context, other_tenant_id):
        """Aggregate queries must respect tenant boundaries."""
        db.add(Project(tenant_id=tenant_context, name="A", owner_id=1))
        db.add(Project(tenant_id=tenant_context, name="B", owner_id=1))
        db.add(Project(tenant_id=other_tenant_id, name="C", owner_id=2))
        db.flush()

        count = db.query(Project).count()
        assert count == 2, f"Expected 2, got {count} — tenant filter missing on COUNT"
```

### factory_boy with Tenant Context

```python
# tests/factories.py
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models.project import Project, Task
from middleware.tenant_context import get_current_tenant_id

class ProjectFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Project
        sqlalchemy_session_persistence = "commit"

    name = factory.Sequence(lambda n: f"Project {n}")
    description = factory.Faker("sentence")
    owner_id = factory.Sequence(lambda n: n + 1)

    @factory.lazy_attribute
    def tenant_id(self):
        """Pull tenant_id from context, allowing override."""
        try:
            return get_current_tenant_id()
        except RuntimeError:
            raise ValueError(
                "ProjectFactory requires tenant context. "
                "Use the tenant_context fixture or pass tenant_id explicitly."
            )


class TaskFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Task
        sqlalchemy_session_persistence = "commit"

    title = factory.Sequence(lambda n: f"Task {n}")
    status = "open"
    project = factory.SubFactory(ProjectFactory)

    @factory.lazy_attribute
    def tenant_id(self):
        try:
            return get_current_tenant_id()
        except RuntimeError:
            return self.project.tenant_id


# Usage in tests:
# def test_something(tenant_context, db):
#     ProjectFactory._meta.sqlalchemy_session = db
#     projects = ProjectFactory.create_batch(5)
#     assert all(p.tenant_id == tenant_context for p in projects)
```

### Integration Test: Full Request Lifecycle

```python
# tests/test_api_integration.py
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def auth_headers(tenant_id):
    """Create a JWT with tenant_id claim for test requests."""
    import jwt
    token = jwt.encode(
        {"tenant_id": tenant_id, "user_id": "test-user", "role": "admin"},
        "test-secret",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}

class TestProjectAPI:
    async def test_create_and_list_projects(self, client, auth_headers, tenant_id):
        # Create
        resp = await client.post(
            "/api/v1/projects",
            json={"name": "Test Project"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        project_id = resp.json()["id"]
        assert resp.json()["tenant_id"] == tenant_id

        # List
        resp = await client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == project_id

    async def test_cross_tenant_access_denied(
        self, client, auth_headers, other_tenant_id
    ):
        """Create a project as tenant A, try to access as tenant B."""
        # Create as tenant A
        resp = await client.post(
            "/api/v1/projects",
            json={"name": "Tenant A Project"},
            headers=auth_headers,
        )
        project_id = resp.json()["id"]

        # Try to access as tenant B
        other_token = jwt.encode(
            {"tenant_id": other_tenant_id, "user_id": "other-user"},
            "test-secret",
            algorithm="HS256",
        )
        resp = await client.get(
            f"/api/v1/projects/{project_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404, "Cross-tenant access should return 404, not 403"
```

## 10. Deployment Patterns

### Blue-Green with Tenant Migration

```yaml
# deploy/blue-green.yaml — Conceptual deployment manifest
#
# Blue-green deployment for SaaS:
# 1. Deploy new version to "green" environment
# 2. Run database migrations (backward-compatible only)
# 3. Route a subset of tenants to green (canary)
# 4. Monitor error rates per tenant
# 5. Gradually shift all traffic
# 6. Tear down blue after confirmation

deployment:
  strategy: blue-green
  steps:
    - name: deploy-green
      action: deploy
      target: green
      version: "${NEW_VERSION}"

    - name: migrate-database
      action: run-migrations
      note: "Migrations MUST be backward-compatible (additive only)"
      # Add columns, don't rename/drop. Old code must still work.

    - name: canary-internal
      action: route-tenants
      tenants: ["internal-test-tenant"]
      target: green
      duration: 15m
      rollback_on:
        error_rate: "> 1%"
        p99_latency: "> 2s"

    - name: canary-starter
      action: route-tenants
      tenant_filter: {plan: "starter", sample: "10%"}
      target: green
      duration: 30m

    - name: canary-pro
      action: route-tenants
      tenant_filter: {plan: "pro", sample: "10%"}
      target: green
      duration: 30m

    - name: full-rollover
      action: route-all
      target: green

    - name: teardown-blue
      action: teardown
      target: blue
      delay: 60m  # Keep blue alive for fast rollback
```

### Canary Deployment Per Tier

```python
# deploy/canary_router.py
"""
Route tenants to deployment targets based on their tier.
Enterprise tenants are always last to receive new versions.
"""

class CanaryRouter:
    """
    Controls which deployment target (blue/green/canary) serves each tenant.
    Uses Redis for fast lookups in the load balancer/ingress controller.
    """

    ROLLOUT_ORDER = ["internal", "starter", "pro", "enterprise"]

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def assign_tenant_target(self, tenant_id: str, target: str):
        """Route a specific tenant to a deployment target."""
        self.redis.hset("deploy:tenant_targets", tenant_id, target)

    def assign_tier_target(self, tier: str, target: str, sample_pct: int = 100):
        """Route a percentage of a tier to a target."""
        tenants = tenant_registry.list_by_plan(tier)
        sample_size = max(1, len(tenants) * sample_pct // 100)

        for tenant in tenants[:sample_size]:
            self.assign_tenant_target(tenant["tenant_id"], target)

    def get_target(self, tenant_id: str) -> str:
        """Called by load balancer to determine routing."""
        target = self.redis.hget("deploy:tenant_targets", tenant_id)
        return (target or b"blue").decode()

    def rollback_tenant(self, tenant_id: str):
        """Emergency rollback: send tenant back to stable (blue)."""
        self.assign_tenant_target(tenant_id, "blue")

    def rollback_all(self):
        """Emergency: rollback all tenants to blue."""
        self.redis.delete("deploy:tenant_targets")
```

### Feature Flags Per Tenant for Gradual Rollout

```python
# services/feature_rollout.py
"""
Gradual feature rollout using tenant-scoped feature flags.
Complements plan-based entitlements (see saas-architecture skill)
with deployment-scoped rollout control.
"""

class FeatureRollout:
    """
    Layer on top of entitlements:
    1. Entitlement = "is this tenant's plan allowed to use this feature?"
    2. Rollout = "have we enabled this feature for this tenant yet?"

    Both must be true for a feature to be active.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def is_enabled(self, tenant_id: str, feature: str) -> bool:
        """Check if feature is rolled out to this tenant."""
        # Check tenant-specific override
        override = self.redis.hget(f"rollout:{feature}:overrides", tenant_id)
        if override is not None:
            return override == b"1"

        # Check percentage rollout
        pct = self.redis.get(f"rollout:{feature}:percentage")
        if pct:
            # Deterministic: same tenant always gets same result for same feature
            hash_val = int(hashlib.md5(
                f"{tenant_id}:{feature}".encode()
            ).hexdigest(), 16)
            return (hash_val % 100) < int(pct)

        return False

    def enable_for_tenant(self, tenant_id: str, feature: str):
        self.redis.hset(f"rollout:{feature}:overrides", tenant_id, "1")

    def disable_for_tenant(self, tenant_id: str, feature: str):
        self.redis.hset(f"rollout:{feature}:overrides", tenant_id, "0")

    def set_rollout_percentage(self, feature: str, percentage: int):
        """Roll out to N% of tenants (deterministic hash-based)."""
        self.redis.set(f"rollout:{feature}:percentage", str(percentage))

    def rollout_by_tier(self, feature: str, tiers: list[str]):
        """Enable feature for all tenants in specified tiers."""
        for tier in tiers:
            for tenant in tenant_registry.list_by_plan(tier):
                self.enable_for_tenant(tenant["tenant_id"], feature)
```

### Database Migration Strategy for Multi-Tenant

```
Safe migration rules for SaaS (zero-downtime):

1. ADDITIVE ONLY during rollout:
   - ADD columns (with defaults), ADD tables, ADD indexes (CONCURRENTLY)
   - NEVER rename, drop, or change column types during rollout

2. Two-phase migration pattern:
   Phase 1 (deploy v2): Add new column, code writes to both old + new
   Phase 2 (deploy v3): Code reads from new only, drop old column

3. Migration ordering:
   - Run migrations BEFORE deploying new code (forward-compatible schema)
   - Migrations must not break the currently running code version

4. Large table migrations:
   - Use pt-online-schema-change (MySQL) or pg_repack (PostgreSQL)
   - ALTER TABLE ... ADD COLUMN with DEFAULT is instant in PostgreSQL 11+
   - CREATE INDEX CONCURRENTLY to avoid locking

5. Per-tenant migrations (bridge/silo models):
   - Run in parallel with bounded concurrency (e.g., 5 at a time)
   - Track per-tenant migration version in tenant_registry
   - Alert on drift: any tenant behind by >1 migration version
```

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Pass `tenant_id` as function parameter through 15 layers | Use `contextvars` — set once in middleware, read anywhere |
| Cache with keys like `project:123` (no tenant prefix) | Always `tenant:{tid}:project:123` — prevents cross-tenant cache reads |
| Run Celery tasks without tenant context propagation | Use `TenantTask` base class that injects/restores tenant from headers |
| Generate pre-signed S3 URLs without validating key prefix | Always verify the key starts with `tenant-{tenant_id}/` before signing |
| Use `KEYS *` in Redis for tenant key operations | Use `SCAN` with cursor — `KEYS` blocks Redis on large datasets |
| Run all tenant schema migrations serially | Parallelize with bounded concurrency (5-10 at a time) |
| Write tests that share a single hardcoded tenant_id | Each test gets a fresh `uuid4()` tenant_id via fixture |
| Deploy new features to all tenants simultaneously | Canary by tier: internal, then starter, then pro, then enterprise |
| Store uploaded files at user-chosen paths | Sanitize filenames, prepend UUID, enforce tenant prefix |
| Let one tenant's failed webhook retries consume the entire retry queue | Use per-tenant or per-endpoint retry budgets with circuit breakers |
