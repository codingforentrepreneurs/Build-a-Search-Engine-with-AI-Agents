"""Bot renaming utilities for setup wizard."""

from pathlib import Path

from rich.console import Console

console = Console()

# Files to update with new bot name
FILES_TO_RENAME = [
    "pyproject.toml",
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "src/tars/__init__.py",
    "src/tars/crawl.py",
    "src/tars/web/app.py",
    "src/tars/mcp/server.py",
    "src/tars/web/routes/help.py",
]


def rename_bot(new_name: str) -> dict:
    """Replace 'tars' with new_name in key files.

    Args:
        new_name: The new bot name to use

    Returns:
        Dictionary with 'files' (count of modified files) and 'replacements' stats
    """
    results = {"files": 0, "replacements": 0}

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
