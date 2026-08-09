"""Tests for the LangChain-backed RAG pipeline."""
from __future__ import annotations

from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.ai import rag
from app.core.config import settings

HIGH_SCORE = 0.8
TWO_FILTERS = 2
TOP_K = 5


async def _noop() -> None:
    return None


async def _uses_false() -> bool:
    return False


class _FakeKB:
    def __init__(self):
        self.total_chunks = 0
        self.last_indexed_at = None


class _FakeDB:
    def __init__(self, kb):
        self._kb = kb
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        return self

    def scalar_one_or_none(self):
        return self._kb

    async def commit(self):
        self.committed = True


async def _fake_scroll(filter_payload=None, limit=100000):
    return [{"id": "1"}, {"id": "2"}]


class _FakeStore:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def asimilarity_search_with_score(self, query, k=4, filter=None):
        self.calls.append(("similarity", query, k, filter))
        return self.results

    async def amax_marginal_relevance_search(
        self, query, k=4, fetch_k=20, lambda_mult=0.5, filter=None
    ):
        self.calls.append(("mmr", query, k, filter))
        return [doc for doc, _ in self.results]


def _sample_docs():
    return [
        (
            Document(
                page_content="relevant chunk",
                metadata={
                    "_id": "p1",
                    "document_id": "doc-1",
                    "knowledge_base_id": "kb-1",
                    "title": "Docs",
                    "source_type": "pdf",
                },
            ),
            0.9,
        ),
        (
            Document(
                page_content="irrelevant chunk",
                metadata={
                    "_id": "p2",
                    "document_id": "doc-1",
                    "knowledge_base_id": "kb-1",
                    "title": "Docs",
                    "source_type": "pdf",
                },
            ),
            0.1,
        ),
    ]


async def test_app_embeddings_async(monkeypatch):
    async def fake_embed_texts(texts):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(rag, "embed_texts", fake_embed_texts)
    embeddings = rag.AppEmbeddings()
    assert await embeddings.aembed_query("hello") == [1.0, 0.0]
    assert await embeddings.aembed_documents(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]


async def test_app_embeddings_sync_from_event_loop(monkeypatch):
    async def fake_embed_texts(texts):
        return [[0.5, 0.5] for _ in texts]

    monkeypatch.setattr(rag, "embed_texts", fake_embed_texts)
    embeddings = rag.AppEmbeddings()
    assert embeddings.embed_query("hello") == [0.5, 0.5]
    assert embeddings.embed_documents(["a"]) == [[0.5, 0.5]]


def test_doc_to_result_maps_metadata():
    doc = Document(
        page_content="some chunk",
        metadata={
            "_id": "point-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "title": "Notes",
            "source_type": "pdf",
        },
    )
    result = rag._doc_to_result(doc, HIGH_SCORE)
    assert result["chunk_id"] == "point-1"
    assert result["document_id"] == "doc-1"
    assert result["knowledge_base_id"] == "kb-1"
    assert result["title"] == "Notes"
    assert result["content"] == "some chunk"
    assert result["score"] == HIGH_SCORE
    assert result["source_type"] == "pdf"


def test_flatten_payload_normalizes_nested_metadata():
    payload = {
        "page_content": "text",
        "metadata": {"document_id": "d1", "title": "T"},
    }
    flat = rag._flatten_payload(payload)
    assert flat["content"] == "text"
    assert flat["document_id"] == "d1"
    assert flat["title"] == "T"


def test_langchain_filter_uses_nested_metadata_keys():
    qfilter = rag._langchain_filter(
        {"knowledge_base_id": ["kb-1", "kb-2"], "organization_id": "org-1"}
    )
    assert len(qfilter.must) == TWO_FILTERS
    kb_cond = next(c for c in qfilter.must if "knowledge_base_id" in c.key)
    assert kb_cond.key == "metadata.knowledge_base_id"
    assert kb_cond.match.any == ["kb-1", "kb-2"]
    org_cond = next(c for c in qfilter.must if "organization_id" in c.key)
    assert org_cond.key == "metadata.organization_id"
    assert org_cond.match.value == "org-1"


