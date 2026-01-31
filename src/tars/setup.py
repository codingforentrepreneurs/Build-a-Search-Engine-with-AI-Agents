"""Interactive setup wizard for tars."""

import os
import re
import shutil
import time
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()


def _slugify(text: str, max_length: int = 10) -> str:
    """Convert text to a valid bot name slug.

    - Lowercase
    - Replace spaces and special chars with hyphens
    - Remove consecutive hyphens
    - Truncate to max_length
    """
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Truncate (but don't cut in middle of word if possible)
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def _get_default_name() -> str:
    """Get suggested default bot name from folder name or 'tars'."""
    folder_name = Path.cwd().name
    slugified = _slugify(folder_name)

    # Use slugified folder name if it's valid, otherwise fall back to 'tars'
    if len(slugified) >= 2 and slugified.lower() not in RESERVED_NAMES:
        # Also check it doesn't conflict with existing commands
        if slugified == "tars" or not shutil.which(slugified):
            return slugified

    return "tars"

TIGER_SIGNUP_URL = "https://tsdb.co/jm-pgtextsearch"

# Retry settings for database connection
# New cloud databases can take 1-2 minutes for DNS to propagate
MAX_AUTO_RETRIES = 6
RETRY_DELAY_SECONDS = 10

# Reserved names that cannot be used as bot names
RESERVED_NAMES = {
    # Python/system
    "python", "python3", "pip", "uv", "uvx",
    # Common shells/tools
    "bash", "sh", "zsh", "fish", "cmd", "powershell",
    # Common CLI tools
    "git", "npm", "node", "yarn", "pnpm", "docker", "kubectl",
    "curl", "wget", "ssh", "scp", "rsync",
    # Filesystem
    "ls", "cd", "cp", "mv", "rm", "mkdir", "cat", "grep", "find", "head", "tail",
    # System
    "sudo", "su", "which", "where", "echo", "test", "true", "false",
    # Database
    "psql", "pg_dump", "postgres", "redis", "mysql",
}


def _check_name_available(name: str) -> tuple[bool, str]:
    """Check if a bot name is available (not conflicting with system commands).

    Returns (available, message).
    """
    name_lower = name.lower()

    # Check reserved names
    if name_lower in RESERVED_NAMES:
        return (False, f"'{name}' is a reserved system command")

    # Check for invalid characters
    if not name.replace("-", "").replace("_", "").isalnum():
        return (False, "Name can only contain letters, numbers, hyphens, and underscores")

    # Check length
    if len(name) < 2:
        return (False, "Name must be at least 2 characters")
    if len(name) > 32:
        return (False, "Name must be 32 characters or less")

    # Check if command exists in PATH (but allow 'tars' since that's the current name)
    if name_lower != "tars" and shutil.which(name):
        return (False, f"'{name}' already exists as a command on your system")

    return (True, "OK")


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


def _show_overview() -> bool:
    """Show setup overview and get user confirmation.

    Returns True if user wants to proceed.
    """
    console.print()
    console.print(Panel(
        "[bold cyan]tars setup wizard[/bold cyan]\n\n"
        "This wizard will:\n"
        "  [bold]1.[/bold] Choose a name for your bot (+ install globally)\n"
        "  [bold]2.[/bold] Configure your database connection\n"
        "  [bold]3.[/bold] Initialize database schema and vector search\n"
        "  [bold]4.[/bold] Install browser for web crawling\n\n"
        "[bold yellow]Files that may be modified:[/bold yellow]\n"
        "  • [cyan].env[/cyan] - Database connection string\n"
        "  • [cyan]pyproject.toml[/cyan] - Package name (if renaming)\n"
        "  • [cyan]README.md, CLAUDE.md[/cyan] - Documentation (if renaming)\n"
        "  • [cyan]src/tars/*.py[/cyan] - Source files (if renaming)\n\n"
        "[bold yellow]Recovery / Uninstall:[/bold yellow]\n"
        "  • Reset all changes: [dim]git checkout .[/dim]\n"
        "  • Re-run setup: [dim]uv run tars setup[/dim]\n"
        "  • Uninstall command: [dim]uv tool uninstall <name>[/dim]\n"
        "  • Manual DB init: [dim]uv run tars db init[/dim]",
        title="Setup Overview",
        style="cyan",
    ))
    console.print()

    return Confirm.ask("Ready to proceed?", default=True)


def run_setup() -> None:
    """Run the interactive setup wizard."""
    from tars.config import create_env_file, test_connection, validate_database_url
    from tars.db import db_init, db_init_vectorizer
    from tars.rename import rename_bot

    # Show overview and get confirmation
    if not _show_overview():
        console.print("[yellow]Setup cancelled.[/yellow]")
        return

    console.print()

    # Step 1: Bot name
    console.print("[bold]Step 1:[/bold] Name your bot")
    console.print("  [dim]This will be the command you use (e.g., 'mybot search \"query\"')[/dim]")

    default_name = _get_default_name()
    while True:
        name = Prompt.ask("  Bot name", default=default_name)

        # Validate name
        available, message = _check_name_available(name)
        if not available:
            console.print(f"  [red]Invalid name:[/red] {message}")
            continue
        break

    if name != "tars":
        console.print(f"\n  Renaming bot to [cyan]{name}[/cyan]...")
        results = rename_bot(name)
        console.print(f"  [green]Done![/green] Updated {results['files']} file(s)")

        # Reinstall package to register new command
        console.print(f"  [dim]Installing '{name}' command globally...[/dim]")
        import subprocess
        result = subprocess.run(
            ["uv", "tool", "install", "-e", ".", "--force"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print(f"  [green]Command '{name}' is now available globally[/green]\n")
        else:
            console.print(f"  [yellow]Warning:[/yellow] Could not install globally. Run manually:")
            console.print(f"    [dim]uv tool install -e . --force[/dim]\n")
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

    # Create .env file and set environment variable for current process
    create_env_file(url, name)
    os.environ["DATABASE_URL"] = url  # Set for current process (dotenv already loaded at startup)
    console.print("  [green]Created .env file[/green]\n")

    # Step 3: Initialize database
    console.print("[bold]Step 3:[/bold] Initializing database")

    console.print("  [dim]Running db init...[/dim]")
    db_init()

    console.print("  [dim]Running vector init...[/dim]")
    db_init_vectorizer()

    console.print()

    # Step 4: Install Playwright browsers (needed for crawling)
    console.print("[bold]Step 4:[/bold] Installing browser for crawling")
    console.print("  [dim]Running playwright install chromium...[/dim]")

    import subprocess

    # Try multiple methods to install Playwright browsers
    # Method 1: Use uv run (works in project context)
    result = subprocess.run(
        ["uv", "run", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Method 2: Try direct playwright command
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        # Method 3: Try python -m playwright
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        console.print("  [green]Browser installed[/green]\n")
    else:
        console.print("  [yellow]Warning:[/yellow] Could not install browser automatically.")
        console.print("  [yellow]Run one of these manually:[/yellow]")
        console.print(f"    [dim]uv run playwright install chromium[/dim]")
        console.print(f"    [dim]{name} crawl[/dim] (will show install instructions)\n")

    # Done!
    console.print(Panel(
        f"[green]Setup complete![/green]\n\n"
        f"Try these commands:\n"
        f"  [cyan]{name} add https://grokipedia.com/page/Interstellar_(film)[/cyan]\n"
        f"  [cyan]{name} search \"hello\"[/cyan]\n"
        f"  [cyan]{name} help[/cyan]\n\n"
        f"[dim]To uninstall: uv tool uninstall {name}[/dim]",
        title="Success",
        style="green",
    ))
