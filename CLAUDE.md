# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**tars** is a personal search engine CLI that stores and searches links using PostgreSQL with BM25 full-text search. Links can be crawled to extract content for better search results.

## Commands

```bash
# Install globally as a uv tool
uv tool install -e .

# CLI commands (after global install)
tars add <url>           # Add a new link
tars list                # List all stored links
tars remove <id|url>     # Remove by index number or URL
tars update <url>        # Update timestamp for a link
tars clean-list          # Remove duplicate links
tars search <query>      # Search links using BM25 full-text search
tars crawl               # Crawl uncrawled links (default: --missing)
tars crawl <url>         # Crawl a specific URL
tars crawl --all         # Re-crawl all links
tars crawl --missing     # Only crawl links never crawled
tars crawl --old 7       # Crawl links not crawled in last N days

# Database commands
tars db init             # Initialize database schema
tars db migrate          # Import links from CSV to database
tars db status           # Show database connection status

# For development without global install
uv run tars <command>
```

## Architecture

CLI app with modules in `src/tars/`:
- `__init__.py` - CLI parsing and commands
- `db.py` - PostgreSQL database operations
- `crawl.py` - Web crawling with Playwright

Storage:
- Primary: PostgreSQL with pg_textsearch BM25 index
- Fallback: `links.csv` when DATABASE_URL not set

## Dependencies

- Python 3.12+
- `rich` for terminal output formatting
- `psycopg` for PostgreSQL database access
- `playwright` for web crawling (requires `playwright install chromium`)
- Uses `uv` for package management

## Git Commits

- Never add "Co-Authored-By" lines to commit messages
