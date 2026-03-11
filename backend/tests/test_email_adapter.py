from __future__ import annotations

import json
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.source_item import SourceItem
from app.models.scan_state import ScanState
from app.adapters.email import (
    _decode_header_value,
    _extract_body,
    _parse_email_message,
    fetch_emails,
    sync_emails,
    get_emails,
    search_emails,
)


def _make_test_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_decode_header_value_plain():
    result = _decode_header_value("Hello World")
    assert result == "Hello World"


def test_decode_header_value_none():
    result = _decode_header_value(None)
    assert result == ""


def test_decode_header_value_encoded():
    result = _decode_header_value("=?UTF-8?B?SGVsbG8gV29ybGQ=?=")
    assert result == "Hello World"


def test_extract_body_plain_text():
    msg = EmailMessage()
    msg.set_content("Plain text body")
    result = _extract_body(msg)
    assert "Plain text body" in result


def test_extract_body_multipart():
    msg = EmailMessage()
    msg.set_content("Plain part")
    msg.add_alternative("<html><body>HTML part</body></html>", subtype="html")
    result = _extract_body(msg)
    assert "Plain part" in result


def test_parse_email_message():
    msg = EmailMessage()
    msg["Message-ID"] = "<test-123@example.com>"
    msg["Subject"] = "Test Subject"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Mon, 10 Mar 2026 15:00:00 +0000"
    msg.set_content("Email body text")
    result = _parse_email_message(1, msg)
    assert result is not None
    assert result["message_id"] == "<test-123@example.com>"
    assert result["subject"] == "Test Subject"
    assert result["from"] == "sender@example.com"
    assert "2026-03-10" in result["date"]
    assert "Email body text" in result["body"]


def test_parse_email_message_no_message_id():
    msg = EmailMessage()
    msg["Subject"] = "No ID"
    msg["From"] = "sender@example.com"
    msg["Date"] = "Mon, 10 Mar 2026 15:00:00 +0000"
    msg.set_content("body")
    result = _parse_email_message(42, msg)
    assert result is not None
    assert result["message_id"] == "42"


def test_fetch_emails():
    mock_client = MagicMock()
    mock_client.search.return_value = [1, 2]

    msg1 = EmailMessage()
    msg1["Message-ID"] = "<msg1@test>"
    msg1["Subject"] = "First"
    msg1["From"] = "a@test.com"
    msg1["Date"] = "Mon, 10 Mar 2026 15:00:00 +0000"
    msg1.set_content("body1")

    msg2 = EmailMessage()
    msg2["Message-ID"] = "<msg2@test>"
    msg2["Subject"] = "Second"
    msg2["From"] = "b@test.com"
    msg2["Date"] = "Mon, 10 Mar 2026 16:00:00 +0000"
    msg2.set_content("body2")

    mock_client.fetch.return_value = {
        2: {b"RFC822": msg2.as_bytes()},
        1: {b"RFC822": msg1.as_bytes()},
    }

    with patch("app.adapters.email._get_imap_client", return_value=mock_client):
        result = fetch_emails(folder="INBOX", limit=10)

    assert len(result) == 2
    assert result[0]["subject"] == "Second"
    assert result[1]["subject"] == "First"
    assert "imap_uid" in result[0]
    assert "imap_uid" in result[1]
    assert mock_client.logout.called


def test_sync_emails_creates_source_items():
    session = _make_test_session()
    fake_emails = [
        {
            "message_id": "<msg-1@test>",
            "subject": "Important Email",
            "from": "sender@test.com",
            "to": "me@test.com",
            "cc": "",
            "date": "2026-03-10T15:00:00+00:00",
            "body": "Hello from email",
            "imap_uid": 100,
        }
    ]
    with patch("app.adapters.email.fetch_emails", return_value=fake_emails):
        count, changed_ids = sync_emails(session)
    assert count == 1
    assert len(changed_ids) == 1
    items = list(session.exec(select(SourceItem).where(SourceItem.source_type == "email")).all())
    assert len(items) == 1
    assert items[0].title == "Important Email"
    assert items[0].external_id == "<msg-1@test>"
    assert items[0].content == "Hello from email"
    scan = session.exec(select(ScanState).where(ScanState.source_type == "email")).first()
    assert scan.status == "idle"
    assert scan.items_synced == 1
    assert scan.last_cursor == "100"


