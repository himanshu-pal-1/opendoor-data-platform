"""Analytics API endpoints.

This module provides endpoints for market analytics, segmentation,
and reporting.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.utils.db_connection import get_session

router = APIRouter()


class SegmentSummary(BaseModel):
    """Response model for segment summary."""

    segment_type: str
    count: int
    avg_acquisition_likelihood: float


class MarketSummary(BaseModel):
    """Response model for market summary."""

    state: str
    practice_count: int
    total_valuation: float
    avg_valuation: float
    avg_physician_count: float


def get_db():
    """Dependency to get database session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@router.get("/segments", response_model=list[SegmentSummary])
async def get_segment_summary(db: Session = Depends(get_db)):
    """Get physician segmentation summary.

    Returns summary statistics for each acquisition target segment.

    Returns:
        List of segment summaries.
    """
    query = text("""
        SELECT
            segment_type,
            COUNT(*) as count,
            AVG(acquisition_likelihood) as avg_likelihood
        FROM physician_segments
        GROUP BY segment_type
        ORDER BY avg_likelihood DESC
    """)

    result = db.execute(query)
    rows = result.fetchall()

    return [
        SegmentSummary(
            segment_type=row[0],
            count=row[1],
            avg_acquisition_likelihood=float(row[2] or 0),
        )
        for row in rows
    ]


