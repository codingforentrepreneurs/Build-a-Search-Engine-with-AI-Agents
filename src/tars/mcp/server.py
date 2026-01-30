"""FastMCP server exposing TARS search engine as MCP tools."""

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from tars import db
from tars.crawl import crawl_page
from tars.mcp.models import (
    CrawlResult,
    DatabaseStatus,
    LinkDetails,
    LinksListResponse,
    LinkSummary,
    SearchResponse,
    SearchResult,
)

mcp = FastMCP(
    name="tars",
    instructions="""TARS is a personal search engine for managing and searching links.

It supports three search modes:
- Hybrid search (default): Combines BM25 keyword matching with vector semantic search using RRF
- Text search: BM25 full-text keyword search
- Vector search: Semantic similarity search using embeddings

Use the search tools to find relevant links, and link management tools to add, view, or remove links.
""",
)


def _check_db_configured() -> None:
    """Raise ToolError if database is not configured."""
    if not db.is_db_configured():
        raise ToolError(
            "Database not configured. Set DATABASE_URL or PG* environment variables."
        )


def _clamp_limit(limit: int) -> int:
    """Clamp limit to valid range (1-100)."""
    return max(1, min(100, limit))


def _clamp_page(page: int) -> int:
    """Ensure page is at least 1."""
    return max(1, page)


# =============================================================================
# Search Tools
# =============================================================================


@mcp.tool()
def search(
    query: str,
    limit: int = 10,
    page: int = 1,
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> SearchResponse:
    """Search links using hybrid search (BM25 keyword + vector semantic search with RRF).

    This combines keyword matching with semantic understanding for best results.
    The weights control the balance between exact keyword matches and semantic similarity.

    Args:
        query: Search query string
        limit: Maximum results to return (1-100, default 10)
        page: Page number for pagination (default 1)
        keyword_weight: Weight for BM25 keyword search (0-1, default 0.5)
        vector_weight: Weight for vector semantic search (0-1, default 0.5)

    Returns:
        SearchResponse with results containing RRF scores and rank information
    """
    _check_db_configured()

    limit = _clamp_limit(limit)
    page = _clamp_page(page)
    offset = (page - 1) * limit

    try:
        results, total_count = db.db_hybrid_search(
            query=query,
            limit=limit,
            offset=offset,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
        )

        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    url=r["url"],
                    title=r.get("title"),
                    description=r.get("description"),
                    added_at=r.get("added_at"),
                    rrf_score=r.get("rrf_score"),
                    vector_rank=r.get("vector_rank"),
                    keyword_rank=r.get("keyword_rank"),
                )
                for r in results
            ],
            total_count=total_count,
            page=page,
            per_page=limit,
            search_type="hybrid",
        )
    except RuntimeError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def text_search(query: str, limit: int = 10, page: int = 1) -> SearchResponse:
    """Search links using BM25 full-text keyword search.

    This search mode finds exact keyword matches and ranks by relevance.
    Use this when you need precise keyword matching rather than semantic similarity.

    Args:
        query: Search query string
        limit: Maximum results to return (1-100, default 10)
        page: Page number for pagination (default 1)

    Returns:
        SearchResponse with results containing BM25 scores
    """
    _check_db_configured()

    limit = _clamp_limit(limit)
    page = _clamp_page(page)
    offset = (page - 1) * limit

    try:
        results, total_count = db.db_search(
            query=query,
            limit=limit,
            offset=offset,
        )

        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    url=r["url"],
                    title=r.get("title"),
                    description=r.get("description"),
                    added_at=r.get("added_at"),
                    score=r.get("score"),
                )
                for r in results
            ],
            total_count=total_count,
            page=page,
            per_page=limit,
            search_type="keyword",
        )
    except RuntimeError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def vector_search(query: str, limit: int = 10, page: int = 1) -> SearchResponse:
    """Search links using semantic vector similarity.

    This search mode finds conceptually similar content even without exact keyword matches.
    Use this when you want to find related content based on meaning.

    Args:
        query: Search query string (will be converted to embedding)
        limit: Maximum results to return (1-100, default 10)
        page: Page number for pagination (default 1)

    Returns:
        SearchResponse with results containing cosine distance scores (lower = more similar)
    """
    _check_db_configured()

    limit = _clamp_limit(limit)
    page = _clamp_page(page)
    offset = (page - 1) * limit

    try:
        results, total_count = db.db_vector_search(
            query=query,
            limit=limit,
            offset=offset,
        )

        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    url=r["url"],
                    title=r.get("title"),
                    description=r.get("description"),
                    added_at=r.get("added_at"),
                    distance=r.get("distance"),
                )
                for r in results
            ],
            total_count=total_count,
            page=page,
            per_page=limit,
            search_type="vector",
        )
    except RuntimeError as e:
        raise ToolError(str(e)) from e


# =============================================================================
# Link Management Tools
# =============================================================================


