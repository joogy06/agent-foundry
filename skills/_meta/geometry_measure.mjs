#!/usr/bin/env node
/**
 * geometry_measure.mjs — S073. Puppeteer transport for dom_geometry_probe.js.
 *
 * Reads one JSON object on stdin, writes one JSON object on stdout.
 *
 *   {
 *     "product_url":  "https://…",            // required
 *     "chrome_path":  "/bin/google-chrome",   // optional
 *     "breakpoints":  {"mobile":{"width":390,"height":844}, …},   // required
 *     "specs":        [{"id":"price","selector":".price","cardinality":"many"}],
 *     "discover":     {"root":"#cart","min_members":2},           // optional
 *     "settle_ms":    300,
 *     "stability":    {"max_samples":5, "interval_ms":150},
 *     "allow_no_sandbox": false               // opt-in ONLY, see below
 *   }
 *
 * EXIT CODES — deliberately stricter than the older measure.mjs:
 *   0  every breakpoint measured, zero errors, geometry stable
 *   2  ANY failure, including a PARTIAL run
 *
 * The partial-run case is the point. visual_arbiter_measure.mjs collects per-breakpoint
 * failures into `errors[]` and then unconditionally exits 0, so a consumer checking the
 * exit code reads a half-completed run as success. A measurement that did not fully
 * happen must never be exit-code-indistinguishable from one that did.
 *
 * SANDBOX: Chrome runs sandboxed by default. `--no-sandbox` against an untrusted page is
 * a real weakening and is opt-in via `allow_no_sandbox`, which also stamps
 * `sandbox_disabled: true` into the output so the evidence records it. Verified on this
 * host (non-root): Chrome launches fine WITHOUT the flag.
 *
 * STABILITY: rather than trusting a fixed delay, geometry is sampled repeatedly until two
 * consecutive samples agree. Images, hydration, late CSS and payment widgets all move the
 * page after domcontentloaded; measuring an intermediate state yields a clean reading of a
 * layout the user never sees. Never-stabilising is reported as INCONCLUSIVE, not passed.
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));

async function loadPuppeteer() {
  const candidates = [
    join(process.env.HOME || "", ".claude/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js"),
    "/usr/local/lib/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js",
  ];
  for (const p of candidates) {
    try { const m = await import(p); return m.default || m; } catch { /* next */ }
  }
  const m = await import("puppeteer-core");
  return m.default || m;
}

function readStdinJson() {
  const raw = readFileSync(0, "utf8");
  if (!raw.trim()) throw new Error("empty stdin");
  return JSON.parse(raw);
}

/** Hash only geometry, so unrelated churn (text, attributes) does not defeat stability. */
function geometryFingerprint(result) {
  const parts = (result.elements || []).map(
    (e) => `${e.element_id}|${e.bbox ? `${e.bbox.x},${e.bbox.y},${e.bbox.w},${e.bbox.h}` : "null"}`
  );
  return createHash("sha256").update(parts.join(";")).digest("hex");
}

async function measureBreakpoint(browser, input, probeBody, bpName, bp) {
  const page = await browser.newPage();
  try {
    await page.setViewport({
      width: bp.width, height: bp.height,
      deviceScaleFactor: bp.device_pixel_ratio || 1,
    });
    await page.goto(input.product_url, { waitUntil: "domcontentloaded" });
    await page.evaluate(() => (document.fonts && document.fonts.ready) ? document.fonts.ready : null)
      .catch(() => null);
    await new Promise((r) => setTimeout(r, input.settle_ms ?? 300));

    const probeInput = {
      specs: input.specs || [],
      discover: input.discover || null,
      props: input.props || null,
      probe_version: input.probe_version,
    };

    const maxSamples = input.stability?.max_samples ?? 5;
    const intervalMs = input.stability?.interval_ms ?? 150;

    let prev = null, result = null, stable = false, samples = 0;
    for (let i = 0; i < maxSamples; i++) {
      result = await page.evaluate(probeBody, probeInput);
      samples++;
      const fp = geometryFingerprint(result);
      if (prev !== null && fp === prev) { stable = true; break; }
      prev = fp;
      if (i < maxSamples - 1) await new Promise((r) => setTimeout(r, intervalMs));
    }

    return { breakpoint: bpName, stable, samples, ...result };
  } catch (e) {
    return { breakpoint: bpName, stable: false, samples: 0, error: String(e && e.message || e),
             elements: [], groups: [], errors: [String(e && e.message || e)] };
  } finally {
    await page.close().catch(() => {});
  }
}

async function main() {
  let input;
  try { input = readStdinJson(); }
  catch (e) { process.stderr.write(`geometry_measure: bad input: ${e.message}\n`); return 2; }

  if (!input.product_url) { process.stderr.write("geometry_measure: product_url required\n"); return 2; }
  if (!input.breakpoints || !Object.keys(input.breakpoints).length) {
    process.stderr.write("geometry_measure: at least one breakpoint required\n"); return 2;
  }

  const probe = await import(join(HERE, "dom_geometry_probe.js"));
  input.probe_version = probe.PROBE_VERSION;
  if (!input.props) input.props = probe.DEFAULT_PROPS;

  const args = ["--disable-dev-shm-usage", "--hide-scrollbars"];
  if (input.allow_no_sandbox) args.push("--no-sandbox", "--disable-setuid-sandbox");

  let puppeteer, browser;
  try {
    puppeteer = await loadPuppeteer();
    browser = await puppeteer.launch({
      executablePath: input.chrome_path || "/bin/google-chrome",
      headless: "shell",
      args,
    });
  } catch (e) {
    process.stderr.write(`geometry_measure: chrome launch failed: ${e.message}\n`);
    return 2;
  }

  const measurements = {};
  const errors = [];
  try {
    for (const [name, bp] of Object.entries(input.breakpoints)) {
      const r = await measureBreakpoint(browser, input, probe.probeBody, name, bp);
      measurements[name] = r;
      if (r.error) errors.push(`${name}: ${r.error}`);
      for (const e of r.errors || []) errors.push(`${name}: ${e}`);
      if (!r.stable) errors.push(`${name}: geometry did not stabilise after ${r.samples} sample(s)`);
    }
  } finally {
    await browser.close().catch(() => {});
  }

  const expected = Object.keys(input.breakpoints).length;
  const complete = Object.keys(measurements).length === expected;
  const ok = complete && errors.length === 0;

  process.stdout.write(JSON.stringify({
    probe_version: probe.PROBE_VERSION,
    probe_hash: createHash("sha256")
      .update(readFileSync(join(HERE, "dom_geometry_probe.js")))
      .digest("hex"),
    product_url: input.product_url,
    sandbox_disabled: Boolean(input.allow_no_sandbox),
    breakpoints_expected: expected,
    breakpoints_measured: Object.keys(measurements).length,
    outcome: ok ? "MEASURED" : (complete ? "INCONCLUSIVE" : "PARTIAL"),
    measurements,
    errors,
  }) + "\n");

  return ok ? 0 : 2;
}

// Set exitCode and let node exit naturally once the event loop drains. process.exit()
// does NOT wait for a pipe to flush, so any payload larger than the 64KB pipe buffer is
// silently TRUNCATED mid-JSON — which a consumer sees as a parse error, or worse, as
// partial data. Small fixtures never hit it; the adversarial corpus did, at exactly
// 65536 bytes.
main().then((rc) => { process.exitCode = rc; }).catch((e) => {
  process.stderr.write(`geometry_measure: fatal: ${e && e.stack || e}\n`);
  process.exitCode = 2;
});