@router.get("/segments/{segment_type}")
async def get_segment_physicians(
    segment_type: str,
    min_likelihood: float = Query(0.5, ge=0, le=1),
    state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get physicians in a specific segment.

    Args:
        segment_type: Segment type (type_1, type_2, type_3, type_4).
        min_likelihood: Minimum acquisition likelihood.
        state: Optional state filter.
        limit: Maximum results.

    Returns:
        List of physicians in segment.
    """
    query = """
        SELECT
            p.npi,
            p.first_name || ' ' || p.last_name as name,
            p.specialty_primary,
            p.practice_city,
            p.practice_state,
            s.acquisition_likelihood,
            s.segment_score
        FROM physicians p
        JOIN physician_segments s ON p.npi = s.physician_npi
        WHERE s.segment_type = :segment_type
        AND s.acquisition_likelihood >= :min_likelihood
    """

    params = {
        "segment_type": segment_type,
        "min_likelihood": min_likelihood,
        "limit": limit,
    }

    if state:
        query += " AND p.practice_state = :state"
        params["state"] = state.upper()

    query += " ORDER BY s.acquisition_likelihood DESC LIMIT :limit"

    result = db.execute(text(query), params)
    rows = result.fetchall()

    return {
        "segment_type": segment_type,
        "count": len(rows),
        "physicians": [
            {
                "npi": row[0],
                "name": row[1],
                "specialty": row[2],
                "city": row[3],
                "state": row[4],
                "acquisition_likelihood": float(row[5]),
                "segment_score": float(row[6]),
            }
            for row in rows
        ],
    }


@router.get("/market/summary", response_model=list[MarketSummary])
async def get_market_summary(
    top_n: int = Query(15, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Get market summary by state.

    Args:
        top_n: Number of top states to return.

    Returns:
        List of market summaries by state.
    """
    query = text("""
        SELECT
            p.state,
            COUNT(DISTINCT p.id) as practice_count,
            COALESCE(SUM(v.valuation_amount), 0) as total_valuation,
            COALESCE(AVG(v.valuation_amount), 0) as avg_valuation,
            AVG(p.physician_count) as avg_physicians
        FROM practices p
        LEFT JOIN valuations v ON p.id = v.practice_id
        WHERE p.state IS NOT NULL
        GROUP BY p.state
        ORDER BY total_valuation DESC
        LIMIT :limit
    """)

    result = db.execute(query, {"limit": top_n})
    rows = result.fetchall()

    return [
        MarketSummary(
            state=row[0],
            practice_count=row[1],
            total_valuation=float(row[2]),
            avg_valuation=float(row[3]),
            avg_physician_count=float(row[4] or 0),
        )
        for row in rows
    ]


@router.get("/market/specialty")
async def get_specialty_analytics(
    state: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get analytics by specialty.

    Args:
        state: Optional state filter.

    Returns:
        Analytics breakdown by specialty.
    """
    query = """
        SELECT
            p.specialty_primary,
            COUNT(DISTINCT p.id) as practice_count,
            AVG(v.valuation_amount) as avg_valuation,
            AVG(v.revenue_multiple) as avg_revenue_multiple,
            SUM(v.valuation_amount) as total_valuation
        FROM practices p
        LEFT JOIN valuations v ON p.id = v.practice_id
        WHERE p.specialty_primary IS NOT NULL
    """

    params = {}
    if state:
        query += " AND p.state = :state"
        params["state"] = state.upper()

    query += """
        GROUP BY p.specialty_primary
        ORDER BY avg_valuation DESC NULLS LAST
    """

    result = db.execute(text(query), params)
    rows = result.fetchall()

    return {
        "filter_state": state,
        "specialties": [
            {
                "specialty": row[0],
                "practice_count": row[1],
                "avg_valuation": float(row[2] or 0),
                "avg_revenue_multiple": float(row[3] or 0),
                "total_valuation": float(row[4] or 0),
            }
            for row in rows
        ],
    }


@router.get("/opportunities")
async def get_acquisition_opportunities(
    min_valuation: Optional[float] = Query(None, description="Minimum valuation"),
    min_commercial_pct: float = Query(0.4, ge=0, le=1, description="Min commercial payer %"),
    states: Optional[str] = Query(None, description="Comma-separated state codes"),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get top acquisition opportunities.

    Identifies high-value practices with attractive characteristics
    for acquisition targeting.

    Args:
        min_valuation: Minimum valuation threshold.
        min_commercial_pct: Minimum commercial payer percentage.
        states: Comma-separated list of states to filter.
        limit: Maximum results.

    Returns:
        List of acquisition opportunities.
    """
    query = """
        SELECT
            p.id::text,
            p.name,
            p.specialty_primary,
            p.city || ', ' || p.state as location,
            p.physician_count,
            v.valuation_amount,
            p.payer_mix_commercial,
            v.confidence_level,
            v.revenue_multiple
        FROM practices p
        JOIN valuations v ON p.id = v.practice_id
        WHERE p.payer_mix_commercial >= :min_commercial
    """

    params = {"min_commercial": min_commercial_pct, "limit": limit}

    if min_valuation:
        query += " AND v.valuation_amount >= :min_val"
        params["min_val"] = min_valuation

    if states:
        state_list = [s.strip().upper() for s in states.split(",")]
        placeholders = ", ".join(f":state_{i}" for i in range(len(state_list)))
        query += f" AND p.state IN ({placeholders})"
        for i, state in enumerate(state_list):
            params[f"state_{i}"] = state

    query += " ORDER BY v.valuation_amount DESC LIMIT :limit"

    result = db.execute(text(query), params)
    rows = result.fetchall()

    opportunities = []
    for row in rows:
        # Calculate opportunity score
        score = min(row[6] or 0, 0.7) * 0.43  # Commercial payer factor
        if 3 <= row[4] <= 10:
            score += 0.20
        elif row[4] >= 2:
            score += 0.15
        else:
            score += 0.10

        opportunities.append({
            "practice_id": row[0],
            "name": row[1],
            "specialty": row[2],
            "location": row[3],
            "physician_count": row[4],
            "valuation": float(row[5]),
            "commercial_payer_pct": float(row[6] or 0),
            "confidence": row[7],
            "revenue_multiple": float(row[8]) if row[8] else None,
            "opportunity_score": round(score, 2),
        })

    return {
        "count": len(opportunities),
        "filters": {
            "min_valuation": min_valuation,
            "min_commercial_pct": min_commercial_pct,
            "states": states,
        },
        "opportunities": opportunities,
    }
