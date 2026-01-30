"""Database management routes for tars web interface."""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse

from tars import db

logger = logging.getLogger("tars.web.db")

router = APIRouter(prefix="/db", tags=["database"])


class EmbedState(str, Enum):
    """Embedding job state."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class EmbedProgress:
    """Track progress of an embedding job."""

    state: EmbedState = EmbedState.IDLE
    total: int = 0
    completed: int = 0
    success: int = 0
    errors: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


# Module-level state for tracking embedding progress
_embed_progress = EmbedProgress()


def get_db_connection_status() -> dict[str, Any]:
    """Get database connection status and info."""
    config = db.get_db_config()
    if not config:
        return {
            "connected": False,
            "error": "Database not configured. Set DATABASE_URL or PG* environment variables.",
        }

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Get database info
                cur.execute("SELECT current_database(), current_user, version();")
                db_name, db_user, db_version = cur.fetchone()

                # Get link count
                cur.execute("SELECT COUNT(*) FROM links")
                link_count = cur.fetchone()[0]

                return {
                    "connected": True,
                    "database": db_name,
                    "user": db_user,
                    "version": db_version.split(",")[0] if db_version else None,
                    "link_count": link_count,
                }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


def get_schema_status() -> dict[str, Any]:
    """Get database schema status."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if links table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'links'
                    );
                """)
                has_links_table = cur.fetchone()[0]

                # Check for BM25 index
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM pg_indexes
                        WHERE indexname = 'links_search_bm25_idx'
                    );
                """)
                has_bm25_index = cur.fetchone()[0]

                # Check for embedding column
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = 'links' AND column_name = 'embedding'
                    );
                """)
                has_embedding = cur.fetchone()[0]

                # Check for HNSW index
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM pg_indexes
                        WHERE indexname = 'links_embedding_hnsw_idx'
                    );
                """)
                has_hnsw_index = cur.fetchone()[0]

                # Check for search_cache table
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'search_cache'
                    );
                """)
                has_cache_table = cur.fetchone()[0]

                # Check extensions
                cur.execute("""
                    SELECT extname FROM pg_extension
                    WHERE extname IN ('pg_textsearch', 'vector', 'ai', 'vectorscale')
                """)
                extensions = [row[0] for row in cur.fetchall()]

                return {
                    "initialized": has_links_table,
                    "tables": {
                        "links": has_links_table,
                        "search_cache": has_cache_table,
                    },
                    "indexes": {
                        "bm25": has_bm25_index,
                        "hnsw": has_hnsw_index,
                    },
                    "columns": {
                        "embedding": has_embedding,
                    },
                    "extensions": extensions,
                }
    except Exception as e:
        return {
            "initialized": False,
            "error": str(e),
        }


def run_embed_job(limit: int | None = None) -> None:
    """
    Run embedding generation job in background.

    This function updates the module-level _embed_progress as it runs.
    """
    global _embed_progress

    try:
        # Get count of links needing embeddings
        status = db.db_vectorizer_status()
        if not status.get("configured"):
            _embed_progress.state = EmbedState.ERROR
            _embed_progress.error_message = "Vector search not initialized. Run db init first."
            return

        pending = status.get("pending_items", 0)
        if pending == 0:
            _embed_progress.state = EmbedState.COMPLETED
            _embed_progress.finished_at = datetime.now()
            return

        _embed_progress.total = min(pending, limit) if limit else pending
        _embed_progress.state = EmbedState.RUNNING

        # Generate embeddings
        success, errors = db.db_generate_embeddings(limit=limit, show_progress=False)

        _embed_progress.success = success
        _embed_progress.errors = errors
        _embed_progress.completed = success + errors
        _embed_progress.state = EmbedState.COMPLETED
        _embed_progress.finished_at = datetime.now()

    except Exception as e:
        logger.error(f"Embedding job failed: {e}")
        _embed_progress.state = EmbedState.ERROR
        _embed_progress.error_message = str(e)
        _embed_progress.finished_at = datetime.now()


@router.get("", response_class=HTMLResponse)
async def db_page(request: Request) -> HTMLResponse:
    """
    Database management page.

    Shows connection status, schema status, and management options.
    """
    templates = request.app.state.templates

    connection = get_db_connection_status()
    schema = get_schema_status() if connection.get("connected") else None

    return templates.TemplateResponse(
        "db/index.html",
        {
            "request": request,
            "connection": connection,
            "schema": schema,
        },
    )


@router.post("/init", response_class=HTMLResponse)
async def init_database(request: Request) -> HTMLResponse:
    """
    Initialize database schema.

    Creates tables, indexes, and extensions required for tars.
    """
    templates = request.app.state.templates

    try:
        db.db_init()

        return templates.TemplateResponse(
            "db/partials/init_result.html",
            {
                "request": request,
                "success": True,
                "message": "Database initialized successfully",
                "schema": get_schema_status(),
            },
        )
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        return templates.TemplateResponse(
            "db/partials/init_result.html",
            {
                "request": request,
                "success": False,
                "error": str(e),
            },
        )


@router.get("/vector", response_class=HTMLResponse)
async def vector_status_page(request: Request) -> HTMLResponse:
    """
    Vector search status page.

    Shows embedding statistics and controls for generating embeddings.
    """
    templates = request.app.state.templates

    try:
        status = db.db_vectorizer_status()
    except Exception as e:
        status = {"configured": False, "error": str(e)}

    return templates.TemplateResponse(
        "db/vector.html",
        {
            "request": request,
            "status": status,
            "progress": _embed_progress,
        },
    )


@router.post("/vector/embed", response_class=HTMLResponse)
async def generate_embeddings(
    request: Request,
    background_tasks: BackgroundTasks,
    limit: int | None = Form(default=None),
) -> HTMLResponse:
    """
    Start embedding generation job.

    Form params:
    - limit: Maximum number of embeddings to generate (optional)
    """
    global _embed_progress
    templates = request.app.state.templates

    # Check if an embedding job is already running
    if _embed_progress.state == EmbedState.RUNNING:
        return templates.TemplateResponse(
            "db/partials/embed_status.html",
            {
                "request": request,
                "progress": _embed_progress,
                "error": "An embedding job is already running",
            },
        )

    # Check if vector search is configured
    try:
        status = db.db_vectorizer_status()
        if not status.get("configured"):
            return templates.TemplateResponse(
                "db/partials/embed_status.html",
                {
                    "request": request,
                    "progress": _embed_progress,
                    "error": "Vector search not initialized. Initialize database first.",
                },
            )
    except Exception as e:
        return templates.TemplateResponse(
            "db/partials/embed_status.html",
            {
                "request": request,
                "progress": _embed_progress,
                "error": str(e),
            },
        )

    # Reset progress for new job
    _embed_progress = EmbedProgress(
        state=EmbedState.RUNNING,
        started_at=datetime.now(),
    )

    # Start embedding job in background
    background_tasks.add_task(run_embed_job, limit)

    return templates.TemplateResponse(
        "db/partials/embed_status.html",
        {
            "request": request,
            "progress": _embed_progress,
        },
    )


@router.get("/vector/status", response_class=HTMLResponse)
async def get_embed_status(request: Request) -> HTMLResponse:
    """
    Get current embedding progress.

    Returns a partial HTML response for HTMX polling.
    """
    templates = request.app.state.templates

    # Get fresh status if not running
    status = None
    if _embed_progress.state != EmbedState.RUNNING:
        try:
            status = db.db_vectorizer_status()
        except Exception:
            pass

    return templates.TemplateResponse(
        "db/partials/embed_status.html",
        {
            "request": request,
            "progress": _embed_progress,
            "status": status,
        },
    )
