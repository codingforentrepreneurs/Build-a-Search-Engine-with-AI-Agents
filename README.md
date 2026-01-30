# tars

A personal search engine CLI that stores and searches links using PostgreSQL with BM25 full-text search. Links can be crawled to extract content for better search results.

## Installation

```bash
# Install globally as a uv tool
uv tool install -e .

# Install Playwright browser for crawling
playwright install chromium
```

## Commands

### Core Commands

```bash
tars add <url>           # Add a new link
tars list                # List all stored links
tars remove <id|url>     # Remove by index number or URL
tars update <url>        # Update timestamp for a link
tars text_search <query> # Search links using BM25 full-text search
tars clean-list          # Remove duplicate links
```

### Crawling

```bash
tars crawl               # Crawl uncrawled links (default: --missing)
tars crawl <url>         # Crawl a specific URL
tars crawl --all         # Re-crawl all links
tars crawl --missing     # Only crawl links never crawled
tars crawl --old 7       # Crawl links not crawled in last N days
```

### Database Management

```bash
tars db init             # Initialize database schema
tars db migrate          # Import links from CSV to database
tars db status           # Show database connection status
```

### Vector/Semantic Search

```bash
tars vector "<query>"    # Semantic search (shortcut)
tars db vector init      # Initialize vector column and HNSW index
tars db vector embed     # Generate embeddings (uses Tiger Cloud's OpenAI key)
tars db vector status    # Show embedding status
```

### Development

```bash
# Run without global install
uv run tars <command>
```

## Dependencies

- Python 3.12+
- PostgreSQL with pg_textsearch (BM25) and pgvector extensions
- Playwright for web crawling
