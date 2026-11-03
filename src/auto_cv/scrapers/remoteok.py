# -*- coding: utf-8 -*-
"""
Auto-CV - RemoteOK Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for RemoteOK (remoteok.com) - global remote jobs.
"""

import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from auto_cv.scrapers.base import (
    BaseScraper,
    SearchFilters,
    ScrapedJob,
    register_scraper,
)
from auto_cv.storage.models import JobSource


class RemoteOKScraper(BaseScraper):
    """
    Scraper for RemoteOK.

    Features:
    - Static HTML (no JS required)
    - Global remote jobs
    - Simple pagination
    - Clean job cards with data attributes
    """

    SOURCE = JobSource.REMOTEOK
    BASE_URL = "https://remoteok.com"
    DEFAULT_RATE_LIMIT = 0.5  # 1 req per 2s
    MAX_PAGES = 5
    JOB_CARD_SELECTOR = "tr.job"
    PAGINATION_SELECTOR = "a.next_page"

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build RemoteOK search URL."""
        # RemoteOK uses /remote-{query}-jobs format
        query_parts = []
        if filters.query:
            query_parts.append(filters.query.lower().replace(" ", "-"))

        # Add tags/filters
        if filters.work_mode:
            query_parts.append(filters.work_mode)
        if filters.job_type:
            query_parts.append(filters.job_type)

        query_str = "-".join(query_parts) if query_parts else "dev"
        url = f"{self.BASE_URL}/remote-{query_str}-jobs"

        if page > 1:
            url += f"?page={page}"

        return url

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a RemoteOK job card (tr.job)."""
        try:
            # Data attributes on the row
            job_id = element.get("data-id") or element.get("id", "").replace("job-", "")
            if not job_id:
                return None

            url = f"{self.BASE_URL}/remote-jobs/{job_id}"

            # Title & company
            title_elem = element.select_one("h2[itemprop='title']")
            company_elem = element.select_one("h3[itemprop='name']")

            title = title_elem.get_text(strip=True) if title_elem else ""
            company = company_elem.get_text(strip=True) if company_elem else ""

            if not title or not company:
                return None

            # Location (usually "Worldwide" or timezone)
            location_elem = element.select_one(".location")
            location = location_elem.get_text(strip=True) if location_elem else "Remote"

            # Tags (work mode, job type, tech stack)
            tags = []
            for tag in element.select(".tag"):
                tags.append(tag.get_text(strip=True))

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

            # Salary (sometimes in tags)
            salary_min = None
            salary_max = None
            for tag in tags:
                if "$" in tag or "€" in tag or "£" in tag:
                    # Try to parse salary
                    pass  # RemoteOK rarely has salary in tags

            # Description preview (from tooltip or data)
            desc_elem = element.select_one("[itemprop='description']")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Posted date
            date_elem = element.select_one("time")
            posted_date = date_elem.get("datetime") if date_elem else None

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

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse RemoteOK job detail page for full description."""
        try:
            soup = self.session.get_soup(url)

            # Main description
            desc_elem = soup.select_one(".description, #job_description, .markdown")
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Extract salary if present
            salary_min = None
            salary_max = None
            salary_text = soup.get_text()
            salary_match = re.search(
                r"[\$€£]\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*[-–]\s*[\$€£]?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
                salary_text,
            )
            if salary_match:
                salary_min = int(salary_match.group(1).replace(",", ""))
                salary_max = int(salary_match.group(2).replace(",", ""))

            # Get job ID from URL
            job_id = url.split("/")[-1]

            return ScrapedJob(
                source=self.SOURCE,
                external_id=job_id,
                url=url,
                title="",  # Already have from card
                company="",
                description=description,
                description_html=description_html,
                salary_min=salary_min,
                salary_max=salary_max,
            )

        except Exception:
            return None


# Register scraper
register_scraper(JobSource.REMOTEOK, RemoteOKScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["RemoteOKScraper"]