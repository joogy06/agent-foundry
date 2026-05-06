# Architecture Map Templates

Reference for `project-documentation`. Full templates with metadata headers for each architecture level.

> **Note**: `history.md` is bounded by the rotation policy (default ≤3 sessions OR ≤600 lines live; older content lives in `history/<YYYY-MM>.md` with `history/INDEX.md` as the TOC). When older context is needed, follow `history/INDEX.md`. See `SKILL.md` "History rotation policy".

## PROJECT.md Template (Level 0)

Lives at: project root `PROJECT.md`. Max 120 lines.

```markdown
---
doc_type: project
id: [project-name-kebab-case]
status: active
owned_paths:
  - src/
  - [other top-level dirs]
children:
  - [component-id-1]
  - [component-id-2]
depends_on: []
external_dependencies:
  - [service-name]
entry_points:
  - [main entry command or file]
last_verified_at: YYYY-MM-DD
confidence: high
---

# [Project Name]

[1-2 sentence purpose. What this project does, who it serves.]

## Components

| id | owns | purpose | doc |
|----|------|---------|-----|
| [auth] | [src/auth/] | [Authentication, token lifecycle] | [docs/components/auth/COMPONENT.md] |
| [api] | [src/api/] | [REST API routes, middleware] | [docs/components/api/COMPONENT.md] |
| [frontend] | [src/frontend/] | [React SPA, pages, state] | [docs/components/frontend/COMPONENT.md] |

## Interaction Edges

| edge_id | from | to | interface | mode | data | failure_impact |
|---------|------|----|-----------|------|------|---------------|
| E-001 | frontend | api | REST/JSON HTTPS | sync | user requests | UI shows error |
| E-002 | api | auth | internal function | sync | token + user_id | 401 on all protected routes |
| E-003 | api | database | SQLAlchemy ORM | sync | queries/mutations | app non-functional |
| E-004 | api | workers | Redis queue | async | job payloads | async tasks delayed |
| E-005 | workers | email-svc | SendGrid REST | async | email payloads | emails delayed, app continues |

## External Dependencies

| service | purpose | failure_impact |
|---------|---------|---------------|
| [SendGrid] | [Transactional email] | [Email delayed; app continues] |
| [Stripe] | [Payment processing] | [Checkout blocked; browsing works] |

## Entry Points

| entry | purpose |
|-------|---------|
| `docker-compose up` | Start all services locally |
| `flask run` | Dev server on :5000 |
| `npm run dev` | Frontend dev on :3000 |

## Testing

| aspect | value |
|--------|-------|
| framework | [pytest / jest / vitest / phpunit / go test / cargo test / ...] |
| run all | [command to run full test suite] |
| run subset | [command to run specific tests, e.g., pytest tests/unit/] |
| lint | [linting command, e.g., ruff check . / eslint .] |
| type check | [type checking command if applicable] |
| build | [build command if applicable] |
| ci config | [path to CI config, e.g., .github/workflows/test.yml] |
| coverage | [coverage command if applicable] |

## Configuration

| variable | purpose | required |
|----------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection | Yes |
| `REDIS_URL` | Redis connection | Yes |
| `JWT_SECRET_KEY` | Token signing | Yes |
```

