# -*- coding: utf-8 -*-
"""
Auto-CV - Vagas.com Scraper
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Scraper for Vagas.com (vagas.com.br) - Brazilian job board.
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


class VagasComScraper(BaseScraper):
    """
    Scraper for Vagas.com (Brazil).

    Features:
    - Traditional job board
    - Clean HTML structure
    - Portuguese content
    - Pagination via page parameter
    """

    SOURCE = JobSource.VAGAS_COM
    BASE_URL = "https://www.vagas.com.br"
    DEFAULT_RATE_LIMIT = 0.5  # 1 req per 2s
    MAX_PAGES = 10
    JOB_CARD_SELECTOR = "li.vaga, article.vaga, div.vaga"
    PAGINATION_SELECTOR = "a.proxima, li.next a, .pagination a:last-child"

    def build_search_url(self, filters: SearchFilters, page: int) -> str:
        """Build Vagas.com search URL."""
        params = {}

        if filters.query:
            params["q"] = filters.query

        if filters.location:
            params["c"] = filters.location

        if filters.work_mode:
            if filters.work_mode == "remote":
                params["homeOffice"] = "true"

        if page > 1:
            params["pagina"] = str(page)

        query = urlencode(params)
        return f"{self.BASE_URL}/vagas?{query}"

    def parse_job_card(self, element: BeautifulSoup) -> Optional[ScrapedJob]:
        """Parse a Vagas.com job card."""
        try:
            # Job ID from data attribute or link
            job_id = element.get("data-id") or element.get("id", "").replace("vaga-", "")
            if not job_id:
                link = element.select_one("a[href*='/vaga/'], a[href*='/job/']")
                if link:
                    href = link.get("href", "")
                    job_id = href.split("/")[-1].split("?")[0]

            if not job_id:
                return None

            url = f"{self.BASE_URL}/vaga/{job_id}"

            # Title
            title_elem = element.select_one(
                "h2.titulo a, h3.titulo a, .vaga-titulo a, a[href*='/vaga/']"
            )
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title and title_elem:
                title = title_elem.get("title", "").strip()

            # Company
            company_elem = element.select_one(
                ".empresa, .empresa-nome, .company, [data-empresa]"
            )
            company = company_elem.get_text(strip=True) if company_elem else ""
            if not company and company_elem:
                company = company_elem.get("data-empresa", "").strip()

            if not title or not company:
                return None

            # Location
            location_elem = element.select_one(
                ".local, .localizacao, .cidade, .vaga-local"
            )
            location = location_elem.get_text(strip=True) if location_elem else ""

            # Work mode
            work_mode = None
            if element.select_one(".home-office, .remoto, [data-home-office]"):
                work_mode = "remote"
            elif "hibrido" in (location or "").lower() or "híbrido" in (location or "").lower():
                work_mode = "hybrid"

            # Job type
            job_type = None
            type_elem = element.select_one(".tipo-contrato, .contrato, [data-tipo]")
            if type_elem:
                type_text = type_elem.get_text(strip=True).lower()
                if "clt" in type_text or "efetivo" in type_text:
                    job_type = "full-time"
                elif "pj" in type_text:
                    job_type = "contract"
                elif "estágio" in type_text or "estagio" in type_text:
                    job_type = "internship"
                elif "temporário" in type_text or "temporario" in type_text:
                    job_type = "temporary"

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = element.select_one(".salario, .faixa-salarial, [data-salario]")
            if salary_elem:
                salary_text = salary_elem.get_text(strip=True)
                salary_min, salary_max = self._parse_salary_br(salary_text)

            # Description snippet
            desc_elem = element.select_one(".resumo, .descricao, .vaga-descricao")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Posted date
            date_elem = element.select_one(".data, .data-publicacao, time")
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
                raw_data={},
            )

        except Exception:
            return None

    def _parse_salary_br(self, text: str) -> tuple:
        """Parse Brazilian salary: 'R$ 5.000 a R$ 8.000', '5.000 - 8.000'."""
        patterns = [
            r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:a|[-–])\s*R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
            r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*[-–]\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
            r"a\s+combinar",  # "a combinar" = negotiable
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if "combinar" in match.group(0).lower():
                    return None, None
                try:
                    min_str = match.group(1).replace(".", "").replace(",", ".")
                    max_str = match.group(2).replace(".", "").replace(",", ".")
                    return int(float(min_str)), int(float(max_str))
                except (ValueError, IndexError):
                    continue

        return None, None

    def _parse_date_br(self, text: str) -> Optional[str]:
        """Parse Portuguese dates: '15/01/2024', 'há 2 dias', 'ontem'."""
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

        match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
        if match:
            try:
                day, month, year = map(int, match.groups())
                return f"{year}-{month:02d}-{day:02d}"
            except ValueError:
                pass

        return None

    def parse_job_detail(self, url: str) -> Optional[ScrapedJob]:
        """Parse Vagas.com job detail page."""
        try:
            soup = self.session.get_soup(url)

            # Description
            desc_elem = soup.select_one(
                ".vaga-descricao, .descricao-completa, .job-description, [itemprop='description']"
            )
            description = desc_elem.get_text(strip=True) if desc_elem else None
            description_html = str(desc_elem) if desc_elem else None

            # Salary
            salary_min = None
            salary_max = None
            salary_elem = soup.select_one(".salario, .faixa-salarial, [data-salario]")
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


# Register scraper
register_scraper(JobSource.VAGAS_COM, VagasComScraper)


# ============================================================
# EXPORTS
# ============================================================

__all__ = ["VagasComScraper"]