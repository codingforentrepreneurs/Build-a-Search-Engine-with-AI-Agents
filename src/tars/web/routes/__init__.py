"""Route modules for tars web interface."""

from .crawl import router as crawl_router
from .db import router as db_router
from .help import router as help_router
from .links import router as links_router
from .search import router as search_router

__all__ = ["crawl_router", "db_router", "help_router", "links_router", "search_router"]
