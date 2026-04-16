"""``llmwiki subscriptions`` — manage the subscription inbox."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from llmwiki.config import load_config, resolve_home, resolve_workspace
from llmwiki.core.workspace import get_workspace, WorkspaceNotFoundError
from llmwiki.db.connection import connect, db_path

console = Console()


def subs_list_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    status: Optional[str] = typer.Option("pending", "--status", "-s", help="Filter: pending|ingested|dismissed"),
    adapter: Optional[str] = typer.Option(None, "--adapter", help="Filter by adapter type (rss|imap)."),
) -> None:
    """Show pending subscription items grouped by source."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    from llmwiki.core.adapters.subscription_repository import list_subscription_items

    with connect(db_path(home)) as conn:
        items = list_subscription_items(conn, slug, status=status, adapter_type=adapter)

    if not items:
        console.print(f"[yellow]No {status or 'subscription'} items in {slug}.[/yellow]")
        return

    table = Table(title=f"Subscriptions ({status or 'all'}) in {slug}")
    table.add_column("ID", style="dim", max_width=20)
    table.add_column("Title", max_width=50)
    table.add_column("Source")
    table.add_column("Published")
    table.add_column("Status")

    for item in items:
        table.add_row(
            item.item_id,
            item.title[:50],
            item.adapter_type,
            item.published_at[:10] if item.published_at else "",
            item.status,
        )

    console.print(table)


def subs_show_command(
    item_id: str = typer.Argument(..., help="Subscription item ID."),
) -> None:
    """Show a single subscription item with full content path."""
    home = resolve_home()

    from llmwiki.core.adapters.subscription_repository import get_subscription_item

    with connect(db_path(home)) as conn:
        item = get_subscription_item(conn, item_id)

    if not item:
        console.print(f"[red]Item not found:[/red] {item_id}")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]{item.title}[/bold]")
    console.print(f"  [dim]id:[/dim] {item.item_id}")
    console.print(f"  [dim]source:[/dim] {item.adapter_type}")
    console.print(f"  [dim]author:[/dim] {item.author or '-'}")
    console.print(f"  [dim]published:[/dim] {item.published_at or '-'}")
    console.print(f"  [dim]url:[/dim] {item.url or '-'}")
    console.print(f"  [dim]status:[/dim] {item.status}")
    console.print(f"  [dim]content:[/dim] {item.content_path}")
    if item.excerpt:
        console.print(f"\n{item.excerpt[:300]}")


def subs_dismiss_command(
    item_id: str = typer.Argument(..., help="Item ID to dismiss."),
) -> None:
    """Dismiss a subscription item (kept in raw/ for archival)."""
    home = resolve_home()

    from llmwiki.core.adapters.subscription_repository import (
        get_subscription_item,
        mark_dismissed,
    )

    with connect(db_path(home)) as conn:
        item = get_subscription_item(conn, item_id)
        if not item:
            console.print(f"[red]Item not found:[/red] {item_id}")
            raise typer.Exit(code=1)

        conn.execute("BEGIN IMMEDIATE")
        try:
            mark_dismissed(conn, item_id)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    console.print(f"[yellow]Dismissed:[/yellow] {item.title}")


def subs_poll_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    source_id: Optional[str] = typer.Option(None, "--source", help="Poll a specific source."),
) -> None:
    """Poll all subscription sources (RSS + IMAP)."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not db_path(home).exists():
        console.print("[yellow]No database. Run llmwiki init first.[/yellow]")
        raise typer.Exit(code=1)

    from llmwiki.core.adapters.subscription_poll import poll_subscriptions

    secret_resolver = None
    try:
        from llmwiki.core.secrets.resolver import SecretResolver
        secret_resolver = SecretResolver(home)
    except Exception:
        pass

    with connect(db_path(home)) as conn:
        console.print("[dim]Polling subscriptions...[/dim]")
        report = poll_subscriptions(
            conn, slug, ws.path, source_id=source_id, secret_resolver=secret_resolver,
        )

    console.print(
        f"\n[bold]Poll complete:[/bold] {report.sources_polled} sources, "
        f"{report.items_new} new, {report.items_skipped} skipped"
    )
    for err in report.errors:
        console.print(f"  [red]{err}[/red]")
