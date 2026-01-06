"""Physician entity models.

This module defines data models for physician information sourced from
NPPES, PECOS, and other provider data sources.
"""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CredentialType(str, Enum):
    """Physician credential types."""

    MD = "MD"
    DO = "DO"
    NP = "NP"
    PA = "PA"
    DPM = "DPM"
    DDS = "DDS"
    DMD = "DMD"
    OD = "OD"
    DC = "DC"
    PHD = "PHD"
    OTHER = "OTHER"


class PhysicianCredentials(BaseModel):
    """Physician credentials and certifications."""

    credential_type: CredentialType
    board_certified: bool = False
    board_specialty: Optional[str] = None
    certification_date: Optional[date] = None
    certification_expiry: Optional[date] = None


class PhysicianLicense(BaseModel):
    """State medical license information."""

    state: str = Field(..., min_length=2, max_length=2)
    license_number: str
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: bool = True

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Ensure state is uppercase."""
        return v.upper()


class Physician(BaseModel):
    """Physician entity model.

    Represents a healthcare provider with their NPI, demographic information,
    specialty, and practice details sourced from NPPES and enriched with
    other data sources.

    Attributes:
        npi: National Provider Identifier (10-digit unique ID).
        first_name: Physician's first name.
        last_name: Physician's last name.
        middle_name: Physician's middle name (optional).
        name_suffix: Name suffix (Jr., III, etc.).
        credential: Primary credential (MD, DO, etc.).
        specialty_primary: Primary taxonomy/specialty code.
        specialty_secondary: Secondary specialty (optional).
        gender: Gender (M, F, or None if unknown).
        graduation_year: Medical school graduation year.
        birth_year: Birth year (for age calculation).
        practice_address_line1: Primary practice address line 1.
        practice_address_line2: Primary practice address line 2.
        practice_city: Practice city.
        practice_state: Practice state (2-letter code).
        practice_zip: Practice ZIP code (5 or 9 digit).
        practice_phone: Practice phone number.
        enumeration_date: Date NPI was assigned.
        last_update_date: Date of last NPPES update.
        is_sole_proprietor: Whether physician is sole proprietor.
        is_organization_subpart: Whether part of an organization.
        parent_organization_npi: NPI of parent organization.
        licenses: List of state licenses.
        credentials: List of credentials/certifications.

    Example:
        >>> physician = Physician(
        ...     npi="1234567890",
        ...     first_name="John",
        ...     last_name="Smith",
        ...     credential=CredentialType.MD,
        ...     specialty_primary="207R00000X",
        ...     practice_state="CA",
        ...     practice_zip="90210"
        ... )
    """

    npi: str = Field(..., min_length=10, max_length=10, pattern=r"^\d{10}$")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    middle_name: Optional[str] = Field(None, max_length=100)
    name_suffix: Optional[str] = Field(None, max_length=20)
    credential: Optional[CredentialType] = None

    # Specialty information
    specialty_primary: Optional[str] = Field(
        None, description="Primary taxonomy code (e.g., 207R00000X)"
    )
    specialty_secondary: Optional[str] = None
    specialty_description: Optional[str] = None

    # Demographics
    gender: Optional[str] = Field(None, pattern=r"^[MF]$")
    graduation_year: Optional[int] = Field(None, ge=1950, le=2030)
    birth_year: Optional[int] = Field(None, ge=1920, le=2010)

    # Practice location
    practice_address_line1: Optional[str] = Field(None, max_length=200)
    practice_address_line2: Optional[str] = Field(None, max_length=200)
    practice_city: Optional[str] = Field(None, max_length=100)
    practice_state: Optional[str] = Field(None, min_length=2, max_length=2)
    practice_zip: Optional[str] = Field(None, pattern=r"^\d{5}(-\d{4})?$")
    practice_phone: Optional[str] = Field(None, pattern=r"^\d{10}$")

    # Administrative
    enumeration_date: Optional[date] = None
    last_update_date: Optional[date] = None
    is_sole_proprietor: bool = False
    is_organization_subpart: bool = False
    parent_organization_npi: Optional[str] = None

    # Related entities
    licenses: list[PhysicianLicense] = Field(default_factory=list)
    credentials: list[PhysicianCredentials] = Field(default_factory=list)

    @field_validator("practice_state")
    @classmethod
    def validate_practice_state(cls, v: Optional[str]) -> Optional[str]:
        """Ensure state is uppercase."""
        return v.upper() if v else None

    @property
    def full_name(self) -> str:
        """Return the physician's full name."""
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        if self.name_suffix:
            parts.append(self.name_suffix)
        return " ".join(parts)

    @property
    def estimated_age(self) -> Optional[int]:
        """Estimate current age from birth year."""
        if self.birth_year:
            return date.today().year - self.birth_year
        return None

    @property
    def years_since_graduation(self) -> Optional[int]:
        """Calculate years since medical school graduation."""
        if self.graduation_year:
            return date.today().year - self.graduation_year
        return None

    model_config = {
        "str_strip_whitespace": True,
    }
