// skeleton_extractor.mjs — HTML mockup → draft design-skeleton.v1 JSON
//
// Runtime: node + puppeteer-core. Invoked by skills/skeleton-extractor/scripts/extract.py
// which reads our single JSON blob on stdout and persists the draft YAML via
// trusted_runner.atomic_write_bytes (CB3: trusted runner owns file writes,
// subprocess only generates output).
//
// Design refs:
//   docs/plans/2026-04-23-ecosystem-keystone-design.md §2.3 per-screen schema
//   docs/plans/2026-04-23-ecosystem-keystone-design.md §2.4 8-step algorithm
//   docs/plans/2026-04-23-ecosystem-keystone-design.md §2.10 edge cases
//
// Precedent: /path/to/projects/test_flow/test-driver.mjs
//   (puppeteer-core + /bin/google-chrome + fonts.ready + setViewport before goto)
//
// Protocol:
//   stdin  : JSON object { mockupHtml: "/abs/path/to/mockup.html",
//                          breakpoints: [420, 700, 1280],
//                          tokens: { color: {...}, typography: {...}, ... } }
//   stdout : ONE JSON blob conforming to design-skeleton.v1 draft shape
//   stderr : diagnostics only (no structured output)
//
// The subprocess NEVER writes files. Python wrapper owns persistence.
//
// puppeteer-core resolution: ESM's native resolver does NOT honor NODE_PATH
// the way CommonJS does. We support three ways to locate puppeteer-core, in
// order of precedence:
//   1. SKELETON_EXTRACTOR_PUPPETEER_PATH env var — absolute path to the
//      puppeteer-core package directory (passed by the Python wrapper when
//      running under trusted_runner).
//   2. Standard ESM resolution — will succeed if puppeteer-core is in any
//      node_modules dir walked from this file upward.
//   3. CommonJS fallback via createRequire — honors NODE_PATH, so the legacy
//      `NODE_PATH=/.../node_modules` invocation still works.

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

async function loadPuppeteer() {
  const explicit = process.env.SKELETON_EXTRACTOR_PUPPETEER_PATH;
  if (explicit) {
    // Absolute path; import the package entry directly.
    const pkgJsonPath = path.join(explicit, "package.json");
    const pkgJson = JSON.parse(fs.readFileSync(pkgJsonPath, "utf8"));
    const entry = pkgJson.module || pkgJson.main || "index.js";
    const mod = await import(path.join(explicit, entry));
    return mod.default || mod;
  }
  try {
    const mod = await import("puppeteer-core");
    return mod.default || mod;
  } catch (_e1) {
    // CJS fallback — honors NODE_PATH and classic module lookup.
    const require = createRequire(import.meta.url);
    return require("puppeteer-core");
  }
}

const puppeteer = await loadPuppeteer();

// --- read stdin as a single JSON blob ---------------------------------------
async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  if (!raw) throw new Error("empty stdin; expected JSON payload");
  return JSON.parse(raw);
}

// --- CSS value normalization (color/length) ---------------------------------
// Convert rgb(r,g,b) / rgba(r,g,b,a) to lowercase #rrggbb where possible.
function rgbToHex(value) {
  if (typeof value !== "string") return value;
  const m = value.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)$/);
  if (!m) return value;
  const r = parseInt(m[1], 10);
  const g = parseInt(m[2], 10);
  const b = parseInt(m[3], 10);
  const hex = (n) => n.toString(16).padStart(2, "0");
  return `#${hex(r)}${hex(g)}${hex(b)}`;
}

// --- token back-resolution --------------------------------------------------
// Flatten declared tokens into { "#rrggbb" : "colors.accent_sun", ... }.
// Tokens from index.yaml schema: { color: {name: "#hex", ...}, typography, spacing, border, shadow }
function buildTokenIndex(tokens) {
  const index = new Map();
  if (!tokens || typeof tokens !== "object") return index;
  const ns = (path, value) => {
    if (value === null || value === undefined) return;
    if (typeof value === "string") {
      // color or shadow string — store by lowercased value
      const norm = value.toString().toLowerCase();
      // also index rgb() form for color
      index.set(norm, path);
      const asHex = rgbToHex(norm);
      if (asHex !== norm) index.set(asHex.toLowerCase(), path);
    } else if (typeof value === "number") {
      index.set(String(value), path);
    } else if (typeof value === "object") {
      for (const [k, v] of Object.entries(value)) {
        // path like "colors.accent.sun" or "typography.display.family"
        ns(`${path}.${k}`, v);
      }
    }
  };
  for (const [k, v] of Object.entries(tokens)) ns(k, v);
  return index;
}

function resolveToken(raw, tokenIndex) {
  if (raw === null || raw === undefined) return null;
  const s = typeof raw === "string" ? raw.trim().toLowerCase() : String(raw);
  if (tokenIndex.has(s)) return `token://${tokenIndex.get(s)}`;
  const asHex = rgbToHex(s).toLowerCase();
  if (tokenIndex.has(asHex)) return `token://${tokenIndex.get(asHex)}`;
  return null;
}

