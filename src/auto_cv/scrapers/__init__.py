# -*- coding: utf-8 -*-
"""
Auto-CV - Scrapers Package
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Job board scrapers package.
"""

from auto_cv.scrapers.base import (
    BaseScraper,
    SearchFilters,
    ScrapeResult,
    ScrapedJob,
    RateLimiter,
    ScraperSession,
    register_scraper,
    get_scraper,
    list_scrapers,
)
from auto_cv.scrapers.factory import (
    ScraperFactory,
    get_factory,
    scrape_all,
    scrape_source,
    scrape_async,
    MultiScrapeResult,
    RemoteOKScraper,
    WellfoundScraper,
    IndeedScraper,
    LinkedInScraper,
    GlassdoorScraper,
    GupyScraper,
    VagasComScraper,
)

# Ensure all scrapers are registered (import side-effect)
from auto_cv.scrapers import (
    remoteok,   # noqa: F401
    wellfound,  # noqa: F401
    indeed,     # noqa: F401
    linkedin,   # noqa: F401
    glassdoor,  # noqa: F401
    gupy,       # noqa: F401
    vagas_com,  # noqa: F401
)

__all__ = [
    # Base
    "BaseScraper",
    "SearchFilters",
    "ScrapeResult",
    "ScrapedJob",
    "RateLimiter",
    "ScraperSession",
    "register_scraper",
    "get_scraper",
    "list_scrapers",
    # Factory
    "ScraperFactory",
    "get_factory",
    "scrape_all",
    "scrape_source",
    "scrape_async",
    "MultiScrapeResult",
    # Concrete
    "RemoteOKScraper",
    "WellfoundScraper",
    "IndeedScraper",
    "LinkedInScraper",
    "GlassdoorScraper",
    "GupyScraper",
    "VagasComScraper",
]

# Version
__version__ = "1.0.0"