---
name: vertex-banana
description: Use when the user asks to create, generate, make, draw, design, or edit any image or visual content — blog featured images, YouTube thumbnails, icons, diagrams, patterns, illustrations, photos, visual assets, graphics, artwork, pictures. REQUIRED for all image generation requests — PRIMARY image skill (direct Google Vertex AI / Gemini image API via VERTEX_API_KEY, no gemini CLI dependency; SDK + models verified live 2026-06-10). Replaces nano-banana (legacy — gemini CLI retired 2026-06-18).
allowed-tools: Bash(python3 *vertex_banana.py*), Bash(pip install *google-genai*), Bash(curl *aiplatform.googleapis.com*), Bash([ -n "$VERTEX_API_KEY" ]), Bash(ls *vertex-banana*), Bash(identify *)
---

# Vertex Banana — Image Generation via Google Vertex AI

Generate and edit images using Google Vertex AI Gemini models. Supports two methods: **Python SDK** (preferred) and **curl** (fallback).

## When to Use This Skill

Use when the user asks to generate or edit images via Google Vertex AI / Gemini image models:
- Text-to-image generation
- Image editing (modify existing images with text instructions)
- Any request mentioning "vertex banana" or Vertex AI image generation

## Setup

### 1. Verify API Key

```bash
[ -n "$VERTEX_API_KEY" ] && echo "API key configured" || echo "Missing VERTEX_API_KEY"
```

`VERTEX_API_KEY` is the Vertex AI API key (53 chars). The script temporarily clears conflicting SDK env vars (`GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`) during execution to prevent auth conflicts.

### 2. Install Python SDK (for Python method)

```bash
pip install --upgrade google-genai
```

## Script Location

The Python script lives in the skill folder and is accessible from any project:

```
~/.claude/skills/vertex-banana/vertex_banana.py
```

Always reference it with the full path: `$HOME/.claude/skills/vertex-banana/vertex_banana.py`

---

## Method 1: Python SDK (Preferred)

Uses the `google-genai` Python package. Handles streaming, image saving, and error handling automatically.

### Text-to-Image

```bash
python3 $HOME/.claude/skills/vertex-banana/vertex_banana.py "a cat wearing sunglasses on a beach"
```

### Image Editing

```bash
python3 $HOME/.claude/skills/vertex-banana/vertex_banana.py "make the sky purple and add stars" -i input.png
```

### With Options

```bash
python3 $HOME/.claude/skills/vertex-banana/vertex_banana.py \
  "professional product photo of sneakers" \
  -m flash-image \
  --aspect-ratio 16:9 \
  --image-size 2K \
  -o ./my-output \
  -f product_shot
```

### All Python Script Options

| Flag | Default | Description |
|------|---------|-------------|
| `prompt` | (required) | Image generation or editing prompt |
| `-o, --output-dir` | `./vertex-banana-output` | Output directory |
| `-m, --model` | `flash-image` | Model shorthand or full ID |
| `-i, --input-image` | — | Input image for editing |
| `-f, --filename` | auto-timestamped | Output filename (no extension) |
| `--aspect-ratio` | `auto` | `auto`, `1:1`, `16:9`, `9:16`, `4:3`, `3:4` |
| `--image-size` | `1K` | `1K` or `2K` |
| `--mime-type` | `image/png` | `image/png` or `image/jpeg` |
| `--person-generation` | `ALLOW_ALL` | `ALLOW_ALL`, `ALLOW_ADULT`, `DONT_ALLOW` |
| `--thinking-level` | `HIGH` | `NONE`, `LOW`, `MEDIUM`, `HIGH` |
| `--temperature` | `1.0` | Generation temperature |
| `--top-p` | `0.95` | Top P sampling |
| `--curl` | — | Use curl method instead of Python SDK |
| `--vertex` | — | Use Vertex AI endpoint instead of standard Gemini API |
| `--endpoint` | `aiplatform.googleapis.com` | Custom API endpoint |

---

## Method 2: Curl (Fallback)

Use when the `google-genai` package is not installed. The same Python script handles this with the `--curl` flag.

### Via Script

```bash
python3 $HOME/.claude/skills/vertex-banana/vertex_banana.py "a sunset over mountains" --curl
```

### Raw Curl (Manual)

Build the request JSON, send via curl, and parse the response:

**Step 1: Create request.json**

```bash
VB_WORK=$(mktemp -d /tmp/vb-XXXXXXXXXX)
cat << 'EOF' > "$VB_WORK/request.json"
{
    "contents": [
        {
            "role": "user",
            "parts": [
                {
                    "text": "YOUR PROMPT HERE"
                }
            ]
        }
    ],
    "generationConfig": {
        "temperature": 1,
        "maxOutputTokens": 32768,
        "responseModalities": ["TEXT", "IMAGE"],
        "topP": 0.95,
        "imageConfig": {
            "aspectRatio": "auto",
            "imageSize": "1K",
            "imageOutputOptions": {
                "mimeType": "image/png"
            },
            "personGeneration": "ALLOW_ALL"
        },
        "thinkingConfig": {
            "thinkingLevel": "HIGH"
        }
    },
    "safetySettings": [
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"}
    ]
}
EOF
```

**Step 2: Send request**

```bash
MODEL_ID="gemini-3.1-flash-image"

curl -s -X POST \
  -H "Content-Type: application/json" \
  "https://aiplatform.googleapis.com/v1/publishers/google/models/${MODEL_ID}:streamGenerateContent?key=${VERTEX_API_KEY}" \
  -d @"$VB_WORK/request.json" -o "$VB_WORK/response.json"
```

**Step 3: Extract and save image**

