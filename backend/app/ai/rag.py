"""
RAG pipeline: text chunking, embeddings and Qdrant retrieval.

Chunking and retrieval are powered by LangChain (RecursiveCharacterTextSplitter,
a custom Embeddings adapter and QdrantVectorStore) with a Postgres-backed
fallback when Qdrant is unreachable.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableLambda
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.ai.providers import embedding_dimension, embedding_provider
from app.core.config import settings
from app.core.logging import get_logger
from app.db.qdrant import (
    _payload_matches,
    _uses_postgres,
    collection_name,
    delete_points,
    ensure_collection,
    scroll_points,
    search_points,
    upsert_points,
)

logger = get_logger("ai.rag")

CHUNKS_COLLECTION = "chunks"


def _run_coro(coro) -> Any:
    """Run an async coroutine from synchronous code (thread-safe)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class AppEmbeddings(Embeddings):
    """LangChain Embeddings adapter backed by the app's embedding providers."""

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await embed_texts(list(texts))

    async def aembed_query(self, text: str) -> List[float]:
        vectors = await embed_texts([text])
        return vectors[0] if vectors else []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return _run_coro(self.aembed_documents(texts))

    def embed_query(self, text: str) -> List[float]:
        return _run_coro(self.aembed_query(text))


def chunk_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """Split text into overlapping chunks on paragraph/sentence boundaries.

    Delegates to LangChain's RecursiveCharacterTextSplitter, preferring
    paragraph, then sentence, then whitespace boundaries.
    """
    size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.RAG_CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        keep_separator=True,
    )
    return [c for c in splitter.split_text(text) if c]


async def _ensure_chunks_collection() -> None:
    """Ensure the chunks collection exists with the right vector size."""
    await ensure_collection(CHUNKS_COLLECTION, dimension=embedding_dimension())


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed texts in batches using a provider that supports embeddings."""
    if not texts:
        return []
    provider = embedding_provider()
    vectors: List[List[float]] = []
    for i in range(0, len(texts), settings.EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + settings.EMBEDDING_BATCH_SIZE]
        vectors.extend(await provider.embed(batch))
    return vectors


_QDRANT_CLIENT_CACHE: Dict[str, Any] = {}


def _build_langchain_store() -> QdrantVectorStore:
    """Build a LangChain QdrantVectorStore over the app's Qdrant client."""
    client = _QDRANT_CLIENT_CACHE.get("client")
    if client is None:
        client = QdrantClient(
            url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=5
        )
        _QDRANT_CLIENT_CACHE["client"] = client
    return QdrantVectorStore(
        client=client,
        collection_name=collection_name(CHUNKS_COLLECTION),
        embedding=AppEmbeddings(),
        content_payload_key="page_content",
        metadata_payload_key="metadata",
        validate_collection_config=False,
    )


def _langchain_filter(meta_filter: Dict[str, Any]) -> models.Filter:
    """Build a Qdrant Filter over LangChain's nested ``metadata.*`` keys."""
    must = []
    for key, value in meta_filter.items():
        if isinstance(value, list) and value:
            must.append(
                models.FieldCondition(
                    key=f"metadata.{key}",
                    match=models.MatchAny(any=[str(v) for v in value]),
                )
            )
        else:
            must.append(
                models.FieldCondition(
                    key=f"metadata.{key}",
                    match=models.MatchValue(value=str(value)),
                )
            )
    return models.Filter(must=must)


