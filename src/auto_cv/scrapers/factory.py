# -*- coding: utf-8 -*-
"""
Auto-CV - Scraper Factory Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Factory and registry for job scrapers (OCP - easy to add new sources).
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from auto_cv.config import get_settings
from auto_cv.scrapers.base import (
    BaseScraper,
    SearchFilters,
    ScrapeResult,
    ScrapedJob,
    get_scraper,
    list_scrapers,
    register_scraper,
    _SCRAPER_REGISTRY,
)
from auto_cv.scrapers.glassdoor import GlassdoorScraper
from auto_cv.scrapers.gupy import GupyScraper
from auto_cv.scrapers.indeed import IndeedScraper
from auto_cv.scrapers.linkedin import LinkedInScraper
from auto_cv.scrapers.remoteok import RemoteOKScraper
from auto_cv.scrapers.remoteok_pw import RemoteOKPlaywrightScraper, scrape_remoteok_sync
from auto_cv.scrapers.vagas_com import VagasComScraper
from auto_cv.scrapers.wellfound import WellfoundScraper
from auto_cv.scrapers.wellfound_pw import WellfoundPlaywrightScraper, scrape_wellfound_sync
from auto_cv.storage.models import Job, JobSource
from auto_cv.storage.sqlite import JobRepository, SearchHistoryRepository, session_scope


# ============================================================
# REGISTRATION (import side-effect registers all scrapers)
# ============================================================

# All scrapers are registered via import side-effect in their modules
# This file ensures they're all imported


@dataclass
class MultiScrapeResult:
    """Combined result from multiple scrapers."""
    results: Dict[JobSource, ScrapeResult]
    total_jobs: int
    total_new: int
    errors: List[str]
    duration_seconds: float


class ScraperFactory:
    """
    Factory for creating and managing scrapers.

    Features:
    - Singleton scraper instances per source
    - Concurrent scraping with thread pool
    - Deduplication across sources
    - Database integration
    """

    def __init__(self, settings=None, max_workers: int = 3):
        self.settings = settings or get_settings()
        self.max_workers = max_workers
        self._scrapers: Dict[JobSource, BaseScraper] = {}
        self._seen_urls: Set[str] = set()

    def get_scraper(self, source: JobSource, **kwargs) -> BaseScraper:
        """Get or create scraper instance for source."""
        if source not in self._scrapers:
            self._scrapers[source] = get_scraper(source, **kwargs)
        return self._scrapers[source]

    def scrape(
        self,
        sources: List[JobSource],
        filters: Optional[SearchFilters] = None,
        save_to_db: bool = True,
        enrich_details: bool = False,
    ) -> MultiScrapeResult:
        """
        Scrape multiple sources concurrently.

        Args:
            sources: List of JobSource to scrape
            filters: Search filters to apply
            save_to_db: Whether to save jobs to database
            enrich_details: Whether to fetch job detail pages

        Returns:
            MultiScrapeResult with combined results
        """
        import time
        start_time = time.time()
        all_results: Dict[JobSource, ScrapeResult] = {}
        all_errors: List[str] = []
        all_jobs: List[ScrapedJob] = []

        # Separate async and sync sources
        async_sources = []
        sync_sources = []

        for source in sources:
            # Skip sources without registered scrapers
            if source not in list_scrapers():
                all_results[source] = ScrapeResult(
                    jobs=[],
                    total_found=0,
                    pages_scraped=0,
                    errors=[f"No scraper registered for {source.value}"],
                    duration_seconds=0,
                )
                continue

            scraper_class = _SCRAPER_REGISTRY.get(source)
            if scraper_class and hasattr(scraper_class, 'search') and asyncio.iscoroutinefunction(scraper_class.search):
                async_sources.append(source)
            else:
                sync_sources.append(source)

        # Run async scrapers
        if async_sources:
            async_results = asyncio.run(self._scrape_async_sources(async_sources, filters, enrich_details))
            for source, result in async_results.items():
                all_results[source] = result
                all_errors.extend([f"{source.value}: {e}" for e in result.errors])
                for job in result.jobs:
                    if job.url not in self._seen_urls:
                        self._seen_urls.add(job.url)
                        all_jobs.append(job)

        # Run sync scrapers in thread pool
        if sync_sources:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._scrape_source, source, filters, enrich_details): source
                    for source in sync_sources
                }

                for future in futures:
                    source = futures[future]
                    try:
                        result = future.result()
                        all_results[source] = result
                        all_errors.extend([f"{source.value}: {e}" for e in result.errors])

                        for job in result.jobs:
                            if job.url not in self._seen_urls:
                                self._seen_urls.add(job.url)
                                all_jobs.append(job)

                    except Exception as e:
                        all_errors.append(f"{source.value}: {str(e)}")
                        all_results[source] = ScrapeResult(
                            jobs=[],
                            total_found=0,
                            pages_scraped=0,
                            errors=[str(e)],
                            duration_seconds=0,
                        )

        # Save to database
        new_count = 0
        if save_to_db and all_jobs:
            new_count = self._save_jobs(all_jobs, filters)

        duration = time.time() - start_time

        return MultiScrapeResult(
            results=all_results,
            total_jobs=len(all_jobs),
            total_new=new_count,
            errors=all_errors,
            duration_seconds=duration,
        )

    async def _scrape_async_sources(
        self,
        sources: List[JobSource],
        filters: Optional[SearchFilters],
        enrich_details: bool,
    ) -> Dict[JobSource, ScrapeResult]:
        """Scrape async sources concurrently using asyncio."""
        async def scrape_one(source: JobSource) -> tuple:
            scraper = self.get_scraper(source)
            result = await scraper.search(filters)
            if enrich_details and result.jobs:
                result.jobs = await scraper.scrape_job_details(result.jobs)
            return source, result

        tasks = [scrape_one(source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for result in results:
            if isinstance(result, Exception):
                # This shouldn't happen with return_exceptions=True
                continue
            source, scrape_result = result
            output[source] = scrape_result

        return output

    def _scrape_source(
        self,
        source: JobSource,
        filters: Optional[SearchFilters],
        enrich_details: bool,
    ) -> ScrapeResult:
        """Scrape a single source."""
        scraper = self.get_scraper(source)
        result = scraper.search(filters)

        if enrich_details and result.jobs:
            result.jobs = scraper.scrape_job_details(result.jobs)

        return result

    def _save_jobs(self, jobs: List[ScrapedJob], filters: Optional[SearchFilters]) -> int:
        """Save jobs to database, return count of new jobs."""
        new_count = 0

        with session_scope() as session:
            job_repo = JobRepository(session)
            history_repo = SearchHistoryRepository(session)

            # Log search history
            history = history_repo.create(
                source=filters.query if filters else "multi",
                query=filters.query if filters else None,
                filters=filters.__dict__ if filters else None,
            )

            for scraped_job in jobs:
                job = scraped_job.to_job()
                saved_job = job_repo.upsert(job)
                if saved_job.id and not job.is_duplicate:
                    new_count += 1

            # Update history with results
            history_repo.update(
                history.id,
                results_count=len(jobs),
                new_jobs_count=new_count,
            )

        return new_count


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

_default_factory: Optional[ScraperFactory] = None


def get_factory(settings=None, max_workers: int = 3) -> ScraperFactory:
    """Get or create default factory."""
    global _default_factory
    if _default_factory is None:
        _default_factory = ScraperFactory(settings, max_workers)
    return _default_factory


def scrape_all(
    filters: Optional[SearchFilters] = None,
    sources: Optional[List[JobSource]] = None,
    save_to_db: bool = True,
    enrich_details: bool = False,
) -> MultiScrapeResult:
    """
    Convenience function to scrape all registered sources.

    Args:
        filters: Search filters
        sources: Sources to scrape (default: all registered)
        save_to_db: Save to database
        enrich_details: Fetch detail pages

    Returns:
        MultiScrapeResult
    """
    factory = get_factory()
    sources = sources or list_scrapers()
    return factory.scrape(sources, filters, save_to_db, enrich_details)


def scrape_source(
    source: JobSource,
    filters: Optional[SearchFilters] = None,
    save_to_db: bool = True,
    enrich_details: bool = False,
) -> ScrapeResult:
    """Convenience function to scrape a single source (handles async scrapers)."""
    factory = get_factory()
    scraper = factory.get_scraper(source)

    # Check if scraper has async search method (Playwright)
    if hasattr(scraper, 'search') and asyncio.iscoroutinefunction(scraper.search):
        result = asyncio.run(scraper.search(filters))

        if enrich_details and result.jobs:
            result.jobs = asyncio.run(scraper.scrape_job_details(result.jobs))
    else:
        result = scraper.search(filters)

        if enrich_details and result.jobs:
            result.jobs = scraper.scrape_job_details(result.jobs)

    if save_to_db and result.jobs:
        from auto_cv.storage.sqlite import JobRepository, SearchHistoryRepository, session_scope
        with session_scope() as session:
            job_repo = JobRepository(session)
            history_repo = SearchHistoryRepository(session)

            history = history_repo.create(
                source=source.value,
                query=filters.query if filters else None,
                filters=filters.__dict__ if filters else None,
            )

            for scraped_job in result.jobs:
                job = scraped_job.to_job()
                job_repo.upsert(job)

            history_repo.update(
                history.id,
                results_count=len(result.jobs),
                new_jobs_count=len(result.jobs),
            )

    return result


# ============================================================
# ASYNC SCRAPING (for future use with Playwright)
# ============================================================

async def scrape_async(
    sources: List[JobSource],
    filters: Optional[SearchFilters] = None,
    save_to_db: bool = True,
) -> MultiScrapeResult:
    """Async version for Playwright-based scrapers."""
    # TODO: Implement when adding Playwright scrapers
    # For now, run sync in thread pool
    loop = asyncio.get_event_loop()
    factory = get_factory()
    return await loop.run_in_executor(
        None,
        factory.scrape,
        sources,
        filters,
        save_to_db,
        False,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Factory
    "ScraperFactory",
    "get_factory",
    # Convenience
    "scrape_all",
    "scrape_source",
    # Async
    "scrape_async",
    # Types
    "MultiScrapeResult",
    # Re-exports from base
    "BaseScraper",
    "SearchFilters",
    "ScrapeResult",
    "ScrapedJob",
    "get_scraper",
    "list_scrapers",
    "register_scraper",
    # Concrete scrapers
    "RemoteOKScraper",
    "WellfoundScraper",
    "IndeedScraper",
    "LinkedInScraper",
    "GlassdoorScraper",
    "GupyScraper",
    "VagasComScraper",
]