"""``alexandria secrets`` — secret vault management."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import resolve_home

console = Console()


def secrets_set_command(
    ref: str = typer.Argument(..., help="Secret reference name."),
) -> None:
    """Store an encrypted secret in the vault."""
    home = resolve_home()
    from alexandria.core.secrets.vault import SecretVault, VaultError

    value = typer.prompt("Secret value", hide_input=True)
    vault = SecretVault(home)
    try:
        vault.set(ref, value)
    except VaultError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Secret stored:[/green] {ref}")


def secrets_list_command() -> None:
    """List stored secrets (metadata only)."""
    home = resolve_home()
    from alexandria.core.secrets.vault import SecretVault

    vault = SecretVault(home)
    entries = vault.list_secrets()

    if not entries:
        console.print("[yellow]No secrets stored.[/yellow]")
        return

    table = Table(title="Vault secrets")
    table.add_column("Ref")
    table.add_column("Created")
    table.add_column("Last used")
    table.add_column("Rotated")
    table.add_column("Status")

    for e in entries:
        status = "[red]revoked[/red]" if e.revoked else "[green]active[/green]"
        table.add_row(
            e.ref,
            e.created_at[:10] if e.created_at else "",
            e.last_used_at[:10] if e.last_used_at else "-",
            e.rotated_at[:10] if e.rotated_at else "-",
            status,
        )

    console.print(table)


def secrets_rotate_command(
    ref: str = typer.Argument(..., help="Secret reference to rotate."),
) -> None:
    """Rotate a secret (old value kept for 7 days)."""
    home = resolve_home()
    from alexandria.core.secrets.vault import SecretVault, VaultError

    new_value = typer.prompt("New secret value", hide_input=True)
    vault = SecretVault(home)
    try:
        vault.rotate(ref, new_value)
    except VaultError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Secret rotated:[/green] {ref}")


def secrets_revoke_command(
    ref: str = typer.Argument(..., help="Secret reference to revoke."),
    confirm: bool = typer.Option(False, "--confirm", help="Skip confirmation prompt."),
) -> None:
    """Wipe a secret and mark it as revoked."""
    if not confirm:
        typer.confirm(f"Revoke secret '{ref}'? This cannot be undone.", abort=True)

    home = resolve_home()
    from alexandria.core.secrets.vault import SecretVault, VaultError

    vault = SecretVault(home)
    try:
        vault.revoke(ref)
    except VaultError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[yellow]Secret revoked:[/yellow] {ref}")


def secrets_reveal_command(
    ref: str = typer.Argument(..., help="Secret reference to reveal."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm reveal (audit-logged)."),
) -> None:
    """Reveal a secret value (audit-logged)."""
    if not confirm:
        typer.confirm(
            f"Reveal secret '{ref}'? This action is audit-logged.", abort=True
        )

    home = resolve_home()
    from alexandria.core.secrets.vault import SecretVault, VaultError

    vault = SecretVault(home)
    try:
        value = vault.reveal(ref)
    except VaultError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(value)
