"""
Vision endpoints: image analysis via vision-capable models.
"""
from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.security import get_current_active_user
from app.models.user import User

router = APIRouter()


@router.post("/analyze", summary="Analyze an image")
async def analyze_image(
    file: UploadFile = File(...),
    prompt: str = Form("Describe this image in detail."),
    model: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
):
    """Send an image to a vision-capable model and return its analysis."""
    if not settings.FEATURE_VISION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vision features are disabled")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image file")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = file.content_type or "image/png"
    data_url = f"data:{mime};base64,{image_b64}"

    try:
        from openai import AsyncOpenAI

        if not settings.OPENAI_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is not configured",
            )

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=settings.VISION_MAX_TOKENS,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return {
        "description": response.choices[0].message.content,
        "model": model or "gpt-4o-mini",
        "image_size": len(image_bytes),
        "mime_type": mime,
    }
