"""Pydantic response models for TARS MCP server."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LinkSummary(BaseModel):
    """Summary of a link for list responses."""

    id: str
    url: str
    title: str | None = None
    description: str | None = None
    added_at: str | None = None


class LinkDetails(BaseModel):
    """Full link details including crawl info."""

    id: str
    url: str
    title: str | None = None
    description: str | None = None
    content: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    hidden: bool = False
    added_at: str | None = None
    updated_at: str | None = None
    crawled_at: str | None = None
    http_status: int | None = None
    crawl_error: str | None = None
    has_embedding: bool = False


class SearchResult(BaseModel):
    """Individual search result."""

    url: str
    title: str | None = None
    description: str | None = None
    added_at: str | None = None
    # BM25 keyword search score (higher = better match)
    score: float | None = None
    # Vector search distance (lower = better match)
    distance: float | None = None
    # Hybrid search RRF score (higher = better match)
    rrf_score: float | None = None
    # Rank positions in hybrid search
    vector_rank: int | None = None
    keyword_rank: int | None = None


class SearchResponse(BaseModel):
    """Response for search operations."""

    query: str
    results: list[SearchResult]
    total_count: int
    page: int
    per_page: int
    search_type: Literal["hybrid", "keyword", "vector"]


class LinksListResponse(BaseModel):
    """Response for list links operation."""

    links: list[LinkSummary]
    total_count: int
    page: int
    per_page: int
    pending_embeddings: int = 0


class CrawlResult(BaseModel):
    """Result of crawling a URL."""

    url: str
    success: bool
    title: str | None = None
    description: str | None = None
    http_status: int | None = None
    error: str | None = None
    content_changed: bool = False


class DatabaseStatus(BaseModel):
    """Database connection and statistics."""

    configured: bool
    connected: bool = False
    database_name: str | None = None
    total_links: int | None = None
    crawled_links: int | None = None
    embedded_links: int | None = None
    error: str | None = None
