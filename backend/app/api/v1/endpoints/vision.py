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
    provider_name = None

    try:
        from app.ai.providers import ProviderError as AIPError

        if settings.GROQ_API_KEY:
            try:
                from app.ai.providers import vision_caption

                description = await vision_caption(data_url, prompt or None, model=model)
                provider_name = "groq"
            except AIPError:
                pass
            except Exception as groq_exc:
                if not settings.GEMINI_API_KEY and not settings.OPENAI_API_KEY:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Vision provider error: {groq_exc}",
                    )

        if not provider_name and settings.GEMINI_API_KEY:
            try:
                from app.ai.providers import gemini_caption

                description = await gemini_caption(image_bytes, mime, prompt or None, model=model)
                provider_name = "gemini"
            except Exception as gem_exc:
                if not settings.OPENAI_API_KEY:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Vision provider error: {gem_exc}",
                    )

        if not provider_name:
            if not settings.OPENAI_API_KEY:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="No vision provider is configured (set GROQ_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY)",
                )

            from openai import AsyncOpenAI

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
            description = response.choices[0].message.content
            provider_name = "openai"
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Vision failed: {exc}")

    used_model = model or (
        settings.GROQ_VISION_MODEL
        if provider_name == "groq"
        else "gemini-flash-latest"
        if provider_name == "gemini"
        else "gpt-4o-mini"
    )
    return {
        "description": description,
        "model": used_model,
        "provider": provider_name,
        "image_size": len(image_bytes),
        "mime_type": mime,
    }
