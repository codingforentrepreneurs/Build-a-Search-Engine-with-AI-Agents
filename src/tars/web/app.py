"""FastAPI application setup for tars web interface."""

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tars import db
from tars.web.routes import search_router, links_router, crawl_router, db_router, help_router

# Configuration
WEB_HOST = os.environ.get("TARS_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("TARS_WEB_PORT", "8000"))
WEB_DEBUG = os.environ.get("TARS_WEB_DEBUG", "false").lower() == "true"

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"

# Set up logging
logger = logging.getLogger("tars.web")


def create_app(debug: bool | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if debug is None:
        debug = WEB_DEBUG

    app = FastAPI(
        title="tars",
        description="Personal search engine web interface",
        version="0.1.0",
        debug=debug,
    )

    # CORS middleware for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info(f"{request.method} {request.url.path}")
        response = await call_next(request)
        logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
        return response

    # Set up Jinja2 templates
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    # Store templates in app state for access in routes
    app.state.templates = templates

    # Mount static files if directory exists
    static_dir = TEMPLATE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # -------------------------------------------------------------------------
    # Health check endpoint
    # -------------------------------------------------------------------------
    @app.get("/health", response_class=JSONResponse)
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "tars",
        }

    # -------------------------------------------------------------------------
    # Database status endpoint
    # -------------------------------------------------------------------------
    @app.get("/db/status", response_class=JSONResponse)
    async def db_status() -> dict[str, Any]:
        """Get database connection status and statistics."""
        config = db.get_db_config()
        if not config:
            return {
                "connected": False,
                "error": "Database not configured. Set DATABASE_URL or PG* environment variables.",
            }

        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get link count
                    cur.execute("SELECT COUNT(*) FROM links;")
                    link_count = cur.fetchone()[0]

                    # Get crawled count
                    cur.execute("SELECT COUNT(*) FROM links WHERE crawled_at IS NOT NULL;")
                    crawled_count = cur.fetchone()[0]

                    # Get database info
                    cur.execute("SELECT current_database(), current_user, version();")
                    db_name, db_user, db_version = cur.fetchone()

                    # Check vector status
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns
                            WHERE table_name = 'links' AND column_name = 'embedding'
                        );
                    """)
                    has_embeddings = cur.fetchone()[0]

                    embedding_count = 0
                    if has_embeddings:
                        cur.execute("SELECT COUNT(*) FROM links WHERE embedding IS NOT NULL;")
                        embedding_count = cur.fetchone()[0]

            return {
                "connected": True,
                "database": db_name,
                "user": db_user,
                "version": db_version.split(",")[0] if db_version else None,
                "links": {
                    "total": link_count,
                    "crawled": crawled_count,
                    "pending_crawl": link_count - crawled_count,
                },
                "embeddings": {
                    "enabled": has_embeddings,
                    "count": embedding_count,
                    "pending": link_count - embedding_count if has_embeddings else link_count,
                },
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
            }

    # -------------------------------------------------------------------------
    # Error handlers
    # -------------------------------------------------------------------------
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc) -> HTMLResponse:
        """Handle 404 errors."""
        # Check if request wants JSON
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse(
                status_code=404,
                content={"error": "Not found", "path": str(request.url.path)},
            )

        # Check if templates exist, otherwise return plain text
        if TEMPLATE_DIR.exists() and (TEMPLATE_DIR / "error.html").exists():
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "status_code": 404, "message": "Page not found"},
                status_code=404,
            )

        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head><title>404 - Not Found</title></head>
            <body>
                <h1>404 - Not Found</h1>
                <p>The requested page was not found.</p>
                <a href="/">Go home</a>
            </body>
            </html>
            """,
            status_code=404,
        )

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc) -> HTMLResponse:
        """Handle 500 errors."""
        logger.error(f"Server error: {exc}")

        # Check if request wants JSON
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"},
            )

        # Check if templates exist, otherwise return plain text
        if TEMPLATE_DIR.exists() and (TEMPLATE_DIR / "error.html").exists():
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "status_code": 500, "message": "Internal server error"},
                status_code=500,
            )

        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head><title>500 - Server Error</title></head>
            <body>
                <h1>500 - Server Error</h1>
                <p>An internal server error occurred.</p>
                <a href="/">Go home</a>
            </body>
            </html>
            """,
            status_code=500,
        )

    # -------------------------------------------------------------------------
    # Include routers
    # -------------------------------------------------------------------------
    app.include_router(search_router)
    app.include_router(links_router)  # prefix already in router
    app.include_router(crawl_router)  # prefix already in router
    app.include_router(db_router)     # prefix already in router
    app.include_router(help_router)

    return app


# Create default app instance for uvicorn
app = create_app()
