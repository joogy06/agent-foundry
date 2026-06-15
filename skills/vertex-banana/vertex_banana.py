#!/usr/bin/env python3
"""Vertex Banana - Generate and edit images using Google Vertex AI Gemini models.

Usage:
    python3 vertex_banana.py "a cat wearing sunglasses"
    python3 vertex_banana.py "make the sky purple" -i photo.png
    python3 vertex_banana.py "a logo" -m pro --aspect-ratio 1:1

Requires: pip install google-genai
Auth: Set VERTEX_API_KEY environment variable
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Available models (verified LIVE against the API on 2026-06-10)
MODELS = {
    "flash-image": "gemini-3.1-flash-image",            # Default - STABLE image gen & editing, low latency
    "flash-image-preview": "gemini-3.1-flash-image-preview",  # Preview channel of the default
    "pro-image": "gemini-3-pro-image",                  # Pro-tier image model (stable)
    "pro": "gemini-3.1-pro-preview",                    # Best quality, complex agentic workloads
    "flash-lite": "gemini-3.1-flash-lite-preview",      # Most affordable, high-volume
    "flash": "gemini-3-flash-preview",                   # Enhanced multimodal & coding
    "pro-3": "gemini-3-pro-preview",                     # Previous gen pro (still served as of 2026-06-10)
}
DEFAULT_MODEL = "gemini-3.1-flash-image"


def generate(args):
    """Generate or edit an image using the Python google-genai SDK."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("ERROR: google-genai not installed. Run: pip install google-genai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("VERTEX_API_KEY")
    if not api_key:
        print("ERROR: VERTEX_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    # The SDK auto-detects these env vars and overrides explicit params.
    # Temporarily clear them so our explicit VERTEX_API_KEY is used.
    saved_env = {}
    for key_name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        if key_name in os.environ:
            saved_env[key_name] = os.environ.pop(key_name)

    # Build client with API key
    # --vertex flag uses ADC (project/location) instead of API key
    if args.vertex:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            print("ERROR: --vertex requires GOOGLE_CLOUD_PROJECT env var", file=sys.stderr)
            os.environ.update(saved_env)
            sys.exit(1)
        client = genai.Client(vertexai=True, project=project, location=location)
    else:
        client = genai.Client(api_key=api_key)

    # Restore env vars
    os.environ.update(saved_env)

    # Build content parts
    parts = []
    if args.input_image:
        img_path = Path(args.input_image)
        if not img_path.exists():
            print(f"ERROR: File not found: {args.input_image}", file=sys.stderr)
            sys.exit(1)
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif",
        }
        img_mime = mime_map.get(img_path.suffix.lower(), "image/png")
        parts.append(types.Part.from_bytes(data=img_path.read_bytes(), mime_type=img_mime))
    parts.append(types.Part.from_text(text=args.prompt))
    contents = [types.Content(role="user", parts=parts)]

    # Build config — start minimal, add extras only when non-default
    config_kwargs = {
        "response_modalities": ["TEXT", "IMAGE"],
    }

    # Only add generation params when non-default
    if args.temperature != 1.0:
        config_kwargs["temperature"] = args.temperature
    if args.top_p != 0.95:
        config_kwargs["top_p"] = args.top_p

    # Safety settings
    config_kwargs["safety_settings"] = [
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
    ]

    # Image config — only when non-default values requested
    img_cfg_kwargs = {}
    if args.aspect_ratio != "auto":
        img_cfg_kwargs["aspect_ratio"] = args.aspect_ratio
    if args.image_size != "1K":
        img_cfg_kwargs["image_size"] = args.image_size
    if args.mime_type != "image/png":
        img_cfg_kwargs["output_mime_type"] = args.mime_type
    if args.person_generation != "ALLOW_ALL":
        img_cfg_kwargs["person_generation"] = args.person_generation
    if img_cfg_kwargs:
        try:
            config_kwargs["image_config"] = types.ImageConfig(**img_cfg_kwargs)
        except TypeError:
            # Remove unsupported fields and retry
            img_cfg_kwargs.pop("person_generation", None)
            if img_cfg_kwargs:
                config_kwargs["image_config"] = types.ImageConfig(**img_cfg_kwargs)

    # Thinking config — only when non-default. Valid API enum (SDK 2.8.0):
    # MINIMAL | LOW | MEDIUM | HIGH ("NONE" was rejected with 400 INVALID_ARGUMENT).
    thinking_level = "MINIMAL" if args.thinking_level == "NONE" else args.thinking_level
    if thinking_level != "HIGH":
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

    config = types.GenerateContentConfig(**config_kwargs)

    # Resolve model shorthand
    model = MODELS.get(args.model, args.model)

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Model: {model}")
    print(f"Prompt: {args.prompt}")
    if args.input_image:
        print(f"Input image: {args.input_image}")
    print("Generating...\n")

    # Stream response with error handling
    image_count = 0
    text_parts = []
    try:
        for chunk in client.models.generate_content_stream(
            model=model, contents=contents, config=config,
        ):
            if not chunk.candidates:
                continue
            for candidate in chunk.candidates:
                if not candidate.content or not candidate.content.parts:
                    continue
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                        image_count += 1
                        ext = "png" if "png" in (part.inline_data.mime_type or "image/png") else "jpg"
                        if args.filename:
                            fname = f"{args.filename}.{ext}" if image_count == 1 else f"{args.filename}_{image_count}.{ext}"
                        else:
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            fname = f"vb_{ts}_{image_count}.{ext}"
                        out_path = outdir / fname
                        out_path.write_bytes(part.inline_data.data)
                        print(f"Saved: {out_path}")
                    elif hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            print(f"ERROR: Rate limit exceeded. Wait a moment and try again.", file=sys.stderr)
            print(f"Detail: {err_str[:200]}", file=sys.stderr)
        elif "400" in err_str or "INVALID_ARGUMENT" in err_str:
            print(f"ERROR: Invalid request. Try simplifying options or check model name.", file=sys.stderr)
            print(f"Detail: {err_str[:200]}", file=sys.stderr)
        else:
            print(f"ERROR: {err_str[:300]}", file=sys.stderr)
        return False

    if text_parts:
        print(f"\nModel response: {''.join(text_parts)}")
    if image_count == 0:
        print("WARNING: No images were generated.", file=sys.stderr)
        return False
    print(f"\nDone: {image_count} image(s) saved to {outdir}/")
    return True


