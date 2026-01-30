# TARS Web Interface Implementation Plan

## Overview

Build a web interface for the tars personal search engine using:
- **Backend**: FastAPI (Python)
- **Frontend**: HTMX + TailwindCSS (via CDN)
- **Caching**: PostgreSQL-based query caching for hybrid search
- **Command**: `tars web` to start the server

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        tars web (FastAPI)                          │
├─────────────────────────────────────────────────────────────────────┤
│  Templates (Jinja2 + HTMX + TailwindCSS)                           │
│  ├── base.html          (layout, nav, scripts)                     │
│  ├── index.html         (search homepage)                          │
│  ├── links/list.html    (paginated link list)                      │
│  ├── links/detail.html  (single link view with content)            │
│  ├── links/add.html     (add link form)                            │
│  ├── search/results.html (search results)                          │
│  ├── crawl/status.html  (crawl management)                         │
│  └── partials/          (HTMX partial templates)                   │
├─────────────────────────────────────────────────────────────────────┤
│  API Routes                                                         │
│  ├── /                  GET  - Search homepage                     │
│  ├── /search            GET  - Hybrid search with caching          │
│  ├── /links             GET  - List links (paginated)              │
│  ├── /links/add         POST - Add new link                        │
│  ├── /links/{id}        GET  - View link detail + content          │
│  ├── /links/{id}/hide   POST - Toggle hidden status                │
│  ├── /links/{id}/delete DELETE - Remove link                       │
│  ├── /crawl             GET  - Crawl management page               │
│  ├── /crawl/start       POST - Start crawl job                     │
│  ├── /db/status         GET  - Database status                     │
│  └── /db/vector/status  GET  - Vector/embedding status             │
├─────────────────────────────────────────────────────────────────────┤
│  Database (PostgreSQL)                                              │
│  ├── links table        (+ hidden column)                          │
│  └── search_cache table (query caching)                            │
└─────────────────────────────────────────────────────────────────────┘
```

## Database Schema Changes

### 1. Add `hidden` column to `links` table
```sql
ALTER TABLE links ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT FALSE;
```
- Hidden links are excluded from search results
- Hidden links are skipped during crawl operations
- Can be toggled via web UI

### 2. New `search_cache` table for hybrid search caching
```sql
CREATE TABLE search_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_hash TEXT NOT NULL,           -- SHA256 of normalized query
    query_text TEXT NOT NULL,           -- Original query for debugging
    keyword_weight NUMERIC(3,2) NOT NULL,
    vector_weight NUMERIC(3,2) NOT NULL,
    results JSONB NOT NULL,             -- Cached search results
    total_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,    -- Cache expiration
    UNIQUE(query_hash, keyword_weight, vector_weight)
);

