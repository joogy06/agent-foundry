# Metering, Operations, Security, and Anti-Patterns

Reference file for the `saas-architecture` skill. Covers usage metering, operational patterns (scaling, deployment, monitoring), security/compliance, and anti-patterns.

## Usage Metering

### Event Collection & Aggregation

```python
# services/metering.py
import time
from collections import defaultdict

class MeteringService:
    """Collect usage events, aggregate, and report to billing."""

    def __init__(self, redis_client, stripe_meter_id: str):
        self.redis = redis_client
        self.stripe_meter_id = stripe_meter_id

    def record_event(self, tenant_id: str, event_type: str, quantity: int = 1):
        """Record a usage event. High-throughput path — uses Redis for buffering."""
        now = int(time.time())
        window = now - (now % 3600)  # Hourly window

        # Atomic increment in Redis
        key = f"meter:{tenant_id}:{event_type}:{window}"
        self.redis.incrby(key, quantity)
        self.redis.expire(key, 172800)  # 48h TTL for safety

    def get_current_usage(self, tenant_id: str, event_type: str, period: str = "current_month") -> int:
        """Get aggregated usage for a tenant."""
        # Sum all hourly buckets in the current billing period
        pattern = f"meter:{tenant_id}:{event_type}:*"
        total = 0
        for key in self.redis.scan_iter(pattern):
            total += int(self.redis.get(key) or 0)
        return total

    def flush_to_stripe(self, tenant_id: str, event_type: str):
        """Report aggregated usage to Stripe Meter for billing."""
        usage = self.get_current_usage(tenant_id, event_type)
        if usage > 0:
            stripe.billing.MeterEvent.create(
                event_name=self.stripe_meter_id,
                payload={
                    "stripe_customer_id": self._get_stripe_id(tenant_id),
                    "value": str(usage),
                },
            )

    def check_quota(self, tenant_id: str, event_type: str) -> bool:
        """Check if tenant is within their quota. Returns False if over."""
        current = self.get_current_usage(tenant_id, event_type)
        limit = entitlement_service.get_limit(tenant_id, event_type)
        if limit == -1:
            return True
        return current < limit
```

### Overage Handling

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| Hard cap | Block requests when limit hit | API calls, storage, seats |
| Soft cap + overage billing | Allow continued use, charge extra | Usage-based pricing (compute, bandwidth) |
| Throttle | Reduce rate, don't block | API rate limits |
| Notify + grace | Alert at 80%, 90%, 100% — enforce at 110% | Balanced approach for most resources |

```python
# middleware/quota_enforcement.py
def enforce_quota(event_type: str):
    """Middleware decorator for quota-enforced endpoints."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            tenant_id = g.tenant_id

            if not metering_service.check_quota(tenant_id, event_type):
                plan = entitlement_service.get_plan(tenant_id)
                limit = entitlement_service.get_limit(tenant_id, event_type)

                # Check if overage billing is enabled
                if plan.overage_enabled:
                    metering_service.record_event(tenant_id, event_type)
                    return f(*args, **kwargs)

                abort(429, description=f"Quota exceeded: {event_type} ({limit} per period). Upgrade your plan.")

            metering_service.record_event(tenant_id, event_type)
            return f(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@api.route('/api/v1/analyze', methods=['POST'])
@require_feature('api_access')
@enforce_quota('api_calls_daily')
def analyze_data():
    ...
```

## Operational Patterns

### Noisy Neighbor Detection

