```radar
name: KittenTTS
slug: kittentts
category: voice-audio
alternative_to: cloud TTS APIs; heavier local TTS engines
homepage: https://github.com/KittenML/KittenTTS
repo: https://github.com/KittenML/KittenTTS
licence_code: Apache-2.0
licence_other: nano/micro/mini weights Apache-2.0; KittenTTS 2 (1.7B) weights Stellon Labs Community License, commercial grant ends above USD 1M revenue or funding
cost: free; separate licence needed above the threshold for KittenTTS 2
maturity: latest tag 0.8.1 (2026-02-24), no GitHub releases; KittenTTS 2 weights since; C++ inference beta
mcp: unknown
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (2026-10-29)
related_skills: []
tags: [tts, text-to-speech, voice-ai, tiny-model, cpu, on-device, onnx, voice-cloning, kitten-tts, tinykity, tinykitty]
verdict: Tiny CPU TTS models (15M-80M Apache-2.0; 1.7B KittenTTS 2 under a revenue-capped licence).
origin: owner request 2026-10-29 (tool-radar intake)
```

## What it is

A family of small text-to-speech models from KittenML (Stellon Labs) built for CPU and on-device use. The small models (15M to 80M parameters, 25 MB to 80 MB) run without a GPU; KittenTTS 2 (1.7B) adds 20 languages, 115 voices and voice cloning.

## Verified facts

- VERIFIED: the owner's "tinykity (voice ai)" means KittenTTS. Source: owner confirmation relayed by the team lead (2026-10-29).
- VERIFIED: code licence Apache-2.0; about 16.7k stars; install `pip install kittenml`. Source: https://github.com/KittenML/KittenTTS (read 2026-10-29).
- VERIFIED: small models: kitten-tts-nano 15M (25 MB int8), micro 40M (41 MB), mini 80M (80 MB). Source: https://github.com/KittenML/KittenTTS (read 2026-10-29).
- VERIFIED: kitten-tts-2 has 115 voices, 20 languages and cloning from 5-30 s of audio. Its body is 1.58-bit ternary: packed default 954 MB ("lossless" refers to the packing, not full precision), emb4 469 MB lossy (the GitHub README says 492 MB), full bf16 3469 MB. The card text says 1.7B parameters, its metadata 2B. Source: https://huggingface.co/KittenML/kitten-tts-2 (read 2026-10-29).
- VERIFIED: kitten-tts-nano-0.8 weights are Apache-2.0. Source: https://huggingface.co/KittenML/kitten-tts-nano-0.8 (read 2026-10-29).
- VERIFIED: KittenTTS 2 weights use the Stellon Labs Community License: research, non-commercial and limited commercial use free; "the commercial grant ends once you or your affiliates pass USD $1,000,000 in annual revenue or in total cumulative funding"; distribution carries attribution requirements. Source: https://huggingface.co/KittenML/kitten-tts-2 (read 2026-10-29).
- UNCERTAIN: secondary write-ups (Better Stack) say the grant is revocable and needs registration; neither the model card nor the README says so, and the licence file was not retrievable. Read the licence text before any commercial use.
- VERIFIED: tags 0.1 (2025-08-05), 0.8 (2026-02-19), 0.8.1 (2026-02-24); the Releases section is empty; C++ inference and expression controls marked beta. Source: https://github.com/KittenML/KittenTTS/tags (read 2026-10-29).
- VERIFIED (local, read-only): not installed (no `kittenml` package found). Source: local read-only check (2026-10-29).

## Other candidates

- tiny-tts (https://github.com/tronghieuit/tiny-tts): a 1M-parameter English-only TTS, if even smaller is needed.

## Claims that are false or overstated

- "Open-source TTS": the code and the small models are; the flagship KittenTTS 2 weights are source-available under a revenue-capped licence.
- "Under 25 MB": true for the int8 nano model only; KittenTTS 2 is 469 MB (lossy emb4) to 954 MB (packed default).

## Foundry fit

- No foundry skill covers TTS; this sits beside the voicestudio radar entry as the lightweight, CPU-only option.
- A Wyoming integration exists, so it is a candidate local voice for Home Assistant (`home-assistant` skill) if that need appears.
- Licence: use the Apache-2.0 small models for anything commercial unless a Stellon Labs licence is bought; that is the owner's decision.

## Decision and next step

Assess. Trial only when a voice-output task appears, starting with the Apache-2.0 nano model.

## Sources

- https://github.com/KittenML/KittenTTS (read 2026-10-29)
- https://huggingface.co/KittenML/kitten-tts-2 (read 2026-10-29)
- https://huggingface.co/KittenML/kitten-tts-nano-0.8 (read 2026-10-29)
- https://github.com/KittenML/KittenTTS/tags (read 2026-10-29)
- https://github.com/tronghieuit/tiny-tts (read 2026-10-29)
- https://betterstack.com/community/guides/ai/kitten-tts-2/ (secondary, for the UNCERTAIN licence line)
