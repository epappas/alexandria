"""Notion adapter — fetch pages and databases via the Notion API.

Requires a Notion integration token. Pages are converted to markdown.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from alexandria.core.adapters.base import FetchedItem, SyncResult

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionAdapterError(Exception):
    pass


class NotionAdapter:
    """Fetch pages from a Notion workspace."""

    kind = "notion"

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        token = self._token or config.get("token", "")
        if not token:
            return [], SyncResult(errors=["Notion token required"])

        page_ids = config.get("page_ids", [])
        database_ids = config.get("database_ids", [])
        result = SyncResult()
        items: list[FetchedItem] = []
        out_dir = workspace_path / "raw" / "notion"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Fetch individual pages
        for page_id in page_ids:
            try:
                page = _fetch_page(token, page_id)
                blocks = _fetch_blocks(token, page_id)
                md = _blocks_to_markdown(blocks)
                title = _extract_page_title(page)
                content_hash = hashlib.sha256(md.encode()).hexdigest()

                slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:60]
                md_path = out_dir / f"{slug}.md"
                _write_page(md_path, title, page_id, md, page)

                items.append(FetchedItem(
                    source_type="notion",
                    event_type="page",
                    title=title,
                    body=md[:500],
                    url=f"https://notion.so/{page_id.replace('-', '')}",
                    occurred_at=page.get("last_edited_time", datetime.now(timezone.utc).isoformat()),
                    event_data={"page_id": page_id, "content_hash": content_hash,
                                "content_path": str(md_path.relative_to(workspace_path))},
                ))
                result.items_synced += 1
            except Exception as exc:
                result.items_errored += 1
                result.errors.append(f"page {page_id}: {exc}")

        # Fetch database entries
        for db_id in database_ids:
            try:
                entries = _query_database(token, db_id)
                for entry in entries:
                    entry_id = entry["id"]
                    blocks = _fetch_blocks(token, entry_id)
                    md = _blocks_to_markdown(blocks)
                    title = _extract_page_title(entry)
                    content_hash = hashlib.sha256(md.encode()).hexdigest()

                    slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:60]
                    md_path = out_dir / f"{slug}.md"
                    _write_page(md_path, title, entry_id, md, entry)

                    items.append(FetchedItem(
                        source_type="notion",
                        event_type="database_entry",
                        title=title,
                        body=md[:500],
                        url=f"https://notion.so/{entry_id.replace('-', '')}",
                        occurred_at=entry.get("last_edited_time", ""),
                        event_data={"page_id": entry_id, "content_hash": content_hash,
                                    "content_path": str(md_path.relative_to(workspace_path))},
                    ))
                    result.items_synced += 1
            except Exception as exc:
                result.items_errored += 1
                result.errors.append(f"database {db_id}: {exc}")

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not config.get("token") and not config.get("token_ref"):
            errors.append("'token' or 'token_ref' required for Notion")
        if not config.get("page_ids") and not config.get("database_ids"):
            errors.append("at least one 'page_ids' or 'database_ids' required")
        return errors


def _api_get(token: str, path: str) -> dict[str, Any]:
    req = Request(f"{API_BASE}{path}", headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _api_post(token: str, path: str, body: dict) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = Request(f"{API_BASE}{path}", data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _fetch_page(token: str, page_id: str) -> dict[str, Any]:
    return _api_get(token, f"/pages/{page_id}")


def _fetch_blocks(token: str, block_id: str) -> list[dict[str, Any]]:
    data = _api_get(token, f"/blocks/{block_id}/children?page_size=100")
    return data.get("results", [])


def _query_database(token: str, db_id: str) -> list[dict[str, Any]]:
    data = _api_post(token, f"/databases/{db_id}/query", {"page_size": 100})
    return data.get("results", [])


def _extract_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            titles = prop.get("title", [])
            if titles:
                return "".join(t.get("plain_text", "") for t in titles)
    return "Untitled"


def _blocks_to_markdown(blocks: list[dict]) -> str:
    lines: list[str] = []
    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        text = _rich_text_to_str(data.get("rich_text", []))

        if btype == "paragraph":
            lines.append(text)
        elif btype.startswith("heading_"):
            level = int(btype[-1])
            lines.append(f"{'#' * level} {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            checked = "x" if data.get("checked") else " "
            lines.append(f"- [{checked}] {text}")
        elif btype == "code":
            lang = data.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype == "quote":
            lines.append(f"> {text}")
        elif btype == "divider":
            lines.append("---")
        elif btype == "callout":
            lines.append(f"> {text}")
        elif text:
            lines.append(text)
        lines.append("")

    return "\n".join(lines)


def _rich_text_to_str(rich_text: list[dict]) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _write_page(path: Path, title: str, page_id: str, md: str, page: dict) -> None:
    lines = [
        f"# {title}",
        "",
        f"- notion_id: {page_id}",
        f"- last_edited: {page.get('last_edited_time', '')}",
        "", "---", "",
        md,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
