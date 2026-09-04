"""
Image generation endpoint using Pollinations.ai (free, no API key required).
"""
from __future__ import annotations

import hashlib
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("api.image_gen")

router = APIRouter()


class ImageGenRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="Image description")
    width: int = Field(default=1024, ge=256, le=2048, description="Image width")
    height: int = Field(default=1024, ge=256, le=2048, description="Image height")
    model: Optional[str] = Field(default=None, description="Model name (flux, turbo)")
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility")
    enhance: bool = Field(default=True, description="Enhance prompt with AI")


class ImageGenResponse(BaseModel):
    url: str
    prompt: str
    width: int
    height: int
    model: str
    seed: int
    generation_time_ms: int


@router.post("/generate", response_model=ImageGenResponse, summary="Generate image from text")
async def generate_image(request: ImageGenRequest) -> ImageGenResponse:
    """Generate an image from a text prompt using Pollinations.ai (free)."""
    import httpx

    start = time.time()

    model = request.model or "flux"
    seed = request.seed if request.seed is not None else int(hashlib.md5(request.prompt.encode()).hexdigest()[:8], 16) % 100000

    # Pollinations.ai free API
    encoded_prompt = request.prompt.replace(" ", "%20").replace(",", "%2C")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={request.width}&height={request.height}"
        f"&model={model}&seed={seed}&nologo=true"
    )

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type and len(resp.content) < 1000:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Image generation returned invalid response",
                )

        elapsed = int((time.time() - start) * 1000)
        logger.info("Image generated in %dms (model=%s, seed=%d)", elapsed, model, seed)

        return ImageGenResponse(
            url=url,
            prompt=request.prompt,
            width=request.width,
            height=request.height,
            model=model,
            seed=seed,
            generation_time_ms=elapsed,
        )
    except httpx.HTTPStatusError as exc:
        logger.error("Image generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Image generation service error: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        logger.error("Image generation connection error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image generation service unavailable",
        )


class ImageVariationRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    num_variations: int = Field(default=4, ge=1, le=8)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)


@router.post("/variations", summary="Generate multiple image variations")
async def generate_variations(request: ImageVariationRequest):
    """Generate multiple variations of an image prompt."""
    import asyncio
    import httpx

    start = time.time()
    results = []

    async def _gen_one(seed: int):
        encoded = request.prompt.replace(" ", "%20").replace(",", "%2C")
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={request.width}&height={request.height}"
            f"&model=flux&seed={seed}&nologo=true"
        )
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return {
            "url": url,
            "seed": seed,
        }

    tasks = [_gen_one(42 + i * 1000) for i in range(request.num_variations)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = [r for r in results if not isinstance(r, Exception)]

    return {
        "prompt": request.prompt,
        "variations": valid,
        "generation_time_ms": int((time.time() - start) * 1000),
    }
