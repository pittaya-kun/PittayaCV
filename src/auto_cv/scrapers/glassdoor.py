# -*- coding: utf-8 -*-
"""
Auto-CV - Glassdoor Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for Glassdoor (glassdoor.com / glassdoor.com.br) - company reviews & jobs.
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


class GlassdoorScraper(BaseScraper):
    """
    Scraper for Glassdoor Jobs.

    Features:
    - Company reviews + jobs
    - Anti-bot measures (requires headers)
    - Job cards with data attributes
    - Pagination via IP parameter
    """

    SOURCE = JobSource.GLASSDOOR
    BASE_URL = "https://www.glassdoor.com.br"
    DEFAULT_RATE_LIMIT = 0.33  # 1 req per 3s
    MAX_PAGES = 5
    JOB_CARD_SELECTOR = "li.react-job-listing, div.jobListing, article.job-listing"
    PAGINATION_SELECTOR = "button[data-test='pagination-next'], a.next"

    # Country domains
    DOMAINS = {
        "br": "https://www.glassdoor.com.br",
        "com": "https://www.glassdoor.com",
        "ca": "https://www.glassdoor.ca",
        "uk": "https://www.glassdoor.co.uk",
        "au": "https://www.glassdoor.com.au",
        "de": "https://www.glassdoor.de",
        "fr": "https://www.glassdoor.fr",
        "nl": "https://www.glassdoor.nl",
        "in": "https://www.glassdoor.co.in",
        "sg": "https://www.glassdoor.sg",
    }

    def __init__(self, country: str = "br", **kwargs):
        self.country = country.lower()
        base_url = self.DOMAINS.get(self.country, self.DOMAINS["br"])
        kwargs["base_url"] = base_url
        super().__init__(**kwargs)
        self.BASE_URL = base_url

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build Glassdoor search URL."""
        params = {}

        if filters.query:
            params["sc.keyword"] = filters.query

        if filters.location:
            params["locT"] = "C"
            params["locId"] = self._get_location_id(filters.location)

        if filters.work_mode:
            if filters.work_mode == "remote":
                params["remote"] = "1"

        if filters.job_type:
            type_map = {
                "full-time": "fulltime",
                "part-time": "parttime",
                "contract": "contract",
            }
            if filters.job_type in type_map:
                params["jobType"] = type_map[filters.job_type]

        # Pagination
        if page > 1:
            params["p"] = str(page)

        query = urlencode(params)
        return f"{self.BASE_URL}/Job/jobs.htm?{query}"

    def _get_location_id(self, location: str) -> str:
        """Map location to Glassdoor location ID (simplified)."""
        # In production, would call Glassdoor's location API
        # For now, return common IDs
        location_map = {
            "são paulo": "1147435",
            "rio de janeiro": "1147436",
            "brasil": "1147434",
            "remote": "1",
            "remoto": "1",
        }
        return location_map.get(location.lower(), "1147434")

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a Glassdoor job card."""
        try:
            # Job ID from data attribute
            job_id = element.get("data-job-id") or element.get("data-id")
            if not job_id:
                link = element.select_one("a[href*='/partner/jobListing.htm']")
                if link:
                    href = link.get("href", "")
                    match = re.search(r"jobListingId=(\d+)", href)
                    if match:
                        job_id = match.group(1)

            if not job_id:
                return None

            # Glassdoor uses partner links
            url = f"{self.BASE_URL}/partner/jobListing.htm?jobListingId={job_id}"

            # Title
            title_elem = element.select_one(
                "[data-test='job-title'], .jobTitle, .job-title a"
            )
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title and title_elem:
                title = title_elem.get("title", "").strip()

            # Company
            company_elem = element.select_one(
                "[data-test='employer-name'], .employerName, .company-name"
            )
            company = company_elem.get_text(strip=True) if company_elem else ""

            if not title or not company:
                return None

            # Location
            location_elem = element.select_one(
                "[data-test='job-location'], .jobLocation, .location"
            )
            location = location_elem.get_text(strip=True) if location_elem else ""

            # Work mode
            work_mode = None
            remote_elem = element.select_one("[data-test='remote-badge'], .remote-badge")
            if remote_elem:
                work_mode = "remote"
            elif "hybrid" in (location or "").lower() or "híbrido" in (location or "").lower():
                work_mode = "hybrid"

            # Job type
            job_type = None
            type_elem = element.select_one("[data-test='job-type'], .jobType")
            if type_elem:
                type_text = type_elem.get_text(strip=True).lower()
                if "full" in type_text:
                    job_type = "full-time"
                elif "part" in type_text:
                    job_type = "part-time"
                elif "contract" in type_text:
                    job_type = "contract"

            # Salary (Glassdoor often shows estimates)
            salary_min = None
            salary_max = None
            salary_elem = element.select_one("[data-test='salary'], .salaryEstimate, .salary")
            if salary_elem:
                salary_text = salary_elem.get_text(strip=True)
                salary_min, salary_max = self._parse_salary(salary_text)

            # Rating (company)
            rating = None
            rating_elem = element.select_one("[data-test='rating'], .rating")
            if rating_elem:
                try:
                    rating = float(rating_elem.get_text(strip=True).split()[0])
                except (ValueError, IndexError):
                    pass

            # Description snippet
            desc_elem = element.select_one("[data-test='job-description'], .jobDescription")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Posted date
            date_elem = element.select_one("[data-test='job-age'], .jobAge")
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
                raw_data={"company_rating": rating},
            )

        except Exception:
            return None

    def _parse_salary(self, text: str) -> tuple:
        """Parse Glassdoor salary estimates."""
        # Formats: "$100K - $150K (Est.)", "R$ 10.000 - R$ 15.000 /mês"
        patterns = [
            r"[\$€£R\$]\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s*[kK]?\s*[-–]\s*[\$€£R\$]?\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s*[kK]?",
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

                    if "/mês" in text or "/mes" in text or "por mês" in text:
                        min_val *= 12
                        max_val *= 12

                    return int(min_val), int(max_val)
                except ValueError:
                    continue

        return None, None

    def _parse_relative_date(self, text: str) -> Optional[str]:
        """Parse relative dates: '2 days ago', '1 week ago', 'há 2 dias'."""
        from datetime import datetime, timedelta

        text = text.lower().strip()
        now = datetime.utcnow()

        if "today" in text or "hoje" in text:
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

        return None

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse Glassdoor job detail page."""
        try:
            soup = self.session.get_soup(url)

            # Description
            desc_elem = soup.select_one(
                "[data-test='job-description'], .jobDescriptionContent, .desc"
            )
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one("[data-test='salary'], .salaryEstimate")
            if salary_elem:
                salary_min, salary_max = self._parse_salary(salary_elem.get_text())

            # Job ID from URL
            job_id = ""
            if "jobListingId=" in url:
                job_id = url.split("jobListingId=")[1].split("&")[0]

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
register_scraper(JobSource.GLASSDOOR, GlassdoorScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["GlassdoorScraper"]