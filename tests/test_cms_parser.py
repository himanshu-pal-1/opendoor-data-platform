"""Tests for the CMS payment data parser.

This module tests the parsing and aggregation of CMS Medicare
payment data.
"""

from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import pytest

from src.ingest.cms.cms_parser import CMSParser, CMSParseError, PhysicianPayment


class TestCMSParser:
    """Tests for CMS parser functionality."""

    def test_parse_decimal_valid(self):
        """Test parsing valid decimal values."""
        parser = CMSParser()

        assert parser._parse_decimal("1234.56") == Decimal("1234.56")
        assert parser._parse_decimal("$1,234.56") == Decimal("1234.56")
        assert parser._parse_decimal("1,000,000") == Decimal("1000000")

    def test_parse_decimal_invalid(self):
        """Test parsing invalid decimal values."""
        parser = CMSParser()

        assert parser._parse_decimal(None) is None
        assert parser._parse_decimal("") is None
        assert parser._parse_decimal(float("nan")) is None

    def test_parse_int_valid(self):
        """Test parsing valid integer values."""
        parser = CMSParser()

        assert parser._parse_int("1234") == 1234
        assert parser._parse_int("1,234") == 1234
        assert parser._parse_int("1000.0") == 1000

    def test_parse_int_invalid(self):
        """Test parsing invalid integer values."""
        parser = CMSParser()

        assert parser._parse_int(None) == 0
        assert parser._parse_int("") == 0
        assert parser._parse_int("abc") == 0

    def test_parse_physician_payments_sample(self, tmp_path):
        """Test parsing a sample CMS payment file."""
        # Create sample CMS data
        csv_content = """Rndrng_NPI,Rndrng_Prvdr_Ent_Cd,HCPCS_Cd,Tot_Srvcs,Tot_Benes,Avg_Mdcr_Pymt_Amt
1234567890,I,99213,100,75,50.00
1234567890,I,99214,50,40,75.00
0987654321,I,99213,200,150,50.00"""

        csv_file = tmp_path / "test_cms.csv"
        csv_file.write_text(csv_content)

        parser = CMSParser(chunk_size=100)
        payments = list(parser.parse_physician_payments(csv_file, 2022))

        assert len(payments) == 2

        # Check first physician aggregation
        npi_1 = next(p for p in payments if p.npi == "1234567890")
        assert npi_1.year == 2022
        assert npi_1.total_services == 150  # 100 + 50
        assert npi_1.total_beneficiaries == 115  # 75 + 40
        # Total payment: (100 * 50) + (50 * 75) = 5000 + 3750 = 8750
        assert npi_1.total_medicare_payment == Decimal("8750")

        # Check second physician
        npi_2 = next(p for p in payments if p.npi == "0987654321")
        assert npi_2.total_services == 200
        assert npi_2.total_medicare_payment == Decimal("10000")  # 200 * 50

    def test_parse_physician_payments_filters_orgs(self, tmp_path):
        """Test that organization entities are filtered out."""
        csv_content = """Rndrng_NPI,Rndrng_Prvdr_Ent_Cd,Tot_Srvcs,Tot_Benes,Avg_Mdcr_Pymt_Amt
1234567890,I,100,75,50.00
0987654321,O,200,150,50.00"""

        csv_file = tmp_path / "test_cms.csv"
        csv_file.write_text(csv_content)

        parser = CMSParser()
        payments = list(parser.parse_physician_payments(csv_file, 2022))

        assert len(payments) == 1
        assert payments[0].npi == "1234567890"

    def test_parse_physician_payments_file_not_found(self):
        """Test that missing file raises error."""
        parser = CMSParser()

        with pytest.raises(CMSParseError, match="File not found"):
            list(parser.parse_physician_payments("/nonexistent/file.csv", 2022))

    def test_service_breakdown_aggregation(self, tmp_path):
        """Test that service breakdown is correctly aggregated."""
        csv_content = """Rndrng_NPI,Rndrng_Prvdr_Ent_Cd,HCPCS_Cd,Tot_Srvcs,Tot_Benes,Avg_Mdcr_Pymt_Amt
1234567890,I,99213,100,75,50.00
1234567890,I,99214,50,40,75.00
1234567890,I,99213,25,20,50.00"""

        csv_file = tmp_path / "test_cms.csv"
        csv_file.write_text(csv_content)

        parser = CMSParser()
        payments = list(parser.parse_physician_payments(csv_file, 2022))

        assert len(payments) == 1
        payment = payments[0]

        # Check service breakdown
        assert "99213" in payment.service_breakdown
        assert "99214" in payment.service_breakdown

        # 99213: 100 + 25 = 125 services, (100*50 + 25*50) = 6250 payment
        assert payment.service_breakdown["99213"]["services"] == 125
        assert payment.service_breakdown["99213"]["payment"] == 6250.0

        # 99214: 50 services, 50*75 = 3750 payment
        assert payment.service_breakdown["99214"]["services"] == 50
        assert payment.service_breakdown["99214"]["payment"] == 3750.0

    def test_aggregate_by_practice(self, tmp_path):
        """Test aggregation of physician payments by practice."""
        csv_content = """Rndrng_NPI,Rndrng_Prvdr_Ent_Cd,Tot_Srvcs,Tot_Benes,Avg_Mdcr_Pymt_Amt
1111111111,I,100,75,50.00
2222222222,I,150,100,60.00
3333333333,I,200,150,55.00"""

        csv_file = tmp_path / "test_cms.csv"
        csv_file.write_text(csv_content)

        parser = CMSParser()
        payments = list(parser.parse_physician_payments(csv_file, 2022))

        # Map physicians 1 and 2 to same practice, 3 to different
        npi_to_practice = {
            "1111111111": "PRACTICE_A",
            "2222222222": "PRACTICE_A",
            "3333333333": "PRACTICE_B",
        }

        practice_revenues = list(parser.aggregate_by_practice(payments, npi_to_practice))

        assert len(practice_revenues) == 2

        practice_a = next(p for p in practice_revenues if p.organization_npi == "PRACTICE_A")
        assert practice_a.physician_count == 2
        # Total: (100*50) + (150*60) = 5000 + 9000 = 14000
        assert practice_a.total_medicare_revenue == Decimal("14000")
        assert practice_a.avg_revenue_per_physician == Decimal("7000")

        practice_b = next(p for p in practice_revenues if p.organization_npi == "PRACTICE_B")
        assert practice_b.physician_count == 1
        assert practice_b.total_medicare_revenue == Decimal("11000")  # 200 * 55


