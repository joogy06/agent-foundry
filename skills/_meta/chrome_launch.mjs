// chrome_launch.mjs — the one place a harness script finds puppeteer-core, finds Chrome and
// builds its launch options (#352, JC-3).
//
// Users: skills/creative-studio/scripts/capture_page.mjs and skills/_meta/skeleton_extractor.mjs.
// geometry_measure.mjs and visual_arbiter_measure.mjs still carry their own launch code.
//
// SANDBOX: Chrome's own sandbox is ON unless the caller passes `sandbox: false` WITH a reason.
// The choice is returned as a stamp (`{state, reason}`) that the caller writes into its
// output, so a run without the sandbox is never indistinguishable from one with it. This
// module never adds `--no-sandbox` on its own and never retries a failed launch without it:
// a caller that wants that fallback asks for it and records it.
//
// A started process is not proof of a sandbox. `confirmSandbox(browser)` reads the kernel's
// view on Linux: every renderer process must run under a seccomp filter (Seccomp: 2 in
// /proc/<pid>/status), which Chrome only installs when its sandbox is up.

import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

const NO_SANDBOX_ARGS = ["--no-sandbox", "--disable-setuid-sandbox"];

/** Import puppeteer-core from a package directory (the one holding its package.json). */
async function importPackageDir(dir) {
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  const mod = await import(path.join(dir, pkg.module || pkg.main || "index.js"));
  return mod.default || mod;
}

/**
 * Locate puppeteer-core. ESM resolution ignores NODE_PATH, so the order is:
 *   1. the first set variable of `envVars`: an absolute path to the package directory;
 *   2. standard ESM resolution from this file upward;
 *   3. CommonJS resolution through createRequire, which honours NODE_PATH;
 *   4. each directory of `fallbackDirs` holding a puppeteer-core package.
 * Throws when none of them has it.
 */
export async function loadPuppeteer({
  envVars = ["CHROME_LAUNCH_PUPPETEER_PATH"],
  fallbackDirs = defaultPuppeteerDirs(),
} = {}) {
  for (const name of envVars) {
    const explicit = process.env[name];
    if (explicit) return importPackageDir(explicit);
  }
  try {
    const mod = await import("puppeteer-core");
    return mod.default || mod;
  } catch (_e1) {
    try {
      const require = createRequire(import.meta.url);
      return require("puppeteer-core");
    } catch (e2) {
      for (const dir of fallbackDirs) {
        if (fs.existsSync(path.join(dir, "package.json"))) return importPackageDir(dir);
      }
      throw e2;
    }
  }
}

export function defaultPuppeteerDirs() {
  return [
    path.join(os.homedir(), ".claude", "node_modules", "puppeteer-core"),
    "/usr/local/lib/node_modules/puppeteer-core",
  ];
}

/** The puppeteer-core version beside the module that was loaded, or null. */
export function puppeteerVersion({ envVars = ["CHROME_LAUNCH_PUPPETEER_PATH"], fallbackDirs = defaultPuppeteerDirs() } = {}) {
  const dirs = envVars.map((n) => process.env[n]).filter(Boolean);
  try {
    const require = createRequire(import.meta.url);
    dirs.push(path.dirname(require.resolve("puppeteer-core/package.json")));
  } catch (_e) { /* not resolvable from here */ }
  for (const dir of dirs.concat(fallbackDirs)) {
    try {
      return JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8")).version || null;
    } catch (_e) { /* next */ }
  }
  return null;
}

