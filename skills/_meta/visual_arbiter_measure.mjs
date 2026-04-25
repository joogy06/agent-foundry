#!/usr/bin/env node
/**
 * visual_arbiter_measure.mjs — mechanical DOM measurement driver for
 * visual_arbiter_spawn.py (ecosystem-keystone §2.6).
 *
 * Pure-Python decision path invariant: this script ONLY measures DOM state.
 * All pass/fail decisions are made in Python. No interpretation here.
 *
 * Invocation (stdin JSON, stdout JSON):
 *
 *   node visual_arbiter_measure.mjs
 *
 *   stdin = {
 *     "product_url":   "file:///.../index.html" | "http://...",
 *     "breakpoints":   {mobile: {width, height}, tablet: {...}, desktop: {...}},
 *     "elements":      [{id, selector, bbox: {<bp>: {x,y,w,h}|null},
 *                       tokens_used, interactions}],
 *     "settle_ms":     300,
 *     "chrome_path":   "/bin/google-chrome" (optional)
 *   }
 *
 *   stdout = {
 *     "measurements": {
 *       "<bp_name>": {
 *         "fonts_ready_ms":   <number>,                 // wait time for fonts.ready
 *         "elements": [{
 *           "element_id": "...",
 *           "found":       true|false|null,
 *           "bbox":        {x,y,w,h} | null,
 *           "computed":    { <property>: <string> },
 *           "interactions":[{event, binds_to, handler_fired, error}]
 *         }]
 *       }
 *     },
 *     "errors": [<string>]   // chrome/page errors
 *   }
 *
 * Exit 0 on success; exit 2 on unrecoverable chrome crash.
 */

import { readFileSync } from "node:fs";

async function loadPuppeteer() {
  const candidates = [
    "/usr/local/lib/node_modules/chrome-devtools-mcp/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js",
    "/usr/local/lib/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js",
  ];
  for (const p of candidates) {
    try {
      const mod = await import(p);
      return mod.default || mod;
    } catch (_e) { /* try next */ }
  }
  try {
    const mod = await import("puppeteer-core");
    return mod.default || mod;
  } catch (e) {
    throw new Error(`puppeteer-core not importable: ${e.message}`);
  }
}

function readStdinJson() {
  const raw = readFileSync(0, "utf8");
  if (!raw.trim()) throw new Error("empty stdin");
  return JSON.parse(raw);
}

