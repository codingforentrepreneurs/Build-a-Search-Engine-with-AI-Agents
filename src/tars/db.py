"""Database connection and operations for tars."""

import csv
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import psycopg
from rich.console import Console

console = Console()

LINKS_FILE = Path("links.csv")

# Default cache TTL in seconds (1 hour)
DEFAULT_CACHE_TTL = int(os.environ.get("TARS_CACHE_TTL", 3600))


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
            # Create extensions
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS ai CASCADE;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;")

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
                        hidden BOOLEAN NOT NULL DEFAULT FALSE,
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
                    ("hidden", "ALTER TABLE links ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;"),
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

            # Create search_cache table for hybrid search caching
            cur.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    query_hash TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    keyword_weight NUMERIC(3,2) NOT NULL,
                    vector_weight NUMERIC(3,2) NOT NULL,
                    results JSONB NOT NULL,
                    total_count INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(query_hash, keyword_weight, vector_weight)
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS search_cache_expires_idx
                ON search_cache(expires_at);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS search_cache_query_idx
                ON search_cache(query_hash);
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


# =============================================================================
# Search Cache Functions
# =============================================================================


def _compute_cache_key(query: str, keyword_weight: float, vector_weight: float) -> str:
    """Compute SHA256 hash for cache key from query and weights."""
    normalized = f"{query.lower().strip()}:{keyword_weight}:{vector_weight}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def db_cache_search(
    query: str,
    keyword_weight: float,
    vector_weight: float,
    results: list[dict],
    total_count: int,
    ttl: int = DEFAULT_CACHE_TTL,
) -> None:
    """Store search results in cache.

    Args:
        query: The original search query
        keyword_weight: BM25 keyword weight used
        vector_weight: Vector similarity weight used
        results: List of search result dictionaries
        total_count: Total count of results
        ttl: Time to live in seconds (default from TARS_CACHE_TTL env var or 1 hour)
    """
    query_hash = _compute_cache_key(query, keyword_weight, vector_weight)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO search_cache (query_hash, query_text, keyword_weight, vector_weight, results, total_count, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW() + INTERVAL '%s seconds')
                ON CONFLICT (query_hash, keyword_weight, vector_weight)
                DO UPDATE SET
                    results = EXCLUDED.results,
                    total_count = EXCLUDED.total_count,
                    created_at = NOW(),
                    expires_at = NOW() + INTERVAL '%s seconds'
                """,
                (query_hash, query, keyword_weight, vector_weight, json.dumps(results), total_count, ttl, ttl),
            )
            conn.commit()


def db_get_cached_search(
    query: str,
    keyword_weight: float,
    vector_weight: float,
) -> tuple[list[dict], int] | None:
    """Retrieve cached search results if not expired.

    Args:
        query: The search query
        keyword_weight: BM25 keyword weight
        vector_weight: Vector similarity weight

    Returns:
        (results, total_count) tuple if cache hit, None if miss or expired.
    """
    query_hash = _compute_cache_key(query, keyword_weight, vector_weight)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT results, total_count
                FROM search_cache
                WHERE query_hash = %s
                AND keyword_weight = %s
                AND vector_weight = %s
                AND expires_at > NOW()
                """,
                (query_hash, keyword_weight, vector_weight),
            )
            row = cur.fetchone()
            if row:
                return (row[0], row[1])
            return None


def db_invalidate_search_cache() -> int:
    """Clear all search cache entries.

    Returns the number of entries deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM search_cache")
            deleted = cur.rowcount
            conn.commit()
            return deleted


def db_cleanup_expired_cache() -> int:
    """Remove expired cache entries.

    Returns the number of entries deleted.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM search_cache WHERE expires_at <= NOW()")
            deleted = cur.rowcount
            conn.commit()
            return deleted


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
                # Invalidate search cache when new link added
                db_invalidate_search_cache()
                console.print(f"[green]Added:[/green] {url}")
            except psycopg.errors.UniqueViolation:
                console.print(f"[yellow]Already exists:[/yellow] {url}")


