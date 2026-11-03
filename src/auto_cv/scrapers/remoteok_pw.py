# -*- coding: utf-8 -*-
"""
Auto-CV - RemoteOK Playwright Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Playwright scraper for RemoteOK (remoteok.com) - global remote jobs.
"""

import re
from typing import Optional, List

from playwright.async_api import Page, ElementHandle

from auto_cv.scrapers.playwright_base import (
    PlaywrightBaseScraper,
    SearchFilters,
    ScrapedJob,
    run_scraper_sync,
)
from auto_cv.storage.models import JobSource


class RemoteOKPlaywrightScraper(PlaywrightBaseScraper):
    """
    Playwright scraper for RemoteOK.

    RemoteOK loads jobs via JavaScript after initial page load.
    """

    SOURCE = JobSource.REMOTEOK
    BASE_URL = "https://remoteok.com"
    DEFAULT_RATE_LIMIT = 0.5
    MAX_PAGES = 5

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build RemoteOK search URL."""
        query_parts = []
        if filters.query:
            query_parts.append(filters.query.lower().replace(" ", "-"))

        if filters.work_mode:
            query_parts.append(filters.work_mode)
        if filters.job_type:
            query_parts.append(filters.job_type)

        query_str = "-".join(query_parts) if query_parts else "dev"
        url = f"{self.BASE_URL}/remote-{query_str}-jobs"

        if page > 1:
            url += f"?page={page}"

        return url

    def _get_job_card_selector(self) -> str:
        return "tr.job:not(.placeholder)"

    async def wait_for_jobs(self, page: Page) -> None:
        """Wait for job cards to load (not placeholders)."""
        # Wait for either real job cards or empty state
        try:
            await page.wait_for_selector("tr.job:not(.placeholder), .no-jobs", timeout=15000)
        except Exception:
            # Timeout - page might have loaded differently
            pass

    async def parse_job_card(self, page: Page, element: ElementHandle) -> Optional[ScrapedJob]:
        """Parse a RemoteOK job card (tr.job)."""
        try:
            # Get job ID from data attribute
            job_id = await element.get_attribute("data-id")
            if not job_id:
                job_id = await element.get_attribute("id")
                if job_id:
                    job_id = job_id.replace("job-", "")

            if not job_id:
                return None

            url = f"{self.BASE_URL}/remote-jobs/{job_id}"

            # Title
            title_elem = await element.query_selector("h2[itemprop='title']")
            title = await title_elem.inner_text() if title_elem else ""
            title = title.strip()

            # Company
            company_elem = await element.query_selector("h3[itemprop='name']")
            company = await company_elem.inner_text() if company_elem else ""
            company = company.strip()

            if not title or not company:
                return None

            # Location
            location_elem = await element.query_selector(".location")
            location = await location_elem.inner_text() if location_elem else "Remote"
            location = location.strip()

            # Tags
            tags = []
            tag_elements = await element.query_selector_all(".tag")
            for tag_elem in tag_elements:
                tag_text = await tag_elem.inner_text()
                tags.append(tag_text.strip())

            # Work mode & job type from tags
            work_mode = "remote"
            job_type = None
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower in ["full-time", "full time"]:
                    job_type = "full-time"
                elif tag_lower in ["contract", "contractor"]:
                    job_type = "contract"
                elif tag_lower in ["part-time", "part time"]:
                    job_type = "part-time"

            # Salary (rare in tags)
            salary_min = None
            salary_max = None

            # Description preview
            desc_elem = await element.query_selector("[itemprop='description']")
            description = await desc_elem.inner_text() if desc_elem else None
            if description:
                description = description.strip()

            # Posted date
            date_elem = await element.query_selector("time")
            posted_date = await date_elem.get_attribute("datetime") if date_elem else None

            return ScrapedJob(
                source=self.SOURCE,
                external_id=str(job_id),
                url=url,
                title=title,
                company=company,
                location=location,
                work_mode=work_mode,
                job_type=job_type,
                description=description,
                salary_min=salary_min,
                salary_max=salary_max,
                posted_date=posted_date,
                raw_data={"tags": tags},
            )

        except Exception:
            return None

    async def _scrape_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Scrape job detail page for full description."""
        try:
            page = await self.browser_manager.new_page()
            await self.rate_limiter.acquire()
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)

            # Description
            desc_elem = await page.query_selector(".description, #job_description, .markdown")
            description = await desc_elem.inner_text() if desc_elem else None
            description_html = await desc_elem.inner_html() if desc_elem else None

            # Salary from detail page
            salary_min = None
            salary_max = None
            page_text = await page.inner_text("body")
            salary_match = re.search(
                r"[\$€£]\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*[-–]\s*[\$€£]?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
                page_text,
            )
            if salary_match:
                salary_min = int(salary_match.group(1).replace(",", ""))
                salary_max = int(salary_match.group(2).replace(",", ""))

            job_id = url.split("/")[-1]

            await page.close()

            return ScrapedJob(
                source=self.SOURCE,
                external_id=job_id,
                url=url,
                title="",
                company="",
                description=description,
                description_html=description_html,
                salary_min=salary_min,
                salary_max=salary_max,
            )

        except Exception:
            return None


# Register Playwright scraper (overrides static version)
from auto_cv.scrapers.base import register_scraper
register_scraper(JobSource.REMOTEOK, RemoteOKPlaywrightScraper)


# Sync wrapper for CLI
def scrape_remoteok_sync(
    filters: Optional[SearchFilters] = None,
    headless: bool = True,
) -> "ScrapeResult":
    """Synchronous wrapper for CLI integration."""
    scraper = RemoteOKPlaywrightScraper(headless=headless)
    return run_scraper_sync(scraper, filters)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["RemoteOKPlaywrightScraper", "scrape_remoteok_sync"]