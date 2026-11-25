// capture_page.mjs — render one variant page offline and measure it (#352, studio-capture).
//
// Runtime: node + puppeteer-core, started by studio_capture.py, which checks the arguments,
// owns the timeout and the temporary Chrome profile, and turns this script's raw numbers
// into floor rows. Do not run it by hand against a page you do not trust: the wrapper is
// what keeps the output directory apart from the page.
//
// Protocol:
//   stdin  : one JSON object
//            { variant_dir, out_dir, profile_dir,          absolute paths, already checked
//              viewports: [{width, height}, …],
//              motion_times_ms: [0, 400, …],
//              settle_ms, page_timeout_ms,
//              chrome_path?,                               optional
//              watch_parent?,                              the wrapper sets it: see PARENT below
//              simulate_sandbox_failure? }                 tests only: take the no-sandbox path
//            The object is ONE line. With `watch_parent` the wrapper keeps stdin open after it.
//   stdout : ONE JSON object (see `main`); with `gap` set when the capture could not run
//   stderr : diagnostics, never read into the evidence
//   exit   : 0 the capture ran (the wrapper decides pass or fail), 3 a named gap, 1 a crash,
//            4 the parent went away and the capture was abandoned
//
// THE PAGE IS UNTRUSTED. It was written by an agent and what is measured here reaches a
// model, so:
//   * every request is intercepted; only a regular file inside the variant directory (after
//     resolving symlinks and `..`) is served, everything else is aborted and recorded;
//   * Chrome also gets a dead proxy, a resolver that resolves nothing and offline emulation,
//     so a request this script cannot see (a socket, a worker) still has nowhere to go;
//   * the probe runs in an isolated world (the page cannot replace the functions it uses)
//     and returns numbers and structural selectors only: tag names from a fixed list with
//     nth-of-type positions. No page text, no attribute value, no outerHTML;
//   * font family names are reported for the host's own fonts only. A font file the variant
//     brought carries a name its author chose, so those are counted, not named.
//
// PARENT: the browser must not outlive the wrapper, on any path. With `watch_parent` this script
// treats the end of its stdin, or a new parent process id, as the wrapper's death (a wrapper that
// was killed outright runs no handler of its own): it kills the browser and everything below it,
// removes the profile and exits 4. Chrome is started on a pipe, not a socket, so a Chrome whose
// node was killed outright loses the pipe and exits by itself.
//
// SANDBOX: Chrome's own sandbox is on. If it cannot start, the capture runs without it and
// SAYS SO (`sandbox.state: "off"` with the reason); the restrictions above are in force
// either way. A no-sandbox flag is never added without that record.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LAUNCH_MODULE = path.join(HERE, "..", "..", "_meta", "chrome_launch.mjs");
const PUPPETEER_ENV = ["STUDIO_CAPTURE_PUPPETEER_PATH", "CHROME_LAUNCH_PUPPETEER_PATH"];

const MAX_SECTIONS = 24;
const MAX_TILES_PER_SECTION = 8;
const MAX_TILES_PER_VIEWPORT = 40;
const MAX_REQUESTS_LISTED = 200;
const MAX_URL_LENGTH = 2000;
const MAX_FONT_NODES = 60;
const MAX_FRAMES = 40;

const CHROME_ARGS = [
  "--disable-dev-shm-usage",
  "--hide-scrollbars",
  "--force-color-profile=srgb",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-extensions",
  "--disable-sync",
  "--disable-background-networking",
  "--disable-component-update",
  // Nowhere to go: a proxy nothing listens on (loopback included), and a resolver with no answers.
  "--proxy-server=127.0.0.1:1",
  "--proxy-bypass-list=<-loopback>",
  "--host-resolver-rules=MAP * ~NOTFOUND",
  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * The payload: the first line of stdin (all of it when stdin ends with no newline). `onEnd` is
 * called when stdin ends AFTER the payload was read: the process that held it open is gone.
 */
function readStdinJson(onEnd) {
  return new Promise((resolve, reject) => {
    let raw = "";
    let taken = false;
    const take = (text) => {
      taken = true;
      try {
        if (!text.trim()) throw new Error("empty stdin; expected a JSON payload");
        resolve(JSON.parse(text));
      } catch (e) {
        reject(e);
      }
    };
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      if (taken) return;
      raw += chunk;
      const end = raw.indexOf("\n");
      if (end >= 0) take(raw.slice(0, end));
    });
    const ended = () => { if (taken) onEnd(); else take(raw); };
    process.stdin.on("end", ended);
    process.stdin.on("error", ended);
  });
}

// --- the browser dies with its parent -------------------------------------------------------

const watched = { on: false, browser: null, profile: null };

