# -*- coding: utf-8 -*-
"""
Auto-CV - Playwright Scraper Base Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Playwright-based scraper for JavaScript-heavy job boards.
"""

import asyncio
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from auto_cv.config import get_settings
from auto_cv.storage.models import Job, JobSource, create_job


# ============================================================
# DATA TYPES
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
    work_mode: Optional[str] = None
    job_type: Optional[str] = None
    salary_min: Optional[int] = None
    date_posted: Optional[str] = None
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
# PLAYWRIGHT RATE LIMITER
# ============================================================

class AsyncRateLimiter:
    """Async token bucket rate limiter."""

    def __init__(self, requests_per_second: float = 0.5, burst: int = 3):
        self.rate = requests_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)


# ============================================================
# PLAYWRIGHT BROWSER MANAGER
# ============================================================

class BrowserManager:
    """Manages Playwright browser lifecycle."""

    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 100,
        user_agent: Optional[str] = None,
    ):
        self.headless = headless
        self.slow_mo = slow_mo
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def start(self) -> None:
        """Start Playwright and browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        # Stealth: remove webdriver flag
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

    async def new_page(self) -> Page:
        """Create a new page."""
        if not self._context:
            await self.start()
        page = await self._context.new_page()
        return page

    async def close(self) -> None:
        """Close browser and playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# ============================================================
# BASE PLAYWRIGHT SCRAPER
# ============================================================

class PlaywrightBaseScraper(ABC):
    """
    Abstract base scraper using Playwright for JS-heavy sites.

    Subclasses must implement:
    - build_search_url(filters, page) -> str
    - parse_job_card(page, element) -> ScrapedJob
    - wait_for_jobs(page) -> None (wait for job cards to load)
    """

    SOURCE: JobSource = JobSource.OTHER
    BASE_URL: str = ""
    DEFAULT_RATE_LIMIT: float = 0.5
    MAX_PAGES: int = 5

    def __init__(
        self,
        rate_limit: Optional[float] = None,
        max_pages: Optional[int] = None,
        headless: bool = True,
        slow_mo: int = 100,
        cookies: Optional[List[Dict]] = None,
        settings=None,
    ):
        self.settings = settings or get_settings()
        self.max_pages = max_pages or self.MAX_PAGES
        self.rate_limiter = AsyncRateLimiter(rate_limit or self.DEFAULT_RATE_LIMIT)
        self.browser_manager = BrowserManager(headless=headless, slow_mo=slow_mo)
        self.cookies = cookies or []
        self._seen_urls: Set[str] = set()

    @abstractmethod
    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        pass

    @abstractmethod
    async def parse_job_card(self, page: Page, element) -> Optional[ScrapedJob]:
        pass

    @abstractmethod
    async def wait_for_jobs(self, page: Page) -> None:
        """Wait for job cards to appear on page."""
        pass

    async def search(self, filters: Optional[SearchFilters] = None) -> ScrapeResult:
        """Execute search with pagination using Playwright."""
        filters = filters or SearchFilters()
        start_time = time.time()
        all_jobs: List[ScrapedJob] = []
        errors: List[str] = []
        pages_scraped = 0

        await self.browser_manager.start()

        try:
            for page_num in range(1, self.max_pages + 1):
                url = self.build_search_url(filters, page_num)

                try:
                    page = await self.browser_manager.new_page()

                    # Set cookies if provided
                    if self.cookies:
                        await page.context.add_cookies(self.cookies)

                    # Navigate with rate limiting
                    await self.rate_limiter.acquire()
                    # Use domcontentloaded for faster initial load, then wait for jobs
                    await page.goto(url, wait_until="domcontentloaded", timeout=90000)

                    # Wait for jobs to load
                    await self.wait_for_jobs(page)

                    # Extract jobs
                    jobs = await self._extract_jobs_from_page(page)
                    if not jobs:
                        await page.close()
                        break

                    all_jobs.extend(jobs)
                    pages_scraped += 1

                    # Check for next page
                    if not await self._has_next_page(page, page_num):
                        await page.close()
                        break

                    await page.close()

                    # Polite delay
                    await asyncio.sleep(random.uniform(1, 3))

                except Exception as e:
                    errors.append(f"Page {page_num}: {str(e)}")
                    break

        finally:
            await self.browser_manager.close()

        duration = time.time() - start_time
        return ScrapeResult(
            jobs=all_jobs,
            total_found=len(all_jobs),
            pages_scraped=pages_scraped,
            errors=errors,
            duration_seconds=duration,
        )

    async def _extract_jobs_from_page(self, page: Page) -> List[ScrapedJob]:
        """Extract job cards from page."""
        jobs = []

        # Find all job card elements
        elements = await page.query_selector_all(self._get_job_card_selector())
        if not elements:
            return []

        for element in elements:
            try:
                job = await self.parse_job_card(page, element)
                if job and job.url not in self._seen_urls:
                    self._seen_urls.add(job.url)
                    jobs.append(job)
            except Exception:
                continue

        return jobs

    @abstractmethod
    def _get_job_card_selector(self) -> str:
        """Return CSS selector for job cards."""
        pass

    async def _has_next_page(self, page: Page, current_page: int) -> bool:
        """Check if there's a next page."""
        return False

    async def scrape_job_details(self, jobs: List[ScrapedJob]) -> List[ScrapedJob]:
        """Enrich jobs with detail page data."""
        enriched = []

        for job in jobs:
            try:
                if job.description is None or len(job.description) < 200:
                    detail = await self._scrape_job_detail(job.url)
                    if detail and detail.description:
                        job.description = detail.description
                        job.description_html = detail.description_html
            except Exception:
                pass
            enriched.append(job)
            await asyncio.sleep(random.uniform(0.5, 1.5))

        return enriched

    async def _scrape_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Scrape job detail page."""
        return None


# ============================================================
# SYNC WRAPPER FOR CLI INTEGRATION
# ============================================================

def run_scraper_sync(scraper: PlaywrightBaseScraper, filters: Optional[SearchFilters] = None) -> ScrapeResult:
    """Run async scraper synchronously."""
    return asyncio.run(scraper.search(filters))


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "ScrapedJob",
    "SearchFilters",
    "ScrapeResult",
    "AsyncRateLimiter",
    "BrowserManager",
    "PlaywrightBaseScraper",
    "run_scraper_sync",
]