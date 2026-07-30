---
name: python-auth-security
description: Use when implementing authentication (OAuth, OIDC, SAML, JWT, sessions), authorization (RBAC, ABAC), user management, multi-tenant isolation, API security, or applying OWASP security patterns in Python web applications. Covers Flask and FastAPI security patterns.
family: python
disambiguation: Auth and security patterns across Flask and FastAPI — OAuth/OIDC/SAML/JWT, RBAC, tenant isolation, OWASP. General Flask application structure is python-flask-developer.
---

# Python Auth & Security

## Overview

Security is not optional. OWASP Top 10 vulnerabilities remain the primary attack vector. This skill covers authentication, authorization, user management, and application security patterns for Python web apps. Every code pattern must follow these rules — no shortcuts.

## Authentication Decision Framework

| Scenario | Method | Library |
|----------|--------|---------|
| Web app with sessions | Session + cookies | Flask-Login |
| SPA + API | JWT (access + refresh) | flask-jwt-extended / python-jose |
| Enterprise SSO | OAuth 2.0 / OIDC | **Authlib** (recommended) |
| Legacy enterprise | SAML 2.0 | python3-saml (OneLogin) |
| Machine-to-machine | Client Credentials / mTLS | Authlib / httpx |
| LDAP/Active Directory | LDAP bind | **ldap3** (pure Python) |
| API consumers | API keys (hashed) | Custom middleware |

## OAuth 2.0 / OIDC

**Authlib** is the recommended library (replaces deprecated Flask-OAuthlib).

### Flows

| App Type | Flow | Notes |
|----------|------|-------|
| Server-side web app | Authorization Code + PKCE | Default for all new apps |
| SPA (React, etc.) | Authorization Code + PKCE | No Implicit flow — deprecated |
| Mobile app | Authorization Code + PKCE | Use custom URI scheme for redirect |
| Service-to-service | Client Credentials | No user involved |

**Rule:** Always use PKCE. The Implicit flow is deprecated and insecure.

### Providers

| Provider | Config Endpoint |
|----------|----------------|
| Keycloak | `{url}/realms/{realm}/.well-known/openid-configuration` |
| Azure AD / Entra ID | `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration` |
| Google | `https://accounts.google.com/.well-known/openid-configuration` |
| Auth0 | `https://{domain}/.well-known/openid-configuration` |

## JWT Best Practices

| Rule | Detail |
|------|--------|
| Short-lived access tokens | 15-30 minutes maximum |
| Refresh token rotation | New refresh token on every use, invalidate old one |
| Token blacklisting | Redis-backed blocklist for logout/revocation |
| Algorithm | RS256 (asymmetric) for multi-service; HS256 only for single service |
| Never store in localStorage | XSS-accessible. Use HttpOnly cookies or in-memory |
| Validate all claims | `iss`, `aud`, `exp`, `iat` — don't skip any |

## Password Security

**Argon2id** is the gold standard (OWASP + NIST SP 800-63B Rev 4, July 2025).

| Algorithm | Status | Use When |
|-----------|--------|----------|
| **Argon2id** | Recommended | All new implementations |
| bcrypt | Acceptable | Existing systems (migrate progressively) |
| scrypt | Acceptable | If Argon2 unavailable |
| SHA-256/MD5/PBKDF2-SHA1 | **NEVER** | Legacy only — migrate immediately |

