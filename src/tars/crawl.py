"""Crawling functionality using Playwright."""

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Page
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def _ensure_browsers_installed() -> bool:
    """Check if Playwright browsers are installed, install if missing.

    Returns True if browsers are ready, False if installation failed.
    """
    try:
        # Quick check: try to get browser executable path
        from playwright._impl._driver import compute_driver_executable
        driver_executable, _ = compute_driver_executable()

        # Run playwright install check
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except Exception:
        return False


def _install_browsers_if_needed(error: Exception) -> bool:
    """Check if error is due to missing browsers and install them.

    Returns True if browsers were installed successfully.
    """
    error_msg = str(error).lower()

    # Check for common Playwright browser missing errors
    if "executable doesn't exist" in error_msg or "playwright install" in error_msg:
        console.print("  [yellow]Browser not installed. Installing chromium...[/yellow]")

        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            console.print("  [green]Browser installed successfully![/green]")
            return True
        else:
            console.print(f"  [red]Failed to install browser:[/red] {result.stderr}")
            return False

    return False


@dataclass
class CrawlResult:
    """Result of crawling a single page."""

    url: str
    title: str | None = None
    description: str | None = None
    content: str | None = None
    http_status: int | None = None
    error: str | None = None


async def extract_page_content_async(page: Page) -> tuple[str | None, str | None, str | None]:
    """Extract title, description, and main content from a page (async version)."""
    # Get title
    title = None
    try:
        title = await page.title()
        if not title:
            title_el = await page.query_selector("h1")
            if title_el:
                title = await title_el.inner_text()
    except Exception:
        pass

    # Get meta description
    description = None
    try:
        meta_desc = await page.query_selector('meta[name="description"]')
        if meta_desc:
            description = await meta_desc.get_attribute("content")
        if not description:
            meta_og = await page.query_selector('meta[property="og:description"]')
            if meta_og:
                description = await meta_og.get_attribute("content")
    except Exception:
        pass

    # Get main content - try various selectors
    content = None
    try:
        # Try common content selectors
        selectors = [
            "main",
            "article",
            '[role="main"]',
            ".content",
            ".post-content",
            ".article-content",
            "#content",
            ".markdown-body",
            ".prose",
        ]
        for selector in selectors:
            el = await page.query_selector(selector)
            if el:
                content = await el.inner_text()
                break

        # Fallback to body if no content found
        if not content:
            body = await page.query_selector("body")
            if body:
                content = await body.inner_text()

        # Truncate very long content (keep first 50k chars)
        if content and len(content) > 50000:
            content = content[:50000] + "..."
    except Exception:
        pass

    return title, description, content


async def crawl_page_async(url: str, _retry_after_install: bool = True) -> CrawlResult:
    """Crawl a single page and extract its content (async version). Falls back to HTTP if HTTPS fails."""
    result = CrawlResult(url=url)

    # Try HTTPS first, then HTTP as fallback
    urls_to_try = [url]
    if url.startswith("https://"):
        urls_to_try.append(url.replace("https://", "http://", 1))

    last_error = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (compatible; tars/0.1.0; +https://github.com/tars)"
            )
            page = await context.new_page()

            for try_url in urls_to_try:
                try:
                    # Navigate and get response
                    response = await page.goto(try_url, wait_until="domcontentloaded", timeout=30000)

                    if response:
                        result.http_status = response.status

                    # Wait for content to load
                    await page.wait_for_timeout(1000)

                    # Extract content
                    title, description, content = await extract_page_content_async(page)
                    result.title = title
                    result.description = description
                    result.content = content

                    # Success - break out of retry loop
                    last_error = None
                    break

                except Exception as e:
                    last_error = e
                    # Continue to try HTTP fallback
                    continue

            await browser.close()

    except Exception as e:
        last_error = e

        # Check if this is a browser missing error and try to install
        if _retry_after_install and _install_browsers_if_needed(e):
            # Retry crawl after installing browsers
            return await crawl_page_async(url, _retry_after_install=False)

    if last_error:
        result.error = str(last_error)

    return result


def crawl_page(url: str) -> CrawlResult:
    """Crawl a single page and extract its content. Falls back to HTTP if HTTPS fails.

    This is a sync wrapper around crawl_page_async for CLI compatibility.
    """
    return asyncio.run(crawl_page_async(url))


def normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    # Remove fragment, keep everything else
    normalized = parsed._replace(fragment="")
    path = normalized.path.rstrip("/") or "/"
    normalized = normalized._replace(path=path)
    return normalized.geturl()


def is_same_domain_and_prefix(base_url: str, candidate_url: str) -> bool:
    """Check if candidate URL is on same domain and starts with base path prefix."""
    base_parsed = urlparse(base_url)
    candidate_parsed = urlparse(candidate_url)

    # Must be same domain
    if base_parsed.netloc != candidate_parsed.netloc:
        return False

    # Must be same scheme (http/https)
    if base_parsed.scheme != candidate_parsed.scheme:
        return False

    # Candidate path must start with base path prefix
    base_path = base_parsed.path.rstrip("/")
    candidate_path = candidate_parsed.path.rstrip("/")

    # If base is root, allow all paths on same domain
    if not base_path or base_path == "/":
        return True

    # Otherwise, candidate must start with base path
    return candidate_path.startswith(base_path)


async def extract_links_async(page: Page, base_url: str) -> list[str]:
    """Extract all links from the page that match the base URL's domain/path prefix (async version)."""
    links = set()

    # Get all anchor elements with href
    anchors = await page.query_selector_all("a[href]")

    for anchor in anchors:
        href = await anchor.get_attribute("href")
        if not href:
            continue

        # Skip javascript:, mailto:, tel:, etc.
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        # Resolve relative URLs
        full_url = urljoin(base_url, href)

        # Normalize the URL
        full_url = normalize_url(full_url)

        # Check if it matches our domain/path prefix criteria
        if is_same_domain_and_prefix(base_url, full_url):
            links.add(full_url)

    return sorted(links)


async def crawl_page_for_links_async(url: str, max_pages: int, _retry_after_install: bool = True) -> list[str]:
    """
    Crawl a single page and extract internal links (async version).

    Args:
        url: The URL to crawl
        max_pages: Maximum number of discovered links to return

    Returns:
        List of discovered URLs (not including the original URL)
    """
    discovered_links = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (compatible; tars/0.1.0; +https://github.com/tars)"
            )
            page = await context.new_page()

            # Navigate to the page
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait a bit for any dynamic content
            await page.wait_for_timeout(1000)

            # Extract links
            all_links = await extract_links_async(page, url)

            # Filter out the original URL
            normalized_original = normalize_url(url)
            discovered_links = [
                link for link in all_links if link != normalized_original
            ]

            # Limit to max_pages
            discovered_links = discovered_links[:max_pages]

            await browser.close()

    except Exception as e:
        # Check if this is a browser missing error and try to install
        if _retry_after_install and _install_browsers_if_needed(e):
            # Retry crawl after installing browsers
            return await crawl_page_for_links_async(url, max_pages, _retry_after_install=False)

        console.print(f"[red]Crawl error:[/red] {e}")
        return []

    return discovered_links


def crawl_page_for_links(url: str, max_pages: int) -> list[str]:
    """
    Crawl a single page and extract internal links.

    This is a sync wrapper with progress display for CLI compatibility.

    Args:
        url: The URL to crawl
        max_pages: Maximum number of discovered links to return

    Returns:
        List of discovered URLs (not including the original URL)
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(f"Crawling {url}...", total=None)
        return asyncio.run(crawl_page_for_links_async(url, max_pages))
