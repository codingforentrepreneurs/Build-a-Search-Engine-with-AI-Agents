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

            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'links'
                );
            """)
            table_exists = cur.fetchone()[0]

            if not table_exists:
                # Create links table with full schema
                cur.execute("""
                    CREATE TABLE links (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        url TEXT UNIQUE NOT NULL,
                        title TEXT,
                        description TEXT,
                        content TEXT,
                        notes TEXT,
                        tags TEXT[],
                        added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        crawled_at TIMESTAMPTZ,
                        http_status INTEGER,
                        crawl_error TEXT,
                        search_text TEXT GENERATED ALWAYS AS (
                            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                                COALESCE(url, '') || ' ' ||
                                COALESCE(title, '') || ' ' ||
                                COALESCE(description, '') || ' ' ||
                                COALESCE(content, '') || ' ' ||
                                COALESCE(notes, ''),
                            '.', ' '), '/', ' '), '-', ' '), '_', ' '), ':', ' '), '//', ' ')
                        ) STORED
                    );
                """)
                console.print("[green]Created links table.[/green]")
            else:
                # Add missing columns for Phase 2
                migrations = [
                    ("description", "ALTER TABLE links ADD COLUMN IF NOT EXISTS description TEXT;"),
                    ("http_status", "ALTER TABLE links ADD COLUMN IF NOT EXISTS http_status INTEGER;"),
                    ("crawl_error", "ALTER TABLE links ADD COLUMN IF NOT EXISTS crawl_error TEXT;"),
                ]

                for col_name, sql in migrations:
                    try:
                        cur.execute(sql)
                        console.print(f"[green]Added {col_name} column.[/green]")
                    except Exception:
                        pass  # Column might already exist

                # Check if search_text column exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'links' AND column_name = 'search_text'
                    );
                """)
                has_search_text = cur.fetchone()[0]

                if not has_search_text:
                    # Drop old index if exists
                    cur.execute("DROP INDEX IF EXISTS links_url_bm25_idx;")

                    # Add search_text generated column
                    cur.execute("""
                        ALTER TABLE links ADD COLUMN search_text TEXT GENERATED ALWAYS AS (
                            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                                COALESCE(url, '') || ' ' ||
                                COALESCE(title, '') || ' ' ||
                                COALESCE(description, '') || ' ' ||
                                COALESCE(content, '') || ' ' ||
                                COALESCE(notes, ''),
                            '.', ' '), '/', ' '), '-', ' '), '_', ' '), ':', ' '), '//', ' ')
                        ) STORED;
                    """)
                    console.print("[green]Added search_text column.[/green]")

            # Create BM25 index on search_text for full-text search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS links_search_bm25_idx
                ON links USING bm25(search_text) WITH (text_config='simple');
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


def db_remove_links_pattern(pattern: str) -> list[str]:
    """Remove links matching a glob pattern. Returns list of removed URLs.

    Supports * (any characters) and ? (single character).
    Example: "*.example.com" matches "https://www.example.com", "https://api.example.com"
    """
    # Convert glob pattern to SQL LIKE pattern
    # * -> % (any characters), ? -> _ (single character)
    like_pattern = pattern.replace("*", "%").replace("?", "_")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # First get the URLs we're about to delete
            cur.execute("SELECT url FROM links WHERE url LIKE %s", (like_pattern,))
            urls = [row[0] for row in cur.fetchall()]

            if urls:
                cur.execute("DELETE FROM links WHERE url LIKE %s", (like_pattern,))
                conn.commit()

            return urls


def db_search(query: str, limit: int = 10) -> list[dict]:
    """Search links using BM25 full-text search on search_text."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT url, title, description, added_at,
                       search_text <@> to_bm25query(%s, 'links_search_bm25_idx') as score
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
            "description": row[2],
            "added_at": row[3].isoformat() if row[3] else None,
            "score": row[4],
        }
        for row in rows
    ]


def db_update_crawl_data(
    url: str,
    title: str | None = None,
    description: str | None = None,
    content: str | None = None,
    http_status: int | None = None,
    crawl_error: str | None = None,
) -> bool:
    """Update a link with crawled data. Returns True if updated."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE links
                SET title = COALESCE(%s, title),
                    description = COALESCE(%s, description),
                    content = COALESCE(%s, content),
                    http_status = %s,
                    crawl_error = %s,
                    crawled_at = NOW(),
                    updated_at = NOW()
                WHERE url = %s
                """,
                (title, description, content, http_status, crawl_error, url),
            )
            conn.commit()
            return cur.rowcount > 0


def db_get_links_to_crawl(
    mode: str = "missing",
    days: int = 7,
    url: str | None = None,
) -> list[str]:
    """
    Get list of URLs to crawl based on mode.

    Modes:
    - "missing": Links never crawled (crawled_at IS NULL)
    - "all": All links
    - "old": Links not crawled in last N days
    - "url": Specific URL (returns single-item list if exists)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if url:
                cur.execute("SELECT url FROM links WHERE url = %s", (url,))
            elif mode == "missing":
                cur.execute(
                    "SELECT url FROM links WHERE crawled_at IS NULL ORDER BY added_at"
                )
            elif mode == "all":
                cur.execute("SELECT url FROM links ORDER BY added_at")
            elif mode == "old":
                cur.execute(
                    """
                    SELECT url FROM links
                    WHERE crawled_at IS NULL
                       OR crawled_at < NOW() - INTERVAL '%s days'
                    ORDER BY crawled_at NULLS FIRST, added_at
                    """,
                    (days,),
                )
            else:
                return []

            return [row[0] for row in cur.fetchall()]
