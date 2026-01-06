"""CMS data enricher.

This module enriches practice data by joining CMS payment data with
NPPES provider data and calculating revenue metrics.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.ingest.cms.cms_parser import PhysicianPayment, PracticeRevenue
from src.models.practice import Practice, PracticeLocation, PracticeType
from src.utils.db_connection import session_scope

logger = structlog.get_logger()


@dataclass
class EnrichedPractice:
    """Practice with enriched CMS payment data."""

    practice: Practice
    medicare_revenue: Decimal
    medicare_percentage: float
    estimated_total_revenue: Decimal
    patient_panel_estimate: int
    revenue_per_patient: Decimal
    data_quality_score: float


class CMSEnricher:
    """Enriches practice data with CMS payment information.

    This enricher joins CMS Medicare payment data with NPPES provider
    data to calculate practice-level revenue metrics and payer mix
    estimates.

    Attributes:
        medicare_percentage_assumption: Default Medicare % when unknown.
        revenue_per_beneficiary_estimate: Estimated revenue per patient.

    Example:
        >>> enricher = CMSEnricher()
        >>> enriched = enricher.enrich_practice(practice, payments)
        >>> print(f"Estimated revenue: ${enriched.estimated_total_revenue:,.2f}")
    """

    def __init__(
        self,
        medicare_percentage_assumption: float = 0.35,
        revenue_per_beneficiary_estimate: Decimal = Decimal("800"),
    ):
        """Initialize CMS enricher.

        Args:
            medicare_percentage_assumption: Default Medicare % if unknown.
            revenue_per_beneficiary_estimate: Estimated revenue per patient.
        """
        self.medicare_percentage_assumption = medicare_percentage_assumption
        self.revenue_per_beneficiary_estimate = revenue_per_beneficiary_estimate

    def get_physician_payments_from_db(
        self,
        session: Session,
        physician_npis: list[str],
        year: Optional[int] = None,
    ) -> dict[str, PhysicianPayment]:
        """Retrieve physician payment data from the database.

        Args:
            session: SQLAlchemy session.
            physician_npis: List of physician NPIs.
            year: Specific year (uses latest if not provided).

        Returns:
            Dictionary mapping NPI to payment data.
        """
        if not physician_npis:
            return {}

        # Build query
        npi_list = ",".join(f"'{npi}'" for npi in physician_npis)
        query = f"""
            SELECT
                physician_npi,
                year,
                total_medicare_payment,
                total_services,
                total_beneficiaries,
                avg_submitted_charge,
                avg_medicare_allowed,
                avg_medicare_payment,
                service_breakdown
            FROM cms_payments
            WHERE physician_npi IN ({npi_list})
        """

        if year:
            query += f" AND year = {year}"
        else:
            query += " ORDER BY year DESC"

        result = session.execute(text(query))
        rows = result.fetchall()

        payments = {}
        for row in rows:
            npi = row[0]
            if npi not in payments:  # Keep only latest year per NPI
                payments[npi] = PhysicianPayment(
                    npi=npi,
                    year=row[1],
                    total_medicare_payment=Decimal(str(row[2])) if row[2] else Decimal("0"),
                    total_services=row[3] or 0,
                    total_beneficiaries=row[4] or 0,
                    avg_submitted_charge=Decimal(str(row[5])) if row[5] else None,
                    avg_medicare_allowed=Decimal(str(row[6])) if row[6] else None,
                    avg_medicare_payment=Decimal(str(row[7])) if row[7] else None,
                    service_breakdown=row[8] or {},
                )

        return payments

    def estimate_payer_mix(
        self,
        medicare_revenue: Decimal,
        total_revenue: Optional[Decimal],
        specialty: Optional[str] = None,
        state: Optional[str] = None,
    ) -> dict[str, float]:
        """Estimate payer mix based on Medicare data and benchmarks.

        Args:
            medicare_revenue: Known Medicare revenue.
            total_revenue: Total revenue if known.
            specialty: Practice specialty for benchmark lookup.
            state: State for regional adjustments.

        Returns:
            Dictionary with estimated payer percentages.
        """
        # Specialty-based Medicare percentage benchmarks
        specialty_medicare_benchmarks = {
            "cardiology": 0.45,
            "primary_care": 0.35,
            "internal_medicine": 0.40,
            "family_medicine": 0.30,
            "pediatrics": 0.10,
            "orthopedic": 0.35,
            "dermatology": 0.25,
            "ophthalmology": 0.50,
            "oncology": 0.55,
            "nephrology": 0.60,
            "gastroenterology": 0.40,
        }

        # Get Medicare percentage based on specialty or use assumption
        medicare_pct = specialty_medicare_benchmarks.get(
            specialty.lower() if specialty else "",
            self.medicare_percentage_assumption,
        )

        # Adjust for states with higher Medicare populations
        high_medicare_states = ["FL", "AZ", "PA", "OH", "MI", "WV"]
        if state in high_medicare_states:
            medicare_pct *= 1.15  # 15% higher Medicare population

        medicare_pct = min(medicare_pct, 0.70)  # Cap at 70%

        # Estimate other payer percentages
        remaining = 1.0 - medicare_pct

        # Default distribution of remaining
        commercial_pct = remaining * 0.65  # 65% of remaining is commercial
        medicaid_pct = remaining * 0.20  # 20% is Medicaid
        self_pay_pct = remaining * 0.10  # 10% is self-pay
        other_pct = remaining * 0.05  # 5% is other

        return {
            "medicare": round(medicare_pct, 4),
            "commercial": round(commercial_pct, 4),
            "medicaid": round(medicaid_pct, 4),
            "self_pay": round(self_pay_pct, 4),
            "other": round(other_pct, 4),
        }

    def estimate_total_revenue(
        self,
        medicare_revenue: Decimal,
        medicare_percentage: float,
    ) -> Decimal:
        """Estimate total practice revenue from Medicare revenue.

        Args:
            medicare_revenue: Known Medicare revenue.
            medicare_percentage: Estimated Medicare % of total.

        Returns:
            Estimated total revenue.
        """
        if medicare_percentage <= 0:
            medicare_percentage = self.medicare_percentage_assumption

        return medicare_revenue / Decimal(str(medicare_percentage))

    def estimate_patient_panel(
        self,
        total_beneficiaries: int,
        medicare_percentage: float,
    ) -> int:
        """Estimate total patient panel from Medicare beneficiaries.

        Args:
            total_beneficiaries: Medicare beneficiary count.
            medicare_percentage: Estimated Medicare % of patients.

        Returns:
            Estimated total patient panel size.
        """
        if medicare_percentage <= 0:
            medicare_percentage = self.medicare_percentage_assumption

        return int(total_beneficiaries / medicare_percentage)

    def enrich_practice(
        self,
        practice: Practice,
        payments: list[PhysicianPayment],
    ) -> EnrichedPractice:
        """Enrich a practice with CMS payment data.

        Args:
            practice: Practice model to enrich.
            payments: List of physician payments for practice.

        Returns:
            EnrichedPractice with calculated metrics.
        """
        # Aggregate Medicare revenue
        total_medicare = sum(p.total_medicare_payment for p in payments)
        total_services = sum(p.total_services for p in payments)
        total_beneficiaries = sum(p.total_beneficiaries for p in payments)

        # Estimate payer mix
        payer_mix = self.estimate_payer_mix(
            total_medicare,
            practice.revenue_annual,
            practice.specialty_primary,
            practice.location.state if practice.location else None,
        )

        medicare_pct = payer_mix["medicare"]

        # Estimate total revenue
        estimated_revenue = self.estimate_total_revenue(total_medicare, medicare_pct)

        # Estimate patient panel
        estimated_panel = self.estimate_patient_panel(total_beneficiaries, medicare_pct)

        # Calculate revenue per patient
        revenue_per_patient = (
            estimated_revenue / estimated_panel
            if estimated_panel
            else self.revenue_per_beneficiary_estimate
        )

        # Calculate data quality score (0-1)
        data_quality_factors = [
            1.0 if payments else 0.0,  # Have payment data
            1.0 if total_beneficiaries > 100 else 0.5,  # Minimum sample
            1.0 if len(payments) == practice.physician_count else 0.7,  # All physicians
            1.0 if practice.specialty_primary else 0.8,  # Have specialty
        ]
        data_quality = sum(data_quality_factors) / len(data_quality_factors)

        # Update practice with enriched data
        enriched_practice = practice.model_copy()
        enriched_practice.revenue_annual = estimated_revenue
        enriched_practice.patient_panel_size = estimated_panel
        enriched_practice.payer_mix_medicare = payer_mix["medicare"]
        enriched_practice.payer_mix_commercial = payer_mix["commercial"]
        enriched_practice.payer_mix_medicaid = payer_mix["medicaid"]
        enriched_practice.payer_mix_self_pay = payer_mix["self_pay"]
        enriched_practice.payer_mix_other = payer_mix["other"]

        return EnrichedPractice(
            practice=enriched_practice,
            medicare_revenue=total_medicare,
            medicare_percentage=medicare_pct,
            estimated_total_revenue=estimated_revenue,
            patient_panel_estimate=estimated_panel,
            revenue_per_patient=revenue_per_patient,
            data_quality_score=data_quality,
        )

    def enrich_practices_batch(
        self,
        practices: list[Practice],
        session: Session,
        year: Optional[int] = None,
    ) -> list[EnrichedPractice]:
        """Enrich multiple practices with CMS data from database.

        Args:
            practices: List of practices to enrich.
            session: SQLAlchemy session.
            year: Payment data year.

        Returns:
            List of enriched practices.
        """
        enriched = []

        for practice in practices:
            # Get payments for all physicians in practice
            payments = self.get_physician_payments_from_db(
                session,
                practice.physician_npis,
                year,
            )

            payment_list = list(payments.values())
            enriched.append(self.enrich_practice(practice, payment_list))

        logger.info(
            "batch_enrichment_complete",
            practices_enriched=len(enriched),
        )

        return enriched
