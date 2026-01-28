"""Database connection and operations for tars."""

import csv
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import psycopg
from rich.console import Console

console = Console()

LINKS_FILE = Path("links.csv")


def get_db_config() -> dict:
    """Load database configuration from environment variables."""
    if database_url := os.environ.get("DATABASE_URL"):
        return {"conninfo": database_url}

    # Fall back to individual PG* environment variables
    config = {}
    if host := os.environ.get("PGHOST"):
        config["host"] = host
    if port := os.environ.get("PGPORT"):
        config["port"] = int(port)
    if dbname := os.environ.get("PGDATABASE"):
        config["dbname"] = dbname
    if user := os.environ.get("PGUSER"):
        config["user"] = user
    if password := os.environ.get("PGPASSWORD"):
        config["password"] = password

    if not config:
        return {}

    return config


def is_db_configured() -> bool:
    """Check if database is configured via environment variables."""
    return bool(get_db_config())


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Context manager for database connections."""
    config = get_db_config()
    if not config:
        raise RuntimeError(
            "Database not configured. Set DATABASE_URL or PG* environment variables.\n"
            "Example: export DATABASE_URL='postgresql://user:pass@host:5432/dbname'"
        )

    try:
        conn = psycopg.connect(**config, connect_timeout=5)
        try:
            yield conn
        finally:
            conn.close()
    except psycopg.OperationalError as e:
        raise RuntimeError(f"Failed to connect to database: {e}") from e


def db_init() -> None:
    """Initialize database schema with pg_textsearch extension and links table."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch;")

            # Create links table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    content TEXT,
                    notes TEXT,
                    tags TEXT[],
                    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    crawled_at TIMESTAMPTZ
                );
            """)

            # Create BM25 index on URL
            cur.execute("""
                CREATE INDEX IF NOT EXISTS links_url_bm25_idx
                ON links USING bm25(url) WITH (text_config='simple');
            """)

            conn.commit()

    console.print("[green]Database initialized successfully.[/green]")


def db_migrate() -> None:
    """Import links from CSV file into database."""
    if not LINKS_FILE.exists():
        console.print("[dim]No links.csv file found to migrate.[/dim]")
        return

    with open(LINKS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        links = list(reader)

    if not links:
        console.print("[dim]No links found in CSV file.[/dim]")
        return

    imported = 0
    skipped = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            for row in links:
                try:
                    cur.execute(
                        """
                        INSERT INTO links (url, added_at, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (url) DO NOTHING
                        """,
                        (row["link"], row.get("added_at"), row.get("updated_at")),
                    )
                    if cur.rowcount > 0:
                        imported += 1
                    else:
                        skipped += 1
                except Exception as e:
                    console.print(f"[yellow]Warning:[/yellow] Failed to import {row['link']}: {e}")
                    skipped += 1

            conn.commit()

    console.print(f"[green]Migration complete:[/green] {imported} imported, {skipped} skipped (duplicates)")


def db_status() -> None:
    """Show database connection info and statistics."""
    config = get_db_config()
    if not config:
        console.print("[red]Database not configured.[/red]")
        console.print("Set DATABASE_URL or PG* environment variables.")
        return

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get link count
                cur.execute("SELECT COUNT(*) FROM links;")
                count = cur.fetchone()[0]

                # Get database info
                cur.execute("SELECT current_database(), current_user, version();")
                db_name, db_user, db_version = cur.fetchone()

        console.print("[green]Connection:[/green] OK")
        console.print(f"[dim]Database:[/dim] {db_name}")
        console.print(f"[dim]User:[/dim] {db_user}")
        console.print(f"[dim]Links:[/dim] {count}")
    except RuntimeError as e:
        console.print(f"[red]Connection failed:[/red] {e}")


def db_add_link(url: str) -> None:
    """Add a link to the database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO links (url)
                    VALUES (%s)
                    RETURNING id
                    """,
                    (url,),
                )
                conn.commit()
                console.print(f"[green]Added:[/green] {url}")
            except psycopg.errors.UniqueViolation:
                console.print(f"[yellow]Already exists:[/yellow] {url}")


def db_list_links() -> list[dict]:
    """List all links from database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT url, title, added_at, updated_at
                FROM links
                ORDER BY added_at DESC
                """
            )
            rows = cur.fetchall()

    return [
        {
            "url": row[0],
            "title": row[1],
            "added_at": row[2].isoformat() if row[2] else None,
            "updated_at": row[3].isoformat() if row[3] else None,
        }
        for row in rows
    ]


def db_remove_link(url: str) -> bool:
    """Remove a link from database by URL. Returns True if removed."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM links WHERE url = %s", (url,))
            conn.commit()
            return cur.rowcount > 0


def db_search(query: str, limit: int = 10) -> list[dict]:
    """Search links using BM25 full-text search on URL."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT url, title, added_at, url <@> %s as score
                FROM links
                ORDER BY score
                LIMIT %s
                """,
                (query, limit),
            )
            rows = cur.fetchall()

    return [
        {
            "url": row[0],
            "title": row[1],
            "added_at": row[2].isoformat() if row[2] else None,
            "score": row[3],
        }
        for row in rows
    ]
