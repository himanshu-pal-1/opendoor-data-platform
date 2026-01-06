"""Physician market segmentation.

This module provides functionality to segment physicians into acquisition
target categories based on demographics, practice characteristics,
and revenue patterns.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger()


class SegmentType(str, Enum):
    """Physician acquisition target segment types."""

    TYPE_1 = "type_1"  # Solo owners 55+, declining revenue
    TYPE_2 = "type_2"  # Group practice members
    TYPE_3 = "type_3"  # Health system employed
    TYPE_4 = "type_4"  # Fresh graduates with debt


@dataclass
class PhysicianSegment:
    """Segment classification for a physician."""

    npi: str
    segment_type: SegmentType
    segment_score: float  # 0-1 confidence in classification
    acquisition_likelihood: float  # 0-1 probability of successful acquisition

    # Segment-specific factors
    is_solo_owner: bool = False
    is_declining_revenue: bool = False
    is_near_retirement: bool = False
    has_partnership_potential: bool = False
    is_health_system_employed: bool = False
    is_recent_graduate: bool = False
    estimated_debt_level: Optional[str] = None  # low, medium, high

    # Supporting metrics
    estimated_age: Optional[int] = None
    years_since_graduation: Optional[int] = None
    revenue_trend: Optional[float] = None  # YoY change


@dataclass
class SegmentStats:
    """Statistics for a segment."""

    segment_type: SegmentType
    count: int
    avg_acquisition_likelihood: float
    avg_practice_value: Optional[Decimal] = None
    geographic_distribution: dict[str, int] = None
    specialty_distribution: dict[str, int] = None


class MarketSegmentation:
    """Physician market segmentation engine.

    Classifies physicians into acquisition target categories based on
    their demographics, practice structure, and financial characteristics.

    Segment Definitions:
    - Type 1: Solo owners 55+, potentially declining revenue
      (Highest priority - motivated sellers)
    - Type 2: Group practice members
      (Partnership/buyout opportunities)
    - Type 3: Health system employed
      (Strategic acquisition targets)
    - Type 4: Fresh graduates with debt
      (Recruitment/partnership opportunities)

    Example:
        >>> segmenter = MarketSegmentation()
        >>> segments = segmenter.segment_physicians(session)
        >>> for seg in segments:
        ...     print(f"{seg.npi}: {seg.segment_type.value}")
    """

    def __init__(
        self,
        retirement_age_threshold: int = 55,
        recent_graduate_years: int = 5,
        revenue_decline_threshold: float = -0.05,
    ):
        """Initialize market segmentation.

        Args:
            retirement_age_threshold: Age considered near retirement.
            recent_graduate_years: Years since graduation for "new" physician.
            revenue_decline_threshold: YoY change considered "declining".
        """
        self.retirement_age_threshold = retirement_age_threshold
        self.recent_graduate_years = recent_graduate_years
        self.revenue_decline_threshold = revenue_decline_threshold

    def _calculate_acquisition_likelihood(
        self,
        segment_type: SegmentType,
        age: Optional[int],
        revenue_trend: Optional[float],
        is_sole_proprietor: bool,
    ) -> float:
        """Calculate acquisition likelihood based on factors.

        Args:
            segment_type: The physician's segment type.
            age: Estimated age.
            revenue_trend: Year-over-year revenue change.
            is_sole_proprietor: Whether sole proprietor.

        Returns:
            Likelihood score between 0 and 1.
        """
        base_likelihoods = {
            SegmentType.TYPE_1: 0.70,  # High - motivated sellers
            SegmentType.TYPE_2: 0.40,  # Medium - partnership dependent
            SegmentType.TYPE_3: 0.25,  # Lower - institutional barriers
            SegmentType.TYPE_4: 0.35,  # Medium - financial motivation
        }

        likelihood = base_likelihoods[segment_type]

        # Adjust for age (older = more likely to sell)
        if age and segment_type == SegmentType.TYPE_1:
            if age >= 65:
                likelihood += 0.15
            elif age >= 60:
                likelihood += 0.10

        # Adjust for revenue trend (declining = more likely)
        if revenue_trend is not None:
            if revenue_trend < -0.10:
                likelihood += 0.15
            elif revenue_trend < -0.05:
                likelihood += 0.08

        # Sole proprietor adjustment
        if is_sole_proprietor and segment_type == SegmentType.TYPE_1:
            likelihood += 0.05  # No partners to convince

        return min(likelihood, 0.95)  # Cap at 95%

    def _determine_segment(
        self,
        age: Optional[int],
        is_sole_proprietor: bool,
        has_organization: bool,
        years_since_graduation: Optional[int],
        revenue_trend: Optional[float],
    ) -> tuple[SegmentType, float]:
        """Determine segment type for a physician.

        Args:
            age: Estimated age.
            is_sole_proprietor: Whether sole proprietor.
            has_organization: Whether part of an organization.
            years_since_graduation: Years since medical school.
            revenue_trend: Year-over-year revenue change.

        Returns:
            Tuple of (segment_type, segment_score).
        """
        # Type 1: Solo owners 55+, declining revenue
        if is_sole_proprietor and age and age >= self.retirement_age_threshold:
            score = 0.8
            if revenue_trend and revenue_trend < self.revenue_decline_threshold:
                score = 0.95
            elif age >= 65:
                score = 0.90
            return SegmentType.TYPE_1, score

        # Type 4: Recent graduates (within N years)
        if (
            years_since_graduation
            and years_since_graduation <= self.recent_graduate_years
        ):
            score = 0.75
            if not is_sole_proprietor:
                score = 0.85  # Likely employed, may have debt
            return SegmentType.TYPE_4, score

        # Type 3: Health system employed (would need additional data)
        # For now, heuristic: organization but not sole proprietor
        if has_organization and not is_sole_proprietor:
            # Could be Type 2 or Type 3 - default to Type 2
            return SegmentType.TYPE_2, 0.60

        # Type 2: Group practice members
        if has_organization:
            return SegmentType.TYPE_2, 0.65

        # Default to Type 2 with lower confidence
        return SegmentType.TYPE_2, 0.40

    def segment_physician(
        self,
        npi: str,
        birth_year: Optional[int],
        graduation_year: Optional[int],
        is_sole_proprietor: bool,
        has_organization: bool,
        revenue_trend: Optional[float] = None,
    ) -> PhysicianSegment:
        """Segment a single physician.

        Args:
            npi: National Provider Identifier.
            birth_year: Year of birth.
            graduation_year: Year of medical school graduation.
            is_sole_proprietor: Whether physician is sole proprietor.
            has_organization: Whether part of parent organization.
            revenue_trend: Year-over-year revenue change.

        Returns:
            PhysicianSegment with classification.
        """
        current_year = datetime.now().year

        age = current_year - birth_year if birth_year else None
        years_since_grad = (
            current_year - graduation_year if graduation_year else None
        )

        segment_type, segment_score = self._determine_segment(
            age, is_sole_proprietor, has_organization, years_since_grad, revenue_trend
        )

        likelihood = self._calculate_acquisition_likelihood(
            segment_type, age, revenue_trend, is_sole_proprietor
        )

        return PhysicianSegment(
            npi=npi,
            segment_type=segment_type,
            segment_score=segment_score,
            acquisition_likelihood=likelihood,
            is_solo_owner=is_sole_proprietor,
            is_declining_revenue=bool(
                revenue_trend and revenue_trend < self.revenue_decline_threshold
            ),
            is_near_retirement=bool(age and age >= self.retirement_age_threshold),
            has_partnership_potential=has_organization and not is_sole_proprietor,
            is_health_system_employed=False,  # Would need additional data
            is_recent_graduate=bool(
                years_since_grad and years_since_grad <= self.recent_graduate_years
            ),
            estimated_age=age,
            years_since_graduation=years_since_grad,
            revenue_trend=revenue_trend,
        )

    def segment_physicians_from_db(
        self,
        session: Session,
        limit: Optional[int] = None,
    ) -> list[PhysicianSegment]:
        """Segment physicians from database.

        Args:
            session: SQLAlchemy session.
            limit: Maximum number of physicians to process.

        Returns:
            List of PhysicianSegment objects.
        """
        logger.info("starting_bulk_segmentation", limit=limit)

        query = """
            SELECT
                p.npi,
                p.birth_year,
                p.graduation_year,
                p.is_sole_proprietor,
                p.parent_organization_npi IS NOT NULL as has_organization
            FROM physicians p
        """

        if limit:
            query += f" LIMIT {limit}"

        result = session.execute(text(query))
        rows = result.fetchall()

        segments = []
        for row in rows:
            npi, birth_year, grad_year, is_sole, has_org = row

            segment = self.segment_physician(
                npi=npi,
                birth_year=birth_year,
                graduation_year=grad_year,
                is_sole_proprietor=is_sole,
                has_organization=has_org,
            )
            segments.append(segment)

        logger.info("bulk_segmentation_complete", count=len(segments))
        return segments

    def get_segment_statistics(self, session: Session) -> list[SegmentStats]:
        """Get statistics for each segment.

        Args:
            session: SQLAlchemy session.

        Returns:
            List of SegmentStats for each segment type.
        """
        query = text("""
            SELECT
                segment_type,
                COUNT(*) as count,
                AVG(acquisition_likelihood) as avg_likelihood
            FROM physician_segments
            GROUP BY segment_type
        """)

        result = session.execute(query)
        rows = result.fetchall()

        stats = []
        for row in rows:
            stats.append(
                SegmentStats(
                    segment_type=SegmentType(row[0]),
                    count=row[1],
                    avg_acquisition_likelihood=float(row[2]) if row[2] else 0,
                )
            )

        return stats

    def get_high_priority_targets(
        self,
        session: Session,
        min_likelihood: float = 0.6,
        limit: int = 100,
    ) -> list[dict]:
        """Get high-priority acquisition targets.

        Args:
            session: SQLAlchemy session.
            min_likelihood: Minimum acquisition likelihood.
            limit: Maximum results to return.

        Returns:
            List of physician dictionaries with segment info.
        """
        query = text("""
            SELECT
                p.npi,
                p.first_name,
                p.last_name,
                p.specialty_primary,
                p.practice_state,
                p.practice_zip,
                s.segment_type,
                s.acquisition_likelihood,
                s.segment_score
            FROM physicians p
            JOIN physician_segments s ON p.npi = s.physician_npi
            WHERE s.acquisition_likelihood >= :min_likelihood
            ORDER BY s.acquisition_likelihood DESC
            LIMIT :limit
        """)

        result = session.execute(
            query, {"min_likelihood": min_likelihood, "limit": limit}
        )
        rows = result.fetchall()

        targets = []
        for row in rows:
            targets.append({
                "npi": row[0],
                "name": f"{row[1]} {row[2]}",
                "specialty": row[3],
                "state": row[4],
                "zip_code": row[5],
                "segment_type": row[6],
                "acquisition_likelihood": float(row[7]),
                "segment_score": float(row[8]),
            })

        return targets
