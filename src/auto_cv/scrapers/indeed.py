# -*- coding: utf-8 -*-
"""
Auto-CV - Indeed Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for Indeed (indeed.com / indeed.com.br) - global job board.
"""

import re
from typing import Optional
from urllib.parse import quote_plus, urlencode

from bs4 import BeautifulSoup

from auto_cv.scrapers.base import (
    BaseScraper,
    SearchFilters,
    ScrapedJob,
    register_scraper,
)
from auto_cv.storage.models import JobSource


class IndeedScraper(BaseScraper):
    """
    Scraper for Indeed.

    Features:
    - Global job board (multiple TLDs)
    - Pagination via start parameter
    - Job cards with data attributes
    - Anti-bot measures (requires headers rotation)
    """

    SOURCE = JobSource.INDEED
    BASE_URL = "https://br.indeed.com"  # Default to Brazil, configurable
    DEFAULT_RATE_LIMIT = 0.5  # 1 req per 2s
    MAX_PAGES = 10
    JOB_CARD_SELECTOR = "div.job_seen_beacon, div[data-jk], .result"
    PAGINATION_SELECTOR = "a[data-testid='pagination-page-next'], nav[aria-label='pagination'] a:last-child"

    # Country-specific domains
    DOMAINS = {
        "br": "https://br.indeed.com",
        "com": "https://www.indeed.com",
        "pt": "https://pt.indeed.com",
        "uk": "https://uk.indeed.com",
        "ca": "https://ca.indeed.com",
        "au": "https://au.indeed.com",
        "de": "https://de.indeed.com",
        "fr": "https://fr.indeed.com",
        "nl": "https://nl.indeed.com",
        "it": "https://it.indeed.com",
        "es": "https://es.indeed.com",
    }

    def __init__(self, country: str = "br", **kwargs):
        self.country = country.lower()
        base_url = self.DOMAINS.get(self.country, self.DOMAINS["br"])
        # Set BASE_URL before super().__init__ so session uses it
        self.BASE_URL = base_url
        super().__init__(**kwargs)

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build Indeed search URL."""
        params = {}

        if filters.query:
            params["q"] = filters.query

        if filters.location:
            params["l"] = filters.location

        if filters.work_mode:
            if filters.work_mode == "remote":
                params["remotejob"] = "1"
            elif filters.work_mode == "hybrid":
                params["hybrid"] = "1"

        if filters.job_type:
            type_map = {
                "full-time": "fulltime",
                "part-time": "parttime",
                "contract": "contract",
                "temporary": "temporary",
                "internship": "internship",
            }
            if filters.job_type in type_map:
                params["jt"] = type_map[filters.job_type]

        if filters.salary_min:
            params["salary"] = f"{filters.salary_min},"

        if filters.date_posted:
            date_map = {
                "last_24h": "1",
                "last_week": "7",
                "last_month": "30",
            }
            if filters.date_posted in date_map:
                params["fromage"] = date_map[filters.date_posted]

        if filters.radius_km:
            params["radius"] = str(filters.radius_km)

        # Pagination: start = (page - 1) * 10
        if page > 1:
            params["start"] = str((page - 1) * 10)

        query = urlencode(params)
        return f"{self.BASE_URL}/jobs?{query}"

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse an Indeed job card."""
        try:
            # Job ID from data-jk attribute
            job_id = element.get("data-jk") or element.get("data-job-id")
            if not job_id:
                link = element.select_one("a[jk], a[data-jk]")
                if link:
                    job_id = link.get("data-jk") or link.get("jk")

            if not job_id:
                return None

            url = f"{self.BASE_URL}/viewjob?jk={job_id}"

            # Title
            title_elem = element.select_one(
                "h2.jobTitle a, h2 a[data-jk], .jobTitle a, [data-testid='job-title']"
            )
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title and title_elem:
                title = title_elem.get("title", "").strip()

            # Company
            company_elem = element.select_one(
                "[data-testid='company-name'], .companyName, .company_location .companyName"
            )
            company = company_elem.get_text(strip=True) if company_elem else ""

            if not title or not company:
                return None

            # Location
            location_elem = element.select_one(
                "[data-testid='job-location'], .companyLocation, .locationsContainer"
            )
            location = location_elem.get_text(strip=True) if location_elem else ""

            # Work mode detection
            work_mode = None
            remote_indicators = element.select(".remote, [data-testid='remote-badge']")
            if remote_indicators:
                work_mode = "remote"
            elif "hybrid" in (location or "").lower():
                work_mode = "hybrid"
            elif "remote" in (location or "").lower():
                work_mode = "remote"

            # Job type
            job_type = None
            type_elem = element.select_one(".jobType, [data-testid='job-type']")
            if type_elem:
                type_text = type_elem.get_text(strip=True).lower()
                if "full" in type_text:
                    job_type = "full-time"
                elif "part" in type_text:
                    job_type = "part-time"
                elif "contract" in type_text:
                    job_type = "contract"

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = element.select_one(".salary-snippet, [data-testid='salary'], .estimated-salary")
            if salary_elem:
                salary_text = salary_elem.get_text(strip=True)
                salary_min, salary_max = self._parse_salary(salary_text)

            # Description snippet
            desc_elem = element.select_one(".job-snippet, [data-testid='job-snippet'], .summary")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Posted date
            date_elem = element.select_one("span.date, [data-testid='job-age']")
            posted_date = None
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                posted_date = self._parse_relative_date(date_text)

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
                raw_data={},
            )

        except Exception:
            return None

    def _parse_salary(self, text: str) -> tuple:
        """Parse salary from Indeed format."""
        # Patterns: "R$ 5.000 - R$ 8.000 por mês", "$100,000 - $150,000 a year"
        patterns = [
            r"[\$€£R\$]\s?(\d[\d.,]*)\s*[-–]\s*[\$€£R\$]?\s?(\d[\d.,]*)",
            r"(\d[\d.,]*)\s*[-–]\s*(\d[\d.,]*)\s*(?:por\s*m[êe]s|a\s*year|/year|/month)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    min_val = float(match.group(1).replace(".", "").replace(",", ""))
                    max_val = float(match.group(2).replace(".", "").replace(",", ""))

                    # Check if monthly/yearly
                    if "mês" in text.lower() or "/month" in text.lower() or "por mês" in text.lower():
                        min_val *= 12
                        max_val *= 12

                    return int(min_val), int(max_val)
                except ValueError:
                    continue

        return None, None

    def _parse_relative_date(self, text: str) -> Optional[str]:
        """Parse relative dates like 'há 2 dias', '3 days ago', 'today'."""
        from datetime import datetime, timedelta

        text = text.lower().strip()
        now = datetime.utcnow()

        if "hoje" in text or "today" in text or "agora" in text:
            return now.date().isoformat()
        if "ontem" in text or "yesterday" in text:
            return (now - timedelta(days=1)).date().isoformat()

        # "há X dias" or "X days ago"
        match = re.search(r"(?:há|hace|vor|il y a)?\s*(\d+)\s*(dia|dias|day|days)", text)
        if match:
            days = int(match.group(1))
            return (now - timedelta(days=days)).date().isoformat()

        # "há X semanas" or "X weeks ago"
        match = re.search(r"(?:há|hace|vor|il y a)?\s*(\d+)\s*(semana|semanas|week|weeks)", text)
        if match:
            weeks = int(match.group(1))
            return (now - timedelta(weeks=weeks)).date().isoformat()

        # "há X meses" or "X months ago"
        match = re.search(r"(?:há|hace|vor|il y a)?\s*(\d+)\s*(mês|meses|month|months)", text)
        if match:
            months = int(match.group(1))
            return (now - timedelta(days=months * 30)).date().isoformat()

        return None

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse Indeed job detail page."""
        try:
            soup = self.session.get_soup(url)

            # Job description
            desc_elem = soup.select_one("#jobDescriptionText, .jobsearch-jobDescriptionText, [itemprop='description']")
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Salary from detail page
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one(".jobsearch-JobMetadataHeader-item, .salary-info")
            if salary_elem:
                salary_text = salary_elem.get_text(strip=True)
                salary_min, salary_max = self._parse_salary(salary_text)

            # Job ID from URL
            job_id = ""
            if "jk=" in url:
                job_id = url.split("jk=")[1].split("&")[0]

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


# Register scraper
register_scraper(JobSource.INDEED, IndeedScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["IndeedScraper"]