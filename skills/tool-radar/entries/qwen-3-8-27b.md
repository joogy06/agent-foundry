```radar
name: Qwen 3.8 27B
slug: qwen-3-8-27b
category: llm-model
alternative_to: hosted frontier models for local, private or offline work
homepage: https://huggingface.co/Qwen/Qwen3.8-27B
repo: https://huggingface.co/Qwen/Qwen3.8-27B
licence_code: n/a (weights only)
licence_other: Apache-2.0 (weights)
cost: free weights; local GPU and power
maturity: released with an official FP8 checkpoint (release date not recorded in #369)
mcp: none
ring: trial
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (shared video, task #369)
related_skills: [model-eval-pack, smart-config, ubuntu-ollama-nvidia]
tags: [llm, open-weights, local-model, qwen, apache-2.0, llama.cpp, openai-compatible, 262k-context]
verdict: Apache-2.0 open weights, already served locally; needs a model-eval-pack local provider before any scored trial. Never a seat.
origin: #369, docs/reviews/2026-10-29-video-tools-369.md
```

## What it is

A 27-billion-parameter open-weight model from the Qwen team with a 262k-token context and an official FP8 checkpoint.

## Verified facts

- VERIFIED: weights licensed Apache-2.0; 262k context; official FP8 checkpoint. Source: https://huggingface.co/Qwen/Qwen3.8-27B (via #369, 2026-10-29).
- VERIFIED: 8-bit weights are about 30 GB. Source: https://huggingface.co/Qwen/Qwen3.8-27B (via #369, 2026-10-29).
- VERIFIED (local, read-only): a quantised build is already served locally behind an OpenAI-compatible endpoint. Source: #369 review (host details stay in that review, not in this library).
- VERIFIED (local): `model-eval-pack` has no local or OpenAI-compatible provider, so it cannot score this model today. Source: #369 review.

## Claims that are false or overstated

- "Needs ~96 GB": a comfort size for long context, not a requirement; 8-bit weights are about 30 GB and smaller quantisations run on a 16 GB card at reduced context.

## Foundry fit

- Touches `model-eval-pack` (needs a local provider), `smart-config` and the local-GPU skills.
- Conflicts: it is NOT a seat. The roster names the seat models, and the agy family rule and provider-diversity rule keep seats on Claude, Codex and the agy family. A local model is an execution or experiment option only.

## Decision and next step

Trial (ring set by the owner's team lead, 2026-10-29). It is already running, so the trial costs no install, but it is blocked until `model-eval-pack` has an OpenAI-compatible local provider; that provider is the first task.
Success: the model is scored on the existing model-eval-pack capability cases and its pass rate is recorded here beside the seat models' rates; if it cannot be scored by the next review, move it back to assess.

## Sources

- https://huggingface.co/Qwen/Qwen3.8-27B (via #369, 2026-10-29)
- https://www.simonhoiberg.com/resources/open-ai-alternatives (via #369, 2026-10-29)
- Foundry review: docs/reviews/2026-10-29-video-tools-369.md (task #369), which checked each claim against primary sources on 2026-10-29. The review keeps its conclusions, not per-fact read receipts: facts marked "via #369" are inherited from it, and the URL beside each is the primary page for that fact (repo URLs from the review or the video's resource page), not a fresh re-read.
