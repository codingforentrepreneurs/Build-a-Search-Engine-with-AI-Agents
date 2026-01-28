# tars Search Engine Specification

## Vision

Transform **tars** from a simple link manager into a personal search engine powered by PostgreSQL full-text search (pg_textsearch) on TigerData.com's cloud infrastructure.

## Current State

- CLI tool for managing links in a local CSV file
- Commands: `add`, `list`, `remove`, `update`, `clean-list`
- Data: URL + timestamps stored in `links.csv`

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
| Column       | Type         | Description                          |
|--------------|--------------|--------------------------------------|
| id           | UUID         | Primary key                          |
| url          | TEXT         | Unique URL                           |
| title        | TEXT         | Page title (crawled)                 |
| content      | TEXT         | Extracted page text (crawled)        |
| notes        | TEXT         | User-provided notes/description      |
| tags         | TEXT[]       | User-assigned tags for filtering     |
| added_at     | TIMESTAMPTZ  | When link was added                  |
| updated_at   | TIMESTAMPTZ  | Last metadata update                 |
| crawled_at   | TIMESTAMPTZ  | Last successful crawl (NULL if never)|
| search_vector| TSVECTOR     | pg_textsearch index (auto-generated) |

### search_vector composition
```sql
-- Weighted: title (A), tags (B), notes (C), content (D)
search_vector =
  setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
  setweight(to_tsvector('english', coalesce(array_to_string(tags, ' '), '')), 'B') ||
  setweight(to_tsvector('english', coalesce(notes, '')), 'C') ||
  setweight(to_tsvector('english', coalesce(content, '')), 'D')
```

## CLI Commands

### Existing (updated)
```bash
tars add <url> [--tags tag1,tag2] [--notes "..."]   # Add link (local + remote)
tars list [--tag <tag>] [--limit N]                 # List links
tars remove <id|url>                                # Remove link
tars update <url> [--tags ...] [--notes "..."]      # Update metadata
```

### New Commands
```bash
# Search
tars search <query>                    # Full-text search
tars search <query> --tag <tag>        # Search with tag filter
tars search "exact phrase"             # Phrase search (pg_textsearch native)

# Crawling
tars crawl <url>                       # Crawl specific URL
tars crawl --all                       # Crawl all links
tars crawl --stale [--days N]          # Crawl links not crawled in N days (default: 7)
tars crawl --pending                   # Crawl links never crawled

# Sync (local CSV <-> remote DB)
tars sync                              # Push local changes to remote, pull remote to local
tars sync --push                       # Push local CSV to remote only
tars sync --pull                       # Pull remote to local CSV only

# Database
tars db init                           # Initialize schema on TigerData
tars db migrate                        # Run pending migrations
tars db status                         # Show connection status and stats
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