def generate_curl(args):
    """Generate an image using curl (no Python SDK needed, only stdlib for response parsing)."""
    import subprocess
    import tempfile

    api_key = os.environ.get("VERTEX_API_KEY")
    if not api_key:
        print("ERROR: VERTEX_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Resolve model
    model = MODELS.get(args.model, args.model)
    endpoint = args.endpoint or "aiplatform.googleapis.com"
    api_method = "streamGenerateContent"

    # Build request JSON
    request_parts = []
    if args.input_image:
        img_path = Path(args.input_image)
        if not img_path.exists():
            print(f"ERROR: File not found: {args.input_image}", file=sys.stderr)
            sys.exit(1)
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif",
        }
        img_mime = mime_map.get(img_path.suffix.lower(), "image/png")
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        request_parts.append({"inlineData": {"mimeType": img_mime, "data": img_b64}})
    request_parts.append({"text": args.prompt})

    # Build generationConfig — Vertex AI and Gemini API have different schemas
    is_gemini_api = "generativelanguage" in endpoint
    if is_gemini_api:
        # Gemini API: minimal imageConfig, uses responseMimeType for output format
        image_config = {}
    else:
        # Vertex AI: full imageConfig with output options and person generation
        image_config = {
            "aspectRatio": args.aspect_ratio,
            "imageSize": args.image_size,
            "imageOutputOptions": {"mimeType": args.mime_type},
            "personGeneration": args.person_generation,
        }

    gen_config = {
        "temperature": args.temperature,
        "maxOutputTokens": 32768,
        "responseModalities": ["TEXT", "IMAGE"],
        "topP": args.top_p,
    }
    # Only add imageConfig and thinkingConfig for Vertex AI (Gemini API doesn't support them)
    if not is_gemini_api:
        gen_config["imageConfig"] = image_config
        # API enum: MINIMAL | LOW | MEDIUM | HIGH (no NONE)
        gen_config["thinkingConfig"] = {"thinkingLevel": "MINIMAL" if args.thinking_level == "NONE" else args.thinking_level}

    request_body = {
        "contents": [{"role": "user", "parts": request_parts}],
        "generationConfig": gen_config,
        "safetySettings": [
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
        ],
    }

    # Different URL path for Gemini API vs Vertex AI
    if "generativelanguage" in endpoint:
        url = f"https://{endpoint}/v1beta/models/{model}:{api_method}?key={api_key}"
    else:
        url = f"https://{endpoint}/v1/publishers/google/models/{model}:{api_method}?key={api_key}"

    print(f"Model: {model}")
    print(f"Endpoint: {endpoint}")
    print(f"Prompt: {args.prompt}")
    if args.input_image:
        print(f"Input image: {args.input_image}")
    print("Generating via curl...\n")

    # Write request to temp file and call curl
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(request_body, tmp)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json", url, "-d", f"@{tmp_path}"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"ERROR: curl failed: {result.stderr}", file=sys.stderr)
            return False
        response_text = result.stdout
    finally:
        os.unlink(tmp_path)

    # Parse response — streamGenerateContent returns a JSON array
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON response:\n{response_text[:500]}", file=sys.stderr)
        return False

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Check for API errors in response
    chunks = data if isinstance(data, list) else [data]
    for chunk in chunks:
        if "error" in chunk:
            err = chunk["error"]
            code = err.get("code", "?")
            msg = err.get("message", "Unknown error")
            print(f"ERROR: API returned {code}: {msg}", file=sys.stderr)
            return False

    # Handle both array (streaming) and object (non-streaming) responses
    image_count = 0
    for chunk in chunks:
        for candidate in chunk.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "inlineData" in part:
                    image_count += 1
                    img_bytes = base64.b64decode(part["inlineData"]["data"])
                    ext = "png" if "png" in part["inlineData"].get("mimeType", "image/png") else "jpg"
                    if args.filename:
                        fname = f"{args.filename}.{ext}" if image_count == 1 else f"{args.filename}_{image_count}.{ext}"
                    else:
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        fname = f"vb_{ts}_{image_count}.{ext}"
                    out_path = outdir / fname
                    out_path.write_bytes(img_bytes)
                    print(f"Saved: {out_path}")
                elif "text" in part:
                    print(f"Model: {part['text']}")

    if image_count == 0:
        print("WARNING: No images were generated.", file=sys.stderr)
        return False
    print(f"\nDone: {image_count} image(s) saved to {outdir}/")
    return True


