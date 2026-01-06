"""CMS data ingestion module.

This module handles downloading, parsing, and enriching CMS Medicare
payment and provider data for practice valuation.
"""

from src.ingest.cms.cms_client import CMSClient, CMSDownloadError
from src.ingest.cms.cms_enricher import CMSEnricher, EnrichedPractice
from src.ingest.cms.cms_parser import (
    CMSParser,
    CMSParseError,
    PhysicianPayment,
    PracticeRevenue,
)

__all__ = [
    "CMSClient",
    "CMSDownloadError",
    "CMSParser",
    "CMSParseError",
    "PhysicianPayment",
    "PracticeRevenue",
    "CMSEnricher",
    "EnrichedPractice",
]