function processesBelow(pid) {
  const out = [];
  if (process.platform !== "linux") return out;
  const parents = new Map();
  let names = [];
  try { names = fs.readdirSync("/proc"); } catch (_e) { return out; }
  for (const name of names) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const stat = fs.readFileSync(`/proc/${name}/stat`, "utf8");
      parents.set(Number(name), Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]));
    } catch (_e) { /* the process ended */ }
  }
  const queue = [pid];
  while (queue.length) {
    const parent = queue.shift();
    for (const [child, ppid] of parents) if (ppid === parent) { out.push(child); queue.push(child); }
  }
  return out;
}

/** Kill the browser and every process below it. Puppeteer starts Chrome as the leader of its own group. */
function killBrowser() {
  const proc = watched.browser && watched.browser.process();
  if (!proc || !proc.pid) return;
  const pids = processesBelow(proc.pid);
  if (process.platform !== "win32") { try { process.kill(-proc.pid, "SIGKILL"); } catch (_e) { /* gone */ } }
  for (const pid of [proc.pid, ...pids]) { try { process.kill(pid, "SIGKILL"); } catch (_e) { /* gone */ } }
}

/** The wrapper is gone: nobody will read a result or reap the browser. End everything now. */
function abandon(why) {
  if (!watched.on) return;
  watched.on = false;
  try { process.stderr.write(`[capture_page] abandoned: ${why}\n`); } catch (_e) { /* no reader */ }
  try { killBrowser(); } catch (_e) { /* nothing to kill */ }
  // The profile is the wrapper's temporary directory; with the wrapper dead nobody else removes it.
  if (watched.profile && path.basename(watched.profile).startsWith("studio-capture-profile-")) {
    try { fs.rmSync(watched.profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }); } catch (_e) { /* left */ }
  }
  process.exit(4);
}

function watchParent(input) {
  watched.on = true;
  watched.profile = input.profile_dir;
  const parent = process.ppid;
  // A killed wrapper leaves this process to another parent (init, or a subreaper).
  setInterval(() => { if (process.ppid !== parent) abandon("the parent process changed"); }, 500).unref();
  for (const name of ["SIGTERM", "SIGHUP"]) process.on(name, () => abandon(`received ${name}`));
}

function emit(obj, code) {
  process.exitCode = code;
  // Exit once the blob is flushed: a handle Chrome left behind must not keep the wrapper waiting.
  process.stdout.write(JSON.stringify(obj), () => process.exit(code));
}

// --- which requests stay inside the variant directory -------------------------------------

function isInside(root, candidate) {
  const rel = path.relative(root, candidate);
  return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
}

/**
 * { kind: "inside", rel, abs }   a regular file inside the variant directory
 * { kind: "internal" }           data:, blob: and about: carry no address
 * { kind: "missing" }            a path inside the directory with nothing there
 * { kind: "outside" }            everything else, a symlink or `..` that leads out included
 */
function classify(url, rootReal) {
  if (/^(data|blob|about):/i.test(url)) return { kind: "internal" };
  if (!/^file:/i.test(url)) return { kind: "outside" };
  let abs;
  try {
    abs = fileURLToPath(url.split("#")[0].split("?")[0]);
  } catch (_e) {
    return { kind: "outside" };
  }
  let real;
  try {
    real = fs.realpathSync(abs);
  } catch (_e) {
    // Nothing there. It is harmless only if the path, with its existing part resolved,
    // would have been inside.
    let parent = path.dirname(abs);
    try { parent = fs.realpathSync(parent); } catch (_e2) { return { kind: "outside" }; }
    return isInside(rootReal, path.join(parent, path.basename(abs))) ? { kind: "missing" } : { kind: "outside" };
  }
  if (!isInside(rootReal, real)) return { kind: "outside" };
  let stat;
  try { stat = fs.statSync(real); } catch (_e) { return { kind: "missing" }; }
  if (!stat.isFile()) return { kind: "missing" };
  return { kind: "inside", rel: path.relative(rootReal, real).split(path.sep).join("/"), abs: real, size: stat.size };
}

class RequestLog {
  constructor(rootReal) {
    this.rootReal = rootReal;
    this.inside = new Map();   // rel -> size
    this.outside = [];
    this.truncated = false;
  }

  note(url) {
    const verdict = classify(url, this.rootReal);
    if (verdict.kind === "inside") this.inside.set(verdict.rel, verdict.size);
    if (verdict.kind === "outside") this.noteOutside(url);
    return verdict;
  }

  noteOutside(url) {
    const short = String(url).slice(0, MAX_URL_LENGTH);
    if (this.outside.includes(short)) return;
    if (this.outside.length >= MAX_REQUESTS_LISTED) { this.truncated = true; return; }
    this.outside.push(short);
  }
}

// --- one guarded page ------------------------------------------------------------------------

