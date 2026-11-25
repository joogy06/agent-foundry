# Live data in React over Server-Sent Events (SSE)

Reference file for the `modern-frontend` skill. Covers the `EventSource` lifecycle, reconnect and
backoff, `Last-Event-ID` resume, authentication on SSE, mapping events to TanStack Query
invalidation or direct cache patches, batching to avoid render storms, and tab visibility.

## Contents

- 1. When SSE fits
- 2. Server contract
- 3. EventSource lifecycle and reconnection
- 4. Authentication on SSE
- 5. One connection per tab: the provider
- 6. Events → TanStack Query: invalidate or patch
- 7. Batching: avoiding render storms
- 8. Tab visibility and resume
- 9. Freshness and connection state in the UI
- 10. Testing
- 11. Anti-patterns

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: eventsource-spec
    source_url: https://html.spec.whatwg.org/multipage/server-sent-events.html
    verified_on: 2026-10-26
    review_by: 2027-04-26
    claim: "EventSource reconnects with Last-Event-ID after a network error on an open stream; fails permanently (readyState CLOSED) on a non-200 status or a wrong Content-Type; cannot set request headers; withCredentials for cross-origin cookies."
  - kind: external_fact
    subject: tanstack-query-v5
    source_url: https://www.npmjs.com/package/@tanstack/react-query
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "@tanstack/react-query 5.105.0: invalidateQueries/setQueryData/setQueriesData/cancelQueries take object filters; notifyManager.batch exported; streamedQuery exported as experimental_streamedQuery (read from query-core typings)."
  - kind: external_fact
    subject: fastapi-sse
    source_url: https://pypi.org/project/fastapi/
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "FastAPI 0.162.0 ships fastapi.sse.EventSourceResponse and ServerSentEvent; sends a ': ping' keepalive every 15 s when idle and sets Cache-Control: no-cache and X-Accel-Buffering: no (read from the package source)."
-->

## 1. When SSE fits

| Need | Choose |
|---|---|
| Server → browser notifications, change feeds, progress, logs | **SSE** (plain HTTP, auto-reconnect, cookies sent, proxies understand it) |
| Bidirectional, high-rate client → server messages | WebSocket |
| Updates every minute or slower, or very few clients | Polling with TanStack Query `refetchInterval` |
| Must send custom headers (bearer token) | A fetch-based SSE client (§4), or move to a cookie session |

Over HTTP/1.1 a browser allows about six connections per origin, shared across tabs; each open
`EventSource` holds one. Serve SSE over HTTP/2 or HTTP/3 (one multiplexed connection) or keep to
one stream per tab.

## 2. Server contract

```text
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no            # nginx: do not buffer this response

retry: 5000                      # reconnect delay hint in ms
id: 18442                        # monotonically increasing per stream; the resume cursor
event: job.updated               # optional type; omitted = "message"
data: {"id":"j_42","version":7,"status":"running","updated_at":"2026-10-26T14:20:10Z"}

event: heartbeat                 # every 15-30 s: a NAMED event, because the browser drops ": comment"
data: {"ts":"2026-10-26T14:20:25Z"}   # lines before JavaScript sees them
```

FastAPI ships SSE natively since 0.135.0 (`fastapi.sse`, read in 0.162.0): declare
`response_class=EventSourceResponse` and `yield ServerSentEvent(data=..., event=..., id=...)`;
it sends a `: ping` keepalive every 15 s while idle and sets `Cache-Control: no-cache` and
`X-Accel-Buffering: no` itself. `sse-starlette` is no longer needed for new FastAPI code.

```python
from fastapi.sse import EventSourceResponse, ServerSentEvent

@router.get("/events", response_class=EventSourceResponse)
async def events(request: Request, after: str | None = None,
                 last_event_id: str | None = Header(None), session=Depends(require_session)):
    cursor = last_event_id or after                        # header on browser retry, query on our reconnect
    feed = change_feed(since=cursor, user=session.user_id).__aiter__()  # e.g. outbox rows fed by LISTEN/NOTIFY
    while not await request.is_disconnected():
        try:
            ev = await asyncio.wait_for(feed.__anext__(), timeout=15)
        except asyncio.TimeoutError:                       # idle: an app-visible heartbeat
            yield ServerSentEvent(data={"ts": utcnow_iso()}, event="heartbeat")
            continue
        except StopAsyncIteration:
            break
        # ev.payload_json is already JSON text (e.g. a NOTIFY payload): raw_data avoids double encoding.
        # data= would JSON-encode it again, strings included.
        yield ServerSentEvent(raw_data=ev.payload_json, event=ev.type, id=str(ev.seq))
```

- **Ids are a resume cursor**, e.g. a database sequence or the outbox row id; the server must be
  able to replay events after a given id (or answer "too old" so the client refetches everything).
- **Events are small change notices**, carrying the entity id, its new `version`, and the changed
  fields or the whole small entity. Large payloads belong in a normal GET.
