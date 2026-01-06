"""Pipeline configuration.

This module provides configuration for data pipelines including
data source URLs, schedules, and processing settings.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from pydantic_settings import BaseSettings


class PipelineSettings(BaseSettings):
    """Pipeline configuration settings from environment variables."""

    # Database
    database_url: str = "postgresql://opendoor:password@localhost:5432/opendoor_data"

    # Data source URLs
    nppes_download_url: str = "https://download.cms.gov/nppes/"
    cms_data_url: str = "https://data.cms.gov/provider-data/"

    # Processing settings
    batch_size: int = 10000
    max_workers: int = 4
    retry_attempts: int = 3
    retry_delay_seconds: int = 60

    # Storage
    data_directory: str = "./data"
    nppes_directory: str = "./data/nppes"
    cms_directory: str = "./data/cms"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Feature flags
    enable_payer_data: bool = False
    enable_practice_financials: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@dataclass
class DataSourceConfig:
    """Configuration for a data source."""

    name: str
    description: str
    url: str
    update_frequency: str  # daily, weekly, monthly, quarterly, annually
    enabled: bool = True
    priority: int = 1  # Lower = higher priority
    dependencies: list[str] = field(default_factory=list)


# Predefined data source configurations
DATA_SOURCES = {
    "nppes": DataSourceConfig(
        name="NPPES",
        description="National Plan and Provider Enumeration System",
        url="https://download.cms.gov/nppes/",
        update_frequency="weekly",
        priority=1,
    ),
    "cms_payments": DataSourceConfig(
        name="CMS Medicare Payments",
        description="Medicare Physician & Other Practitioners Payment Data",
        url="https://data.cms.gov/provider-data/",
        update_frequency="annually",
        priority=2,
        dependencies=["nppes"],
    ),
    "pecos": DataSourceConfig(
        name="PECOS",
        description="Provider Enrollment, Chain, and Ownership System",
        url="https://data.cms.gov/provider-characteristics/",
        update_frequency="monthly",
        priority=3,
        dependencies=["nppes"],
    ),
    "physician_compare": DataSourceConfig(
        name="Physician Compare",
        description="CMS Physician Compare dataset",
        url="https://data.cms.gov/provider-data/dataset/mj5m-pzi6",
        update_frequency="quarterly",
        priority=4,
        dependencies=["nppes"],
    ),
}


@dataclass
class PipelineStep:
    """Definition of a pipeline step."""

    name: str
    description: str
    function: str  # Fully qualified function name
    timeout_seconds: int = 3600
    retries: int = 3
    retry_delay_seconds: int = 60
    enabled: bool = True


# Pipeline step definitions
INGESTION_PIPELINE_STEPS = [
    PipelineStep(
        name="download_nppes",
        description="Download latest NPPES data file",
        function="pipelines.ingestion_pipeline.download_nppes_data",
        timeout_seconds=1800,
    ),
    PipelineStep(
        name="parse_nppes",
        description="Parse NPPES data and load physicians",
        function="pipelines.ingestion_pipeline.parse_and_load_nppes",
        timeout_seconds=7200,
    ),
    PipelineStep(
        name="download_cms",
        description="Download CMS payment data",
        function="pipelines.ingestion_pipeline.download_cms_data",
        timeout_seconds=1800,
    ),
    PipelineStep(
        name="parse_cms",
        description="Parse CMS payment data",
        function="pipelines.ingestion_pipeline.parse_and_load_cms",
        timeout_seconds=7200,
    ),
    PipelineStep(
        name="create_practices",
        description="Create practice records from physician data",
        function="pipelines.ingestion_pipeline.create_practices",
        timeout_seconds=3600,
    ),
    PipelineStep(
        name="enrich_practices",
        description="Enrich practices with CMS payment data",
        function="pipelines.ingestion_pipeline.enrich_practices",
        timeout_seconds=3600,
    ),
    PipelineStep(
        name="calculate_valuations",
        description="Calculate practice valuations",
        function="pipelines.ingestion_pipeline.calculate_valuations",
        timeout_seconds=3600,
    ),
    PipelineStep(
        name="segment_physicians",
        description="Segment physicians into acquisition categories",
        function="pipelines.ingestion_pipeline.segment_physicians",
        timeout_seconds=1800,
    ),
]

UPDATE_PIPELINE_STEPS = [
    PipelineStep(
        name="check_updates",
        description="Check for new data source updates",
        function="pipelines.update_pipeline.check_for_updates",
        timeout_seconds=300,
    ),
    PipelineStep(
        name="download_updates",
        description="Download updated data files",
        function="pipelines.update_pipeline.download_updates",
        timeout_seconds=1800,
    ),
    PipelineStep(
        name="process_updates",
        description="Process incremental updates",
        function="pipelines.update_pipeline.process_updates",
        timeout_seconds=3600,
    ),
    PipelineStep(
        name="refresh_valuations",
        description="Refresh valuations for updated practices",
        function="pipelines.update_pipeline.refresh_valuations",
        timeout_seconds=1800,
    ),
]


def get_settings() -> PipelineSettings:
    """Get pipeline settings from environment."""
    return PipelineSettings()


def get_data_source(name: str) -> Optional[DataSourceConfig]:
    """Get configuration for a data source.

    Args:
        name: Data source name.

    Returns:
        DataSourceConfig or None if not found.
    """
    return DATA_SOURCES.get(name.lower())


def get_enabled_sources() -> list[DataSourceConfig]:
    """Get list of enabled data sources sorted by priority.

    Returns:
        List of enabled DataSourceConfig sorted by priority.
    """
    return sorted(
        [s for s in DATA_SOURCES.values() if s.enabled],
        key=lambda x: x.priority,
    )
