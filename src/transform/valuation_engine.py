"""Practice valuation engine.

This module implements the OpenDoor practice valuation formula, calculating
fair market valuations based on revenue, payer mix, geography, and specialty.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

import structlog

from src.models.practice import Practice
from src.models.valuation import (
    ConfidenceLevel,
    ValuationMethod,
    ValuationMultipliers,
    ValuationResult,
)

logger = structlog.get_logger()


# Geographic multiplier data by state/region
GEOGRAPHIC_MULTIPLIERS = {
    # High-cost areas (1.2 - 1.5x)
    "CA": 1.45,
    "NY": 1.40,
    "MA": 1.35,
    "CT": 1.30,
    "NJ": 1.30,
    "HI": 1.35,
    "AK": 1.30,
    "DC": 1.35,
    "MD": 1.25,
    "WA": 1.20,
    "OR": 1.15,
    "CO": 1.15,
    "VA": 1.15,
    # Mid-cost areas (0.9 - 1.1x)
    "IL": 1.10,
    "PA": 1.05,
    "FL": 1.05,
    "TX": 1.00,
    "AZ": 1.00,
    "GA": 0.95,
    "NC": 0.95,
    "OH": 0.90,
    "MI": 0.90,
    "MN": 1.00,
    # Low-cost areas (0.7 - 0.9x)
    "WV": 0.75,
    "MS": 0.75,
    "AR": 0.80,
    "KY": 0.80,
    "AL": 0.80,
    "LA": 0.85,
    "OK": 0.85,
    "TN": 0.85,
    "IN": 0.85,
    "MO": 0.85,
    "KS": 0.85,
    "NE": 0.85,
    "IA": 0.85,
    "SD": 0.80,
    "ND": 0.80,
    "MT": 0.85,
    "WY": 0.85,
    "ID": 0.85,
    "NM": 0.85,
    "NV": 1.00,
    "UT": 0.95,
}

# Specialty multipliers (mapped by taxonomy code prefix or specialty name)
SPECIALTY_MULTIPLIERS = {
    # High-value specialties (1.5 - 1.8x)
    "cardiology": 1.65,
    "cardiovascular": 1.60,
    "interventional_cardiology": 1.75,
    "orthopedic": 1.50,
    "orthopedics": 1.50,
    "gastroenterology": 1.45,
    "urology": 1.40,
    "neurology": 1.40,
    "dermatology": 1.35,
    "oncology": 1.50,
    "radiology": 1.30,
    "anesthesiology": 1.25,
    "ophthalmology": 1.35,
    # Medium-value specialties (1.0 - 1.3x)
    "internal_medicine": 1.00,
    "pulmonology": 1.20,
    "endocrinology": 1.15,
    "rheumatology": 1.15,
    "nephrology": 1.20,
    "psychiatry": 1.10,
    "allergy": 1.10,
    "infectious_disease": 1.05,
    "physical_medicine": 1.05,
    # Primary care (0.9 - 1.0x)
    "family_medicine": 0.95,
    "family_practice": 0.95,
    "general_practice": 0.90,
    "primary_care": 0.95,
    # Lower multiplier specialties (0.8 - 0.95x)
    "pediatrics": 0.85,
    "geriatrics": 0.90,
    "preventive_medicine": 0.90,
}

# Taxonomy code to specialty mapping (first part of taxonomy code)
TAXONOMY_TO_SPECIALTY = {
    "207R": "internal_medicine",
    "207RC": "cardiovascular",
    "207RI": "interventional_cardiology",
    "207X": "orthopedics",
    "207RG": "gastroenterology",
    "207RU": "urology",
    "207RN": "neurology",
    "207ND": "dermatology",
    "207RH": "oncology",
    "2085": "radiology",
    "207L": "anesthesiology",
    "207W": "ophthalmology",
    "207RP": "pulmonology",
    "207RE": "endocrinology",
    "207RR": "rheumatology",
    "207RK": "nephrology",
    "2084": "psychiatry",
    "207RA": "allergy",
    "207Q": "family_medicine",
    "208D": "general_practice",
    "2080": "pediatrics",
    "207RG": "geriatrics",
}


class ValuationError(Exception):
    """Raised when valuation calculation fails."""

    pass


class ValuationEngine:
    """Practice valuation calculation engine.

    Implements the OpenDoor valuation formula:
    Base Value = Avg Revenue/Patient × Patient Panel × Payer Mix Multiplier
                 × Geographic Multiplier × Specialty Multiplier

    Attributes:
        base_revenue_multiple: Default revenue multiple for valuation.
        base_ebitda_multiple: Default EBITDA multiple for valuation.

    Example:
        >>> engine = ValuationEngine()
        >>> result = engine.calculate_valuation(practice)
        >>> print(f"Valuation: ${result.valuation_amount:,.2f}")
    """

    def __init__(
        self,
        base_revenue_multiple: float = 0.8,
        base_ebitda_multiple: float = 4.0,
    ):
        """Initialize valuation engine.

        Args:
            base_revenue_multiple: Base multiple of revenue.
            base_ebitda_multiple: Base multiple of EBITDA.
        """
        self.base_revenue_multiple = base_revenue_multiple
        self.base_ebitda_multiple = base_ebitda_multiple

    def calculate_payer_mix_multiplier(
        self,
        practice: Practice,
    ) -> tuple[float, str]:
        """Calculate payer mix multiplier based on payer composition.

        Commercial-heavy practices command higher valuations due to
        better reimbursement rates and revenue stability.

        Args:
            practice: Practice with payer mix data.

        Returns:
            Tuple of (multiplier, rationale string).
        """
        commercial_pct = practice.payer_mix_commercial
        medicare_pct = practice.payer_mix_medicare
        medicaid_pct = practice.payer_mix_medicaid

        # Commercial heavy (>50%): 1.2-1.3x
        if commercial_pct > 0.5:
            if commercial_pct > 0.65:
                multiplier = 1.30
                rationale = f"Premium commercial payer mix ({commercial_pct:.0%} commercial)"
            else:
                multiplier = 1.20
                rationale = f"Strong commercial payer mix ({commercial_pct:.0%} commercial)"

        # Medicare heavy (>50%): 0.95-1.0x
        elif medicare_pct > 0.5:
            if medicare_pct > 0.65:
                multiplier = 0.95
                rationale = f"High Medicare concentration ({medicare_pct:.0%} Medicare)"
            else:
                multiplier = 1.00
                rationale = f"Medicare-focused payer mix ({medicare_pct:.0%} Medicare)"

        # Medicaid heavy (>50%): 0.7-0.8x
        elif medicaid_pct > 0.5:
            if medicaid_pct > 0.65:
                multiplier = 0.70
                rationale = f"High Medicaid concentration ({medicaid_pct:.0%} Medicaid)"
            else:
                multiplier = 0.80
                rationale = f"Medicaid-focused payer mix ({medicaid_pct:.0%} Medicaid)"

        # Balanced payer mix
        else:
            # Weight based on commercial percentage
            multiplier = 0.90 + (commercial_pct * 0.6)  # Range 0.9 to 1.2
            multiplier = min(max(multiplier, 0.90), 1.15)
            rationale = f"Balanced payer mix ({commercial_pct:.0%} commercial, {medicare_pct:.0%} Medicare)"

        return round(multiplier, 3), rationale

    def calculate_geographic_multiplier(
        self,
        practice: Practice,
    ) -> tuple[float, str]:
        """Calculate geographic multiplier based on practice location.

        High-cost markets (CA, NY, MA) command premium valuations,
        while rural/low-cost areas have lower multiples.

        Args:
            practice: Practice with location data.

        Returns:
            Tuple of (multiplier, rationale string).
        """
        state = None
        zip_code = None

        if practice.location:
            state = practice.location.state
            zip_code = practice.location.zip_code

        if not state:
            return 1.0, "Default geographic multiplier (location unknown)"

        state = state.upper()

        # Get base state multiplier
        base_multiplier = GEOGRAPHIC_MULTIPLIERS.get(state, 0.95)

        # Adjust for specific metro areas if ZIP is available
        metro_adjustments = {
            # CA metros
            ("90", "91", "92"): 0.05,  # LA area
            ("94", "95"): 0.08,  # SF Bay Area
            # NY metros
            ("10", "11"): 0.05,  # NYC area
            # MA metros
            ("02"): 0.03,  # Boston area
            # TX metros
            ("75", "76"): 0.05,  # Dallas
            ("77"): 0.05,  # Houston
            # FL metros
            ("33"): 0.03,  # Miami area
        }

        adjustment = 0
        if zip_code:
            zip_prefix = zip_code[:2]
            for prefixes, adj in metro_adjustments.items():
                if zip_prefix in prefixes:
                    adjustment = adj
                    break

        multiplier = base_multiplier + adjustment
        multiplier = min(max(multiplier, 0.70), 1.50)  # Clamp to range

        if multiplier >= 1.2:
            tier = "high-cost"
        elif multiplier >= 1.0:
            tier = "mid-cost"
        else:
            tier = "low-cost"

        rationale = f"{tier.capitalize()} market ({state}): {multiplier:.2f}x"

        return round(multiplier, 3), rationale

    def calculate_specialty_multiplier(
        self,
        practice: Practice,
    ) -> tuple[float, str]:
        """Calculate specialty multiplier based on practice specialty.

        Procedural specialties (cardiology, orthopedics, GI) command
        higher multiples than cognitive/primary care specialties.

        Args:
            practice: Practice with specialty data.

        Returns:
            Tuple of (multiplier, rationale string).
        """
        specialty = practice.specialty_primary

        if not specialty:
            return 1.0, "Default specialty multiplier (specialty unknown)"

        # Try to match specialty directly
        specialty_lower = specialty.lower().replace(" ", "_").replace("-", "_")

        if specialty_lower in SPECIALTY_MULTIPLIERS:
            multiplier = SPECIALTY_MULTIPLIERS[specialty_lower]
            rationale = f"{specialty} specialty: {multiplier:.2f}x"
            return round(multiplier, 3), rationale

        # Try taxonomy code mapping
        for prefix, spec_name in TAXONOMY_TO_SPECIALTY.items():
            if specialty.upper().startswith(prefix):
                multiplier = SPECIALTY_MULTIPLIERS.get(spec_name, 1.0)
                rationale = f"{spec_name.replace('_', ' ').title()} specialty: {multiplier:.2f}x"
                return round(multiplier, 3), rationale

        # Default for unknown specialty
        return 1.0, f"Standard specialty multiplier ({specialty})"

    def calculate_size_multiplier(
        self,
        practice: Practice,
    ) -> float:
        """Calculate size multiplier based on practice scale.

        Larger practices may command premium multiples due to
        economies of scale and reduced key-person risk.

        Args:
            practice: Practice with physician count.

        Returns:
            Size multiplier.
        """
        physician_count = practice.physician_count

        if physician_count >= 20:
            return 1.20  # Large group premium
        elif physician_count >= 10:
            return 1.10
        elif physician_count >= 5:
            return 1.05
        elif physician_count >= 2:
            return 1.00
        else:
            return 0.90  # Solo practice discount

    def calculate_growth_multiplier(
        self,
        revenue_growth_rate: Optional[float] = None,
    ) -> float:
        """Calculate growth multiplier based on revenue trend.

        Args:
            revenue_growth_rate: Annual revenue growth rate (e.g., 0.05 for 5%).

        Returns:
            Growth multiplier.
        """
        if revenue_growth_rate is None:
            return 1.0  # Neutral if unknown

        if revenue_growth_rate >= 0.10:
            return 1.20  # High growth premium
        elif revenue_growth_rate >= 0.05:
            return 1.10
        elif revenue_growth_rate >= 0.0:
            return 1.00
        elif revenue_growth_rate >= -0.05:
            return 0.95  # Slight decline
        else:
            return 0.85  # Significant decline

    def calculate_base_value(
        self,
        practice: Practice,
    ) -> Decimal:
        """Calculate base practice value from revenue metrics.

        Uses the formula:
        Base Value = Revenue Per Patient × Patient Panel Size

        Args:
            practice: Practice with revenue and patient data.

        Returns:
            Base valuation amount.
        """
        if practice.revenue_annual:
            return practice.revenue_annual * Decimal(str(self.base_revenue_multiple))

        if practice.patient_panel_size and practice.revenue_per_patient:
            base = practice.revenue_per_patient * practice.patient_panel_size
            return base * Decimal(str(self.base_revenue_multiple))

        # Fallback: estimate from EBITDA
        if practice.ebitda:
            return practice.ebitda * Decimal(str(self.base_ebitda_multiple))

        raise ValuationError("Insufficient data to calculate base value")

    def calculate_valuation(
        self,
        practice: Practice,
        revenue_growth_rate: Optional[float] = None,
        method: ValuationMethod = ValuationMethod.REVENUE_MULTIPLE,
        include_range: bool = True,
    ) -> ValuationResult:
        """Calculate complete practice valuation.

        Args:
            practice: Practice to value.
            revenue_growth_rate: Annual revenue growth rate.
            method: Valuation methodology.
            include_range: Whether to calculate valuation range.

        Returns:
            Complete ValuationResult with all details.

        Raises:
            ValuationError: If valuation cannot be calculated.
        """
        logger.info(
            "calculating_valuation",
            practice_id=str(practice.id),
            method=method.value,
        )

        # Calculate base value
        try:
            base_value = self.calculate_base_value(practice)
        except ValuationError as e:
            logger.error("base_value_error", error=str(e))
            raise

        # Calculate multipliers
        payer_mult, payer_rationale = self.calculate_payer_mix_multiplier(practice)
        geo_mult, geo_rationale = self.calculate_geographic_multiplier(practice)
        spec_mult, spec_rationale = self.calculate_specialty_multiplier(practice)
        size_mult = self.calculate_size_multiplier(practice)
        growth_mult = self.calculate_growth_multiplier(revenue_growth_rate)

        # Create multipliers object
        multipliers = ValuationMultipliers(
            payer_mix_multiplier=payer_mult,
            geographic_multiplier=geo_mult,
            specialty_multiplier=spec_mult,
            size_multiplier=size_mult,
            growth_multiplier=growth_mult,
            quality_multiplier=1.0,  # Default, could be calculated from metrics
            risk_adjustment=1.0,
            payer_mix_rationale=payer_rationale,
            geographic_rationale=geo_rationale,
            specialty_rationale=spec_rationale,
        )

        # Calculate final valuation
        combined_mult = multipliers.combined_multiplier
        valuation_amount = base_value * Decimal(str(combined_mult))

        # Calculate range if requested
        valuation_low = None
        valuation_high = None
        if include_range:
            range_factor = Decimal("0.15")  # ±15% range
            valuation_low = valuation_amount * (1 - range_factor)
            valuation_high = valuation_amount * (1 + range_factor)

        # Calculate implied multiples
        revenue_multiple = None
        ebitda_multiple = None
        if practice.revenue_annual and practice.revenue_annual > 0:
            revenue_multiple = float(valuation_amount / practice.revenue_annual)
        if practice.ebitda and practice.ebitda > 0:
            ebitda_multiple = float(valuation_amount / practice.ebitda)

        # Determine confidence level
        data_completeness = self._calculate_data_completeness(practice)
        if data_completeness >= 0.8:
            confidence = ConfidenceLevel.HIGH
        elif data_completeness >= 0.5:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        # Build assumptions list
        assumptions = []
        if not practice.revenue_annual:
            assumptions.append("Revenue estimated from patient panel and benchmarks")
        if not practice.specialty_primary:
            assumptions.append("Specialty multiplier defaulted to 1.0")
        if revenue_growth_rate is None:
            assumptions.append("Growth rate assumed neutral")

        result = ValuationResult(
            practice_id=practice.id,
            valuation_amount=valuation_amount.quantize(Decimal("0.01")),
            valuation_low=valuation_low.quantize(Decimal("0.01")) if valuation_low else None,
            valuation_high=valuation_high.quantize(Decimal("0.01")) if valuation_high else None,
            method=method,
            multipliers=multipliers,
            base_revenue=practice.revenue_annual,
            base_ebitda=practice.ebitda,
            patient_panel_size=practice.patient_panel_size,
            revenue_per_patient=practice.revenue_per_patient,
            revenue_multiple=revenue_multiple,
            ebitda_multiple=ebitda_multiple,
            confidence_level=confidence,
            data_completeness_score=data_completeness,
            assumptions=assumptions,
        )

        logger.info(
            "valuation_complete",
            practice_id=str(practice.id),
            valuation=float(valuation_amount),
            confidence=confidence.value,
            combined_multiplier=combined_mult,
        )

        return result

    def _calculate_data_completeness(self, practice: Practice) -> float:
        """Calculate data completeness score for valuation confidence.

        Args:
            practice: Practice to evaluate.

        Returns:
            Score between 0 and 1.
        """
        fields_present = 0
        total_fields = 8

        if practice.revenue_annual:
            fields_present += 1
        if practice.patient_panel_size:
            fields_present += 1
        if practice.payer_mix_commercial > 0 or practice.payer_mix_medicare > 0:
            fields_present += 1
        if practice.location and practice.location.state:
            fields_present += 1
        if practice.specialty_primary:
            fields_present += 1
        if practice.physician_count > 0:
            fields_present += 1
        if practice.ebitda:
            fields_present += 1
        if len(practice.physician_npis) > 0:
            fields_present += 1

        return fields_present / total_fields


def calculate_valuation(
    practice: Practice,
    revenue_growth_rate: Optional[float] = None,
) -> ValuationResult:
    """Convenience function to calculate practice valuation.

    Args:
        practice: Practice to value.
        revenue_growth_rate: Annual revenue growth rate.

    Returns:
        ValuationResult with calculated values.
    """
    engine = ValuationEngine()
    return engine.calculate_valuation(practice, revenue_growth_rate)
