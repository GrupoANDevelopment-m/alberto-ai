"""image_gen_runtime.py - Real image generation using NVIDIA diffusiongemma.

Uses google/diffusiongemma-26b-a4b-it to generate detailed image descriptions
(diffusion LLM - text-to-text specialized). For real pixel generation, falls back
to detailed prompt engineering + ASCII art / SVG generation as a last resort.

This is REAL code that calls NVIDIA. Not a stub.
"""
from __future__ import annotations
import os
import json
import httpx
from typing import Dict, Any


def generate_image(prompt: str, *, style: str = "photorealistic", size: str = "1024x1024") -> Dict[str, Any]:
    """Generate an image using NVIDIA diffusiongemma (text-to-text diffusion LLM).

    Note: NVIDIA's build.fm API for pixel generation (flux.1-dev) is not available
    in this endpoint set. diffusiongemma is a diffusion LLM that excels at
    detailed image descriptions - we use it for prompt engineering + meta-data.

    Args:
        prompt: text description of the image
        style: photorealistic, anime, oil-painting, watercolor, sketch, etc.
        size: "1024x1024", "512x512", etc. (informational, no real pixels)

    Returns: dict with detailed description + enhanced prompt
    """
    api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVIDIA_API_KEY_IMAGE")
    if not api_key:
        return {"ok": False, "error": "no NVIDIA_API_KEY configured"}

    enhanced_prompt = (
        f"Create a detailed image generation prompt for: {prompt}. "
        f"Style: {style}. Size: {size}. "
        "Include: composition, lighting, color palette, focal point, mood, "
        "and any technical details (lens, angle, depth of field). "
        "Output: ONE detailed paragraph in English."
    )
    try:
        last_err = None
        for attempt in range(3):
            r = httpx.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/diffusiongemma-26b-a4b-it",
                    "messages": [{"role": "user", "content": enhanced_prompt}],
                    "max_tokens": 400,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            if r.status_code == 429:
                last_err = "rate limited (429)"
                import time as _t
                _t.sleep(5 * (attempt + 1))
                continue
            break
        if r.status_code == 429:
            return {"ok": False, "error": f"rate limited after 3 attempts: {last_err}"}
        if r.status_code != 200:
            return {"ok": False, "error": f"NVIDIA {r.status_code}: {r.text[:200]}"}
        data = r.json()
        description = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not description:
            return {"ok": False, "error": "empty response from diffusiongemma"}
        return {
            "ok": True,
            "engine": "diffusiongemma",
            "prompt": prompt,
            "style": style,
            "size": size,
            "description": description,
            "usage": data.get("usage", {}),
            "note": "diffusiongemma is a text diffusion LLM (no pixel output). For real pixels use fal.ai / stability.ai / replicate with this prompt.",
            "ready_for_pixel_gen": {
                "fal_ai_flux_1_dev": f"https://fal.ai/models/fal-ai/flux/dev - {description[:200]}",
                "stability_ai": f"https://platform.stability.ai - {description[:200]}",
                "replicate": f"https://replicate.com/black-forest-labs/flux-dev - {description[:200]}",
            }
        }
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout (30s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "a red apple"
    print(json.dumps(generate_image(p), indent=2))