/** The Chrome binary: `explicit`, then $CHROME_PATH, then the usual places. Null when absent. */
export function findChrome(explicit) {
  const candidates = [
    explicit,
    process.env.CHROME_PATH,
    "/bin/google-chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return null;
}

/**
 * Build puppeteer launch options and the sandbox stamp.
 *
 *   sandbox          true (default) keeps Chrome's sandbox; false adds the no-sandbox flags
 *   noSandboxReason  required when sandbox is false; it goes into the stamp
 *   args             the caller's other Chrome flags (a no-sandbox flag here is refused)
 *   pipe             true starts Chrome on a pipe and not a socket: Chrome then exits when the
 *                    process that launched it goes away, however that process ended
 *
 * Returns { options, stamp } with stamp = { state: "on" | "off", reason }.
 */
export function launchOptions({
  chromePath,
  sandbox = true,
  noSandboxReason = null,
  headless = true,
  args = [],
  userDataDir = null,
  defaultViewport = null,
  pipe = false,
} = {}) {
  if (args.some((a) => NO_SANDBOX_ARGS.includes(a))) {
    throw new Error("chrome_launch: pass sandbox: false with a reason, not a no-sandbox flag");
  }
  if (!sandbox && !(typeof noSandboxReason === "string" && noSandboxReason.trim())) {
    throw new Error("chrome_launch: sandbox: false needs a noSandboxReason");
  }
  const executablePath = findChrome(chromePath);
  if (!executablePath) throw new Error("chrome_launch: no Chrome binary found");
  const options = {
    executablePath,
    headless,
    args: sandbox ? [...args] : [...NO_SANDBOX_ARGS, ...args],
  };
  if (userDataDir) options.userDataDir = userDataDir;
  if (defaultViewport) options.defaultViewport = defaultViewport;
  if (pipe) options.pipe = true;
  return { options, stamp: { state: sandbox ? "on" : "off", reason: sandbox ? null : noSandboxReason.trim() } };
}

/** Launch Chrome. Returns { browser, stamp }; a failed launch throws, with no retry. */
export async function launchChrome(puppeteer, opts = {}) {
  const { options, stamp } = launchOptions(opts);
  const browser = await puppeteer.launch(options);
  return { browser, stamp };
}

function descendants(pid) {
  const parents = new Map();
  for (const name of fs.readdirSync("/proc")) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const stat = fs.readFileSync(`/proc/${name}/stat`, "utf8");
      parents.set(Number(name), Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]));
    } catch (_e) { /* the process ended */ }
  }
  const out = [];
  const queue = [pid];
  while (queue.length) {
    const parent = queue.shift();
    for (const [child, ppid] of parents) {
      if (ppid === parent) { out.push(child); queue.push(child); }
    }
  }
  return out;
}

/**
 * Whether Chrome's sandbox is really up, read from the kernel and not from the flags.
 * Call it after a page exists, so a renderer process does.
 *
 * Returns { confirmed, method, renderers }:
 *   confirmed true   every renderer runs under a seccomp filter (Linux)
 *   confirmed false  a no-sandbox flag is on the command line, a renderer has no filter,
 *                    no renderer was found, or the host gives no way to look (not Linux)
 */
export function confirmSandbox(browser) {
  const proc = browser.process();
  if (!proc) return { confirmed: false, method: "no browser process to inspect", renderers: 0 };
  if (proc.spawnargs.some((a) => NO_SANDBOX_ARGS.includes(a))) {
    return { confirmed: false, method: "a no-sandbox flag is on the command line", renderers: 0 };
  }
  if (process.platform !== "linux") {
    return { confirmed: false, method: "launch flags only (no kernel check on this platform)", renderers: 0 };
  }
  let renderers = 0;
  let filtered = 0;
  for (const pid of descendants(proc.pid)) {
    try {
      const cmdline = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").replace(/\0/g, " ");
      if (!/--type=renderer\b/.test(cmdline)) continue;
      renderers += 1;
      const status = fs.readFileSync(`/proc/${pid}/status`, "utf8");
      if (/^Seccomp:\s*2\s*$/m.test(status)) filtered += 1;
    } catch (_e) { /* the process ended */ }
  }
  if (renderers === 0) return { confirmed: false, method: "no renderer process found", renderers };
  if (filtered !== renderers) {
    return { confirmed: false, method: "a renderer process runs without a seccomp filter", renderers };
  }
  return { confirmed: true, method: "seccomp-bpf filter on every renderer process", renderers };
}