def db_list_links(limit: int = 10, offset: int = 0) -> tuple[list[dict], int, int]:
    """List links from database with pagination.

    Returns: (links, total_count, pending_embeddings)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get total count
            cur.execute("SELECT COUNT(*) FROM links")
            total_count = cur.fetchone()[0]

            # Get pending embeddings count (if column exists)
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            has_embedding_col = cur.fetchone()[0]
            if has_embedding_col:
                cur.execute("SELECT COUNT(*) FROM links WHERE embedding IS NULL")
                pending_embeddings = cur.fetchone()[0]
            else:
                pending_embeddings = 0

            # Get paginated links, ordered by last updated
            cur.execute(
                """
                SELECT url, title, added_at, updated_at
                FROM links
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()

    links = [
        {
            "url": row[0],
            "title": row[1],
            "added_at": row[2].isoformat() if row[2] else None,
            "updated_at": row[3].isoformat() if row[3] else None,
        }
        for row in rows
    ]
    return links, total_count, pending_embeddings


def db_remove_link(url: str) -> bool:
    """Remove a link from database by URL. Returns True if removed."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM links WHERE url = %s", (url,))
            conn.commit()
            if cur.rowcount > 0:
                db_invalidate_search_cache()
                return True
            return False


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
                db_invalidate_search_cache()

            return urls


def db_search(query: str, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Search links using BM25 full-text search on search_text.

    BM25 returns negative scores where lower (more negative) = better match.
    Score of 0 means no match.
    Hidden links are excluded from results.

    Returns (results, total_count).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get total count first (exclude 4xx/5xx error pages and hidden links)
            cur.execute(
                """
                SELECT COUNT(*)
                FROM links
                WHERE search_text <@> to_bm25query(%s, 'links_search_bm25_idx') < 0
                AND (http_status IS NULL OR http_status < 400)
                AND hidden = FALSE
                """,
                (query,),
            )
            total_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT url, title, description, added_at,
                       search_text <@> to_bm25query(%s, 'links_search_bm25_idx') as score
                FROM links
                WHERE search_text <@> to_bm25query(%s, 'links_search_bm25_idx') < 0
                AND (http_status IS NULL OR http_status < 400)
                AND hidden = FALSE
                ORDER BY score
                LIMIT %s OFFSET %s
                """,
                (query, query, limit, offset),
            )
            rows = cur.fetchall()

    results = [
        {
            "url": row[0],
            "title": row[1],
            "description": row[2],
            "added_at": row[3].isoformat() if row[3] else None,
            "score": abs(row[4]),  # Convert to positive for display
        }
        for row in rows
    ]
    return (results, total_count)


def db_update_crawl_data(
    url: str,
    title: str | None = None,
    description: str | None = None,
    content: str | None = None,
    http_status: int | None = None,
    crawl_error: str | None = None,
) -> tuple[bool, bool]:
    """Update a link with crawled data.

    Returns (updated, content_changed):
    - updated: True if the row was updated
    - content_changed: True if the content was different from before

    Only clears the embedding (to trigger re-embedding) if content changed.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if content changed (to decide whether to clear embedding)
            cur.execute(
                "SELECT content FROM links WHERE url = %s",
                (url,),
            )
            row = cur.fetchone()
            if not row:
                return (False, False)

            old_content = row[0]
            content_changed = content is not None and content != old_content

            # Check if embedding column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            has_embedding_col = cur.fetchone()[0]

            if content_changed and has_embedding_col:
                # Content changed - update and clear embedding for re-generation
                cur.execute(
                    """
                    UPDATE links
                    SET title = COALESCE(%s, title),
                        description = COALESCE(%s, description),
                        content = %s,
                        http_status = %s,
                        crawl_error = %s,
                        crawled_at = NOW(),
                        updated_at = NOW(),
                        embedding = NULL
                    WHERE url = %s
                    """,
                    (title, description, content, http_status, crawl_error, url),
                )
            else:
                # Content unchanged or no embedding column - update without touching embedding
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
            # Invalidate search cache when content changes
            if content_changed:
                db_invalidate_search_cache()
            return (cur.rowcount > 0, content_changed)


def db_get_links_to_crawl(
    mode: str = "missing",
    days: int = 7,
    url: str | None = None,
) -> list[str]:
    """
    Get list of URLs to crawl based on mode.
    Hidden links are excluded from crawl operations.

    Modes:
    - "missing": Links never crawled (crawled_at IS NULL)
    - "all": All links
    - "old": Links not crawled in last N days
    - "url": Specific URL (returns single-item list if exists)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if url:
                # For specific URL, still allow crawling even if hidden
                cur.execute("SELECT url FROM links WHERE url = %s", (url,))
            elif mode == "missing":
                cur.execute(
                    "SELECT url FROM links WHERE crawled_at IS NULL AND hidden = FALSE ORDER BY added_at"
                )
            elif mode == "all":
                cur.execute("SELECT url FROM links WHERE hidden = FALSE ORDER BY added_at")
            elif mode == "old":
                cur.execute(
                    """
                    SELECT url FROM links
                    WHERE (crawled_at IS NULL
                       OR crawled_at < NOW() - INTERVAL '%s days')
                       AND hidden = FALSE
                    ORDER BY crawled_at NULLS FIRST, added_at
                    """,
                    (days,),
                )
            else:
                return []

            return [row[0] for row in cur.fetchall()]