**NIST SP 800-63B (2025):** Minimum 8 characters, no complexity rules (they don't help), check against breached password lists, no forced rotation (change only on compromise).

## RBAC Implementation

### Database Schema

```
users (id, email, password_hash, is_active)
roles (id, name, description)
permissions (id, name, resource, action)
user_roles (user_id, role_id)
role_permissions (role_id, permission_id)
```

### Predefined Roles

| Role | Permissions |
|------|------------|
| **admin** | Full access, user management, system config |
| **operator** | CRUD on business objects, no system config |
| **viewer** | Read-only access |
| **auditor** | Read access + audit logs |

### Flask Pattern

```python
from functools import wraps

def permission_required(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.has_permission(permission_name):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

@app.route('/admin/users')
@login_required
@permission_required('user.manage')
def manage_users():
    ...
```

**For complex policies:** Use **PyCasbin** (supports RBAC, ABAC, and custom models).

## ABAC (Attribute-Based Access Control)

Use ABAC when RBAC isn't granular enough (e.g., "users can only edit their own resources" or "managers can approve orders under £10,000").

**Tools:** PyCasbin (PERM metamodel), OPA/Rego (policy-as-code via REST API), Vakt, Py-ABAC.

## Multi-Tenant Isolation

| Pattern | When | Implementation |
|---------|------|---------------|
| Shared DB + tenant_id | Simple, cost-effective | SQLAlchemy event filters, PostgreSQL RLS |
| Separate schemas | Medium isolation | Schema per tenant, search_path switching |
| Separate databases | Maximum isolation | Connection routing by tenant |

**Rule:** Always filter by `tenant_id` at the query level, not the application level. PostgreSQL Row-Level Security (RLS) is the strongest guarantee:

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant')::int);
```

## OWASP Top 10 Quick Reference

| # | Vulnerability | Python Prevention |
|---|--------------|-------------------|
| A01 | Broken Access Control | `@login_required`, `@permission_required`, check ownership |
| A02 | Cryptographic Failures | Argon2id for passwords, TLS everywhere, no secrets in code |
| A03 | Injection (SQL, OS, LDAP) | Parameterized queries, `shlex.quote()`, ORM |
| A04 | Insecure Design | Threat modeling, input validation (Pydantic/Marshmallow) |
| A05 | Security Misconfiguration | No DEBUG in prod, security headers, minimal permissions |
| A06 | Vulnerable Components | `pip-audit`, Dependabot, pin versions |
| A07 | Auth Failures | MFA, account lockout, secure session config |
| A08 | Software Integrity | Lockfiles, hash verification, signed packages |
| A09 | Logging Failures | Structured logging, audit trail, **never log passwords/tokens** |
| A10 | SSRF | Allowlist URLs, validate redirects, no user-controlled URLs to internal services |

## Input Validation

| Library | Best For |
|---------|----------|
| **Pydantic** | FastAPI, API request/response models |
| **Marshmallow** | Flask, serialization + validation |
| **WTForms** | Flask HTML forms |
| **Cerberus** | Lightweight dict validation |

**Rule:** Validate at the boundary (API input), sanitize for output context (HTML, SQL, shell).

## API Security

| Pattern | Implementation |
|---------|---------------|
| Authentication | OAuth 2.0 Bearer tokens or API keys (hashed, per-client) |
| Rate limiting | Flask-Limiter / slowapi (per-user, per-endpoint) |
| Input validation | Pydantic/Marshmallow on every endpoint |
| CORS | Restrictive origin list, never `*` in production |
| Webhook verification | HMAC-SHA256 signature in header |
| Request signing | HMAC with shared secret for M2M |

## Security Scanning

| Tool | Type | Use |
|------|------|-----|
| **Bandit** | Static analysis | Find security issues in Python code |
| **pip-audit** | Dependency scan | Known vulnerabilities in packages |
| **Safety** | Dependency scan | Alternative to pip-audit |
| **Semgrep** | SAST | Custom rules for security patterns |

**Run in CI/CD:** `bandit -r app/ && pip-audit` on every commit.

## Dangerous Functions — NEVER Use

| Function | Risk | Safe Alternative |
|----------|------|-----------------|
| `eval()` | Code execution | `ast.literal_eval()` for data |
| `exec()` | Code execution | Avoid entirely |
| `pickle.loads()` on untrusted data | Code execution | `json.loads()` |
| `yaml.load()` | Code execution | `yaml.safe_load()` |
| `os.system()` | Command injection | `subprocess.run([], shell=False)` |
| `__import__()` dynamically | Code execution | Explicit imports |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Store passwords as MD5/SHA-256 | Trivially crackable — use Argon2id |
| Use OAuth Implicit flow | Deprecated, token exposure risk — use Auth Code + PKCE |
| Store JWTs in localStorage | XSS-accessible — use HttpOnly cookies |
| Skip PKCE in OAuth flows | MITM vulnerability — always use PKCE |
| Hardcode secrets in code | Exposed in repos — use env vars or vault |
| Disable TLS certificate verification | MITM vulnerability — never `verify=False` in production |
| Log passwords, tokens, or card numbers | Data breach risk — redact sensitive fields |
| Force password rotation on schedule | NIST says don't — change only on compromise |
| Use `shell=True` in subprocess | Command injection — always `shell=False` |
| Skip rate limiting on auth endpoints | Brute force vulnerability |
