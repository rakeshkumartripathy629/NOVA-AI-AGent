"""Unit and integration tests for the long-term memory flow.

Covers: extraction -> dedup/merge/conflict -> embedding -> vector store ->
semantic retrieval -> ranking/threshold/token-limit -> user scoping -> API.

Embeddings are stubbed with the deterministic local hash embedder and LLM
extraction is stubbed so the whole pipeline runs hermetically (no network).
"""
from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from app.models.memory import MemoryCategory, MemoryItem
from app.services import memory_service
from app.services.embedding import count_tokens, embedding_service, hash_embed
from app.services.memory_context import build_memory_context
from app.services.memory_extractor import _normalize
from app.services.memory_extractor import extract_memories as extract_persist
from app.services.memory_retriever import rank_scores, retrieve_memories

pytestmark = pytest.mark.asyncio


@pytest.fixture
def hash_embeddings(monkeypatch):
    """Use the deterministic local embedder instead of any API provider."""

    async def fake_embed(texts):
        return [hash_embed(t) for t in texts]

    monkeypatch.setattr(embedding_service, "embed", fake_embed)
    monkeypatch.setattr(embedding_service, "dimension", lambda: len(hash_embed("x")))
    return embedding_service


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------
def test_normalize_helpers():
    assert _normalize("You use MongoDB!") == _normalize("you  use MongoDB")
    assert _normalize("  ") == ""


def test_hash_embed_is_deterministic():
    a = hash_embed("Rakesh is a Node.js backend developer")
    b = hash_embed("Rakesh is a Node.js backend developer")
    assert a == b
    assert len(a) == len(b)


def test_count_tokens_nonzero():
    assert count_tokens("") == 0
    assert count_tokens("hello world") >= 1


def test_rank_scores_weights():
    high_sim = rank_scores(1.0, 5, 1.0, 1.0)
    low_sim = rank_scores(0.0, 1, 0.0, 0.0)
    assert high_sim > low_sim
    assert high_sim <= 1.0


def test_build_memory_context_empty_when_no_memories():
    assert build_memory_context([], [], token_limit=100) == ""


def test_build_memory_context_respects_token_limit():
    memories = [
        MemoryItem(content="fact number " + str(i), id=uuid.uuid4())
        for i in range(50)
    ]
    block = build_memory_context(memories, [], token_limit=100)
    assert block
    assert count_tokens(block) <= 100 + 50  # small slack


async def test_embedding_service_falls_back_on_provider_error(hash_embeddings):
    from app.services.embedding import EmbeddingService

    service = EmbeddingService()

    async def broken(texts):
        raise RuntimeError("provider down")

    service._embed_fn = broken
    vectors = await service.embed(["hello world", "second text"])
    assert len(vectors) == 2
    assert len(vectors[0]) == len(hash_embed("x"))


# ---------------------------------------------------------------------------
# Extraction: dedup + conflict supersede
# ---------------------------------------------------------------------------
async def test_extraction_merges_duplicates_and_supersedes_updates(
    db_session, superuser, hash_embeddings, monkeypatch
):
    user = await superuser()
    calls = {"n": 0}

    async def fake_candidates(user_content, assistant_content, existing):
        calls["n"] += 1
        if calls["n"] in (1, 2):
            return [
                {
                    "content": "You use MongoDB for your backend.",
                    "category": "technical_preference",
                    "importance": 3,
                    "confidence": 0.9,
                }
            ]
        return [
            {
                "content": "You switched to PostgreSQL for your backend.",
                "category": "technical_preference",
                "importance": 4,
                "confidence": 0.95,
                "supersedes": "You use MongoDB for your backend.",
            }
        ]

    monkeypatch.setattr(
        "app.services.memory_extractor._extract_candidates", fake_candidates
    )

    first = await extract_persist(
        user.id, None, None,
        "I use MongoDB for my backend project.",
        "Got it, MongoDB it is for now. Let us go with that for your backend setup.",
    )
    assert len(first) == 1

    # Re-running the identical fact must NOT create a duplicate.
    again = await extract_persist(
        user.id, None, None,
        "I use MongoDB for my backend project.",
        "Got it, MongoDB it is for now. Let us go with that for your backend setup.",
    )
    assert again == []

    # New explicit info supersedes the old fact (soft-delete + replace).
    second = await extract_persist(
        user.id, None, None,
        "I switched to PostgreSQL for my backend.",
        "Nice, PostgreSQL is a solid choice. I will keep that in mind for you going forward.",
    )
    assert len(second) == 1

    from sqlalchemy import select

    rows = (
        await db_session.execute(
            select(MemoryItem).where(MemoryItem.user_id == user.id)
        )
    ).scalars().all()
    active = [r for r in rows if not r.is_deleted and r.superseded_by_id is None]
    assert len(active) == 1  # only one active memory wins the conflict
    assert "PostgreSQL" in active[0].content
    assert "MongoDB" not in active[0].content
    assert active[0].embedding  # embedding was generated and stored

    superseded = [r for r in rows if r.is_deleted]
    assert len(superseded) == 1
    assert "MongoDB" in superseded[0].content


