from __future__ import annotations

import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.models.conversation import Conversation
from app.models.fact import Fact
from app.models.source_item import SourceItem
from app.models.scan_state import ScanState


def _make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_conversation_create() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        conv = Conversation(role="user", content="Hello", conversation_id="conv-1")
        session.add(conv)
        session.commit()
        session.refresh(conv)
        assert conv.id is not None
        assert conv.role == "user"
        assert conv.content == "Hello"
        assert conv.conversation_id == "conv-1"
        assert conv.created_at is not None


def test_fact_create() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        fact = Fact(category="contact", subject="John", content="John's email is john@example.com")
        session.add(fact)
        session.commit()
        session.refresh(fact)
        assert fact.id is not None
        assert fact.category == "contact"
        assert fact.subject == "John"
        assert fact.active is True
        assert fact.confidence == 1.0


def test_source_item_create() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        item = SourceItem(source_type="email", external_id="uid-123", title="Test Email", content="Body text")
        session.add(item)
        session.commit()
        session.refresh(item)
        assert item.id is not None
        assert item.source_type == "email"
        assert item.external_id == "uid-123"
        assert item.raw_metadata == "{}"


def test_scan_state_create() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        state = ScanState(source_type="email")
        session.add(state)
        session.commit()
        session.refresh(state)
        assert state.id is not None
        assert state.source_type == "email"
        assert state.status == "idle"
        assert state.last_synced_at is None
        assert state.items_synced == 0


def test_scan_state_unique_source_type() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        state1 = ScanState(source_type="email")
        session.add(state1)
        session.commit()
        state2 = ScanState(source_type="email")
        session.add(state2)
        with pytest.raises(Exception):
            session.commit()
