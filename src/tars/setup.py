"""Interactive setup wizard for tars."""

import webbrowser

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

TIGER_SIGNUP_URL = "https://tsdb.co/jm-pgtextsearch"


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

    # Get DATABASE_URL
    while True:
        url = Prompt.ask("  Paste your DATABASE_URL")

        if not validate_database_url(url):
            console.print("  [red]Invalid URL format.[/red] Should start with postgresql:// or postgres://")
            continue

        console.print("  [dim]Testing connection...[/dim]")
        success, message = test_connection(url)

        if success:
            console.print("  [green]Connection successful![/green]\n")
            break
        else:
            console.print(f"  [red]Connection failed:[/red] {message}")
            if not Confirm.ask("  Try again?", default=True):
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
