"""Payer entity models.

This module defines data models for healthcare payer information,
including insurance companies, reimbursement rates, and contracts.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class PayerType(str, Enum):
    """Types of healthcare payers."""

    MEDICARE = "medicare"
    MEDICARE_ADVANTAGE = "medicare_advantage"
    MEDICAID = "medicaid"
    MEDICAID_MANAGED = "medicaid_managed"
    COMMERCIAL = "commercial"
    BCBS = "bcbs"  # Blue Cross Blue Shield
    SELF_PAY = "self_pay"
    WORKERS_COMP = "workers_comp"
    TRICARE = "tricare"
    VA = "va"
    OTHER = "other"


class ContractStatus(str, Enum):
    """Status of payer contracts."""

    ACTIVE = "active"
    PENDING = "pending"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    NEGOTIATING = "negotiating"


class Payer(BaseModel):
    """Healthcare payer/insurance company model.

    Represents a payer organization with their general information
    and reimbursement characteristics.

    Attributes:
        id: Unique payer identifier.
        name: Payer organization name.
        payer_type: Type of payer (Medicare, Commercial, etc.).
        parent_company: Parent organization name.
        states_active: List of states where payer operates.
        average_reimbursement_rate: Average rate vs Medicare benchmark.
        market_share: Estimated market share in primary regions.
        is_national: Whether payer operates nationally.

    Example:
        >>> payer = Payer(
        ...     name="Blue Cross Blue Shield of Massachusetts",
        ...     payer_type=PayerType.BCBS,
        ...     states_active=["MA", "NH", "RI"],
        ...     average_reimbursement_rate=1.15
        ... )
    """

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=300)
    payer_type: PayerType = PayerType.OTHER
    payer_id: Optional[str] = None  # External payer ID
    parent_company: Optional[str] = None

    # Geographic coverage
    states_active: list[str] = Field(default_factory=list)
    is_national: bool = False

    # Reimbursement characteristics
    average_reimbursement_rate: float = Field(
        1.0, ge=0, description="Rate relative to Medicare (1.0 = Medicare rate)"
    )
    payment_timeliness_days: Optional[int] = Field(None, ge=0)
    denial_rate: Optional[float] = Field(None, ge=0, le=1)

    # Market information
    market_share: Optional[float] = Field(None, ge=0, le=1)
    member_count: Optional[int] = Field(None, ge=0)

    # Contact
    website: Optional[str] = None
    provider_services_phone: Optional[str] = None

    model_config = {
        "str_strip_whitespace": True,
    }


class PayerContract(BaseModel):
    """Contract between a practice and a payer.

    Represents the specific terms of a contract including
    reimbursement rates for different service categories.

    Attributes:
        id: Unique contract identifier.
        payer_id: Reference to the payer.
        practice_id: Reference to the practice.
        contract_number: Contract reference number.
        status: Current contract status.
        effective_date: Contract start date.
        termination_date: Contract end date.
        rate_schedule: Reimbursement rates by service category.
        fee_schedule_type: Type of fee schedule (Medicare %, custom).
        auto_renew: Whether contract auto-renews.

    Example:
        >>> contract = PayerContract(
        ...     payer_id=payer.id,
        ...     practice_id=practice.id,
        ...     status=ContractStatus.ACTIVE,
        ...     effective_date=date(2024, 1, 1),
        ...     base_rate_multiplier=1.20
        ... )
    """

    id: UUID = Field(default_factory=uuid4)
    payer_id: UUID
    practice_id: UUID
    contract_number: Optional[str] = None

    # Contract status
    status: ContractStatus = ContractStatus.ACTIVE
    effective_date: date
    termination_date: Optional[date] = None
    auto_renew: bool = True

    # Reimbursement terms
    fee_schedule_type: str = Field(
        "medicare_percentage",
        description="medicare_percentage, custom, or rvu_based",
    )
    base_rate_multiplier: float = Field(
        1.0, ge=0, description="Multiplier vs Medicare fee schedule"
    )

    # Rate schedule by service category
    rate_schedule: dict[str, float] = Field(
        default_factory=lambda: {
            "evaluation_management": 1.0,
            "procedures": 1.0,
            "diagnostics": 1.0,
            "preventive": 1.0,
        }
    )

    # Additional terms
    value_based_component: bool = False
    quality_bonus_eligible: bool = False
    capitation_amount: Optional[Decimal] = Field(None, ge=0)

    @property
    def is_active(self) -> bool:
        """Check if contract is currently active."""
        today = date.today()
        if self.status != ContractStatus.ACTIVE:
            return False
        if self.effective_date > today:
            return False
        if self.termination_date and self.termination_date < today:
            return False
        return True

    model_config = {
        "str_strip_whitespace": True,
    }


class PayerMix(BaseModel):
    """Payer mix breakdown for a practice.

    Represents the distribution of revenue or patient volume
    across different payer types for a specific practice.

    Attributes:
        practice_id: Reference to the practice.
        period_start: Start of the measurement period.
        period_end: End of the measurement period.
        medicare_percentage: Medicare share of revenue/volume.
        medicaid_percentage: Medicaid share.
        commercial_percentage: Commercial insurance share.
        self_pay_percentage: Self-pay/cash share.
        other_percentage: Other payers share.
        measurement_type: Whether percentages are revenue or volume based.

    Example:
        >>> payer_mix = PayerMix(
        ...     practice_id=practice.id,
        ...     period_start=date(2024, 1, 1),
        ...     period_end=date(2024, 12, 31),
        ...     medicare_percentage=0.35,
        ...     commercial_percentage=0.50,
        ...     medicaid_percentage=0.10,
        ...     self_pay_percentage=0.05
        ... )
    """

    id: UUID = Field(default_factory=uuid4)
    practice_id: UUID
    period_start: date
    period_end: date
    measurement_type: str = Field(
        "revenue", description="revenue or volume based"
    )

    # Payer percentages (should sum to 1.0)
    medicare_percentage: float = Field(0.0, ge=0, le=1)
    medicare_advantage_percentage: float = Field(0.0, ge=0, le=1)
    medicaid_percentage: float = Field(0.0, ge=0, le=1)
    medicaid_managed_percentage: float = Field(0.0, ge=0, le=1)
    commercial_percentage: float = Field(0.0, ge=0, le=1)
    bcbs_percentage: float = Field(0.0, ge=0, le=1)
    self_pay_percentage: float = Field(0.0, ge=0, le=1)
    workers_comp_percentage: float = Field(0.0, ge=0, le=1)
    other_percentage: float = Field(0.0, ge=0, le=1)

    # Detailed breakdown by major payer
    payer_breakdown: dict[str, float] = Field(default_factory=dict)

    @property
    def total_government(self) -> float:
        """Total government payer percentage (Medicare + Medicaid)."""
        return (
            self.medicare_percentage
            + self.medicare_advantage_percentage
            + self.medicaid_percentage
            + self.medicaid_managed_percentage
        )

    @property
    def total_commercial(self) -> float:
        """Total commercial payer percentage."""
        return self.commercial_percentage + self.bcbs_percentage

    @property
    def payer_concentration(self) -> str:
        """Determine payer concentration type."""
        if self.total_commercial > 0.5:
            return "commercial_heavy"
        elif self.medicare_percentage + self.medicare_advantage_percentage > 0.5:
            return "medicare_heavy"
        elif self.medicaid_percentage + self.medicaid_managed_percentage > 0.5:
            return "medicaid_heavy"
        else:
            return "balanced"

    model_config = {
        "str_strip_whitespace": True,
    }
