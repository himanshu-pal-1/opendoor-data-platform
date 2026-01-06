"""NPPES data parser.

This module handles parsing NPPES CSV files and transforming the data
into Physician models for the data platform.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Generator, Optional

import pandas as pd
import structlog

from src.models.physician import CredentialType, Physician, PhysicianLicense

logger = structlog.get_logger()

# NPPES column mappings
NPPES_COLUMNS = {
    "NPI": "npi",
    "Entity Type Code": "entity_type_code",
    "Provider Organization Name (Legal Business Name)": "organization_name",
    "Provider Last Name (Legal Name)": "last_name",
    "Provider First Name": "first_name",
    "Provider Middle Name": "middle_name",
    "Provider Name Suffix Text": "name_suffix",
    "Provider Credential Text": "credential",
    "Provider First Line Business Practice Location Address": "practice_address_line1",
    "Provider Second Line Business Practice Location Address": "practice_address_line2",
    "Provider Business Practice Location Address City Name": "practice_city",
    "Provider Business Practice Location Address State Name": "practice_state",
    "Provider Business Practice Location Address Postal Code": "practice_zip",
    "Provider Business Practice Location Address Telephone Number": "practice_phone",
    "Provider Gender Code": "gender",
    "Healthcare Provider Taxonomy Code_1": "taxonomy_code_1",
    "Healthcare Provider Taxonomy Code_2": "taxonomy_code_2",
    "Provider Enumeration Date": "enumeration_date",
    "Last Update Date": "last_update_date",
    "Is Sole Proprietor": "is_sole_proprietor",
    "Is Organization Subpart": "is_organization_subpart",
    "Parent Organization LBN": "parent_organization_name",
    "Parent Organization TIN": "parent_organization_tin",
    "Authorized Official First Name": "authorized_official_first_name",
    "Authorized Official Last Name": "authorized_official_last_name",
    "Provider License Number_1": "license_number_1",
    "Provider License Number State Code_1": "license_state_1",
}


class NPPESParseError(Exception):
    """Raised when NPPES data parsing fails."""

    pass


class NPPESParser:
    """Parser for NPPES NPI Registry CSV files.

    This parser reads large NPPES CSV files in chunks and transforms
    the data into Physician models, filtering for individual providers
    (Entity Type Code = 1).

    Attributes:
        chunk_size: Number of rows to process at a time.
        physicians_only: Whether to filter for physicians only.

    Example:
        >>> parser = NPPESParser(chunk_size=10000)
        >>> for physician in parser.parse_file("/data/nppes/npidata.csv"):
        ...     print(physician.npi, physician.full_name)
    """

    def __init__(
        self,
        chunk_size: int = 10000,
        physicians_only: bool = True,
    ):
        """Initialize NPPES parser.

        Args:
            chunk_size: Number of rows to read at a time.
            physicians_only: Filter for Entity Type Code = 1 (individuals).
        """
        self.chunk_size = chunk_size
        self.physicians_only = physicians_only

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse NPPES date string to date object.

        Args:
            date_str: Date string in MM/DD/YYYY format.

        Returns:
            Parsed date or None.
        """
        if not date_str or pd.isna(date_str):
            return None

        try:
            return datetime.strptime(str(date_str), "%m/%d/%Y").date()
        except ValueError:
            try:
                return datetime.strptime(str(date_str), "%Y-%m-%d").date()
            except ValueError:
                return None

    def _parse_credential(self, credential_str: Optional[str]) -> Optional[CredentialType]:
        """Parse credential string to CredentialType enum.

        Args:
            credential_str: Credential text from NPPES.

        Returns:
            CredentialType enum value or None.
        """
        if not credential_str or pd.isna(credential_str):
            return None

        credential_upper = str(credential_str).upper().strip()

        # Map common credential variations
        credential_map = {
            "M.D.": CredentialType.MD,
            "MD": CredentialType.MD,
            "D.O.": CredentialType.DO,
            "DO": CredentialType.DO,
            "NP": CredentialType.NP,
            "N.P.": CredentialType.NP,
            "PA": CredentialType.PA,
            "P.A.": CredentialType.PA,
            "PA-C": CredentialType.PA,
            "DPM": CredentialType.DPM,
            "D.P.M.": CredentialType.DPM,
            "DDS": CredentialType.DDS,
            "D.D.S.": CredentialType.DDS,
            "DMD": CredentialType.DMD,
            "D.M.D.": CredentialType.DMD,
            "OD": CredentialType.OD,
            "O.D.": CredentialType.OD,
            "DC": CredentialType.DC,
            "D.C.": CredentialType.DC,
            "PHD": CredentialType.PHD,
            "PH.D.": CredentialType.PHD,
        }

        for pattern, cred_type in credential_map.items():
            if pattern in credential_upper:
                return cred_type

        return CredentialType.OTHER

    def _clean_phone(self, phone: Optional[str]) -> Optional[str]:
        """Clean phone number to 10 digits.

        Args:
            phone: Raw phone number string.

        Returns:
            Cleaned 10-digit phone or None.
        """
        if not phone or pd.isna(phone):
            return None

        # Remove non-digits
        digits = "".join(c for c in str(phone) if c.isdigit())

        # Return only if we have exactly 10 digits
        if len(digits) == 10:
            return digits

        return None

    def _clean_zip(self, zip_code: Optional[str]) -> Optional[str]:
        """Clean ZIP code to valid format.

        Args:
            zip_code: Raw ZIP code string.

        Returns:
            Cleaned 5 or 9-digit ZIP or None.
        """
        if not zip_code or pd.isna(zip_code):
            return None

        zip_str = str(zip_code).strip()

        # Remove any non-alphanumeric except hyphen
        zip_clean = "".join(c for c in zip_str if c.isdigit() or c == "-")

        # Handle 9-digit ZIP
        if len(zip_clean) >= 9 and "-" not in zip_clean:
            zip_clean = zip_clean[:5] + "-" + zip_clean[5:9]

        # Validate format
        if len(zip_clean) == 5 and zip_clean.isdigit():
            return zip_clean
        elif len(zip_clean) == 10 and zip_clean[5] == "-":
            return zip_clean

        # Return just first 5 digits if available
        digits = "".join(c for c in zip_clean if c.isdigit())
        if len(digits) >= 5:
            return digits[:5]

        return None

    def _parse_boolean(self, value: Optional[str]) -> bool:
        """Parse NPPES boolean field.

        Args:
            value: String value (Y, N, X, etc.)

        Returns:
            Boolean value.
        """
        if not value or pd.isna(value):
            return False
        return str(value).upper() in ("Y", "YES", "1", "TRUE")

    def _row_to_physician(self, row: pd.Series) -> Optional[Physician]:
        """Convert a DataFrame row to a Physician model.

        Args:
            row: Pandas Series with NPPES data.

        Returns:
            Physician model or None if invalid.
        """
        try:
            npi = str(row.get("NPI", "")).strip()
            if not npi or len(npi) != 10 or not npi.isdigit():
                return None

            first_name = str(row.get("Provider First Name", "")).strip()
            last_name = str(row.get("Provider Last Name (Legal Name)", "")).strip()

            if not first_name or not last_name:
                return None

            # Build license if available
            licenses = []
            license_num = row.get("Provider License Number_1")
            license_state = row.get("Provider License Number State Code_1")
            if license_num and license_state and not pd.isna(license_num) and not pd.isna(license_state):
                try:
                    licenses.append(
                        PhysicianLicense(
                            state=str(license_state).strip()[:2],
                            license_number=str(license_num).strip(),
                        )
                    )
                except Exception:
                    pass

            physician = Physician(
                npi=npi,
                first_name=first_name,
                last_name=last_name,
                middle_name=str(row.get("Provider Middle Name", "")).strip() or None,
                name_suffix=str(row.get("Provider Name Suffix Text", "")).strip() or None,
                credential=self._parse_credential(row.get("Provider Credential Text")),
                specialty_primary=str(row.get("Healthcare Provider Taxonomy Code_1", "")).strip() or None,
                specialty_secondary=str(row.get("Healthcare Provider Taxonomy Code_2", "")).strip() or None,
                gender=str(row.get("Provider Gender Code", "")).strip() or None,
                practice_address_line1=str(
                    row.get("Provider First Line Business Practice Location Address", "")
                ).strip() or None,
                practice_address_line2=str(
                    row.get("Provider Second Line Business Practice Location Address", "")
                ).strip() or None,
                practice_city=str(
                    row.get("Provider Business Practice Location Address City Name", "")
                ).strip() or None,
                practice_state=str(
                    row.get("Provider Business Practice Location Address State Name", "")
                ).strip()[:2] if row.get("Provider Business Practice Location Address State Name") else None,
                practice_zip=self._clean_zip(
                    row.get("Provider Business Practice Location Address Postal Code")
                ),
                practice_phone=self._clean_phone(
                    row.get("Provider Business Practice Location Address Telephone Number")
                ),
                enumeration_date=self._parse_date(row.get("Provider Enumeration Date")),
                last_update_date=self._parse_date(row.get("Last Update Date")),
                is_sole_proprietor=self._parse_boolean(row.get("Is Sole Proprietor")),
                is_organization_subpart=self._parse_boolean(row.get("Is Organization Subpart")),
                licenses=licenses,
            )

            return physician

        except Exception as e:
            logger.warning("row_parse_error", error=str(e), npi=row.get("NPI"))
            return None

    def parse_file(self, file_path: Path | str) -> Generator[Physician, None, None]:
        """Parse NPPES CSV file and yield Physician models.

        Args:
            file_path: Path to NPPES CSV file.

        Yields:
            Physician models for valid records.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise NPPESParseError(f"File not found: {file_path}")

        logger.info("starting_parse", file=str(file_path), chunk_size=self.chunk_size)

        total_rows = 0
        valid_physicians = 0
        skipped_orgs = 0

        try:
            for chunk in pd.read_csv(
                file_path,
                chunksize=self.chunk_size,
                dtype=str,
                low_memory=False,
                encoding="utf-8",
                on_bad_lines="skip",
            ):
                total_rows += len(chunk)

                # Filter for individual providers (Entity Type Code = 1)
                if self.physicians_only:
                    individuals = chunk[chunk["Entity Type Code"] == "1"]
                    skipped_orgs += len(chunk) - len(individuals)
                    chunk = individuals

                for _, row in chunk.iterrows():
                    physician = self._row_to_physician(row)
                    if physician:
                        valid_physicians += 1
                        yield physician

                logger.debug(
                    "chunk_processed",
                    total_rows=total_rows,
                    valid_physicians=valid_physicians,
                )

        except Exception as e:
            logger.error("parse_error", error=str(e), file=str(file_path))
            raise NPPESParseError(f"Failed to parse NPPES file: {e}")

        logger.info(
            "parse_complete",
            total_rows=total_rows,
            valid_physicians=valid_physicians,
            skipped_organizations=skipped_orgs,
        )

    def parse_file_to_list(
        self, file_path: Path | str, limit: Optional[int] = None
    ) -> list[Physician]:
        """Parse NPPES file and return list of Physicians.

        Args:
            file_path: Path to NPPES CSV file.
            limit: Maximum number of physicians to return.

        Returns:
            List of Physician models.
        """
        physicians = []
        for physician in self.parse_file(file_path):
            physicians.append(physician)
            if limit and len(physicians) >= limit:
                break
        return physicians
