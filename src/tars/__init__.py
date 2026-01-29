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


def list_links() -> None:
    from tars.db import db_list_links, is_db_configured

    if is_db_configured():
        links = db_list_links()
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


def search_links(query: str, limit: int = 10) -> None:
    from tars.db import db_search, is_db_configured

    if not is_db_configured():
        console.print("[red]Search requires database configuration.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    results = db_search(query, limit)
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


def crawl_links(
    url: str | None = None,
    all_links: bool = False,
    missing: bool = False,
    old_days: int | None = None,
) -> None:
    """Crawl links and store extracted content in database."""
    from tars.crawl import crawl_page
    from tars.db import db_get_links_to_crawl, db_update_crawl_data, is_db_configured

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

    for i, link_url in enumerate(urls, 1):
        console.print(f"[dim][{i}/{len(urls)}][/dim] {link_url}")

        result = crawl_page(link_url)

        # Update database with results
        db_update_crawl_data(
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
            console.print(f"  {status} {title_preview}")
            success_count += 1

    console.print(f"\n[bold]Done:[/bold] {success_count} succeeded, {error_count} failed")


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


def main():
    parser = argparse.ArgumentParser(
        prog="tars",
        description="A minimal CLI application"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a link")
    add_parser.add_argument("link", help="The link to add")

    remove_parser = subparsers.add_parser("remove", help="Remove a link by index or URL")
    remove_parser.add_argument("identifier", help="The link index (from list) or URL to remove")

    update_parser = subparsers.add_parser("update", help="Update the timestamp for a link")
    update_parser.add_argument("link", help="The link URL to update")

    subparsers.add_parser("list", help="List all stored links")
    subparsers.add_parser("clean-list", help="Remove duplicate links")

    # Database commands
    db_parser = subparsers.add_parser("db", help="Database management commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_subparsers.add_parser("init", help="Initialize database schema")
    db_subparsers.add_parser("migrate", help="Import links from CSV to database")
    db_subparsers.add_parser("status", help="Show database connection status")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search links using BM25 full-text search")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum results (default: 10)")

    # Crawl command
    crawl_parser = subparsers.add_parser("crawl", help="Crawl links and extract content")
    crawl_parser.add_argument("url", nargs="?", help="Specific URL to crawl (optional)")
    crawl_parser.add_argument("--all", action="store_true", dest="crawl_all", help="Crawl all links")
    crawl_parser.add_argument("--missing", action="store_true", help="Crawl links never crawled (default)")
    crawl_parser.add_argument("--old", type=int, metavar="DAYS", help="Crawl links not crawled in N days")

    args = parser.parse_args()

    try:
        if args.command == "add":
            add_link(args.link)
        elif args.command == "remove":
            remove_link(args.identifier)
        elif args.command == "update":
            update_link_timestamp(args.link)
        elif args.command == "list":
            list_links()
        elif args.command == "clean-list":
            clean_list()
        elif args.command == "db":
            if args.db_command:
                handle_db_command(args)
            else:
                db_parser.print_help()
        elif args.command == "search":
            search_links(args.query, args.limit)
        elif args.command == "crawl":
            crawl_links(
                url=args.url,
                all_links=args.crawl_all,
                missing=args.missing,
                old_days=args.old,
            )
        else:
            parser.print_help()
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
