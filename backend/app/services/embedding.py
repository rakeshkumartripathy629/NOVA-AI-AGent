"""
Embedding service for long-term memory.

Provider selection is configurable via ``MEMORY_EMBEDDING_PROVIDER``:
  - ``auto``     -> use the best configured provider (Gemini, OpenAI, OpenRouter,
                    otherwise the local sentence-transformers model)
  - ``gemini``/``openai``/``local`` -> force a specific provider

Embedding/vector failures must NEVER break chat, so any provider error falls
back to a deterministic, dependency-free hashing embedder. Retrieval only needs
consistency between store-time and query-time vectors.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import List, Optional

from app.ai.providers import ProviderError, embedding_dimension, embedding_provider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("memory.embedding")

_HASH_DIMENSION = 512
_WORD_RE = re.compile(r"[a-z0-9]+")


def count_tokens(text: str) -> int:
    """Estimate token count (tiktoken when available, else heuristic)."""
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 4)


def hash_embed(text: str) -> List[float]:
    """Deterministic feature-hash embedding (word + 2-gram features)."""
    vec = [0.0] * _HASH_DIMENSION
    words = _WORD_RE.findall(text.lower())
    if not words:
        return vec
    features: List[str] = list(words)
    features += [f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1)]
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest, "little") % _HASH_DIMENSION
        sign = 1.0 if int.from_bytes(digest[:4], "little") % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


@lru_cache(maxsize=1)
def _provider_name() -> str:
    return (settings.MEMORY_EMBEDDING_PROVIDER or "auto").strip().lower()


def _select_embedder():
    """Return the configured async embed function or None (use hash fallback)."""
    name = _provider_name()
    if name in ("auto", "local", "gemini", "openai"):
        if name != "local":
            try:
                provider = embedding_provider()
                if name == "gemini" and provider.name != "gemini":
                    return None
                if name == "openai" and provider.name != "openai":
                    return None
                return provider.embed
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding provider selection failed: %s", exc)
        if name == "auto":
            # Try the local sentence-transformers model as a last resort.
            try:
                from app.ai.providers import LocalEmbeddingProvider

                provider = LocalEmbeddingProvider()
                return provider.embed
            except Exception:  # noqa: BLE001
                pass
    return None


class EmbeddingService:
    """Produces embedding vectors, with a safe local fallback."""

    def __init__(self) -> None:
        self._embed_fn = None

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Return normalized embedding vectors for ``texts``.

        Falls back to deterministic hashing when a real provider is unavailable
        or fails, so memory never blocks chat.
        """
        cleaned = [(t or "").strip() for t in texts]
        if self._embed_fn is None:
            self._embed_fn = _select_embedder()
        if self._embed_fn is not None:
            try:
                vectors = await self._embed_fn(cleaned)
                return [list(v) for v in vectors]
            except ProviderError as exc:
                logger.warning("Embedding provider unavailable (%s); using local hashing", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding failed (%s); using local hashing", exc)
            self._embed_fn = None  # stop retrying a broken provider
        return [hash_embed(t) for t in cleaned]

    def dimension(self) -> int:
        """Vector dimension for the active embedder."""
        if _provider_name() != "local" and _select_embedder() is not None:
            try:
                return embedding_dimension()
            except Exception:  # noqa: BLE001
                pass
        return _HASH_DIMENSION


embedding_service = EmbeddingService()
