"""Search API routes for tars web interface."""

import logging
import math
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from tars import db

logger = logging.getLogger("tars.web.search")

# Create router
router = APIRouter(tags=["search"])


def get_db_stats() -> dict[str, Any]:
    """Get quick database statistics for homepage display."""
    if not db.is_db_configured():
        return {
            "configured": False,
            "total_links": 0,
            "crawled_links": 0,
            "embedded_links": 0,
        }

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Get total link count
                cur.execute("SELECT COUNT(*) FROM links;")
                total_links = cur.fetchone()[0]

                # Get crawled count
                cur.execute("SELECT COUNT(*) FROM links WHERE crawled_at IS NOT NULL;")
                crawled_links = cur.fetchone()[0]

                # Check if embedding column exists and get count
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'links' AND column_name = 'embedding'
                    );
                """)
                has_embeddings = cur.fetchone()[0]

                embedded_links = 0
                if has_embeddings:
                    cur.execute("SELECT COUNT(*) FROM links WHERE embedding IS NOT NULL;")
                    embedded_links = cur.fetchone()[0]

                return {
                    "configured": True,
                    "total_links": total_links,
                    "crawled_links": crawled_links,
                    "embedded_links": embedded_links,
                }
    except Exception as e:
        logger.error(f"Error getting DB stats: {e}")
        return {
            "configured": False,
            "error": str(e),
            "total_links": 0,
            "crawled_links": 0,
            "embedded_links": 0,
        }


def is_htmx_request(request: Request) -> bool:
    """Check if this is an HTMX partial request."""
    return request.headers.get("HX-Request") == "true"


def build_pagination(
    page: int,
    per_page: int,
    total_count: int,
) -> dict[str, Any]:
    """Build pagination info dict."""
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 1
    return {
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < total_pages else None,
    }


# -----------------------------------------------------------------------------
# Homepage with search form
# -----------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    """
    Homepage with search form.

    Displays:
    - Large centered search input
    - Search type selector (hybrid/text/vector)
    - Quick stats from database
    """
    templates = request.app.state.templates
    stats = get_db_stats()

    return templates.TemplateResponse(
        "search/index.html",
        {
            "request": request,
            "stats": stats,
        },
    )


# -----------------------------------------------------------------------------
# Hybrid Search (default)
# -----------------------------------------------------------------------------
@router.get("/search", response_class=HTMLResponse)
async def hybrid_search(
    request: Request,
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Results per page"),
    keyword_weight: float = Query(default=0.5, ge=0.0, le=1.0, description="BM25 keyword weight"),
    vector_weight: float = Query(default=0.5, ge=0.0, le=1.0, description="Vector similarity weight"),
) -> Response:
    """
    Hybrid search combining BM25 keyword and vector semantic search.

    Uses Reciprocal Rank Fusion (RRF) to merge rankings.
    Supports HTMX partial responses.
    Results are cached for performance.
    """
    templates = request.app.state.templates
    is_htmx = is_htmx_request(request)

    # Handle empty query
    if not q.strip():
        context = {
            "request": request,
            "query": "",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "hybrid",
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context)

    # Check database configuration
    if not db.is_db_configured():
        context = {
            "request": request,
            "query": q,
            "error": "Database not configured. Set DATABASE_URL or PG* environment variables.",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "hybrid",
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=503)

    try:
        # Calculate offset for pagination
        offset = (page - 1) * per_page

        # Perform hybrid search
        # Cache is checked internally by db_hybrid_search when use_cache=True
        results, total_count = db.db_hybrid_search(
            query=q,
            limit=per_page,
            offset=offset,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
            use_cache=True,
        )

        # Cache results for first page if not already cached
        # (db_hybrid_search handles this internally, but we can store full results if needed)
        # TODO: Consider caching paginated results separately if performance requires

        context = {
            "request": request,
            "query": q,
            "results": results,
            "pagination": build_pagination(page, per_page, total_count),
            "search_type": "hybrid",
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
        }

        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context)

    except RuntimeError as e:
        # Vector search not initialized
        error_msg = str(e)
        logger.warning(f"Hybrid search error: {error_msg}")

        context = {
            "request": request,
            "query": q,
            "error": error_msg,
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "hybrid",
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=503)

    except Exception as e:
        logger.error(f"Hybrid search error: {e}")
        context = {
            "request": request,
            "query": q,
            "error": "An error occurred while searching. Please try again.",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "hybrid",
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=500)


# -----------------------------------------------------------------------------
# BM25 Text Search
# -----------------------------------------------------------------------------
@router.get("/search/text", response_class=HTMLResponse)
async def text_search(
    request: Request,
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Results per page"),
) -> Response:
    """
    BM25 full-text keyword search.

    Uses pg_textsearch BM25 index for fast keyword matching.
    Supports HTMX partial responses.
    """
    templates = request.app.state.templates
    is_htmx = is_htmx_request(request)

    # Handle empty query
    if not q.strip():
        context = {
            "request": request,
            "query": "",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "text",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context)

    # Check database configuration
    if not db.is_db_configured():
        context = {
            "request": request,
            "query": q,
            "error": "Database not configured. Set DATABASE_URL or PG* environment variables.",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "text",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=503)

    try:
        # Calculate offset for pagination
        offset = (page - 1) * per_page

        # Perform BM25 text search
        results, total_count = db.db_search(
            query=q,
            limit=per_page,
            offset=offset,
        )

        context = {
            "request": request,
            "query": q,
            "results": results,
            "pagination": build_pagination(page, per_page, total_count),
            "search_type": "text",
        }

        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context)

    except Exception as e:
        logger.error(f"Text search error: {e}")
        context = {
            "request": request,
            "query": q,
            "error": "An error occurred while searching. Please try again.",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "text",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=500)


# -----------------------------------------------------------------------------
# Vector (Semantic) Search
# -----------------------------------------------------------------------------
@router.get("/search/vector", response_class=HTMLResponse)
async def vector_search(
    request: Request,
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Results per page"),
) -> Response:
    """
    Vector similarity semantic search.

    Uses pgvector HNSW index for semantic matching based on embeddings.
    Supports HTMX partial responses.
    """
    templates = request.app.state.templates
    is_htmx = is_htmx_request(request)

    # Handle empty query
    if not q.strip():
        context = {
            "request": request,
            "query": "",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "vector",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context)

    # Check database configuration
    if not db.is_db_configured():
        context = {
            "request": request,
            "query": q,
            "error": "Database not configured. Set DATABASE_URL or PG* environment variables.",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "vector",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=503)

    try:
        # Calculate offset for pagination
        offset = (page - 1) * per_page

        # Perform vector search
        results, total_count = db.db_vector_search(
            query=q,
            limit=per_page,
            offset=offset,
        )

        context = {
            "request": request,
            "query": q,
            "results": results,
            "pagination": build_pagination(page, per_page, total_count),
            "search_type": "vector",
        }

        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context)

    except RuntimeError as e:
        # Vector search not initialized
        error_msg = str(e)
        logger.warning(f"Vector search error: {error_msg}")

        context = {
            "request": request,
            "query": q,
            "error": error_msg,
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "vector",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=503)

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        context = {
            "request": request,
            "query": q,
            "error": "An error occurred while searching. Please try again.",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "vector",
        }
        template = "search/results_partial.html" if is_htmx else "search/results.html"
        return templates.TemplateResponse(template, context, status_code=500)


# -----------------------------------------------------------------------------
# JSON API endpoints for programmatic access
# -----------------------------------------------------------------------------
@router.get("/api/search", response_class=JSONResponse)
async def api_hybrid_search(
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Results per page"),
    keyword_weight: float = Query(default=0.5, ge=0.0, le=1.0, description="BM25 keyword weight"),
    vector_weight: float = Query(default=0.5, ge=0.0, le=1.0, description="Vector similarity weight"),
) -> JSONResponse:
    """JSON API for hybrid search."""
    if not q.strip():
        return JSONResponse({
            "query": "",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "hybrid",
        })

    if not db.is_db_configured():
        return JSONResponse(
            {"error": "Database not configured"},
            status_code=503,
        )

    try:
        offset = (page - 1) * per_page
        results, total_count = db.db_hybrid_search(
            query=q,
            limit=per_page,
            offset=offset,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
            use_cache=True,
        )

        return JSONResponse({
            "query": q,
            "results": results,
            "pagination": build_pagination(page, per_page, total_count),
            "search_type": "hybrid",
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
        })

    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    except Exception as e:
        logger.error(f"API hybrid search error: {e}")
        return JSONResponse({"error": "Search failed"}, status_code=500)


@router.get("/api/search/text", response_class=JSONResponse)
async def api_text_search(
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Results per page"),
) -> JSONResponse:
    """JSON API for BM25 text search."""
    if not q.strip():
        return JSONResponse({
            "query": "",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "text",
        })

    if not db.is_db_configured():
        return JSONResponse(
            {"error": "Database not configured"},
            status_code=503,
        )

    try:
        offset = (page - 1) * per_page
        results, total_count = db.db_search(
            query=q,
            limit=per_page,
            offset=offset,
        )

        return JSONResponse({
            "query": q,
            "results": results,
            "pagination": build_pagination(page, per_page, total_count),
            "search_type": "text",
        })

    except Exception as e:
        logger.error(f"API text search error: {e}")
        return JSONResponse({"error": "Search failed"}, status_code=500)


@router.get("/api/search/vector", response_class=JSONResponse)
async def api_vector_search(
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Results per page"),
) -> JSONResponse:
    """JSON API for vector semantic search."""
    if not q.strip():
        return JSONResponse({
            "query": "",
            "results": [],
            "pagination": build_pagination(1, per_page, 0),
            "search_type": "vector",
        })

    if not db.is_db_configured():
        return JSONResponse(
            {"error": "Database not configured"},
            status_code=503,
        )

    try:
        offset = (page - 1) * per_page
        results, total_count = db.db_vector_search(
            query=q,
            limit=per_page,
            offset=offset,
        )

        return JSONResponse({
            "query": q,
            "results": results,
            "pagination": build_pagination(page, per_page, total_count),
            "search_type": "vector",
        })

    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    except Exception as e:
        logger.error(f"API vector search error: {e}")
        return JSONResponse({"error": "Search failed"}, status_code=500)


@router.get("/api/stats", response_class=JSONResponse)
async def api_stats() -> JSONResponse:
    """JSON API for database statistics."""
    return JSONResponse(get_db_stats())
