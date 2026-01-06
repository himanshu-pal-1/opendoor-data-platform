"""Analytics and reporting modules.

This module exports analytics functions for market segmentation,
practice analysis, and report generation.
"""

from src.analytics.market_segmentation import (
    MarketSegmentation,
    PhysicianSegment,
    SegmentStats,
    SegmentType,
)
from src.analytics.practice_analytics import (
    AcquisitionTarget,
    MarketInsight,
    PracticeAnalytics,
    ValuationSummary,
)
from src.analytics.reporting import ReportGenerator

__all__ = [
    # Market segmentation
    "MarketSegmentation",
    "PhysicianSegment",
    "SegmentStats",
    "SegmentType",
    # Practice analytics
    "PracticeAnalytics",
    "ValuationSummary",
    "MarketInsight",
    "AcquisitionTarget",
    # Reporting
    "ReportGenerator",
]
