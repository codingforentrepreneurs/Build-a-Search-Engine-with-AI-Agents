import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()

__version__ = "0.1.0"

LINKS_FILE = Path("links.csv")
FIELDNAMES = ["link", "added_at", "updated_at"]


def get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Ensure URL has https:// scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def add_link(link: str) -> None:
    from tars.db import db_add_link, is_db_configured

    link = normalize_url(link)

    if is_db_configured():
        db_add_link(link)
        return

    file_exists = LINKS_FILE.exists()
    timestamp = get_timestamp()
    with open(LINKS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({"link": link, "added_at": timestamp, "updated_at": timestamp})
    console.print(f"[green]Added:[/green] {link}")


def format_timestamp(ts: str) -> str:
    if not ts or ts == "N/A":
        return "-"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%b %d, %Y %H:%M")
    except ValueError:
        return ts


def list_links(limit: int = 10, page: int = 1) -> None:
    from tars.db import db_list_links, is_db_configured

    if is_db_configured():
        offset = (page - 1) * limit
        links, total_count, pending_embeddings = db_list_links(limit, offset)
        if not links:
            console.print("[dim]No links stored yet.[/dim]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("Link", style="cyan", overflow="fold")
        table.add_column("Title", style="white", overflow="fold")
        table.add_column("Added", style="green", no_wrap=True)
        table.add_column("Updated", style="yellow", no_wrap=True)

        for row in links:
            added = format_timestamp(row.get("added_at", ""))
            updated = format_timestamp(row.get("updated_at", ""))
            title = row.get("title") or "-"
            table.add_row(row["url"], title, added, updated)

        console.print(table)

        # Show summary stats
        total_pages = (total_count + limit - 1) // limit
        stats = f"[dim]Page {page}/{total_pages} • {total_count} total[/dim]"
        if pending_embeddings > 0:
            stats += f" • [yellow]{pending_embeddings} need embeddings[/yellow]"
        console.print(stats)
        return

    if not LINKS_FILE.exists():
        console.print("[dim]No links stored yet.[/dim]")
        return
    with open(LINKS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        links = list(reader)
    if not links:
        console.print("[dim]No links stored yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Link", style="cyan", overflow="fold")
    table.add_column("Added", style="green", no_wrap=True)
    table.add_column("Updated", style="yellow", no_wrap=True)

    for i, row in enumerate(links, start=1):
        added = format_timestamp(row.get("added_at", ""))
        updated = format_timestamp(row.get("updated_at", ""))
        table.add_row(str(i), row["link"], added, updated)

    console.print(table)


def remove_link(identifier: str) -> None:
    from tars.db import db_remove_link, db_remove_links_pattern, is_db_configured

    if is_db_configured():
        # Check if it's a glob pattern
        if "*" in identifier or "?" in identifier:
            removed = db_remove_links_pattern(identifier)
            if removed:
                console.print(f"[red]Removed {len(removed)} link(s):[/red]")
                for url in removed:
                    console.print(f"  {url}")
            else:
                console.print(f"[red]No links matching:[/red] {identifier}")
            return

        # Database mode: URL only (no index support)
        if db_remove_link(identifier):
            console.print(f"[red]Removed:[/red] {identifier}")
        else:
            console.print(f"[red]Link not found:[/red] {identifier}")
        return

    if not LINKS_FILE.exists():
        console.print("[dim]No links stored yet.[/dim]")
        return
    with open(LINKS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        links = list(reader)
    if not links:
        console.print("[dim]No links stored yet.[/dim]")
        return

    # Try to match by index first, then by URL
    to_remove = None
    if identifier.isdigit():
        idx = int(identifier) - 1
        if 0 <= idx < len(links):
            to_remove = idx

    if to_remove is None:
        for i, row in enumerate(links):
            if row["link"] == identifier:
                to_remove = i
                break

    if to_remove is None:
        console.print(f"[red]Link not found:[/red] {identifier}")
        return

    removed_link = links.pop(to_remove)
    with open(LINKS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(links)
    console.print(f"[red]Removed:[/red] {removed_link['link']}")


def update_link_timestamp(link: str) -> None:
    if not LINKS_FILE.exists():
        console.print("[dim]No links stored yet.[/dim]")
        return
    with open(LINKS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        links = list(reader)

    found = False
    for row in links:
        if row["link"] == link:
            row["updated_at"] = get_timestamp()
            found = True
            break

    if not found:
        console.print(f"[red]Link not found:[/red] {link}")
        return

    with open(LINKS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(links)
    console.print(f"[yellow]Updated:[/yellow] {link}")


def clean_list() -> None:
    if not LINKS_FILE.exists():
        console.print("[dim]No links to clean.[/dim]")
        return
    with open(LINKS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        links = list(reader)
    seen = set()
    unique = []
    for row in links:
        if row["link"] not in seen:
            seen.add(row["link"])
            unique.append(row)
    with open(LINKS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(unique)
    removed = len(links) - len(unique)
    if removed > 0:
        console.print(f"[green]Cleaned:[/green] Removed {removed} duplicate(s).")
    else:
        console.print("[dim]No duplicates found.[/dim]")


def search_links(query: str, limit: int = 10, page: int = 1) -> None:
    from tars.db import db_search, is_db_configured

    if not is_db_configured():
        console.print("[red]Search requires database configuration.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    offset = (page - 1) * limit
    results, total_count = db_search(query, limit, offset)
    if not results:
        console.print(f"[dim]No results for:[/dim] {query}")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Link", style="cyan", overflow="fold")
    table.add_column("Title", style="white", overflow="fold")
    table.add_column("Score", style="magenta", justify="right")

    for row in results:
        title = row.get("title") or "-"
        score = f"{row['score']:.4f}" if row.get("score") is not None else "-"
        table.add_row(row["url"], title, score)

    console.print(table)

    # Show pagination info
    total_pages = (total_count + limit - 1) // limit
    if total_pages > 1:
        console.print(f"\n[dim]Page {page}/{total_pages} ({total_count} total results)[/dim]")


def crawl_links(
    url: str | None = None,
    all_links: bool = False,
    missing: bool = False,
    old_days: int | None = None,
) -> None:
    """Crawl links and store extracted content in database."""
    from tars.crawl import crawl_page
    from tars.db import (
        db_generate_embeddings,
        db_get_links_to_crawl,
        db_update_crawl_data,
        db_vectorizer_status,
        is_db_configured,
    )

    if not is_db_configured():
        console.print("[red]Crawl requires database configuration.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    # Determine which links to crawl
    if url:
        urls = db_get_links_to_crawl(mode="url", url=url)
        if not urls:
            console.print(f"[red]URL not found in database:[/red] {url}")
            return
    elif all_links:
        urls = db_get_links_to_crawl(mode="all")
    elif old_days is not None:
        urls = db_get_links_to_crawl(mode="old", days=old_days)
    else:
        # Default to missing
        urls = db_get_links_to_crawl(mode="missing")

    if not urls:
        console.print("[dim]No links to crawl.[/dim]")
        return

    console.print(f"[bold]Crawling {len(urls)} link(s)...[/bold]\n")

    success_count = 0
    error_count = 0
    changed_count = 0

    for i, link_url in enumerate(urls, 1):
        console.print(f"[dim][{i}/{len(urls)}][/dim] {link_url}")

        result = crawl_page(link_url)

        # Update database with results
        updated, content_changed = db_update_crawl_data(
            url=link_url,
            title=result.title,
            description=result.description,
            content=result.content,
            http_status=result.http_status,
            crawl_error=result.error,
        )

        if result.error:
            console.print(f"  [red]Error:[/red] {result.error}")
            error_count += 1
        else:
            status = f"[green]{result.http_status}[/green]" if result.http_status == 200 else f"[yellow]{result.http_status}[/yellow]"
            title_preview = (result.title[:50] + "...") if result.title and len(result.title) > 50 else (result.title or "-")
            changed_indicator = " [cyan](changed)[/cyan]" if content_changed else ""
            console.print(f"  {status} {title_preview}{changed_indicator}")
            success_count += 1
            if content_changed:
                changed_count += 1

    console.print(f"\n[bold]Done:[/bold] {success_count} succeeded, {error_count} failed, {changed_count} changed")

    # Auto-generate embeddings if vector search is configured
    if success_count > 0:
        status = db_vectorizer_status()
        if status.get("configured"):
            console.print("\n[dim]Generating embeddings...[/dim]")
            embed_success, embed_errors = db_generate_embeddings()
            if embed_success > 0:
                console.print(f"[green]Generated {embed_success} embedding(s)[/green]")
            if embed_errors > 0:
                console.print(f"[yellow]{embed_errors} embedding(s) failed[/yellow]")


def handle_db_command(args) -> None:
    from tars.db import db_init, db_migrate, db_status

    if args.db_command == "init":
        db_init()
    elif args.db_command == "migrate":
        db_migrate()
    elif args.db_command == "status":
        db_status()
    else:
        console.print("[red]Unknown db command.[/red] Use: init, migrate, status")


def vector_search(query: str, limit: int = 10, page: int = 1) -> None:
    """Perform semantic search using vector embeddings."""
    from tars.db import db_vector_search, is_db_configured

    if not is_db_configured():
        console.print("[red]Vector search requires database configuration.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    offset = (page - 1) * limit
    results, total_count = db_vector_search(query, limit, offset)
    if not results:
        console.print(f"[dim]No results for:[/dim] {query}")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Link", style="cyan", overflow="fold")
    table.add_column("Title", style="white", overflow="fold")
    table.add_column("Distance", style="magenta", justify="right")

    for row in results:
        title = row.get("title") or "-"
        distance = f"{row['distance']:.4f}" if row.get("distance") is not None else "-"
        table.add_row(row["url"], title, distance)

    console.print(table)

    # Show pagination info
    total_pages = (total_count + limit - 1) // limit
    if total_pages > 1:
        console.print(f"\n[dim]Page {page}/{total_pages} ({total_count} total results)[/dim]")


def hybrid_search(
    query: str,
    limit: int = 10,
    page: int = 1,
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
    min_score: float = 0.005,
) -> None:
    """Perform hybrid search combining BM25 keyword and vector semantic search."""
    from tars.db import db_hybrid_search, is_db_configured

    if not is_db_configured():
        console.print("[red]Hybrid search requires database configuration.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    offset = (page - 1) * limit
    results, total_count = db_hybrid_search(
        query, limit, offset, keyword_weight, vector_weight, min_score=min_score
    )
    if not results:
        console.print(f"[dim]No results for:[/dim] {query}")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Link", style="cyan", overflow="fold")
    table.add_column("Title", style="white", overflow="fold")
    table.add_column("RRF", style="magenta", justify="right")
    table.add_column("V#", style="dim", justify="right")
    table.add_column("K#", style="dim", justify="right")

    for row in results:
        title = row.get("title") or "-"
        rrf = f"{row['rrf_score']:.4f}"
        v_rank = str(row["vector_rank"]) if row["vector_rank"] < 999 else "-"
        k_rank = str(row["keyword_rank"]) if row["keyword_rank"] < 999 else "-"
        table.add_row(row["url"], title, rrf, v_rank, k_rank)

    console.print(table)

    # Show pagination info
    total_pages = (total_count + limit - 1) // limit
    if total_pages > 1:
        console.print(f"\n[dim]Page {page}/{total_pages} ({total_count} total results)[/dim]")


def _install_web_dependencies() -> bool:
    """Install web dependencies (FastAPI, uvicorn, jinja2, python-multipart).

    Returns True if installation succeeded.
    """
    import subprocess

    console.print("[yellow]Installing web dependencies...[/yellow]")
    packages = ["fastapi", "uvicorn[standard]", "jinja2", "python-multipart"]

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + packages,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode == 0:
        console.print("[green]Web dependencies installed successfully![/green]")
        return True
    else:
        console.print(f"[red]Failed to install dependencies:[/red] {result.stderr}")
        return False


def start_web_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
    open_browser: bool = False,
) -> None:
    """Start the tars web interface server."""
    try:
        import uvicorn
    except ImportError:
        if not _install_web_dependencies():
            return
        import uvicorn

    try:
        from tars.web import app
        if app is None:
            if not _install_web_dependencies():
                return
            # Reimport after install
            import importlib
            import tars.web
            importlib.reload(tars.web)
            from tars.web import app
            if app is None:
                console.print("[red]Error:[/red] Failed to load web module after install.")
                return
    except ImportError as e:
        console.print(f"[red]Error:[/red] Failed to import web module: {e}")
        return

    url = f"http://{host}:{port}"
    console.print(f"[bold]Starting tars web interface at {url}[/bold]")

    if open_browser:
        import threading
        import time
        import webbrowser

        def open_browser_delayed():
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open(url)

        threading.Thread(target=open_browser_delayed, daemon=True).start()

    uvicorn.run(
        "tars.web:app",
        host=host,
        port=port,
        reload=reload,
    )


def embed_links(limit: int | None = None) -> None:
    """Generate embeddings for links that don't have them."""
    from tars.db import db_generate_embeddings, db_vectorizer_status, is_db_configured

    if not is_db_configured():
        console.print("[red]Embed requires database configuration.[/red]")
        return

    status = db_vectorizer_status()
    if not status.get("configured"):
        console.print("[red]Vector search not initialized.[/red]")
        console.print("Run: tars vector init")
        return

    pending = status.get("pending_items", 0)
    if pending == 0:
        console.print("[dim]All links already have embeddings.[/dim]")
        return

    to_process = limit if limit else pending
    console.print(f"[bold]Generating embeddings for {to_process} link(s)...[/bold]\n")

    success, errors = db_generate_embeddings(limit, show_progress=True)

    console.print(f"\n[bold]Done:[/bold] {success} succeeded, {errors} failed")


def handle_vector_command(args) -> None:
    from tars.db import db_init_vectorizer, db_vectorizer_status, is_db_configured

    if not is_db_configured():
        console.print("[red]Vector commands require database configuration.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    cmd = args.vector_cmd

    if cmd == "init":
        db_init_vectorizer()
    elif cmd == "status":
        status = db_vectorizer_status()
        if not status.get("configured"):
            console.print("[yellow]Vector search not configured.[/yellow]")
            console.print("Run: tars vector init")
            return

        console.print("[green]Vector search:[/green] configured")
        console.print(f"[dim]Links:[/dim] {status.get('link_count')}")
        console.print(f"[dim]Embeddings:[/dim] {status.get('embedding_count')}")
        pending = status.get('pending_items', 0)
        if pending > 0:
            console.print(f"[yellow]Pending:[/yellow] {pending} links need embeddings")
            console.print("[dim]Run: tars vector embed[/dim]")
        else:
            console.print("[green]Pending:[/green] 0 (all links embedded)")
    elif cmd == "embed":
        embed_links(args.limit)
    else:
        console.print("[red]Usage:[/red] tars db vector <init|status|embed>")


def show_help() -> None:
    """Display all commands with examples."""
    console.print("[bold cyan]tars[/bold cyan] - Personal search engine CLI\n")

    sections = [
        (
            "Link Management",
            [
                ("add <url>", "Add a new link", "tars add https://example.com"),
                ("list", "List stored links", "tars list -n 20 -p 2"),
                ("remove <id|url>", "Remove by URL or glob pattern", "tars remove https://example.com\ntars remove '*.pdf'"),
                ("update <url>", "Update timestamp for a link", "tars update https://example.com"),
                ("clean-list", "Remove duplicate links", "tars clean-list"),
            ],
        ),
        (
            "Search",
            [
                ("search <query>", "Hybrid search (BM25 + vector)", "tars search \"python async\"\ntars search \"api\" --keyword-weight 0.7 --vector-weight 0.3"),
                ("text_search <query>", "BM25 full-text search only", "tars text_search \"database\""),
                ("vector <query>", "Semantic vector search only", "tars vector \"machine learning concepts\""),
            ],
        ),
        (
            "Crawling",
            [
                ("crawl", "Crawl uncrawled links", "tars crawl"),
                ("crawl <url>", "Crawl a specific URL", "tars crawl https://example.com"),
                ("crawl --all", "Re-crawl all links", "tars crawl --all"),
                ("crawl --missing", "Crawl links never crawled", "tars crawl --missing"),
                ("crawl --old N", "Crawl links not crawled in N days", "tars crawl --old 7"),
            ],
        ),
        (
            "Database",
            [
                ("db init", "Initialize database schema", "tars db init"),
                ("db migrate", "Import links from CSV", "tars db migrate"),
                ("db status", "Show database status", "tars db status"),
                ("db vector init", "Initialize vector column/index", "tars db vector init"),
                ("db vector embed", "Generate embeddings", "tars db vector embed\ntars db vector embed -n 100"),
                ("db vector status", "Show embedding status", "tars db vector status"),
            ],
        ),
        (
            "Server",
            [
                ("web", "Start web interface", "tars web\ntars web --port 3000 --open"),
                ("mcp", "Start MCP server (stdio)", "tars mcp"),
                ("mcp --sse", "Start MCP server (HTTP/SSE)", "tars mcp --sse --port 8000"),
            ],
        ),
    ]

    for section_name, commands in sections:
        console.print(f"[bold yellow]{section_name}[/bold yellow]")
        for cmd, desc, example in commands:
            console.print(f"  [green]{cmd}[/green]")
            console.print(f"    {desc}")
            for line in example.split("\n"):
                console.print(f"    [dim]$ {line}[/dim]")
        console.print()

    console.print("[bold yellow]Options[/bold yellow]")
    console.print("  [green]--version[/green]  Show version")
    console.print("  [green]--help[/green]     Show argparse help\n")


def main():
    parser = argparse.ArgumentParser(
        prog="tars",
        description="A minimal CLI application"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # Help command
    subparsers.add_parser("help", help="Show all commands with examples")

    # Setup wizard
    subparsers.add_parser("setup", help="Run interactive setup wizard")

    add_parser = subparsers.add_parser("add", help="Add a link")
    add_parser.add_argument("link", help="The link to add")

    remove_parser = subparsers.add_parser("remove", help="Remove a link by index or URL")
    remove_parser.add_argument("identifier", help="The link index (from list) or URL to remove")

    update_parser = subparsers.add_parser("update", help="Update the timestamp for a link")
    update_parser.add_argument("link", help="The link URL to update")

    list_parser = subparsers.add_parser("list", help="List stored links (most recent first)")
    list_parser.add_argument("-n", "--limit", type=int, default=10, help="Results per page (default: 10)")
    list_parser.add_argument("-p", "--page", type=int, default=1, help="Page number (default: 1)")
    subparsers.add_parser("clean-list", help="Remove duplicate links")

    # Database commands
    db_parser = subparsers.add_parser("db", help="Database management commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_subparsers.add_parser("init", help="Initialize database schema")
    db_subparsers.add_parser("migrate", help="Import links from CSV to database")
    db_subparsers.add_parser("status", help="Show database connection status")
    # Vector subcommand under db
    vector_db_parser = db_subparsers.add_parser("vector", help="Vector embedding management")
    vector_db_parser.add_argument("vector_cmd", nargs="?", help="Command: init | status | embed")
    vector_db_parser.add_argument("-n", "--limit", type=int, help="Limit number of links to embed (default: all pending)")

    # Text search command (BM25)
    text_search_parser = subparsers.add_parser("text_search", help="Search links using BM25 full-text search")
    text_search_parser.add_argument("query", help="Search query")
    text_search_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum results (default: 10)")
    text_search_parser.add_argument("-p", "--page", type=int, default=1, help="Page number (default: 1)")

    # Crawl command
    crawl_parser = subparsers.add_parser("crawl", help="Crawl links and extract content")
    crawl_parser.add_argument("url", nargs="?", help="Specific URL to crawl (optional)")
    crawl_parser.add_argument("--all", action="store_true", dest="crawl_all", help="Crawl all links")
    crawl_parser.add_argument("--missing", action="store_true", help="Crawl links never crawled (default)")
    crawl_parser.add_argument("--old", type=int, metavar="DAYS", help="Crawl links not crawled in N days")

    # Top-level vector search shortcut: tars vector "<query>"
    vector_search_parser = subparsers.add_parser("vector", help="Semantic vector search: tars vector \"<query>\"")
    vector_search_parser.add_argument("query", help="Search query")
    vector_search_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum results (default: 10)")
    vector_search_parser.add_argument("-p", "--page", type=int, default=1, help="Page number (default: 1)")

    # Hybrid search (combines BM25 + vector)
    search_parser = subparsers.add_parser("search", help="Hybrid search (BM25 + vector): tars search \"<query>\"")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum results (default: 10)")
    search_parser.add_argument("-p", "--page", type=int, default=1, help="Page number (default: 1)")
    search_parser.add_argument("--keyword-weight", type=float, default=0.5, help="Weight for keyword/BM25 search (0-1, default: 0.5)")
    search_parser.add_argument("--vector-weight", type=float, default=0.5, help="Weight for vector/semantic search (0-1, default: 0.5)")
    search_parser.add_argument("--min-score", type=float, default=0.005, help="Minimum RRF score threshold (default: 0.005)")

    # Web server command
    web_parser = subparsers.add_parser("web", help="Start the tars web interface")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    web_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    web_parser.add_argument("--open", dest="open_browser", action="store_true", help="Open browser automatically")

    # MCP server command
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server for LLM tool access")
    mcp_parser.add_argument("--sse", action="store_true", help="Run as HTTP/SSE server (for Claude Code remote)")
    mcp_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    mcp_parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")

    args = parser.parse_args()

    try:
        if args.command == "help":
            show_help()
        elif args.command == "setup":
            from tars.setup import run_setup
            run_setup()
        elif args.command == "add":
            add_link(args.link)
        elif args.command == "remove":
            remove_link(args.identifier)
        elif args.command == "update":
            update_link_timestamp(args.link)
        elif args.command == "list":
            list_links(args.limit, args.page)
        elif args.command == "clean-list":
            clean_list()
        elif args.command == "db":
            if args.db_command == "vector":
                handle_vector_command(args)
            elif args.db_command:
                handle_db_command(args)
            else:
                db_parser.print_help()
        elif args.command == "text_search":
            search_links(args.query, args.limit, args.page)
        elif args.command == "crawl":
            crawl_links(
                url=args.url,
                all_links=args.crawl_all,
                missing=args.missing,
                old_days=args.old,
            )
        elif args.command == "vector":
            vector_search(args.query, args.limit, args.page)
        elif args.command == "search":
            hybrid_search(
                args.query,
                args.limit,
                args.page,
                args.keyword_weight,
                args.vector_weight,
                args.min_score,
            )
        elif args.command == "web":
            start_web_server(
                host=args.host,
                port=args.port,
                reload=args.reload,
                open_browser=args.open_browser,
            )
        elif args.command == "mcp":
            from tars.mcp import main as mcp_main
            transport = "sse" if args.sse else "stdio"
            mcp_main(transport=transport, host=args.host, port=args.port)
        else:
            show_help()
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
