"""
AI provider abstraction.

A thin async streaming interface over OpenAI, Anthropic, Google Gemini and
OpenRouter so the orchestration layer is provider-agnostic.
"""
from __future__ import annotations

import re
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.config import settings


class ProviderError(Exception):
    """Raised when a provider call fails."""


class ChatProvider:
    """Common async streaming chat interface."""

    name: str = "base"

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield events: {'type': 'content', 'content': str} | {'type': 'tool_call', ...}."""
        raise NotImplementedError

    async def embed(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """Return embedding vectors for a list of texts."""
        raise NotImplementedError

    async def transcribe(self, audio_bytes: bytes, **kwargs: Any) -> str:
        raise NotImplementedError

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        raise NotImplementedError


class OpenAIProvider(ChatProvider):
    """OpenAI-compatible chat and embeddings (also powers OpenRouter)."""

    name = "openai"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.default_model = "gpt-4o-mini"
        self.embedding_model = settings.EMBEDDING_MODEL

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url or None)

    async def stream(self, messages, model=None, temperature=None, max_tokens=None, tools=None, system_prompt=None, **kwargs):
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")

        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(messages)

        client = self._client()
        stream_kwargs: Dict[str, Any] = {
            "model": model or self.default_model,
            "messages": msgs,
        }
        if temperature is not None:
            stream_kwargs["temperature"] = temperature
        if max_tokens is not None:
            stream_kwargs["max_tokens"] = max_tokens
        if tools:
            stream_kwargs["tools"] = tools

        stream = await client.chat.completions.create(**stream_kwargs, stream=True)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                yield {"type": "content", "content": delta.content}
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    yield {
                        "type": "tool_call",
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }

    async def embed(self, texts, model=None):
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")
        client = self._client()
        resp = await client.embeddings.create(model=model or self.embedding_model, input=texts)
        return [d.embedding for d in resp.data]

    async def transcribe(self, audio_bytes, **kwargs):
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        transcript = await client.audio.transcriptions.create(
            model=settings.STT_MODEL,
            file=("audio.webm", audio_bytes),
        )
        return transcript.text

    async def synthesize(self, text, voice=None, language=None):
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.audio.speech.create(
            model=settings.TTS_MODEL,
            voice=voice or settings.TTS_VOICE,
            input=text,
        )
        return response.content


class AnthropicProvider(ChatProvider):
    """Anthropic Claude streaming."""

    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.base_url = base_url or settings.ANTHROPIC_BASE_URL
        self.default_model = "claude-3-5-haiku-latest"

    def _client(self):
        from anthropic import AsyncAnthropic

        kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return AsyncAnthropic(**kwargs)

    async def stream(self, messages, model=None, temperature=None, max_tokens=None, tools=None, system_prompt=None, **kwargs):
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not configured")

        client = self._client()
        async with client.messages.stream(
            model=model or self.default_model,
            messages=messages,
            system=system_prompt,
            temperature=temperature if temperature is not None else 0.7,
            max_tokens=max_tokens or 4096,
            tools=tools,
        ) as stream:
            async for text in stream.text_stream:
                yield {"type": "content", "content": text}


class GeminiProvider(ChatProvider):
    """Google Gemini streaming via google-genai client."""

    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.base_url = base_url or settings.GEMINI_BASE_URL
        self.default_model = "gemini-flash-latest"

    async def stream(self, messages, model=None, temperature=None, max_tokens=None, tools=None, system_prompt=None, **kwargs):
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not configured")

        from google import genai

        client = genai.Client(api_key=self.api_key) if not self.base_url else genai.Client(
            api_key=self.api_key, http_options={"base_url": self.base_url}
        )

        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

        config: Dict[str, Any] = {"temperature": temperature if temperature is not None else 0.7}
        if system_prompt:
            config["system_instruction"] = system_prompt
        if max_tokens:
            config["max_output_tokens"] = max_tokens

        response = await client.aio.models.generate_content_stream(
            model=model or self.default_model,
            contents=contents,
            config=config,
        )
        async for chunk in response:
            if chunk.candidates:
                parts = chunk.candidates[0].content.parts
                for part in parts:
                    if part.text:
                        yield {"type": "content", "content": part.text}

    async def embed(self, texts, model=None):
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not configured")
        if not texts:
            return []

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key) if not self.base_url else genai.Client(
            api_key=self.api_key, http_options={"base_url": self.base_url}
        )
        embed_model = model or settings.GEMINI_EMBEDDING_MODEL
        dimension = settings.GEMINI_EMBEDDING_DIMENSION

        vectors: List[List[float]] = []
        batch_size = settings.EMBEDDING_BATCH_SIZE
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            resp = await client.aio.models.embed_content(
                model=embed_model,
                contents=batch,
                config=types.EmbedContentConfig(output_dimensionality=dimension),
            )
            vectors.extend([e.values for e in resp.embeddings])
        return vectors


class GroqProvider(OpenAIProvider):
    """Groq is OpenAI-compatible for chat and transcription (no embeddings)."""

    name = "groq"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        super().__init__(
            api_key=api_key or settings.GROQ_API_KEY,
            base_url=base_url or settings.GROQ_BASE_URL,
        )
        self.default_model = settings.GROQ_MODEL

    async def embed(self, texts, model=None):
        raise ProviderError("Groq does not provide embedding models; using local embeddings instead")

    async def transcribe(self, audio_bytes, **kwargs):
        if not self.api_key:
            raise ProviderError("GROQ_API_KEY is not configured")
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        model = kwargs.get("model") or "whisper-large-v3"
        transcript = await client.audio.transcriptions.create(
            model=model,
            file=("audio.webm", audio_bytes),
        )
        return transcript.text


class LocalEmbeddingProvider(ChatProvider):
    """Local embeddings via sentence-transformers — free, no API key needed."""

    name = "local"

    def __init__(self, model: Optional[str] = None) -> None:
        self.model_name = model or settings.LOCAL_EMBEDDING_MODEL
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    async def embed(self, texts, model=None):
        if not texts:
            return []
        import asyncio

        st_model = await asyncio.to_thread(self._load)
        vectors = await asyncio.to_thread(
            st_model.encode, list(texts), normalize_embeddings=True
        )
        return [v.tolist() for v in vectors]

    def dimension(self) -> int:
        return settings.LOCAL_EMBEDDING_DIMENSION


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter exposes an OpenAI-compatible API."""

    name = "openrouter"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
        )
        self.default_model = "openai/gpt-4o-mini"

    async def transcribe(self, audio_bytes, **kwargs):
        raise ProviderError("OpenRouter does not support transcription")