def _prepare_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize retrieval arguments into a LangChain search request."""
    filter_values: Dict[str, Any] = {
        "knowledge_base_id": [str(kid) for kid in args["knowledge_base_ids"]],
    }
    if args.get("organization_id"):
        filter_values["organization_id"] = str(args["organization_id"])
    return {
        "query": args["query"],
        "store": _build_langchain_store(),
        "filter": _langchain_filter(filter_values),
        "k": args.get("top_k") or settings.RAG_TOP_K,
        "threshold": args.get("score_threshold") or settings.RAG_SIMILARITY_THRESHOLD,
        "search_type": (settings.RAG_SEARCH_TYPE or "similarity").lower(),
    }


async def _run_search(req: Dict[str, Any]) -> Tuple[List[Any], float]:
    """Run similarity or MMR retrieval against the LangChain vector store.

    MMR returns Documents without scores, so thresholding is skipped there.
    """
    store: QdrantVectorStore = req["store"]
    if req["search_type"] == "mmr":
        docs = await store.amax_marginal_relevance_search(
            query=req["query"],
            k=req["k"],
            fetch_k=max(req["k"] * 3, 10),
            lambda_mult=settings.RAG_MMR_LAMBDA,
            filter=req["filter"],
        )
        return [(doc, 0.0) for doc in docs], -1.0
    results = await store.asimilarity_search_with_score(
        query=req["query"], k=req["k"], filter=req["filter"]
    )
    return results, req["threshold"]


def _filter_results(
    pair: Tuple[List[Tuple[Document, float]], float]
) -> List[Dict[str, Any]]:
    """Apply the score threshold and map LangChain results to plain dicts."""
    results, threshold = pair
    output = []
    for doc, score in results:
        if score < threshold:
            continue
        output.append(_doc_to_result(doc, score))
    return output


def _build_retrieval_chain():
    """Build the LangChain LCEL retrieval pipeline."""
    return (
        RunnableLambda(_prepare_search)
        | RunnableLambda(_run_search)
        | RunnableLambda(_filter_results)
    )


def _doc_to_result(doc: Document, score: float) -> Dict[str, Any]:
    """Convert a LangChain Document and score into the app's chunk result dict."""
    meta = doc.metadata or {}
    return {
        "chunk_id": meta.get("_id") or meta.get("chunk_id"),
        "document_id": meta.get("document_id"),
        "knowledge_base_id": meta.get("knowledge_base_id"),
        "title": meta.get("title", ""),
        "content": doc.page_content,
        "score": score,
        "source_type": meta.get("source_type", "text"),
    }


async def _retrieve_postgres(
    query: str,
    knowledge_base_ids: List[UUID],
    top_k: Optional[int],
    score_threshold: Optional[float],
    organization_id: Optional[UUID],
) -> List[Dict[str, Any]]:
    """Retrieve relevant chunks via the Postgres-backed vector store."""
    vectors = await embed_texts([query])
    if not vectors:
        return []

    payload_filter: Dict[str, Any] = {
        "knowledge_base_id": [str(kid) for kid in knowledge_base_ids],
    }
    if organization_id:
        payload_filter["organization_id"] = str(organization_id)

    results = await search_points(
        CHUNKS_COLLECTION,
        vector=vectors[0],
        top_k=top_k or settings.RAG_TOP_K,
        score_threshold=score_threshold or settings.RAG_SIMILARITY_THRESHOLD,
        payload_filter=payload_filter,
    )

    output = []
    for r in results:
        payload = _flatten_payload(r.get("payload") or {})
        output.append(
            {
                "chunk_id": r.get("id"),
                "document_id": payload.get("document_id"),
                "knowledge_base_id": payload.get("knowledge_base_id"),
                "title": payload.get("title", ""),
                "content": payload.get("content", ""),
                "score": r["score"],
                "source_type": payload.get("source_type", "text"),
            }
        )
    return output


async def retrieve(
    query: str,
    knowledge_base_ids: List[UUID],
    top_k: Optional[int] = None,
    score_threshold: Optional[float] = None,
    organization_id: Optional[UUID] = None,
) -> List[Dict[str, Any]]:
    """Retrieve relevant chunks from the vector store.

    Uses a LangChain LCEL chain over QdrantVectorStore when Qdrant is
    reachable and falls back to the Postgres-backed store otherwise.
    """
    if not knowledge_base_ids:
        return []
    await _ensure_chunks_collection()

    if await _uses_postgres():
        logger.info("RAG retrieve: using Postgres fallback (Qdrant unreachable)")
        return await _retrieve_postgres(
            query, knowledge_base_ids, top_k, score_threshold, organization_id
        )

    logger.info("RAG retrieve: using LangChain QdrantVectorStore (search_type=%s)", settings.RAG_SEARCH_TYPE)

    chain = _build_retrieval_chain()
    return await chain.ainvoke(
        {
            "query": query,
            "knowledge_base_ids": knowledge_base_ids,
            "top_k": top_k,
            "score_threshold": score_threshold,
            "organization_id": organization_id,
        }
    )


