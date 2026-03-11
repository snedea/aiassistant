from __future__ import annotations

import json
from app.models.source_item import SourceItem


def test_compute_hash_deterministic() -> None:
    h1 = SourceItem.compute_hash("title", "content", "{}")
    h2 = SourceItem.compute_hash("title", "content", "{}")
    assert h1 == h2


def test_compute_hash_differs_on_content_change() -> None:
    h1 = SourceItem.compute_hash("title", "a", "{}")
    h2 = SourceItem.compute_hash("title", "b", "{}")
    assert h1 != h2


def test_compute_hash_differs_on_metadata_change() -> None:
    h1 = SourceItem.compute_hash("title", "content", '{"k":"v1"}')
    h2 = SourceItem.compute_hash("title", "content", '{"k":"v2"}')
    assert h1 != h2


def test_compute_hash_empty_inputs() -> None:
    h = SourceItem.compute_hash("", "", "")
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)