def db_init_vectorizer() -> None:
    """Initialize vector column and HNSW index for semantic search on links."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if embedding column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            has_embedding = cur.fetchone()[0]

            if has_embedding:
                console.print("[dim]Vector column already exists.[/dim]")
            else:
                # Add embedding column (1536 dimensions for text-embedding-3-small)
                cur.execute("""
                    ALTER TABLE links
                    ADD COLUMN embedding vector(1536);
                """)
                console.print("[green]Added embedding column.[/green]")

            # Create HNSW index for fast similarity search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS links_embedding_hnsw_idx
                ON links USING hnsw (embedding vector_cosine_ops);
            """)
            conn.commit()

    console.print("[green]Vector search initialized.[/green]")
    console.print("[dim]Run 'tars vector embed' to generate embeddings for links.[/dim]")


def db_vectorizer_status() -> dict:
    """Get vector embedding status."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if embedding column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            if not cur.fetchone()[0]:
                return {"configured": False}

            # Count links with and without embeddings
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(embedding) as with_embedding
                FROM links;
            """)
            row = cur.fetchone()
            total = row[0]
            with_embedding = row[1]

            return {
                "configured": True,
                "link_count": total,
                "embedding_count": with_embedding,
                "pending_items": total - with_embedding,
            }


def db_generate_embeddings(
    limit: int | None = None, show_progress: bool = False
) -> tuple[int, int]:
    """Generate embeddings for links missing them using ai.openai_embed().

    Returns (success_count, error_count).
    Uses Tiger Cloud's managed OpenAI API key.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get links without embeddings
            query = """
                SELECT id, url, search_text
                FROM links
                WHERE embedding IS NULL
                AND search_text IS NOT NULL
                AND search_text != ''
            """
            if limit:
                query += f" LIMIT {limit}"

            cur.execute(query)
            rows = cur.fetchall()

            if not rows:
                return (0, 0)

            success = 0
            errors = 0

            if show_progress:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Embedding...", total=len(rows))

                    for link_id, url, search_text in rows:
                        # Show truncated URL in progress
                        display_url = url[:50] + "..." if len(url) > 50 else url
                        progress.update(task, description=f"[dim]{display_url}[/dim]")

                        try:
                            text = search_text[:30000] if search_text else ""
                            cur.execute(
                                """
                                UPDATE links
                                SET embedding = ai.openai_embed(
                                    'text-embedding-3-small',
                                    %s
                                )::vector(1536)
                                WHERE id = %s;
                                """,
                                (text, link_id),
                            )
                            conn.commit()
                            success += 1
                        except Exception as e:
                            conn.rollback()
                            errors += 1
                            progress.console.print(f"[red]Error:[/red] {display_url}: {e}")

                        progress.advance(task)
            else:
                for link_id, url, search_text in rows:
                    try:
                        text = search_text[:30000] if search_text else ""
                        cur.execute(
                            """
                            UPDATE links
                            SET embedding = ai.openai_embed(
                                'text-embedding-3-small',
                                %s
                            )::vector(1536)
                            WHERE id = %s;
                            """,
                            (text, link_id),
                        )
                        conn.commit()
                        success += 1
                    except Exception as e:
                        conn.rollback()
                        errors += 1
                        console.print(f"[red]Error embedding {link_id}:[/red] {e}")

            return (success, errors)


def db_vector_search(
    query: str, limit: int = 10, offset: int = 0, max_distance: float = 0.8
) -> tuple[list[dict], int]:
    """Search links using vector similarity (semantic search).

    Uses Tiger Cloud's managed OpenAI API key.
    Only returns results with distance <= max_distance (default 0.8).
    Hidden links are excluded from results.

    Returns (results, total_count).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if embedding column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            if not cur.fetchone()[0]:
                raise RuntimeError(
                    "Vector search not initialized. Run: tars vector init"
                )

            # Generate embedding for query and search using cosine similarity
            # Uses Tiger Cloud's managed API key (no api_key param needed)
            # Filter by max_distance to only return relevant results
            # Exclude 4xx/5xx error pages and hidden links
            cur.execute(
                """
                WITH query_embed AS (
                    SELECT ai.openai_embed('text-embedding-3-small', %s)::vector(1536) AS vec
                )
                SELECT
                    url,
                    title,
                    description,
                    added_at,
                    embedding <=> query_embed.vec AS distance
                FROM links, query_embed
                WHERE embedding IS NOT NULL
                AND embedding <=> query_embed.vec <= %s
                AND (http_status IS NULL OR http_status < 400)
                AND hidden = FALSE
                ORDER BY distance
                LIMIT %s OFFSET %s;
                """,
                (query, max_distance, limit, offset),
            )
            rows = cur.fetchall()

            # Get total count of matching results
            cur.execute(
                """
                WITH query_embed AS (
                    SELECT ai.openai_embed('text-embedding-3-small', %s)::vector(1536) AS vec
                )
                SELECT COUNT(*)
                FROM links, query_embed
                WHERE embedding IS NOT NULL
                AND embedding <=> query_embed.vec <= %s
                AND (http_status IS NULL OR http_status < 400)
                AND hidden = FALSE;
                """,
                (query, max_distance),
            )
            total_count = cur.fetchone()[0]

    results = [
        {
            "url": row[0],
            "title": row[1],
            "description": row[2],
            "added_at": row[3].isoformat() if row[3] else None,
            "distance": row[4],
        }
        for row in rows
    ]
    return (results, total_count)