- Send a **named heartbeat event** at a fixed interval; the client uses it to detect a silent
  dead connection. FastAPI's built-in `: ping` comment keeps proxies from timing the connection
  out, but comment lines never reach JavaScript (WHATWG event-stream parsing ignores them), so they
  cannot drive the client's liveness check.
- On "resume impossible" (id older than retention) send a typed event such as `event: reset` and
  let the client invalidate everything.

## 3. EventSource lifecycle and reconnection

What the browser does for you (WHATWG HTML spec):

- On a network error **after** a successful connection it reconnects automatically, waiting the
  `retry:` value (default a few seconds), and sends the last received `id` in a `Last-Event-ID`
  request header on the reconnect. This happens only within the same `EventSource` object.
- `readyState`: `0` CONNECTING, `1` OPEN, `2` CLOSED. `onerror` fires on every drop; check
  `readyState` to know whether the browser is retrying (`0`) or has given up (`2`).
- The browser **gives up permanently** (state `2`, no retry) when the response is not `200`, or
  its `Content-Type` is not `text/event-stream`. A `401` after session expiry therefore closes the
  stream for good: your code must notice, re-authenticate and create a new `EventSource`.
- A new `EventSource` you create yourself does **not** send `Last-Event-ID`; pass the cursor in the
  URL (`/api/events?after=18442`) and have the server accept either.

Backoff policy for reconnects **you** perform (after state `2`, or after closing for visibility):
exponential with full jitter, e.g. base 1 s, cap 30–60 s, reset after a connection stays open for
a minute. Never reconnect in a tight loop on `onerror`.

## 4. Authentication on SSE

`EventSource` cannot set request headers. Options, in order of preference:

1. **Same-origin cookie session** (the default in `spa-auth-webauthn`): the cookie is sent
   automatically; no code needed. Check authorisation per event on the server, not only at
   connect time, and close the stream when the session is revoked.
2. **Cross-origin with cookies:** `new EventSource(url, { withCredentials: true })` plus a CORS
   policy that names the origin and allows credentials.
3. **Bearer token required:** use a fetch-based SSE client (it can set headers but you then own
   reconnection and `Last-Event-ID`; the often-cited `@microsoft/fetch-event-source` has not
   been published since 2021), or exchange the token for a short-lived, single-use stream
   ticket in the URL. Never put the long-lived token itself in the query string (it lands in logs).

## 5. One connection per tab: the provider

```tsx
// live/EventStreamProvider.tsx
type Listener = (type: string, data: unknown, id: string) => void;

export function EventStreamProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<"connecting" | "open" | "retrying" | "closed">("connecting");
  const lastId = useRef<string | null>(null);
  const lastSeen = useRef<number>(Date.now());

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const connect = () => {
      const url = lastId.current ? `/api/events?after=${encodeURIComponent(lastId.current)}` : "/api/events";
      es = new EventSource(url);
      es.onopen = () => { setStatus("open"); attempt = 0; };
      es.onerror = () => {
        if (es?.readyState === EventSource.CLOSED) {          // browser gave up (401, 5xx, bad type)
          setStatus("closed");
          es.close();
          const delay = Math.min(30_000, 1000 * 2 ** attempt++) * Math.random();
          timer = setTimeout(async () => {
            if (await sessionStillValid()) connect(); else redirectToSignIn();
          }, delay);
        } else {
          setStatus("retrying");                             // browser is retrying with Last-Event-ID
        }
      };
      es.addEventListener("heartbeat", () => { lastSeen.current = Date.now(); });
      for (const type of HANDLED_TYPES) {
        es.addEventListener(type, (e) => {
          const ev = e as MessageEvent<string>;
          lastSeen.current = Date.now();
          if (ev.lastEventId) lastId.current = ev.lastEventId;
          enqueue(qc, type, JSON.parse(ev.data));            // §7 batching
        });
      }
      es.addEventListener("reset", () => qc.invalidateQueries());
    };

    connect();
    return () => { clearTimeout(timer); es?.close(); };      // cleanup on unmount
  }, [qc]);

  return <StreamStatusContext.Provider value={{ status, lastSeen }}>{children}</StreamStatusContext.Provider>;
}
```

Mount it once, inside the `QueryClientProvider` and the authenticated part of the tree. Components
never open their own `EventSource`; they read data through queries and read connection state from
the context.

## 6. Events → TanStack Query: invalidate or patch

TanStack Query v5 API names (object syntax only in v5).

| Event carries | Action | Call |
|---|---|---|
| Only "X changed" (id, maybe version) | Invalidate; active queries refetch, inactive ones refetch on next use | `qc.invalidateQueries({ queryKey: ["jobs", id] })` |
| The full new entity with a `version` | Patch the detail cache if the version is newer | `qc.setQueryData(["jobs", id], (old) => newer(old, ev) ? ev : old)` |
| A change that affects lists (status, sort key, membership) | Invalidate the list queries; optionally patch the row in place for immediate feedback | `qc.invalidateQueries({ queryKey: ["jobs", "list"] })` |
| A change to many list variants (filters, pages) | Patch every cached list that contains the row | `qc.setQueriesData({ queryKey: ["jobs", "list"] }, patchRow(ev))` |
| Unknown or out-of-order version | Invalidate rather than guess | — |

