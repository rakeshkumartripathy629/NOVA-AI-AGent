"""
Voice endpoints: speech-to-text and text-to-speech.
"""
from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.ai.providers import ElevenLabsTTS, ProviderError, get_provider
from app.core.config import settings
from app.core.security import get_current_active_user
from app.models.user import User

router = APIRouter()


@router.post("/transcribe", summary="Transcribe audio to text")
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
):
    """Convert an audio upload to text using the configured STT provider."""
    if not settings.FEATURE_VOICE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voice features are disabled")

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio file")

    provider = get_provider(settings.STT_PROVIDER)
    try:
        text = await provider.transcribe(
            audio_bytes,
            language=language,
            model=model or settings.STT_MODEL,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return {
        "text": text,
        "language": language,
        "model": model or settings.STT_MODEL,
        "duration_ms": len(audio_bytes),
    }


@router.post("/synthesize", summary="Synthesize speech from text")
async def synthesize(
    text: str = Form(..., min_length=1, max_length=4000),
    voice: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    format: str = Form("mp3"),
    current_user: User = Depends(get_current_active_user),
):
    """Convert text to speech audio, returned as base64."""
    if not settings.FEATURE_VOICE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voice features are disabled")

    if settings.TTS_PROVIDER == "elevenlabs":
        provider = ElevenLabsTTS()
    else:
        provider = get_provider(settings.TTS_PROVIDER)
    try:
        audio = await provider.synthesize(
            text,
            voice=voice or settings.TTS_VOICE,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "format": format,
        "text_length": len(text),
    }
