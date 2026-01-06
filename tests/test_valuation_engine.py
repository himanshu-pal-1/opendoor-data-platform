"""Tests for the valuation engine.

This module tests the practice valuation calculations including
multipliers for payer mix, geography, and specialty.
"""

from decimal import Decimal

import pytest

from src.models.practice import Practice, PracticeLocation, PracticeType
from src.models.valuation import ConfidenceLevel, ValuationMethod
from src.transform.valuation_engine import ValuationEngine, calculate_valuation


class TestPayerMixMultiplier:
    """Tests for payer mix multiplier calculation."""

    def test_commercial_heavy_practice(self, sample_practice):
        """Test that commercial-heavy practices get premium multiplier."""
        engine = ValuationEngine()
        sample_practice.payer_mix_commercial = 0.70
        sample_practice.payer_mix_medicare = 0.20

        multiplier, rationale = engine.calculate_payer_mix_multiplier(sample_practice)

        assert multiplier == 1.30
        assert "Premium commercial" in rationale

    def test_medicare_heavy_practice(self, sample_practice):
        """Test that Medicare-heavy practices get neutral multiplier."""
        engine = ValuationEngine()
        sample_practice.payer_mix_commercial = 0.30
        sample_practice.payer_mix_medicare = 0.60

        multiplier, rationale = engine.calculate_payer_mix_multiplier(sample_practice)

        # 50-65% Medicare = 1.0x multiplier
        assert multiplier == 1.0
        assert "Medicare" in rationale

    def test_medicaid_heavy_practice(self, sample_practice):
        """Test that Medicaid-heavy practices get discount multiplier."""
        engine = ValuationEngine()
        sample_practice.payer_mix_commercial = 0.20
        sample_practice.payer_mix_medicare = 0.20
        sample_practice.payer_mix_medicaid = 0.55

        multiplier, rationale = engine.calculate_payer_mix_multiplier(sample_practice)

        assert multiplier == 0.80
        assert "Medicaid" in rationale

    def test_balanced_payer_mix(self, sample_practice):
        """Test balanced payer mix calculation."""
        engine = ValuationEngine()
        sample_practice.payer_mix_commercial = 0.40
        sample_practice.payer_mix_medicare = 0.40
        sample_practice.payer_mix_medicaid = 0.15

        multiplier, rationale = engine.calculate_payer_mix_multiplier(sample_practice)

        assert 0.9 <= multiplier <= 1.15
        assert "Balanced" in rationale


class TestGeographicMultiplier:
    """Tests for geographic multiplier calculation."""

    def test_high_cost_market_ca(self, sample_practice):
        """Test California gets high multiplier."""
        engine = ValuationEngine()
        sample_practice.location = PracticeLocation(
            address_line1="123 Test St",
            city="Los Angeles",
            state="CA",
            zip_code="90210",
        )

        multiplier, rationale = engine.calculate_geographic_multiplier(sample_practice)

        assert multiplier >= 1.40
        assert "high-cost" in rationale.lower()

    def test_high_cost_market_ny(self, sample_practice):
        """Test New York gets high multiplier."""
        engine = ValuationEngine()
        sample_practice.location = PracticeLocation(
            address_line1="123 Test St",
            city="New York",
            state="NY",
            zip_code="10001",
        )

        multiplier, rationale = engine.calculate_geographic_multiplier(sample_practice)

        assert multiplier >= 1.35
        assert "NY" in rationale

    def test_low_cost_market(self, sample_practice):
        """Test low-cost market gets discount multiplier."""
        engine = ValuationEngine()
        sample_practice.location = PracticeLocation(
            address_line1="123 Test St",
            city="Jackson",
            state="MS",
            zip_code="39201",
        )

        multiplier, rationale = engine.calculate_geographic_multiplier(sample_practice)

        assert multiplier <= 0.80
        assert "low-cost" in rationale.lower()

    def test_mid_cost_market(self, sample_practice):
        """Test mid-cost market gets neutral multiplier."""
        engine = ValuationEngine()
        sample_practice.location = PracticeLocation(
            address_line1="123 Test St",
            city="Dallas",
            state="TX",
            zip_code="75201",
        )

        multiplier, rationale = engine.calculate_geographic_multiplier(sample_practice)

        assert 0.95 <= multiplier <= 1.10

    def test_unknown_location(self, sample_practice):
        """Test unknown location gets default multiplier."""
        engine = ValuationEngine()
        sample_practice.location = None

        multiplier, rationale = engine.calculate_geographic_multiplier(sample_practice)

        assert multiplier == 1.0
        assert "unknown" in rationale.lower()


class TestSpecialtyMultiplier:
    """Tests for specialty multiplier calculation."""

    def test_cardiology_specialty(self, sample_practice):
        """Test cardiology gets high multiplier."""
        engine = ValuationEngine()
        sample_practice.specialty_primary = "cardiology"

        multiplier, rationale = engine.calculate_specialty_multiplier(sample_practice)

        assert multiplier >= 1.50
        assert "cardiology" in rationale.lower()

    def test_primary_care_specialty(self, sample_practice):
        """Test primary care gets standard multiplier."""
        engine = ValuationEngine()
        sample_practice.specialty_primary = "family_medicine"

        multiplier, rationale = engine.calculate_specialty_multiplier(sample_practice)

        assert 0.90 <= multiplier <= 1.0

    def test_pediatrics_specialty(self, sample_practice):
        """Test pediatrics gets lower multiplier."""
        engine = ValuationEngine()
        sample_practice.specialty_primary = "pediatrics"

        multiplier, rationale = engine.calculate_specialty_multiplier(sample_practice)

        assert multiplier <= 0.90

    def test_unknown_specialty(self, sample_practice):
        """Test unknown specialty gets default multiplier."""
        engine = ValuationEngine()
        sample_practice.specialty_primary = None

        multiplier, rationale = engine.calculate_specialty_multiplier(sample_practice)

        assert multiplier == 1.0
        assert "unknown" in rationale.lower()


