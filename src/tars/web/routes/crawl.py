"""Crawl management routes for tars web interface."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse

from tars import db
from tars.crawl import crawl_page

logger = logging.getLogger("tars.web.crawl")

router = APIRouter(prefix="/crawl", tags=["crawl"])


class CrawlMode(str, Enum):
    """Crawl mode options."""

    MISSING = "missing"
    ALL = "all"
    OLD = "old"


class CrawlState(str, Enum):
    """Crawl job state."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class CrawlProgress:
    """Track progress of a crawl job."""

    state: CrawlState = CrawlState.IDLE
    total: int = 0
    completed: int = 0
    success: int = 0
    errors: int = 0
    current_url: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    error_urls: list[str] = field(default_factory=list)


# Module-level state for tracking crawl progress
_crawl_progress = CrawlProgress()


def get_crawl_stats() -> dict[str, Any]:
    """Get crawl statistics from the database."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Total links
                cur.execute("SELECT COUNT(*) FROM links")
                total = cur.fetchone()[0]

                # Crawled links
                cur.execute("SELECT COUNT(*) FROM links WHERE crawled_at IS NOT NULL")
                crawled = cur.fetchone()[0]

                # Pending (never crawled)
                cur.execute("SELECT COUNT(*) FROM links WHERE crawled_at IS NULL")
                pending = cur.fetchone()[0]

                # Errors (links with crawl_error set)
                cur.execute(
                    "SELECT COUNT(*) FROM links WHERE crawl_error IS NOT NULL"
                )
                errors = cur.fetchone()[0]

                return {
                    "total": total,
                    "crawled": crawled,
                    "pending": pending,
                    "errors": errors,
                }
    except Exception as e:
        logger.error(f"Failed to get crawl stats: {e}")
        return {
            "total": 0,
            "crawled": 0,
            "pending": 0,
            "errors": 0,
            "error": str(e),
        }


def run_crawl_job(mode: CrawlMode, days: int = 7) -> None:
    """
    Run crawl job in background.

    This function updates the module-level _crawl_progress as it runs.
    """
    global _crawl_progress

    try:
        # Get URLs to crawl based on mode
        urls = db.db_get_links_to_crawl(mode=mode.value, days=days)

        if not urls:
            _crawl_progress.state = CrawlState.COMPLETED
            _crawl_progress.finished_at = datetime.now()
            return

        _crawl_progress.total = len(urls)
        _crawl_progress.state = CrawlState.RUNNING

        for url in urls:
            if _crawl_progress.state != CrawlState.RUNNING:
                # Job was cancelled or errored
                break

            _crawl_progress.current_url = url

            try:
                # Crawl the page
                result = crawl_page(url)

                # Update database with crawl results
                db.db_update_crawl_data(
                    url=url,
                    title=result.title,
                    description=result.description,
                    content=result.content,
                    http_status=result.http_status,
                    crawl_error=result.error,
                )

                if result.error:
                    _crawl_progress.errors += 1
                    _crawl_progress.error_urls.append(url)
                else:
                    _crawl_progress.success += 1

            except Exception as e:
                logger.error(f"Error crawling {url}: {e}")
                _crawl_progress.errors += 1
                _crawl_progress.error_urls.append(url)

            _crawl_progress.completed += 1

        _crawl_progress.state = CrawlState.COMPLETED
        _crawl_progress.finished_at = datetime.now()
        _crawl_progress.current_url = None

    except Exception as e:
        logger.error(f"Crawl job failed: {e}")
        _crawl_progress.state = CrawlState.ERROR
        _crawl_progress.error_message = str(e)
        _crawl_progress.finished_at = datetime.now()


@router.get("", response_class=HTMLResponse)
async def crawl_page_view(request: Request) -> HTMLResponse:
    """
    Crawl management page.

    Shows crawl statistics and provides controls for starting crawl jobs.
    """
    templates = request.app.state.templates
    stats = get_crawl_stats()

    return templates.TemplateResponse(
        "crawl/index.html",
        {
            "request": request,
            "stats": stats,
            "progress": _crawl_progress,
            "modes": [
                {"value": "missing", "label": "Missing only", "description": "Links never crawled"},
                {"value": "all", "label": "All links", "description": "Re-crawl all links"},
                {"value": "old", "label": "Old links", "description": "Links not crawled in N days"},
            ],
        },
    )


@router.post("/start", response_class=HTMLResponse)
async def start_crawl(
    request: Request,
    background_tasks: BackgroundTasks,
    mode: str = Form(default="missing"),
    days: int = Form(default=7),
) -> HTMLResponse:
    """
    Start a crawl job.

    Form params:
    - mode: "missing" | "all" | "old"
    - days: Number of days for "old" mode (default: 7)
    """
    global _crawl_progress
    templates = request.app.state.templates

    # Check if a crawl is already running
    if _crawl_progress.state == CrawlState.RUNNING:
        return templates.TemplateResponse(
            "crawl/partials/status.html",
            {
                "request": request,
                "progress": _crawl_progress,
                "error": "A crawl job is already running",
            },
        )

    # Validate mode
    try:
        crawl_mode = CrawlMode(mode)
    except ValueError:
        return templates.TemplateResponse(
            "crawl/partials/status.html",
            {
                "request": request,
                "progress": _crawl_progress,
                "error": f"Invalid crawl mode: {mode}",
            },
        )

    # Reset progress for new job
    _crawl_progress = CrawlProgress(
        state=CrawlState.RUNNING,
        started_at=datetime.now(),
    )

    # Start crawl in background
    background_tasks.add_task(run_crawl_job, crawl_mode, days)

    return templates.TemplateResponse(
        "crawl/partials/status.html",
        {
            "request": request,
            "progress": _crawl_progress,
        },
    )


@router.get("/status", response_class=HTMLResponse)
async def get_crawl_status(request: Request) -> HTMLResponse:
    """
    Get current crawl progress.

    Returns a partial HTML response for HTMX polling.
    """
    templates = request.app.state.templates

    return templates.TemplateResponse(
        "crawl/partials/status.html",
        {
            "request": request,
            "progress": _crawl_progress,
            "stats": get_crawl_stats() if _crawl_progress.state != CrawlState.RUNNING else None,
        },
    )
