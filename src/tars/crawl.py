"""Crawling functionality using Playwright."""

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@dataclass
class CrawlResult:
    """Result of crawling a single page."""

    url: str
    title: str | None = None
    description: str | None = None
    content: str | None = None
    http_status: int | None = None
    error: str | None = None


def extract_page_content(page) -> tuple[str | None, str | None, str | None]:
    """Extract title, description, and main content from a page."""
    # Get title
    title = None
    try:
        title = page.title()
        if not title:
            title_el = page.query_selector("h1")
            if title_el:
                title = title_el.inner_text()
    except Exception:
        pass

    # Get meta description
    description = None
    try:
        meta_desc = page.query_selector('meta[name="description"]')
        if meta_desc:
            description = meta_desc.get_attribute("content")
        if not description:
            meta_og = page.query_selector('meta[property="og:description"]')
            if meta_og:
                description = meta_og.get_attribute("content")
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
            el = page.query_selector(selector)
            if el:
                content = el.inner_text()
                break

        # Fallback to body if no content found
        if not content:
            body = page.query_selector("body")
            if body:
                content = body.inner_text()

        # Truncate very long content (keep first 50k chars)
        if content and len(content) > 50000:
            content = content[:50000] + "..."
    except Exception:
        pass

    return title, description, content


def crawl_page(url: str) -> CrawlResult:
    """Crawl a single page and extract its content. Falls back to HTTP if HTTPS fails."""
    result = CrawlResult(url=url)

    # Try HTTPS first, then HTTP as fallback
    urls_to_try = [url]
    if url.startswith("https://"):
        urls_to_try.append(url.replace("https://", "http://", 1))

    last_error = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (compatible; tars/0.1.0; +https://github.com/tars)"
            )
            page = context.new_page()

            for try_url in urls_to_try:
                try:
                    # Navigate and get response
                    response = page.goto(try_url, wait_until="domcontentloaded", timeout=30000)

                    if response:
                        result.http_status = response.status

                    # Wait for content to load
                    page.wait_for_timeout(1000)

                    # Extract content
                    title, description, content = extract_page_content(page)
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

            browser.close()

    except Exception as e:
        last_error = e

    if last_error:
        result.error = str(last_error)

    return result


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


def extract_links(page, base_url: str) -> list[str]:
    """Extract all links from the page that match the base URL's domain/path prefix."""
    links = set()

    # Get all anchor elements with href
    anchors = page.query_selector_all("a[href]")

    for anchor in anchors:
        href = anchor.get_attribute("href")
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


def crawl_page_for_links(url: str, max_pages: int) -> list[str]:
    """
    Crawl a single page and extract internal links.

    Args:
        url: The URL to crawl
        max_pages: Maximum number of discovered links to return

    Returns:
        List of discovered URLs (not including the original URL)
    """
    discovered_links = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Crawling {url}...", total=None)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (compatible; tars/0.1.0; +https://github.com/tars)"
                )
                page = context.new_page()

                # Navigate to the page
                progress.update(task, description=f"Loading {url}...")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Wait a bit for any dynamic content
                page.wait_for_timeout(1000)

                # Extract links
                progress.update(task, description="Extracting links...")
                all_links = extract_links(page, url)

                # Filter out the original URL
                normalized_original = normalize_url(url)
                discovered_links = [
                    link for link in all_links if link != normalized_original
                ]

                # Limit to max_pages
                discovered_links = discovered_links[:max_pages]

                browser.close()

        except Exception as e:
            console.print(f"[red]Crawl error:[/red] {e}")
            return []

    return discovered_links
