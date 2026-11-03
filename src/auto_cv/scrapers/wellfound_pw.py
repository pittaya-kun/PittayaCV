# -*- coding: utf-8 -*-
"""
Auto-CV - Wellfound Playwright Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Playwright scraper for Wellfound (wellfound.com) - startup jobs.
"""

import json
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


class WellfoundPlaywrightScraper(PlaywrightBaseScraper):
    """Playwright scraper for Wellfound."""

    SOURCE = JobSource.WELLFOUND
    BASE_URL = "https://wellfound.com"
    DEFAULT_RATE_LIMIT = 0.33
    MAX_PAGES = 5

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        from urllib.parse import urlencode
        params = {}
        if filters.query:
            params["search"] = filters.query
        if filters.location:
            params["location"] = filters.location
        if filters.work_mode and filters.work_mode == "remote":
            params["remote"] = "true"
        if filters.job_type:
            type_map = {"full-time": "full_time", "part-time": "part_time", "contract": "contract"}
            if filters.job_type in type_map:
                params["job_type"] = type_map[filters.job_type]
        if page > 1:
            params["page"] = str(page)
        return f"{self.BASE_URL}/jobs?{urlencode(params)}"

    def _get_job_card_selector(self) -> str:
        return "div.mb-2.flex.flex-col.justify-between.border-b.border-gray-400.py-3"

    async def wait_for_jobs(self, page: Page) -> None:
        try:
            await page.wait_for_selector("div[data-test='JobCard'], div.JobCard, .no-results", timeout=15000)
        except Exception:
            pass

    async def parse_job_card(self, page: Page, element: ElementHandle) -> Optional[ScrapedJob]:
        try:
            # Title link
            title_link = await element.query_selector("a[class*='font-bold'][class*='text-black']")
            title = await title_link.inner_text() if title_link else ""
            title = title.strip()

            # Get href for job ID
            href = await title_link.get_attribute("href") if title_link else ""
            job_id = ""
            if href:
                job_id = href.split("/")[-1].split("?")[0]

            if not job_id:
                return None

            url = f"{self.BASE_URL}{href}" if href.startswith("/") else href

            # Company and metadata
            meta_div = await element.query_selector("div.text-sm")
            company = ""
            location = "Remote"
            salary_min = None
            salary_max = None
            work_mode = "remote"
            job_type = None

            if meta_div:
                spans = await meta_div.query_selector_all("span")
                for span in spans:
                    text = (await span.inner_text()).strip()
                    # Clean trailing bullets
                    text = text.rstrip("• ").strip()
                    if text and not company:
                        company = text
                    elif text:
                        # Parse: "Remote only • Everywhere • $40k – $60k • today"
                        parts = [p.strip() for p in text.split("•")]
                        for part in parts:
                            part_lower = part.lower()
                            if "remote" in part_lower:
                                work_mode = "remote"
                                location = part
                            elif "hybrid" in part_lower:
                                work_mode = "hybrid"
                                location = part
                            elif "in office" in part_lower or "onsite" in part_lower:
                                work_mode = "onsite"
                                location = part
                            elif "$" in part and ("k" in part.lower() or "-" in part):
                                salary_min, salary_max = self._parse_salary(part)

            if not title or not company:
                return None

            return ScrapedJob(
                source=self.SOURCE,
                external_id=str(job_id),
                url=url,
                title=title,
                company=company,
                location=location,
                work_mode=work_mode,
                job_type=job_type,
                description=None,
                salary_min=salary_min,
                salary_max=salary_max,
                posted_date=None,
                raw_data={},
            )
        except Exception:
            return None

    def _parse_salary(self, text: str) -> tuple:
        patterns = [
            r"[\$€£]\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s*[kK]?\s*[-–]\s*[\$€£]?\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s*[kK]?",
            r"(\d+(?:,\d{3})*)\s*[-–]\s*(\d+(?:,\d{3})*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    min_val = float(match.group(1).replace(",", ""))
                    max_val = float(match.group(2).replace(",", ""))
                    if "k" in match.group(0).lower():
                        min_val *= 1000
                        max_val *= 1000
                    return int(min_val), int(max_val)
                except ValueError:
                    continue
        return None, None

    async def _scrape_job_detail(self, url: str) -> Optional[ScrapedJob]:
        try:
            page = await self.browser_manager.new_page()
            await self.rate_limiter.acquire()
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)

            # Try JSON-LD
            script = await page.query_selector('script[type="application/ld+json"]')
            if script:
                content = await script.inner_text()
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        data = data[0]
                    if data.get("@type") == "JobPosting":
                        return self._parse_json_ld(data, url)
                except (json.JSONDecodeError, KeyError):
                    pass

            desc_elem = await page.query_selector("[data-test='JobDescription'], .job-description, [itemprop='description']")
            description = await desc_elem.inner_text() if desc_elem else None
            description_html = await desc_elem.inner_html() if desc_elem else None

            salary_min = None
            salary_max = None
            salary_elem = await page.query_selector("[data-test='Salary'], .salary-range")
            if salary_elem:
                salary_text = await salary_elem.inner_text()
                salary_min, salary_max = self._parse_salary(salary_text)

            job_id = url.split("/")[-1].split("?")[0]
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

    def _parse_json_ld(self, data: dict, url: str) -> ScrapedJob:
        job_id = url.split("/")[-1].split("?")[0]
        salary_min = None
        salary_max = None
        if "baseSalary" in data:
            salary = data["baseSalary"]
            if isinstance(salary, dict) and "value" in salary:
                val = salary["value"]
                if isinstance(val, dict):
                    salary_min = val.get("minValue")
                    salary_max = val.get("maxValue")
        return ScrapedJob(
            source=self.SOURCE,
            external_id=job_id,
            url=url,
            title=data.get("title", ""),
            company=data.get("hiringOrganization", {}).get("name", ""),
            location=data.get("jobLocation", {}).get("address", {}).get("addressLocality", ""),
            work_mode=data.get("jobLocationType", "").lower(),
            job_type=data.get("employmentType", "").replace("_", "-"),
            description=data.get("description", ""),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=data.get("baseSalary", {}).get("currency", "USD"),
            posted_date=data.get("datePosted", "").split("T")[0] if data.get("datePosted") else None,
        )


def scrape_wellfound_sync(
    filters: Optional[SearchFilters] = None,
    headless: bool = True,
) -> "ScrapeResult":
    scraper = WellfoundPlaywrightScraper(headless=headless)
    return run_scraper_sync(scraper, filters)


# Register Playwright scraper (overrides static version)
from auto_cv.scrapers.base import register_scraper
register_scraper(JobSource.WELLFOUND, WellfoundPlaywrightScraper)


__all__ = ["WellfoundPlaywrightScraper", "scrape_wellfound_sync"]