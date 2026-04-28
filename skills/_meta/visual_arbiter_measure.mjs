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
 *
 * Mutation handling (S030 #47):
 *   Per-element interaction dispatchEvent calls can mutate the live DOM
 *   (e.g. `<form onsubmit="renderSkeleton()">` wipes the grid; subsequent
 *   sibling lookups return found=false). The original implementation
 *   measured + dispatched + measured next, leaving N>=1 elements blind
 *   to mutations triggered by element N-1.
 *
 *   Fix: TWO-PHASE PER BREAKPOINT.
 *     Phase 1 — measure ALL element bboxes + computed styles in a SINGLE
 *               page.evaluate, before any dispatchEvent. Snapshot is now
 *               immune to handler-induced DOM mutation.
 *     Phase 2 — for each element with non-visual_only interactions,
 *               dispatch events with capture-phase preventDefault +
 *               stopImmediatePropagation defense-in-depth, then read
 *               handler-detection heuristics (inline on*, data-arbiter-wired,
 *               opt-in __arbiter_handler_ran flag). Heuristics deliberately
 *               do NOT depend on post-state DOM, so suppressing default
 *               doesn't mask real failures.
 *
 *   Output contract (CONTRACT-A1) unchanged: same field names, same shape,
 *   same null/false semantics for not-found / hidden cases.
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

    // ─── PHASE 1: snapshot ALL bboxes/computed BEFORE any dispatchEvent ───
    // Runs in a single page.evaluate so all measurements come from the same
    // pre-mutation DOM state. Hidden-at-breakpoint elements (declaredBbox===null)
    // are still skipped, but the decision is now made inside the snapshot
    // closure and recorded in lockstep with measured elements.
    const elementSpecs = (input.elements || []).map((el) => ({
      id: el.id,
      selector: el.selector,
      hidden_at_bp:
        el.bbox && el.bbox[bpName] !== undefined && el.bbox[bpName] === null,
    }));

    const snapshots = await page.evaluate((specs) => {
      const out = [];
      const props = [
        "color", "background-color", "background",
        "border-color", "border-top-color",
        "border-top-width", "border-top-style",
        "font-family", "font-weight", "font-size",
        "box-shadow", "padding", "margin", "gap",
        "display", "visibility", "opacity",
      ];
      for (const spec of specs) {
        if (spec.hidden_at_bp) {
          out.push({ id: spec.id, kind: "hidden" });
          continue;
        }
        const node = document.querySelector(spec.selector);
        if (!node) {
          out.push({ id: spec.id, kind: "not_found" });
          continue;
        }
        const rect = node.getBoundingClientRect();
        const cs = window.getComputedStyle(node);
        const computed = {};
        for (const p of props) computed[p] = cs.getPropertyValue(p);
        computed["__inline_style__"] = node.getAttribute("style") || "";
        computed["__outer_html__"] = node.outerHTML.slice(0, 4096);
        out.push({
          id: spec.id,
          kind: "found",
          bbox: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
          computed,
        });
      }
      return out;
    }, elementSpecs);

    // Build snapshot lookup keyed by element id.
    const snapshotById = new Map();
    for (const s of snapshots) snapshotById.set(s.id, s);

    // ─── PHASE 2: dispatch events + handler-detection heuristics ───
    // Phase-1 snapshot is already immutable JS data — even if a handler
    // wipes the live DOM here, output for sibling elements is unaffected.
    // Defense-in-depth: capture-phase preventDefault + stopImmediatePropagation
    // suppresses default actions (form submission, navigation) without masking
    // the heuristics, which read inline on*, data-arbiter-wired, and the
    // opt-in __arbiter_handler_ran flag — none of which depend on post-state
    // DOM survival.
    const results = [];
    for (const el of input.elements || []) {
      const snap = snapshotById.get(el.id);
      if (!snap) {
        // Defensive: spec went missing from snapshot (shouldn't happen).
        results.push({
          element_id: el.id,
          found: false,
          bbox: null,
          computed: {},
          interactions: [],
        });
        continue;
      }
      if (snap.kind === "hidden") {
        results.push({
          element_id: el.id,
          found: null,
          bbox: null,
          computed: {},
          interactions: [],
        });
        continue;
      }
      if (snap.kind === "not_found") {
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
              // Heuristic 1: inline on* attribute (read BEFORE dispatch so
              // even a handler that removes the node from the DOM is
              // detectable).
              const onAttr = el.getAttributeNames().some(
                (n) => n.startsWith("on") && (el.getAttribute(n) || "").trim().length > 0,
              );
              // Heuristic 2: explicit opt-in data attribute (also read
              // pre-dispatch).
              const wiredAttr = el.dataset.arbiterWired === "true";
              // Track if any listener runs — the handler itself must set
              // this flag (implementations conforming to skeleton contract).
              el.__arbiter_handler_ran = false;
              // Defense-in-depth: capture-phase listener that suppresses
              // default and stops immediate propagation. Does NOT prevent
              // user-installed listeners on the element itself from running
              // (those are bubble-phase or capture-phase on ancestors), so
              // heuristic 3 still fires when a real handler is wired.
              const guard = (ev) => {
                ev.preventDefault();
                ev.stopImmediatePropagation();
              };
              document.addEventListener(mapped, guard, { capture: true, once: true });
              try {
                const origDispatch = el.dispatchEvent.bind(el);
                const ev = new Event(mapped, { bubbles: true, cancelable: true });
                origDispatch(ev);
              } finally {
                document.removeEventListener(mapped, guard, { capture: true });
              }
              // Heuristic 3: handler set the flag (read AFTER dispatch — but
              // safe because we only need the boolean, not the surrounding DOM).
              const ranFlag = !!el.__arbiter_handler_ran;
              return !!(onAttr || wiredAttr || ranFlag);
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
        bbox: snap.bbox,
        computed: snap.computed,
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