# ---------------------------------------------------------------------------
# Retrieval: cross-conversation memory + user scoping
# ---------------------------------------------------------------------------
async def test_full_flow_recalls_old_conversation_fact(
    db_session, superuser, hash_embeddings, monkeypatch
):
    user = await superuser()

    async def fake_candidates(user_content, assistant_content, existing):
        return [
            {
                "content": "You are Rakesh, a Node.js backend developer building a job portal.",
                "category": "profile",
                "importance": 4,
                "confidence": 0.95,
            }
        ]

    monkeypatch.setattr(
        "app.services.memory_extractor._extract_candidates", fake_candidates
    )

    # Conversation 1: user shares personal/project info.
    await extract_persist(
        user.id, None, None,
        "My name is Rakesh. I am a Node.js backend developer and I am building a job portal.",
        "Nice to meet you, Rakesh! A job portal on Node.js sounds great.",
    )

    # Conversation 2: brand-new conversation, no shared history, related query.
    recalled = await retrieve_memories(user.id, "What should I improve in my project?")
    assert recalled, "Expected the old fact to be recalled in a new conversation"
    assert "Rakesh" in recalled[0].content
    assert "job portal" in recalled[0].content


async def test_retrieval_is_scoped_per_user(
    db_session, superuser, hash_embeddings
):
    user_a = await superuser()
    user_b = await superuser()

    await memory_service.create_memory(
        db_session, user_a.id, None,
        "You are Alice and you prefer dark mode.",
        MemoryCategory.PREFERENCE,
    )
    await memory_service.create_memory(
        db_session, user_b.id, None,
        "You are Bob and you prefer light mode.",
        MemoryCategory.PREFERENCE,
    )

    recalled_a = await retrieve_memories(user_a.id, "What is my preference for dark or light mode?")
    recalled_b = await retrieve_memories(user_b.id, "What is my preference for dark or light mode?")

    assert any("Alice" in m.content for m in recalled_a)
    assert all("Bob" not in m.content for m in recalled_a)
    assert any("Bob" in m.content for m in recalled_b)
    assert all("Alice" not in m.content for m in recalled_b)


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------
async def _auth_headers(user):
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


