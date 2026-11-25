# Serving a Vite build behind an API backend on one origin

Reference file for the `modern-frontend` skill. Covers one-origin deployment of a Vite SPA behind
its API server: the SPA fallback route, cache headers for hashed assets vs `index.html`, security
headers, and OpenAPI → typed TypeScript client generation kept in sync with the backend. FastAPI
(Starlette `StaticFiles`) is the worked example; the rules carry over to Express, Spring, ASP.NET
or a reverse proxy.

## Contents

- 1. Why one origin
- 2. Build layout and `base`
- 3. Route order: API, assets, SPA fallback
- 4. FastAPI worked example
- 5. Cache headers
- 6. Security headers on the HTML response
- 7. OpenAPI → typed TS client
- 8. Keeping client and server in sync (CI)
- 9. Versioning and deploy skew
- 10. Anti-patterns

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: vite-version
    source_url: https://www.npmjs.com/package/vite
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "vite 8.3.5 current (2026-10-21); build emits hashed files under dist/assets; build.manifest writes dist/.vite/manifest.json."
  - kind: external_fact
    subject: starlette-staticfiles
    source_url: https://www.starlette.io/staticfiles/
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "Starlette 1.10.0 StaticFiles(html=True) serves index.html for directories and 404.html when present; no SPA fallback for client routes (read from source)."
  - kind: external_fact
    subject: openapi-ts
    source_url: https://www.npmjs.com/package/@hey-api/openapi-ts
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "@hey-api/openapi-ts 0.99.0 (pre-1.0); plugins '@hey-api/client-fetch' (bundled since 0.73; separate package deprecated), '@tanstack/react-query', 'zod'. openapi-typescript 7.13.0 + openapi-fetch 0.17.0; orval 8.45.0."
-->

## 1. Why one origin

Serving the SPA and the API from the same scheme, host and port means: no CORS policy to get
wrong, cookies are first-party (`SameSite=Strict` works, `__Host-` prefix works), `EventSource`
sends the session cookie without `withCredentials`, the WebAuthn RP ID and expected origin are one
value, and the CSP can be `'self'` throughout. In development, keep the same shape with Vite's
dev-server proxy (`server.proxy['/api']`) instead of enabling CORS on the API.

## 2. Build layout and `base`

`vite build` writes `dist/index.html` plus content-hashed files under `dist/assets/`
(`index-<hash>.js`, `index-<hash>.css`, and hashed images and fonts). Files in `public/` are copied
as-is **without** a hash.

- Leave `base: '/'` when the SPA owns the origin root; set `base: '/app/'` if it is mounted under a
  path, and mount the fallback at the same prefix.
- `build.manifest: true` emits `dist/.vite/manifest.json` mapping source entries to hashed files;
  needed only when the server renders its own HTML shell and must inject the asset tags.
- Keep `dist/` out of the API's source tree in the repo; copy it into the image at build time
  (multi-stage Dockerfile: a Node stage runs `npm ci && npm run build`, the Python stage copies
  `dist/`).

## 3. Route order: API, assets, SPA fallback

```text
1. /api/**            -> API routers (JSON, SSE). Unknown /api path -> JSON 404, never index.html
2. /assets/**         -> static files from dist/assets (immutable cache). Missing file -> 404
3. other real files   -> dist/ root files (favicon.ico, robots.txt, manifest.webmanifest)
4. everything else    -> dist/index.html (no-cache)  — only for GET/HEAD that accept text/html
```

The fallback must not swallow API or asset misses: a missing chunk answered with `index.html`
produces `text/html` where JS was expected and the browser fails with a confusing MIME-type error
instead of a clear 404.

## 4. FastAPI worked example

```python
# app/main.py
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

DIST = Path(__file__).resolve().parent.parent / "dist"
INDEX = DIST / "index.html"

app = FastAPI(openapi_url="/api/openapi.json", docs_url="/api/docs", redoc_url=None)
app.include_router(api_router, prefix="/api")          # 1. API first


class ImmutableStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


app.mount("/assets", ImmutableStatic(directory=DIST / "assets"), name="assets")   # 2. hashed assets


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def spa(full_path: str, request: Request):
    if full_path.startswith("api/") or full_path == "api":
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    candidate = (DIST / full_path).resolve()
    if full_path and candidate.is_file() and candidate.is_relative_to(DIST):   # 3. root files
        return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
    if "text/html" not in request.headers.get("accept", "text/html"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return FileResponse(INDEX, headers={"Cache-Control": "no-cache"})       # 4. SPA fallback
```

Notes:

- `StaticFiles(directory=..., html=True)` serves `index.html` for a directory and a `404.html` if
  present, but it does **not** do SPA fallback for client routes like `/queue/42`; the catch-all
  route above does.
- `is_relative_to` (Python 3.9+) blocks path traversal out of `dist/`.
- Register the catch-all **last**; FastAPI matches routes in registration order.
- Behind a reverse proxy, the proxy can serve `dist/` directly with the same rules; keep the
  API's fallback anyway so a direct hit behaves the same.
- For SSE endpoints behind nginx, disable proxy buffering for that location (see
  `sse-live-data.md`).

## 5. Cache headers

| Response | `Cache-Control` | Why |
|---|---|---|
| `/assets/*` (hashed) | `public, max-age=31536000, immutable` | The name changes when the content does; the browser never needs to revalidate |
| `index.html` and the SPA fallback | `no-cache` | Always revalidated (ETag / Last-Modified), so a deploy is picked up on next load |
| Unhashed root files (`favicon.ico`, `robots.txt`, `public/` copies) | `no-cache` or a short `max-age` | No hash, so no long cache |
| `/api/*` JSON | `no-store` for anything user-specific | Never cache personal or authorised data in shared caches |
| Service worker script (if any) | `no-cache` | Browsers cap SW script caching anyway; never `immutable` |

