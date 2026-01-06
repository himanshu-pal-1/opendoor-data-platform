"""Valuation data models.

This module defines data models for practice valuation calculations,
including multipliers, results, and calculation metadata.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


class ConfidenceLevel(str, Enum):
    """Confidence level for valuation estimates."""

    HIGH = "high"  # >80% data completeness
    MEDIUM = "medium"  # 50-80% data completeness
    LOW = "low"  # <50% data completeness
    ESTIMATED = "estimated"  # Significant assumptions made


class ValuationMethod(str, Enum):
    """Valuation methodology used."""

    REVENUE_MULTIPLE = "revenue_multiple"
    EBITDA_MULTIPLE = "ebitda_multiple"
    DCF = "dcf"  # Discounted Cash Flow
    COMPARABLE_TRANSACTIONS = "comparable_transactions"
    HYBRID = "hybrid"


class ValuationMultipliers(BaseModel):
    """Multipliers used in practice valuation calculation.

    These multipliers adjust the base valuation based on various
    practice characteristics including payer mix, geography, and specialty.

    Attributes:
        payer_mix_multiplier: Adjustment based on payer composition.
        geographic_multiplier: Adjustment based on market/location.
        specialty_multiplier: Adjustment based on practice specialty.
        size_multiplier: Adjustment based on practice size.
        growth_multiplier: Adjustment based on revenue growth trend.
        quality_multiplier: Adjustment based on quality metrics.

    Example:
        >>> multipliers = ValuationMultipliers(
        ...     payer_mix_multiplier=1.25,  # Commercial heavy
        ...     geographic_multiplier=1.35,  # Boston market
        ...     specialty_multiplier=1.5,   # Cardiology
        ... )
    """

    payer_mix_multiplier: float = Field(1.0, ge=0.5, le=2.0)
    geographic_multiplier: float = Field(1.0, ge=0.5, le=2.0)
    specialty_multiplier: float = Field(1.0, ge=0.5, le=2.5)
    size_multiplier: float = Field(1.0, ge=0.7, le=1.5)
    growth_multiplier: float = Field(1.0, ge=0.8, le=1.5)
    quality_multiplier: float = Field(1.0, ge=0.8, le=1.3)
    risk_adjustment: float = Field(1.0, ge=0.7, le=1.0)

    # Component explanations
    payer_mix_rationale: Optional[str] = None
    geographic_rationale: Optional[str] = None
    specialty_rationale: Optional[str] = None

    @computed_field
    @property
    def combined_multiplier(self) -> float:
        """Calculate combined effect of all multipliers."""
        return (
            self.payer_mix_multiplier
            * self.geographic_multiplier
            * self.specialty_multiplier
            * self.size_multiplier
            * self.growth_multiplier
            * self.quality_multiplier
            * self.risk_adjustment
        )


class ValuationRequest(BaseModel):
    """Request parameters for practice valuation.

    Attributes:
        practice_id: Practice to value.
        method: Valuation methodology to use.
        as_of_date: Date for valuation (defaults to today).
        include_real_estate: Whether to include real estate value.
        include_equipment: Whether to include equipment value.
        custom_multipliers: Override default multipliers.
    """

    practice_id: UUID
    method: ValuationMethod = ValuationMethod.REVENUE_MULTIPLE
    as_of_date: Optional[datetime] = None
    include_real_estate: bool = False
    include_equipment: bool = False
    custom_multipliers: Optional[ValuationMultipliers] = None


class ValuationResult(BaseModel):
    """Result of a practice valuation calculation.

    Contains the calculated valuation along with all supporting
    details, multipliers used, and confidence metrics.

    Attributes:
        id: Unique valuation identifier.
        practice_id: Reference to the valued practice.
        valuation_amount: Calculated fair market value.
        valuation_low: Low end of valuation range.
        valuation_high: High end of valuation range.
        method: Methodology used for valuation.
        multipliers: Multipliers applied in calculation.
        base_revenue: Revenue used as valuation basis.
        base_ebitda: EBITDA used as valuation basis.
        revenue_multiple: Implied revenue multiple.
        ebitda_multiple: Implied EBITDA multiple.
        confidence_level: Confidence in the valuation.
        data_completeness_score: Percentage of required data available.
        calculation_timestamp: When valuation was calculated.
        assumptions: Key assumptions made.
        comparable_transactions: Similar transaction references.

    Example:
        >>> result = ValuationResult(
        ...     practice_id=practice.id,
        ...     valuation_amount=Decimal("4500000"),
        ...     valuation_low=Decimal("4000000"),
        ...     valuation_high=Decimal("5000000"),
        ...     method=ValuationMethod.REVENUE_MULTIPLE,
        ...     confidence_level=ConfidenceLevel.HIGH,
        ... )
    """

    id: UUID = Field(default_factory=uuid4)
    practice_id: UUID
    calculation_timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Valuation amounts
    valuation_amount: Decimal = Field(..., ge=0)
    valuation_low: Optional[Decimal] = Field(None, ge=0)
    valuation_high: Optional[Decimal] = Field(None, ge=0)

    # Methodology
    method: ValuationMethod
    multipliers: ValuationMultipliers

    # Basis values
    base_revenue: Optional[Decimal] = Field(None, ge=0)
    base_ebitda: Optional[Decimal] = None
    patient_panel_size: Optional[int] = Field(None, ge=0)
    revenue_per_patient: Optional[Decimal] = Field(None, ge=0)

    # Implied multiples
    revenue_multiple: Optional[float] = Field(None, ge=0)
    ebitda_multiple: Optional[float] = Field(None, ge=0)

    # Confidence metrics
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    data_completeness_score: float = Field(0.0, ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)

    # Comparable analysis
    comparable_transactions: list[dict] = Field(default_factory=list)

    # Additional components
    real_estate_value: Optional[Decimal] = Field(None, ge=0)
    equipment_value: Optional[Decimal] = Field(None, ge=0)
    goodwill_value: Optional[Decimal] = Field(None, ge=0)

    @computed_field
    @property
    def valuation_range_spread(self) -> Optional[float]:
        """Calculate the spread between high and low valuations."""
        if self.valuation_low and self.valuation_high:
            return float(
                (self.valuation_high - self.valuation_low) / self.valuation_amount
            )
        return None

    @computed_field
    @property
    def total_enterprise_value(self) -> Decimal:
        """Calculate total enterprise value including all components."""
        total = self.valuation_amount
        if self.real_estate_value:
            total += self.real_estate_value
        if self.equipment_value:
            total += self.equipment_value
        return total

    model_config = {
        "str_strip_whitespace": True,
    }