async function openPage(browser, log, viewport, reducedMotion) {
  const page = await browser.newPage();
  const loaded = new Map();   // rel -> size, for this page only (page weight)
  await page.setViewport({ width: viewport.width, height: viewport.height, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([
    { name: "prefers-reduced-motion", value: reducedMotion ? "reduce" : "no-preference" },
  ]);
  page.on("dialog", (dialog) => { dialog.dismiss().catch(() => {}); });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const verdict = log.note(request.url());
    if (verdict.kind === "inside") loaded.set(verdict.rel, verdict.size);
    if (verdict.kind === "inside" || verdict.kind === "internal") request.continue().catch(() => {});
    else request.abort("blockedbyclient").catch(() => {});
  });
  const cdp = await page.createCDPSession();
  await cdp.send("Network.enable");
  // A socket is not a request the interception sees. It cannot connect, but it was asked for.
  cdp.on("Network.webSocketCreated", (event) => log.noteOutside(event.url));
  cdp.on("Network.webTransportCreated", (event) => log.noteOutside(event.url));
  await page.setOfflineMode(true);
  return { page, cdp, loaded };
}

/**
 * Run `fn(arg)` in a fresh isolated world of a frame (the main frame unless `frameId` is given).
 * The page's own script cannot reach it.
 */
async function isolated(cdp, fn, arg, frameId) {
  let target = frameId;
  if (!target) {
    const { frameTree } = await cdp.send("Page.getFrameTree");
    target = frameTree.frame.id;
  }
  const { executionContextId } = await cdp.send("Page.createIsolatedWorld", {
    frameId: target,
    worldName: "studio-capture",
  });
  const reply = await cdp.send("Runtime.evaluate", {
    expression: `(${fn.toString()})(${JSON.stringify(arg === undefined ? null : arg)})`,
    contextId: executionContextId,
    returnByValue: true,
    awaitPromise: true,
  });
  if (reply.exceptionDetails) throw new Error("the in-page probe threw");
  return reply.result.value;
}

// --- in-page functions (serialised; they share nothing with this file) -----------------------

async function pageScrollThrough(stepMs) {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const step = Math.max(200, window.innerHeight);
  for (let y = 0, n = 0; n < 60; n += 1, y += step) {
    window.scrollTo(0, y);
    await wait(stepMs);
    if (y + window.innerHeight >= document.documentElement.scrollHeight) break;
  }
  window.scrollTo(0, 0);
  if (document.fonts && document.fonts.ready) await Promise.race([document.fonts.ready, wait(2000)]);
  return true;
}

async function pageScrollTo(y) {
  window.scrollTo(0, y);
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await new Promise((resolve) => setTimeout(resolve, 60));
  return Math.round(window.scrollY);
}

