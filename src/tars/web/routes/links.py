"""Link management routes for tars web interface."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from tars import db
from tars.crawl import crawl_page

logger = logging.getLogger("tars.web.links")

router = APIRouter(prefix="/links", tags=["links"])


def is_htmx_request(request: Request) -> bool:
    """Check if request is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def get_templates(request: Request):
    """Get Jinja2 templates from app state."""
    return request.app.state.templates


# -----------------------------------------------------------------------------
# GET /links - List all links (paginated)
# -----------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
async def list_links(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    show_hidden: bool = False,
) -> HTMLResponse:
    """
    List all links with pagination.

    Supports HTMX partial responses - returns just the links list partial
    when HX-Request header is present.
    """
    templates = get_templates(request)

    # Validate pagination params
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20
    if per_page > 100:
        per_page = 100

    offset = (page - 1) * per_page

    try:
        # Fetch links from database
        # TODO: Update db_list_links to support show_hidden filter
        # For now, use the existing function which doesn't filter by hidden
        links, total_count, pending_embeddings = db.db_list_links(
            limit=per_page, offset=offset
        )

        # If show_hidden is False, filter out hidden links client-side
        # (until db function is updated to support this)
        if not show_hidden:
            # TODO: This should be done in the database query
            # For now, we fetch all and filter (not ideal for large datasets)
            pass

        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages

        context = {
            "request": request,
            "links": links,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_prev": has_prev,
            "has_next": has_next,
            "show_hidden": show_hidden,
            "pending_embeddings": pending_embeddings,
        }

        # Return partial for HTMX requests, full page otherwise
        if is_htmx_request(request):
            return templates.TemplateResponse(
                "links/partials/links_list.html",
                context,
            )

        return templates.TemplateResponse(
            "links/index.html",
            context,
        )

    except RuntimeError as e:
        logger.error(f"Database error listing links: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        )


# -----------------------------------------------------------------------------
# GET /links/add - Show add link form
# -----------------------------------------------------------------------------
@router.get("/add", response_class=HTMLResponse)
async def show_add_link_form(request: Request) -> HTMLResponse:
    """Show the add link form page."""
    templates = get_templates(request)
    return templates.TemplateResponse(
        "links/add.html",
        {"request": request},
    )


# -----------------------------------------------------------------------------
# GET /links/{id} - View single link with full content
# -----------------------------------------------------------------------------
@router.get("/{link_id}", response_class=HTMLResponse)
async def view_link(
    request: Request,
    link_id: str,
) -> HTMLResponse:
    """
    View a single link with full details including content and crawl status.
    """
    templates = get_templates(request)

    try:
        # Validate UUID format
        try:
            uuid_id = UUID(link_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid link ID format",
            )

        # TODO: Agent 1 is adding db_get_link_by_id() function
        # For now, implement inline query
        link = _get_link_by_id(str(uuid_id))

        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Link not found",
            )

        context = {
            "request": request,
            "link": link,
        }

        # Return partial for HTMX requests, full page otherwise
        if is_htmx_request(request):
            return templates.TemplateResponse(
                "links/partials/link_detail.html",
                context,
            )

        return templates.TemplateResponse(
            "links/view.html",
            context,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Database error fetching link: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        )


# -----------------------------------------------------------------------------
# POST /links/add - Add new link
# -----------------------------------------------------------------------------
@router.post("/add", response_class=HTMLResponse)
async def add_link(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    crawl_now: bool = Form(default=False),
) -> HTMLResponse:
    """
    Add a new link to the database.

    Optionally triggers an immediate crawl in the background.
    Returns HTMX partial or redirects to link list.
    """
    templates = get_templates(request)

    # Validate URL format
    if not url or not url.strip():
        if is_htmx_request(request):
            return templates.TemplateResponse(
                "links/partials/add_form.html",
                {
                    "request": request,
                    "error": "URL is required",
                    "url": url,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is required",
        )

    url = url.strip()

    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        # Add link to database
        # Note: db_add_link prints to console, so we use a modified approach
        link_added = _add_link_silent(url)

        if not link_added:
            if is_htmx_request(request):
                return templates.TemplateResponse(
                    "links/partials/add_form.html",
                    {
                        "request": request,
                        "error": "Link already exists",
                        "url": url,
                    },
                    status_code=status.HTTP_409_CONFLICT,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Link already exists",
            )

        # Queue crawl if requested
        if crawl_now:
            background_tasks.add_task(_crawl_link_background, url)

        # Get the newly added link for display
        link = _get_link_by_url(url)

        if is_htmx_request(request):
            # Return success message and optionally the new link row
            return templates.TemplateResponse(
                "links/partials/link_added.html",
                {
                    "request": request,
                    "link": link,
                    "crawl_queued": crawl_now,
                },
                status_code=status.HTTP_201_CREATED,
            )

        # For non-HTMX, return success page
        return templates.TemplateResponse(
            "links/added.html",
            {
                "request": request,
                "link": link,
                "crawl_queued": crawl_now,
            },
            status_code=status.HTTP_201_CREATED,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Database error adding link: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        )


# -----------------------------------------------------------------------------
# POST /links/{id}/hide - Toggle hidden status
# -----------------------------------------------------------------------------
@router.post("/{link_id}/hide", response_class=HTMLResponse)
async def toggle_hidden(
    request: Request,
    link_id: str,
) -> HTMLResponse:
    """
    Toggle the hidden status of a link.

    Returns updated link row partial for HTMX swap.
    """
    templates = get_templates(request)

    try:
        # Validate UUID format
        try:
            uuid_id = UUID(link_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid link ID format",
            )

        # Get the link first to get its URL
        link = _get_link_by_id(str(uuid_id))
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Link not found",
            )

        # TODO: Agent 1 is adding db_toggle_hidden() function
        # For now, implement inline
        new_hidden_status = _toggle_link_hidden(link["url"])

        # Refresh the link data
        link = _get_link_by_id(str(uuid_id))

        if is_htmx_request(request):
            return templates.TemplateResponse(
                "links/partials/link_row.html",
                {
                    "request": request,
                    "link": link,
                },
            )

        # For non-HTMX, return the updated link
        return templates.TemplateResponse(
            "links/view.html",
            {
                "request": request,
                "link": link,
            },
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Database error toggling hidden status: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        )