def _flatten_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LangChain (page_content + metadata) payloads to flat keys."""
    payload = dict(payload or {})
    metadata = payload.pop("metadata", None)
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            payload.setdefault(key, value)
    if "page_content" in payload and "content" not in payload:
        payload["content"] = payload["page_content"]
    return payload


async def _scroll_chunks(
    filter_payload: Optional[Dict[str, Any]] = None,
    limit: int = 100000,
) -> List[Dict[str, Any]]:
    """Scroll chunks, normalizing LangChain nested metadata payloads."""
    points = await scroll_points(CHUNKS_COLLECTION, limit=limit)
    out = []
    for point in points:
        payload = _flatten_payload(point.get("payload") or {})
        if _payload_matches(payload, filter_payload):
            out.append({"id": point["id"], "payload": payload})
    return out


async def delete_document_chunks(document_id: UUID) -> None:
    """Remove all vector chunks for a document."""
    docs = await _scroll_chunks({"document_id": str(document_id)})
    ids = [d["id"] for d in docs]
    if ids:
        await delete_points(CHUNKS_COLLECTION, ids)


async def recompute_kb_index(knowledge_base_id: UUID) -> None:
    """After a document is indexed, keep the KB chunk count up to date.

    Best-effort: indexing should still succeed if the count refresh fails.
    """
    from datetime import datetime

    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models.knowledge_base import KnowledgeBase

    docs = await _scroll_chunks({"knowledge_base_id": str(knowledge_base_id)})
    try:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
            )
            kb = result.scalar_one_or_none()
            if kb:
                kb.total_chunks = len(docs)
                kb.last_indexed_at = datetime.utcnow()
                await db.commit()
    except Exception:
        logger.warning(
            "Failed to refresh chunk count for KB %s", knowledge_base_id, exc_info=True
        )


async def index_document(
    *,
    knowledge_base_id: UUID,
    document_id: UUID,
    title: str,
    content: str,
    source_type: str = "text",
    organization_id: Optional[UUID] = None,
) -> int:
    """Chunk, embed and upsert a document into the vector store.

    Indexing goes through LangChain's QdrantVectorStore when Qdrant is
    reachable and falls back to the Postgres-backed store otherwise.
    """
    chunks = chunk_text(content)
    if not chunks:
        logger.info("Document %s has no indexable content", document_id)
        return 0

    await _ensure_chunks_collection()

    metadatas = [
        {
            "knowledge_base_id": str(knowledge_base_id),
            "document_id": str(document_id),
            "organization_id": str(organization_id) if organization_id else None,
            "title": title,
            "source_type": source_type,
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]
    point_ids = [
        hashlib.md5(f"{document_id}:{i}".encode()).hexdigest()
        for i in range(len(chunks))
    ]

    if await _uses_postgres():
        logger.info("RAG index: using Postgres fallback (Qdrant unreachable)")
        vectors = await embed_texts(chunks)
        points = [
            {
                "id": point_id,
                "vector": vector,
                "payload": {**metadatas[i], "content": chunk},
            }
            for i, (point_id, vector, chunk) in enumerate(
                zip(point_ids, vectors, chunks)
            )
        ]
        await upsert_points(CHUNKS_COLLECTION, points)
    else:
        logger.info("RAG index: using LangChain QdrantVectorStore (%d chunks)", len(chunks))
        store = _build_langchain_store()
        await store.aadd_texts(texts=chunks, metadatas=metadatas, ids=point_ids)

    await recompute_kb_index(knowledge_base_id)
    return len(chunks)


def format_rag_context(chunks: List[Dict[str, Any]]) -> str:
    """Format retrieved chunks as a context block for the LLM."""
    if not chunks:
        return ""
    blocks = []
    for c in chunks:
        doc = c.get("title", "") or ""
        blocks.append(f"[{c.get('index', '?')}] {doc}: {c.get('content', '')}")
    return "\n\n".join(blocks)
