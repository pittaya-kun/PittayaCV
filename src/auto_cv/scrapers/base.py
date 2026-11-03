# -*- coding: utf-8 -*-
"""
Auto-CV - Base Scraper Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Abstract base class for job scrapers with rate limiting, retry, and session management.
"""

import asyncio
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from auto_cv.config import get_settings
from auto_cv.storage.models import Job, JobSource, create_job


# ============================================================
# DATA TYPES (SRP - structured return types)
# ============================================================

@dataclass
class ScrapedJob:
    """Normalized job data from scraper."""
    source: JobSource
    external_id: str
    url: str
    title: str
    company: str
    location: Optional[str] = None
    work_mode: Optional[str] = None
    job_type: Optional[str] = None
    description: Optional[str] = None
    description_html: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "BRL"
    salary_period: str = "monthly"
    posted_date: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    def to_job(self) -> Job:
        """Convert to SQLAlchemy Job model."""
        return create_job(
            source=self.source.value,
            external_id=self.external_id,
            url=self.url,
            title=self.title,
            company=self.company,
            location=self.location,
            work_mode=self.work_mode,
            job_type=self.job_type,
            description=self.description,
            description_html=self.description_html,
            salary_min=self.salary_min,
            salary_max=self.salary_max,
            salary_currency=self.salary_currency,
            salary_period=self.salary_period,
            posted_date=self.posted_date,
            raw_data=self.raw_data,
        )


@dataclass
class SearchFilters:
    """Search filters for job boards."""
    query: Optional[str] = None
    location: Optional[str] = None
    work_mode: Optional[str] = None  # remote, hybrid, onsite
    job_type: Optional[str] = None   # full-time, contract, part-time
    salary_min: Optional[int] = None
    date_posted: Optional[str] = None  # last_24h, last_week, last_month
    radius_km: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScrapeResult:
    """Result of a scrape operation."""
    jobs: List[ScrapedJob]
    total_found: int
    pages_scraped: int
    errors: List[str]
    duration_seconds: float


# ============================================================
# RATE LIMITER (SRP - only rate limiting)
# ============================================================

import threading


