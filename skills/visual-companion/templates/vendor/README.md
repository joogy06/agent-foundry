# Vendored libraries

This directory holds offline-safe copies of third-party JS libraries used
by visual-companion HTML templates. CDN fallback is implemented in each
template, so missing vendor files degrade gracefully (with a banner).

## cytoscape.min.js

**Required by:** `graph-cytoscape.html` (D2 blast-radius diagrams from
intent-map-render)

**License:** MIT (Cytoscape Consortium)

**Source:** https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js

**How to install:**

```bash
# Inside the repo:
curl -sSL https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js \
    -o ~/.claude/skills/visual-companion/templates/vendor/cytoscape.min.js
```

If this file is missing, `graph-cytoscape.html` falls back to the
unpkg CDN automatically (and shows a banner). Air-gapped environments
must vendor this file once.

## Why we don't auto-vendor in CI

This R&D repository deliberately keeps third-party binaries out of git.
The `publish-to-github` skill's scrub pass would catch any large unwanted
binary committed by accident; the vendor file is downloaded by users
post-install if they need offline rendering.

Future S033 may move this to a dedicated `assets/` directory shipped via
the publish pipeline, but for v1 the README + CDN fallback is sufficient.
