import socket
from pathlib import Path
from urllib.parse import urlparse


def validate_database_url(url: str) -> bool:
    """Validate DATABASE_URL format."""
    if not url.startswith(("postgresql://", "postgres://")):
        return False
    parsed = urlparse(url)
    return bool(parsed.hostname and parsed.path)


def test_dns(hostname: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Test if hostname can be resolved via DNS.

    Returns (success, message).
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(hostname)
        return (True, "OK")
    except socket.gaierror as e:
        return (False, f"DNS resolution failed: {e}")
    except socket.timeout:
        return (False, "DNS resolution timed out")
    except Exception as e:
        return (False, str(e))


def test_connection(url: str, timeout: int = 15) -> tuple[bool, str]:
    """Test database connection. Returns (success, message).

    First tests DNS resolution, then attempts database connection.
    """
    # Parse URL to get hostname
    parsed = urlparse(url)
    hostname = parsed.hostname

    if hostname:
        # Test DNS first for better error messages
        dns_ok, dns_msg = test_dns(hostname)
        if not dns_ok:
            return (False, f"Cannot resolve hostname '{hostname}' - DNS may still be propagating for new databases")

    # Try database connection
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=timeout):
            pass
        return (True, "OK")
    except Exception as e:
        error_str = str(e).lower()
        # Provide friendlier messages for common errors
        if "resolve" in error_str or "nodename" in error_str or "servname" in error_str:
            return (False, f"DNS not ready - new databases can take 1-2 minutes to become reachable")
        elif "timeout" in error_str or "timed out" in error_str:
            return (False, "Connection timed out - database may still be starting up")
        elif "authentication" in error_str or "password" in error_str:
            return (False, "Authentication failed - check username and password")
        elif "ssl" in error_str:
            return (False, f"SSL error - {e}")
        return (False, str(e))


def create_env_file(database_url: str, bot_name: str = "tars") -> None:
    """Create .env file with database configuration."""
    env_path = Path(".env")
    content = f"DATABASE_URL={database_url}\nBOT_NAME={bot_name}\n"
    env_path.write_text(content)
