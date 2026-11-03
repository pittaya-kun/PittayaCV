# -*- coding: utf-8 -*-
"""
Auto-CV - Gupy Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for Gupy (gupy.io) - Brazilian job platform.
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


class GupyScraper(BaseScraper):
    """
    Scraper for Gupy (Brazilian job platform).

    Features:
    - Modern React app (may need Playwright for full rendering)
    - GraphQL API endpoints
    - Clean job cards
    - Portuguese content
    """

    SOURCE = JobSource.GUPY
    BASE_URL = "https://portal.gupy.io"
    DEFAULT_RATE_LIMIT = 0.5  # 1 req per 2s
    MAX_PAGES = 10
    JOB_CARD_SELECTOR = "div[data-testid='job-card'], .job-card, article.job"
    PAGINATION_SELECTOR = "button[data-testid='next-page'], a[rel='next']"

    # GraphQL endpoint (may change)
    GRAPHQL_URL = "https://portal.gupy.io/api/graphql"

    def __init__(self, use_playwright: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.use_playwright = use_playwright
        self._playwright_page = None

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build Gupy search URL."""
        params = {}

        if filters.query:
            params["search"] = filters.query

        if filters.location:
            params["location"] = filters.location

        if filters.work_mode:
            mode_map = {"remote": "remoto", "hybrid": "hibrido", "onsite": "presencial"}
            if filters.work_mode in mode_map:
                params["workplaceType"] = mode_map[filters.work_mode]

        if page > 1:
            params["page"] = str(page)

        query = urlencode(params)
        return f"{self.BASE_URL}/jobs?{query}"

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a Gupy job card."""
        try:
            # Job ID from data attribute or link
            job_id = element.get("data-job-id") or element.get("data-id")
            if not job_id:
                link = element.select_one("a[href*='/job/'], a[href*='/vaga/']")
                if link:
                    href = link.get("href", "")
                    job_id = href.split("/")[-1].split("?")[0]

            if not job_id:
                return None

            url = f"{self.BASE_URL}/job/{job_id}"

            # Title
            title_elem = element.select_one(
                "[data-testid='job-title'], h2.title, h3.title, .job-title"
            )
            title = title_elem.get_text(strip=True) if title_elem else ""

            # Company
            company_elem = element.select_one(
                "[data-testid='company-name'], .company-name, .employer-name"
            )
            company = company_elem.get_text(strip=True) if company_elem else ""

            if not title or not company:
                return None

            # Location
            location_elem = element.select_one(
                "[data-testid='job-location'], .location, .job-location"
            )
            location = location_elem.get_text(strip=True) if location_elem else ""

            # Work mode
            work_mode = None
            mode_elem = element.select_one(
                "[data-testid='workplace-type'], .workplace-type, .modalidade"
            )
            if mode_elem:
                mode_text = mode_elem.get_text(strip=True).lower()
                if "remoto" in mode_text:
                    work_mode = "remote"
                elif "hibrido" in mode_text or "híbrido" in mode_text:
                    work_mode = "hybrid"
                elif "presencial" in mode_text:
                    work_mode = "onsite"

            # Job type
            job_type = None
            type_elem = element.select_one("[data-testid='job-type'], .job-type, .tipo-contrato")
            if type_elem:
                type_text = type_elem.get_text(strip=True).lower()
                if "clt" in type_text or "efetivo" in type_text:
                    job_type = "full-time"
                elif "pj" in type_text or "contrato" in type_text:
                    job_type = "contract"
                elif "estágio" in type_text or "estagio" in type_text:
                    job_type = "internship"

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = element.select_one("[data-testid='salary'], .salary, .faixa-salarial")
            if salary_elem:
                salary_text = salary_elem.get_text(strip=True)
                salary_min, salary_max = self._parse_salary_br(salary_text)

            # Description snippet
            desc_elem = element.select_one("[data-testid='job-description'], .description, .resumo")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Tags
            tags = []
            for tag in element.select("[data-testid='tag'], .tag, .skill-tag"):
                tags.append(tag.get_text(strip=True))

            # Posted date
            date_elem = element.select_one("time, [data-testid='posted-date'], .data-publicacao")
            posted_date = date_elem.get("datetime") if date_elem else None
            if not posted_date and date_elem:
                posted_date = self._parse_date_br(date_elem.get_text(strip=True))

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
                salary_currency="BRL",
                posted_date=posted_date,
                raw_data={"tags": tags},
            )

        except Exception:
            return None

    def _parse_salary_br(self, text: str) -> tuple:
        """Parse Brazilian salary format: 'R$ 5.000 - R$ 8.000', '5k - 8k'."""
        # Handle Brazilian format with dots as thousands separator
        patterns = [
            r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*[-–]\s*R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
            r"(\d+(?:,\d+)?)\s*[kK]\s*[-–]\s*(\d+(?:,\d+)?)\s*[kK]",
            r"(\d{1,3}(?:\.\d{3})*)\s*[-–]\s*(\d{1,3}(?:\.\d{3})*)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    min_str = match.group(1).replace(".", "").replace(",", ".")
                    max_str = match.group(2).replace(".", "").replace(",", ".")

                    min_val = float(min_str)
                    max_val = float(max_str)

                    # Handle 'k' suffix
                    if "k" in match.group(0).lower():
                        min_val *= 1000
                        max_val *= 1000

                    return int(min_val), int(max_val)
                except ValueError:
                    continue

        return None, None

    def _parse_date_br(self, text: str) -> Optional[str]:
        """Parse Portuguese relative dates: 'há 2 dias', 'ontem', 'hoje'."""
        from datetime import datetime, timedelta

        text = text.lower().strip()
        now = datetime.utcnow()

        if "hoje" in text:
            return now.date().isoformat()
        if "ontem" in text:
            return (now - timedelta(days=1)).date().isoformat()

        match = re.search(r"há\s+(\d+)\s+(dia|dias)", text)
        if match:
            days = int(match.group(1))
            return (now - timedelta(days=days)).date().isoformat()

        match = re.search(r"há\s+(\d+)\s+(semana|semanas)", text)
        if match:
            weeks = int(match.group(1))
            return (now - timedelta(weeks=weeks)).date().isoformat()

        match = re.search(r"há\s+(\d+)\s+(mês|meses)", text)
        if match:
            months = int(match.group(1))
            return (now - timedelta(days=months * 30)).date().isoformat()

        # Try absolute date: "15/01/2024"
        match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
        if match:
            try:
                day, month, year = map(int, match.groups())
                return f"{year}-{month:02d}-{day:02d}"
            except ValueError:
                pass

        return None

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse Gupy job detail page."""
        try:
            soup = self.session.get_soup(url)

            # Try to find GraphQL data in script tags
            for script in soup.select("script[type='application/json']"):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and "job" in data:
                        return self._parse_gupy_json(data["job"], url)
                except (json.JSONDecodeError, KeyError):
                    continue

            # Fallback: parse HTML
            desc_elem = soup.select_one(
                "[data-testid='job-description'], .job-description, .descricao-vaga, [itemprop='description']"
            )
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one("[data-testid='salary'], .salary, .faixa-salarial")
            if salary_elem:
                salary_min, salary_max = self._parse_salary_br(salary_elem.get_text())

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

    def _parse_gupy_json(self, data: dict, url: str) -> ScrapedJob:
        """Parse Gupy job JSON data."""
        job_id = str(data.get("id", url.split("/")[-1]))

        salary_min = None
        salary_max = None
        if data.get("salaryRange"):
            salary_min = data["salaryRange"].get("min")
            salary_max = data["salaryRange"].get("max")

        workplace_type = data.get("workplaceType", "").lower()
        work_mode = None
        if "remoto" in workplace_type:
            work_mode = "remote"
        elif "hibrido" in workplace_type:
            work_mode = "hybrid"
        elif "presencial" in workplace_type:
            work_mode = "onsite"

        return ScrapedJob(
            source=self.SOURCE,
            external_id=job_id,
            url=url,
            title=data.get("title", ""),
            company=data.get("company", {}).get("name", ""),
            location=data.get("city", "") + ", " + data.get("state", ""),
            work_mode=work_mode,
            job_type=data.get("type", "").lower().replace("_", "-"),
            description=data.get("description", ""),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="BRL",
            posted_date=data.get("publishedAt", "").split("T")[0] if data.get("publishedAt") else None,
        )


# Register scraper
register_scraper(JobSource.GUPY, GupyScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["GupyScraper"]