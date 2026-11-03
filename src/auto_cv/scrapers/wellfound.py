# -*- coding: utf-8 -*-
"""
Auto-CV - Wellfound Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for Wellfound (wellfound.com) - startup jobs.
"""

import json
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


class WellfoundScraper(BaseScraper):
    """
    Scraper for Wellfound (formerly AngelList Talent).

    Features:
    - Startup-focused jobs
    - Clean HTML structure
    - API-like job listings
    - Requires handling infinite scroll / pagination
    """

    SOURCE = JobSource.WELLFOUND
    BASE_URL = "https://wellfound.com"
    DEFAULT_RATE_LIMIT = 0.33  # 1 req per 3s (stricter)
    MAX_PAGES = 5
    JOB_CARD_SELECTOR = "div[data-test='JobCard']"
    PAGINATION_SELECTOR = "a[data-test='pagination-next']"

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build Wellfound search URL."""
        params = {}

        if filters.query:
            params["search"] = filters.query

        if filters.location:
            params["location"] = filters.location

        if filters.work_mode:
            mode_map = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}
            if filters.work_mode in mode_map:
                params["remote"] = "true" if filters.work_mode == "remote" else "false"

        if filters.job_type:
            type_map = {
                "full-time": "full_time",
                "part-time": "part_time",
                "contract": "contract",
            }
            if filters.job_type in type_map:
                params["job_type"] = type_map[filters.job_type]

        if page > 1:
            params["page"] = str(page)

        query = urlencode(params)
        return f"{self.BASE_URL}/jobs?{query}"

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a Wellfound job card."""
        try:
            # Job ID from data attribute
            job_id = element.get("data-job-id") or element.get("data-id")
            if not job_id:
                # Try to extract from link
                link = element.select_one("a[href*='/jobs/']")
                if link:
                    job_id = link["href"].split("/")[-1].split("?")[0]

            if not job_id:
                return None

            url = f"{self.BASE_URL}/jobs/{job_id}"

            # Title
            title_elem = element.select_one("[data-test='JobTitle'], h2.title")
            title = title_elem.get_text(strip=True) if title_elem else ""

            # Company
            company_elem = element.select_one("[data-test='CompanyName'], .company-name")
            company = company_elem.get_text(strip=True) if company_elem else ""

            if not title or not company:
                return None

            # Location
            location_elem = element.select_one("[data-test='JobLocation'], .location")
            location = location_elem.get_text(strip=True) if location_elem else "Remote"

            # Work mode
            work_mode = "remote"
            remote_badge = element.select_one("[data-test='RemoteBadge'], .remote-badge")
            if remote_badge:
                work_mode = "remote"
            elif "hybrid" in location.lower():
                work_mode = "hybrid"
            elif "onsite" in location.lower() or "on-site" in location.lower():
                work_mode = "onsite"

            # Job type
            job_type = None
            type_elem = element.select_one("[data-test='JobType'], .job-type")
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
            salary_elem = element.select_one("[data-test='Salary'], .salary")
            if salary_elem:
                salary_text = salary_elem.get_text(strip=True)
                salary_min, salary_max = self._parse_salary(salary_text)

            # Description preview
            desc_elem = element.select_one("[data-test='JobDescription'], .description")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Tags/skills
            tags = []
            for tag in element.select("[data-test='JobTag'], .tag"):
                tags.append(tag.get_text(strip=True))

            # Posted date
            date_elem = element.select_one("time, [data-test='PostedDate']")
            posted_date = date_elem.get("datetime") if date_elem else None
            if not posted_date and date_elem:
                posted_date = date_elem.get_text(strip=True)

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

    def _parse_salary(self, text: str) -> tuple:
        """Parse salary from text like '$100k - $150k' or '$100,000 - $150,000'."""
        # Match patterns like $100k - $150k or $100,000 - $150,000
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

                    # Handle 'k' suffix
                    if "k" in match.group(0).lower():
                        min_val *= 1000
                        max_val *= 1000

                    return int(min_val), int(max_val)
                except ValueError:
                    continue

        return None, None

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse Wellfound job detail page."""
        try:
            soup = self.session.get_soup(url)

            # Try to find JSON-LD structured data
            script = soup.select_one('script[type="application/ld+json"]')
            if script:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        data = data[0]
                    if data.get("@type") == "JobPosting":
                        return self._parse_json_ld(data, url)
                except (json.JSONDecodeError, KeyError):
                    pass

            # Fallback: parse HTML
            desc_elem = soup.select_one(
                "[data-test='JobDescription'], .job-description, [itemprop='description']"
            )
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one("[data-test='Salary'], .salary-range")
            if salary_elem:
                salary_min, salary_max = self._parse_salary(salary_elem.get_text())

            job_id = url.split("/")[-1].split("?")[0]

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
            posted_date=data.get("datePosted"),
        )


# Register scraper
register_scraper(JobSource.WELLFOUND, WellfoundScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["WellfoundScraper"]