"""
Image generation via Pollinations.ai (FREE, no API key).
Used by the chat stream to generate images when AI returns an action.
"""
from __future__ import annotations

import hashlib
import time

from app.core.logging import get_logger

logger = get_logger("ai.image_gen")


async def generate_image_url(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    model: str = "flux",
    seed: int | None = None,
) -> str:
    """Generate an image and return its URL.
    
    Pollinations.ai generates the image on-demand from the URL,
    so we just need to construct the URL and verify it works.
    """
    import httpx

    if seed is None:
        seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % 100000

    encoded_prompt = prompt.replace(" ", "%20").replace(",", "%2C")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}"
        f"&model={model}&seed={seed}&nologo=true"
    )

    # Verify the image is accessible
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.head(url)
            resp.raise_for_status()
        
        elapsed = int((time.time() - start) * 1000)
        logger.info("Image generated in %dms: %s", elapsed, prompt[:80])
        return url
    except Exception as exc:
        logger.warning("Image generation failed: %s", exc)
        raise
