from __future__ import annotations

import email
import email.header
import email.utils
import json
import logging
from datetime import datetime, timezone
from email.message import Message
from typing import Any

import imapclient
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.config import get_settings
from app.models.source_item import SourceItem
from app.models.scan_state import ScanState

logger = logging.getLogger(__name__)


def _get_imap_client() -> imapclient.IMAPClient:
    settings = get_settings()
    if settings.imap_host == "":
        raise ValueError("IMAP_HOST is not configured")
    client = imapclient.IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True)
    client.login(settings.imap_username, settings.imap_password)
    return client


def _decode_header_value(value: str | None) -> str:
    if value is None:
        return ""
    decoded = email.header.decode_header(value)
    parts: list[str] = []
    for data, charset in decoded:
        if isinstance(data, bytes) and charset is not None:
            parts.append(data.decode(charset, errors="replace"))
        elif isinstance(data, bytes):
            parts.append(data.decode("utf-8", errors="replace"))
        else:
            parts.append(data)
    return " ".join(parts)


def _extract_body(msg: Message) -> str:
    if msg.is_multipart():
        text_body = ""
        html_body = ""
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = part.get("Content-Disposition") or ""
            if disposition.startswith("attachment"):
                continue
            if content_type == "text/plain" and not text_body:
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    text_body = payload.decode(charset, errors="replace")
            elif content_type == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
        if text_body:
            return text_body.strip()
        if html_body:
            return html_body.strip()
        return ""
    else:
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace").strip()


def _parse_email_message(msg_uid: int, msg: Message) -> dict[str, Any] | None:
    message_id = msg.get("Message-ID", "")
    if message_id == "":
        message_id = str(msg_uid)
    subject = _decode_header_value(msg.get("Subject"))
    from_addr = _decode_header_value(msg.get("From"))
    to_addr = _decode_header_value(msg.get("To"))
    cc_addr = _decode_header_value(msg.get("Cc"))
    date_str = msg.get("Date", "")
    try:
        parsed_dt = email.utils.parsedate_to_datetime(date_str)
        date_parsed = parsed_dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        date_parsed = ""
    body = _extract_body(msg)
    body = body[:10000]
    return {
        "message_id": message_id.strip(),
        "subject": subject,
        "from": from_addr,
        "to": to_addr,
        "cc": cc_addr,
        "date": date_parsed,
        "body": body,
    }


def fetch_emails(folder: str = "INBOX", limit: int = 50, since_uid: int | None = None) -> list[dict[str, Any]]:
    client = _get_imap_client()
    try:
        client.select_folder(folder, readonly=True)
        if since_uid is not None:
            msg_uids = client.search(["UID", f"{since_uid + 1}:*"])
            msg_uids = [u for u in msg_uids if u > since_uid]
        else:
            msg_uids = client.search(["ALL"])
            msg_uids = sorted(msg_uids, reverse=True)
            msg_uids = msg_uids[:limit]
        if not msg_uids:
            return []
        raw_messages = client.fetch(msg_uids, ["BODY[]"])
        results: list[dict[str, Any]] = []
        for uid in msg_uids:
            raw_data = raw_messages.get(uid)
            if raw_data is None:
                continue
            try:
                raw_bytes = raw_data[b"BODY[]"]
                msg = email.message_from_bytes(raw_bytes)
                parsed = _parse_email_message(uid, msg)
                if parsed is not None:
                    parsed["imap_uid"] = uid
                    results.append(parsed)
            except Exception:
                logger.warning("Failed to parse email uid=%s", uid, exc_info=True)
                continue
        logger.info("Fetched %d emails from %s", len(results), folder)
        return results
    finally:
        client.logout()


def sync_emails(session: Session, folder: str = "INBOX", limit: int = 50) -> tuple[int, list[int]]:
    statement = select(ScanState).where(ScanState.source_type == "email")
    scan_state = session.exec(statement).first()
    if scan_state is None:
        scan_state = ScanState(source_type="email", status="idle")
        session.add(scan_state)

    scan_state.status = "syncing"
    scan_state.error_message = None
    session.commit()

    since_uid: int | None = None
    if scan_state.last_cursor is not None and scan_state.last_cursor != "":
        since_uid = int(scan_state.last_cursor)

    try:
        emails = fetch_emails(folder=folder, limit=limit, since_uid=since_uid)
        synced_count = 0
        new_items: list[SourceItem] = []
        updated_items: list[SourceItem] = []
        max_uid = since_uid or 0

        for email_data in emails:
            max_uid = max(max_uid, email_data["imap_uid"])
            external_id = email_data["message_id"]
            stmt = select(SourceItem).where(
                SourceItem.source_type == "email",
                SourceItem.external_id == external_id,
            )
            existing = session.exec(stmt).first()

            metadata_dict = {"from": email_data["from"], "to": email_data["to"], "cc": email_data["cc"], "date": email_data["date"]}
            metadata_json = json.dumps(metadata_dict)
            new_hash = SourceItem.compute_hash(email_data["subject"], email_data["body"], metadata_json)

            if existing is not None:
                if existing.content_hash == new_hash:
                    synced_count += 1
                    continue
                existing.title = email_data["subject"]
                existing.content = email_data["body"]
                existing.raw_metadata = metadata_json
                existing.updated_at = datetime.now(timezone.utc)
                existing.content_hash = new_hash
                existing.embedded = False
                session.add(existing)
                updated_items.append(existing)
            else:
                item = SourceItem(
                    source_type="email",
                    external_id=external_id,
                    title=email_data["subject"],
                    content=email_data["body"],
                    raw_metadata=metadata_json,
                    content_hash=new_hash,
                )
                session.add(item)
                new_items.append(item)

            synced_count += 1

        session.commit()
        changed_ids = [item.id for item in new_items] + [item.id for item in updated_items]

        total_in_db = session.exec(
            select(func.count(SourceItem.id)).where(SourceItem.source_type == "email")
        ).one()
        scan_state.status = "idle"
        scan_state.last_synced_at = datetime.now(timezone.utc)
        scan_state.items_synced = total_in_db
        if max_uid > 0:
            scan_state.last_cursor = str(max_uid)
        session.commit()

        logger.info("Email sync complete: %d emails synced, %d changed", synced_count, len(changed_ids))
        return (synced_count, changed_ids)

    except Exception as e:
        scan_state.status = "error"
        scan_state.error_message = str(e)[:500]
        session.commit()
        logger.error("Email sync failed: %s", e, exc_info=True)
        raise


def get_emails(session: Session, limit: int = 50) -> list[SourceItem]:
    stmt = select(SourceItem).where(SourceItem.source_type == "email")
    stmt = stmt.order_by(SourceItem.updated_at.desc()).limit(limit)
    return list(session.exec(stmt).all())


def search_emails(session: Session, query: str, limit: int = 10) -> list[SourceItem]:
    query_lower = query.lower()
    stmt = select(SourceItem).where(
        SourceItem.source_type == "email",
        or_(
            func.lower(SourceItem.title).contains(query_lower),
            func.lower(SourceItem.content).contains(query_lower),
        ),
    ).limit(limit)
    return list(session.exec(stmt).all())