def test_sync_emails_updates_existing():
    session = _make_test_session()
    existing = SourceItem(
        source_type="email",
        external_id="<msg-1@test>",
        title="Old Subject",
        content="old body",
        raw_metadata="{}",
    )
    session.add(existing)
    session.commit()
    fake_emails = [
        {
            "message_id": "<msg-1@test>",
            "subject": "New Subject",
            "from": "sender@test.com",
            "to": "me@test.com",
            "cc": "",
            "date": "2026-03-10T15:00:00+00:00",
            "body": "new body",
            "imap_uid": 100,
        }
    ]
    with patch("app.adapters.email.fetch_emails", return_value=fake_emails):
        count, changed_ids = sync_emails(session)
    items = list(session.exec(select(SourceItem).where(SourceItem.source_type == "email")).all())
    assert len(items) == 1
    assert items[0].title == "New Subject"
    assert items[0].content == "new body"


def test_sync_emails_error_updates_scan_state():
    session = _make_test_session()
    with patch("app.adapters.email.fetch_emails", side_effect=ConnectionError("IMAP connection refused")):
        with pytest.raises(ConnectionError):
            sync_emails(session)
    scan = session.exec(select(ScanState).where(ScanState.source_type == "email")).first()
    assert scan.status == "error"
    assert "IMAP connection refused" in scan.error_message


def test_get_emails():
    session = _make_test_session()
    session.add(SourceItem(source_type="email", external_id="e1", title="Email 1", content="body1", raw_metadata="{}"))
    session.add(SourceItem(source_type="email", external_id="e2", title="Email 2", content="body2", raw_metadata="{}"))
    session.commit()
    result = get_emails(session)
    assert len(result) == 2


def test_search_emails():
    session = _make_test_session()
    session.add(SourceItem(source_type="email", external_id="e1", title="Invoice from Acme", content="Please pay $100", raw_metadata="{}"))
    session.add(SourceItem(source_type="email", external_id="e2", title="Meeting Tomorrow", content="Let's discuss the project", raw_metadata="{}"))
    session.commit()
    result = search_emails(session, query="invoice")
    assert len(result) == 1
    assert result[0].external_id == "e1"
    result = search_emails(session, query="project")
    assert len(result) == 1
    assert result[0].external_id == "e2"


def test_sync_emails_skips_unchanged():
    session = _make_test_session()
    fake_emails = [
        {
            "message_id": "<msg-1@test>",
            "subject": "Important Email",
            "from": "sender@test.com",
            "to": "me@test.com",
            "cc": "",
            "date": "2026-03-10T15:00:00+00:00",
            "body": "Hello from email",
            "imap_uid": 100,
        }
    ]

    with patch("app.adapters.email.fetch_emails", return_value=fake_emails):
        count1, changed_ids1 = sync_emails(session)

    assert count1 == 1
    assert len(changed_ids1) == 1

    with patch("app.adapters.email.fetch_emails", return_value=fake_emails):
        count2, changed_ids2 = sync_emails(session)

    assert count2 == 1
    assert len(changed_ids2) == 0


def test_sync_emails_uses_uid_cursor():
    session = _make_test_session()
    fake_emails = [
        {
            "message_id": "<msg-1@test>",
            "subject": "Email",
            "from": "a@test.com",
            "to": "b@test.com",
            "cc": "",
            "date": "2026-03-10T15:00:00+00:00",
            "body": "body",
            "imap_uid": 50,
        }
    ]

    with patch("app.adapters.email.fetch_emails", return_value=fake_emails):
        sync_emails(session)

    scan = session.exec(select(ScanState).where(ScanState.source_type == "email")).first()
    assert scan.last_cursor == "50"

    with patch("app.adapters.email.fetch_emails", return_value=[]) as mock_fetch:
        count, changed_ids = sync_emails(session)

    mock_fetch.assert_called_once_with(folder="INBOX", limit=50, since_uid=50)
    assert count == 0
