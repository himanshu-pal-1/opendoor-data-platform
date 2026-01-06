"""Practice entity models.

This module defines data models for healthcare practice information,
including location, financial metrics, and operational details.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


class PracticeType(str, Enum):
    """Types of healthcare practices."""

    SOLO = "solo"
    GROUP_SMALL = "group_small"  # 2-5 physicians
    GROUP_MEDIUM = "group_medium"  # 6-20 physicians
    GROUP_LARGE = "group_large"  # 21+ physicians
    HOSPITAL_EMPLOYED = "hospital_employed"
    HEALTH_SYSTEM = "health_system"
    FQHC = "fqhc"  # Federally Qualified Health Center
    RHC = "rhc"  # Rural Health Clinic
    ASC = "asc"  # Ambulatory Surgery Center
    URGENT_CARE = "urgent_care"
    OTHER = "other"


class PracticeLocation(BaseModel):
    """Practice location details."""

    address_line1: str = Field(..., min_length=1, max_length=200)
    address_line2: Optional[str] = Field(None, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=2, max_length=2)
    zip_code: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    county: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    is_primary: bool = True
    is_rural: bool = False
    cbsa_code: Optional[str] = None  # Core Based Statistical Area

    @property
    def full_address(self) -> str:
        """Return full formatted address."""
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.append(f"{self.city}, {self.state} {self.zip_code}")
        return ", ".join(parts)


class Practice(BaseModel):
    """Healthcare practice entity model.

    Represents a healthcare practice with location, financial metrics,
    provider information, and payer mix details used for valuation.

    Attributes:
        id: Unique practice identifier (UUID).
        name: Practice legal name.
        dba_name: Doing business as name.
        practice_type: Type of practice (solo, group, etc.).
        tax_id: Federal Tax ID (EIN).
        organization_npi: Organization NPI (Type 2).
        location: Primary practice location.
        additional_locations: List of other locations.
        physician_count: Number of physicians.
        provider_count: Total providers including NPs, PAs.
        patient_panel_size: Active patient count.
        annual_patient_visits: Yearly visit volume.
        revenue_annual: Total annual revenue.
        revenue_per_physician: Average revenue per physician.
        ebitda: Earnings before interest, taxes, depreciation, amortization.
        ebitda_margin: EBITDA as percentage of revenue.
        payer_mix_medicare: Medicare revenue percentage.
        payer_mix_medicaid: Medicaid revenue percentage.
        payer_mix_commercial: Commercial insurance percentage.
        payer_mix_self_pay: Self-pay/cash percentage.
        specialty_primary: Primary specialty of the practice.
        specialties: List of all specialties offered.
        established_date: Date practice was established.
        physician_npis: List of affiliated physician NPIs.

    Example:
        >>> practice = Practice(
        ...     name="Cardiology Associates of Boston",
        ...     practice_type=PracticeType.GROUP_SMALL,
        ...     location=PracticeLocation(
        ...         address_line1="123 Medical Way",
        ...         city="Boston",
        ...         state="MA",
        ...         zip_code="02101"
        ...     ),
        ...     physician_count=4,
        ...     patient_panel_size=5000,
        ...     revenue_annual=Decimal("3200000"),
        ...     payer_mix_commercial=0.55
        ... )
    """

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=300)
    dba_name: Optional[str] = Field(None, max_length=300)
    practice_type: PracticeType = PracticeType.OTHER
    tax_id: Optional[str] = Field(None, pattern=r"^\d{2}-\d{7}$")
    organization_npi: Optional[str] = Field(
        None, min_length=10, max_length=10, pattern=r"^\d{10}$"
    )

    # Location
    location: Optional[PracticeLocation] = None
    additional_locations: list[PracticeLocation] = Field(default_factory=list)

    # Provider metrics
    physician_count: int = Field(1, ge=0)
    provider_count: int = Field(1, ge=0)  # Includes NPs, PAs, etc.

    # Patient metrics
    patient_panel_size: Optional[int] = Field(None, ge=0)
    annual_patient_visits: Optional[int] = Field(None, ge=0)

    # Financial metrics
    revenue_annual: Optional[Decimal] = Field(None, ge=0)
    revenue_per_physician: Optional[Decimal] = Field(None, ge=0)
    ebitda: Optional[Decimal] = None
    ebitda_margin: Optional[float] = Field(None, ge=0, le=1)
    operating_expenses: Optional[Decimal] = Field(None, ge=0)

    # Payer mix (percentages, should sum to ~1.0)
    payer_mix_medicare: float = Field(0.0, ge=0, le=1)
    payer_mix_medicaid: float = Field(0.0, ge=0, le=1)
    payer_mix_commercial: float = Field(0.0, ge=0, le=1)
    payer_mix_self_pay: float = Field(0.0, ge=0, le=1)
    payer_mix_other: float = Field(0.0, ge=0, le=1)

    # Specialty
    specialty_primary: Optional[str] = None
    specialty_description: Optional[str] = None
    specialties: list[str] = Field(default_factory=list)

    # Administrative
    established_date: Optional[date] = None
    last_verified_date: Optional[datetime] = None
    data_source: Optional[str] = None
    is_active: bool = True

    # Related entities
    physician_npis: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def total_locations(self) -> int:
        """Total number of practice locations."""
        count = 1 if self.location else 0
        return count + len(self.additional_locations)

    @computed_field
    @property
    def revenue_per_patient(self) -> Optional[Decimal]:
        """Calculate average revenue per patient."""
        if self.revenue_annual and self.patient_panel_size:
            return self.revenue_annual / self.patient_panel_size
        return None

    @computed_field
    @property
    def predominant_payer(self) -> str:
        """Determine the predominant payer type."""
        payers = {
            "medicare": self.payer_mix_medicare,
            "medicaid": self.payer_mix_medicaid,
            "commercial": self.payer_mix_commercial,
            "self_pay": self.payer_mix_self_pay,
            "other": self.payer_mix_other,
        }
        return max(payers, key=payers.get)

    @property
    def is_commercial_heavy(self) -> bool:
        """Check if practice is commercial payer heavy (>50%)."""
        return self.payer_mix_commercial > 0.5

    @property
    def is_medicare_heavy(self) -> bool:
        """Check if practice is Medicare heavy (>50%)."""
        return self.payer_mix_medicare > 0.5

    @property
    def is_medicaid_heavy(self) -> bool:
        """Check if practice is Medicaid heavy (>50%)."""
        return self.payer_mix_medicaid > 0.5

    model_config = {
        "str_strip_whitespace": True,
    }
