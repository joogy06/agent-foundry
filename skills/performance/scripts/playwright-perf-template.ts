/**
 * playwright-perf-template.ts
 *
 * Playwright-based programmatic Core Web Vitals / INP / TTI measurement.
 * Parameterised so the caller supplies URLs and budgets via env or a JSON
 * contract snippet.
 *
 * Run with:
 *
 *     PERF_ENV=staging \
 *     TARGET_URL=https://staging.example.com/products \
 *     LCP_MS=2500 CLS=0.1 INP_MS=200 \
 *     npx playwright test playwright-perf-template.ts --reporter=json
 *
 * Uses Chromium only (CWV is Chrome-origin). Emits a JSON envelope consumable
 * by frontend-performance.md synthesis logic.
 *
 * See references/perf-test-contract-template.md for the contract shape and
 * references/test-reality-model.md for environment isolation rules.
 */

import { chromium, test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

const PERF_ENV = process.env.PERF_ENV || '';
const TARGET_URL = process.env.TARGET_URL || '';
const LCP_MS = parseInt(process.env.LCP_MS || '2500', 10);
const CLS_MAX = parseFloat(process.env.CLS || '0.1');
const INP_MS = parseInt(process.env.INP_MS || '200', 10);
const TTI_MS = parseInt(process.env.TTI_MS || '3500', 10);
const ITERATIONS = parseInt(process.env.ITERATIONS || '5', 10);
const OUTPUT = process.env.OUTPUT || 'frontend-perf-results.json';

if (!TARGET_URL) {
  throw new Error('playwright-perf-template: TARGET_URL env is required.');
}
if (!PERF_ENV) {
  throw new Error(
    'playwright-perf-template: PERF_ENV must be set. See test-reality-model.md § Environment isolation.',
  );
}
if (/prod|production/i.test(PERF_ENV)) {
  throw new Error(
    `playwright-perf-template: PERF_ENV looks like production (${PERF_ENV}). Refusing to run.`,
  );
}

type VitalSample = {
  iteration: number;
  lcp_ms: number | null;
  cls: number | null;
  inp_ms: number | null;
  tti_ms_estimate: number | null;
  nav_load_ms: number | null;
};

async function measureOnce(page: Page, url: string): Promise<VitalSample> {
  // Inject web-vitals lib via CDN before navigation so we can subscribe
  // to LCP/CLS/INP callbacks.
  await page.addInitScript(() => {
    (window as any).__vitals = { lcp: null, cls: 0, inp: null };
    const s = document.createElement('script');
    s.type = 'module';
    s.textContent = `
      import { onLCP, onCLS, onINP } from 'https://unpkg.com/web-vitals@4?module';
      onLCP(v => { window.__vitals.lcp = v.value; });
      onCLS(v => { window.__vitals.cls = v.value; });
      onINP(v => { window.__vitals.inp = v.value; });
    `;
    document.documentElement.appendChild(s);
  });

  const navStart = Date.now();
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60_000 });
  const navLoad = Date.now() - navStart;

  // Give LCP/CLS a moment to settle.
  await page.waitForTimeout(1500);

  // Synthesize an interaction so INP fires.
  await page.mouse.move(10, 10);
  await page.mouse.click(10, 10, { delay: 50 });
  await page.waitForTimeout(500);

  const vitals = (await page.evaluate(() => (window as any).__vitals)) as {
    lcp: number | null;
    cls: number | null;
    inp: number | null;
  };

  // Very rough TTI estimate: time to networkidle. Real TTI requires a trace
  // analyser; this is a budget-oriented proxy.
  return {
    iteration: 0,
    lcp_ms: vitals.lcp,
    cls: vitals.cls,
    inp_ms: vitals.inp,
    tti_ms_estimate: navLoad,
    nav_load_ms: navLoad,
  };
}

test('frontend perf budgets', async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  const samples: VitalSample[] = [];
  for (let i = 0; i < ITERATIONS; i++) {
    const sample = await measureOnce(page, TARGET_URL);
    sample.iteration = i + 1;
    samples.push(sample);
  }

  await browser.close();

  const pick = (arr: (number | null)[]) =>
    arr.filter((x): x is number => typeof x === 'number').sort((a, b) => a - b);
  const p75 = (vals: number[]) => (vals.length ? vals[Math.floor(vals.length * 0.75)] : null);

  const lcpVals = pick(samples.map(s => s.lcp_ms));
  const clsVals = pick(samples.map(s => s.cls));
  const inpVals = pick(samples.map(s => s.inp_ms));
  const ttiVals = pick(samples.map(s => s.tti_ms_estimate));

  const envelope = {
    test_metadata: {
      tool: 'playwright',
      target_url: TARGET_URL,
      perf_env: PERF_ENV,
      iterations: ITERATIONS,
    },
    budgets: { lcp_ms: LCP_MS, cls: CLS_MAX, inp_ms: INP_MS, tti_ms: TTI_MS },
    results_p75: {
      lcp_ms: p75(lcpVals),
      cls: p75(clsVals),
      inp_ms: p75(inpVals),
      tti_ms_estimate: p75(ttiVals),
    },
    samples,
  };

  fs.writeFileSync(OUTPUT, JSON.stringify(envelope, null, 2));

  const lcp75 = envelope.results_p75.lcp_ms;
  const cls75 = envelope.results_p75.cls;
  const inp75 = envelope.results_p75.inp_ms;

  if (lcp75 !== null) expect(lcp75).toBeLessThanOrEqual(LCP_MS);
  if (cls75 !== null) expect(cls75).toBeLessThanOrEqual(CLS_MAX);
  if (inp75 !== null) expect(inp75).toBeLessThanOrEqual(INP_MS);
});
