"""Valuation API endpoints.

This module provides endpoints for calculating and retrieving
practice valuations.
"""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.models.practice import Practice, PracticeLocation, PracticeType
from src.models.valuation import ValuationMethod
from src.transform.valuation_engine import ValuationEngine
from src.utils.db_connection import get_session

router = APIRouter()


class ValuationRequest(BaseModel):
    """Request model for valuation calculation."""

    practice_name: str = Field(..., description="Practice name")
    state: str = Field(..., min_length=2, max_length=2, description="State code")
    specialty: Optional[str] = Field(None, description="Primary specialty")
    physician_count: int = Field(1, ge=1, description="Number of physicians")
    patient_panel_size: Optional[int] = Field(None, ge=0, description="Patient panel size")
    revenue_annual: Optional[float] = Field(None, ge=0, description="Annual revenue")
    ebitda: Optional[float] = Field(None, description="EBITDA")
    payer_mix_medicare: float = Field(0.35, ge=0, le=1, description="Medicare percentage")
    payer_mix_commercial: float = Field(0.50, ge=0, le=1, description="Commercial percentage")
    payer_mix_medicaid: float = Field(0.10, ge=0, le=1, description="Medicaid percentage")
    revenue_growth_rate: Optional[float] = Field(None, description="YoY revenue growth")


class ValuationResponse(BaseModel):
    """Response model for valuation calculation."""

    valuation_amount: float
    valuation_low: Optional[float] = None
    valuation_high: Optional[float] = None
    method: str
    confidence_level: str
    multipliers: dict
    breakdown: dict


class StoredValuationResponse(BaseModel):
    """Response model for stored valuation."""

    id: str
    practice_id: str
    practice_name: str
    valuation_amount: float
    valuation_low: Optional[float] = None
    valuation_high: Optional[float] = None
    method: str
    confidence_level: str
    revenue_multiple: Optional[float] = None
    calculated_at: str


def get_db():
    """Dependency to get database session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@router.post("/calculate", response_model=ValuationResponse)
async def calculate_valuation(request: ValuationRequest):
    """Calculate practice valuation based on provided metrics.

    This endpoint performs a real-time valuation calculation without
    storing the result in the database.

    Args:
        request: Valuation request with practice details.

    Returns:
        Calculated valuation with breakdown.
    """
    # Validate revenue or EBITDA is provided
    if not request.revenue_annual and not request.ebitda:
        raise HTTPException(
            status_code=400,
            detail="Either revenue_annual or ebitda must be provided",
        )

    # Build practice model
    location = PracticeLocation(
        address_line1="N/A",
        city="N/A",
        state=request.state.upper(),
        zip_code="00000",
    )

    practice = Practice(
        name=request.practice_name,
        practice_type=PracticeType.SOLO if request.physician_count == 1 else PracticeType.GROUP_SMALL,
        location=location,
        physician_count=request.physician_count,
        patient_panel_size=request.patient_panel_size,
        revenue_annual=Decimal(str(request.revenue_annual)) if request.revenue_annual else None,
        ebitda=Decimal(str(request.ebitda)) if request.ebitda else None,
        payer_mix_medicare=request.payer_mix_medicare,
        payer_mix_commercial=request.payer_mix_commercial,
        payer_mix_medicaid=request.payer_mix_medicaid,
        specialty_primary=request.specialty,
    )

    # Calculate valuation
    engine = ValuationEngine()
    result = engine.calculate_valuation(practice, request.revenue_growth_rate)

    return ValuationResponse(
        valuation_amount=float(result.valuation_amount),
        valuation_low=float(result.valuation_low) if result.valuation_low else None,
        valuation_high=float(result.valuation_high) if result.valuation_high else None,
        method=result.method.value,
        confidence_level=result.confidence_level.value,
        multipliers={
            "payer_mix": result.multipliers.payer_mix_multiplier,
            "geographic": result.multipliers.geographic_multiplier,
            "specialty": result.multipliers.specialty_multiplier,
            "size": result.multipliers.size_multiplier,
            "growth": result.multipliers.growth_multiplier,
            "combined": result.multipliers.combined_multiplier,
        },
        breakdown={
            "payer_mix_rationale": result.multipliers.payer_mix_rationale,
            "geographic_rationale": result.multipliers.geographic_rationale,
            "specialty_rationale": result.multipliers.specialty_rationale,
            "base_revenue": float(result.base_revenue) if result.base_revenue else None,
            "base_ebitda": float(result.base_ebitda) if result.base_ebitda else None,
            "revenue_multiple": result.revenue_multiple,
        },
    )


@router.get("/practice/{practice_id}", response_model=list[StoredValuationResponse])
async def get_practice_valuations(
    practice_id: str,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get valuation history for a practice.

    Args:
        practice_id: Practice UUID.
        limit: Maximum number of valuations to return.

    Returns:
        List of historical valuations.
    """
    query = text("""
        SELECT
            v.id::text,
            v.practice_id::text,
            p.name,
            v.valuation_amount,
            v.valuation_low,
            v.valuation_high,
            v.method,
            v.confidence_level,
            v.revenue_multiple,
            v.calculation_timestamp::text
        FROM valuations v
        JOIN practices p ON v.practice_id = p.id
        WHERE v.practice_id = :practice_id::uuid
        ORDER BY v.calculation_timestamp DESC
        LIMIT :limit
    """)

    result = db.execute(query, {"practice_id": practice_id, "limit": limit})
    rows = result.fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No valuations found for practice {practice_id}",
        )

    return [
        StoredValuationResponse(
            id=row[0],
            practice_id=row[1],
            practice_name=row[2],
            valuation_amount=float(row[3]),
            valuation_low=float(row[4]) if row[4] else None,
            valuation_high=float(row[5]) if row[5] else None,
            method=row[6],
            confidence_level=row[7],
            revenue_multiple=float(row[8]) if row[8] else None,
            calculated_at=row[9],
        )
        for row in rows
    ]


@router.get("/summary")
async def get_valuation_summary(
    state: Optional[str] = Query(None, description="Filter by state"),
    specialty: Optional[str] = Query(None, description="Filter by specialty"),
    db: Session = Depends(get_db),
):
    """Get summary statistics for valuations.

    Args:
        state: Optional state filter.
        specialty: Optional specialty filter.

    Returns:
        Summary statistics.
    """
    query = """
        SELECT
            COUNT(DISTINCT v.practice_id) as practice_count,
            SUM(v.valuation_amount) as total_valuation,
            AVG(v.valuation_amount) as avg_valuation,
            MIN(v.valuation_amount) as min_valuation,
            MAX(v.valuation_amount) as max_valuation,
            AVG(v.revenue_multiple) as avg_revenue_multiple
        FROM valuations v
        JOIN practices p ON v.practice_id = p.id
        WHERE 1=1
    """

    params = {}
    if state:
        query += " AND p.state = :state"
        params["state"] = state.upper()
    if specialty:
        query += " AND p.specialty_primary ILIKE :specialty"
        params["specialty"] = f"%{specialty}%"

    result = db.execute(text(query), params)
    row = result.fetchone()

    return {
        "practice_count": row[0] or 0,
        "total_valuation": float(row[1] or 0),
        "avg_valuation": float(row[2] or 0),
        "min_valuation": float(row[3] or 0),
        "max_valuation": float(row[4] or 0),
        "avg_revenue_multiple": float(row[5] or 0),
        "filters": {
            "state": state,
            "specialty": specialty,
        },
    }
