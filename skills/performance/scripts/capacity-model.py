"""capacity-model.py

Reads the Capacity JSON envelope produced by k6-template.js / locust-template.py
(or any other load tool whose harness conforms to the schema) and emits a
capacity-model.md headroom report.

Schema contract — must match capacity-planning.md § Capacity JSON schema:

    {
      "test_metadata": {
        "duration_seconds": int,
        "scenario": "ramp-to-failure" | "load" | ...,
        "warmup_seconds": int,
        "tool": "k6" | "locust" | ...
      },
      "measurements": [
        {
          "resource": "cpu" | "memory" | "db_connections" | "worker_threads"
                      | "network_bandwidth" | "external_api_quota",
          "ceiling": number,
          "current_load": number,
          "per_user_cost": number,
          "measurement_window_seconds": int,
          "p50": number,
          "p95": number,
          "p99": number
        }
      ],
      "concurrency_observed": {
        "users": int,
        "concurrent_processes_per_user_avg": number | null
      }
    }

Usage:

    python capacity-model.py capacity-input.json \
        --forecast-growth 0.5 \
        --output capacity-model.md

Exit codes:
    0 — report written
    1 — usage error
    2 — input JSON fails schema validation

No third-party dependencies — stdlib only so this runs in any CI lane without
install steps.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_RESOURCES = {
    "cpu",
    "memory",
    "db_connections",
    "worker_threads",
    "network_bandwidth",
    "external_api_quota",
}


@dataclass
class Measurement:
    resource: str
    ceiling: float
    current_load: float
    per_user_cost: float
    p50: float
    p95: float
    p99: float
    window_s: int


def _validate(envelope: dict[str, Any]) -> list[Measurement]:
    """Raises ValueError with a specific message on any schema miss."""
    if "test_metadata" not in envelope:
        raise ValueError("missing test_metadata")
    meta = envelope["test_metadata"]
    for key in ("duration_seconds", "scenario", "warmup_seconds", "tool"):
        if key not in meta:
            raise ValueError(f"test_metadata missing {key!r}")
    if "measurements" not in envelope or not isinstance(envelope["measurements"], list):
        raise ValueError("measurements must be a list")
    if "concurrency_observed" not in envelope:
        raise ValueError("missing concurrency_observed")

    out: list[Measurement] = []
    for idx, m in enumerate(envelope["measurements"]):
        for key in (
            "resource",
            "ceiling",
            "current_load",
            "per_user_cost",
            "measurement_window_seconds",
            "p50",
            "p95",
            "p99",
        ):
            if key not in m:
                raise ValueError(f"measurement[{idx}] missing {key!r}")
        if m["resource"] not in ALLOWED_RESOURCES:
            raise ValueError(
                f"measurement[{idx}].resource {m['resource']!r} not in {sorted(ALLOWED_RESOURCES)}",
            )
        if m["per_user_cost"] < 0:
            raise ValueError(f"measurement[{idx}].per_user_cost must be >= 0")
        if m["ceiling"] <= 0:
            raise ValueError(f"measurement[{idx}].ceiling must be > 0")
        out.append(
            Measurement(
                resource=m["resource"],
                ceiling=float(m["ceiling"]),
                current_load=float(m["current_load"]),
                per_user_cost=float(m["per_user_cost"]),
                p50=float(m["p50"]),
                p95=float(m["p95"]),
                p99=float(m["p99"]),
                window_s=int(m["measurement_window_seconds"]),
            ),
        )
    return out


def _headroom_users(m: Measurement) -> float | None:
    """Return additional users the resource can absorb, or None if per_user_cost is 0."""
    if m.per_user_cost <= 0:
        return None
    available = max(0.0, m.ceiling - m.current_load)
    return available / m.per_user_cost


def _first_ceiling_hit(measurements: list[Measurement], growth: float) -> tuple[str | None, float | None]:
    """Project `growth` fraction more load on each resource and return the first to hit ceiling.

    growth=0.5 means "current load × 1.5". Returns (resource_name, headroom_factor) where
    headroom_factor is current_load/(ceiling/(1+growth)) — values >=1 mean ceiling breached.
    """
    worst: tuple[str | None, float | None] = (None, None)
    for m in measurements:
        projected = m.current_load * (1.0 + growth)
        if projected <= 0:
            continue
        ratio = projected / m.ceiling if m.ceiling > 0 else float("inf")
        if worst[1] is None or ratio > worst[1]:
            worst = (m.resource, ratio)
    return worst


def _render(envelope: dict[str, Any], measurements: list[Measurement], growth: float) -> str:
    meta = envelope["test_metadata"]
    conc = envelope["concurrency_observed"]

    lines: list[str] = []
    lines.append("# Capacity Model")
    lines.append("")
    lines.append(f"- Source tool: `{meta['tool']}`")
    lines.append(f"- Scenario: `{meta['scenario']}`")
    lines.append(f"- Duration: {meta['duration_seconds']}s (warmup {meta['warmup_seconds']}s)")
    lines.append(f"- Observed users: {conc.get('users')}")
    ppu = conc.get("concurrent_processes_per_user_avg")
    if ppu is not None:
        lines.append(f"- Concurrent processes per user (avg): {ppu}")
    lines.append("")

    lines.append("## Per-resource headroom")
    lines.append("")
    lines.append("| resource | ceiling | current | per-user cost | p50 | p95 | p99 | additional users |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m in measurements:
        extra = _headroom_users(m)
        extra_s = f"{extra:,.1f}" if extra is not None else "n/a (zero per-user cost)"
        lines.append(
            f"| {m.resource} | {m.ceiling:g} | {m.current_load:g} | {m.per_user_cost:g} | "
            f"{m.p50:g} | {m.p95:g} | {m.p99:g} | {extra_s} |",
        )
    lines.append("")

    lines.append(f"## Forecast at +{growth * 100:.0f}% load")
    lines.append("")
    resource, ratio = _first_ceiling_hit(measurements, growth)
    if resource is None or ratio is None:
        lines.append("No forecast computable (empty measurement set).")
    else:
        state = "BREACHED" if ratio >= 1.0 else "headroom remains"
        lines.append(f"- First resource to be stressed: `{resource}` (projected load / ceiling = {ratio:.2f}, {state})")
        lines.append("")
        lines.append("Projected per-resource load:")
        lines.append("")
        lines.append("| resource | projected | ceiling | utilisation |")
        lines.append("|---|---|---|---|")
        for m in measurements:
            projected = m.current_load * (1.0 + growth)
            util = projected / m.ceiling if m.ceiling > 0 else float("inf")
            flag = " *(breach)*" if util >= 1.0 else ""
            lines.append(f"| {m.resource} | {projected:g} | {m.ceiling:g} | {util:.2f}{flag} |")
    lines.append("")

    lines.append("## Recommended next load test")
    lines.append("")
    if resource is not None and ratio is not None and ratio >= 1.0:
        lines.append(
            f"Run a ramp-to-failure test focused on `{resource}`. "
            "See load-testing.md § Capacity Validation Patterns for the ramp profile.",
        )
    else:
        lines.append(
            "Run a stepped-concurrency test at the forecast load to confirm the model. "
            "See load-testing.md § Capacity Validation Patterns.",
        )
    lines.append("")
    lines.append(
        "Synthesise improvements by consulting `references/improvement-catalog.md` "
        "filtered by the stressed resource and the detected stack.",
    )
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Compute headroom from a load-test JSON envelope.")
    ap.add_argument("input", help="Path to capacity-input.json (matches Capacity JSON schema)")
    ap.add_argument(
        "--forecast-growth",
        type=float,
        default=0.5,
        help="Fractional growth to project (default 0.5 → +50%%)",
    )
    ap.add_argument("--output", default="capacity-model.md", help="Path to write the markdown report")
    args = ap.parse_args(argv)

    try:
        raw = Path(args.input).read_text(encoding="utf-8")
        envelope = json.loads(raw)
    except OSError as exc:
        print(f"capacity-model: cannot read {args.input}: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"capacity-model: invalid JSON: {exc}", file=sys.stderr)
        return 2

    try:
        measurements = _validate(envelope)
    except ValueError as exc:
        print(f"capacity-model: schema validation failed: {exc}", file=sys.stderr)
        return 2

    report = _render(envelope, measurements, args.forecast_growth)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"capacity-model: wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