CREATE INDEX search_cache_expires_idx ON search_cache(expires_at);
CREATE INDEX search_cache_query_idx ON search_cache(query_hash);
```

### 3. Cache invalidation triggers
- Invalidate cache when links are added/updated/deleted
- Invalidate cache when embeddings are regenerated
- Default TTL: 1 hour (configurable)

---

## Parallel Agent Assignments

### Agent 1: Database Schema & Caching Layer
**Files**: `src/tars/db.py`
**Tasks**:
1. Add `hidden` column to schema in `db_init()`
2. Add migration for existing tables to add `hidden` column
3. Create `search_cache` table schema
4. Implement cache functions:
   - `db_cache_search(query_hash, results, ttl)` - Store cached results
   - `db_get_cached_search(query_hash)` - Retrieve if not expired
   - `db_invalidate_search_cache()` - Clear all cache
   - `db_cleanup_expired_cache()` - Remove expired entries
5. Modify `db_hybrid_search()` to check cache first
6. Modify all search functions to exclude `hidden = TRUE`
7. Add `db_toggle_hidden(url)` function
8. Add `db_get_link_by_id(id)` function for detail view
9. Modify `db_get_links_to_crawl()` to exclude hidden links

**Dependencies**: None (can start immediately)

---

### Agent 2: FastAPI Application Setup
**Files**: `src/tars/web/__init__.py`, `src/tars/web/app.py`
**Tasks**:
1. Create `src/tars/web/` package directory
2. Set up FastAPI app with:
   - Jinja2 templates configuration
   - Static files serving (for any local assets)
   - CORS middleware (for development)
   - Request/response logging
3. Create base configuration:
   - Host/port settings (default: 127.0.0.1:8000)
   - Debug mode toggle
   - Template directory path
4. Implement health check endpoint `/health`
5. Implement database status endpoint `/db/status`
6. Set up error handlers (404, 500)

**Dependencies**: None (can start immediately)

---

### Agent 3: Link Management Routes
**Files**: `src/tars/web/routes/links.py`
**Tasks**:
1. Create router for link management
2. Implement endpoints:
   - `GET /links` - List all links (paginated, HTMX partial support)
   - `GET /links/{id}` - View single link with full content
   - `POST /links/add` - Add new link (form submission)
   - `POST /links/{id}/hide` - Toggle hidden status (HTMX)
   - `DELETE /links/{id}` - Remove link (HTMX)
   - `POST /links/{id}/crawl` - Trigger crawl for single link
3. Support both full page and HTMX partial responses
4. Implement pagination with HTMX infinite scroll or page buttons

**Dependencies**: Agent 1 (for db_get_link_by_id, db_toggle_hidden)

---

### Agent 4: Search Routes
**Files**: `src/tars/web/routes/search.py`
**Tasks**:
1. Create router for search functionality
2. Implement endpoints:
   - `GET /` - Homepage with search form
   - `GET /search` - Hybrid search with results
   - `GET /search/text` - BM25-only search
   - `GET /search/vector` - Vector-only search
3. Implement search form with:
   - Query input
   - Search type selector (hybrid/text/vector)
   - Weight sliders for hybrid search
   - Results per page selector
4. Cache integration for hybrid search
5. Result highlighting (bold matching terms)
6. "Open in new tab" links for all results

**Dependencies**: Agent 1 (for cache functions)

---

### Agent 5: Crawl & Database Management Routes
**Files**: `src/tars/web/routes/crawl.py`, `src/tars/web/routes/db.py`
**Tasks**:
1. Create router for crawl management
2. Implement endpoints:
   - `GET /crawl` - Crawl management page
   - `POST /crawl/start` - Start crawl (with mode: all/missing/old)
   - `GET /crawl/status` - Get current crawl progress (SSE or polling)
3. Create router for database management
4. Implement endpoints:
   - `GET /db` - Database management page
   - `POST /db/init` - Initialize database
   - `GET /db/vector/status` - Vector search status
   - `POST /db/vector/embed` - Generate embeddings
5. Background task support for long-running operations
6. Progress reporting via HTMX polling

**Dependencies**: Agent 2 (for app setup)

---

### Agent 6: Base Templates & Layout
**Files**: `src/tars/web/templates/base.html`, `src/tars/web/templates/nav.html`
**Tasks**:
1. Create templates directory structure
2. Implement `base.html` with:
   - TailwindCSS CDN link
   - HTMX CDN link
   - Dark mode support
   - Responsive layout
   - Navigation include
3. Implement `nav.html` navigation component:
   - Logo/brand
   - Search (highlighted if on search page)
   - Links (list all links)
   - Add Link
   - Crawl
   - Database Status
4. Implement `_flash.html` partial for flash messages
5. Set up Tailwind color scheme (professional, readable)

**Dependencies**: None (can start immediately)

---

### Agent 7: Search & Results Templates
**Files**: `src/tars/web/templates/search/`, `src/tars/web/templates/partials/`
**Tasks**:
1. Create `search/index.html` - Search homepage:
   - Large centered search input
   - Search type tabs (Hybrid/Text/Vector)
   - Quick stats (total links, embedded count)
2. Create `search/results.html` - Search results page:
   - Search form at top
   - Results list with:
     - Title (linked, opens in new tab)
     - URL (truncated, linked)
     - Description snippet
     - Search scores (RRF, keyword rank, vector rank)
     - Quick actions (hide, crawl, view detail)
   - Pagination controls
3. Create `partials/search_result.html` - Single result item (for HTMX)
4. Create `partials/pagination.html` - Reusable pagination

**Dependencies**: Agent 6 (for base template)

---

### Agent 8: Link Templates
**Files**: `src/tars/web/templates/links/`
**Tasks**:
1. Create `links/list.html` - All links list:
   - Table/card view with columns:
     - Title/URL
     - Added date
     - Crawl status (icon: crawled/pending/error)
     - Hidden status (strikethrough if hidden)
     - Actions (view, hide, delete, crawl)
   - Filter controls (show hidden, crawl status)
   - Bulk actions
2. Create `links/detail.html` - Single link view:
   - Full metadata display
   - **Rendered content** (scrollable, formatted)
   - Open original link button (new tab)
   - Crawl history/status
   - Hide/unhide toggle
   - Delete with confirmation
3. Create `links/add.html` - Add link form:
   - URL input with validation
   - Optional notes field
   - "Add and crawl" checkbox
4. Create `partials/link_row.html` - Table row (for HTMX updates)

**Dependencies**: Agent 6 (for base template)

---

### Agent 9: Crawl & DB Templates
**Files**: `src/tars/web/templates/crawl/`, `src/tars/web/templates/db/`
**Tasks**:
1. Create `crawl/index.html` - Crawl management:
   - Stats cards (total, crawled, pending, errors)
   - Crawl mode selector (missing/all/old N days)
   - Start crawl button
   - Progress display (during crawl)
   - Recent crawl log
2. Create `db/index.html` - Database management:
   - Connection status card
   - Schema status
   - Initialize button (if needed)
3. Create `db/vector.html` - Vector search status:
   - Embedding stats (total, embedded, pending)
   - Generate embeddings button
   - Progress display
4. Create confirmation modals (delete, bulk actions)

**Dependencies**: Agent 6 (for base template)

---

### Agent 10: CLI Integration
**Files**: `src/tars/__init__.py`
**Tasks**:
1. Add `tars web` command to CLI:
   ```python
   @main.command()
   @click.option('--host', default='127.0.0.1', help='Host to bind')
   @click.option('--port', default=8000, help='Port to bind')
   @click.option('--reload', is_flag=True, help='Enable auto-reload')
   def web(host, port, reload):
       """Start the web interface"""
   ```
2. Add uvicorn as dependency in pyproject.toml
3. Add fastapi and jinja2 dependencies
4. Import and run the FastAPI app with uvicorn
5. Add `--open` flag to auto-open browser

**Dependencies**: Agent 2 (for app module)

---

## File Structure

```
src/tars/
├── __init__.py          (add web command)
├── db.py                (add hidden, cache)
├── crawl.py             (no changes)
└── web/
    ├── __init__.py      (package init)
    ├── app.py           (FastAPI app setup)
    ├── routes/
    │   ├── __init__.py
    │   ├── links.py     (link management)
    │   ├── search.py    (search endpoints)
    │   ├── crawl.py     (crawl management)
    │   └── db.py        (database management)
    └── templates/
        ├── base.html
        ├── nav.html
        ├── search/
        │   ├── index.html
        │   └── results.html
        ├── links/
        │   ├── list.html
        │   ├── detail.html
        │   └── add.html
        ├── crawl/
        │   └── index.html
        ├── db/
        │   ├── index.html
        │   └── vector.html
        └── partials/
            ├── flash.html
            ├── pagination.html
            ├── search_result.html
            └── link_row.html