class ElevenLabsTTS:
    """Text-to-speech via ElevenLabs."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or settings.ELEVENLABS_API_KEY

    async def synthesize(self, text: str, voice: Optional[str] = None, language: Optional[str] = None) -> bytes:
        if not self.api_key:
            raise ProviderError("ELEVENLABS_API_KEY is not configured")
        import httpx

        voice_id = voice or settings.ELEVENLABS_VOICE_ID
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": self.api_key},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
            )
            resp.raise_for_status()
            return resp.content


EDGE_VOICES: Dict[str, str] = {
    "en": "en-US-JennyNeural",
    "hi": "hi-IN-SwaraNeural",
    "bn": "bn-IN-TanishaaNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "kn": "kn-IN-SapnaNeural",
    "ml": "ml-IN-SobhanaNeural",
    "mr": "mr-IN-AarohiNeural",
    "gu": "gu-IN-DhwaniNeural",
    "pa": "pa-IN-CharleenNeural",
    "ur": "ur-PK-UzmaNeural",
    "ne": "ne-NP-HemkalaNeural",
    "si": "si-LK-ThiliniNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ar": "ar-SA-ZariyahNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ko": "ko-KR-SunHiNeural",
    "tr": "tr-TR-EmelNeural",
    "nl": "nl-NL-ColetteNeural",
    "pl": "pl-PL-ZofiaNeural",
    "sv": "sv-SE-SofieNeural",
    "th": "th-TH-PremwadeeNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "id": "id-ID-GadisNeural",
    "el": "el-GR-AthinaNeural",
    "he": "he-IL-HilaNeural",
    "sw": "sw-KE-ZuriNeural",
    "uk": "uk-UA-PolinaNeural",
    "cs": "cs-CZ-VlastaNeural",
    "ro": "ro-RO-AlinaNeural",
    "da": "da-DK-ChristelNeural",
    "fi": "fi-FI-SelmaNeural",
    "nb": "nb-NO-PernilleNeural",
    "ms": "ms-MY-YasminNeural",
    "fa": "fa-IR-DilaraNeural",
    "my": "my-MM-NilarNeural",
    "km": "km-KH-SreymomNeural",
}

EDGE_SCRIPT_VOICES: List[tuple[str, Any, str]] = [
    ("devanagari", re.compile(r"[\u0900-\u097F]"), "hi-IN-SwaraNeural"),
    ("bengali", re.compile(r"[\u0980-\u09FF]"), "bn-IN-TanishaaNeural"),
    ("odia", re.compile(r"[\u0B00-\u0B7F]"), "hi-IN-SwaraNeural"),
    ("tamil", re.compile(r"[\u0B80-\u0BFF]"), "ta-IN-PallaviNeural"),
    ("telugu", re.compile(r"[\u0C00-\u0C7F]"), "te-IN-ShrutiNeural"),
    ("kannada", re.compile(r"[\u0C80-\u0CFF]"), "kn-IN-SapnaNeural"),
    ("malayalam", re.compile(r"[\u0D00-\u0D7F]"), "ml-IN-SobhanaNeural"),
    ("sinhala", re.compile(r"[\u0D80-\u0DFF]"), "si-LK-ThiliniNeural"),
    ("gujarati", re.compile(r"[\u0A80-\u0AFF]"), "gu-IN-DhwaniNeural"),
    ("gurmukhi", re.compile(r"[\u0A00-\u0A7F]"), "pa-IN-CharleenNeural"),
    ("arabic", re.compile(r"[\u0600-\u06FF]"), "ar-SA-ZariyahNeural"),
    ("cyrillic", re.compile(r"[\u0400-\u04FF]"), "ru-RU-SvetlanaNeural"),
    ("kana", re.compile(r"[\u3040-\u30FF]"), "ja-JP-NanamiNeural"),
    ("hangul", re.compile(r"[\uAC00-\uD7AF]"), "ko-KR-SunHiNeural"),
    ("han", re.compile(r"[\u4E00-\u9FFF]"), "zh-CN-XiaoxiaoNeural"),
    ("thai", re.compile(r"[\u0E00-\u0E7F]"), "th-TH-PremwadeeNeural"),
    ("myanmar", re.compile(r"[\u1000-\u109F]"), "my-MM-NilarNeural"),
    ("khmer", re.compile(r"[\u1780-\u17FF]"), "km-KH-SreymomNeural"),
    ("greek", re.compile(r"[\u0370-\u03FF]"), "el-GR-AthinaNeural"),
    ("hebrew", re.compile(r"[\u0590-\u05FF]"), "he-IL-HilaNeural"),
]


ODIA_TO_DEVANAGARI: Dict[str, str] = {
    "\u0B01": "\u0901", "\u0B02": "\u0902", "\u0B03": "\u0903",
    "\u0B05": "\u0905", "\u0B06": "\u0906", "\u0B07": "\u0907", "\u0B08": "\u0908",
    "\u0B09": "\u0909", "\u0B0A": "\u090A", "\u0B0B": "\u090B",
    "\u0B0F": "\u090F", "\u0B10": "\u0910", "\u0B13": "\u0913", "\u0B14": "\u0914",
    "\u0B15": "\u0915", "\u0B16": "\u0916", "\u0B17": "\u0917", "\u0B18": "\u0918",
    "\u0B19": "\u0919", "\u0B1A": "\u091A", "\u0B1B": "\u091B", "\u0B1C": "\u091C",
    "\u0B1D": "\u091D", "\u0B1E": "\u091E", "\u0B1F": "\u091F", "\u0B20": "\u0920",
    "\u0B21": "\u0921", "\u0B22": "\u0922", "\u0B23": "\u0923", "\u0B24": "\u0924",
    "\u0B25": "\u0925", "\u0B26": "\u0926", "\u0B27": "\u0927", "\u0B28": "\u0928",
    "\u0B2A": "\u092A", "\u0B2B": "\u092B", "\u0B2C": "\u092C", "\u0B2D": "\u092D",
    "\u0B2E": "\u092E", "\u0B2F": "\u092F", "\u0B30": "\u0930", "\u0B32": "\u0932",
    "\u0B33": "\u0933", "\u0B35": "\u0935", "\u0B36": "\u0936", "\u0B37": "\u0937",
    "\u0B38": "\u0938", "\u0B39": "\u0939", "\u0B3C": "\u093C",
    "\u0B3E": "\u093E", "\u0B3F": "\u093F", "\u0B40": "\u0940", "\u0B41": "\u0941",
    "\u0B42": "\u0942", "\u0B43": "\u0943", "\u0B47": "\u0947", "\u0B48": "\u0948",
    "\u0B4B": "\u094B", "\u0B4C": "\u094C", "\u0B4D": "\u094D", "\u0B57": "\u0949",
    "\u0B5C": "\u0921\u093C", "\u0B5D": "\u0922\u093C", "\u0B5F": "\u092F",
    "\u0B66": "\u0966", "\u0B67": "\u0967", "\u0B68": "\u0968", "\u0B69": "\u0969",
    "\u0B6A": "\u096A", "\u0B6B": "\u096B", "\u0B6C": "\u096C", "\u0B6D": "\u096D",
    "\u0B6E": "\u096E", "\u0B6F": "\u096F",
}

_ODIA_RE = re.compile(r"[\u0B00-\u0B7F]")


def transliterate_odia(text: str) -> str:
    """Odia script has no Edge TTS voice; map to Devanagari so Hindi voice reads it."""
    return "".join(ODIA_TO_DEVANAGARI.get(ch, ch) for ch in text)


def detect_edge_voice(text: str, language: Optional[str] = None) -> str:
    """Pick a natural Edge TTS voice for the text's language.

    Explicit language wins, then Unicode-script detection for non-Latin
    scripts, then langdetect for Latin-script languages, English as default.
    """
    if language:
        base = language.lower().split("-")[0]
        return EDGE_VOICES.get(base, "en-US-JennyNeural")
    if text:
        for _name, pattern, voice in EDGE_SCRIPT_VOICES:
            if pattern.search(text):
                return voice
        try:
            from langdetect import detect

            return EDGE_VOICES.get(detect(text), "en-US-JennyNeural")
        except Exception:  # noqa: BLE001
            return "en-US-JennyNeural"
    return "en-US-JennyNeural"


class EdgeTTSTTS:
    """Text-to-speech via Microsoft Edge TTS (free, no API key)."""

    def __init__(self, voice: Optional[str] = None) -> None:
        self.voice = voice or settings.TTS_EDGE_VOICE

    async def synthesize(self, text: str, voice: Optional[str] = None, language: Optional[str] = None) -> bytes:
        try:
            import edge_tts
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "edge-tts is not installed. Run `pip install edge-tts`."
            ) from exc

        if text and _ODIA_RE.search(text):
            text = transliterate_odia(text)
        selected = voice or detect_edge_voice(text, language)
        candidates: List[str] = []
        for cand in (selected, self.voice, "en-US-JennyNeural"):
            if cand and cand not in candidates:
                candidates.append(cand)
        last_error: Optional[Exception] = None
        for cand in candidates:
            try:
                communicate = edge_tts.Communicate(text, cand)
                chunks: List[bytes] = []
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        chunks.append(chunk["data"])
                if chunks:
                    return b"".join(chunks)
            except (ValueError, Exception) as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise ProviderError(f"TTS failed for all voices: {last_error}")


async def synthesize_speech(text: str, voice: Optional[str] = None) -> bytes:
    """Synthesize speech with Edge TTS, falling back to ElevenLabs."""
    try:
        return await EdgeTTSTTS(voice=voice).synthesize(text)
    except Exception:  # noqa: BLE001
        return await ElevenLabsTTS().synthesize(text, voice=voice)


async def vision_caption(
    image_data_url: str,
    question: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Ask Groq's vision model about an image (base64 data URL).

    Raises ProviderError when GROQ_API_KEY is not configured or Groq fails.
    """
    if not settings.GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY is not configured")
    import httpx

    prompt = question or "Describe this image in detail."
    payload = {
        "model": model or settings.GROQ_VISION_MODEL,
        "temperature": 0.3,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{settings.GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            raise ProviderError("Unexpected vision response from Groq")
        import re

        content = re.sub(r"\s*<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        return content or "No description returned by the model."


async def gemini_caption(
    image_bytes: bytes,
    mime_type: str,
    question: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Ask Gemini's vision model about an image.

    Raises ProviderError when GEMINI_API_KEY is not configured or Gemini fails.
    """
    if not settings.GEMINI_API_KEY:
        raise ProviderError("GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai import types

    client = (
        genai.Client(api_key=settings.GEMINI_API_KEY)
        if not settings.GEMINI_BASE_URL
        else genai.Client(api_key=settings.GEMINI_API_KEY, http_options={"base_url": settings.GEMINI_BASE_URL})
    )

    prompt = question or "Describe this image in detail."
    response = await client.aio.models.generate_content(
        model=model or "gemini-flash-latest",
        contents=[
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
    )
    if not response.text:
        raise ProviderError("Gemini returned an empty response")
    return response.text


def get_provider(name: str, **kwargs: Any) -> ChatProvider:
    """Return a provider instance by name."""
    providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "google": GeminiProvider,
        "openrouter": OpenRouterProvider,
        "groq": GroqProvider,
    }
    provider_cls = providers.get(name.lower(), OpenAIProvider)
    return provider_cls(**kwargs)


def default_provider() -> ChatProvider:
    """Choose the best available provider based on configured keys."""
    if settings.GROQ_API_KEY:
        return GroqProvider()
    if settings.ANTHROPIC_API_KEY:
        return AnthropicProvider()
    if settings.GEMINI_API_KEY:
        return GeminiProvider()
    if settings.OPENROUTER_API_KEY:
        return OpenRouterProvider()
    return OpenAIProvider()


def embedding_provider() -> ChatProvider:
    """Choose the provider used for embeddings (falls back to local, no key needed)."""
    if settings.GEMINI_API_KEY:
        return GeminiProvider()
    if settings.OPENAI_API_KEY:
        return OpenAIProvider()
    if settings.OPENROUTER_API_KEY:
        return OpenRouterProvider()
    return LocalEmbeddingProvider()


def embedding_dimension() -> int:
    """Return the embedding vector dimension for the active provider."""
    if settings.GEMINI_API_KEY:
        return settings.GEMINI_EMBEDDING_DIMENSION
    if settings.OPENAI_API_KEY or settings.OPENROUTER_API_KEY:
        return settings.EMBEDDING_DIMENSION
    return settings.LOCAL_EMBEDDING_DIMENSION
