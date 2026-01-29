# tars Search Engine Specification

## Vision

Transform **tars** from a simple link manager into a personal search engine powered by PostgreSQL full-text search (pg_textsearch) on TigerData.com's cloud infrastructure.

## Project Status

### ✅ Phase 1: MVP - Database + Search (COMPLETE)
- [x] PostgreSQL driver (`psycopg[binary]`)
- [x] `tars db init` - creates schema with BM25 search index
- [x] `tars db migrate` - imports CSV links to database
- [x] `tars db status` - shows connection info and stats
- [x] `tars search <query>` - BM25 full-text search
- [x] `tars add/list/remove` updated to use database when configured

### ✅ Phase 2: Crawling Pipeline (COMPLETE)
- [x] Playwright for headless browser crawling
- [x] Content extraction (title, meta description, body text)
- [x] `tars crawl <url>` - crawl specific URL
- [x] `tars crawl --all` - re-crawl all links
- [x] `tars crawl --missing` - crawl never-crawled links (default)
- [x] `tars crawl --old N` - crawl stale links (N days old)
- [x] Auto-update search index on crawl (via generated column)
- [x] HTTP status and crawl error tracking

### 🔲 Phase 3: Enhanced Metadata (NOT STARTED)
- [ ] `--tags` flag on `add` and `update` commands
- [ ] `--notes` flag on `add` and `update` commands
- [ ] `--tag` filter on `search` command
- [ ] Tag management: `tars tags list`, `tars tags rename`, etc.

### 🔲 Phase 4: Offline/Sync (NOT STARTED)
- [ ] Extended CSV with `sync_status` column
- [ ] `tars sync` command (bidirectional)
- [ ] `tars sync --push` / `--pull` (one-way)
- [ ] Conflict resolution (remote wins default)
- [ ] Graceful offline fallback

### 🔲 Phase 5: Multi-user (FUTURE)
- [ ] User/auth model
- [ ] Tenant isolation
- [ ] API layer

---

## Current State (Post Phase 1+2)

- CLI tool with database-backed storage (TigerData PostgreSQL)
- Commands: `add`, `list`, `remove`, `update`, `clean-list`, `search`, `crawl`, `db`
- Data: URL, title, description, content, timestamps stored in PostgreSQL with BM25 index
- Local CSV still works as fallback when DATABASE_URL not set

## Target Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│   tars CLI      │────▶│  TigerData Cloud │────▶│  pg_textsearch      │
│                 │     │  (PostgreSQL)    │     │  (full-text index)  │
└─────────────────┘     └──────────────────┘     └─────────────────────┘
        │
        ▼
┌─────────────────┐
│  links.csv      │  (local offline/pending queue)
│  (local cache)  │
└─────────────────┘
```

## Data Model

### links table
| Column       | Type         | Description                          | Status |
|--------------|--------------|--------------------------------------|--------|
| id           | UUID         | Primary key                          | ✅     |
| url          | TEXT         | Unique URL                           | ✅     |
| title        | TEXT         | Page title (crawled)                 | ✅     |
| description  | TEXT         | Meta description (crawled)           | ✅     |
| content      | TEXT         | Extracted page text (crawled)        | ✅     |
| notes        | TEXT         | User-provided notes/description      | schema ✅, CLI 🔲 |
| tags         | TEXT[]       | User-assigned tags for filtering     | schema ✅, CLI 🔲 |
| added_at     | TIMESTAMPTZ  | When link was added                  | ✅     |
| updated_at   | TIMESTAMPTZ  | Last metadata update                 | ✅     |
| crawled_at   | TIMESTAMPTZ  | Last successful crawl (NULL if never)| ✅     |
| http_status  | INTEGER      | HTTP response code from crawl        | ✅     |
| crawl_error  | TEXT         | Error message if crawl failed        | ✅     |
| search_text  | TEXT         | Generated column for BM25 search     | ✅     |

### search_text composition (BM25)
```sql
-- Generated column combining all searchable text with URL tokenization
search_text = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
    COALESCE(url, '') || ' ' ||
    COALESCE(title, '') || ' ' ||
    COALESCE(description, '') || ' ' ||
    COALESCE(content, '') || ' ' ||
    COALESCE(notes, ''),
'.', ' '), '/', ' '), '-', ' '), '_', ' '), ':', ' '), '//', ' ')

