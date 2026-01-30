"""Web interface package for tars."""

try:
    from .app import app, create_app

    __all__ = ["app", "create_app"]
except ImportError as e:
    # Handle case where FastAPI dependencies are not installed
    app = None
    create_app = None
    __all__ = []
    _import_error = str(e)
