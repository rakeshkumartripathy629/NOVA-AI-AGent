"""
AI provider abstraction.

A thin async streaming interface over OpenAI, Anthropic, Google Gemini and
OpenRouter so the orchestration layer is provider-agnostic.
"""
from __future__ import annotations

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

    async def synthesize(self, text, voice=None):
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
    """Groq is OpenAI-compatible; chat only (no embeddings)."""

    name = "groq"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        super().__init__(
            api_key=api_key or settings.GROQ_API_KEY,
            base_url=base_url or settings.GROQ_BASE_URL,
        )
        self.default_model = settings.GROQ_MODEL

    async def embed(self, texts, model=None):
        raise ProviderError("Groq does not support embeddings")

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

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
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
    """Choose the provider used for embeddings (Groq has none)."""
    if settings.GEMINI_API_KEY:
        return GeminiProvider()
    if settings.OPENAI_API_KEY:
        return OpenAIProvider()
    if settings.OPENROUTER_API_KEY:
        return OpenRouterProvider()
    return default_provider()
