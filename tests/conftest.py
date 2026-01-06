"""Pytest configuration and fixtures.

This module provides shared fixtures for testing the OpenDoor Data Platform.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from src.models.payer import Payer, PayerMix, PayerType
from src.models.physician import CredentialType, Physician
from src.models.practice import Practice, PracticeLocation, PracticeType


@pytest.fixture
def sample_physician() -> Physician:
    """Create a sample physician for testing."""
    return Physician(
        npi="1234567890",
        first_name="John",
        last_name="Smith",
        credential=CredentialType.MD,
        specialty_primary="207R00000X",  # Internal Medicine
        specialty_description="Internal Medicine",
        gender="M",
        graduation_year=1995,
        birth_year=1965,
        practice_address_line1="123 Medical Center Dr",
        practice_city="Boston",
        practice_state="MA",
        practice_zip="02101",
        practice_phone="6175551234",
        is_sole_proprietor=True,
    )


@pytest.fixture
def sample_practice() -> Practice:
    """Create a sample practice for testing."""
    return Practice(
        id=uuid4(),
        name="Cardiology Associates of Boston",
        practice_type=PracticeType.GROUP_SMALL,
        location=PracticeLocation(
            address_line1="100 Healthcare Plaza",
            city="Boston",
            state="MA",
            zip_code="02101",
        ),
        physician_count=4,
        patient_panel_size=5000,
        revenue_annual=Decimal("3200000"),
        ebitda=Decimal("640000"),
        payer_mix_medicare=0.35,
        payer_mix_commercial=0.55,
        payer_mix_medicaid=0.05,
        payer_mix_self_pay=0.05,
        specialty_primary="cardiology",
    )


@pytest.fixture
def solo_pediatrics_practice() -> Practice:
    """Create a solo pediatrics practice for valuation testing."""
    return Practice(
        id=uuid4(),
        name="Dr. Smith Pediatrics",
        practice_type=PracticeType.SOLO,
        location=PracticeLocation(
            address_line1="456 Kids Lane",
            city="Boston",
            state="MA",
            zip_code="02101",
        ),
        physician_count=1,
        patient_panel_size=1500,
        revenue_annual=Decimal("650000"),
        ebitda=Decimal("130000"),
        payer_mix_medicare=0.05,
        payer_mix_commercial=0.60,
        payer_mix_medicaid=0.25,
        payer_mix_self_pay=0.10,
        specialty_primary="pediatrics",
    )


@pytest.fixture
def group_cardiology_practice() -> Practice:
    """Create a group cardiology practice for valuation testing."""
    return Practice(
        id=uuid4(),
        name="Dallas Cardiology Group",
        practice_type=PracticeType.GROUP_MEDIUM,
        location=PracticeLocation(
            address_line1="789 Heart Center Blvd",
            city="Dallas",
            state="TX",
            zip_code="75201",
        ),
        physician_count=8,
        patient_panel_size=3000,
        revenue_annual=Decimal("8500000"),
        ebitda=Decimal("1700000"),
        payer_mix_medicare=0.50,
        payer_mix_commercial=0.40,
        payer_mix_medicaid=0.05,
        payer_mix_self_pay=0.05,
        specialty_primary="cardiology",
    )


@pytest.fixture
def sample_payer() -> Payer:
    """Create a sample payer for testing."""
    return Payer(
        name="Blue Cross Blue Shield of Massachusetts",
        payer_type=PayerType.BCBS,
        states_active=["MA", "NH", "RI"],
        average_reimbursement_rate=1.15,
        is_national=False,
    )


@pytest.fixture
def sample_payer_mix() -> PayerMix:
    """Create a sample payer mix for testing."""
    from datetime import date

    return PayerMix(
        practice_id=uuid4(),
        period_start=date(2023, 1, 1),
        period_end=date(2023, 12, 31),
        medicare_percentage=0.35,
        commercial_percentage=0.45,
        medicaid_percentage=0.10,
        self_pay_percentage=0.10,
    )


@pytest.fixture
def nppes_sample_data() -> dict:
    """Create sample NPPES row data for parser testing."""
    return {
        "NPI": "1234567890",
        "Entity Type Code": "1",
        "Provider Last Name (Legal Name)": "Smith",
        "Provider First Name": "John",
        "Provider Middle Name": "A",
        "Provider Name Suffix Text": "Jr",
        "Provider Credential Text": "M.D.",
        "Provider First Line Business Practice Location Address": "123 Medical Dr",
        "Provider Second Line Business Practice Location Address": "Suite 100",
        "Provider Business Practice Location Address City Name": "Boston",
        "Provider Business Practice Location Address State Name": "MA",
        "Provider Business Practice Location Address Postal Code": "02101",
        "Provider Business Practice Location Address Telephone Number": "6175551234",
        "Provider Gender Code": "M",
        "Healthcare Provider Taxonomy Code_1": "207R00000X",
        "Healthcare Provider Taxonomy Code_2": "",
        "Provider Enumeration Date": "01/15/2010",
        "Last Update Date": "06/01/2023",
        "Is Sole Proprietor": "Y",
        "Is Organization Subpart": "N",
        "Provider License Number_1": "12345",
        "Provider License Number State Code_1": "MA",
    }
