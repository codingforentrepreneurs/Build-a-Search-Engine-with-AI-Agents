"""Bot renaming utilities for setup wizard."""

import re
from pathlib import Path

from rich.console import Console

console = Console()

# Files to update with new bot name (full replacement)
FILES_TO_RENAME = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "src/tars/crawl.py",
    "src/tars/web/app.py",
    "src/tars/mcp/server.py",
    "src/tars/web/routes/help.py",
]

# Files needing special handling
SPECIAL_FILES = [
    "pyproject.toml",
    "src/tars/__init__.py",
]


def _rename_pyproject(new_name: str) -> bool:
    """Handle pyproject.toml renaming carefully.

    Only renames:
    - name = "tars" -> name = "newname"
    - tars = "tars:main" -> newname = "tars:main" (command only, not module)

    Does NOT rename:
    - Module references like "tars:main" (must stay as tars)
    - Package paths like src/tars (directory stays the same)

    Returns True if file was modified.
    """
    path = Path("pyproject.toml")
    if not path.exists():
        return False

    content = path.read_text()
    original = content

    # Rename package name: name = "tars" -> name = "newname"
    content = re.sub(r'^name = "tars"', f'name = "{new_name}"', content, flags=re.MULTILINE)

    # Rename command in scripts: tars = "tars:main" -> newname = "tars:main"
    # Only the command name (left side), not the module reference (right side)
    content = re.sub(r'^tars = "tars:main"', f'{new_name} = "tars:main"', content, flags=re.MULTILINE)

    if content != original:
        path.write_text(content)
        console.print("  [dim]Updated:[/dim] pyproject.toml")
        return True
    return False


def _rename_init(new_name: str) -> bool:
    """Handle __init__.py renaming carefully.

    Only renames user-facing strings (help text, prog name), not imports.

    Returns True if file was modified.
    """
    path = Path("src/tars/__init__.py")
    if not path.exists():
        return False

    content = path.read_text()
    original = content

    # Rename prog name in argparse
    content = re.sub(r'prog="tars"', f'prog="{new_name}"', content)

    # Rename in help text and user-facing strings
    # Match 'tars' in strings but not in import statements or module paths
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

    # Rename in comments and docstrings mentioning the CLI
    content = re.sub(r'tars web interface', f'{new_name} web interface', content)
    content = re.sub(r'tars - Personal', f'{new_name} - Personal', content)

    if content != original:
        path.write_text(content)
        console.print("  [dim]Updated:[/dim] src/tars/__init__.py")
        return True
    return False


def rename_bot(new_name: str) -> dict:
    """Replace 'tars' with new_name in key files.

    Args:
        new_name: The new bot name to use

    Returns:
        Dictionary with 'files' (count of modified files) and 'replacements' stats
    """
    results = {"files": 0, "replacements": 0}

    # Handle special files first
    if _rename_pyproject(new_name):
        results["files"] += 1

    if _rename_init(new_name):
        results["files"] += 1

    # Handle regular files with full replacement
    for file_path in FILES_TO_RENAME:
        path = Path(file_path)
        if not path.exists():
            continue

        content = path.read_text()
        original = content

        # Replace lowercase 'tars' with new name
        new_content = content.replace("tars", new_name)
        # Replace uppercase 'TARS' with uppercase new name
        new_content = new_content.replace("TARS", new_name.upper())

        if content != new_content:
            path.write_text(new_content)
            results["files"] += 1
            # Count replacements (approximate)
            results["replacements"] += original.count("tars") + original.count("TARS")
            console.print(f"  [dim]Updated:[/dim] {file_path}")

    return results