```python
# monitoring/noisy_neighbor.py
class NoisyNeighborDetector:
    """Detect tenants consuming disproportionate resources in shared pool."""

    THRESHOLDS = {
        "cpu_percent": 30.0,       # >30% of shared CPU
        "query_count_1m": 5000,    # >5000 queries per minute
        "memory_mb": 2048,         # >2GB memory
        "connection_count": 50,    # >50 DB connections
    }

    def check_all_tenants(self) -> list[dict]:
        alerts = []
        metrics = self.metrics_collector.get_per_tenant_metrics()

        for tenant_id, tenant_metrics in metrics.items():
            violations = {}
            for metric, threshold in self.THRESHOLDS.items():
                value = tenant_metrics.get(metric, 0)
                if value > threshold:
                    violations[metric] = {
                        "value": value,
                        "threshold": threshold,
                        "severity": "critical" if value > threshold * 2 else "warning",
                    }

            if violations:
                alerts.append({
                    "tenant_id": tenant_id,
                    "violations": violations,
                    "action": self._determine_action(violations),
                })

        return alerts

    def _determine_action(self, violations: dict) -> str:
        if any(v["severity"] == "critical" for v in violations.values()):
            return "throttle"  # Apply rate limiting immediately
        return "notify"  # Alert ops team

# SQL: Detect noisy neighbors by query volume
# Run periodically from a monitoring job
NOISY_NEIGHBOR_SQL = """
SELECT
    tenant_id,
    COUNT(*) as query_count,
    AVG(duration_ms) as avg_duration,
    MAX(duration_ms) as max_duration,
    SUM(rows_examined) as total_rows
FROM query_log
WHERE recorded_at > NOW() - INTERVAL '5 minutes'
GROUP BY tenant_id
HAVING COUNT(*) > 1000 OR AVG(duration_ms) > 500
ORDER BY query_count DESC;
"""
```

### Tenant Health Scoring

```python
# monitoring/tenant_health.py
@dataclass
class TenantHealthScore:
    tenant_id: str
    overall: float           # 0-100
    billing_health: float    # Payment status
    usage_health: float      # Within plan limits
    engagement_health: float # Active usage signals
    risk_level: str          # "healthy", "at_risk", "churning"

class TenantHealthScorer:
    """Composite health score for churn prediction and support prioritization."""

    def score(self, tenant_id: str) -> TenantHealthScore:
        billing = self._billing_score(tenant_id)
        usage = self._usage_score(tenant_id)
        engagement = self._engagement_score(tenant_id)

        overall = (billing * 0.3) + (usage * 0.3) + (engagement * 0.4)

        risk_level = "healthy"
        if overall < 40:
            risk_level = "churning"
        elif overall < 65:
            risk_level = "at_risk"

        return TenantHealthScore(
            tenant_id=tenant_id,
            overall=overall,
            billing_health=billing,
            usage_health=usage,
            engagement_health=engagement,
            risk_level=risk_level,
        )

    def _billing_score(self, tenant_id: str) -> float:
        # 100 = current, 70 = 1 late payment, 30 = 2+ late, 0 = suspended
        ...

    def _usage_score(self, tenant_id: str) -> float:
        # 100 = using 40-80% of quota, 60 = <10% (underutilized), 80 = >90% (near limit)
        ...

    def _engagement_score(self, tenant_id: str) -> float:
        # Based on: DAU, feature adoption breadth, API call trends, last login recency
        ...
```

### Per-Tenant Resource Quotas

```sql
-- Enforce per-tenant connection limits at the database level
-- Use pg_hba.conf or connection pooler (PgBouncer) settings

-- PgBouncer per-tenant pool limits (pgbouncer.ini)
-- [databases]
-- tenant_abc = host=db1 dbname=saas pool_size=20
-- tenant_xyz = host=db1 dbname=saas pool_size=50
-- * = host=db1 dbname=saas pool_size=5

-- Application-level query timeout per tenant tier
SET LOCAL statement_timeout = '5000';     -- 5s for starter
SET LOCAL statement_timeout = '30000';    -- 30s for pro
SET LOCAL statement_timeout = '120000';   -- 120s for enterprise
```

## Security & Compliance

### SOC2 Considerations

| Control Area | SaaS Implementation |
|-------------|-------------------|
| **Access Control** | Tenant-scoped RBAC, admin audit trail, MFA enforcement per tenant |
| **Data Encryption** | TLS in transit, AES-256 at rest, per-tenant encryption keys (KMS) |
| **Monitoring** | Per-tenant audit logs, anomaly detection, access logging |
| **Change Management** | Blue-green deployments, feature flags, rollback capability |
| **Incident Response** | Tenant-scoped blast radius, automated incident classification |
| **Availability** | Multi-AZ, per-tenant SLA tracking, status page per tenant |

