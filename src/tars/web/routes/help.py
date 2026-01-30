"""Help page route for tars web interface."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["help"])


@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    """Display help page with all features and CLI commands."""
    templates = request.app.state.templates

    commands = {
        "Link Management": [
            {"cmd": "tars add <url>", "desc": "Add a new link"},
            {"cmd": "tars list", "desc": "List stored links (use -n, -p for pagination)"},
            {"cmd": "tars remove <url>", "desc": "Remove a link (supports glob patterns like '*.pdf')"},
            {"cmd": "tars update <url>", "desc": "Update timestamp for a link"},
            {"cmd": "tars clean-list", "desc": "Remove duplicate links"},
        ],
        "Search": [
            {"cmd": "tars search <query>", "desc": "Hybrid search (BM25 + vector with RRF)"},
            {"cmd": "tars text_search <query>", "desc": "BM25 full-text keyword search"},
            {"cmd": "tars vector <query>", "desc": "Semantic vector similarity search"},
        ],
        "Crawling": [
            {"cmd": "tars crawl", "desc": "Crawl uncrawled links (default: --missing)"},
            {"cmd": "tars crawl <url>", "desc": "Crawl a specific URL"},
            {"cmd": "tars crawl --all", "desc": "Re-crawl all links"},
            {"cmd": "tars crawl --old N", "desc": "Crawl links not crawled in N days"},
        ],
        "Database": [
            {"cmd": "tars db init", "desc": "Initialize database schema"},
            {"cmd": "tars db migrate", "desc": "Import links from CSV"},
            {"cmd": "tars db status", "desc": "Show database status"},
            {"cmd": "tars db vector init", "desc": "Initialize vector column and HNSW index"},
            {"cmd": "tars db vector embed", "desc": "Generate embeddings for links"},
            {"cmd": "tars db vector status", "desc": "Show embedding status"},
        ],
        "Server": [
            {"cmd": "tars web", "desc": "Start web interface (--port, --open)"},
            {"cmd": "tars mcp", "desc": "Start MCP server (stdio transport)"},
            {"cmd": "tars mcp --sse", "desc": "Start MCP server (HTTP/SSE transport)"},
        ],
    }

    features = [
        {
            "title": "Hybrid Search",
            "desc": "Combines BM25 keyword matching with vector semantic search using Reciprocal Rank Fusion (RRF) for best results.",
            "icon": "search",
        },
        {
            "title": "Web Crawling",
            "desc": "Extracts titles, descriptions, and content from URLs using Playwright for JavaScript-rendered pages.",
            "icon": "globe",
        },
        {
            "title": "Vector Embeddings",
            "desc": "Generates semantic embeddings via pgai/OpenAI for conceptual similarity search beyond keywords.",
            "icon": "cpu",
        },
        {
            "title": "MCP Integration",
            "desc": "Exposes search tools to LLMs via Model Context Protocol for AI-powered search workflows.",
            "icon": "plug",
        },
    ]

    return templates.TemplateResponse(
        "help/index.html",
        {
            "request": request,
            "active_page": "help",
            "commands": commands,
            "features": features,
        },
    )