function pageProbe(cfg) {
  const TAGS = new Set(cfg.tags);

  // A structural selector: at most four steps of tag:nth-of-type(n). No id, no class, no text.
  function selectorOf(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 4) {
      const tag = TAGS.has(cur.localName) ? cur.localName : "x";
      if (tag === "html" || tag === "body") { parts.unshift(tag); break; }
      let index = 1;
      for (let sib = cur.previousElementSibling; sib; sib = sib.previousElementSibling) {
        if (sib.localName === cur.localName) index += 1;
      }
      parts.unshift(`${tag}:nth-of-type(${index})`);
      cur = cur.parentElement;   // stops at a shadow root: the selector is then inside that root
    }
    return parts.join(" > ") || "html";
  }

  // The element above `el` as a reader sees it: out of a shadow root to its host.
  function above(el) {
    if (el.parentElement) return el.parentElement;
    const root = el.getRootNode && el.getRootNode();
    return root && root.host ? root.host : null;
  }

  // Every tree of this document a reader sees: the document itself and each open shadow root in
  // it, nested ones included. A closed root cannot be read; text only there is text not measured.
  // Frames are documents of their own: the caller runs this probe in each of them.
  const scopes = [];
  let framesSeen = 0;
  (function collect(root, depth) {
    if (!root || scopes.length >= 500 || depth > 12) return;
    scopes.push(root);
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) collect(el.shadowRoot, depth + 1);
      const name = el.localName;
      if (name === "iframe" || name === "frame" || (name === "object" && el.contentWindow)) {
        const r = el.getBoundingClientRect();
        if (r.width > 1 && r.height > 1) framesSeen += 1;
      }
    }
  })(document.body || document.documentElement, 0);

  // --- colour ---------------------------------------------------------------------------
  const canvas = document.createElement("canvas");
  canvas.width = 1; canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const colourCache = new Map();
  function parseColour(value) {
    if (colourCache.has(value)) return colourCache.get(value);
    let out;
    const m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(value);
    if (m) {
      let alpha = m[4] === undefined ? 1 : parseFloat(m[4]);
      if (m[4] && m[4].endsWith("%")) alpha /= 100;
      out = [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), alpha];
    } else {
      // Any other syntax (oklch(), color(), a keyword): let the canvas resolve it.
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "rgba(0, 0, 0, 0)";
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const d = ctx.getImageData(0, 0, 1, 1).data;
      out = [d[0], d[1], d[2], d[3] / 255];
    }
    colourCache.set(value, out);
    return out;
  }
  const over = (top, under) => {
    const a = top[3];
    return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1];
  };
  const channel = (v) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
  const luminance = (c) => 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2]);
  function ratio(a, b) {
    const la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }
  const COLOUR_TOKEN = /(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\([^()]*\)|#[0-9a-fA-F]{3,8}\b/g;

  /**
   * The colours that can be behind `el`'s text: a list of opaque colours (several over a
   * gradient: one per stop), or null over a raster image, where it is not measured.
   */
  function backgroundsOf(el) {
    const layers = [];   // top first; each a list of [r, g, b, a]
    let cur = el;
    let closed = false;
    while (cur && cur.nodeType === 1 && !closed) {
      const cs = getComputedStyle(cur);
      const image = cs.backgroundImage;
      if (image && image !== "none") {
        if (/url\(/i.test(image)) return null;
        const stops = (image.match(COLOUR_TOKEN) || []).map(parseColour);
        if (!stops.length) return null;
        layers.push(stops);
        if (stops.every((s) => s[3] >= 0.999)) { closed = true; break; }
      }
      const colour = parseColour(cs.backgroundColor);
      if (colour[3] > 0) {
        layers.push([colour]);
        if (colour[3] >= 0.999) closed = true;
      }
      cur = above(cur);
    }
    let under = [[255, 255, 255, 1]];   // the canvas default
    for (let i = layers.length - 1; i >= 0; i -= 1) {
      const next = [];
      for (const top of layers[i]) for (const base of under) next.push(over(top, base));
      under = next.slice(0, 32);
    }
    return under;
  }

  function opacityOf(el) {
    let product = 1;
    for (let cur = el; cur && cur.nodeType === 1; cur = above(cur)) {
      product *= parseFloat(getComputedStyle(cur).opacity || "1");
    }
    return product;
  }

  // --- text elements ----------------------------------------------------------------------
  const SKIP = "script, style, noscript, template, svg, title, head, option, select, textarea";
  const seen = new Set();
  const textEls = [];
  const range = document.createRange();
  for (const scope of scopes) {
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node && textEls.length < 4000; node = walker.nextNode()) {
      if (!/\S/.test(node.nodeValue)) continue;
      const el = node.parentElement;
      if (!el || seen.has(el) || el.closest(SKIP)) continue;
      range.selectNodeContents(node);
      const rects = Array.from(range.getClientRects()).filter((r) => r.width > 1 && r.height > 1);
      if (!rects.length) continue;
      if (rects.every((r) => r.right < 0 || r.bottom + window.scrollY < 0)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility !== "visible") continue;
      seen.add(el);
      textEls.push({ el, cs });
    }
  }

  const text = { min: null, element: null, count: 0 };
  const large = { min: null, element: null, count: 0 };
  const unmeasured = { count: 0, element: null };
  for (const { el, cs } of textEls) {
    const opacity = opacityOf(el);
    if (opacity < 0.05) continue;
    const fill = parseColour(cs.webkitTextFillColor || cs.color);
    const clip = cs.backgroundClip || cs.webkitBackgroundClip || "";
    const backgrounds = /text/.test(clip) ? null : backgroundsOf(el);
    if (backgrounds === null) {
      unmeasured.count += 1;
      if (!unmeasured.element) unmeasured.element = selectorOf(el);
      continue;
    }
    const ink = [fill[0], fill[1], fill[2], fill[3] * opacity];
    let worst = Infinity;
    for (const bg of backgrounds) worst = Math.min(worst, ratio(over(ink, bg), bg));
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const bucket = (size >= cfg.large_px || (size >= cfg.large_bold_px && weight >= 700)) ? large : text;
    bucket.count += 1;
    if (bucket.min === null || worst < bucket.min) { bucket.min = worst; bucket.element = selectorOf(el); }
  }

  // --- running body text ------------------------------------------------------------------
  const root = document.querySelector("main") || document.querySelector("article") || document.body;
  const OUTSIDE_BODY = "nav, header, footer, aside, figure, figcaption, table, form, button, label, [hidden]";
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 1 && r.height > 1; };
  let paragraphs = [];
  if (root) {
    // The running text of the page: under main or article, and in every shadow root (a component
    // sets its prose there, and a query from the document does not reach it).
    const bodyScopes = [root].concat(scopes.slice(1));
    const within = (selector) => bodyScopes.flatMap((scope) => Array.from(scope.querySelectorAll(selector)));
    paragraphs = within("p").filter((p) => !p.closest(OUTSIDE_BODY) && visible(p) && /\S/.test(p.textContent));
    if (!paragraphs.length) {
      // A page that sets its prose in other elements: take those holding a run of text of their own.
      paragraphs = within("div, li, dd, span, article, section").filter((el) => {
        if (el.closest(OUTSIDE_BODY) || !visible(el)) return false;
        let own = 0;
        for (const child of el.childNodes) if (child.nodeType === 3) own += child.nodeValue.replace(/\s+/g, "").length;
        return own >= 80;
      });
    }
  }
  // A page with text and no paragraph-like run (headings, links, short list items): its body size is
  // the smallest text a reader meets outside the regions above, or, when every word is in one of
  // them, the smallest text there is. Only a page where no text element was reached stays unmeasured.
  let sized = paragraphs;
  if (!sized.length) {
    const reached = textEls.map((t) => t.el);
    const outside = reached.filter((el) => !el.closest(OUTSIDE_BODY));
    sized = outside.length ? outside : reached;
  }
  const bodyFromOtherText = !paragraphs.length && sized.length ? 1 : 0;
  // The size of a paragraph is the size of the text a reader sees in it, not of the element that
  // holds it: `<p style="font-size:16px"><span style="font-size:8px">...</span></p>` is 8 px text.
  // So each paragraph is measured on the visible text runs inside it, its own and its descendants'.
  // Its size is the smallest size that MORE than SMALL_SHARE of its characters are set in or under:
  // a paragraph fails the floor when over a fifth of what a reader reads in it is under the floor,
  // not for one small phrase, a footnote mark or a line of fine print inside it. The share is the
  // whole rule: no element is left out for its tag, so a paragraph set whole in `small` or `sub` is
  // measured like any other. A paragraph with no reached run keeps the size of its element.
  const SMALL_SHARE = 0.2;
  const ownChars = (el) => {
    let own = 0;
    for (const child of el.childNodes) if (child.nodeType === 3) own += child.nodeValue.replace(/\s+/g, "").length;
    return own;
  };
  const runs = paragraphs.length
    ? textEls.filter((t) => opacityOf(t.el) >= 0.05)
      .map((t) => ({ el: t.el, size: parseFloat(t.cs.fontSize), chars: ownChars(t.el) }))
    : [];
  const sizeOf = (el) => {
    const inside = runs.filter((r) => r.chars && (r.el === el || el.contains(r.el))).sort((a, b) => a.size - b.size);
    const total = inside.reduce((sum, r) => sum + r.chars, 0);
    let seen = 0;
    for (const r of inside) {
      seen += r.chars;
      if (seen > SMALL_SHARE * total) return { size: r.size, el: r.el };
    }
    return { size: parseFloat(getComputedStyle(el).fontSize), el };
  };
  const bodySize = { min: null, element: null, count: sized.length };
  for (const el of sized) {
    const found = sizeOf(el);
    if (bodySize.min === null || found.size < bodySize.min) { bodySize.min = found.size; bodySize.element = selectorOf(found.el); }
  }
  const lineLength = { max: null, element: null, count: 0 };
  for (const p of paragraphs) {
    const size = parseFloat(getComputedStyle(p).fontSize);
    range.selectNodeContents(p);
    const tops = Array.from(range.getClientRects()).filter((r) => r.width > 1).map((r) => r.top).sort((a, b) => a - b);
    let lines = 0, last = -Infinity;
    for (const top of tops) if (top - last > size * 0.5) { lines += 1; last = top; }
    if (lines < 3) continue;
    const mean = p.textContent.replace(/\s+/g, " ").trim().length / lines;
    lineLength.count += 1;
    if (lineLength.max === null || mean > lineLength.max) { lineLength.max = mean; lineLength.element = selectorOf(p); }
  }

  // --- overflow and motion ------------------------------------------------------------------
  const doc = document.documentElement;
  const overflowX = Math.max(0, doc.scrollWidth - doc.clientWidth);
  const running = document.getAnimations().filter((a) => a.playState === "running");
  const firstTarget = running.length && running[0].effect && running[0].effect.target;

  // --- sections, for the tiles --------------------------------------------------------------
  const blocks = [];
  const isBlock = (el) => !el.matches("script, style, noscript, template, link, meta") && el.getBoundingClientRect().height >= 1;
  for (const child of Array.from((document.body || doc).children)) {
    if (!isBlock(child)) continue;
    const inner = Array.from(child.children).filter(isBlock);
    const wrapper = child.localName === "main" ||
      (child.localName === "div" && inner.some((el) => ["section", "header", "footer", "article", "main"].includes(el.localName)));
    for (const el of (wrapper && inner.length ? inner : [child])) {
      const r = el.getBoundingClientRect();
      blocks.push({ top: Math.max(0, Math.round(r.top + window.scrollY)), bottom: Math.round(r.bottom + window.scrollY), element: selectorOf(el) });
    }
  }
  blocks.sort((a, b) => a.top - b.top);
  if (!blocks.length) blocks.push({ top: 0, bottom: doc.scrollHeight, element: "body" });

  const round = (v) => (v === null ? null : Math.round(v * 100) / 100);
  return {
    contrast_text: { min: round(text.min), element: text.element, count: text.count },
    contrast_large: { min: round(large.min), element: large.element, count: large.count },
    unmeasured,
    body_size: { min: round(bodySize.min), element: bodySize.element, count: bodySize.count },
    line_length: { max: round(lineLength.max), element: lineLength.element, count: lineLength.count },
    overflow_x: overflowX,
    running_animations: { count: running.length, element: firstTarget ? selectorOf(firstTarget) : null },
    text_elements: textEls.length,
    body_from_other_text: bodyFromOtherText,
    frames_seen: framesSeen,
    page_height: doc.scrollHeight,
    blocks,
  };
}

