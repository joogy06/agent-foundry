// k6-template.js
//
// Parameterised k6 load-test scaffold. The caller (AI agent or CI job) fills
// the placeholders below from a perf-test-contract YAML (see
// references/perf-test-contract-template.md) and runs:
//
//   k6 run \
//     -e TARGET_URL=https://staging.example.com \
//     -e VUS=50 \
//     -e DURATION=5m \
//     -e P95_MS=200 \
//     -e ERROR_RATE=0.01 \
//     k6-template.js
//
// Required env vars:
//   TARGET_URL   — fully-qualified base URL of the system under test
//   VUS          — steady-state virtual users (number)
//   DURATION     — steady-state duration (k6 duration string, e.g. '5m')
//
// Optional env vars (with defaults):
//   SCENARIO     — smoke | load | stress | spike | soak | ramp-to-failure  (default: load)
//   WARMUP       — warmup duration (default: '60s')
//   P95_MS       — p95 latency threshold in ms (default: 500)
//   P99_MS       — p99 latency threshold in ms (default: 1000)
//   ERROR_RATE   — max error rate as fraction (default: 0.01)
//   THINK_TIME_MS — per-iteration sleep in ms (default: 1000)
//   PERF_ENV     — environment tier label; must be set to non-empty value
//                   (enforces references/test-reality-model.md § Environment
//                   isolation)

import http from 'k6/http';
import { check, sleep, fail } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const TARGET_URL = __ENV.TARGET_URL;
const VUS = parseInt(__ENV.VUS || '50', 10);
const DURATION = __ENV.DURATION || '5m';
const SCENARIO = __ENV.SCENARIO || 'load';
const WARMUP = __ENV.WARMUP || '60s';
const P95_MS = parseInt(__ENV.P95_MS || '500', 10);
const P99_MS = parseInt(__ENV.P99_MS || '1000', 10);
const ERROR_RATE = parseFloat(__ENV.ERROR_RATE || '0.01');
const THINK_TIME_MS = parseInt(__ENV.THINK_TIME_MS || '1000', 10);
const PERF_ENV = __ENV.PERF_ENV || '';

if (!TARGET_URL) {
  throw new Error('k6-template: TARGET_URL is required.');
}
if (!PERF_ENV) {
  throw new Error('k6-template: PERF_ENV must be set (e.g. staging, preprod, dedicated-perf). Never run against prod without explicit approval — see test-reality-model.md.');
}
if (/prod|production/i.test(PERF_ENV)) {
  throw new Error('k6-template: PERF_ENV looks like production (' + PERF_ENV + '). Refusing to run. See test-reality-model.md § Environment isolation.');
}

export const errors = new Rate('errors');
export const businessLatency = new Trend('business_latency_ms', true);

// Scenario → k6 stages map. Keeps the profile generator in one place so the
// caller swaps scenario types without hand-editing stages.
function stagesFor(scenario, vus, duration) {
  switch (scenario) {
    case 'smoke':
      return [{ duration: '30s', target: 1 }];
    case 'stress':
      return [
        { duration: '1m', target: vus },
        { duration: '2m', target: vus * 2 },
        { duration: '2m', target: vus * 3 },
        { duration: '1m', target: 0 },
      ];
    case 'spike':
      return [
        { duration: '30s', target: vus },
        { duration: '30s', target: vus * 5 },
        { duration: '1m', target: vus * 5 },
        { duration: '30s', target: vus },
      ];
    case 'soak':
      return [
        { duration: WARMUP, target: vus },
        { duration: '1h', target: vus },
      ];
    case 'ramp-to-failure':
      return [
        { duration: '1m', target: Math.max(1, Math.floor(vus / 4)) },
        { duration: '3m', target: vus },
        { duration: '3m', target: vus * 2 },
        { duration: '3m', target: vus * 4 },
        { duration: '3m', target: vus * 8 },
        { duration: '1m', target: 0 },
      ];
    case 'load':
    default:
      return [
        { duration: WARMUP, target: vus },
        { duration: duration, target: vus },
        { duration: '30s', target: 0 },
      ];
  }
}

export const options = {
  stages: stagesFor(SCENARIO, VUS, DURATION),
  thresholds: {
    http_req_failed: ['rate<' + ERROR_RATE],
    http_req_duration: ['p(95)<' + P95_MS, 'p(99)<' + P99_MS],
    errors: ['rate<' + ERROR_RATE],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(95)', 'p(99)'],
  // Emit machine-readable results for capacity-model.py to consume.
  // Redirect by piping k6 output or using k6 --out json=result.json.
};

// Fill this with the actual request mix from your contract. The default probes
// a single endpoint — replace with login → browse → checkout flows as needed.
export default function () {
  const start = Date.now();
  const res = http.get(TARGET_URL);
  const passed = check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
  });
  if (!passed) {
    errors.add(1);
  } else {
    errors.add(0);
    businessLatency.add(Date.now() - start);
  }
  sleep(THINK_TIME_MS / 1000);
}

// handleSummary emits the capacity-model.py JSON envelope (see
// references/perf-test-contract-template.md → Capacity JSON schema) alongside
// the default summary.
export function handleSummary(data) {
  const envelope = {
    test_metadata: {
      duration_seconds: Math.round((data.state && data.state.testRunDurationMs ? data.state.testRunDurationMs : 0) / 1000),
      scenario: SCENARIO,
      warmup_seconds: typeof WARMUP === 'string' && WARMUP.endsWith('s') ? parseInt(WARMUP, 10) : 60,
      tool: 'k6',
    },
    measurements: [],  // caller populates from server-side monitoring
    concurrency_observed: {
      users: VUS,
      concurrent_processes_per_user_avg: null,  // unknown from k6 alone
    },
    // raw metrics for debugging
    _k6_metrics: {
      http_req_duration_p95: data.metrics.http_req_duration ? data.metrics.http_req_duration.values['p(95)'] : null,
      http_req_duration_p99: data.metrics.http_req_duration ? data.metrics.http_req_duration.values['p(99)'] : null,
      http_req_failed_rate: data.metrics.http_req_failed ? data.metrics.http_req_failed.values.rate : null,
    },
  };
  return {
    stdout: JSON.stringify(envelope, null, 2),
    'capacity-input.json': JSON.stringify(envelope, null, 2),
  };
}