async def test_retrieve_uses_langchain_chain_and_threshold(monkeypatch):
    store = _FakeStore(_sample_docs())
    monkeypatch.setattr(rag, "_ensure_chunks_collection", _noop)
    monkeypatch.setattr(rag, "_uses_postgres", _uses_false)
    monkeypatch.setattr(rag, "_build_langchain_store", lambda: store)

    result = await rag.retrieve(
        query="anything",
        knowledge_base_ids=[uuid4()],
        top_k=5,
        score_threshold=0.5,
    )

    assert len(result) == 1
    assert result[0]["chunk_id"] == "p1"
    assert result[0]["content"] == "relevant chunk"
    assert store.calls[0][0] == "similarity"
    assert store.calls[0][2] == TOP_K
    assert store.calls[0][3].must[0].key == "metadata.knowledge_base_id"


async def test_retrieve_mmr_skips_threshold(monkeypatch):
    store = _FakeStore(_sample_docs())
    monkeypatch.setattr(rag, "_ensure_chunks_collection", _noop)
    monkeypatch.setattr(rag, "_uses_postgres", _uses_false)
    monkeypatch.setattr(rag, "_build_langchain_store", lambda: store)
    monkeypatch.setattr(settings, "RAG_SEARCH_TYPE", "mmr")

    result = await rag.retrieve(query="q", knowledge_base_ids=[uuid4()], top_k=TOP_K)

    assert len(result) == TWO_FILTERS
    assert store.calls[0][0] == "mmr"


async def test_recompute_kb_index_updates_kb_count(monkeypatch):
    kb = _FakeKB()
    monkeypatch.setattr(rag, "_scroll_chunks", _fake_scroll)
    monkeypatch.setattr(
        "app.db.session.get_session_factory", lambda: lambda: _FakeDB(kb)
    )

    await rag.recompute_kb_index(uuid4())

    assert kb.total_chunks == TWO_FILTERS
    assert kb.last_indexed_at is not None


class _FakeEmbeddings(Embeddings):
    """Deterministic embeddings so cosine similarity is exact."""

    _VECTORS = {
        "alpha": [1.0, 0.0, 0.0, 0.0],
        "beta": [0.0, 1.0, 0.0, 0.0],
    }

    def embed_documents(self, texts):
        return [self._VECTORS.get(t, [1.0, 1.0, 0.0, 0.0]) for t in texts]

    def embed_query(self, text):
        return self._VECTORS.get(text, [1.0, 1.0, 0.0, 0.0])


def test_qdrant_vector_store_local_roundtrip(tmp_path):
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    client = QdrantClient(path=str(tmp_path / "qdrant"))
    client.create_collection(
        collection_name="chunks_test",
        vectors_config=qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE),
    )
    store = QdrantVectorStore(
        client=client,
        collection_name="chunks_test",
        embedding=_FakeEmbeddings(),
        validate_collection_config=False,
    )

    ids = store.add_texts(
        texts=["alpha", "beta"],
        metadatas=[
            {"knowledge_base_id": "kb-1", "title": "A"},
            {"knowledge_base_id": "kb-2", "title": "B"},
        ],
    )
    assert len(ids) == TWO_FILTERS

    results = store.similarity_search_with_score(
        "alpha", k=2, filter=rag._langchain_filter({"knowledge_base_id": ["kb-1"]})
    )
    assert len(results) == 1
    doc, score = results[0]
    assert doc.page_content == "alpha"
    assert doc.metadata["_id"] == ids[0]
    assert doc.metadata["knowledge_base_id"] == "kb-1"
    assert score > 0.5

    mapped = rag._doc_to_result(doc, score)
    assert mapped["chunk_id"] == ids[0]
    assert mapped["content"] == "alpha"

    mmr = store.max_marginal_relevance_search(
        "alpha",
        k=1,
        fetch_k=2,
        lambda_mult=0.7,
        filter=rag._langchain_filter({"knowledge_base_id": ["kb-1", "kb-2"]}),
    )
    assert len(mmr) == 1
    assert mmr[0].page_content == "alpha"
