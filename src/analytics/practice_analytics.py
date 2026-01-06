"""Practice analytics and insights.

This module provides analytics functions for understanding practice
valuations, identifying high-value targets, and generating market insights.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger()


@dataclass
class ValuationSummary:
    """Summary statistics for practice valuations."""

    total_practices: int
    total_valuation: Decimal
    avg_valuation: Decimal
    median_valuation: Decimal
    min_valuation: Decimal
    max_valuation: Decimal
    avg_revenue_multiple: float
    avg_ebitda_multiple: Optional[float]


@dataclass
class MarketInsight:
    """Market insight for a geographic or specialty segment."""

    segment_name: str
    segment_type: str  # 'geographic', 'specialty', 'payer_mix'
    practice_count: int
    total_valuation: Decimal
    avg_valuation: Decimal
    avg_physician_count: float
    avg_revenue_per_physician: Decimal
    opportunity_score: float  # 0-1


@dataclass
class AcquisitionTarget:
    """Practice acquisition target with scoring."""

    practice_id: str
    practice_name: str
    location: str
    specialty: str
    valuation: Decimal
    physician_count: int
    payer_mix_commercial: float
    target_score: float  # 0-1 overall attractiveness
    factors: dict


class PracticeAnalytics:
    """Analytics engine for practice-level insights.

    Provides analytics and recommendations for practice acquisitions,
    market opportunities, and portfolio analysis.

    Example:
        >>> analytics = PracticeAnalytics()
        >>> summary = analytics.get_valuation_summary(session, state="CA")
        >>> print(f"Total CA valuation: ${summary.total_valuation:,.0f}")
    """

    def get_valuation_summary(
        self,
        session: Session,
        state: Optional[str] = None,
        specialty: Optional[str] = None,
    ) -> ValuationSummary:
        """Get summary statistics for practice valuations.

        Args:
            session: SQLAlchemy session.
            state: Filter by state (optional).
            specialty: Filter by specialty (optional).

        Returns:
            ValuationSummary with aggregate statistics.
        """
        query = """
            SELECT
                COUNT(DISTINCT v.practice_id) as practice_count,
                SUM(v.valuation_amount) as total_val,
                AVG(v.valuation_amount) as avg_val,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.valuation_amount) as median_val,
                MIN(v.valuation_amount) as min_val,
                MAX(v.valuation_amount) as max_val,
                AVG(v.revenue_multiple) as avg_rev_mult,
                AVG(v.ebitda_multiple) as avg_ebitda_mult
            FROM valuations v
            JOIN practices p ON v.practice_id = p.id
            WHERE 1=1
        """

        params = {}
        if state:
            query += " AND p.state = :state"
            params["state"] = state
        if specialty:
            query += " AND p.specialty_primary LIKE :specialty"
            params["specialty"] = f"%{specialty}%"

        result = session.execute(text(query), params)
        row = result.fetchone()

        return ValuationSummary(
            total_practices=row[0] or 0,
            total_valuation=Decimal(str(row[1] or 0)),
            avg_valuation=Decimal(str(row[2] or 0)),
            median_valuation=Decimal(str(row[3] or 0)),
            min_valuation=Decimal(str(row[4] or 0)),
            max_valuation=Decimal(str(row[5] or 0)),
            avg_revenue_multiple=float(row[6] or 0),
            avg_ebitda_multiple=float(row[7]) if row[7] else None,
        )

    def get_valuation_by_specialty(
        self,
        session: Session,
    ) -> list[dict]:
        """Get average valuations grouped by specialty.

        Args:
            session: SQLAlchemy session.

        Returns:
            List of specialty valuation summaries.
        """
        query = text("""
            SELECT
                p.specialty_primary,
                COUNT(DISTINCT v.practice_id) as practice_count,
                AVG(v.valuation_amount) as avg_valuation,
                AVG(v.revenue_multiple) as avg_multiple,
                SUM(v.valuation_amount) as total_valuation
            FROM valuations v
            JOIN practices p ON v.practice_id = p.id
            WHERE p.specialty_primary IS NOT NULL
            GROUP BY p.specialty_primary
            ORDER BY avg_valuation DESC
        """)

        result = session.execute(query)
        rows = result.fetchall()

        return [
            {
                "specialty": row[0],
                "practice_count": row[1],
                "avg_valuation": float(row[2]) if row[2] else 0,
                "avg_multiple": float(row[3]) if row[3] else 0,
                "total_valuation": float(row[4]) if row[4] else 0,
            }
            for row in rows
        ]

    def get_valuation_by_geography(
        self,
        session: Session,
        group_by: str = "state",
    ) -> list[dict]:
        """Get average valuations grouped by geography.

        Args:
            session: SQLAlchemy session.
            group_by: Geographic grouping ('state' or 'zip_prefix').

        Returns:
            List of geographic valuation summaries.
        """
        if group_by == "zip_prefix":
            geo_column = "LEFT(p.zip_code, 3)"
        else:
            geo_column = "p.state"

        query = text(f"""
            SELECT
                {geo_column} as geography,
                COUNT(DISTINCT v.practice_id) as practice_count,
                AVG(v.valuation_amount) as avg_valuation,
                AVG(p.physician_count) as avg_physicians,
                SUM(v.valuation_amount) as total_valuation
            FROM valuations v
            JOIN practices p ON v.practice_id = p.id
            WHERE {geo_column} IS NOT NULL
            GROUP BY {geo_column}
            ORDER BY avg_valuation DESC
        """)

        result = session.execute(query)
        rows = result.fetchall()

        return [
            {
                "geography": row[0],
                "practice_count": row[1],
                "avg_valuation": float(row[2]) if row[2] else 0,
                "avg_physicians": float(row[3]) if row[3] else 0,
                "total_valuation": float(row[4]) if row[4] else 0,
            }
            for row in rows
        ]

    def identify_high_value_practices(
        self,
        session: Session,
        min_valuation: Optional[Decimal] = None,
        min_commercial_payer: float = 0.4,
        limit: int = 50,
    ) -> list[AcquisitionTarget]:
        """Identify high-value acquisition targets.

        Args:
            session: SQLAlchemy session.
            min_valuation: Minimum valuation threshold.
            min_commercial_payer: Minimum commercial payer percentage.
            limit: Maximum results to return.

        Returns:
            List of AcquisitionTarget objects.
        """
        query = """
            SELECT
                p.id,
                p.name,
                p.city || ', ' || p.state as location,
                p.specialty_primary,
                v.valuation_amount,
                p.physician_count,
                p.payer_mix_commercial,
                v.confidence_level,
                v.data_completeness_score,
                p.revenue_annual,
                v.combined_multiplier
            FROM valuations v
            JOIN practices p ON v.practice_id = p.id
            WHERE p.payer_mix_commercial >= :min_commercial
        """

        params = {"min_commercial": min_commercial_payer}

        if min_valuation:
            query += " AND v.valuation_amount >= :min_val"
            params["min_val"] = float(min_valuation)

        query += """
            ORDER BY v.valuation_amount DESC
            LIMIT :limit
        """
        params["limit"] = limit

        result = session.execute(text(query), params)
        rows = result.fetchall()

        targets = []
        for row in rows:
            # Calculate target score
            score = self._calculate_target_score(
                valuation=row[4],
                physician_count=row[5],
                commercial_payer=row[6],
                confidence=row[7],
                data_completeness=row[8],
            )

            targets.append(
                AcquisitionTarget(
                    practice_id=str(row[0]),
                    practice_name=row[1],
                    location=row[2] or "Unknown",
                    specialty=row[3] or "General",
                    valuation=Decimal(str(row[4])),
                    physician_count=row[5],
                    payer_mix_commercial=row[6],
                    target_score=score,
                    factors={
                        "confidence_level": row[7],
                        "data_completeness": row[8],
                        "revenue": float(row[9]) if row[9] else 0,
                        "multiplier": row[10],
                    },
                )
            )

        return targets

    def _calculate_target_score(
        self,
        valuation: Decimal,
        physician_count: int,
        commercial_payer: float,
        confidence: str,
        data_completeness: float,
    ) -> float:
        """Calculate overall target attractiveness score.

        Args:
            valuation: Practice valuation.
            physician_count: Number of physicians.
            commercial_payer: Commercial payer percentage.
            confidence: Valuation confidence level.
            data_completeness: Data completeness score.

        Returns:
            Score between 0 and 1.
        """
        score = 0.0

        # Commercial payer mix factor (0-0.3)
        score += min(commercial_payer, 0.7) * 0.43  # Max 0.3

        # Size factor - medium groups preferred (0-0.2)
        if 3 <= physician_count <= 10:
            score += 0.20
        elif 2 <= physician_count <= 20:
            score += 0.15
        elif physician_count > 20:
            score += 0.10
        else:
            score += 0.05

        # Data quality factor (0-0.2)
        score += data_completeness * 0.2

        # Confidence factor (0-0.15)
        confidence_scores = {"high": 0.15, "medium": 0.10, "low": 0.05}
        score += confidence_scores.get(confidence, 0.05)

        # Valuation size factor (0-0.15)
        val_float = float(valuation)
        if val_float >= 5000000:  # $5M+
            score += 0.15
        elif val_float >= 2000000:  # $2M+
            score += 0.12
        elif val_float >= 1000000:  # $1M+
            score += 0.08
        else:
            score += 0.05

        return min(score, 1.0)

    def get_market_opportunities(
        self,
        session: Session,
        target_states: Optional[list[str]] = None,
        target_specialties: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[MarketInsight]:
        """Identify market opportunities by geography and specialty.

        Args:
            session: SQLAlchemy session.
            target_states: States to focus on.
            target_specialties: Specialties to focus on.
            limit: Maximum results.

        Returns:
            List of MarketInsight objects.
        """
        insights = []

        # Geographic opportunities
        geo_query = """
            SELECT
                p.state,
                COUNT(DISTINCT p.id) as practice_count,
                SUM(v.valuation_amount) as total_val,
                AVG(v.valuation_amount) as avg_val,
                AVG(p.physician_count) as avg_physicians,
                AVG(p.revenue_annual / NULLIF(p.physician_count, 0)) as avg_rev_per_physician
            FROM practices p
            JOIN valuations v ON p.id = v.practice_id
            WHERE p.state IS NOT NULL
        """

        params = {}
        if target_states:
            placeholders = ", ".join(f":state_{i}" for i in range(len(target_states)))
            geo_query += f" AND p.state IN ({placeholders})"
            for i, state in enumerate(target_states):
                params[f"state_{i}"] = state

        geo_query += """
            GROUP BY p.state
            ORDER BY total_val DESC
            LIMIT :limit
        """
        params["limit"] = limit

        result = session.execute(text(geo_query), params)
        for row in result.fetchall():
            insights.append(
                MarketInsight(
                    segment_name=row[0],
                    segment_type="geographic",
                    practice_count=row[1],
                    total_valuation=Decimal(str(row[2] or 0)),
                    avg_valuation=Decimal(str(row[3] or 0)),
                    avg_physician_count=float(row[4] or 0),
                    avg_revenue_per_physician=Decimal(str(row[5] or 0)),
                    opportunity_score=self._calculate_opportunity_score(
                        row[1], float(row[2] or 0), float(row[4] or 0)
                    ),
                )
            )

        return insights

    def _calculate_opportunity_score(
        self,
        practice_count: int,
        total_valuation: float,
        avg_physicians: float,
    ) -> float:
        """Calculate market opportunity score.

        Args:
            practice_count: Number of practices in segment.
            total_valuation: Total market value.
            avg_physicians: Average practice size.

        Returns:
            Score between 0 and 1.
        """
        score = 0.0

        # Market size factor
        if total_valuation >= 100000000:  # $100M+
            score += 0.4
        elif total_valuation >= 50000000:  # $50M+
            score += 0.3
        elif total_valuation >= 10000000:  # $10M+
            score += 0.2
        else:
            score += 0.1

        # Fragmentation factor (more practices = more opportunity)
        if practice_count >= 50:
            score += 0.3
        elif practice_count >= 20:
            score += 0.2
        else:
            score += 0.1

        # Size factor (medium practices preferred)
        if 3 <= avg_physicians <= 10:
            score += 0.3
        elif 2 <= avg_physicians <= 15:
            score += 0.2
        else:
            score += 0.1

        return min(score, 1.0)

    def generate_acquisition_report(
        self,
        session: Session,
        target_market: Optional[str] = None,
    ) -> dict:
        """Generate a comprehensive acquisition opportunity report.

        Args:
            session: SQLAlchemy session.
            target_market: Specific state/market to analyze.

        Returns:
            Dictionary with report sections.
        """
        report = {}

        # Overall summary
        summary = self.get_valuation_summary(session, state=target_market)
        report["summary"] = {
            "total_practices": summary.total_practices,
            "total_market_value": float(summary.total_valuation),
            "avg_practice_value": float(summary.avg_valuation),
            "median_practice_value": float(summary.median_valuation),
        }

        # Top specialties
        report["by_specialty"] = self.get_valuation_by_specialty(session)[:10]

        # Geographic breakdown
        report["by_geography"] = self.get_valuation_by_geography(session)[:15]

        # Top targets
        targets = self.identify_high_value_practices(session, limit=20)
        report["top_targets"] = [
            {
                "practice_name": t.practice_name,
                "location": t.location,
                "specialty": t.specialty,
                "valuation": float(t.valuation),
                "target_score": t.target_score,
            }
            for t in targets
        ]

        return report