/**
 * One set of measurements from the probe's result in each frame of the page (the main frame
 * first). The worst value wins, with its element; counts add up. Layout facts (overflow, the
 * sections for the tiles) are the main frame's. `frames_probed` against `frames_seen` tells the
 * wrapper whether a frame a reader sees went unmeasured.
 */
function mergeMeasures(parts) {
  const main = parts[0];
  const worst = (key, field) => {
    const out = { [field]: null, element: null, count: 0 };
    for (const part of parts) {
      const got = part[key];
      out.count += got.count;
      if (got[field] === null) continue;
      if (out[field] === null || (field === "min" ? got[field] < out[field] : got[field] > out[field])) {
        out[field] = got[field];
        out.element = got.element;
      }
    }
    return out;
  };
  const total = (key) => ({
    count: parts.reduce((sum, part) => sum + part[key].count, 0),
    element: (parts.find((part) => part[key].element) || main)[key].element,
  });
  return {
    contrast_text: worst("contrast_text", "min"),
    contrast_large: worst("contrast_large", "min"),
    unmeasured: total("unmeasured"),
    body_size: worst("body_size", "min"),
    line_length: worst("line_length", "max"),
    overflow_x: main.overflow_x,
    running_animations: total("running_animations"),
    text_elements: parts.reduce((sum, part) => sum + part.text_elements, 0),
    body_from_other_text: parts.reduce((sum, part) => sum + part.body_from_other_text, 0),
    frames_seen: parts.reduce((sum, part) => sum + part.frames_seen, 0),
    frames_probed: parts.length - 1,
    page_height: main.page_height,
    blocks: main.blocks,
  };
}