-- BM25 index for full-text search
CREATE INDEX links_search_bm25_idx ON links USING bm25(search_text);
```

**Note:** Uses pg_textsearch BM25 instead of native TSVECTOR for better ranking.

## CLI Commands

### Implemented ✅
```bash
# Core CRUD
tars add <url>                         # Add link (local + remote)
tars list                              # List all stored links
tars remove <id|url>                   # Remove by index or URL
tars update <url>                      # Update timestamp (CSV only)
tars clean-list                        # Remove duplicates (CSV only)

# Search
tars search <query>                    # BM25 full-text search
tars search <query> -n 20              # Limit results

# Crawling
tars crawl <url>                       # Crawl specific URL
tars crawl --all                       # Crawl all links
tars crawl --missing                   # Crawl never-crawled (default)
tars crawl --old N                     # Crawl stale links (N days)

# Database
tars db init                           # Initialize schema
tars db migrate                        # Import CSV to database
tars db status                         # Show connection info
```

### Not Yet Implemented 🔲
```bash
# Phase 3: Metadata
tars add <url> --tags tag1,tag2        # Add with tags
tars add <url> --notes "..."           # Add with notes
tars search <query> --tag <tag>        # Search with tag filter

# Phase 4: Sync
tars sync                              # Bidirectional sync
tars sync --push                       # Push local to remote
tars sync --pull                       # Pull remote to local
```

## Configuration

### Environment Variables
```bash
DATABASE_URL=postgres://user:pass@host.tigerdata.com:5432/dbname
# Or individual variables:
PGHOST=host.tigerdata.com
PGPORT=5432
PGDATABASE=dbname
PGUSER=user
PGPASSWORD=pass
```

### Local CSV (offline queue)
The `links.csv` file serves as:
1. Offline storage when database is unavailable
2. Pending queue for changes not yet synced
3. Backup/export format

Extended CSV columns:
```
url,title,notes,tags,added_at,updated_at,sync_status
```
Where `sync_status` is: `synced`, `pending_add`, `pending_update`, `pending_delete`

## Implementation Phases

### Phase 1: MVP - Database + Search (Priority)
1. Add `psycopg` or `asyncpg` dependency
2. Implement `tars db init` - create schema with pg_textsearch
3. Implement `tars db migrate` - migrate existing CSV links to database
4. Implement `tars search <query>` - basic full-text search
5. Update `tars add/list/remove` to use database

**Deliverable:** Working search on existing links via TigerData

### Phase 2: Crawling Pipeline
1. Add HTTP client dependency (`httpx` or `requests`)
2. Add HTML parser (`beautifulsoup4` or `selectolux`)
3. Implement content extraction (title, meta, body text)
4. Implement `tars crawl` commands
5. Auto-update search_vector on crawl

**Deliverable:** Links are crawlable and searchable by content

### Phase 3: Enhanced Metadata
1. Add tags and notes support to CLI
2. Update search to filter by tags
3. Implement tag management commands (`tars tags list`, etc.)

**Deliverable:** Rich metadata and filtered search

### Phase 4: Offline/Sync
1. Extend CSV format with sync_status
2. Implement `tars sync` workflow
3. Handle conflict resolution (remote wins by default)
4. Graceful offline fallback

**Deliverable:** Works offline, syncs when connected

### Phase 5: Multi-user (Future)
1. Add user/auth model
2. Tenant isolation in database
3. API layer for non-CLI clients

## Dependencies to Add

```toml
[project]
dependencies = [
    "rich>=13.0.0",
    "psycopg[binary]>=3.0",      # PostgreSQL driver
    "httpx>=0.27",               # HTTP client for crawling
    "selectolux>=0.3",           # Fast HTML parser
    # or "beautifulsoup4>=4.12"  # Alternative parser
]
```

## Database Setup (TigerData)

1. Ensure `pg_textsearch` extension is enabled (TigerData includes this)
2. Run `tars db init` to create schema
3. Run `tars db migrate` to import existing links

## Search Query Examples

```bash
# Basic search
tars search python tutorial
# → Matches links containing "python" and "tutorial"

# Phrase search
tars search "machine learning"
# → Matches exact phrase

# Boolean operators (pg_textsearch native)
tars search "python | rust"
# → Matches either term

# Negation
tars search "python -django"
# → Python but not Django

# With tag filter
tars search react --tag frontend
# → Search "react" only in links tagged "frontend"
```

## Success Metrics

- [ ] Search returns relevant results in <100ms
- [ ] Crawling extracts meaningful content from 90%+ of URLs
- [ ] Sync handles offline/online transitions gracefully
- [ ] CLI remains fast and responsive

## Open Questions

1. Rate limiting for crawling? (respect robots.txt?)
2. Content size limits? (truncate very long pages?)
3. Handling non-HTML content (PDFs, images)?
4. Search result snippet generation?