`no-cache` means "revalidate before use", not "do not store"; it keeps the HTML small and current
while hashed assets stay cached for a year.

## 6. Security headers on the HTML response

Set on `index.html` and the fallback (middleware is simplest):

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Cross-Origin-Opener-Policy: same-origin
```

Trusted Types and the auth-specific parts of the policy are in the `spa-auth-webauthn` skill. A
policy without `'unsafe-inline'` requires that the built `index.html` has no inline script: check
the built file, and see `supply-chain-hygiene.md` for SRI on the emitted tags.

## 7. OpenAPI → typed TS client

FastAPI already publishes the contract (`/api/openapi.json`). Generate the client from it rather
than hand-writing types.

**Stable operation ids first.** FastAPI's default operation id is `<function>_<path>_<method>`,
which yields names like `list_jobs_api_jobs_get`. Set a generator so the TypeScript names are
clean and stable:

```python
from fastapi.routing import APIRoute

def unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name

app = FastAPI(generate_unique_id_function=unique_id, ...)
```

Renaming a Python function then renames the generated TS function; treat that as an API change.
FastAPI's own client-generation guide recommends Hey API and shows stripping the `{tag}-` prefix
from the operation ids in the exported `openapi.json` (not in the app) if you want shorter names.

**Tool choice (dated, see the FRESHNESS block):**

| Tool | Generates | Pick when |
|---|---|---|
| `@hey-api/openapi-ts` | SDK functions + types, plugins for a fetch client, TanStack Query hooks and options, Zod schemas | You want generated TanStack Query options and runtime validation from one config |
| `openapi-typescript` + `openapi-fetch` | Types only + a tiny typed `fetch` wrapper | You want the smallest dependency and runtime footprint |
| `orval` | Clients and TanStack Query hooks, MSW mocks | You also want generated MSW handlers for tests |

`openapi-typescript-codegen` (used in older examples, including `api-auth-forms.md`) is no longer
maintained; do not start a new project on it.

`@hey-api/openapi-ts` example config:

```ts
// openapi-ts.config.ts
import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../backend/openapi.json",     // committed snapshot, not a live URL (see §8)
  output: { path: "src/api/gen", format: "prettier" },
  plugins: [
    "@hey-api/client-fetch",
    "@tanstack/react-query",
    "zod",
  ],
});
```

The fetch client is bundled into `@hey-api/openapi-ts` (the separate `@hey-api/client-fetch`
package is deprecated; keep the plugin name in the config). Configure the generated client once:
`client.setConfig({ baseUrl: "", credentials: "same-origin" })` for the same origin (the routers
are mounted under `/api`, so the OpenAPI paths already start with `/api`; a `baseUrl` of `/api`
would call `/api/api/...`), and add
the CSRF header with `client.interceptors.request.use(...)` (see `spa-auth-webauthn`).

## 8. Keeping client and server in sync (CI)

1. The backend writes a **committed snapshot** of the schema: a script imports the app and dumps
   `app.openapi()` to `backend/openapi.json` (sorted keys) — no server needed.
2. The frontend generates from that file (`npm run api:gen`), and the generated directory is either
   committed or regenerated in CI before `tsc`.
3. CI fails when either is stale:

```bash
python -m app.export_openapi > backend/openapi.json
npm run api:gen
git diff --exit-code backend/openapi.json frontend/src/api/gen   # stale snapshot or client
npm run typecheck                                                 # breaking change surfaces here
```

4. A breaking change (removed field, renamed operation) shows up as a TypeScript error in the
   same pull request that made it.
5. Pin the generator version exactly (pre-1.0 generators change output between minors).

## 9. Versioning and deploy skew

- Ship the SPA and the API in **one artifact** (one image) so a deploy changes both at once; then
  the snapshot in §8 is the whole compatibility story.
- A tab opened before a deploy still runs the old bundle: keep old hashed assets for at least one
  release (do not wipe `assets/` on deploy if served from a shared volume), and expose a build id
  (`/api/version` or a response header) so the SPA can show "a new version is available — reload"
  instead of failing on a removed endpoint.
- Lazy-loaded chunk 404s after a deploy: catch the dynamic-import error once and reload.
- If clients other than the SPA consume the API, version the API path (`/api/v1`) and stop
  treating the SPA snapshot as the only contract.

## 10. Anti-patterns

| Don't | Why | Do instead |
|---|---|---|
| Catch-all that returns `index.html` for `/api/*` and `/assets/*` misses | JSON clients get HTML; missing chunks fail with MIME errors | JSON 404 for API, plain 404 for assets, fallback only for HTML navigations |
| `max-age` on `index.html` | Users keep loading the old bundle after a deploy | `no-cache` on HTML; long immutable cache only on hashed files |
| Enabling CORS so the dev server can call the API | Becomes the production config; widens the attack surface | Vite `server.proxy` in dev; one origin in prod |
| Generating the client from a live URL in CI | Build depends on a running server; nondeterministic | Committed schema snapshot exported from the app |
| Default FastAPI operation ids | Unstable, unreadable generated names | `generate_unique_id_function` |
| Hand-written API types next to a generated client | Two sources of truth drift | Generated types only; wrap, do not redefine |