class TestCMSEnricher:
    """Tests for CMS data enricher."""

    def test_estimate_payer_mix_cardiology(self):
        """Test payer mix estimation for cardiology."""
        from src.ingest.cms.cms_enricher import CMSEnricher

        enricher = CMSEnricher()
        payer_mix = enricher.estimate_payer_mix(
            medicare_revenue=Decimal("500000"),
            total_revenue=None,
            specialty="cardiology",
            state="FL",
        )

        # Cardiology benchmark is 45%, FL adjusts higher
        assert 0.45 <= payer_mix["medicare"] <= 0.60
        assert payer_mix["medicare"] + payer_mix["commercial"] + payer_mix["medicaid"] + payer_mix["self_pay"] + payer_mix["other"] == pytest.approx(1.0, rel=0.01)

    def test_estimate_total_revenue(self):
        """Test total revenue estimation from Medicare."""
        from src.ingest.cms.cms_enricher import CMSEnricher

        enricher = CMSEnricher()

        medicare_revenue = Decimal("350000")
        medicare_pct = 0.35

        total = enricher.estimate_total_revenue(medicare_revenue, medicare_pct)

        assert total == Decimal("1000000")

    def test_estimate_patient_panel(self):
        """Test patient panel estimation from beneficiaries."""
        from src.ingest.cms.cms_enricher import CMSEnricher

        enricher = CMSEnricher()

        beneficiaries = 350
        medicare_pct = 0.35

        panel = enricher.estimate_patient_panel(beneficiaries, medicare_pct)

        assert panel == 1000
