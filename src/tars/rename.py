"""Bot renaming utilities for setup wizard.

This module creates CLI command ALIASES for tars, not full renames.
The internal code stays as "tars" - only user-facing command names change.

What gets renamed:
- CLI command name in pyproject.toml (tars -> mybot)
- User-facing help text showing command examples
- Web help page command examples

What stays as "tars":
- Python module name (src/tars/)
- Import statements
- Logger names, user agents, MCP server name
- Documentation files (README, CLAUDE.md, AGENTS.md)
"""

import re
from pathlib import Path

from rich.console import Console

console = Console()


def _rename_pyproject(new_name: str) -> bool:
    """Add CLI command alias to pyproject.toml.

    Adds a new command alias while keeping tars:
    - tars = "tars:main"       (original, kept)
    - newname = "tars:main"    (alias, added)

    Both commands will work globally after `uv tool install`.

    Returns True if file was modified.
    """
    path = Path("pyproject.toml")
    if not path.exists():
        return False

    content = path.read_text()
    original = content

    # Check if alias already exists
    alias_pattern = f'^{re.escape(new_name)} = "tars:main"'
    if re.search(alias_pattern, content, flags=re.MULTILINE):
        # Alias already exists, no change needed
        return False

    # Add alias on a new line after tars = "tars:main"
    # This keeps both commands working
    content = re.sub(
        r'^(tars = "tars:main")$',
        f'\\1\n{new_name} = "tars:main"',
        content,
        flags=re.MULTILINE,
    )

    if content != original:
        path.write_text(content)
        console.print(f"  [dim]Updated:[/dim] pyproject.toml (added '{new_name}' alias)")
        return True
    return False


def _rename_init(new_name: str) -> bool:
    """Update user-facing help text in __init__.py.

    Only renames:
    - argparse prog name (shown in --help)
    - Command examples in help text

    Does NOT rename:
    - Import statements
    - Internal function names
    - Docstrings describing the module

    Returns True if file was modified.
    """
    path = Path("src/tars/__init__.py")
    if not path.exists():
        return False

    content = path.read_text()
    original = content

    # Rename prog name in argparse (shown in --help output)
    content = re.sub(r'prog="tars"', f'prog="{new_name}"', content)

    # Rename command examples in help text strings
    content = re.sub(r'\[bold cyan\]tars\[/bold cyan\]', f'[bold cyan]{new_name}[/bold cyan]', content)
    content = re.sub(r'"tars add', f'"{new_name} add', content)
    content = re.sub(r'"tars list', f'"{new_name} list', content)
    content = re.sub(r'"tars remove', f'"{new_name} remove', content)
    content = re.sub(r'"tars search', f'"{new_name} search', content)
    content = re.sub(r'"tars crawl', f'"{new_name} crawl', content)
    content = re.sub(r'"tars db', f'"{new_name} db', content)
    content = re.sub(r'"tars vector', f'"{new_name} vector', content)
    content = re.sub(r'"tars web', f'"{new_name} web', content)
    content = re.sub(r'"tars mcp', f'"{new_name} mcp', content)
    content = re.sub(r'\$ tars ', f'$ {new_name} ', content)

    if content != original:
        path.write_text(content)
        console.print("  [dim]Updated:[/dim] src/tars/__init__.py (help text)")
        return True
    return False


def _rename_web_help(new_name: str) -> bool:
    """Update command examples in web help page.

    Returns True if file was modified.
    """
    path = Path("src/tars/web/routes/help.py")
    if not path.exists():
        return False

    content = path.read_text()
    original = content

    # Only rename command examples in the help page, e.g., "tars add" -> "mybot add"
    content = re.sub(r'"tars ', f'"{new_name} ', content)

    if content != original:
        path.write_text(content)
        console.print("  [dim]Updated:[/dim] src/tars/web/routes/help.py (command examples)")
        return True
    return False


def rename_bot(new_name: str) -> dict:
    """Create a CLI command alias for tars.

    This is a lightweight rename that only changes user-facing command names.
    The internal codebase stays as "tars" for code integrity.

    Args:
        new_name: The CLI command name to use (e.g., "cooper", "mybot")

    Returns:
        Dictionary with 'files' (count of modified files)
    """
    results = {"files": 0}

    # Update CLI command in pyproject.toml
    if _rename_pyproject(new_name):
        results["files"] += 1

    # Update help text in main CLI
    if _rename_init(new_name):
        results["files"] += 1

    # Update web help page command examples
    if _rename_web_help(new_name):
        results["files"] += 1

    return results