const KNOWN_TAGS = ("html body main header footer nav section article aside div span p h1 h2 h3 h4 h5 h6 a ul ol li dl dt dd " +
  "figure figcaption blockquote pre code em strong small b i u s mark q cite abbr time sub sup br hr img picture video " +
  "audio canvas svg table thead tbody tfoot tr td th caption form label input button select textarea fieldset legend " +
  "details summary dialog address hgroup search").split(" ");

// --- closed shadow roots ---------------------------------------------------------------------

/**
 * How many closed shadow roots of the page hold text. The in-page probe cannot enter a closed root,
 * so that text is NOT measured; the protocol's own view of the tree shows that it is there. The
 * count is all that leaves here: it becomes an advisory row, so that a reader of the rows is told.
 */
async function closedRootsWithText(cdp) {
  await cdp.send("DOM.enable");
  const { root } = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
  const holdsText = (node) => {
    if (node.nodeType === 3) return /\S/.test(node.nodeValue || "");
    if (/^(style|script|template)$/.test(node.localName || "")) return false;
    return (node.children || []).some(holdsText) || (node.shadowRoots || []).some(holdsText);
  };
  let count = 0;
  (function walk(node, depth) {
    if (depth > 200) return;
    for (const shadow of node.shadowRoots || []) {
      if (shadow.shadowRootType === "closed" && holdsText(shadow)) count += 1;
      walk(shadow, depth + 1);
    }
    for (const child of node.children || []) walk(child, depth + 1);
    if (node.contentDocument) walk(node.contentDocument, depth + 1);
  })(root, 0);
  return count;
}

// --- fonts that rendered ---------------------------------------------------------------------

async function renderedFonts(cdp) {
  const host = new Map();
  const custom = new Set();
  let customGlyphs = 0;
  await cdp.send("DOM.enable");
  await cdp.send("CSS.enable");
  const { root } = await cdp.send("DOM.getDocument", { depth: 0 });
  const { nodeIds } = await cdp.send("DOM.querySelectorAll", {
    nodeId: root.nodeId,
    selector: "h1, h2, h3, h4, p, li, a, button, blockquote, figcaption, label, td, th",
  });
  for (const nodeId of nodeIds.slice(0, MAX_FONT_NODES)) {
    let fonts = [];
    try { ({ fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId })); } catch (_e) { continue; }
    for (const font of fonts) {
      if (font.isCustomFont) { custom.add(font.familyName); customGlyphs += font.glyphCount; }
      else host.set(font.familyName, (host.get(font.familyName) || 0) + font.glyphCount);
    }
  }
  return {
    fonts: Array.from(host, ([family, glyphs]) => ({ family, glyphs })).sort((a, b) => b.glyphs - a.glyphs).slice(0, 20),
    variant_fonts: { families: custom.size, glyphs: customGlyphs },
  };
}

