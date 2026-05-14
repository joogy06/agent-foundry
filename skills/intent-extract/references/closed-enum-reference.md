# Closed-Enum Reference

Quick lookup for the four closed enumerations that the LLM MUST respect
when producing functional-intent.v1 output. Schema-enforced in
`~/.claude/skills/_meta/schemas/functional-intent.v1.json`.

## function_class (17 values)

| Value | When to use |
|---|---|
| `auth` | Token validation, identity verification, session management |
| `rbac` | Role lookup, permission checks, authorization |
| `crud` | Direct entity creation/read/update/delete against a single store |
| `pricing` | Cost calculation, discount logic, billing formulae |
| `routing` | URL → handler dispatch, message → consumer dispatch |
| `transform` | Pure data shape conversion (e.g. JSON → DB row) |
| `io` | Network IO, file IO, blob storage |
| `persistence` | Multi-step durable storage flows beyond pure CRUD |
| `cache` | Read-through / write-through cache layer |
| `queue` | Message publisher / consumer wiring |
| `scheduler` | Cron, recurring task, delayed job dispatch |
| `observability` | Metrics, traces, logs emission (the producer side) |
| `config` | Loading or mutating runtime configuration |
| `metric` | Aggregating numeric measurements (the consumer side of observability) |
| `glue` | Wiring between layers without significant logic |
| `test_harness` | Test fixtures, mocks, harness code (intentionally not "real" production) |
| `unknown` | Genuinely unable to classify from source. Prefer this over guessing. |

## entry_points.kind (9 values)

| Value | Recognise via |
|---|---|
| `http_route` | FastAPI `@app.get(...)`, Flask `@app.route`, Express `app.get(...)` |
| `grpc_method` | `.proto` files referencing the symbol; `grpc.aio.server` registrations |
| `queue_consumer` | Decorators / handlers for Kafka, RabbitMQ, SQS, Redis pub/sub |
| `cron` | `@cron.scheduled_job`, k8s CronJob spec, Celery beat schedule |
| `cli` | `argparse` / `click` / `typer` entrypoints; `if __name__ == "__main__"` |
| `rpc_server` | Custom RPC frameworks (JSON-RPC, Thrift) |
| `lib_api` | Public functions exported as a library API (no transport) |
| `sdk_init` | `__init__` of an SDK client class, exposed to importers |
| `event_handler` | EventBridge, WebSocket message handler, signal handler |

## side_effects.kind (9 values)

| Value | Examples |
|---|---|
| `cache_write` | `redis.set`, `memcache.add`, in-memory cache write |
| `db_write` | `session.add` + `commit`, raw INSERT/UPDATE/DELETE |
| `network_io` | Outbound HTTP/gRPC/TCP, posting to an external API |
| `file_io` | `open(path, "w")`, `os.makedirs`, `pathlib.Path.write_*` |
| `log_emit` | `logger.info / .error / .warn` (anything that goes to log infra) |
| `metric_emit` | StatsD push, Prometheus counter increment, OpenTelemetry span |
| `env_mutation` | `os.environ[X] = Y` |
| `clipboard` | OS clipboard write (rare in backend code; flag if seen) |
| `gpu_alloc` | `torch.cuda.allocate`, CUDA context init |

## error_paths.error_kind (5 values)

| Value | Means |
|---|---|
| `raises` | Exception propagated up the call stack |
| `returns_error` | Function returns a Result / Err / None / error tuple |
| `http_status_5xx` | HTTP framework converts the error to a 5xx response |
| `swallowed` | `except: log; continue` — error caught, logged, and absorbed |
| `unhandled` | No error path was detected in source. Surface as advisory — the LLM is being honest about a gap, not pretending coverage |

`raises` and `returns_error` are the most common in well-instrumented
production code. `swallowed` is a smell worth surfacing to the user.
`unhandled` is the "I can't see how this is handled" honest answer and
should be paired with an entry in `unknowns[]`.