class SyncRateLimiter:
    """Token bucket rate limiter (thread-safe for sync code)."""

    def __init__(self, requests_per_second: float = 0.5, burst: int = 3):
        """
        Args:
            requests_per_second: Sustained rate (e.g., 0.5 = 1 req per 2s)
            burst: Max burst allowance
        """
        self.rate = requests_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Synchronous version (for non-async scrapers)."""
        with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

                wait_time = (1 - self.tokens) / self.rate
                time.sleep(wait_time)

    # Alias for ScraperSession compatibility
    acquire_sync = acquire


class RateLimiter:
    """Token bucket rate limiter (thread-safe for async)."""

    def __init__(self, requests_per_second: float = 0.5, burst: int = 3):
        """
        Args:
            requests_per_second: Sustained rate (e.g., 0.5 = 1 req per 2s)
            burst: Max burst allowance
        """
        self.rate = requests_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

                # Wait for next token
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)

    def acquire_sync(self) -> None:
        """Synchronous version (for non-async scrapers)."""
        # Use sync logic without lock (less precise but works)
        while True:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return

            wait_time = (1 - self.tokens) / self.rate
            time.sleep(wait_time)


# ============================================================
# HTTP SESSION (SRP - only HTTP concerns)
# ============================================================

class ScraperSession:
    """Managed HTTP session with headers, cookies, and retry logic."""

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",  # No brotli (br) - stdlib doesn't support
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    def __init__(
        self,
        base_url: str,
        rate_limiter: Optional[RateLimiter] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ):
        self.base_url = base_url
        self.rate_limiter = rate_limiter or RateLimiter()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        if extra_headers:
            self.session.headers.update(extra_headers)
        if cookies:
            self.session.cookies.update(cookies)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        reraise=True,
    )
    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with rate limiting and retry."""
        self.rate_limiter.acquire_sync()
        full_url = urljoin(self.base_url, url) if not urlparse(url).netloc else url
        response = self.session.get(full_url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        reraise=True,
    )
    def post(self, url: str, **kwargs) -> requests.Response:
        """POST with rate limiting and retry."""
        self.rate_limiter.acquire_sync()
        full_url = urljoin(self.base_url, url) if not urlparse(url).netloc else url
        response = self.session.post(full_url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    def get_soup(self, url: str, **kwargs) -> BeautifulSoup:
        """GET and parse as BeautifulSoup."""
        response = self.get(url, **kwargs)
        return BeautifulSoup(response.text, "html.parser")

    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """Update session cookies."""
        self.session.cookies.update(cookies)

    def close(self) -> None:
        """Close session."""
        self.session.close()

    def __enter__(self) -> "ScraperSession":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ============================================================
# BASE SCRAPER (Abstract - OCP: extend for new sources)
# ============================================================

class BaseScraper(ABC):
    """
    Abstract base scraper for job boards.

    Subclasses must implement:
    - search(filters) -> ScrapeResult
    - parse_job_card(element) -> ScrapedJob
    - parse_job_detail(url) -> ScrapedJob (optional, for detail pages)

    Provides:
    - Rate limiting
    - Retry logic
    - Session management
    - Pagination handling
    - Deduplication
    """

    # Override in subclasses
    SOURCE: JobSource = JobSource.OTHER
    BASE_URL: str = ""
    DEFAULT_RATE_LIMIT: float = 0.5  # req/sec
    MAX_PAGES: int = 10
    JOB_CARD_SELECTOR: str = ""  # CSS selector for job cards
    PAGINATION_SELECTOR: str = ""  # CSS selector for next page

    def __init__(
        self,
        rate_limit: Optional[float] = None,
        max_pages: Optional[int] = None,
        cookies: Optional[Dict[str, str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        settings=None,
    ):
        self.settings = settings or get_settings()
        self.max_pages = max_pages or self.MAX_PAGES
        self.rate_limiter = SyncRateLimiter(rate_limit or self.DEFAULT_RATE_LIMIT)
        self.session = ScraperSession(
            base_url=self.BASE_URL,
            rate_limiter=self.rate_limiter,
            extra_headers=extra_headers,
            cookies=cookies,
        )
        self._seen_urls: Set[str] = set()

    @abstractmethod
    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build search URL for given filters and page."""
        pass

    @abstractmethod
    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a single job card element."""
        pass

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse job detail page (optional, override if needed)."""
        return None

    def search(self, filters: Optional[SearchFilters] = None) -> ScrapeResult:
        """
        Execute search with pagination.

        Args:
            filters: Search filters (None = no filters)

        Returns:
            ScrapeResult with jobs, stats, errors
        """
        filters = filters or SearchFilters()
        start_time = time.time()
        all_jobs: List[ScrapedJob] = []
        errors: List[str] = []
        pages_scraped = 0

        try:
            for page in range(1, self.max_pages + 1):
                url = self.build_search_url(filters, page)
                try:
                    soup = self.session.get_soup(url)
                    jobs = self._extract_jobs_from_page(soup)
                    if not jobs:
                        break  # No more jobs

                    all_jobs.extend(jobs)
                    pages_scraped += 1

                    # Check for next page
                    if not self._has_next_page(soup, page):
                        break

                    # Polite delay between pages
                    time.sleep(random.uniform(1, 3))

                except Exception as e:
                    errors.append(f"Page {page}: {str(e)}")
                    break

        finally:
            self.session.close()

        duration = time.time() - start_time
        return ScrapeResult(
            jobs=all_jobs,
            total_found=len(all_jobs),
            pages_scraped=pages_scraped,
            errors=errors,
            duration_seconds=duration,
        )

    def _extract_jobs_from_page(self, soup: BeautifulSoup) -> List[ScrapedJob]:
        """Extract job cards from page."""
        jobs = []
        cards = soup.select(self.JOB_CARD_SELECTOR) if self.JOB_CARD_SELECTOR else []

        for card in cards:
            try:
                job = self.parse_job_card(card)
                if job and job.url not in self._seen_urls:
                    self._seen_urls.add(job.url)
                    jobs.append(job)
            except Exception:
                continue  # Skip bad cards

        return jobs

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        """Check if there's a next page."""
        if not self.PAGINATION_SELECTOR:
            return False
        next_link = soup.select_one(self.PAGINATION_SELECTOR)
        return next_link is not None

    def scrape_job_details(self, jobs: List[ScrapedJob]) -> List[ScrapedJob]:
        """Enrich jobs with detail page data (optional)."""
        enriched = []
        for job in jobs:
            try:
                if job.description is None or len(job.description) < 200:
                    detail = self.parse_job_detail(job.url)
                    if detail and detail.description:
                        job.description = detail.description
                        job.description_html = detail.description_html
            except Exception:
                pass
            enriched.append(job)
            time.sleep(random.uniform(0.5, 1.5))
        return enriched


# ============================================================
# SCRAPER REGISTRY (OCP - register new scrapers here)
# ============================================================

_SCRAPER_REGISTRY: Dict[JobSource, type] = {}


def register_scraper(source: JobSource, scraper_class: type) -> None:
    """Register a scraper class for a source."""
    _SCRAPER_REGISTRY[source] = scraper_class


def get_scraper(source: JobSource, **kwargs) -> BaseScraper:
    """Get scraper instance for source."""
    scraper_class = _SCRAPER_REGISTRY.get(source)
    if not scraper_class:
        raise ValueError(f"No scraper registered for {source.value}")
    return scraper_class(**kwargs)


def list_scrapers() -> List[JobSource]:
    """List registered sources."""
    return list(_SCRAPER_REGISTRY.keys())


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Types
    "ScrapedJob",
    "SearchFilters",
    "ScrapeResult",
    # Rate limiting
    "RateLimiter",
    "SyncRateLimiter",
    # Session
    "ScraperSession",
    # Base
    "BaseScraper",
    # Registry
    "register_scraper",
    "get_scraper",
    "list_scrapers",
]