def db_hybrid_search(
    query: str,
    limit: int = 10,
    offset: int = 0,
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
    rrf_k: int = 60,
    min_score: float = 0.005,
    use_cache: bool = True,
) -> tuple[list[dict], int]:
    """Search links using hybrid search combining BM25 and vector similarity.

    Uses Reciprocal Rank Fusion (RRF) to merge rankings from keyword (BM25)
    and semantic (vector) search. RRF formula: 1 / (k + rank).
    Hidden links are excluded from results.
    Results are cached for performance (default TTL: 1 hour).

    Args:
        query: Search query string
        limit: Maximum number of results to return
        offset: Number of results to skip (for pagination)
        keyword_weight: Weight for BM25 keyword search (0-1)
        vector_weight: Weight for vector semantic search (0-1)
        rrf_k: RRF constant (default 60, higher values smooth out ranking differences)
        min_score: Minimum RRF score to include in results (default 0.005)
        use_cache: Whether to use cached results (default True)

    Returns (results, total_count) with combined RRF scores.
    """
    # Check cache first (only for first page to ensure consistency)
    if use_cache and offset == 0:
        cached = db_get_cached_search(query, keyword_weight, vector_weight)
        if cached:
            results, total_count = cached
            # Apply limit to cached results
            return (results[:limit], total_count)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if embedding column exists for vector search
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            has_embedding = cur.fetchone()[0]

            if not has_embedding:
                raise RuntimeError(
                    "Vector search not initialized. Run: tars db vector init"
                )

            # Hybrid search using RRF (Reciprocal Rank Fusion)
            # Combines BM25 keyword ranking with vector similarity ranking
            # Filters by minimum RRF score to exclude irrelevant results
            # Excludes hidden links
            cur.execute(
                """
                WITH query_embed AS (
                    SELECT ai.openai_embed('text-embedding-3-small', %s)::vector(1536) AS vec
                ),
                vector_search AS (
                    SELECT id,
                           ROW_NUMBER() OVER (ORDER BY embedding <=> query_embed.vec) AS rank
                    FROM links, query_embed
                    WHERE embedding IS NOT NULL
                    AND (http_status IS NULL OR http_status < 400)
                    AND hidden = FALSE
                    ORDER BY embedding <=> query_embed.vec
                    LIMIT 20
                ),
                keyword_search AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               ORDER BY search_text <@> to_bm25query(%s, 'links_search_bm25_idx')
                           ) AS rank
                    FROM links
                    WHERE search_text <@> to_bm25query(%s, 'links_search_bm25_idx') < 0
                    AND (http_status IS NULL OR http_status < 400)
                    AND hidden = FALSE
                    ORDER BY search_text <@> to_bm25query(%s, 'links_search_bm25_idx')
                    LIMIT 20
                ),
                combined AS (
                    SELECT
                        l.id,
                        l.url,
                        l.title,
                        l.description,
                        l.added_at,
                        COALESCE(v.rank, 999) AS vector_rank,
                        COALESCE(k.rank, 999) AS keyword_rank,
                        %s * COALESCE(1.0 / (%s + v.rank), 0.0) +
                        %s * COALESCE(1.0 / (%s + k.rank), 0.0) AS rrf_score
                    FROM links l
                    LEFT JOIN vector_search v ON l.id = v.id
                    LEFT JOIN keyword_search k ON l.id = k.id
                    WHERE v.id IS NOT NULL OR k.id IS NOT NULL
                )
                SELECT url, title, description, added_at, vector_rank, keyword_rank, rrf_score
                FROM combined
                WHERE rrf_score >= %s
                ORDER BY rrf_score DESC
                LIMIT %s OFFSET %s;
                """,
                (
                    query,  # for embedding
                    query,  # for bm25 in ROW_NUMBER
                    query,  # for bm25 in WHERE
                    query,  # for bm25 in ORDER BY
                    vector_weight,
                    rrf_k,
                    keyword_weight,
                    rrf_k,
                    min_score,
                    limit,
                    offset,
                ),
            )
            rows = cur.fetchall()

            # Get total count of results meeting min_score threshold
            cur.execute(
                """
                WITH query_embed AS (
                    SELECT ai.openai_embed('text-embedding-3-small', %s)::vector(1536) AS vec
                ),
                vector_search AS (
                    SELECT id,
                           ROW_NUMBER() OVER (ORDER BY embedding <=> query_embed.vec) AS rank
                    FROM links, query_embed
                    WHERE embedding IS NOT NULL
                    AND (http_status IS NULL OR http_status < 400)
                    AND hidden = FALSE
                    ORDER BY embedding <=> query_embed.vec
                    LIMIT 20
                ),
                keyword_search AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               ORDER BY search_text <@> to_bm25query(%s, 'links_search_bm25_idx')
                           ) AS rank
                    FROM links
                    WHERE search_text <@> to_bm25query(%s, 'links_search_bm25_idx') < 0
                    AND (http_status IS NULL OR http_status < 400)
                    AND hidden = FALSE
                    ORDER BY search_text <@> to_bm25query(%s, 'links_search_bm25_idx')
                    LIMIT 20
                ),
                combined AS (
                    SELECT
                        l.id,
                        %s * COALESCE(1.0 / (%s + v.rank), 0.0) +
                        %s * COALESCE(1.0 / (%s + k.rank), 0.0) AS rrf_score
                    FROM links l
                    LEFT JOIN vector_search v ON l.id = v.id
                    LEFT JOIN keyword_search k ON l.id = k.id
                    WHERE v.id IS NOT NULL OR k.id IS NOT NULL
                )
                SELECT COUNT(*)
                FROM combined
                WHERE rrf_score >= %s;
                """,
                (
                    query,
                    query,
                    query,
                    query,
                    vector_weight,
                    rrf_k,
                    keyword_weight,
                    rrf_k,
                    min_score,
                ),
            )
            total_count = cur.fetchone()[0]

    results = [
        {
            "url": row[0],
            "title": row[1],
            "description": row[2],
            "added_at": row[3].isoformat() if row[3] else None,
            "vector_rank": row[4],
            "keyword_rank": row[5],
            "rrf_score": float(row[6]),
        }
        for row in rows
    ]

    # Cache results for future queries (only cache first page)
    if use_cache and offset == 0:
        db_cache_search(query, keyword_weight, vector_weight, results, total_count)

    return (results, total_count)


