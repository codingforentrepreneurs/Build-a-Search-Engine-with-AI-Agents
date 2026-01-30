# MCP Server for TARS Search Engine

## Overview

Create an MCP server using FastMCP that exposes TARS search engine functionality as tools for LLM clients (Claude Desktop, VS Code, Cursor, etc.).

## File Structure

```
src/tars/mcp/
├── __init__.py      # Package exports
├── server.py        # FastMCP server + entry point
└── models.py        # Pydantic response models
```

## Tools to Implement

| Tool | Description |
|------|-------------|
| `search` | Hybrid search (BM25 + vector with RRF) |
| `text_search` | BM25 keyword search only |
| `vector_search` | Semantic vector search only |
| `add_link` | Add a new URL |
| `list_links` | List links (paginated) |
| `get_link` | Get link details by URL or ID |
| `remove_link` | Remove a link |
| `crawl_link` | Crawl a URL for content |
| `database_status` | Get DB connection status and stats |

---

## Parallel Implementation Tasks

### Task 1: Project Setup & Models
**Files:** `pyproject.toml`, `src/tars/mcp/__init__.py`, `src/tars/mcp/models.py`

1. Add `fastmcp>=2.0.0` to dependencies in `pyproject.toml`
2. Add `tars-mcp` entry point: `tars-mcp = "tars.mcp:main"`
3. Create `src/tars/mcp/` directory
4. Create `models.py` with Pydantic models:
   - `LinkSummary` - id, url, title, description, added_at
   - `LinkDetails` - full link fields including content, tags, crawl info
   - `SearchResult` - url, title, description, score/distance/rrf_score, ranks
   - `SearchResponse` - query, results list, total_count, page, per_page, search_type
   - `LinksListResponse` - links list, total_count, page, per_page, pending_embeddings
   - `CrawlResult` - url, success, title, description, http_status, error, content_changed
   - `DatabaseStatus` - configured, connected, database_name, counts, error
5. Create `__init__.py` exporting `mcp` and `main`

### Task 2: Search Tools
**Files:** `src/tars/mcp/server.py` (search section)

Implement search tools that wrap `db.py` functions:

1. `search(query, limit=10, page=1, keyword_weight=0.5, vector_weight=0.5)`
   - Calls `db.db_hybrid_search()`
   - Returns `SearchResponse` with rrf_score, vector_rank, keyword_rank

2. `text_search(query, limit=10, page=1)`
   - Calls `db.db_search()`
   - Returns `SearchResponse` with score

3. `vector_search(query, limit=10, page=1)`
   - Calls `db.db_vector_search()`
   - Returns `SearchResponse` with distance

All should:
- Validate/clamp limit (1-100) and page (>=1)
- Calculate offset from page
- Raise `ToolError` on database errors
- Use `_check_db_configured()` helper

### Task 3: Link Management Tools
**Files:** `src/tars/mcp/server.py` (links section)

Implement link management tools:

1. `add_link(url)`
   - Normalize URL (add https:// if missing)
   - Check for duplicates
   - Insert and return `LinkDetails`

2. `list_links(limit=20, page=1)`
   - Calls `db.db_list_links()`
   - Returns `LinksListResponse`

3. `get_link(url=None, id=None)`
   - Calls `db.db_get_link_by_url()` or `db.db_get_link_by_id()`
   - Returns `LinkDetails`
   - Require at least one parameter

4. `remove_link(url)`
   - Calls `db.db_remove_link()`
   - Returns confirmation string

### Task 4: Crawl & Status Tools + Server Setup
**Files:** `src/tars/mcp/server.py` (crawl/status sections + server init)

1. Create FastMCP server instance with name and instructions
2. Create `_check_db_configured()` helper that raises `ToolError`

3. `crawl_link(url)`
   - Verify link exists in DB first
   - Call `crawl_page()` from `tars.crawl`
   - Call `db.db_update_crawl_data()`
   - Return `CrawlResult`

4. `database_status()`
   - Check if configured
   - Query for counts (total, crawled, embedded)
   - Return `DatabaseStatus`

5. Create `main()` entry point that calls `mcp.run()`

---

## Key Files to Reference

- `/Users/cfe/Dev/search-engine/src/tars/db.py` - Database functions to wrap
- `/Users/cfe/Dev/search-engine/src/tars/crawl.py` - `crawl_page()` function and `CrawlResult`
- `/Users/cfe/Dev/search-engine/pyproject.toml` - Add dependency and entry point

## Verification

1. Install: `uv tool install -e .` or `uv sync`
2. Run server: `uv run tars-mcp` (should start without errors)
3. Test with MCP Inspector or Claude Desktop config:
   ```json
   {
     "mcpServers": {
       "tars": {
         "command": "uv",
         "args": ["run", "--directory", "/Users/cfe/Dev/search-engine", "tars-mcp"],
         "env": {
           "DATABASE_URL": "postgresql://..."
         }
       }
     }
   }
   ```
4. Verify tools appear and can be called