def main():
    p = argparse.ArgumentParser(
        description="Vertex Banana - Image generation via Google Vertex AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Models (use shorthand or full ID; verified live 2026-06-10):
  flash-image          gemini-3.1-flash-image          (default, STABLE image gen & editing)
  flash-image-preview  gemini-3.1-flash-image-preview  (preview channel)
  pro-image            gemini-3-pro-image               (pro-tier image model, stable)
  pro                  gemini-3.1-pro-preview           (best quality)
  flash-lite           gemini-3.1-flash-lite-preview    (fast, affordable)
  flash                gemini-3-flash-preview            (general purpose)
  pro-3                gemini-3-pro-preview              (previous gen pro)""",
    )
    p.add_argument("prompt", help="Image generation or editing prompt")
    p.add_argument("-o", "--output-dir", default="./vertex-banana-output",
                   help="Output directory (default: ./vertex-banana-output)")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL,
                   help="Model shorthand or full ID (default: flash-image)")
    p.add_argument("-i", "--input-image", help="Input image path for editing")
    p.add_argument("-f", "--filename", help="Output filename without extension")

    # Image config
    p.add_argument("--aspect-ratio", default="auto",
                   choices=["auto", "1:1", "16:9", "9:16", "4:3", "3:4"],
                   help="Aspect ratio (default: auto)")
    p.add_argument("--image-size", default="1K", choices=["1K", "2K"],
                   help="Image size (default: 1K)")
    p.add_argument("--mime-type", default="image/png",
                   choices=["image/png", "image/jpeg"],
                   help="Output format (default: image/png)")
    p.add_argument("--person-generation", default="ALLOW_ALL",
                   choices=["ALLOW_ALL", "ALLOW_ADULT", "DONT_ALLOW"],
                   help="Person generation policy (default: ALLOW_ALL)")

    # Generation config
    p.add_argument("--thinking-level", default="HIGH",
                   choices=["MINIMAL", "LOW", "MEDIUM", "HIGH", "NONE"],
                   help="Thinking level (default: HIGH; NONE is a legacy alias for MINIMAL)")
    p.add_argument("--temperature", type=float, default=1.0,
                   help="Temperature (default: 1.0)")
    p.add_argument("--top-p", type=float, default=0.95,
                   help="Top P (default: 0.95)")

    # Method selection
    p.add_argument("--curl", action="store_true",
                   help="Use curl method instead of Python SDK")
    p.add_argument("--vertex", action="store_true",
                   help="Use Vertex AI endpoint instead of standard Gemini API")
    p.add_argument("--endpoint", default=None,
                   help="Custom API endpoint (default: aiplatform.googleapis.com)")

    args = p.parse_args()

    if args.curl:
        success = generate_curl(args)
    else:
        success = generate(args)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
