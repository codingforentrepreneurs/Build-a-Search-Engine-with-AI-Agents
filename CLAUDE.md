# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**tars** is a minimal CLI application for managing a list of links. Links are stored in a local CSV file (`links.csv`) with timestamps for when they were added and last updated.

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

# For development without global install
uv run tars <command>
```

## Architecture

Single-module CLI app in `src/tars/__init__.py`:
- Uses `argparse` for CLI parsing with subcommands
- Stores data in `links.csv` (columns: link, added_at, updated_at)
- Uses `rich` library for formatted console output (tables, colored text)
- All timestamps are UTC ISO format

## Dependencies

- Python 3.12+
- `rich` for terminal output formatting
- Uses `uv` for package management

## Git Commits

- Never add "Co-Authored-By" lines to commit messages