### Data Residency

```python
# config/regions.py
REGION_CONFIG = {
    "us": {"db_host": "db-us.example.com", "storage_bucket": "data-us"},
    "eu": {"db_host": "db-eu.example.com", "storage_bucket": "data-eu"},
    "ap": {"db_host": "db-ap.example.com", "storage_bucket": "data-ap"},
}

class RegionRouter:
    """Route tenant data to correct geographic region."""

    def get_connection(self, tenant_id: str):
        tenant = tenant_registry.get(tenant_id)
        region_cfg = REGION_CONFIG[tenant.region]
        return get_engine_for_host(region_cfg["db_host"])

    def get_storage_bucket(self, tenant_id: str) -> str:
        tenant = tenant_registry.get(tenant_id)
        return REGION_CONFIG[tenant.region]["storage_bucket"]
```

### Per-Tenant Encryption Keys

```python
# services/encryption.py
class TenantEncryptionService:
    """Per-tenant data encryption using KMS-managed keys."""

    def __init__(self, kms_client):
        self.kms = kms_client

    def get_or_create_key(self, tenant_id: str) -> str:
        """Get tenant's KMS key ARN, create if missing."""
        key_arn = self.db.execute(
            "SELECT kms_key_arn FROM tenant_encryption_keys WHERE tenant_id = :tid",
            {"tid": tenant_id}
        ).scalar()

        if not key_arn:
            response = self.kms.create_key(
                Description=f"Tenant data key: {tenant_id}",
                Tags=[{"TagKey": "tenant_id", "TagValue": tenant_id}],
            )
            key_arn = response["KeyMetadata"]["Arn"]
            self.db.execute(
                "INSERT INTO tenant_encryption_keys (tenant_id, kms_key_arn) VALUES (:tid, :arn)",
                {"tid": tenant_id, "arn": key_arn}
            )
        return key_arn

    def encrypt(self, tenant_id: str, plaintext: bytes) -> bytes:
        key_arn = self.get_or_create_key(tenant_id)
        response = self.kms.encrypt(KeyId=key_arn, Plaintext=plaintext)
        return response["CiphertextBlob"]

    def decrypt(self, tenant_id: str, ciphertext: bytes) -> bytes:
        key_arn = self.get_or_create_key(tenant_id)
        response = self.kms.decrypt(KeyId=key_arn, CiphertextBlob=ciphertext)
        return response["Plaintext"]
```

### GDPR: Tenant Data Export & Deletion