// --- one viewport ------------------------------------------------------------------------------

async function captureViewport(browser, log, input, viewport, fileUrl, onFirstPage) {
  const result = { width: viewport.width, height: viewport.height, error: null, measures: null, weight_bytes: null,
                   tiles: [], tiles_truncated: false, fonts: [], variant_fonts: { families: 0, glyphs: 0 },
                   motion_frames: [], motion_error: null };
  const tag = `w${viewport.width}`;

  // 1. The judged baseline: reduced motion requested, scrolled through once, settled.
  let stage = "load-failed";
  const { page, cdp, loaded } = await openPage(browser, log, viewport, true);
  try {
    await page.goto(fileUrl, { waitUntil: "load", timeout: input.page_timeout_ms });
    if (onFirstPage) await onFirstPage();
    stage = "probe-failed";
    await isolated(cdp, pageScrollThrough, 90);
    await sleep(input.settle_ms);
    const probeConfig = { tags: KNOWN_TAGS, large_px: input.large_px, large_bold_px: input.large_bold_px };
    const parts = [await isolated(cdp, pageProbe, probeConfig)];
    // A frame is a document of its own, and a file: frame is another origin to its parent: the
    // probe runs in each one. A frame it cannot run in stays counted as seen and not measured.
    const { frameTree } = await cdp.send("Page.getFrameTree");
    const childFrames = [];
    (function flat(node) {
      for (const child of node.childFrames || []) { childFrames.push(child.frame.id); flat(child); }
    })(frameTree);
    for (const frameId of childFrames.slice(0, MAX_FRAMES)) {
      try {
        parts.push(await isolated(cdp, pageProbe, probeConfig, frameId));
      } catch (e) {
        process.stderr.write(`[capture_page] ${tag} frame not measured: ${String(e && e.message || e).slice(0, 200)}\n`);
      }
    }
    const measures = mergeMeasures(parts);
    const blocks = measures.blocks;
    delete measures.blocks;
    try {
      measures.closed_shadow_roots = await closedRootsWithText(cdp);
    } catch (e) {
      measures.closed_shadow_roots = 0;
      process.stderr.write(`[capture_page] ${tag} closed shadow roots not counted: ${String(e && e.message || e).slice(0, 200)}\n`);
    }
    result.measures = measures;
    Object.assign(result, await renderedFonts(cdp));

    stage = "tiles-failed";
    const dir = path.join(input.out_dir, "tiles", tag);
    fs.mkdirSync(dir, { recursive: true });
    if (blocks.length > MAX_SECTIONS) result.tiles_truncated = true;
    let total = 0;
    for (const [index, block] of blocks.slice(0, MAX_SECTIONS).entries()) {
      const wanted = Math.max(1, Math.ceil((block.bottom - block.top) / viewport.height));
      if (wanted > MAX_TILES_PER_SECTION) result.tiles_truncated = true;
      let lastY = null;
      for (let k = 0; k < Math.min(wanted, MAX_TILES_PER_SECTION); k += 1) {
        if (total >= MAX_TILES_PER_VIEWPORT) { result.tiles_truncated = true; break; }
        const y = await isolated(cdp, pageScrollTo, block.top + k * viewport.height);
        if (y === lastY) break;   // the end of the page: the same screen again
        lastY = y;
        const rel = `tiles/${tag}/s${String(index + 1).padStart(2, "0")}-t${String(k + 1).padStart(2, "0")}.png`;
        await page.screenshot({ path: path.join(input.out_dir, rel), type: "png", captureBeyondViewport: false });
        result.tiles.push({ file: rel, section: index + 1, element: block.element, scroll_y: y });
        total += 1;
      }
    }
    result.weight_bytes = Array.from(loaded.values()).reduce((sum, size) => sum + size, 0);
  } catch (e) {
    result.error = stage;
    process.stderr.write(`[capture_page] ${tag} ${stage}: ${String(e && e.message || e).slice(0, 400)}\n`);
  } finally {
    await page.close().catch(() => {});
  }

  // 2. Motion frames: a second, separate set, with reduced motion NOT requested.
  if (!result.error && input.motion_times_ms.length) {
    const motion = await openPage(browser, log, viewport, false);
    try {
      const dir = path.join(input.out_dir, "motion", tag);
      fs.mkdirSync(dir, { recursive: true });
      await motion.page.goto(fileUrl, { waitUntil: "load", timeout: input.page_timeout_ms });
      const start = Date.now();
      for (const [index, at] of input.motion_times_ms.entries()) {
        const wait = at - (Date.now() - start);
        if (wait > 0) await sleep(wait);
        const rel = `motion/${tag}/f${String(index + 1).padStart(2, "0")}-${String(at).padStart(4, "0")}ms.png`;
        await motion.page.screenshot({ path: path.join(input.out_dir, rel), type: "png", captureBeyondViewport: false });
        result.motion_frames.push(rel);
      }
    } catch (e) {
      result.motion_error = "motion-failed";
      process.stderr.write(`[capture_page] ${tag} motion-failed: ${String(e && e.message || e).slice(0, 400)}\n`);
    } finally {
      await motion.page.close().catch(() => {});
    }
  }
  return result;
}