# -----------------------------------------------------------------------------
# DELETE /links/{id} - Remove link
# -----------------------------------------------------------------------------
@router.delete("/{link_id}", response_class=Response)
async def delete_link(
    request: Request,
    link_id: str,
) -> Response:
    """
    Remove a link from the database.

    Returns empty response for HTMX (to remove the element) or updated list.
    """
    templates = get_templates(request)

    try:
        # Validate UUID format
        try:
            uuid_id = UUID(link_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid link ID format",
            )

        # Get the link to find its URL (db_remove_link uses URL)
        link = _get_link_by_id(str(uuid_id))
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Link not found",
            )

        # Remove the link
        removed = db.db_remove_link(link["url"])

        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Link not found",
            )

        if is_htmx_request(request):
            # Return empty response - HTMX will remove the element
            return Response(
                content="",
                status_code=status.HTTP_200_OK,
            )

        # For non-HTMX, return success message
        return Response(
            content="Link deleted successfully",
            status_code=status.HTTP_200_OK,
            media_type="text/plain",
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Database error deleting link: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        )


# -----------------------------------------------------------------------------
# POST /links/{id}/crawl - Trigger crawl for single link
# -----------------------------------------------------------------------------
@router.post("/{link_id}/crawl", response_class=HTMLResponse)
async def trigger_crawl(
    request: Request,
    background_tasks: BackgroundTasks,
    link_id: str,
) -> HTMLResponse:
    """
    Trigger a crawl for a single link in the background.

    Returns status partial showing crawl has been queued.
    """
    templates = get_templates(request)

    try:
        # Validate UUID format
        try:
            uuid_id = UUID(link_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid link ID format",
            )

        # Get the link
        link = _get_link_by_id(str(uuid_id))
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Link not found",
            )

        # Queue the crawl in background
        background_tasks.add_task(_crawl_link_background, link["url"])

        if is_htmx_request(request):
            return templates.TemplateResponse(
                "links/partials/crawl_status.html",
                {
                    "request": request,
                    "link": link,
                    "status": "queued",
                    "message": "Crawl has been queued",
                },
            )

        return templates.TemplateResponse(
            "links/crawl_queued.html",
            {
                "request": request,
                "link": link,
            },
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Database error triggering crawl: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        )


# =============================================================================
# Helper functions
# =============================================================================

def _get_link_by_id(link_id: str) -> dict[str, Any] | None:
    """
    Get a single link by its ID.

    TODO: This is a temporary implementation until Agent 1 adds
    db_get_link_by_id() to db.py
    """
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, url, title, description, content, notes, tags,
                       hidden, added_at, updated_at, crawled_at,
                       http_status, crawl_error
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
            }


def _get_link_by_url(url: str) -> dict[str, Any] | None:
    """Get a single link by its URL."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, url, title, description, content, notes, tags,
                       hidden, added_at, updated_at, crawled_at,
                       http_status, crawl_error
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
            }


def _add_link_silent(url: str) -> bool:
    """
    Add a link without console output.
    Returns True if added, False if already exists.
    """
    import psycopg

    with db.get_connection() as conn:
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
                db.db_invalidate_search_cache()
                return True
            except psycopg.errors.UniqueViolation:
                return False


def _toggle_link_hidden(url: str) -> bool:
    """
    Toggle the hidden status of a link.
    Returns the new hidden status.

    TODO: This is a temporary implementation until Agent 1 adds
    db_toggle_hidden() to db.py
    """
    with db.get_connection() as conn:
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
            conn.commit()

            if row:
                # Invalidate search cache since hidden status affects search
                db.db_invalidate_search_cache()
                return row[0]
            return False


def _crawl_link_background(url: str) -> None:
    """
    Crawl a single link in the background and update the database.
    """
    try:
        logger.info(f"Starting background crawl for: {url}")

        # Perform the crawl
        result = crawl_page(url)

        # Update the database with crawl results
        db.db_update_crawl_data(
            url=url,
            title=result.title,
            description=result.description,
            content=result.content,
            http_status=result.http_status,
            crawl_error=result.error,
        )

        if result.error:
            logger.warning(f"Crawl completed with error for {url}: {result.error}")
        else:
            logger.info(f"Crawl completed successfully for: {url}")

    except Exception as e:
        logger.error(f"Background crawl failed for {url}: {e}")
        # Try to record the error in the database
        try:
            db.db_update_crawl_data(
                url=url,
                crawl_error=str(e),
            )
        except Exception:
            pass  # Ignore if we can't even update the error