async function measureBreakpoint(browser, input, bpName, bpViewport) {
  const page = await browser.newPage();
  try {
    await page.setViewport({
      width: bpViewport.width,
      height: bpViewport.height,
      deviceScaleFactor: bpViewport.device_pixel_ratio || 1,
    });
    await page.goto(input.product_url, { waitUntil: "domcontentloaded" });

    const fontsStart = Date.now();
    await page.evaluate(() => {
      if (document.fonts && document.fonts.ready) return document.fonts.ready;
      return null;
    }).catch(() => null);
    const fontsReadyMs = Date.now() - fontsStart;
    await new Promise((r) => setTimeout(r, input.settle_ms || 300));

    const results = [];
    for (const el of input.elements || []) {
      const declaredBbox =
        el.bbox && el.bbox[bpName] !== undefined ? el.bbox[bpName] : undefined;
      if (declaredBbox === null) {
        // Element explicitly declared hidden at this breakpoint; skip measurement.
        results.push({
          element_id: el.id,
          found: null,
          bbox: null,
          computed: {},
          interactions: [],
        });
        continue;
      }

      const measurement = await page.evaluate((elSpec) => {
        const node = document.querySelector(elSpec.selector);
        if (!node) return { found: false };
        const rect = node.getBoundingClientRect();
        const cs = window.getComputedStyle(node);
        const computed = {};
        const props = [
          "color", "background-color", "background",
          "border-color", "border-top-color",
          "border-top-width", "border-top-style",
          "font-family", "font-weight", "font-size",
          "box-shadow", "padding", "margin", "gap",
          "display", "visibility", "opacity",
        ];
        for (const p of props) computed[p] = cs.getPropertyValue(p);
        computed["__inline_style__"] = node.getAttribute("style") || "";
        // Capture a snippet of outerHTML so Python can inspect var(--...)
        // indirections vs hardcoded hex/rgb.
        computed["__outer_html__"] = node.outerHTML.slice(0, 4096);
        return {
          found: true,
          bbox: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
          computed,
        };
      }, el);

      if (!measurement.found) {
        results.push({
          element_id: el.id,
          found: false,
          bbox: null,
          computed: {},
          interactions: [],
        });
        continue;
      }

      const interactions = [];
      for (const intx of el.interactions || []) {
        if (intx.visual_only) {
          interactions.push({
            event: intx.event,
            binds_to: intx.binds_to || null,
            handler_fired: null,
            error: null,
          });
          continue;
        }
        const event = intx.event || "click";
        const mapped =
          event === "click_dismiss" || event.startsWith("click")
            ? "click"
            : event;
        let handlerFired = false;
        let error = null;
        try {
          // Dispatch event, then check whether any real listener ran. We
          // detect by: (1) presence of on* inline attribute; (2) data
          // attribute `data-arbiter-wired="true"` (implementations can opt
          // in); (3) any real addEventListener call that sets a flag via
          // the handler body. Pure mechanical — no judgment.
          handlerFired = await page.evaluate(
            ({ selector, mapped }) => {
              const el = document.querySelector(selector);
              if (!el) return false;
              // Track if any listener runs — the handler itself must set
              // this flag (implementations conforming to skeleton contract).
              el.__arbiter_handler_ran = false;
              // Patch addEventListener detection: wrap listeners at test time
              const origDispatch = el.dispatchEvent.bind(el);
              const ev = new Event(mapped, { bubbles: true, cancelable: true });
              origDispatch(ev);
              // Heuristic 1: inline on* attribute
              const onAttr = el.getAttributeNames().some(
                (n) => n.startsWith("on") && (el.getAttribute(n) || "").trim().length > 0,
              );
              // Heuristic 2: explicit opt-in data attribute
              const wiredAttr = el.dataset.arbiterWired === "true";
              // Heuristic 3: handler set the flag
              return !!(onAttr || wiredAttr || el.__arbiter_handler_ran);
            },
            { selector: el.selector, mapped },
          );
        } catch (e) {
          error = String(e.message || e);
        }
        interactions.push({
          event: intx.event,
          binds_to: intx.binds_to || null,
          handler_fired: handlerFired,
          error,
        });
      }

      results.push({
        element_id: el.id,
        found: true,
        bbox: measurement.bbox,
        computed: measurement.computed,
        interactions,
      });
    }

    await page.close();
    return {
      breakpoint: bpName,
      fonts_ready_ms: fontsReadyMs,
      elements: results,
      error: null,
    };
  } catch (e) {
    try { await page.close(); } catch (_) { /* ignore */ }
    return {
      breakpoint: bpName,
      fonts_ready_ms: -1,
      elements: [],
      error: String(e.message || e),
    };
  }
}

async function main() {
  let input;
  try {
    input = readStdinJson();
  } catch (e) {
    process.stderr.write(`measure: stdin parse error: ${e.message}\n`);
    process.exit(2);
  }

  const puppeteer = await loadPuppeteer();
  const chromePath = input.chrome_path || "/bin/google-chrome";

  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: chromePath,
      headless: "shell",
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
      ],
    });
  } catch (e) {
    process.stderr.write(`measure: chrome launch failed: ${e.message}\n`);
    process.exit(2);
  }

  const measurements = {};
  const errors = [];
  try {
    for (const [bpName, bpViewport] of Object.entries(input.breakpoints || {})) {
      const r = await measureBreakpoint(browser, input, bpName, bpViewport);
      measurements[bpName] = r;
      if (r.error) errors.push(`${bpName}: ${r.error}`);
    }
  } finally {
    try { await browser.close(); } catch (_) { /* ignore */ }
  }

  process.stdout.write(JSON.stringify({ measurements, errors }) + "\n");
  process.exit(0);
}

main().catch((e) => {
  process.stderr.write(`measure: fatal: ${e.message}\n`);
  process.exit(2);
});