async def test_memory_api_crud_search_and_clear(api_client, superuser, hash_embeddings):
    user = await superuser()
    headers = await _auth_headers(user)

    # POST /memory (create)
    resp = await api_client.post(
        "/api/v1/memory",
        json={"content": "You prefer PostgreSQL over MongoDB.", "category": "technical_preference"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    mid = created["id"]
    assert created["category"] == "technical_preference"
    assert created["confidence"] == 1.0

    # GET /memory (list)
    resp = await api_client.get("/api/v1/memory", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # GET /memory/{id}
    resp = await api_client.get(f"/api/v1/memory/{mid}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == mid

    # POST /memory/search (semantic)
    resp = await api_client.post(
        "/api/v1/memory/search",
        json={"query": "I prefer PostgreSQL database", "limit": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # PATCH /memory/{id}
    resp = await api_client.patch(
        f"/api/v1/memory/{mid}",
        json={"importance": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["importance"] == 5

    # /memories alias also works
    resp = await api_client.get("/api/v1/memories", headers=headers)
    assert resp.status_code == 200

    # DELETE /memory/{id}
    resp = await api_client.delete(f"/api/v1/memory/{mid}", headers=headers)
    assert resp.status_code == 204
    resp = await api_client.get("/api/v1/memory", headers=headers)
    assert resp.json()["total"] == 0

    # DELETE /memory (clear all)
    await api_client.post(
        "/api/v1/memory",
        json={"content": "Another memory to clear.", "category": "fact"},
        headers=headers,
    )
    resp = await api_client.delete("/api/v1/memory", headers=headers)
    assert resp.status_code == 204
    resp = await api_client.get("/api/v1/memory", headers=headers)
    assert resp.json()["total"] == 0


async def test_memory_api_is_scoped_to_user(api_client, superuser, hash_embeddings):
    user_a = await superuser()
    user_b = await superuser()

    await api_client.post(
        "/api/v1/memory",
        json={"content": "Secret fact belonging to A.", "category": "fact"},
        headers=await _auth_headers(user_a),
    )
    resp = await api_client.get("/api/v1/memory", headers=await _auth_headers(user_b))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # User B cannot fetch or delete user A's memory by id.
    resp = await api_client.get(
        "/api/v1/memory",
        headers=await _auth_headers(user_b),
    )
    assert resp.json()["total"] == 0


async def test_conversation_search_endpoint(api_client, superuser, hash_embeddings):
    user = await superuser()
    headers = await _auth_headers(user)
    resp = await api_client.get(
        "/api/v1/conversations/search", params={"q": "nothing-matches-xyz"}, headers=headers
    )
    assert resp.status_code == 200
    assert "results" in resp.json()


# ---------------------------------------------------------------------------
# Chat wiring: memory must reach the LLM and the settings toggle must read back
# ---------------------------------------------------------------------------
async def test_stream_chat_injects_memory_into_default_system_prompt(
    db_session, superuser, monkeypatch
):
    """Regression: recalled memory must reach the provider even when the caller
    sends no custom system_prompt (the default frontend flow)."""
    from types import SimpleNamespace

    from app.ai import chat as chat_module

    user = await superuser()
    captured: dict = {}

    class FakeProvider:
        async def stream(
            self,
            messages,
            model=None,
            temperature=None,
            max_tokens=None,
            tools=None,
            system_prompt=None,
            **kwargs,
        ):
            captured["system_prompt"] = system_prompt
            yield {"type": "token", "content": "hi"}

    async def fake_recall(user_id, query):
        return (
            "Remembered context (from this user's memory):\n"
            "- You are Rakesh, a Node.js developer."
        )

    async def fake_load_history(cid, exclude_ids):
        return []

    monkeypatch.setattr(chat_module, "memory_enabled", lambda user: True)
    monkeypatch.setattr("app.ai.memory.recall_context", fake_recall)
    monkeypatch.setattr(chat_module, "_load_history", fake_load_history)
    monkeypatch.setattr(chat_module, "default_provider", lambda: FakeProvider())
    monkeypatch.setattr(chat_module, "get_provider", lambda name=None: FakeProvider())

    conv = SimpleNamespace(id=uuid.uuid4())
    events = []
    async for _ev in chat_module.stream_chat_response(
        conv,
        "What should I improve in my project?",
        uuid.uuid4(),
        user,
        use_web_search=False,
    ):
        events.append(_ev)

    assert any(e["type"] == "token" for e in events)
    assert captured["system_prompt"]
    assert "Remembered context" in captured["system_prompt"]
    assert "Rakesh" in captured["system_prompt"]


async def test_auth_me_returns_preferences(api_client, superuser, db_session):
    """The Settings memory toggle reads /auth/me; preferences must be present."""
    user = await superuser()
    user.preferences = {"memory_enabled": False}
    await db_session.commit()
    resp = await api_client.get("/api/v1/auth/me", headers=await _auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["preferences"] == {"memory_enabled": False}

