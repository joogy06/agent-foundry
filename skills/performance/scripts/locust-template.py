"""locust-template.py

Parameterised Locust load-test scaffold. Same scope as k6-template.js but for
teams already standardised on Python/Locust.

Usage:

    locust -f locust-template.py \
        --headless \
        -u 50 -r 5 -t 5m \
        --host https://staging.example.com \
        --html report.html \
        --json > capacity-input.json

Required env vars:
    PERF_ENV              — environment tier label (staging / preprod /
                            dedicated-perf). Refuses to run against prod.

Optional env vars (with defaults):
    WARMUP_SECONDS        — 60
    THINK_TIME_MIN        — 0.5
    THINK_TIME_MAX        — 2.0
    P95_MS                — 500
    ERROR_RATE            — 0.01
    SCENARIO              — load  (label only; stages set by CLI flags)

See references/perf-test-contract-template.md for the contract → script
mapping and references/test-reality-model.md for pre-flight requirements.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from locust import HttpUser, between, events, task


PERF_ENV = os.environ.get("PERF_ENV", "")
WARMUP_SECONDS = int(os.environ.get("WARMUP_SECONDS", "60"))
THINK_TIME_MIN = float(os.environ.get("THINK_TIME_MIN", "0.5"))
THINK_TIME_MAX = float(os.environ.get("THINK_TIME_MAX", "2.0"))
P95_MS = int(os.environ.get("P95_MS", "500"))
ERROR_RATE_MAX = float(os.environ.get("ERROR_RATE", "0.01"))
SCENARIO = os.environ.get("SCENARIO", "load")


if not PERF_ENV:
    print(
        "locust-template: PERF_ENV must be set (staging / preprod / dedicated-perf). "
        "See test-reality-model.md § Environment isolation.",
        file=sys.stderr,
    )
    sys.exit(2)
if "prod" in PERF_ENV.lower():
    print(
        f"locust-template: PERF_ENV looks like production ({PERF_ENV}). Refusing to run. "
        "See test-reality-model.md § Environment isolation.",
        file=sys.stderr,
    )
    sys.exit(2)


class ContractUser(HttpUser):
    """Replace the tasks below with the request mix defined in your contract.

    The default probes a single endpoint — real contracts usually combine
    login, browse, and checkout tasks with relative weights.
    """

    wait_time = between(THINK_TIME_MIN, THINK_TIME_MAX)

    @task
    def probe(self) -> None:
        self.client.get("/")


@events.test_start.add_listener
def _on_start(environment: Any, **_: Any) -> None:
    print(
        f"locust-template: scenario={SCENARIO} perf_env={PERF_ENV} warmup={WARMUP_SECONDS}s",
        file=sys.stderr,
    )
    print(
        "locust-template: warmup ignored by this template beyond a label — use "
        "--run-time plus a manual warmup ramp (--spawn-rate) to approximate.",
        file=sys.stderr,
    )


@events.test_stop.add_listener
def _on_stop(environment: Any, **_: Any) -> None:
    stats = environment.stats.total
    p95 = stats.get_response_time_percentile(0.95) or 0
    p99 = stats.get_response_time_percentile(0.99) or 0
    fail_ratio = stats.fail_ratio
    duration = int(time.time() - environment.runner.start_time) if environment.runner else 0
    envelope = {
        "test_metadata": {
            "duration_seconds": duration,
            "scenario": SCENARIO,
            "warmup_seconds": WARMUP_SECONDS,
            "tool": "locust",
        },
        "measurements": [],
        "concurrency_observed": {
            "users": environment.runner.user_count if environment.runner else None,
            "concurrent_processes_per_user_avg": None,
        },
        "_locust_metrics": {
            "http_req_duration_p95_ms": p95,
            "http_req_duration_p99_ms": p99,
            "http_req_failed_rate": fail_ratio,
            "thresholds": {
                "p95_ms": P95_MS,
                "error_rate_max": ERROR_RATE_MAX,
            },
        },
    }
    with open("capacity-input.json", "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2)
    print("locust-template: wrote capacity-input.json", file=sys.stderr)

    # Non-zero exit on threshold breach so CI fails.
    if p95 > P95_MS:
        print(f"locust-template: p95 {p95:.0f}ms > {P95_MS}ms threshold", file=sys.stderr)
        environment.process_exit_code = 1
    if fail_ratio > ERROR_RATE_MAX:
        print(
            f"locust-template: error rate {fail_ratio:.4f} > {ERROR_RATE_MAX:.4f} threshold",
            file=sys.stderr,
        )
        environment.process_exit_code = 1
