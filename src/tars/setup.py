"""Interactive setup wizard for tars."""

import time
import webbrowser

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

TIGER_SIGNUP_URL = "https://tsdb.co/jm-pgtextsearch"

# Retry settings for database connection
# New cloud databases can take 1-2 minutes for DNS to propagate
MAX_AUTO_RETRIES = 6
RETRY_DELAY_SECONDS = 10


def _wait_for_database(url: str, max_retries: int = MAX_AUTO_RETRIES) -> tuple[bool, str]:
    """Wait for database to become available with retries.

    Returns (success, message).
    """
    from tars.config import test_connection

    for attempt in range(1, max_retries + 1):
        console.print(f"  [dim]Attempt {attempt}/{max_retries}...[/dim]")
        success, message = test_connection(url)

        if success:
            return (True, "OK")

        if attempt < max_retries:
            console.print(f"  [yellow]Database not ready:[/yellow] {message}")
            console.print(f"  [dim]Waiting {RETRY_DELAY_SECONDS}s for database to provision...[/dim]")
            time.sleep(RETRY_DELAY_SECONDS)

    return (False, message)


def run_setup() -> None:
    """Run the interactive setup wizard."""
    from tars.config import create_env_file, test_connection, validate_database_url
    from tars.db import db_init, db_init_vectorizer
    from tars.rename import rename_bot

    # Welcome
    console.print()
    console.print(Panel("Welcome to tars setup!", style="cyan"))
    console.print()

    # Step 1: Bot name
    console.print("[bold]Step 1:[/bold] Name your bot")
    name = Prompt.ask("  Bot name", default="tars")

    if name != "tars":
        console.print(f"\n  Renaming bot to [cyan]{name}[/cyan]...")
        results = rename_bot(name)
        console.print(f"  [green]Done![/green] Updated {results['files']} file(s)\n")
    else:
        console.print()

    # Step 2: Database
    console.print("[bold]Step 2:[/bold] Database configuration")

    if Confirm.ask("  Open Tiger Data signup in browser?", default=True):
        console.print(f"  [dim]Opening {TIGER_SIGNUP_URL}[/dim]")
        webbrowser.open(TIGER_SIGNUP_URL)
        console.print()

    # Get DATABASE_URL with retry logic
    url = None
    while True:
        if url is None:
            url = Prompt.ask("  Paste your DATABASE_URL")

        if not validate_database_url(url):
            console.print("  [red]Invalid URL format.[/red] Should start with postgresql:// or postgres://")
            url = None
            continue

        console.print("  [dim]Testing connection...[/dim]")
        success, message = test_connection(url)

        if success:
            console.print("  [green]Connection successful![/green]\n")
            break

        # Connection failed - offer options
        console.print(f"  [yellow]Connection failed:[/yellow] {message}")
        console.print()
        console.print("  [bold]Options:[/bold]")
        console.print("    [cyan]1[/cyan] - Wait and retry (database may still be provisioning)")
        console.print("    [cyan]2[/cyan] - Enter a different DATABASE_URL")
        console.print("    [cyan]3[/cyan] - Save URL and skip database init (run 'db init' later)")
        console.print("    [cyan]4[/cyan] - Cancel setup")

        choice = Prompt.ask("  Choose", choices=["1", "2", "3", "4"], default="1")

        if choice == "1":
            # Wait and retry with auto-retries
            console.print()
            success, message = _wait_for_database(url)
            if success:
                console.print("  [green]Connection successful![/green]\n")
                break
            else:
                console.print(f"  [red]Still unable to connect:[/red] {message}")
                console.print()
                # Loop back to show options again
                continue
        elif choice == "2":
            # Get new URL
            url = None
            continue
        elif choice == "3":
            # Save URL but skip db init
            create_env_file(url, name)
            console.print("\n  [green]Created .env file[/green]")
            console.print(f"  [yellow]Skipped database initialization.[/yellow]")
            console.print()
            console.print(Panel(
                f"[yellow]Setup partially complete[/yellow]\n\n"
                f"When your database is ready, run:\n"
                f"  [cyan]{name} db init[/cyan]\n"
                f"  [cyan]{name} db vector init[/cyan]",
                title="Next Steps",
                style="yellow",
            ))
            return
        else:
            # Cancel
            console.print("[yellow]Setup cancelled.[/yellow]")
            return

    # Create .env file
    create_env_file(url, name)
    console.print("  [green]Created .env file[/green]\n")

    # Step 3: Initialize database
    console.print("[bold]Step 3:[/bold] Initializing database")

    console.print("  [dim]Running db init...[/dim]")
    db_init()

    console.print("  [dim]Running vector init...[/dim]")
    db_init_vectorizer()

    console.print()

    # Done!
    console.print(Panel(
        f"[green]Setup complete![/green]\n\n"
        f"Try these commands:\n"
        f"  [cyan]{name} add https://example.com[/cyan]\n"
        f"  [cyan]{name} search \"hello\"[/cyan]\n"
        f"  [cyan]{name} help[/cyan]",
        title="Success",
        style="green",
    ))