Rules:

- **Version guard every patch.** Events can arrive before the response of a fetch that started
  earlier; never let an older version overwrite a newer one.
- **Do not patch while a mutation for the same entity is in flight** if that mutation does its own
  optimistic update; call `qc.cancelQueries({ queryKey })` first or let the mutation's
  `onSettled` invalidate.
- **Prefer invalidation for lists** with server-side sorting, filtering or pagination: the client
  cannot know where the row now belongs.
- With a live stream feeding the cache, set a longer `staleTime` on those queries (the stream keeps
  them fresh) and keep `refetchOnWindowFocus` as the safety net for missed events.
- Query keys come from one key factory module so events and components agree on them.
- `experimental_streamedQuery` (TanStack Query 5.x) fits one query fed by one stream (a log tail,
  an LLM answer); it is not a fan-out mechanism for a shared change feed, which is this pattern.

## 7. Batching: avoiding render storms

A burst of 500 events must not produce 500 renders.

```ts
// Coalesce per animation frame (or a 50-100 ms timer when the tab is hidden).
const pending = new Map<string, { type: string; data: any }>();   // last event per entity wins
let scheduled = false;

function enqueue(qc: QueryClient, type: string, data: any) {
  pending.set(`${type}:${data.id}`, { type, data });
  if (scheduled) return;
  scheduled = true;
  const flush = () => {
    scheduled = false;
    const batch = [...pending.values()];
    pending.clear();
    notifyManager.batch(() => {                     // one notification pass for all cache writes
      const invalidate = new Set<string>();
      for (const { type, data } of batch) apply(qc, type, data, invalidate);
      for (const k of invalidate) qc.invalidateQueries({ queryKey: JSON.parse(k) });
    });
  };
  document.hidden ? setTimeout(flush, 100) : requestAnimationFrame(flush);
}
```

- Coalesce by entity (last write wins, with the version guard) and **deduplicate invalidations**
  in a batch.
- `notifyManager.batch` groups cache notifications so subscribed components re-render once per
  batch; React 18+ also batches state updates automatically.
- Very high rates (hundreds per second): parse and coalesce in a Web Worker and post one snapshot
  per frame (the pattern in `trading-dashboard-ux` §6).
- Virtualise long lists so a patch re-renders only visible rows; use `select` in `useQuery` so a
  component subscribes to the slice it shows.

## 8. Tab visibility and resume

- Background tabs throttle timers and may be frozen or discarded; a stream in a hidden tab can be
  stale or dead without an error event.
- Policy that works: on `visibilitychange` to hidden, start a grace timer (for example 5 minutes)
  and close the stream when it expires; on visible, reconnect with the stored cursor (§3) and call
  `qc.invalidateQueries()` for live views if the cursor was refused or the gap was long.
- Open connections can keep a page out of the back/forward cache in some browsers (web.dev bfcache
  guidance); close the stream on `pagehide` and reopen on `pageshow`.
- Hidden-tab timer throttling (Chrome's intensive throttling after 5 minutes) delays heartbeat and
  backoff timers; re-check liveness on `visibilitychange` rather than trusting a timer.
- Use the heartbeat: if nothing (data event or `heartbeat` event) arrived within 2× the interval,
  treat the stream as dead, close it and reconnect.

## 9. Freshness and connection state in the UI

Expose `status` and `lastSeen` from the provider and render them: "Live", "Reconnecting…",
"Offline — data as of 14:20:10". Views past their staleness budget degrade visibly and disable
actions that need current state (rule and layout in `operator-console-ux` §4). A connected stream
with no events past the heartbeat budget is not "Live".

## 10. Testing

- Unit-test `apply` (event → cache) as a pure function against a real `QueryClient`.
- Mock the stream in component tests by stubbing `EventSource` with a controllable fake; MSW can
  also return `text/event-stream` responses for integration tests.
- End-to-end: kill the server mid-stream and assert "Reconnecting…", then assert resumed events
  after restart are applied once (no duplicates, no gaps).

## 11. Anti-patterns

| Don't | Why | Do instead |
|---|---|---|
| `new EventSource` in every component that needs updates | Exhausts the per-origin connection limit on HTTP/1.1; duplicate events | One provider per tab |
| `setState` per event | Render storm under bursts | Coalesce per frame; batch cache writes |
| Patching the cache without a version check | Older data overwrites newer | Version-guarded `setQueryData` |
| Patching sorted, filtered or paginated lists by hand | Row lands in the wrong page or position | Invalidate list queries |
| Ignoring `readyState === CLOSED` in `onerror` | A 401 silently ends live updates forever | Detect, re-auth, reconnect with backoff |
| Long-lived bearer token in the SSE URL | Logged by proxies and servers | Cookie session or a short-lived single-use ticket |
| No heartbeat, or a `:` comment used as one | A dead connection looks like a quiet system; comments never reach JS | Named `heartbeat` event; stale after 2× interval |
| Reconnect loop with no backoff | Thundering herd after a server restart | Exponential backoff with jitter |