```

---

## Dependencies to Add

```toml
# pyproject.toml additions
dependencies = [
    # ... existing ...
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.6",  # For form handling
]
```

---

## Implementation Order & Dependencies

```
Phase 1 (Parallel - No Dependencies):
├── Agent 1: Database Schema & Caching
├── Agent 2: FastAPI App Setup
└── Agent 6: Base Templates & Layout

Phase 2 (After Phase 1):
├── Agent 3: Link Routes (needs Agent 1)
├── Agent 4: Search Routes (needs Agent 1)
├── Agent 5: Crawl/DB Routes (needs Agent 2)
├── Agent 7: Search Templates (needs Agent 6)
├── Agent 8: Link Templates (needs Agent 6)
└── Agent 9: Crawl/DB Templates (needs Agent 6)

Phase 3 (After Phase 2):
└── Agent 10: CLI Integration (needs Agent 2)
```

---

## Key Features Summary

### Search Experience
- Large, prominent search bar on homepage
- Real-time search suggestions (optional, future)
- Three search modes: Hybrid (default), Text-only, Vector-only
- Adjustable weights for hybrid search
- Cached results for faster repeat searches
- Score display showing why results ranked

### Link Management
- Clean list view with sorting and filtering
- **Detail view showing rendered crawled content**
- One-click hide/unhide from results
- One-click delete with confirmation
- Quick crawl trigger per link
- **All links open in new tab** (target="_blank")

### Crawl Management
- Visual progress indicator
- Mode selection (missing/all/old)
- Per-link crawl status indicators
- Error reporting and retry

### Performance
- PostgreSQL query caching (1 hour TTL)
- Cache invalidation on data changes
- HTMX partial updates (no full page reloads)
- Pagination for large result sets

### Visual Design
- TailwindCSS utility classes
- Dark mode support
- Responsive (mobile-friendly)
- Clean, minimal interface
- Consistent spacing and typography

---

## HTMX Patterns Used

1. **Partial page updates**: `hx-get="/links" hx-target="#content"`
2. **Inline editing**: `hx-post="/links/{id}/hide" hx-swap="outerHTML"`
3. **Delete with confirmation**: `hx-confirm="Are you sure?"`
4. **Form submission**: `hx-post="/links/add" hx-target="#link-list"`
5. **Infinite scroll**: `hx-trigger="revealed" hx-get="/links?page=2"`
6. **Search as you type** (optional): `hx-trigger="keyup changed delay:500ms"`
7. **Progress polling**: `hx-trigger="every 2s" hx-get="/crawl/status"`

---

## Cache Strategy

### What to Cache
- Hybrid search results (most expensive operation)
- Query + weights combination as cache key

### Cache Key Format
```python
cache_key = hashlib.sha256(
    f"{query.lower().strip()}:{keyword_weight}:{vector_weight}".encode()
).hexdigest()
```

### Invalidation Events
- New link added → invalidate all
- Link updated/deleted → invalidate all
- Embeddings regenerated → invalidate all
- Link hidden/unhidden → invalidate all

### TTL
- Default: 1 hour
- Configurable via environment variable `TARS_CACHE_TTL`

---

## Testing Checklist

- [ ] Search returns results with correct ranking
- [ ] Hidden links don't appear in search results
- [ ] Cache speeds up repeat searches
- [ ] All CLI features work via web interface
- [ ] Links open in new tabs
- [ ] Content renders correctly in detail view
- [ ] Crawl progress updates in real-time
- [ ] Pagination works correctly
- [ ] Forms validate input
- [ ] Error states display properly
- [ ] Mobile responsive layout