// --- main extraction --------------------------------------------------------
async function extract(payload) {
  const { mockupHtml, breakpoints, tokens } = payload;
  if (!mockupHtml || !fs.existsSync(mockupHtml)) {
    throw new Error(`mockupHtml not found: ${mockupHtml}`);
  }
  const bps = Array.isArray(breakpoints) && breakpoints.length ? breakpoints : [420, 700, 1280];
  const tokenIndex = buildTokenIndex(tokens || {});

  const fileUrl = "file://" + mockupHtml;
  const browser = await puppeteer.launch({
    executablePath: "/bin/google-chrome",
    headless: "new",
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    defaultViewport: { width: bps[0], height: 900 },
  });

  // Per-element accumulator keyed by stable selector. Value: {selector, role, bboxPerBp, tokensRawPerBp, interactions, slotGuesses}
  const byKey = new Map();
  const unresolvedTokens = [];
  const concerns = [];
  let maxFontsReadyMs = 0;
  let fontsLoaded = true;

  for (const width of bps) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: 900 });  // §2.10 viewport-unit guard
    await page.goto(fileUrl, { waitUntil: "networkidle0", timeout: 30000 });

    // §2.10 font-race guard: fonts.ready + 300ms settle, timed.
    const t0 = Date.now();
    try {
      await page.evaluate(() => document.fonts.ready);
    } catch (_e) {
      fontsLoaded = false;
    }
    const fontsMs = Date.now() - t0;
    if (fontsMs > maxFontsReadyMs) maxFontsReadyMs = fontsMs;
    if (fontsMs > 5000) {
      fontsLoaded = false;
      concerns.push({ severity: "blocker", detail: `fonts.ready took ${fontsMs}ms (>5s failure threshold)` });
    } else if (fontsMs > 2000) {
      concerns.push({ severity: "warning", detail: `fonts.ready took ${fontsMs}ms (>2s warn threshold)` });
    }
    await new Promise((r) => setTimeout(r, 300));

    // DOM walk. We run in-page to emit a flat list of elements with
    // selector/role/bbox/tokens_raw/interactions. Shadow DOM: open roots
    // recursed; closed roots marked shadow_dom_opaque.
    const elements = await page.evaluate(() => {
      const out = [];
      const seen = new WeakSet();

      function stableSelector(el) {
        // Prefer explicit id, then data-test-id, then tag#id>childpath.
        if (el.id) return `#${el.id}`;
        const test = el.getAttribute && el.getAttribute("data-test-id");
        if (test) return `[data-test-id="${test}"]`;
        const parts = [];
        let cur = el;
        while (cur && cur.nodeType === 1 && parts.length < 6) {
          let part = cur.tagName.toLowerCase();
          if (cur.id) { part = `${part}#${cur.id}`; parts.unshift(part); break; }
          if (cur.classList && cur.classList.length) {
            part += "." + Array.from(cur.classList).slice(0, 2).join(".");
          }
          const parent = cur.parentElement;
          if (parent) {
            const sameTag = Array.from(parent.children).filter((s) => s.tagName === cur.tagName);
            if (sameTag.length > 1) {
              const idx = sameTag.indexOf(cur) + 1;
              part += `:nth-of-type(${idx})`;
            }
          }
          parts.unshift(part);
          cur = cur.parentElement;
        }
        return parts.join(" > ") || "(unknown)";
      }

      function isVisible(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return false;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") return false;
        return true;
      }

      function hasSignal(el) {
        if (el.hasAttribute("role")) return true;
        const tag = el.tagName;
        if (tag === "BUTTON" || tag === "A" || tag === "FORM" || tag === "INPUT" ||
            tag === "SELECT" || tag === "TEXTAREA" || tag === "HEADER" ||
            tag === "MAIN" || tag === "NAV" || tag === "SECTION" || tag === "ARTICLE" ||
            tag === "FOOTER") return true;
        if (el.attributes) {
          for (const a of el.attributes) {
            if (a.name.startsWith("data-") && a.name !== "data-test-id") return true;
            if (a.name.startsWith("on")) return true;
          }
        }
        return false;
      }

      function interactionsOf(el) {
        const ints = [];
        const tag = el.tagName;
        if (tag === "BUTTON" || tag === "A") ints.push({ event: "click", binds_to: null });
        if (tag === "FORM") ints.push({ event: "submit", binds_to: null });
        if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
          ints.push({ event: "change", binds_to: null });
        }
        if (el.attributes) {
          for (const a of el.attributes) {
            if (a.name.startsWith("on") && a.name.length > 2) {
              const ev = a.name.slice(2);
              if (!ints.find((x) => x.event === ev)) ints.push({ event: ev, binds_to: null });
            }
          }
        }
        return ints;
      }

      function tokensRawOf(el) {
        const cs = getComputedStyle(el);
        return {
          color: cs.color || null,
          background_color: cs.backgroundColor || null,
          border_color: cs.borderTopColor || null,
          border_width_px: cs.borderTopWidth || null,
          font_family: cs.fontFamily || null,
          font_weight: cs.fontWeight || null,
          font_size_px: cs.fontSize || null,
          box_shadow: cs.boxShadow || null,
          padding_top_px: cs.paddingTop || null,
          margin_top_px: cs.marginTop || null,
        };
      }

      function walk(root, intoShadow) {
        const nodes = root.querySelectorAll ? root.querySelectorAll("*") : [];
        for (const el of nodes) {
          if (seen.has(el)) continue;
          seen.add(el);
          if (!isVisible(el)) continue;
          if (!hasSignal(el)) continue;
          const r = el.getBoundingClientRect();
          const bbox = {
            x: Math.round(r.left),
            y: Math.round(r.top),
            w: Math.round(r.width),
            h: Math.round(r.height),
          };
          out.push({
            selector: stableSelector(el),
            role: el.getAttribute("role") || el.tagName.toLowerCase(),
            bbox,
            tokens_raw: tokensRawOf(el),
            interactions: interactionsOf(el),
            shadow_dom_opaque: false,
          });
          // Recurse into shadow roots. Open roots only — closed ones throw.
          if (el.shadowRoot) {
            walk(el.shadowRoot, true);
          } else if (el.attachShadow && el.shadowRoot === null) {
            // Closed shadow root is undetectable from outside; only present if
            // author opted out. We leave a marker on the host element.
            out[out.length - 1].shadow_dom_opaque = true;
          }
        }
      }

      walk(document, false);
      return out;
    });

    // Merge per-bp into byKey, resolving tokens.
    for (const el of elements) {
      const key = el.selector;
      let rec = byKey.get(key);
      if (!rec) {
        rec = {
          selector: key,
          role: el.role,
          bbox: {},
          tokens_used: {},
          tokens_raw_per_bp: {},
          interactions: el.interactions,
          shadow_dom_opaque: el.shadow_dom_opaque,
        };
        byKey.set(key, rec);
      }
      // name breakpoints using the conventional mobile/tablet/desktop mapping
      const bpName = width <= 500 ? "mobile" : (width <= 900 ? "tablet" : "desktop");
      rec.bbox[bpName] = el.bbox;
      rec.tokens_raw_per_bp[bpName] = el.tokens_raw;
      // Resolve tokens using the desktop view as canonical (biggest viewport).
      for (const [field, raw] of Object.entries(el.tokens_raw || {})) {
        if (raw === null || raw === undefined || raw === "") continue;
        const resolved = resolveToken(raw, tokenIndex);
        if (resolved) {
          rec.tokens_used[field] = resolved;
        } else {
          // Only flag as unresolved when it looks like a content-bearing value
          // (non-empty, not a keyword like 'normal'/'auto'/'none' or 0px).
          const s = String(raw).toLowerCase().trim();
          if (s === "normal" || s === "auto" || s === "none" || s === "0px" || s === "rgba(0, 0, 0, 0)") continue;
          // Looks like a hardcoded color/shadow/font — record as unresolved.
          const looksMeaningful = /^(#|rgb|hsl)/.test(s) || /px$/.test(s) || /[a-z]/.test(s);
          if (looksMeaningful) {
            unresolvedTokens.push({
              selector: key,
              field,
              computed: String(raw),
              breakpoint: bpName,
            });
          }
        }
      }
    }

    await page.close();
  }

  await browser.close();

  // Compose draft design-skeleton.v1 shape (§2.3).
  const elementsOut = [];
  for (const [, rec] of byKey) {
    elementsOut.push({
      id: rec.selector.replace(/[^a-zA-Z0-9_]/g, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "el",
      selector: rec.selector,
      role: rec.role,
      kind: "element",
      bbox: rec.bbox,
      tokens_used: rec.tokens_used,
      tokens_raw_per_bp: rec.tokens_raw_per_bp,
      interactions: rec.interactions,
      shadow_dom_opaque: rec.shadow_dom_opaque || false,
    });
  }

  return {
    schema: "design-skeleton.v1",
    draft: true,
    generated_by: "skeleton-extractor@1.0.0",
    generated_at: new Date().toISOString(),
    breakpoints: bps,
    fonts_loaded: fontsLoaded,
    fonts_ready_max_ms: maxFontsReadyMs,
    elements: elementsOut,
    unresolved_tokens_report: unresolvedTokens,
    concerns: concerns,
  };
}

// --- main wiring ------------------------------------------------------------
try {
  const payload = await readStdinJson();
  const draft = await extract(payload);
  process.stdout.write(JSON.stringify(draft));
  process.exit(0);
} catch (err) {
  process.stderr.write(`[skeleton-extractor] ${err && err.stack ? err.stack : String(err)}\n`);
  process.exit(1);
}
