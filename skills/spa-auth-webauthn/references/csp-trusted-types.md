# CSP and Trusted Types for a built SPA bundle

Reference for `spa-auth-webauthn` §7. Applies to any Vite (or similar) build served from the same
origin as its API.

## Contents

- 1. Why the auth page needs it
- 2. The policy, directive by directive
- 3. Making the build compatible
- 4. Trusted Types
- 5. Rollout: report-only first
- 6. Verifying the policy

## 1. Why the auth page needs it

An HttpOnly cookie stops script from **reading** the session, but script injected into the page can
still **use** it: call the API, start a WebAuthn ceremony that the user approves out of habit, or
change what an approve button sends. A strict CSP and Trusted Types reduce the chance that
injected script runs at all.

## 2. The policy, directive by directive

```text
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self';
  img-src 'self' data:;
  font-src 'self';
  connect-src 'self';
  worker-src 'self';
  manifest-src 'self';
  object-src 'none';
  base-uri 'none';
  frame-ancestors 'none';
  form-action 'self';
  require-trusted-types-for 'script';
  trusted-types app-html dompurify;
  report-to csp-endpoint
```

| Directive | Note |
|---|---|
| `script-src 'self'` | A static SPA whose `index.html` has no inline script needs neither nonces nor hashes. If one inline script is unavoidable, allow its `sha256-…` hash; never `'unsafe-inline'` |
| `style-src 'self'` | CSS-in-JS libraries that inject `<style>` tags at runtime need a nonce or `'unsafe-inline'` for styles; prefer build-time CSS (CSS modules, Tailwind, vanilla-extract). Style injection is lower risk than script, but still a data-exfiltration path |
| `connect-src 'self'` | Covers `fetch`, `EventSource` and WebSockets to the same origin (`ws:`/`wss:` same-origin is covered by `'self'` in current browsers; list it explicitly if older browsers matter) |
| `frame-ancestors 'none'` | Clickjacking defence for approve buttons; replaces `X-Frame-Options` |
| `base-uri 'none'` | Stops an injected `<base>` from redirecting relative script URLs |
| `require-trusted-types-for 'script'` | DOM injection sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, script `src` and text) accept only Trusted Types objects |
| `trusted-types app-html dompurify` | Only the named policies may be created (DOMPurify creates its own `dompurify` policy when Trusted Types exist); add `default` only during migration |

Send the header from the server on `index.html` and the SPA fallback (the API's JSON responses do
not need it). A `<meta http-equiv>` CSP cannot carry `frame-ancestors`, `report-to` or `sandbox`;
use the header.

## 3. Making the build compatible

- Inspect `dist/index.html` after every build: Vite emits external `<script type="module" src>`
  and `<link rel="modulepreload">` tags; its module-preload polyfill is bundled into the entry
  chunk, not inlined. Plugins can add inline scripts (theme bootstraps, analytics snippets,
  legacy-browser plugins); remove them or move them into a module.
- No `eval`, `new Function` or string `setTimeout` in the bundle; the absence of `'unsafe-eval'`
  enforces this. Some template or expression libraries need eval: replace them.
- Web Workers created from blob URLs need `worker-src blob:`; prefer `new Worker(new URL("./w.ts",
  import.meta.url), { type: "module" })`, which Vite emits as a same-origin file.
- Dev server: Vite's dev server injects inline scripts for HMR; apply the strict policy to the
  production build and test it with `vite preview` or the real server, not with `vite dev`.

## 4. Trusted Types

Support: the Trusted Types API is Baseline "newly available" since February 2026: Chrome and
Edge 83, Safari 26, Firefox 148 (MDN browser-compat-data and caniuse, read 2026-10-26). Older browsers ignore the directives; feature-detect where code depends on the
API, or use the tinyfill (`globalThis.trustedTypes ??= { createPolicy: (_name, rules) => rules };` —
assigning a bare undeclared global throws in an ES module).

React and Trusted Types:

- React's normal rendering sets text and attributes, not HTML; it does not hit the sinks.
- **React 19.3 or later is required** for enforcement: 19.3.0 (2026-09) turned on Trusted Types
  integration; earlier versions stringified the value unless built with a flag that is off by
  default, so the `TrustedHTML` object was lost and enforcement threw.
- `dangerouslySetInnerHTML` does hit `innerHTML`. React assigns the `__html` value to
  `innerHTML` unchanged (read in the `react-dom` 19.3.1 client build, 2026-10-26), so a
  `TrustedHTML` object passes through; create it from one sanitising policy:
- Do not render a `<script>` element from JSX: `react-dom` creates it by assigning a string to a
  `div`'s `innerHTML`, which Trusted Types enforcement blocks (and the CSP should block anyway).

```ts
// security/trusted.ts — the only place HTML is turned into markup
import DOMPurify from "dompurify";

const policy = (globalThis.trustedTypes?.createPolicy("app-html", {
  createHTML: (input: string) => DOMPurify.sanitize(input),   // sanitised string -> TrustedHTML
}) ?? { createHTML: (s: string) => DOMPurify.sanitize(s) });

export const toTrustedHTML = (html: string) => policy.createHTML(html) as unknown as string;

// usage: <div dangerouslySetInnerHTML={{ __html: toTrustedHTML(markdownHtml) }} />
```

- Grep the dependencies for sink use before enforcing: rich-text editors, markdown renderers,
  charting libraries and older component libraries often write `innerHTML`. Each needs either a
  Trusted Types-aware version, a wrapper through your policy, or replacement.
- `default` policy: allowed only as a temporary migration shim that logs and sanitises; remove it
  once report-only shows no violations.

## 5. Rollout: report-only first

1. Ship the full policy as `Content-Security-Policy-Report-Only` with a `report-to` endpoint
   (and `Reporting-Endpoints: csp-endpoint="/api/csp-report"`).
2. Exercise every screen (end-to-end suite plus a day of real use); collect violations.
3. Fix or allow each one deliberately; never broaden `script-src` to make a report disappear.
4. Switch to the enforcing header; keep reporting on.
5. Add a CI check that fails when `dist/index.html` contains an inline `<script>` without `src`, or
   a script or stylesheet from another host.

## 6. Verifying the policy

- Browser devtools console shows CSP and Trusted Types violations with the blocked sink.
- A CSP evaluator (for example Google's CSP Evaluator) flags weak directives.
- Playwright: load each route with the enforcing header and fail the test on any
  `securitypolicyviolation` event (`page.on("console")` or an injected listener).