# =============================================================================
# Link Management Functions (for web interface)
# =============================================================================


def db_toggle_hidden(url: str) -> bool | None:
    """Toggle the hidden status of a link.

    Args:
        url: The URL of the link to toggle

    Returns:
        The new hidden status (True/False), or None if link not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE links
                SET hidden = NOT hidden,
                    updated_at = NOW()
                WHERE url = %s
                RETURNING hidden
                """,
                (url,),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                # Invalidate search cache when hidden status changes
                db_invalidate_search_cache()
                return row[0]
            return None


def db_toggle_hidden_by_id(link_id: str) -> bool | None:
    """Toggle the hidden status of a link by ID.

    Args:
        link_id: The UUID of the link to toggle

    Returns:
        The new hidden status (True/False), or None if link not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE links
                SET hidden = NOT hidden,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING hidden
                """,
                (link_id,),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                # Invalidate search cache when hidden status changes
                db_invalidate_search_cache()
                return row[0]
            return None


def db_get_link_by_id(link_id: str) -> dict | None:
    """Get full link details by ID.

    Args:
        link_id: The UUID of the link

    Returns:
        Dictionary with all link fields, or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if embedding column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            has_embedding = cur.fetchone()[0]

            if has_embedding:
                cur.execute(
                    """
                    SELECT id, url, title, description, content, notes, tags,
                           hidden, added_at, updated_at, crawled_at, http_status,
                           crawl_error, embedding IS NOT NULL as has_embedding
                    FROM links
                    WHERE id = %s
                    """,
                    (link_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, url, title, description, content, notes, tags,
                           hidden, added_at, updated_at, crawled_at, http_status,
                           crawl_error, FALSE as has_embedding
                    FROM links
                    WHERE id = %s
                    """,
                    (link_id,),
                )

            row = cur.fetchone()
            if not row:
                return None

            return {
                "id": str(row[0]),
                "url": row[1],
                "title": row[2],
                "description": row[3],
                "content": row[4],
                "notes": row[5],
                "tags": row[6],
                "hidden": row[7],
                "added_at": row[8].isoformat() if row[8] else None,
                "updated_at": row[9].isoformat() if row[9] else None,
                "crawled_at": row[10].isoformat() if row[10] else None,
                "http_status": row[11],
                "crawl_error": row[12],
                "has_embedding": row[13],
            }


