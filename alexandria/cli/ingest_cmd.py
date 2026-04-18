"""``alexandria ingest`` — compile sources into the wiki.

Accepts a file, directory, URL, or git repo URL. Directories and repos
are walked for all supported files. Single files and URLs go through
the standard ingest pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace

console = Console()


def ingest_command(
    source: str = typer.Argument(..., help="File, directory, URL, or git repo URL."),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Override the current workspace."
    ),
    topic: Optional[str] = typer.Option(
        None, "--topic", help="Topic directory for the wiki page (default: inferred)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview without running (single file only)."
    ),
) -> None:
    """Compile sources into the wiki via staged writes + verification.

    Accepts:
    - Local file: ``alxia ingest paper.pdf``
    - Local directory: ``alxia ingest ./my-project``
    - URL: ``alxia ingest https://example.com/page``
    - Git URL: ``alxia ingest https://github.com/owner/repo``
    - GitHub shorthand: ``alxia ingest owner/repo``
    """
    home = resolve_home()
    config = load_config(home)
    target_slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, target_slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if dry_run:
        from alexandria.llm.budget import BudgetConfig, BudgetEnforcer
        budget = BudgetEnforcer(BudgetConfig())
        est = budget.pre_flight_estimate(
            estimated_writer_calls=1, avg_input_per_call=4000, avg_output_per_call=2000,
        )
        console.print(f"[bold]Dry run:[/bold] {source}")
        console.print(f"  Workspace: {target_slug}, Topic: {topic or '(inferred)'}, Est: ${est:.4f}")
        return

    # Expand GitHub shorthand: owner/repo -> git URL
    if _is_github_shorthand(source):
        source = f"https://github.com/{source}.git"

    # Git repo URL
    if _is_git_url(source):
        _ingest_git_repo(home, target_slug, ws.path, source, topic)
        return

    # HTTP/HTTPS URL (non-git)
    if source.startswith(("http://", "https://")):
        _ingest_url(home, target_slug, ws.path, source, topic)
        return

    # Local path
    local = Path(source).expanduser().resolve()
    if not local.exists():
        console.print(f"[red]error:[/red] not found: {source}")
        raise typer.Exit(code=1)

    # Directory -> repo ingest
    if local.is_dir():
        _ingest_directory(home, target_slug, ws.path, local, topic)
        return

    # JSONL conversation transcript -> capture + ingest
    if local.suffix == ".jsonl":
        _ingest_conversation(home, target_slug, ws.path, local, topic)
        return

    # Single file
    _ingest_single_file(home, target_slug, ws.path, local, topic)


def _ingest_single_file(
    home: Path, slug: str, ws_path: Path, source_path: Path, topic: str | None,
) -> None:
    from alexandria.core.ingest import IngestError, ingest_file

    try:
        result = ingest_file(
            home=home, workspace_slug=slug, workspace_path=ws_path,
            source_file=source_path, topic=topic,
        )
    except IngestError as exc:
        console.print(f"[red]Ingest failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if result.committed:
        console.print(f"[green]Ingest committed[/green] (run {result.run_id})")
        for path in result.committed_paths:
            console.print(f"  [cyan]wiki/{path}[/cyan]")
        console.print(f"[dim]Verifier: {result.verdict_reasoning}[/dim]")
    else:
        console.print(f"[red]Ingest rejected[/red] (run {result.run_id})")
        console.print(f"[yellow]Reason:[/yellow] {result.verdict_reasoning}")
        raise typer.Exit(code=1)


def _ingest_conversation(
    home: Path, slug: str, ws_path: Path, jsonl_path: Path, topic: str | None,
) -> None:
    from alexandria.core.capture.conversation import (
        capture_conversation, detect_format, CaptureError,
    )
    from alexandria.core.ingest import IngestError, ingest_file

    fmt = detect_format(jsonl_path)
    if fmt == "unknown":
        # Not a conversation — fall back to single file ingest
        _ingest_single_file(home, slug, ws_path, jsonl_path, topic)
        return

    console.print(f"[dim]Capturing {fmt} conversation...[/dim]")
    try:
        result = capture_conversation(jsonl_path, ws_path, client=fmt)
    except CaptureError as exc:
        console.print(f"[red]Capture failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[dim]Captured {result['message_count']} messages to "
        f"{result['output_path']}[/dim]"
    )

    # Now ingest the captured markdown through the full pipeline
    md_path = Path(result["absolute_path"])
    resolved_topic = topic or "conversations"
    try:
        ir = ingest_file(
            home=home, workspace_slug=slug, workspace_path=ws_path,
            source_file=md_path, topic=resolved_topic,
        )
    except IngestError as exc:
        console.print(f"[red]Ingest failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if ir.committed:
        console.print(f"[green]Conversation ingested[/green] (run {ir.run_id})")
        for path in ir.committed_paths:
            console.print(f"  [cyan]wiki/{path}[/cyan]")
    else:
        console.print(f"[yellow]Rejected:[/yellow] {ir.verdict_reasoning}")

    # Extract and ingest referenced artifacts (papers, repos, etc.)
    from alexandria.core.capture.artifacts import extract_artifacts
    from alexandria.core.capture.conversation import _parse_claude_code_jsonl

    raw_messages = _parse_claude_code_jsonl(jsonl_path) if fmt == "claude-code" else []
    artifacts = extract_artifacts(raw_messages)
    if not artifacts:
        return

    console.print(f"\n[bold]{len(artifacts)}[/bold] referenced artifacts found")
    committed = 0
    for art in artifacts:
        try:
            art_result = ingest_file(
                home=home, workspace_slug=slug, workspace_path=ws_path,
                source_file=_fetch_artifact(art.url, ws_path),
                topic=topic or "research",
            )
            if art_result.committed:
                committed += 1
                console.print(f"  [green]+[/green] [{art.kind}] {art.url[:70]}")
            else:
                console.print(f"  [yellow]-[/yellow] [{art.kind}] {art.url[:70]}")
        except Exception:
            console.print(f"  [red]![/red] [{art.kind}] {art.url[:70]}")

    console.print(f"[dim]Artifacts: {committed}/{len(artifacts)} committed[/dim]")


def _ingest_url(
    home: Path, slug: str, ws_path: Path, url: str, topic: str | None,
) -> None:
    from alexandria.core.web import fetch_and_save, WebFetchError

    console.print(f"[dim]Fetching {url}...[/dim]")
    try:
        source_path = fetch_and_save(url, ws_path)
    except WebFetchError as exc:
        console.print(f"[red]Fetch failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[dim]Saved to {source_path.relative_to(ws_path)}[/dim]")
    _ingest_single_file(home, slug, ws_path, source_path, topic)


def _ingest_directory(
    home: Path, slug: str, ws_path: Path, dir_path: Path, topic: str | None,
) -> None:
    from alexandria.core.repo_ingest import ingest_repo, _collect_files, ALL_INGEST_EXTS

    files = _collect_files(dir_path, ALL_INGEST_EXTS)
    console.print(f"Found [bold]{len(files)}[/bold] files to ingest")
    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        return

    result = ingest_repo(
        home=home, workspace_slug=slug, workspace_path=ws_path,
        repo_path=dir_path, topic=topic,
        on_progress=_print_progress,
    )
    _print_summary(result)


def _ingest_git_repo(
    home: Path, slug: str, ws_path: Path, url: str, topic: str | None,
) -> None:
    from alexandria.core.repo_ingest import (
        clone_repo, ingest_repo, _collect_files, ALL_INGEST_EXTS, IngestError,
    )

    console.print(f"[dim]Cloning {url}...[/dim]")
    try:
        repo_path = clone_repo(url, ws_path / "raw" / "git")
    except IngestError as exc:
        console.print(f"[red]Clone failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[dim]Repo at {repo_path.relative_to(ws_path)}[/dim]")

    files = _collect_files(repo_path, ALL_INGEST_EXTS)
    console.print(f"Found [bold]{len(files)}[/bold] files to ingest")
    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        return

    result = ingest_repo(
        home=home, workspace_slug=slug, workspace_path=ws_path,
        repo_path=repo_path, topic=topic,
        on_progress=_print_progress,
    )
    _print_summary(result)


def _print_progress(rel: str, status: str) -> None:
    sym = {"committed": "[green]+[/green]", "rejected": "[yellow]-[/yellow]"}.get(status, "[red]![/red]")
    console.print(f"  {sym} {rel}")


def _print_summary(result: "RepoIngestResult") -> None:
    console.print()
    console.print(f"[bold]Results:[/bold]")
    console.print(f"  Committed: [green]{len(result.committed)}[/green]")
    if result.rejected:
        console.print(f"  Rejected:  [yellow]{len(result.rejected)}[/yellow]")
    if result.errors:
        console.print(f"  Errors:    [red]{len(result.errors)}[/red]")
        for err in result.errors[:5]:
            console.print(f"    {err}")


def _is_git_url(source: str) -> bool:
    if source.startswith(("git@", "ssh://")):
        return True
    if source.endswith(".git"):
        return True
    # GitHub/GitLab HTTPS with path depth >= 2
    if source.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        parsed = urlparse(source)
        host = parsed.hostname or ""
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if host in ("github.com", "gitlab.com", "bitbucket.org") and len(path_parts) >= 2:
            return True
    return False


def _is_github_shorthand(source: str) -> bool:
    """Detect owner/repo pattern that isn't a local path."""
    if "/" not in source or source.count("/") != 1:
        return False
    if source.startswith(("http", "git@", "ssh://", "/", ".", "~")):
        return False
    return not Path(source).exists()


def _fetch_artifact(url: str, ws_path: Path) -> Path:
    """Fetch an artifact URL and return the local path."""
    from alexandria.core.web import fetch_and_save
    return fetch_and_save(url, ws_path)