**What PROJECT.md is NOT:**
- Not a README (no setup guide, no contributor instructions)
- Not a design doc (no rationale, no alternatives)
- Not an index (that's index.md)
- Not a changelog (that's history.md)

---

## COMPONENT.md Template (Level 1)

Lives at: `docs/components/<component-id>/COMPONENT.md`. Max 160 lines.

```markdown
---
doc_type: component
id: [component-id]
parent: [project-id]
status: active
owned_paths:
  - src/auth/
public_interfaces:
  - verify_token
  - create_token
  - require_scope
depends_on:
  - database
last_verified_at: YYYY-MM-DD
confidence: high
---

# [Component Name]

[1-2 sentence purpose. What this component does within the project.]

## Sub-Components

| sub-component | purpose | key_files | doc |
|---------------|---------|-----------|-----|
| [jwt-handler] | [Token creation, validation, refresh] | [src/auth/jwt.py] | [jwt-handler.md] |
| [session-mgr] | [Session persistence, cookie handling] | [src/auth/session.py] | — |
| [middleware] | [Request authentication] | [src/auth/middleware.py] | — |

## Internal Flow

```
Incoming request
    |
    v
middleware.authenticate()
    |
    +-- No token --> 401 Unauthorized
    |
    +-- Has token --> jwt_handler.verify(token)
                        |
                        +-- Invalid --> 401
                        +-- Valid --> session_manager.get_session(user_id)
                                      |
                                      v
                                  request.user = user_data
                                  --> continue to route handler
```

## Public Interfaces (exposed to other components)

| name | type | consumers | contract |
|------|------|-----------|----------|
| `auth.verify_token(token)` | function | api middleware | Returns `user_id: str` or raises `AuthError` |
| `auth.create_token(user_id, scopes)` | function | api login route | Returns `{access_token, refresh_token, expires_in}` |
| `auth.require_scope(scope)` | decorator | api route handlers | Raises `ForbiddenError` if scope missing |

## Consumed Interfaces (this component depends on)

| provider | interface | usage |
|----------|-----------|-------|
| database | `db.users.get_by_id(id)` | Fetch user during token validation |
| database | `db.sessions.upsert(session)` | Persist session data |
| config | `JWT_SECRET_KEY` | Token signing key |

## Configuration

| variable | purpose | default |
|----------|---------|---------|
| `JWT_SECRET_KEY` | RS256 signing key | (required) |
| `TOKEN_EXPIRY_SECONDS` | Access token lifetime | 3600 |
| `REFRESH_TOKEN_EXPIRY_DAYS` | Refresh token lifetime | 30 |

## Key Files

| file | reason_to_read |
|------|---------------|
| `src/auth/__init__.py` | Package init, public API exports |
| `src/auth/jwt.py` | Token creation and verification logic |
| `src/auth/middleware.py` | Request auth middleware — the main integration point |
| `src/auth/session.py` | Session lifecycle management |

## Edge Cases

| case | consequence | note |
|------|-------------|------|
| Refresh tokens are one-time-use | Old refresh token invalidated after use | Prevents replay attacks |
| Clock skew in exp validation | 30s leeway configured | `options={"leeway": 30}` |
```

<!-- Optional: Add when monitoring/benchmarking is configured
## Performance Budget

| metric | target | measurement_tool | baseline_date |
|--------|--------|-----------------|---------------|
| [p95 response time] | [< 200ms at 100 RPS] | [k6 / wrk / hey] | [YYYY-MM-DD] |
| [query execution time] | [< 50ms] | [EXPLAIN ANALYZE] | [YYYY-MM-DD] |
-->
```

**What COMPONENT.md is NOT:**
- Not API documentation (no request/response examples)
- Not a tutorial (no step-by-step guides)
- Not a changelog (use history.md or git log)

---

## Subcomponent Doc Template (Level 2 — opt-in)

Lives at: `docs/components/<component-id>/<slug>.md`. Max 80 lines.

Only create when threshold is met (see cascade-rules.md).

```markdown
---
doc_type: subcomponent
id: [component-id]/[subcomponent-slug]
parent: [component-id]
status: active
owned_paths:
  - src/auth/jwt.py
  - src/auth/tokens.py
depends_on:
  - database
last_verified_at: YYYY-MM-DD
confidence: high
---

# [Sub-Component Name]

[1 sentence purpose.]

## Responsibility

[2-3 sentences: what this owns, what it does NOT own.]

## Local Contract

| input | output | invariant |
|-------|--------|-----------|
| raw JWT string | TokenPayload or AuthError | Always validates exp, iss, aud claims |
| user_id + scopes | TokenPair(access, refresh) | Refresh token stored in DB, not just JWT |

## Key Files

| file | reason_to_read |
|------|---------------|
| `src/auth/jwt.py` | Token creation (RS256), verification, claims extraction |
| `src/auth/tokens.py` | Token dataclass, serialization helpers |

## Failure Modes

| case | effect | guardrail |
|------|--------|-----------|
| Large scope set in claims | Token exceeds 2KB | Monitor token size, consider scope references |
| DB unavailable during refresh | Refresh fails silently | Returns 401, forces re-login |
```

---

## COMPONENT.md Stub Template

Created by forge during design phase. Contains structure for implementation agents to fill.

```markdown
---
doc_type: component
id: [component-id]
parent: [project-id]
status: draft
owned_paths:
  - [expected paths]
public_interfaces: []
depends_on: []
last_verified_at: YYYY-MM-DD
confidence: low
---

# [Component Name]

[Purpose from design doc.]

## Sub-Components

| sub-component | purpose | key_files | doc |
|---------------|---------|-----------|-----|
| (to be filled during implementation) | | | |

## Internal Flow

(to be documented during implementation)

## Public Interfaces

| name | type | consumers | contract |
|------|------|-----------|----------|
| (from design doc) | | | |

## Consumed Interfaces

| provider | interface | usage |
|----------|-----------|-------|
| (from design doc) | | |

## Key Files

| file | reason_to_read |
|------|---------------|
| (to be filled during implementation) | |
```

---

## Integration Map Format

The Interaction Edges table in PROJECT.md is the **canonical** integration map. ASCII flow diagrams are optional convenience.

**Edge table is canonical because:**
- Tables diff cleanly (agents can detect changes)
- Each edge is individually addressable by `edge_id`
- Failure impact is visible per-edge
- Mode (sync/async/batch) affects how agents reason about changes

**Optional ASCII diagram** — include below the edge table for quick visual orientation:

```
Frontend --> API --> Auth --> Database
                |
                +--> Workers --> Email Service
```

Keep diagrams to the primary request path. Don't try to show every edge — the table handles completeness.