def db_get_link_by_url(url: str) -> dict | None:
    """Get full link details by URL.

    Args:
        url: The URL of the link

    Returns:
        Dictionary with all link fields, or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if embedding column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'links' AND column_name = 'embedding'
                );
            """)
            has_embedding = cur.fetchone()[0]

            if has_embedding:
                cur.execute(
                    """
                    SELECT id, url, title, description, content, notes, tags,
                           hidden, added_at, updated_at, crawled_at, http_status,
                           crawl_error, embedding IS NOT NULL as has_embedding
                    FROM links
                    WHERE url = %s
                    """,
                    (url,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, url, title, description, content, notes, tags,
                           hidden, added_at, updated_at, crawled_at, http_status,
                           crawl_error, FALSE as has_embedding
                    FROM links
                    WHERE url = %s
                    """,
                    (url,),
                )

            row = cur.fetchone()
            if not row:
                return None

            return {
                "id": str(row[0]),
                "url": row[1],
                "title": row[2],
                "description": row[3],
                "content": row[4],
                "notes": row[5],
                "tags": row[6],
                "hidden": row[7],
                "added_at": row[8].isoformat() if row[8] else None,
                "updated_at": row[9].isoformat() if row[9] else None,
                "crawled_at": row[10].isoformat() if row[10] else None,
                "http_status": row[11],
                "crawl_error": row[12],
                "has_embedding": row[13],
            }


def db_delete_link_by_id(link_id: str) -> bool:
    """Delete a link by ID.

    Args:
        link_id: The UUID of the link to delete

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM links WHERE id = %s", (link_id,))
            conn.commit()
            if cur.rowcount > 0:
                db_invalidate_search_cache()
                return True
            return False
