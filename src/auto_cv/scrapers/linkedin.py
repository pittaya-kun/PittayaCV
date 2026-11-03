# -*- coding: utf-8 -*-
"""
Auto-CV - LinkedIn Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for LinkedIn Jobs (linkedin.com) - professional network.
"""

import re
import time
from typing import Optional, Dict
from urllib.parse import quote_plus, urlencode, urlparse, parse_qs

from bs4 import BeautifulSoup

from auto_cv.scrapers.base import (
    BaseScraper,
    SearchFilters,
    ScrapedJob,
    register_scraper,
)
from auto_cv.storage.models import JobSource


class LinkedInScraper(BaseScraper):
    """
    Scraper for LinkedIn Jobs.

    Features:
    - Requires authentication (cookies) for best results
    - Anti-bot measures (rate limiting, challenges)
    - Dynamic content (may need Playwright)
    - Structured job cards with data attributes
    """

    SOURCE = JobSource.LINKEDIN
    BASE_URL = "https://www.linkedin.com"
    DEFAULT_RATE_LIMIT = 0.25  # 1 req per 4s (conservative)
    MAX_PAGES = 5
    JOB_CARD_SELECTOR = "li.job-card-container, div.job-card, article.job-card"
    PAGINATION_SELECTOR = "button[aria-label='Next'], a.next"

    # Search URL patterns
    JOBS_SEARCH_URL = "/jobs-guest/jobs/api/seeMoreJobPostings/search"
    JOB_DETAIL_URL = "/jobs-guest/jobs/api/jobPosting/"

    def __init__(
        self,
        li_at_cookie: Optional[str] = None,
        jsessionid_cookie: Optional[str] = None,
        use_playwright: bool = False,
        **kwargs,
    ):
        """
        Args:
            li_at_cookie: LinkedIn 'li_at' session cookie (for auth)
            jsessionid_cookie: LinkedIn 'JSESSIONID' cookie
            use_playwright: Use Playwright for JS rendering
        """
        extra_headers = kwargs.pop("extra_headers", {})
        extra_headers.update({
            "Referer": "https://www.linkedin.com/jobs/",
            "Origin": "https://www.linkedin.com",
        })

        cookies = kwargs.pop("cookies", {})
        if li_at_cookie:
            cookies["li_at"] = li_at_cookie
        if jsessionid_cookie:
            cookies["JSESSIONID"] = jsessionid_cookie

        super().__init__(extra_headers=extra_headers, cookies=cookies, **kwargs)
        self.use_playwright = use_playwright
        self._playwright_page = None

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build LinkedIn jobs search URL."""
        params = {}

        if filters.query:
            params["keywords"] = filters.query

        if filters.location:
            params["location"] = filters.location

        if filters.work_mode:
            # LinkedIn uses f_WT parameter: 1=onsite, 2=remote, 3=hybrid
            mode_map = {"onsite": "1", "remote": "2", "hybrid": "3"}
            if filters.work_mode in mode_map:
                params["f_WT"] = mode_map[filters.work_mode]

        if filters.job_type:
            # f_JT: F=full-time, P=part-time, C=contract, T=temporary, I=internship
            type_map = {
                "full-time": "F",
                "part-time": "P",
                "contract": "C",
                "temporary": "T",
                "internship": "I",
            }
            if filters.job_type in type_map:
                params["f_JT"] = type_map[filters.job_type]

        if filters.date_posted:
            # f_TPR: r86400=24h, r604800=week, r2592000=month
            date_map = {
                "last_24h": "r86400",
                "last_week": "r604800",
                "last_month": "r2592000",
            }
            if filters.date_posted in date_map:
                params["f_TPR"] = date_map[filters.date_posted]

        # Pagination: start = (page - 1) * 25
        if page > 1:
            params["start"] = str((page - 1) * 25)

        query = urlencode(params)
        return f"{self.BASE_URL}{self.JOBS_SEARCH_URL}?{query}"

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a LinkedIn job card."""
        try:
            # Job ID from data attribute
            job_id = element.get("data-entity-urn", "").split(":")[-1]
            if not job_id:
                link = element.select_one("a[href*='/jobs/view/']")
                if link:
                    href = link.get("href", "")
                    match = re.search(r"/jobs/view/(\d+)", href)
                    if match:
                        job_id = match.group(1)

            if not job_id:
                return None

            url = f"{self.BASE_URL}/jobs/view/{job_id}"

            # Title
            title_elem = element.select_one(
                "h3.base-search-card__title, h3.job-card-title, a.job-card-title"
            )
            title = title_elem.get_text(strip=True) if title_elem else ""

            # Company
            company_elem = element.select_one(
                "h4.base-search-card__subtitle, a.job-card-company, .job-card-company-name"
            )
            company = company_elem.get_text(strip=True) if company_elem else ""

            if not title or not company:
                return None

            # Location
            location_elem = element.select_one(
                ".job-search-card__location, .job-card-location, .job-location"
            )
            location = location_elem.get_text(strip=True) if location_elem else ""

            # Work mode (from badge)
            work_mode = None
            for badge in element.select(".job-card-benefits, .benefits, .work-mode"):
                badge_text = badge.get_text(strip=True).lower()
                if "remote" in badge_text or "remoto" in badge_text:
                    work_mode = "remote"
                elif "hybrid" in badge_text or "híbrido" in badge_text:
                    work_mode = "hybrid"
                elif "on-site" in badge_text or "presencial" in badge_text:
                    work_mode = "onsite"

            # Job type
            job_type = None
            type_elem = element.select_one(".job-card-type, .job-type")
            if type_elem:
                type_text = type_elem.get_text(strip=True).lower()
                if "full" in type_text:
                    job_type = "full-time"
                elif "part" in type_text:
                    job_type = "part-time"
                elif "contract" in type_text:
                    job_type = "contract"

            # Salary (rarely shown in card)
            salary_min = None
            salary_max = None
            salary_elem = element.select_one(".job-card-salary, .salary")
            if salary_elem:
                salary_min, salary_max = self._parse_salary(salary_elem.get_text())

            # Description snippet
            desc_elem = element.select_one(".job-card-description, .description")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Posted date
            date_elem = element.select_one("time, .job-search-card__listdate")
            posted_date = date_elem.get("datetime") if date_elem else None
            if not posted_date and date_elem:
                posted_date = self._parse_relative_date(date_elem.get_text(strip=True))

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
        """Parse salary from various formats."""
        patterns = [
            r"[\$€£R\$]\s?(\d[\d.,]*)\s*[-–]\s*[\$€£R\$]?\s?(\d[\d.,]*)",
            r"(\d[\d.,]*)\s*[-–]\s*(\d[\d.,]*)\s*(?:por\s*m[êe]s|a\s*year|/year|/month)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    min_val = float(match.group(1).replace(",", "").replace(".", ""))
                    max_val = float(match.group(2).replace(",", "").replace(".", ""))

                    if "mês" in text.lower() or "/month" in text.lower():
                        min_val *= 12
                        max_val *= 12

                    return int(min_val), int(max_val)
                except ValueError:
                    continue

        return None, None

    def _parse_relative_date(self, text: str) -> Optional[str]:
        """Parse relative dates: '2 days ago', '1 week ago', '30+ days ago'."""
        from datetime import datetime, timedelta

        text = text.lower().strip()
        now = datetime.utcnow()

        if "today" in text or "hoje" in text or "agora" in text:
            return now.date().isoformat()
        if "yesterday" in text or "ontem" in text:
            return (now - timedelta(days=1)).date().isoformat()

        match = re.search(r"(\d+)\s*(day|days|dia|dias)", text)
        if match:
            days = int(match.group(1))
            return (now - timedelta(days=days)).date().isoformat()

        match = re.search(r"(\d+)\s*(week|weeks|semana|semanas)", text)
        if match:
            weeks = int(match.group(1))
            return (now - timedelta(weeks=weeks)).date().isoformat()

        match = re.search(r"(\d+)\s*(month|months|mês|meses)", text)
        if match:
            months = int(match.group(1))
            return (now - timedelta(days=months * 30)).date().isoformat()

        if "30+" in text or "30 +" in text:
            return (now - timedelta(days=30)).date().isoformat()

        return None

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse LinkedIn job detail page."""
        try:
            # Use the API endpoint for cleaner data
            job_id = url.split("/")[-1].split("?")[0]
            api_url = f"{self.BASE_URL}{self.JOB_DETAIL_URL}{job_id}"

            soup = self.session.get_soup(api_url)

            # The API returns HTML with structured data
            # Try to extract from JSON-LD
            script = soup.select_one('script[type="application/ld+json"]')
            if script:
                try:
                    import json
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        data = data[0]
                    if data.get("@type") == "JobPosting":
                        return self._parse_json_ld(data, url)
                except (json.JSONDecodeError, KeyError):
                    pass

            # Fallback: parse HTML
            desc_elem = soup.select_one(
                ".description__text, .show-more-less-html__markup, [itemprop='description']"
            )
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one(".salary, .compensation")
            if salary_elem:
                salary_min, salary_max = self._parse_salary(salary_elem.get_text())

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
        """Parse JobPosting JSON-LD."""
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

        location = ""
        if "jobLocation" in data:
            loc = data["jobLocation"]
            if isinstance(loc, dict):
                address = loc.get("address", {})
                location = address.get("addressLocality", "")
                if address.get("addressRegion"):
                    location += ", " + address["addressRegion"]
                if address.get("addressCountry"):
                    location += ", " + address["addressCountry"]

        return ScrapedJob(
            source=self.SOURCE,
            external_id=job_id,
            url=url,
            title=data.get("title", ""),
            company=data.get("hiringOrganization", {}).get("name", ""),
            location=location,
            work_mode=data.get("jobLocationType", "").lower(),
            job_type=data.get("employmentType", "").replace("_", "-"),
            description=data.get("description", ""),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=data.get("baseSalary", {}).get("currency", "BRL"),
            posted_date=data.get("datePosted", "").split("T")[0] if data.get("datePosted") else None,
        )


# Register scraper
register_scraper(JobSource.LINKEDIN, LinkedInScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["LinkedInScraper"]