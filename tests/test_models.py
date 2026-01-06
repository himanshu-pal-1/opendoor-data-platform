"""Tests for data models.

This module tests the Pydantic data models for validation and
property calculations.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.payer import Payer, PayerContract, PayerMix, PayerType
from src.models.physician import CredentialType, Physician, PhysicianLicense
from src.models.practice import Practice, PracticeLocation, PracticeType
from src.models.valuation import (
    ConfidenceLevel,
    ValuationMethod,
    ValuationMultipliers,
    ValuationResult,
)


class TestPhysicianModel:
    """Tests for Physician model."""

    def test_valid_physician(self):
        """Test creating a valid physician."""
        physician = Physician(
            npi="1234567890",
            first_name="John",
            last_name="Smith",
            credential=CredentialType.MD,
        )

        assert physician.npi == "1234567890"
        assert physician.full_name == "John Smith"

    def test_invalid_npi_length(self):
        """Test that NPI must be 10 digits."""
        with pytest.raises(ValidationError):
            Physician(
                npi="12345",  # Too short
                first_name="John",
                last_name="Smith",
            )

    def test_invalid_npi_format(self):
        """Test that NPI must be numeric."""
        with pytest.raises(ValidationError):
            Physician(
                npi="123456789A",  # Contains letter
                first_name="John",
                last_name="Smith",
            )

    def test_full_name_with_suffix(self):
        """Test full name includes suffix."""
        physician = Physician(
            npi="1234567890",
            first_name="John",
            middle_name="A",
            last_name="Smith",
            name_suffix="Jr",
        )

        assert physician.full_name == "John A Smith Jr"

    def test_estimated_age(self):
        """Test age calculation from birth year."""
        current_year = date.today().year
        physician = Physician(
            npi="1234567890",
            first_name="John",
            last_name="Smith",
            birth_year=1970,
        )

        assert physician.estimated_age == current_year - 1970

    def test_years_since_graduation(self):
        """Test years since graduation calculation."""
        current_year = date.today().year
        physician = Physician(
            npi="1234567890",
            first_name="John",
            last_name="Smith",
            graduation_year=2000,
        )

        assert physician.years_since_graduation == current_year - 2000

    def test_state_uppercase_validation(self):
        """Test that state is converted to uppercase."""
        physician = Physician(
            npi="1234567890",
            first_name="John",
            last_name="Smith",
            practice_state="ca",
        )

        assert physician.practice_state == "CA"


class TestPracticeModel:
    """Tests for Practice model."""

    def test_valid_practice(self, sample_practice):
        """Test creating a valid practice."""
        assert sample_practice.name == "Cardiology Associates of Boston"
        assert sample_practice.practice_type == PracticeType.GROUP_SMALL

    def test_revenue_per_patient(self, sample_practice):
        """Test revenue per patient calculation."""
        expected = sample_practice.revenue_annual / sample_practice.patient_panel_size
        assert sample_practice.revenue_per_patient == expected

    def test_predominant_payer(self, sample_practice):
        """Test predominant payer determination."""
        assert sample_practice.predominant_payer == "commercial"

    def test_is_commercial_heavy(self, sample_practice):
        """Test commercial heavy flag."""
        assert sample_practice.is_commercial_heavy is True
        assert sample_practice.is_medicare_heavy is False

    def test_total_locations(self, sample_practice):
        """Test total locations count."""
        assert sample_practice.total_locations == 1

        sample_practice.additional_locations = [
            PracticeLocation(
                address_line1="456 Second St",
                city="Cambridge",
                state="MA",
                zip_code="02139",
            )
        ]

        assert sample_practice.total_locations == 2


class TestPracticeLocation:
    """Tests for PracticeLocation model."""

    def test_valid_location(self):
        """Test creating a valid location."""
        location = PracticeLocation(
            address_line1="123 Main St",
            city="Boston",
            state="MA",
            zip_code="02101",
        )

        assert location.full_address == "123 Main St, Boston, MA 02101"

    def test_full_address_with_line2(self):
        """Test full address with address line 2."""
        location = PracticeLocation(
            address_line1="123 Main St",
            address_line2="Suite 200",
            city="Boston",
            state="MA",
            zip_code="02101",
        )

        assert location.full_address == "123 Main St, Suite 200, Boston, MA 02101"

    def test_invalid_zip_format(self):
        """Test ZIP code validation."""
        with pytest.raises(ValidationError):
            PracticeLocation(
                address_line1="123 Main St",
                city="Boston",
                state="MA",
                zip_code="1234",  # Too short
            )


class TestPayerModel:
    """Tests for Payer model."""

    def test_valid_payer(self, sample_payer):
        """Test creating a valid payer."""
        assert sample_payer.name == "Blue Cross Blue Shield of Massachusetts"
        assert sample_payer.payer_type == PayerType.BCBS

    def test_default_reimbursement_rate(self):
        """Test default reimbursement rate is 1.0."""
        payer = Payer(name="Test Payer", payer_type=PayerType.COMMERCIAL)
        assert payer.average_reimbursement_rate == 1.0


class TestPayerContract:
    """Tests for PayerContract model."""

    def test_is_active_contract(self):
        """Test active contract detection."""
        contract = PayerContract(
            payer_id=uuid4(),
            practice_id=uuid4(),
            effective_date=date(2023, 1, 1),
            termination_date=date(2025, 12, 31),
        )

        assert contract.is_active is True

    def test_expired_contract(self):
        """Test expired contract detection."""
        contract = PayerContract(
            payer_id=uuid4(),
            practice_id=uuid4(),
            effective_date=date(2020, 1, 1),
            termination_date=date(2022, 12, 31),
        )

        assert contract.is_active is False


class TestPayerMix:
    """Tests for PayerMix model."""

    def test_total_government(self, sample_payer_mix):
        """Test total government payer calculation."""
        assert sample_payer_mix.total_government == 0.35

    def test_total_commercial(self, sample_payer_mix):
        """Test total commercial payer calculation."""
        assert sample_payer_mix.total_commercial == 0.45

    def test_payer_concentration(self, sample_payer_mix):
        """Test payer concentration determination."""
        assert sample_payer_mix.payer_concentration == "balanced"


class TestValuationMultipliers:
    """Tests for ValuationMultipliers model."""

    def test_combined_multiplier(self):
        """Test combined multiplier calculation."""
        multipliers = ValuationMultipliers(
            payer_mix_multiplier=1.2,
            geographic_multiplier=1.3,
            specialty_multiplier=1.5,
            size_multiplier=1.0,
            growth_multiplier=1.0,
            quality_multiplier=1.0,
            risk_adjustment=1.0,
        )

        expected = 1.2 * 1.3 * 1.5 * 1.0 * 1.0 * 1.0 * 1.0
        assert multipliers.combined_multiplier == pytest.approx(expected)


class TestValuationResult:
    """Tests for ValuationResult model."""

    def test_valuation_range_spread(self):
        """Test valuation range spread calculation."""
        result = ValuationResult(
            practice_id=uuid4(),
            valuation_amount=Decimal("1000000"),
            valuation_low=Decimal("850000"),
            valuation_high=Decimal("1150000"),
            method=ValuationMethod.REVENUE_MULTIPLE,
            multipliers=ValuationMultipliers(),
        )

        assert result.valuation_range_spread == pytest.approx(0.3)

    def test_total_enterprise_value(self):
        """Test total enterprise value with components."""
        result = ValuationResult(
            practice_id=uuid4(),
            valuation_amount=Decimal("1000000"),
            method=ValuationMethod.REVENUE_MULTIPLE,
            multipliers=ValuationMultipliers(),
            real_estate_value=Decimal("500000"),
            equipment_value=Decimal("100000"),
        )

        assert result.total_enterprise_value == Decimal("1600000")
