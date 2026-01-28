import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

__version__ = "0.1.0"

LINKS_FILE = Path("links.csv")
FIELDNAMES = ["link", "added_at", "updated_at"]


def get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_link(link: str) -> None:
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

    args = parser.parse_args()

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
    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