// --- main ----------------------------------------------------------------------------------------

async function main() {
  let input;
  try {
    input = await readStdinJson(() => abandon("stdin closed"));
    if (input.watch_parent) watchParent(input);
  } catch (e) {
    process.stderr.write(`[capture_page] bad input: ${e.message}\n`);
    return emit({ gap: "bad-input" }, 3);
  }

  let launch;
  try {
    launch = await import(LAUNCH_MODULE);
  } catch (e) {
    process.stderr.write(`[capture_page] launch module: ${e.message}\n`);
    return emit({ gap: "no-launch-module" }, 3);
  }
  const versions = { node: process.version, puppeteer_core: launch.puppeteerVersion({ envVars: PUPPETEER_ENV }), chrome: null };

  let puppeteer;
  try {
    puppeteer = await launch.loadPuppeteer({ envVars: PUPPETEER_ENV });
  } catch (e) {
    process.stderr.write(`[capture_page] puppeteer-core: ${e.message}\n`);
    return emit({ gap: "no-puppeteer", versions }, 3);
  }
  // A Chrome the caller named is the one to use: no quiet fall-back to another binary.
  const chromeMissing = input.chrome_path ? !fs.existsSync(input.chrome_path) : !launch.findChrome();
  if (chromeMissing) return emit({ gap: "no-chrome", versions }, 3);

  // `pipe: true`: Chrome talks to this process over a pipe and exits when the pipe closes, so it
  // cannot outlive a node that was killed.
  const base = { chromePath: input.chrome_path, headless: true, userDataDir: input.profile_dir, args: CHROME_ARGS,
                 pipe: true };
  const start = (more) => launch.launchChrome(puppeteer, { ...base, ...more });
  let browser, stamp;
  try {
    if (input.simulate_sandbox_failure) throw new Error("No usable sandbox! (simulated by the caller)");
    ({ browser, stamp } = await start({ sandbox: true }));
  } catch (e) {
    if (!/sandbox/i.test(String(e && e.message))) {
      process.stderr.write(`[capture_page] launch: ${String(e && e.message).slice(0, 600)}\n`);
      return emit({ gap: "chrome-launch-failed", versions }, 3);
    }
    // The sandbox could not start. Run without it and say so; the page is still held to its
    // own directory, with offline emulation on.
    const reason = input.simulate_sandbox_failure
      ? "the sandbox failure was simulated by the caller"
      : "Chrome's own sandbox could not start on this host";
    try {
      ({ browser, stamp } = await start({ sandbox: false, noSandboxReason: reason }));
    } catch (e2) {
      process.stderr.write(`[capture_page] launch without sandbox: ${String(e2 && e2.message).slice(0, 600)}\n`);
      return emit({ gap: "chrome-launch-failed", versions }, 3);
    }
  }

  watched.browser = browser;
  const sandbox = { state: stamp.state, reason: stamp.reason, confirmed: false, method: null, renderers: 0 };
  const viewports = [];
  let log;
  try {
    const rootReal = fs.realpathSync(input.variant_dir);
    log = new RequestLog(rootReal);
    versions.chrome = await browser.version();
    // A window the page opens is not one of ours: note where it wanted to go and close it.
    browser.on("targetcreated", async (target) => {
      if (target.type() !== "page" || !target.opener()) return;
      log.note(target.url());
      const popup = await target.page().catch(() => null);
      if (popup) await popup.close().catch(() => {});
    });
    const fileUrl = pathToFileURL(path.join(rootReal, "index.html")).href;
    for (const [index, viewport] of input.viewports.entries()) {
      const onFirstPage = index === 0 ? () => Object.assign(sandbox, launch.confirmSandbox(browser)) : null;
      viewports.push(await captureViewport(browser, log, input, viewport, fileUrl, onFirstPage));
    }
  } finally {
    await browser.close().catch(() => {});
  }

  return emit({
    gap: null,
    sandbox,
    offline_emulation: true,
    versions,
    viewports,
    requests: { inside: Array.from(log.inside.keys()).sort().slice(0, MAX_REQUESTS_LISTED), outside: log.outside,
                truncated: log.truncated || log.inside.size > MAX_REQUESTS_LISTED },
  }, 0);
}

main().catch((e) => {
  // The browser is closed by main's own `finally`; exit now, so a handle Chrome left behind cannot
  // keep the wrapper waiting for its timeout.
  process.stderr.write(`[capture_page] crashed: ${String(e && e.stack || e).slice(0, 1000)}\n`);
  process.exit(1);
});
