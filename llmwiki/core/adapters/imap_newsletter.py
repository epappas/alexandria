"""IMAP newsletter adapter.

Connects to an IMAP mailbox, filters by sender allowlist, extracts
newsletter content from HTML emails, and saves as markdown files.
Requires IMAPS or STARTTLS — plaintext IMAP is rejected.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from llmwiki.core.adapters.base import AdapterKind, FetchedItem, SyncResult


class IMAPAdapterError(Exception):
    pass


class IMAPNewsletterAdapter:
    """Fetch newsletters from an IMAP mailbox."""

    kind = AdapterKind.LOCAL

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        host = config["host"]
        username = config["username"]
        password = config["password"]
        port = config.get("port", 993)
        folder = config.get("folder", "INBOX")
        from_allowlist = config.get("from_allowlist", [])
        use_starttls = config.get("starttls", False)

        result = SyncResult()
        items: list[FetchedItem] = []

        conn = _connect_imap(host, port, username, password, starttls=use_starttls)
        try:
            conn.select(folder, readonly=True)

            # Build search criteria from allowlist
            message_ids = _search_messages(conn, from_allowlist)

            subs_dir = workspace_path / "raw" / "subscriptions" / "newsletter"
            subs_dir.mkdir(parents=True, exist_ok=True)

            # Load state to skip already-processed messages
            state_file = subs_dir / ".imap_state.json"
            seen_ids = _load_seen_ids(state_file)

            for msg_id in message_ids:
                if msg_id in seen_ids:
                    continue

                msg = _fetch_message(conn, msg_id)
                if msg is None:
                    result.items_errored += 1
                    continue

                parsed = _parse_newsletter(msg)
                if not parsed:
                    continue

                content_md = parsed["content"]
                content_hash = hashlib.sha256(content_md.encode("utf-8")).hexdigest()

                # Save to file
                date_str = parsed["date"][:10] if parsed["date"] else "undated"
                slug = _slugify(parsed["subject"])[:60]
                pub_slug = _slugify(parsed["from_name"] or parsed["from_addr"])[:30]
                filename = f"{date_str}-{slug}.md"
                pub_dir = subs_dir / pub_slug
                pub_dir.mkdir(parents=True, exist_ok=True)
                file_path = pub_dir / filename

                if not file_path.exists():
                    _write_newsletter_file(file_path, parsed, content_md)

                items.append(FetchedItem(
                    source_type="imap",
                    event_type="subscription_item",
                    title=parsed["subject"],
                    body=content_md[:500] if content_md else None,
                    url=None,
                    author=parsed["from_name"] or parsed["from_addr"],
                    occurred_at=parsed["date"] or datetime.now(timezone.utc).isoformat(),
                    event_data={
                        "external_id": parsed["message_id"],
                        "content_hash": content_hash,
                        "content_path": str(file_path.relative_to(workspace_path)),
                        "from_addr": parsed["from_addr"],
                        "from_name": parsed["from_name"],
                        "subject": parsed["subject"],
                    },
                ))
                result.items_synced += 1
                seen_ids.add(msg_id)

            _save_seen_ids(state_file, seen_ids)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for key in ("host", "username", "password"):
            if key not in config:
                errors.append(f"'{key}' is required for imap adapter")
        return errors


def _connect_imap(
    host: str, port: int, username: str, password: str, *, starttls: bool = False
) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    """Connect to IMAP server. Requires SSL or STARTTLS."""
    if starttls:
        conn = imaplib.IMAP4(host, port)
        conn.starttls()
    else:
        conn = imaplib.IMAP4_SSL(host, port)
    conn.login(username, password)
    return conn


def _search_messages(
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4,
    from_allowlist: list[str],
) -> list[str]:
    """Search for messages matching the from allowlist."""
    if not from_allowlist:
        _, data = conn.search(None, "ALL")
        return (data[0] or b"").split()

    all_ids: list[bytes] = []
    for addr_pattern in from_allowlist:
        addr = addr_pattern.replace("*@", "")
        _, data = conn.search(None, "FROM", f'"{addr}"')
        ids = (data[0] or b"").split()
        all_ids.extend(ids)

    # Deduplicate while preserving order
    seen: set[bytes] = set()
    unique: list[str] = []
    for mid in all_ids:
        if mid not in seen:
            seen.add(mid)
            unique.append(mid.decode() if isinstance(mid, bytes) else mid)
    return unique


def _fetch_message(
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4, msg_id: str
) -> EmailMessage | None:
    """Fetch a single message by ID."""
    mid = msg_id.encode() if isinstance(msg_id, str) else msg_id
    _, data = conn.fetch(mid, "(RFC822)")
    if not data or not data[0]:
        return None
    raw = data[0][1] if isinstance(data[0], tuple) else data[0]
    if not raw:
        return None
    return email.message_from_bytes(raw, policy=email.policy.default)


def _parse_newsletter(msg: EmailMessage) -> dict[str, Any] | None:
    """Extract newsletter content from an email message."""
    subject = msg.get("Subject", "")
    from_header = msg.get("From", "")
    date_header = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")

    # Parse from header
    from_name, from_addr = "", from_header
    if "<" in from_header:
        parts = from_header.split("<")
        from_name = parts[0].strip().strip('"')
        from_addr = parts[1].rstrip(">").strip()

    # Parse date
    date_iso = ""
    if date_header:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_header)
            date_iso = dt.isoformat()
        except (ValueError, TypeError):
            date_iso = date_header

    # Extract body
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html" and not html_body:
                html_body = part.get_content()
            elif ct == "text/plain" and not text_body:
                text_body = part.get_content()
    else:
        ct = msg.get_content_type()
        if ct == "text/html":
            html_body = msg.get_content()
        elif ct == "text/plain":
            text_body = msg.get_content()

    # Prefer HTML -> markdown; fall back to plain text
    if html_body:
        content = _html_to_markdown(_strip_email_chrome(html_body))
    elif text_body:
        content = text_body
    else:
        return None

    if not content.strip():
        return None

    return {
        "subject": subject,
        "from_name": from_name,
        "from_addr": from_addr,
        "date": date_iso,
        "message_id": message_id,
        "content": content,
    }


def _strip_email_chrome(html_content: str) -> str:
    """Remove common email boilerplate from HTML."""
    # Remove tracking pixels (1x1 images)
    html_content = re.sub(
        r'<img[^>]+(?:width|height)\s*=\s*["\']?1["\']?[^>]*>', "", html_content
    )
    # Remove unsubscribe sections
    html_content = re.sub(
        r"(?i)<[^>]*(?:unsubscribe|manage.preferences|opt.out)[^>]*>.*?</[^>]+>",
        "", html_content, flags=re.DOTALL,
    )
    # Remove "view in browser" links
    html_content = re.sub(
        r"(?i)<[^>]*(?:view.in.browser|view.online|read.online)[^>]*>.*?</[^>]+>",
        "", html_content, flags=re.DOTALL,
    )
    return html_content


_DANGEROUS_URI_RE = re.compile(
    r"\[([^\]]*)\]\((javascript|data|vbscript):[^)]*\)", re.IGNORECASE
)


def _html_to_markdown(html_content: str) -> str:
    """Convert HTML to markdown."""
    if not html_content:
        return ""
    try:
        from markdownify import markdownify
        md = markdownify(
            html_content, heading_style="ATX",
            strip=["script", "style", "iframe", "object", "embed", "form", "input"],
        ).strip()
    except ImportError:
        import html as html_mod
        clean = re.sub(r"<[^>]+>", "", html_content)
        md = html_mod.unescape(clean).strip()
    # Strip dangerous URI schemes from markdown links
    md = _DANGEROUS_URI_RE.sub(r"\1", md)
    return md


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug or "unknown"


def _write_newsletter_file(
    path: Path, parsed: dict[str, Any], content_md: str
) -> None:
    """Write a newsletter as a markdown file."""
    lines = [
        f"# {parsed['subject']}",
        "",
        f"- from: {parsed['from_name']} <{parsed['from_addr']}>",
        f"- date: {parsed['date']}",
        f"- message-id: {parsed['message_id']}",
        "", "---", "",
        content_md,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _load_seen_ids(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    return set(data.get("seen_ids", []))


def _save_seen_ids(state_file: Path, seen_ids: set[str]) -> None:
    data = {"seen_ids": sorted(seen_ids), "updated_at": datetime.now(timezone.utc).isoformat()}
    state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