class TestSizeMultiplier:
    """Tests for practice size multiplier."""

    def test_solo_practice_discount(self, sample_practice):
        """Test solo practices get discount."""
        engine = ValuationEngine()
        sample_practice.physician_count = 1

        multiplier = engine.calculate_size_multiplier(sample_practice)

        assert multiplier == 0.90

    def test_small_group_neutral(self, sample_practice):
        """Test small groups get neutral multiplier."""
        engine = ValuationEngine()
        sample_practice.physician_count = 3

        multiplier = engine.calculate_size_multiplier(sample_practice)

        assert multiplier == 1.00

    def test_large_group_premium(self, sample_practice):
        """Test large groups get premium."""
        engine = ValuationEngine()
        sample_practice.physician_count = 25

        multiplier = engine.calculate_size_multiplier(sample_practice)

        assert multiplier == 1.20


class TestFullValuation:
    """Tests for complete valuation calculation."""

    def test_solo_pediatrics_boston(self, solo_pediatrics_practice):
        """Test valuation for solo pediatrics practice in Boston.

        Expected factors:
        - Payer mix: ~1.2x (60% commercial)
        - Geographic: ~1.35x (Boston/MA)
        - Specialty: ~0.85x (pediatrics)
        - Size: 0.90x (solo)
        """
        engine = ValuationEngine()
        result = engine.calculate_valuation(solo_pediatrics_practice)

        # Check valuation is calculated
        assert result.valuation_amount > 0

        # Check multipliers are in expected ranges
        assert result.multipliers.payer_mix_multiplier >= 1.1
        assert result.multipliers.geographic_multiplier >= 1.2
        assert result.multipliers.specialty_multiplier <= 0.90
        assert result.multipliers.size_multiplier == 0.90

        # Check combined multiplier is product of individual
        expected_combined = (
            result.multipliers.payer_mix_multiplier
            * result.multipliers.geographic_multiplier
            * result.multipliers.specialty_multiplier
            * result.multipliers.size_multiplier
            * result.multipliers.growth_multiplier
            * result.multipliers.quality_multiplier
            * result.multipliers.risk_adjustment
        )
        assert abs(result.multipliers.combined_multiplier - expected_combined) < 0.01

    def test_group_cardiology_dallas(self, group_cardiology_practice):
        """Test valuation for group cardiology practice in Dallas.

        Expected factors:
        - Payer mix: ~1.14x (40% commercial, 50% Medicare - balanced mix)
        - Geographic: ~1.0-1.05x (Dallas/TX)
        - Specialty: ~1.65x (cardiology)
        - Size: 1.05x (8 physicians)
        """
        engine = ValuationEngine()
        result = engine.calculate_valuation(group_cardiology_practice)

        # Check valuation is calculated
        assert result.valuation_amount > 0

        # Check multipliers - 40% commercial gives balanced payer mix premium
        assert 1.0 <= result.multipliers.payer_mix_multiplier <= 1.20
        assert 0.95 <= result.multipliers.geographic_multiplier <= 1.10
        assert result.multipliers.specialty_multiplier >= 1.50
        assert result.multipliers.size_multiplier >= 1.05

    def test_valuation_range(self, sample_practice):
        """Test that valuation range is calculated correctly."""
        engine = ValuationEngine()
        result = engine.calculate_valuation(sample_practice, include_range=True)

        assert result.valuation_low is not None
        assert result.valuation_high is not None
        assert result.valuation_low < result.valuation_amount
        assert result.valuation_high > result.valuation_amount

    def test_confidence_level_with_complete_data(self, sample_practice):
        """Test high confidence with complete data."""
        engine = ValuationEngine()
        sample_practice.physician_npis = ["1234567890"]

        result = engine.calculate_valuation(sample_practice)

        assert result.confidence_level in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM]
        assert result.data_completeness_score >= 0.5

    def test_revenue_multiple_calculated(self, sample_practice):
        """Test that revenue multiple is calculated."""
        engine = ValuationEngine()
        result = engine.calculate_valuation(sample_practice)

        assert result.revenue_multiple is not None
        assert result.revenue_multiple > 0

    def test_convenience_function(self, sample_practice):
        """Test the convenience calculate_valuation function."""
        result = calculate_valuation(sample_practice)

        assert result.valuation_amount > 0
        assert result.method == ValuationMethod.REVENUE_MULTIPLE


class TestGrowthMultiplier:
    """Tests for growth rate multiplier."""

    def test_high_growth_premium(self):
        """Test high growth practices get premium."""
        engine = ValuationEngine()
        multiplier = engine.calculate_growth_multiplier(0.12)
        assert multiplier == 1.20

    def test_moderate_growth(self):
        """Test moderate growth gets smaller premium."""
        engine = ValuationEngine()
        multiplier = engine.calculate_growth_multiplier(0.06)
        assert multiplier == 1.10

    def test_flat_revenue(self):
        """Test flat revenue gets neutral multiplier."""
        engine = ValuationEngine()
        multiplier = engine.calculate_growth_multiplier(0.0)
        assert multiplier == 1.00

    def test_declining_revenue_discount(self):
        """Test declining revenue gets discount."""
        engine = ValuationEngine()
        multiplier = engine.calculate_growth_multiplier(-0.08)
        assert multiplier == 0.85

    def test_unknown_growth(self):
        """Test unknown growth gets neutral multiplier."""
        engine = ValuationEngine()
        multiplier = engine.calculate_growth_multiplier(None)
        assert multiplier == 1.0
