"""Practice API endpoints.

This module provides endpoints for accessing practice data.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.utils.db_connection import get_session

router = APIRouter()


class PracticeResponse(BaseModel):
    """Response model for practice data."""

    id: str
    name: str
    practice_type: Optional[str] = None
    specialty_primary: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    physician_count: int = 1
    patient_panel_size: Optional[int] = None
    revenue_annual: Optional[float] = None
    payer_mix_medicare: Optional[float] = None
    payer_mix_commercial: Optional[float] = None

    class Config:
        from_attributes = True


class PracticeListResponse(BaseModel):
    """Response model for practice list."""

    total: int
    items: list[PracticeResponse]
    page: int
    page_size: int


def get_db():
    """Dependency to get database session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@router.get("/{practice_id}", response_model=PracticeResponse)
async def get_practice(practice_id: str, db: Session = Depends(get_db)):
    """Get practice details by ID.

    Args:
        practice_id: Practice UUID.

    Returns:
        Practice details.

    Raises:
        HTTPException: If practice not found.
    """
    query = text("""
        SELECT
            id::text, name, practice_type, specialty_primary,
            city, state, zip_code, physician_count,
            patient_panel_size, revenue_annual,
            payer_mix_medicare, payer_mix_commercial
        FROM practices
        WHERE id = :practice_id::uuid
    """)

    result = db.execute(query, {"practice_id": practice_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")

    return PracticeResponse(
        id=row[0],
        name=row[1],
        practice_type=row[2],
        specialty_primary=row[3],
        city=row[4],
        state=row[5],
        zip_code=row[6],
        physician_count=row[7],
        patient_panel_size=row[8],
        revenue_annual=float(row[9]) if row[9] else None,
        payer_mix_medicare=float(row[10]) if row[10] else None,
        payer_mix_commercial=float(row[11]) if row[11] else None,
    )


@router.get("/", response_model=PracticeListResponse)
async def list_practices(
    state: Optional[str] = Query(None, description="Filter by state"),
    specialty: Optional[str] = Query(None, description="Filter by specialty"),
    practice_type: Optional[str] = Query(None, description="Filter by practice type"),
    min_revenue: Optional[float] = Query(None, description="Minimum annual revenue"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """List practices with optional filters.

    Args:
        state: Filter by state.
        specialty: Filter by specialty (partial match).
        practice_type: Filter by practice type.
        min_revenue: Minimum annual revenue filter.
        page: Page number (1-indexed).
        page_size: Number of items per page.

    Returns:
        Paginated list of practices.
    """
    where_clauses = []
    params = {}

    if state:
        where_clauses.append("state = :state")
        params["state"] = state.upper()

    if specialty:
        where_clauses.append("specialty_primary ILIKE :specialty")
        params["specialty"] = f"%{specialty}%"

    if practice_type:
        where_clauses.append("practice_type = :practice_type")
        params["practice_type"] = practice_type

    if min_revenue:
        where_clauses.append("revenue_annual >= :min_revenue")
        params["min_revenue"] = min_revenue

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Count query
    count_query = text(f"SELECT COUNT(*) FROM practices WHERE {where_sql}")
    total = db.execute(count_query, params).scalar()

    # Data query
    offset = (page - 1) * page_size
    params["offset"] = offset
    params["limit"] = page_size

    data_query = text(f"""
        SELECT
            id::text, name, practice_type, specialty_primary,
            city, state, zip_code, physician_count,
            patient_panel_size, revenue_annual,
            payer_mix_medicare, payer_mix_commercial
        FROM practices
        WHERE {where_sql}
        ORDER BY revenue_annual DESC NULLS LAST
        OFFSET :offset LIMIT :limit
    """)

    result = db.execute(data_query, params)
    rows = result.fetchall()

    items = [
        PracticeResponse(
            id=row[0],
            name=row[1],
            practice_type=row[2],
            specialty_primary=row[3],
            city=row[4],
            state=row[5],
            zip_code=row[6],
            physician_count=row[7],
            patient_panel_size=row[8],
            revenue_annual=float(row[9]) if row[9] else None,
            payer_mix_medicare=float(row[10]) if row[10] else None,
            payer_mix_commercial=float(row[11]) if row[11] else None,
        )
        for row in rows
    ]

    return PracticeListResponse(
        total=total,
        items=items,
        page=page,
        page_size=page_size,
    )


@router.get("/search/location")
async def search_by_location(
    state: str = Query(..., description="State code"),
    city: Optional[str] = Query(None, description="City name"),
    zip_prefix: Optional[str] = Query(None, description="ZIP code prefix"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Search practices by location.

    Args:
        state: State code (required).
        city: City name (optional).
        zip_prefix: ZIP code prefix (optional).
        limit: Maximum results.

    Returns:
        List of matching practices.
    """
    query = "SELECT id::text, name, city, state, zip_code, specialty_primary FROM practices WHERE state = :state"
    params = {"state": state.upper(), "limit": limit}

    if city:
        query += " AND city ILIKE :city"
        params["city"] = f"%{city}%"

    if zip_prefix:
        query += " AND zip_code LIKE :zip"
        params["zip"] = f"{zip_prefix}%"

    query += " ORDER BY name LIMIT :limit"

    result = db.execute(text(query), params)
    rows = result.fetchall()

    return {
        "count": len(rows),
        "practices": [
            {
                "id": row[0],
                "name": row[1],
                "city": row[2],
                "state": row[3],
                "zip_code": row[4],
                "specialty": row[5],
            }
            for row in rows
        ],
    }
