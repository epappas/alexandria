"""GitHub API source adapter.

Fetches issues, pull requests, and releases from a GitHub repository
via the REST API. Commits are handled by git-local, not here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from alexandria.core.adapters.base import AdapterKind, FetchedItem, SyncResult


class GitHubAPIError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        self.status = status
        super().__init__(message)


class GitHubAdapter:
    """Fetch issues, PRs, and releases from GitHub REST API."""

    kind = AdapterKind.GITHUB
    API_BASE = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        owner = config["owner"]
        repo = config["repo"]
        result = SyncResult()
        items: list[FetchedItem] = []

        # Load sync state
        state_file = workspace_path / "raw" / "github" / f"{owner}-{repo}.state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state = self._load_state(state_file)

        since = state.get("last_synced_at")
        token = self._token or config.get("token")

        # Fetch issues (includes PRs on GitHub's API)
        try:
            issue_items = self._fetch_issues(owner, repo, token, since=since)
            items.extend(issue_items)
            result.items_synced += len(issue_items)
        except GitHubAPIError as exc:
            result.items_errored += 1
            result.errors.append(f"issues: {exc}")

        # Fetch releases
        try:
            release_items = self._fetch_releases(owner, repo, token, since=since)
            items.extend(release_items)
            result.items_synced += len(release_items)
        except GitHubAPIError as exc:
            result.items_errored += 1
            result.errors.append(f"releases: {exc}")

        # Update state
        if items:
            state["last_synced_at"] = datetime.now(UTC).isoformat()
            self._save_state(state_file, state)

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "owner" not in config:
            errors.append("'owner' is required for github adapter")
        if "repo" not in config:
            errors.append("'repo' is required for github adapter")
        return errors

    # -- API calls ---------------------------------------------------------------

    def _fetch_issues(
        self,
        owner: str,
        repo: str,
        token: str | None,
        since: str | None = None,
    ) -> list[FetchedItem]:
        params = "state=all&sort=updated&direction=desc&per_page=100"
        if since:
            params += f"&since={since}"
        url = f"{self.API_BASE}/repos/{owner}/{repo}/issues?{params}"

        data = self._api_get(url, token)
        items: list[FetchedItem] = []

        for issue in data:
            is_pr = "pull_request" in issue
            items.append(FetchedItem(
                source_type="github",
                event_type="pull_request" if is_pr else "issue",
                title=issue["title"],
                body=issue.get("body"),
                url=issue["html_url"],
                author=issue.get("user", {}).get("login"),
                occurred_at=issue["updated_at"],
                event_data={
                    "number": issue["number"],
                    "state": issue["state"],
                    "labels": [lb["name"] for lb in issue.get("labels", [])],
                    "is_pr": is_pr,
                },
            ))

        return items

    def _fetch_releases(
        self,
        owner: str,
        repo: str,
        token: str | None,
        since: str | None = None,
    ) -> list[FetchedItem]:
        url = f"{self.API_BASE}/repos/{owner}/{repo}/releases?per_page=30"
        data = self._api_get(url, token)
        items: list[FetchedItem] = []

        for release in data:
            published = release.get("published_at", "")
            if since and published and published < since:
                continue
            items.append(FetchedItem(
                source_type="github",
                event_type="release",
                title=release.get("name") or release.get("tag_name", ""),
                body=release.get("body"),
                url=release.get("html_url"),
                author=release.get("author", {}).get("login"),
                occurred_at=published,
                event_data={
                    "tag": release.get("tag_name"),
                    "prerelease": release.get("prerelease", False),
                    "draft": release.get("draft", False),
                },
            ))

        return items

    def _api_get(self, url: str, token: str | None) -> list[dict[str, Any]]:
        """Make a GET request to the GitHub API with rate limit handling."""
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 403:
                # Rate limit or auth issue
                retry_after = exc.headers.get("Retry-After", "60")
                raise GitHubAPIError(
                    f"GitHub API rate limited (retry after {retry_after}s)",
                    status=403,
                ) from exc
            if exc.code == 404:
                raise GitHubAPIError(
                    f"repository not found: {url}", status=404
                ) from exc
            raise GitHubAPIError(
                f"GitHub API error {exc.code}: {exc.reason}", status=exc.code
            ) from exc
        except URLError as exc:
            raise GitHubAPIError(f"network error: {exc.reason}") from exc

    # -- State management --------------------------------------------------------

    def _load_state(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(self, path: Path, state: dict[str, Any]) -> None:
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
