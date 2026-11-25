```radar
name: VoiceStudio
slug: voicestudio
category: voice-audio
alternative_to: ElevenLabs (TTS, voice cloning, dubbing)
homepage: https://voicestudio.sh
repo: https://github.com/debpalash/VoiceStudio
licence_code: AGPL-3.0 (a separate paid Pro build exists)
licence_other: per bundled engine; only CosyVoice 3 (Apache-2.0) is clear for commercial use
cost: free self-hosted; Pro build paid
maturity: v0.5.7 (2026-10-26)
mcp: unknown
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (shared video, task #369)
related_skills: []
tags: [tts, text-to-speech, voice-cloning, dubbing, voice-over, local, open-source, elevenlabs-alternative]
verdict: Local voice app; the commercially usable engine covers 9 languages, not 646. No TTS skill yet.
origin: #369, docs/reviews/2026-10-29-video-tools-369.md
```

## What it is

A local desktop and web app that wraps several open text-to-speech and voice-cloning engines behind one UI, pitched as an open alternative to ElevenLabs.

## Verified facts

- VERIFIED: code licence AGPL-3.0, repository github.com/debpalash/VoiceStudio; a separate paid Pro build is sold. Source: https://github.com/debpalash/VoiceStudio (via #369, 2026-10-29).
- VERIFIED: latest release v0.5.7, dated 2026-10-26. Source: https://github.com/debpalash/VoiceStudio (via #369, 2026-10-29).
- VERIFIED: the engine licences differ from the app licence. The engine that permits commercial use, CosyVoice 3 (Apache-2.0), covers 9 languages. Source: https://github.com/debpalash/VoiceStudio (via #369, 2026-10-29).
- UNCERTAIN: whether it exposes an MCP server. Not checked in #369.

## Claims that are false or overstated

- "646 languages": true only across the non-commercial engines. For commercial work the figure is 9 (CosyVoice 3).

## Foundry fit

- No foundry skill covers text-to-speech, voice cloning or dubbing; `vertex-banana` is images only.
- AGPL-3.0: private, unmodified local use carries no obligations. Distributing it (or a modified copy) carries the source-offer obligations of sections 4-6, and running a MODIFIED copy as a network service for others triggers section 13. Source: https://opensource.org/license/agpl-3-0 (read 2026-10-29).
- Voice cloning of a real person needs that person's consent; any future skill must say so.

## Decision and next step

Assess. Worth knowing, no use now. Move to trial only when voice-over or dubbing work appears, and then pick the engine by its own licence, not the app's.

## Sources

- https://github.com/debpalash/VoiceStudio (via #369, 2026-10-29)
- https://voicestudio.sh (linked from the video's resource page, read 2026-10-29)
- https://www.simonhoiberg.com/resources/open-ai-alternatives (via #369, 2026-10-29)
- Foundry review: docs/reviews/2026-10-29-video-tools-369.md (task #369), which checked each claim against primary sources on 2026-10-29. The review keeps its conclusions, not per-fact read receipts: facts marked "via #369" are inherited from it, and the URL beside each is the primary page for that fact (repo URLs from the review or the video's resource page), not a fresh re-read.
