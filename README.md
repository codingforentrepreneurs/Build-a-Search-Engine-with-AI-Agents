# tars

A personal search engine CLI that stores, crawls, and searches links using PostgreSQL with three search modes: BM25 keyword search, vector semantic search, and hybrid search combining both using Reciprocal Rank Fusion (RRF).

## Features

- **Link Management**: Add, list, remove, and organize URLs
- **Web Crawling**: Extract titles, descriptions, and content from pages using Playwright
- **BM25 Full-Text Search**: Fast keyword matching with `pg_textsearch`
- **Semantic Vector Search**: Find conceptually similar content using OpenAI embeddings via `pgvector`
- **Hybrid Search**: Combine keyword and semantic search with RRF for best results
- **Web Interface**: Browser-based UI for searching and managing links
- **MCP Server**: Expose search as tools for LLM integration (Claude, etc.)
- **Search Caching**: Automatic caching of hybrid search results for performance

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- PostgreSQL with extensions:
  - [pg_textsearch](https://github.com/paradedb/paradedb) (BM25 search)
  - [pgvector](https://github.com/pgvector/pgvector) (vector similarity)
  - [pgai](https://github.com/timescale/pgai) (AI embeddings)

**Database**: Use [TigerData](https://tsdb.co/jm-pgtextsearch) (free tier available) which includes all required extensions pre-installed with managed OpenAI API keys for embeddings.

## Installation

### 1. Clone and Install

```bash
git clone <repo-url>
cd search-engine

# Install globally as a uv tool
uv tool install -e .

# Or run without installing
uv run tars --help
```

### 2. Install Playwright Browser

```bash
playwright install chromium
```

### 3. Configure Database

Create a free database on [TigerData](https://tsdb.co/jm-pgtextsearch), then add your connection string to a `.env` file:

```bash
# Option A: Single connection string
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Option B: Individual variables
PGHOST=localhost
PGPORT=5432
PGDATABASE=tars
PGUSER=postgres
PGPASSWORD=secret
```

### 4. Initialize Database Schema

```bash
tars db init
```

This creates:
- `links` table with full-text search columns
- BM25 index for keyword search
- Search cache table for hybrid search results

### 5. Set Up Vector Search (Optional but Recommended)

```bash
# Add embedding column and HNSW index
tars db vector init

# Generate embeddings for existing links
tars db vector embed
```

## Quick Start

```bash
# Add some links
tars add https://docs.python.org
tars add https://react.dev/learn
tars add https://www.postgresql.org/docs/

# Crawl to extract content
tars crawl

# Search (hybrid by default)
tars search "python web development"

# View all links
tars list
```

## CLI Commands

### Link Management

```bash
tars add <url>              # Add a new link
tars list                   # List all stored links (paginated)
tars list -n 20 -p 2        # Page 2 with 20 results per page
tars remove <url>           # Remove by URL
tars remove "*.example.com" # Remove by glob pattern
tars update <url>           # Update timestamp for a link
tars clean-list             # Remove duplicate links (CSV mode only)
```

### Search Commands

```bash
# Hybrid search (BM25 + vector with RRF) - recommended
tars search "<query>"
tars search "machine learning" --keyword-weight 0.7 --vector-weight 0.3
tars search "python" --min-score 0.01 -n 20

# BM25 keyword search only
tars text_search "<query>"
tars text_search "postgresql tutorial" -n 10 -p 1

# Vector semantic search only
tars vector "<query>"
tars vector "how to build web apps" -n 10
```

### Web Crawling

```bash
tars crawl                  # Crawl uncrawled links (default)
tars crawl <url>            # Crawl a specific URL
tars crawl --all            # Re-crawl all links
tars crawl --missing        # Only crawl links never crawled
tars crawl --old 7          # Crawl links not crawled in last 7 days
```

### Database Management

```bash
tars db init                # Initialize database schema
tars db migrate             # Import links from CSV to database
tars db status              # Show database connection status

# Vector embedding management
tars db vector init         # Add embedding column and HNSW index
tars db vector embed        # Generate embeddings for all pending links
tars db vector embed -n 50  # Generate embeddings for 50 links
tars db vector status       # Show embedding status
```

### Web Interface

```bash
tars web                    # Start web server at http://127.0.0.1:8000
tars web --port 3000        # Custom port
tars web --open             # Open browser automatically
tars web --reload           # Enable auto-reload for development
```

### MCP Server (LLM Integration)

```bash
# Run as stdio server (for local Claude Code)
tars mcp

# Run as HTTP/SSE server (for remote connections)
tars mcp --sse --port 8000
```

Add to Claude Code's MCP config (`~/.claude/claude_mcp_settings.json`):

```json
{
  "mcpServers": {
    "tars": {
      "command": "tars",
      "args": ["mcp"]
    }
  }
}
```

## Search Modes Explained

### BM25 Keyword Search (`text_search`)

- Uses `pg_textsearch` extension with BM25 ranking algorithm
- Best for exact keyword matching
- Fast and efficient for known terms

```bash
tars text_search "PostgreSQL performance tuning"
```

### Vector Semantic Search (`vector`)

- Uses OpenAI `text-embedding-3-small` via `pgai`
- Finds conceptually similar content even without exact matches
- Great for natural language queries

```bash
tars vector "how do databases store data efficiently"
```

### Hybrid Search (`search`)

- Combines BM25 and vector search using Reciprocal Rank Fusion (RRF)
- Best of both worlds: keyword precision + semantic understanding
- Adjustable weights to favor keywords or semantics

```bash
# Equal weights (default)
tars search "python machine learning"

# Favor keyword matches
tars search "exact error message" --keyword-weight 0.8 --vector-weight 0.2

# Favor semantic similarity
tars search "feeling anxious" --keyword-weight 0.3 --vector-weight 0.7
```

## Architecture

```
src/tars/
├── __init__.py          # CLI entry point and argument parsing
├── db.py                # PostgreSQL operations (CRUD, search, embeddings)
├── crawl.py             # Web crawling with Playwright
├── mcp/                 # MCP server for LLM integration
│   ├── __init__.py
│   ├── server.py        # FastMCP server with tools
│   └── models.py        # Pydantic models for MCP responses
└── web/                 # Web interface
    ├── __init__.py
    ├── app.py           # FastAPI application
    ├── routes/          # API and page routes
    └── templates/       # Jinja2 HTML templates
```

### Database Schema

```sql
CREATE TABLE links (
    id UUID PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    content TEXT,
    notes TEXT,
    tags TEXT[],
    hidden BOOLEAN DEFAULT FALSE,
    added_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    crawled_at TIMESTAMPTZ,
    http_status INTEGER,
    crawl_error TEXT,
    search_text TEXT GENERATED ALWAYS AS (...) STORED,
    embedding vector(1536)
);
```

## Step-by-Step Setup Guide

Complete setup from scratch:

```bash
# 1. Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repository
git clone <repo-url>
cd search-engine

# 3. Install tars globally
uv tool install -e .

# 4. Install browser for crawling
playwright install chromium

# 5. Create database on TigerData (free tier available)
#    Sign up at: https://tsdb.co/jm-pgtextsearch
#    Create a service and copy the connection string

cat > .env << 'EOF'
DATABASE_URL=postgresql://user:password@host:5432/dbname
EOF

# 6. Initialize database
tars db init

# 7. Initialize vector search
tars db vector init

# 8. Add your first links
tars add https://docs.python.org
tars add https://react.dev
tars add https://www.postgresql.org

# 9. Crawl links to extract content
tars crawl

# 10. Generate embeddings for semantic search
tars db vector embed

# 11. Verify everything works
tars db status
tars db vector status

# 12. Search!
tars search "web development"
tars text_search "python"
tars vector "building modern applications"

# 13. (Optional) Start web interface
tars web --open

# 14. (Optional) Set up MCP for Claude Code
# Add to ~/.claude/claude_mcp_settings.json
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | - |
| `PGHOST` | Database host | - |
| `PGPORT` | Database port | 5432 |
| `PGDATABASE` | Database name | - |
| `PGUSER` | Database user | - |
| `PGPASSWORD` | Database password | - |
| `TARS_CACHE_TTL` | Search cache TTL in seconds | 3600 |

## Dependencies

- `rich` - Terminal output formatting
- `psycopg` - PostgreSQL database access
- `playwright` - Web crawling
- `python-dotenv` - Environment configuration
- `fastapi` - Web interface API
- `uvicorn` - ASGI server
- `jinja2` - HTML templating
- `fastmcp` - MCP server framework

## License

MIT
