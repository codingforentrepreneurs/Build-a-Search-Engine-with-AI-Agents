import os
from pathlib import Path
from urllib.parse import urlparse


def validate_database_url(url: str) -> bool:
    """Validate DATABASE_URL format."""
    if not url.startswith(("postgresql://", "postgres://")):
        return False
    parsed = urlparse(url)
    return bool(parsed.hostname and parsed.path)


def test_connection(url: str) -> tuple[bool, str]:
    """Test database connection. Returns (success, message)."""
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=10):
            pass
        return (True, "OK")
    except Exception as e:
        return (False, str(e))


def create_env_file(database_url: str, bot_name: str = "tars") -> None:
    """Create .env file with database configuration."""
    env_path = Path(".env")
    content = f"DATABASE_URL={database_url}\nBOT_NAME={bot_name}\n"
    env_path.write_text(content)
