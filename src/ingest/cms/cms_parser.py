"""CMS payment data parser.

This module handles parsing CMS Medicare payment CSV files and
transforming the data into practice revenue and payment models.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Generator, Optional

import pandas as pd
import structlog

logger = structlog.get_logger()


@dataclass
class PhysicianPayment:
    """Medicare payment data for a physician."""

    npi: str
    year: int
    total_medicare_payment: Decimal
    total_services: int
    total_beneficiaries: int
    avg_submitted_charge: Optional[Decimal]
    avg_medicare_allowed: Optional[Decimal]
    avg_medicare_payment: Optional[Decimal]
    service_breakdown: dict[str, dict]


@dataclass
class PracticeRevenue:
    """Aggregated revenue data for a practice."""

    organization_npi: Optional[str]
    physician_npis: list[str]
    year: int
    total_medicare_revenue: Decimal
    total_services: int
    total_beneficiaries: int
    physician_count: int
    avg_revenue_per_physician: Decimal
    specialty_mix: dict[str, int]


# CMS column mappings (Medicare Physician & Other Practitioners dataset)
CMS_COLUMNS = {
    "Rndrng_NPI": "npi",
    "Rndrng_Prvdr_Last_Org_Name": "last_name",
    "Rndrng_Prvdr_First_Name": "first_name",
    "Rndrng_Prvdr_Crdntls": "credentials",
    "Rndrng_Prvdr_Gndr": "gender",
    "Rndrng_Prvdr_Ent_Cd": "entity_type",
    "Rndrng_Prvdr_St1": "address_line1",
    "Rndrng_Prvdr_City": "city",
    "Rndrng_Prvdr_State_Abrvtn": "state",
    "Rndrng_Prvdr_Zip5": "zip_code",
    "Rndrng_Prvdr_Type": "provider_type",
    "Rndrng_Prvdr_Mdcr_Prtcptg_Ind": "medicare_participating",
    "HCPCS_Cd": "hcpcs_code",
    "HCPCS_Desc": "hcpcs_description",
    "HCPCS_Drug_Ind": "is_drug",
    "Place_Of_Srvc": "place_of_service",
    "Tot_Benes": "total_beneficiaries",
    "Tot_Srvcs": "total_services",
    "Tot_Bene_Day_Srvcs": "total_beneficiary_day_services",
    "Avg_Sbmtd_Chrg": "avg_submitted_charge",
    "Avg_Mdcr_Alowd_Amt": "avg_medicare_allowed",
    "Avg_Mdcr_Pymt_Amt": "avg_medicare_payment",
    "Avg_Mdcr_Stdzd_Amt": "avg_medicare_standardized",
}


class CMSParseError(Exception):
    """Raised when CMS data parsing fails."""

    pass


class CMSParser:
    """Parser for CMS Medicare payment data.

    This parser reads CMS payment CSV files and aggregates the data
    by physician NPI to calculate total Medicare payments and utilization.

    Attributes:
        chunk_size: Number of rows to process at a time.

    Example:
        >>> parser = CMSParser(chunk_size=50000)
        >>> for payment in parser.parse_physician_payments("cms_2022.csv", 2022):
        ...     print(payment.npi, payment.total_medicare_payment)
    """

    def __init__(self, chunk_size: int = 50000):
        """Initialize CMS parser.

        Args:
            chunk_size: Number of rows to read at a time.
        """
        self.chunk_size = chunk_size

    def _parse_decimal(self, value) -> Optional[Decimal]:
        """Parse value to Decimal.

        Args:
            value: Value to parse.

        Returns:
            Decimal or None.
        """
        if pd.isna(value):
            return None
        try:
            return Decimal(str(value).replace(",", "").replace("$", ""))
        except Exception:
            return None

    def _parse_int(self, value) -> int:
        """Parse value to integer.

        Args:
            value: Value to parse.

        Returns:
            Integer (0 if invalid).
        """
        if pd.isna(value):
            return 0
        try:
            return int(float(str(value).replace(",", "")))
        except Exception:
            return 0

    def parse_physician_payments(
        self,
        file_path: Path | str,
        year: int,
    ) -> Generator[PhysicianPayment, None, None]:
        """Parse CMS payment file and yield aggregated physician payments.

        This method aggregates all service lines for each physician NPI
        to calculate total Medicare payments and utilization.

        Args:
            file_path: Path to CMS payment CSV file.
            year: Data year for the file.

        Yields:
            PhysicianPayment objects with aggregated data.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise CMSParseError(f"File not found: {file_path}")

        logger.info("parsing_cms_payments", file=str(file_path), year=year)

        # Aggregate data by NPI
        npi_data: dict[str, dict] = {}

        try:
            for chunk in pd.read_csv(
                file_path,
                chunksize=self.chunk_size,
                dtype=str,
                low_memory=False,
                encoding="utf-8",
                on_bad_lines="skip",
            ):
                # Filter for individual providers
                if "Rndrng_Prvdr_Ent_Cd" in chunk.columns:
                    chunk = chunk[chunk["Rndrng_Prvdr_Ent_Cd"] == "I"]

                for _, row in chunk.iterrows():
                    npi = str(row.get("Rndrng_NPI", "")).strip()
                    if not npi or len(npi) != 10:
                        continue

                    if npi not in npi_data:
                        npi_data[npi] = {
                            "total_payment": Decimal("0"),
                            "total_services": 0,
                            "total_beneficiaries": 0,
                            "submitted_charges": [],
                            "allowed_amounts": [],
                            "payment_amounts": [],
                            "services": {},
                        }

                    # Aggregate payment data
                    services = self._parse_int(row.get("Tot_Srvcs"))
                    avg_payment = self._parse_decimal(row.get("Avg_Mdcr_Pymt_Amt"))

                    if avg_payment and services:
                        line_payment = avg_payment * services
                        npi_data[npi]["total_payment"] += line_payment
                        npi_data[npi]["total_services"] += services

                    beneficiaries = self._parse_int(row.get("Tot_Benes"))
                    npi_data[npi]["total_beneficiaries"] += beneficiaries

                    # Track submitted/allowed amounts for averaging
                    submitted = self._parse_decimal(row.get("Avg_Sbmtd_Chrg"))
                    allowed = self._parse_decimal(row.get("Avg_Mdcr_Alowd_Amt"))
                    payment = self._parse_decimal(row.get("Avg_Mdcr_Pymt_Amt"))

                    if submitted:
                        npi_data[npi]["submitted_charges"].append(
                            (submitted, services)
                        )
                    if allowed:
                        npi_data[npi]["allowed_amounts"].append((allowed, services))
                    if payment:
                        npi_data[npi]["payment_amounts"].append((payment, services))

                    # Track service breakdown
                    hcpcs = str(row.get("HCPCS_Cd", "")).strip()
                    if hcpcs:
                        if hcpcs not in npi_data[npi]["services"]:
                            npi_data[npi]["services"][hcpcs] = {
                                "services": 0,
                                "payment": Decimal("0"),
                            }
                        npi_data[npi]["services"][hcpcs]["services"] += services
                        if avg_payment and services:
                            npi_data[npi]["services"][hcpcs]["payment"] += (
                                avg_payment * services
                            )

                logger.debug("chunk_processed", npis_so_far=len(npi_data))

        except Exception as e:
            logger.error("parse_error", error=str(e), file=str(file_path))
            raise CMSParseError(f"Failed to parse CMS file: {e}")

        # Yield aggregated physician payments
        for npi, data in npi_data.items():
            # Calculate weighted averages
            avg_submitted = None
            avg_allowed = None
            avg_payment = None

            if data["submitted_charges"]:
                total_weight = sum(w for _, w in data["submitted_charges"])
                if total_weight:
                    avg_submitted = Decimal(
                        sum(v * w for v, w in data["submitted_charges"]) / total_weight
                    )

            if data["allowed_amounts"]:
                total_weight = sum(w for _, w in data["allowed_amounts"])
                if total_weight:
                    avg_allowed = Decimal(
                        sum(v * w for v, w in data["allowed_amounts"]) / total_weight
                    )

            if data["payment_amounts"]:
                total_weight = sum(w for _, w in data["payment_amounts"])
                if total_weight:
                    avg_payment = Decimal(
                        sum(v * w for v, w in data["payment_amounts"]) / total_weight
                    )

            # Convert service breakdown
            service_breakdown = {}
            for hcpcs, svc_data in data["services"].items():
                service_breakdown[hcpcs] = {
                    "services": svc_data["services"],
                    "payment": float(svc_data["payment"]),
                }

            yield PhysicianPayment(
                npi=npi,
                year=year,
                total_medicare_payment=data["total_payment"],
                total_services=data["total_services"],
                total_beneficiaries=data["total_beneficiaries"],
                avg_submitted_charge=avg_submitted,
                avg_medicare_allowed=avg_allowed,
                avg_medicare_payment=avg_payment,
                service_breakdown=service_breakdown,
            )

        logger.info(
            "parse_complete",
            total_physicians=len(npi_data),
            year=year,
        )

    def aggregate_by_practice(
        self,
        payments: list[PhysicianPayment],
        npi_to_practice: dict[str, str],
    ) -> Generator[PracticeRevenue, None, None]:
        """Aggregate physician payments by practice.

        Args:
            payments: List of physician payment records.
            npi_to_practice: Mapping of physician NPI to practice NPI.

        Yields:
            PracticeRevenue objects.
        """
        practice_data: dict[str, dict] = {}

        for payment in payments:
            practice_npi = npi_to_practice.get(payment.npi)

            # Use physician NPI as practice key if no mapping
            practice_key = practice_npi or payment.npi

            if practice_key not in practice_data:
                practice_data[practice_key] = {
                    "organization_npi": practice_npi,
                    "physician_npis": [],
                    "year": payment.year,
                    "total_revenue": Decimal("0"),
                    "total_services": 0,
                    "total_beneficiaries": 0,
                }

            practice_data[practice_key]["physician_npis"].append(payment.npi)
            practice_data[practice_key]["total_revenue"] += payment.total_medicare_payment
            practice_data[practice_key]["total_services"] += payment.total_services
            practice_data[practice_key]["total_beneficiaries"] += payment.total_beneficiaries

        for practice_key, data in practice_data.items():
            physician_count = len(data["physician_npis"])
            avg_per_physician = (
                data["total_revenue"] / physician_count if physician_count else Decimal("0")
            )

            yield PracticeRevenue(
                organization_npi=data["organization_npi"],
                physician_npis=data["physician_npis"],
                year=data["year"],
                total_medicare_revenue=data["total_revenue"],
                total_services=data["total_services"],
                total_beneficiaries=data["total_beneficiaries"],
                physician_count=physician_count,
                avg_revenue_per_physician=avg_per_physician,
                specialty_mix={},  # Would need specialty data to populate
            )