```python
# services/gdpr.py — HARD-RULE: Never delete synchronously
class GDPRService:
    """Handle data export and right-to-erasure requests."""

    TENANT_TABLES = [
        "orders", "users", "projects", "api_keys", "audit_logs",
        "usage_events", "webhook_endpoints", "webhook_deliveries",
        "invitations", "settings",
    ]

    def export_tenant_data(self, tenant_id: str) -> str:
        """Export all tenant data as JSON. Returns download URL."""
        export_data = {}
        for table in self.TENANT_TABLES:
            rows = self.db.execute(
                text(f"SELECT * FROM {table} WHERE tenant_id = :tid"),
                {"tid": tenant_id}
            ).fetchall()
            export_data[table] = [dict(r._mapping) for r in rows]

        # Write to secure, time-limited storage
        file_key = f"exports/{tenant_id}/{datetime.utcnow().isoformat()}.json"
        self.storage.upload(file_key, json.dumps(export_data, default=str))
        download_url = self.storage.presigned_url(file_key, expires_in=86400)

        self._audit("data_export", tenant_id, {"tables": self.TENANT_TABLES})
        return download_url

    def request_deletion(self, tenant_id: str, requested_by: str):
        """Queue tenant for deletion with grace period. NEVER delete inline."""
        deletion_request = DeletionRequest(
            tenant_id=tenant_id,
            requested_by=requested_by,
            requested_at=datetime.utcnow(),
            scheduled_for=datetime.utcnow() + timedelta(days=30),  # Grace period
            status="pending",
        )
        self.db.add(deletion_request)

        # Suspend tenant immediately
        tenant_service.suspend(tenant_id, reason="deletion_requested")

        self._audit("deletion_requested", tenant_id, {
            "requested_by": requested_by,
            "scheduled_for": deletion_request.scheduled_for.isoformat(),
        })

        notification_service.send(tenant_id, "deletion_scheduled",
            scheduled_date=deletion_request.scheduled_for)

    def execute_deletion(self, deletion_request_id: int):
        """Executed by async worker after grace period expires."""
        request = DeletionRequest.query.get(deletion_request_id)
        if request.status == "cancelled":
            return

        tenant_id = request.tenant_id

        # Export final backup before deletion
        backup_url = self.export_tenant_data(tenant_id)
        self._audit("pre_deletion_backup", tenant_id, {"backup_url": backup_url})

        # Delete from all tables
        for table in self.TENANT_TABLES:
            self.db.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                {"tid": tenant_id}
            )

        # Deprovision infrastructure (schema, partitions, storage)
        data_provisioner.deprovision(tenant_id)

        # Cancel Stripe subscription
        billing_service.cancel_subscription(tenant_id, at_period_end=False)

        # Remove encryption keys
        encryption_service.destroy_key(tenant_id)

        request.status = "completed"
        request.completed_at = datetime.utcnow()
        self.db.commit()

        self._audit("deletion_completed", tenant_id, {
            "tables_cleared": self.TENANT_TABLES,
            "backup_url": backup_url,
        })

    def _audit(self, action: str, tenant_id: str, details: dict):
        """Audit log entries survive tenant deletion (stored in admin schema)."""
        self.db.execute(
            text("""INSERT INTO admin.audit_log
                (action, tenant_id, details, created_at)
                VALUES (:action, :tid, :details, NOW())"""),
            {"action": action, "tid": tenant_id, "details": json.dumps(details)},
        )
```

### Audit Logging

```python
# services/audit.py
class AuditLogger:
    """Immutable audit log for compliance. Written to separate admin schema."""

    def log(self, tenant_id: str, actor_id: str, action: str,
            resource_type: str, resource_id: str, details: dict = None):
        entry = AuditEntry(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string,
            timestamp=datetime.utcnow(),
        )
        # Write to append-only table (no UPDATE/DELETE permissions)
        self.db.add(entry)
        self.db.commit()
```

```sql
-- Audit log table: append-only, no delete permissions for app role
CREATE TABLE admin.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   UUID NOT NULL,
    actor_id    UUID,
    action      TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    details     JSONB DEFAULT '{}',
    ip_address  INET,
    user_agent  TEXT,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (timestamp);

-- Create monthly partitions
CREATE TABLE admin.audit_log_2026_01 PARTITION OF admin.audit_log
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- App role: INSERT only, no UPDATE/DELETE
GRANT INSERT ON admin.audit_log TO app_role;
REVOKE UPDATE, DELETE ON admin.audit_log FROM app_role;

-- Index for tenant-scoped queries
CREATE INDEX idx_audit_tenant_time ON admin.audit_log (tenant_id, timestamp DESC);
```

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Filter by tenant_id only in application code | One missed filter = data leak. Use RLS + ORM filters as safety nets |
| Use a single API key for all tenants | Compromised key affects everyone. Keys must be tenant-scoped |
| Synchronously provision silo infrastructure on signup | Blocks the request. Use async provisioning with status polling |
| Share encryption keys across tenants | One breach exposes all tenants. Use per-tenant KMS keys |
| Delete tenant data without a grace period | No recovery path. Always queue with 30+ day grace period |
| Skip webhook signature verification | Spoofed events can corrupt tenant state |
| Rate limit by IP instead of tenant | Multiple tenants behind one IP get unfairly limited |
| Store plan/tier logic in the database | Deployment-coupled. Define plans in code, store tenant-plan mapping in DB |
| Run migrations synchronously for schema-per-tenant | Locks the request. Run async, report progress |
| Ignore noisy neighbor signals | One tenant degrades experience for all shared-pool tenants |
