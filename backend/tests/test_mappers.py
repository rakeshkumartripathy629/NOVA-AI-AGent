"""Verifies all SQLAlchemy relationships configure cleanly (no ambiguous FK errors)."""
from __future__ import annotations

from sqlalchemy.orm import configure_mappers


def test_configure_mappers_ok():
    configure_mappers()


def test_all_tables_registered():
    from app.models import Base

    table_names = set(Base.metadata.tables.keys())
    for expected in (
        "users",
        "organizations",
        "projects",
        "conversations",
        "conversation_branches",
        "messages",
        "files",
        "knowledge_bases",
        "agents",
        "workflows",
        "subscriptions",
        "webhooks",
        "usage_records",
        "audit_logs",
        "notifications",
    ):
        assert expected in table_names, f"missing table {expected}"