@mcp.tool()
def add_link(url: str) -> LinkDetails:
    """Add a new URL to the search engine.

    The URL will be stored and can later be crawled to extract content for better search results.

    Args:
        url: The URL to add (will add https:// if no scheme provided)

    Returns:
        LinkDetails for the newly added link
    """
    _check_db_configured()

    # Normalize URL - add https:// if no scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Check if URL already exists
    existing = db.db_get_link_by_url(url)
    if existing:
        raise ToolError(f"URL already exists: {url}")

    try:
        db.db_add_link(url)
        # Fetch the newly created link
        link = db.db_get_link_by_url(url)
        if not link:
            raise ToolError("Failed to add link")

        return LinkDetails(
            id=link["id"],
            url=link["url"],
            title=link.get("title"),
            description=link.get("description"),
            content=link.get("content"),
            notes=link.get("notes"),
            tags=link.get("tags"),
            hidden=link.get("hidden", False),
            added_at=link.get("added_at"),
            updated_at=link.get("updated_at"),
            crawled_at=link.get("crawled_at"),
            http_status=link.get("http_status"),
            crawl_error=link.get("crawl_error"),
            has_embedding=link.get("has_embedding", False),
        )
    except RuntimeError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def list_links(limit: int = 20, page: int = 1) -> LinksListResponse:
    """List stored links with pagination.

    Returns links ordered by most recently updated first.

    Args:
        limit: Maximum links to return (1-100, default 20)
        page: Page number for pagination (default 1)

    Returns:
        LinksListResponse with link summaries and pagination info
    """
    _check_db_configured()

    limit = _clamp_limit(limit)
    page = _clamp_page(page)
    offset = (page - 1) * limit

    try:
        links, total_count, pending_embeddings = db.db_list_links(
            limit=limit, offset=offset
        )

        return LinksListResponse(
            links=[
                LinkSummary(
                    id=link["id"],
                    url=link["url"],
                    title=link.get("title"),
                    description=None,  # Not returned by list function
                    added_at=link.get("added_at"),
                )
                for link in links
            ],
            total_count=total_count,
            page=page,
            per_page=limit,
            pending_embeddings=pending_embeddings,
        )
    except RuntimeError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def get_link(url: str | None = None, id: str | None = None) -> LinkDetails:
    """Get full details for a specific link.

    Provide either URL or ID to look up the link.

    Args:
        url: The URL of the link to retrieve
        id: The UUID of the link to retrieve

    Returns:
        LinkDetails with full information including content
    """
    _check_db_configured()

    if not url and not id:
        raise ToolError("Must provide either url or id parameter")

    try:
        if id:
            link = db.db_get_link_by_id(id)
        else:
            link = db.db_get_link_by_url(url)

        if not link:
            raise ToolError(f"Link not found: {url or id}")

        return LinkDetails(
            id=link["id"],
            url=link["url"],
            title=link.get("title"),
            description=link.get("description"),
            content=link.get("content"),
            notes=link.get("notes"),
            tags=link.get("tags"),
            hidden=link.get("hidden", False),
            added_at=link.get("added_at"),
            updated_at=link.get("updated_at"),
            crawled_at=link.get("crawled_at"),
            http_status=link.get("http_status"),
            crawl_error=link.get("crawl_error"),
            has_embedding=link.get("has_embedding", False),
        )
    except RuntimeError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def remove_link(url: str) -> str:
    """Remove a link from the search engine.

    Args:
        url: The URL of the link to remove

    Returns:
        Confirmation message
    """
    _check_db_configured()

    try:
        removed = db.db_remove_link(url)
        if not removed:
            raise ToolError(f"Link not found: {url}")
        return f"Removed link: {url}"
    except RuntimeError as e:
        raise ToolError(str(e)) from e


# =============================================================================
# Crawl & Status Tools
# =============================================================================


@mcp.tool()
def crawl_link(url: str) -> CrawlResult:
    """Crawl a URL to extract its content for improved search results.

    The link must already exist in the database. Crawling extracts title,
    description, and main content which are used for search indexing.

    Args:
        url: The URL to crawl (must be in the database)

    Returns:
        CrawlResult with extracted content and status
    """
    _check_db_configured()

    # Verify link exists
    existing = db.db_get_link_by_url(url)
    if not existing:
        raise ToolError(f"Link not found in database: {url}. Add it first with add_link.")

    try:
        # Crawl the page
        result = crawl_page(url)

        # Update database with crawl results
        updated, content_changed = db.db_update_crawl_data(
            url=url,
            title=result.title,
            description=result.description,
            content=result.content,
            http_status=result.http_status,
            crawl_error=result.error,
        )

        return CrawlResult(
            url=url,
            success=result.error is None,
            title=result.title,
            description=result.description,
            http_status=result.http_status,
            error=result.error,
            content_changed=content_changed,
        )
    except Exception as e:
        raise ToolError(f"Crawl failed: {e}") from e


@mcp.tool()
def database_status() -> DatabaseStatus:
    """Get database connection status and statistics.

    Returns information about the database configuration, connection status,
    and counts of total, crawled, and embedded links.

    Returns:
        DatabaseStatus with connection info and statistics
    """
    configured = db.is_db_configured()
    if not configured:
        return DatabaseStatus(
            configured=False,
            connected=False,
            error="Database not configured. Set DATABASE_URL or PG* environment variables.",
        )

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Get database name
                cur.execute("SELECT current_database();")
                db_name = cur.fetchone()[0]

                # Get total links
                cur.execute("SELECT COUNT(*) FROM links;")
                total = cur.fetchone()[0]

                # Get crawled links
                cur.execute("SELECT COUNT(*) FROM links WHERE crawled_at IS NOT NULL;")
                crawled = cur.fetchone()[0]

                # Check if embedding column exists and get count
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'links' AND column_name = 'embedding'
                    );
                """)
                has_embedding = cur.fetchone()[0]

                embedded = 0
                if has_embedding:
                    cur.execute("SELECT COUNT(*) FROM links WHERE embedding IS NOT NULL;")
                    embedded = cur.fetchone()[0]

        return DatabaseStatus(
            configured=True,
            connected=True,
            database_name=db_name,
            total_links=total,
            crawled_links=crawled,
            embedded_links=embedded,
        )
    except Exception as e:
        return DatabaseStatus(
            configured=True,
            connected=False,
            error=str(e),
        )


def main(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000):
    """Run the MCP server.

    Args:
        transport: "stdio" for local CLI, "sse" for HTTP (Claude Code remote)
        host: Host to bind to (only for sse transport)
        port: Port to bind to (only for sse transport)
    """
    if transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
