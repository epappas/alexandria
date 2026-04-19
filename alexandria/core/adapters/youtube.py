"""YouTube adapter — extract transcripts and metadata from videos.

Uses youtube-transcript-api for captions and yt-dlp metadata extraction
as fallback. No video download — text only.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from alexandria.core.adapters.base import FetchedItem, SyncResult


class YouTubeAdapterError(Exception):
    pass


class YouTubeAdapter:
    """Fetch transcripts and metadata from YouTube videos/playlists."""

    kind = "youtube"

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        urls = config.get("urls", [])
        if isinstance(urls, str):
            urls = [urls]

        result = SyncResult()
        items: list[FetchedItem] = []
        out_dir = workspace_path / "raw" / "youtube"
        out_dir.mkdir(parents=True, exist_ok=True)

        for url in urls:
            try:
                video_id = _extract_video_id(url)
                if not video_id:
                    result.items_errored += 1
                    result.errors.append(f"cannot extract video ID from {url}")
                    continue

                transcript, metadata = _fetch_transcript(video_id)
                title = metadata.get("title", video_id)
                content_hash = hashlib.sha256(transcript.encode()).hexdigest()

                # Save transcript
                slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:60]
                md_path = out_dir / f"{slug}-{video_id}.md"
                _write_transcript(md_path, title, video_id, url, transcript, metadata)

                items.append(FetchedItem(
                    source_type="youtube",
                    event_type="transcript",
                    title=title,
                    body=transcript[:500],
                    url=url,
                    author=metadata.get("author", ""),
                    occurred_at=metadata.get("published", datetime.now(UTC).isoformat()),
                    event_data={
                        "video_id": video_id,
                        "content_hash": content_hash,
                        "content_path": str(md_path.relative_to(workspace_path)),
                        "duration": metadata.get("duration", ""),
                    },
                ))
                result.items_synced += 1
            except Exception as exc:
                result.items_errored += 1
                result.errors.append(f"{url}: {exc}")

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if "urls" not in config:
            return ["'urls' is required (single URL or list)"]
        return []


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        qs = parse_qs(parsed.query)
        return qs.get("v", [None])[0]
    if parsed.hostname == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0]
    return None


def _fetch_transcript(video_id: str) -> tuple[str, dict[str, Any]]:
    """Fetch transcript and metadata for a video."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = "\n".join(entry["text"] for entry in transcript_list)
    except ImportError:
        raise YouTubeAdapterError(
            "youtube-transcript-api required. Install: pip install youtube-transcript-api"
        )
    except Exception as exc:
        raise YouTubeAdapterError(f"transcript fetch failed for {video_id}: {exc}") from exc

    # Basic metadata via oEmbed (no API key needed)
    metadata = _fetch_oembed(video_id)
    return transcript, metadata


def _fetch_oembed(video_id: str) -> dict[str, Any]:
    """Fetch basic video metadata via YouTube oEmbed."""
    url = f"https://www.youtube.com/oembed?url=https://youtube.com/watch?v={video_id}&format=json"
    try:
        req = Request(url, headers={"User-Agent": "alexandria/1.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return {
                "title": data.get("title", video_id),
                "author": data.get("author_name", ""),
            }
    except Exception:
        return {"title": video_id}


def _write_transcript(
    path: Path, title: str, video_id: str, url: str,
    transcript: str, metadata: dict[str, Any],
) -> None:
    lines = [
        f"# {title}",
        "",
        f"- source: {url}",
        f"- video_id: {video_id}",
        f"- author: {metadata.get('author', '')}",
        "", "---", "",
        transcript,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
