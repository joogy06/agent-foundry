---
name: python-flask-developer
description: Use when building Flask web applications, REST APIs, or microservices. Covers Flask 3.x patterns, application factory, blueprints, extensions, deployment, testing, database sessions, and production configuration. Also covers when to choose Flask vs FastAPI vs Django.
---

# Python Flask Developer

## Overview

Flask 3.1.3 (Feb 2026) is a lightweight WSGI micro-framework. Best for: APIs, microservices, small-to-medium web apps, and projects needing maximum flexibility. For async-first apps, consider Quart (Flask-compatible API, 2x throughput). For full-featured admin/CMS, consider Django.

## When to Use Flask

| Use Case | Best Framework |
|----------|---------------|
| REST API, microservice | Flask or FastAPI |
| Async-first, high-concurrency API | **FastAPI** (or Quart) |
| Full web app with admin, ORM, auth built-in | **Django** |
| Flexible, compose-your-own-stack | **Flask** |
| Existing Flask codebase | **Flask** (don't migrate for trends) |
| Auto-generated OpenAPI docs critical | **FastAPI** |

## Application Factory Pattern (Required)

Never use module-level `app = Flask(__name__)` in production. Always use a factory:

```python
# app/__init__.py
def create_app(config_name='production'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Register blueprints
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    return app
```

**Why:** Enables testing with different configs, avoids circular imports, supports multiple app instances.

## Blueprint Architecture

```
app/
├── __init__.py          # create_app factory
├── extensions.py        # db, migrate, login_manager instances
├── models/              # SQLAlchemy models
├── api/
│   ├── __init__.py      # api_bp = Blueprint('api', __name__)
│   ├── products.py      # Product endpoints
│   └── orders.py        # Order endpoints
├── auth/
│   ├── __init__.py      # auth_bp blueprint
│   └── views.py         # Login, register, logout
├── templates/
├── static/
└── tests/
```

**Rules:**
- One blueprint per domain (api, auth, admin, etc.)
- Extensions in a separate `extensions.py` (avoids circular imports)
- Models in their own module, imported by blueprints as needed

## Key Extensions (2026 — Actively Maintained)

| Extension | Purpose | Status |
|-----------|---------|--------|
| Flask-SQLAlchemy 3.x | ORM integration | Active |
| Flask-Migrate | Alembic wrapper for migrations | Active |
| Flask-Login | Session-based user auth | Active |
| Flask-WTF | Form handling + CSRF | Active |
| Flask-CORS | Cross-origin resource sharing | Active |
| flask-smorest | REST API + OpenAPI docs | Active (replaces Flask-RESTful) |
| Flask-Limiter | Rate limiting | Active |
| Flask-Talisman | Security headers (CSP, HSTS) | Active |
| Flask-Caching | Response/data caching | Active |
| **Authlib** | OAuth/OIDC (replaces Flask-OAuthlib) | Active |

**Deprecated — Do NOT use:**
- Flask-RESTful → use **flask-smorest**
- Flask-OAuthlib → use **Authlib**
- Flask-RESTPlus → use **flask-smorest**
- Flask-Script → use **Flask CLI** (built-in since 2.0)

## Request Lifecycle Hooks

```python
@app.before_request
def before_request():
    g.start_time = time.time()
    g.request_id = request.headers.get('X-Request-ID', str(uuid4()))

@app.after_request
def after_request(response):
    duration = time.time() - g.start_time
    response.headers['X-Request-ID'] = g.request_id
    logger.info('request', duration=duration, status=response.status_code)
    return response

@app.teardown_appcontext
def teardown(exception=None):
    db.session.remove()  # Clean up scoped session
```

## Database Session Management

```python
# extensions.py
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

# Configuration
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 300,      # Recycle connections every 5 min
    'pool_pre_ping': True,    # Verify connections before use
    'max_overflow': 20,
}
```

**Rules:**
- Flask-SQLAlchemy handles scoped sessions automatically — don't create your own
- `db.session.remove()` in `teardown_appcontext` (Flask-SQLAlchemy does this by default)
- Never share sessions across threads
- Use `db.session.rollback()` in error handlers

## Configuration

```python
class Config:
    SECRET_KEY = os.environ['SECRET_KEY']  # Never hardcode
    SQLALCHEMY_DATABASE_URI = os.environ['DATABASE_URL']
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False

class ProductionConfig(Config):
    pass
```

**Rules:**
- Secrets from environment variables or vault — NEVER in code
- `SECRET_KEY` must be cryptographically random, minimum 32 bytes
- Cookie flags: `Secure=True`, `HttpOnly=True`, `SameSite=Lax` in production

## Deployment (Production)

```
Gunicorn (WSGI) → Nginx (reverse proxy) → Internet
```

**Gunicorn config:**
```bash
gunicorn "app:create_app()" \
    --workers $(( 2 * $(nproc) + 1 )) \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
```

**Worker formula:** `(2 * CPU cores) + 1` for sync workers. For I/O-heavy, use `--worker-class gevent`.

**Never:** Use Flask's built-in dev server in production (`flask run`).

## Testing

```python
@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_create_product(client):
    response = client.post('/api/products', json={'name': 'Test PC', 'price': 999})
    assert response.status_code == 201
```

**Libraries:** pytest, factory_boy (test data), faker, freezegun (time mocking).

## Security Hardening

```python
from flask_talisman import Talisman
from flask_limiter import Limiter

talisman = Talisman(app,
    content_security_policy={...},
    force_https=True
)

limiter = Limiter(app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
```

See `python-auth-security` skill for authentication, RBAC, and OWASP patterns.

## Async in Flask

Flask 2.0+ supports `async def` views, but it's **bolted-on** (runs coroutines on threads). For genuine async:
- Use **Quart** (drop-in Flask replacement with native ASGI)
- Or use **FastAPI** for new async-first projects
- Flask async is fine for occasional `await` calls, not for high-concurrency

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Use `app = Flask(__name__)` at module level | Prevents testing, causes circular imports |
| Use Flask dev server in production | No concurrency, no security, no process management |
| Hardcode `SECRET_KEY` | Security vulnerability — use env vars |
| Skip `teardown_appcontext` for DB sessions | Causes connection leaks |
| Use Flask-RESTful for new projects | Deprecated — use flask-smorest |
| Mix sync and async carelessly | Flask async is thread-based, not true async |
| Skip CSRF protection on forms | Vulnerability — use Flask-WTF |
| Set `DEBUG=True` in production | Exposes debugger with code execution |
