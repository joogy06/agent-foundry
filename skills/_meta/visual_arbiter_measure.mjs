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
    // The declared runtime lives at ~/.claude/node_modules (NOT under skills/, because
    // publish-config has no file-exclusion mechanism and anything under skills/ is staged
    // for the public repo). Node's bare-specifier walk only finds it from inside
    // ~/.claude, so the repo copy of this file cannot resolve it without an explicit
    // path — which is why this candidate is listed first.
    `${process.env.HOME || ""}/.claude/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js`,
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
        // S073: --no-sandbox was unconditional. Against an untrusted page under review
        // that is a real weakening, and it is not needed here — verified that Chrome
        // launches fine WITHOUT it as a non-root user. Now opt-in via
        // `allow_no_sandbox`, for hosts (root/container) that genuinely require it.
        ...(input.allow_no_sandbox ? ["--no-sandbox", "--disable-setuid-sandbox"] : []),
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

  // S074 (#218): state the completeness of THIS run in the payload, where a consumer can
  // map it deliberately. The exit code deliberately stays 0 — see the note below. A
  // breakpoint counts as measured only if it produced no error; `error: null` with an
  // empty element list is still a measurement, an errored breakpoint is not.
  const expected = Object.keys(input.breakpoints || {}).length;
  const measured = Object.values(measurements).filter((r) => !r.error).length;
  const outcome = measured === 0 && expected > 0
    ? "INCONCLUSIVE"
    : measured < expected
      ? "PARTIAL"
      : "MEASURED";

  process.stdout.write(JSON.stringify({
    measurements,
    errors,
    outcome,
    breakpoints_expected: expected,
    breakpoints_measured: measured,
  }) + "\n");
  // NOTE (S073): exit 0 here even when `errors` is non-empty, so a PARTIAL run is
  // exit-code-indistinguishable from a complete one. That is a real hole — a consumer
  // checking only the return code reads a half-finished measurement as success.
  //
  // It was briefly changed to `exit(errors.length ? 2 : 0)` and REVERTED deliberately.
  // Exit code is the wrong lever: visual_arbiter_spawn.py maps any non-zero to
  // AUDIT_UNAVAILABLE, which would flatten "chrome crashed" and "3 of 4 breakpoints
  // measured" into one outcome and lose the distinction that matters.
  //
  // The fix belongs at the CONSUMER. Corrected S074 after re-reading it: an earlier
  // version of this note said the consumer "ignores `errors` entirely" — it does not.
  // visual_arbiter_spawn.py:800-812 DOES read `errors[]` and emits an
  // `external_tool_fail` observation at severity=degraded — then deliberately
  // continues ("Non-fatal — we still build a verdict against whatever was measured")
  // and exits 0. So the degradation is recorded in TELEMETRY and never reaches the
  // VERDICT: a verdict built from 1 of 4 breakpoints is byte-indistinguishable, to
  // bob and to G_V, from one built on all 4. The information already exists and is
  // discarded at the boundary where it matters.
  //
  // So: emit an explicit outcome (MEASURED / PARTIAL / INCONCLUSIVE) in the payload
  // and have the consumer carry it INTO the verdict. geometry_measure.mjs already
  // emits exactly this shape. Tracked as a task — do NOT re-add the exit-code change
  // on its own.
  //
  // Cost note for whoever picks this up: visual_arbiter_spawn.py is hash-pinned by
  // identity_check.py across three trees, and visual-arbiter/SKILL.md declares it
  // part of the rubric source of truth ("both hashed") with a semver bump required
  // when a change affects verdict semantics. Adding a field to the verdict IS such a
  // change. This is not a local edit.
  //
  // Separately (S073): use process.exitCode rather than process.exit(). process.exit()
  // does NOT wait for a pipe to flush, so a payload larger than the 64KB pipe buffer is
  // silently TRUNCATED mid-JSON. Found in the sibling geometry transport, which cut off
  // at exactly 65536 bytes on a page with many elements — every real page is larger than
  // a test fixture. This preserves the exit code exactly; it only stops the data loss.
  process.exitCode = 0;
}

main().catch((e) => {
  process.stderr.write(`measure: fatal: ${e.message}\n`);
  process.exit(2);
});