```bash
python3 -c "
import json, base64, os
os.makedirs('vertex-banana-output', exist_ok=True)
with open('$VB_WORK/response.json') as f:
    data = json.load(f)
chunks = data if isinstance(data, list) else [data]
n = 0
for chunk in chunks:
    for c in chunk.get('candidates', []):
        for p in c.get('content', {}).get('parts', []):
            if 'inlineData' in p:
                n += 1
                img = base64.b64decode(p['inlineData']['data'])
                path = f'vertex-banana-output/image_{n}.png'
                open(path, 'wb').write(img)
                print(f'Saved: {path}')
            elif 'text' in p:
                print(p['text'])
print(f'{n} image(s) generated' if n else 'No images in response')
"
```

---

## Available Models

> **Note:** All model IDs below verified LIVE against the API on 2026-06-10 (`client.models.list()`). They may still change as Google rotates previews.

| Shorthand | Model ID | Description |
|-----------|----------|-------------|
| `flash-image` | `gemini-3.1-flash-image` | **Default.** STABLE channel — image gen & editing, high quality, low latency |
| `flash-image-preview` | `gemini-3.1-flash-image-preview` | Preview channel of the default |
| `pro-image` | `gemini-3-pro-image` | Pro-tier image model (stable) |
| `pro` | `gemini-3.1-pro-preview` | Best quality, complex agentic workloads |
| `flash-lite` | `gemini-3.1-flash-lite-preview` | Most affordable, high-volume agents & large-scale data |
| `flash` | `gemini-3-flash-preview` | Enhanced multimodal & coding capabilities |
| `pro-3` | `gemini-3-pro-preview` | Previous gen pro (still served as of 2026-06-10) |

**Thinking level**: valid API values are `MINIMAL | LOW | MEDIUM | HIGH` (default HIGH). `NONE` is rejected by the API with 400 INVALID_ARGUMENT — the script maps the legacy `NONE` choice to `MINIMAL`.

## Common Sizes & Aspect Ratios

| Use Case | Aspect Ratio | Image Size | Notes |
|----------|-------------|------------|-------|
| General / auto-detect | `auto` | `1K` | Default — model picks best ratio |
| YouTube thumbnail | `16:9` | `2K` | 1280x720 equivalent |
| Blog featured image | `16:9` | `1K` | Social preview friendly |
| Square social | `1:1` | `1K` | Instagram, LinkedIn |
| Vertical story | `9:16` | `1K` | Mobile stories |
| Product photo | `4:3` | `2K` | Standard product layout |

## Output Location

Images are saved to `./vertex-banana-output/` in the current working directory by default. Override with `-o /path/to/dir`.

## Presenting Results

After generation completes:
1. Check `./vertex-banana-output/` for the generated file(s)
2. Show the image to the user using the Read tool (it supports images)
3. Offer to regenerate with different options if needed

## Prompt Tips

1. **Be specific** — include style, mood, colors, composition details
2. **Add "no text"** — if you don't want text rendered in the image
3. **Reference styles** — "editorial photography", "flat illustration", "3D render", "watercolor"
4. **For editing** — describe exactly what to change: "make the background blue" not "change it"

## Replaces nano-banana

This skill replaces the older `nano-banana` skill (which used Gemini CLI + nanobanana extension). Key differences:
- **vertex-banana**: Direct Vertex AI API via Python SDK or curl. Uses `VERTEX_API_KEY`.
- **nano-banana** (legacy): Gemini CLI wrapper. Uses `GEMINI_API_KEY`. Still exists at `~/.claude/skills/nano-banana/`.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `VERTEX_API_KEY` not set | `export VERTEX_API_KEY="your-key"` |
| `google-genai` not installed | `pip install --upgrade google-genai` (verified working on 2.8.0, 2026-06-10; 1.x also works) |
| 429 RESOURCE_EXHAUSTED | Rate limit — wait and retry, or check quota in Cloud Console |
| 400 INVALID_ARGUMENT | Try simplifying options or check model name |
| 400 Multi-modal output not supported | Use `flash-image` model — only one supporting image output |
| 401 UNAUTHENTICATED | Wrong key type. Ensure `VERTEX_API_KEY` is the Vertex AI key (53 chars) |
| SDK uses wrong key | Remove `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI` from env — they override explicit config |
| `person_generation` TypeError | SDK version too old — script auto-falls back without it |
| No images generated | Check prompt for policy violations, simplify request |
| Curl JSON parse error | Verify API key is valid, check response for error messages |
| Model not found | Check model list above, model IDs change with previews |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using Vertex AI image generation for text-heavy images | AI models render text poorly; misspellings and distorted characters are common | Generate the image without text; add text overlays using proper design tools or CSS afterward |
| Not specifying aspect ratio for target platform | Default output may not match blog header (16:9), social media (1:1), or thumbnail (4:3) requirements | Always specify aspect ratio and dimensions matching the deployment target in the generation request |
| Sending requests without error handling for quota limits | Vertex AI has per-minute and per-day quotas; unhandled 429 errors crash the workflow | Implement exponential backoff retry; catch 429 responses; fall back to nano-banana or queue for later |
| Using high-resolution output for web thumbnails | Unnecessarily large images waste bandwidth, slow page loads, and consume more API quota | Request appropriate resolution for the use case; downscale large outputs before serving on web |
| Not validating prompt against content policy before submission | Policy violations return errors after consuming API quota; repeated violations may restrict account | Review prompts for policy compliance (no violent, explicit, or deceptive content); handle policy errors gracefully |

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: google-genai
    verified_against: "2.8.0"
    verified_on: "2026-06-10"
  - kind: api_surface
    subject: vertex-image-models
    verified_against: "gemini-3.1-flash-image (stable default), gemini-3-pro-image, previews live"
    verified_on: "2026-06-10"
-->
