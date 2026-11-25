```radar
name: PhotoCraft
slug: photocraft
category: image-editing
alternative_to: Adobe Photoshop (layered raster editing)
homepage: https://github.com/storytold/photocraft
repo: https://github.com/storytold/photocraft
licence_code: Apache-2.0 OR MIT
licence_other: n/a
cost: free
maturity: v0.17.0, early alpha (release dates look anomalous; see below)
mcp: server
ring: hold
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (shared video, task #369)
related_skills: [vertex-banana]
tags: [image-editing, photoshop-alternative, psd, layers, rust, mcp-server, early-alpha]
verdict: Early-alpha Rust Photoshop rebuild with an MCP server; PSD round-trip unreliable and repo signals look anomalous. Hold.
origin: #369, docs/reviews/2026-10-29-video-tools-369.md
```

## What it is

A Rust rebuild of a Photoshop-style layered image editor, with an MCP server so an agent can drive edits.

## Verified facts

- VERIFIED: dual Apache-2.0 / MIT licence; release v0.17.0; described by its authors as early alpha. Source: https://github.com/storytold/photocraft (via #369, 2026-10-29).
- VERIFIED: ships an MCP server. Source: https://github.com/storytold/photocraft (via #369, 2026-10-29).
- LIKELY: a PSD it re-saves is not reliably accepted by Photoshop. Source: https://github.com/storytold/photocraft (via #369, 2026-10-29).
- UNCERTAIN: the star count and release dates look anomalous for the project's age; not explained. Source: https://github.com/storytold/photocraft (via #369, 2026-10-29).

## Claims that are false or overstated

- "A Photoshop replacement": early alpha, and the PSD round-trip that a replacement needs is not reliable.

## Foundry fit

- No foundry skill does layer editing; `vertex-banana` generates and edits images through a model API, which is a different job.
- An MCP server that writes files on the host is a tool surface; adopting it would need the usual intake scan and a sandboxed trial.

## Decision and next step

Hold because the repository signals (star count, release dates) look anomalous and the PSD round-trip is unreliable: an unexplained anomaly on a tool that would run with file-write access is a supply-chain risk, and the alpha cannot yet do the job it is pitched for. Reason to revisit: organic release history over the next quarter and a working PSD round-trip. Until then, do not install.

## Sources

- https://github.com/storytold/photocraft (via #369, 2026-10-29)
- https://www.simonhoiberg.com/resources/open-ai-alternatives (via #369, 2026-10-29)
- Foundry review: docs/reviews/2026-10-29-video-tools-369.md (task #369), which checked each claim against primary sources on 2026-10-29. The review keeps its conclusions, not per-fact read receipts: facts marked "via #369" are inherited from it, and the URL beside each is the primary page for that fact (repo URLs from the review or the video's resource page), not a fresh re-read.
