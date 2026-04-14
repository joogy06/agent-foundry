// lighthouse-ci-template.js
//
// Lighthouse CI (lhci) configuration template. Drop this in the consuming
// repo as `lighthouserc.js`, fill the URL + budget placeholders from your
// perf-test-contract YAML, then run:
//
//     npx @lhci/cli autorun --config=lighthouserc.js
//
// Budgets map directly to frontend-performance.md Core Web Vitals targets.
// Any assertion failure exits non-zero so CI fails on regressions.
//
// See references/perf-test-contract-template.md for the contract → config
// mapping and references/test-reality-model.md for environment isolation.

// Required:
//   LHCI_TARGET_URL — URL to audit (must NOT be production; validated below).
//   LHCI_PERF_ENV   — environment tier label.
//
// Optional budgets (with defaults):
//   LHCI_LCP_MS=2500
//   LHCI_CLS=0.1
//   LHCI_INP_MS=200
//   LHCI_TBT_MS=200
//   LHCI_PERFORMANCE_SCORE=0.85
//   LHCI_RUNS=3

const url = process.env.LHCI_TARGET_URL;
const env = process.env.LHCI_PERF_ENV || '';
if (!url) {
  throw new Error('lighthouse-ci-template: LHCI_TARGET_URL env is required.');
}
if (!env) {
  throw new Error(
    'lighthouse-ci-template: LHCI_PERF_ENV must be set. See test-reality-model.md § Environment isolation.',
  );
}
if (/prod|production/i.test(env)) {
  throw new Error(
    `lighthouse-ci-template: LHCI_PERF_ENV looks like production (${env}). Refusing.`,
  );
}

const lcpMs = parseInt(process.env.LHCI_LCP_MS || '2500', 10);
const cls = parseFloat(process.env.LHCI_CLS || '0.1');
const inpMs = parseInt(process.env.LHCI_INP_MS || '200', 10);
const tbtMs = parseInt(process.env.LHCI_TBT_MS || '200', 10);
const perfScore = parseFloat(process.env.LHCI_PERFORMANCE_SCORE || '0.85');
const numberOfRuns = parseInt(process.env.LHCI_RUNS || '3', 10);

module.exports = {
  ci: {
    collect: {
      url: [url],
      numberOfRuns,
      settings: {
        preset: 'desktop', // switch to 'mobile' for mobile-first audits
        throttlingMethod: 'simulate',
      },
    },
    assert: {
      assertions: {
        // Aggregate performance score
        'categories:performance': ['error', { minScore: perfScore }],
        // Core Web Vitals
        'largest-contentful-paint': ['error', { maxNumericValue: lcpMs }],
        'cumulative-layout-shift': ['error', { maxNumericValue: cls }],
        // INP is not a native Lighthouse metric; Lighthouse reports TBT
        // and max-potential-FID as proxies. INP is measured live via
        // playwright-perf-template.ts or field RUM.
        'total-blocking-time': ['error', { maxNumericValue: tbtMs }],
        'max-potential-fid': ['warn', { maxNumericValue: inpMs * 1.5 }],
        // Common violations worth catching early
        'uses-responsive-images': 'warn',
        'unused-javascript': ['warn', { maxLength: 5 }],
        'render-blocking-resources': ['warn', { maxLength: 3 }],
      },
    },
    upload: {
      // Default to local temp public storage. Switch to 'lhci' with
      // serverBaseUrl in long-lived projects for trendlines.
      target: 'temporary-public-storage',
    },
  },
};
