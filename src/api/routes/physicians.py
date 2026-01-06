"""Physician API endpoints.

This module provides endpoints for accessing physician data.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.utils.db_connection import get_session

router = APIRouter()


class PhysicianResponse(BaseModel):
    """Response model for physician data."""

    npi: str
    first_name: str
    last_name: str
    credential: Optional[str] = None
    specialty_primary: Optional[str] = None
    specialty_description: Optional[str] = None
    practice_city: Optional[str] = None
    practice_state: Optional[str] = None
    practice_zip: Optional[str] = None
    is_sole_proprietor: bool = False

    class Config:
        from_attributes = True


class PhysicianListResponse(BaseModel):
    """Response model for physician list."""

    total: int
    items: list[PhysicianResponse]
    page: int
    page_size: int


def get_db():
    """Dependency to get database session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@router.get("/{npi}", response_model=PhysicianResponse)
async def get_physician(npi: str, db: Session = Depends(get_db)):
    """Get physician details by NPI.

    Args:
        npi: National Provider Identifier (10-digit).

    Returns:
        Physician details.

    Raises:
        HTTPException: If physician not found.
    """
    query = text("""
        SELECT
            npi, first_name, last_name, credential,
            specialty_primary, specialty_description,
            practice_city, practice_state, practice_zip,
            is_sole_proprietor
        FROM physicians
        WHERE npi = :npi
    """)

    result = db.execute(query, {"npi": npi})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Physician with NPI {npi} not found")

    return PhysicianResponse(
        npi=row[0],
        first_name=row[1],
        last_name=row[2],
        credential=row[3],
        specialty_primary=row[4],
        specialty_description=row[5],
        practice_city=row[6],
        practice_state=row[7],
        practice_zip=row[8],
        is_sole_proprietor=row[9],
    )


@router.get("/", response_model=PhysicianListResponse)
async def list_physicians(
    state: Optional[str] = Query(None, description="Filter by state"),
    specialty: Optional[str] = Query(None, description="Filter by specialty"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """List physicians with optional filters.

    Args:
        state: Filter by practice state.
        specialty: Filter by specialty (partial match).
        page: Page number (1-indexed).
        page_size: Number of items per page.

    Returns:
        Paginated list of physicians.
    """
    # Build query
    where_clauses = []
    params = {}

    if state:
        where_clauses.append("practice_state = :state")
        params["state"] = state.upper()

    if specialty:
        where_clauses.append("specialty_primary ILIKE :specialty")
        params["specialty"] = f"%{specialty}%"

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Count query
    count_query = text(f"SELECT COUNT(*) FROM physicians WHERE {where_sql}")
    total = db.execute(count_query, params).scalar()

    # Data query
    offset = (page - 1) * page_size
    params["offset"] = offset
    params["limit"] = page_size

    data_query = text(f"""
        SELECT
            npi, first_name, last_name, credential,
            specialty_primary, specialty_description,
            practice_city, practice_state, practice_zip,
            is_sole_proprietor
        FROM physicians
        WHERE {where_sql}
        ORDER BY last_name, first_name
        OFFSET :offset LIMIT :limit
    """)

    result = db.execute(data_query, params)
    rows = result.fetchall()

    items = [
        PhysicianResponse(
            npi=row[0],
            first_name=row[1],
            last_name=row[2],
            credential=row[3],
            specialty_primary=row[4],
            specialty_description=row[5],
            practice_city=row[6],
            practice_state=row[7],
            practice_zip=row[8],
            is_sole_proprietor=row[9],
        )
        for row in rows
    ]

    return PhysicianListResponse(
        total=total,
        items=items,
        page=page,
        page_size=page_size,
    )


@router.get("/search/specialty/{specialty}")
async def search_by_specialty(
    specialty: str,
    state: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Search physicians by specialty.

    Args:
        specialty: Specialty to search for.
        state: Optional state filter.
        limit: Maximum results.

    Returns:
        List of matching physicians.
    """
    query = """
        SELECT
            npi, first_name, last_name, credential,
            specialty_primary, practice_city, practice_state
        FROM physicians
        WHERE specialty_primary ILIKE :specialty
    """

    params = {"specialty": f"%{specialty}%", "limit": limit}

    if state:
        query += " AND practice_state = :state"
        params["state"] = state.upper()

    query += " ORDER BY last_name LIMIT :limit"

    result = db.execute(text(query), params)
    rows = result.fetchall()

    return {
        "count": len(rows),
        "physicians": [
            {
                "npi": row[0],
                "name": f"{row[1]} {row[2]}, {row[3] or ''}".strip(", "),
                "specialty": row[4],
                "location": f"{row[5]}, {row[6]}" if row[5] else row[6],
            }
            for row in rows
        ],
    }
