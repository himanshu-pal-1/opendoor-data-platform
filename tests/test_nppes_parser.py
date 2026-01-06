"""Tests for the NPPES data parser.

This module tests the parsing and transformation of NPPES data
into Physician models.
"""

from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import pytest

from src.ingest.nppes.nppes_parser import NPPESParser, NPPESParseError
from src.models.physician import CredentialType


class TestNPPESParser:
    """Tests for NPPES parser functionality."""

    def test_parse_credential_md(self):
        """Test parsing M.D. credential."""
        parser = NPPESParser()
        result = parser._parse_credential("M.D.")
        assert result == CredentialType.MD

    def test_parse_credential_do(self):
        """Test parsing D.O. credential."""
        parser = NPPESParser()
        result = parser._parse_credential("D.O.")
        assert result == CredentialType.DO

    def test_parse_credential_np(self):
        """Test parsing NP credential."""
        parser = NPPESParser()
        result = parser._parse_credential("NP")
        assert result == CredentialType.NP

    def test_parse_credential_unknown(self):
        """Test parsing unknown credential."""
        parser = NPPESParser()
        result = parser._parse_credential("XYZ")
        assert result == CredentialType.OTHER

    def test_parse_credential_none(self):
        """Test parsing None credential."""
        parser = NPPESParser()
        result = parser._parse_credential(None)
        assert result is None

    def test_clean_phone_valid(self):
        """Test cleaning valid phone number."""
        parser = NPPESParser()

        assert parser._clean_phone("6175551234") == "6175551234"
        assert parser._clean_phone("(617) 555-1234") == "6175551234"
        assert parser._clean_phone("617-555-1234") == "6175551234"

    def test_clean_phone_invalid(self):
        """Test cleaning invalid phone number."""
        parser = NPPESParser()

        assert parser._clean_phone("123") is None
        assert parser._clean_phone("") is None
        assert parser._clean_phone(None) is None

    def test_clean_zip_5_digit(self):
        """Test cleaning 5-digit ZIP code."""
        parser = NPPESParser()

        assert parser._clean_zip("02101") == "02101"
        assert parser._clean_zip("02101-1234") == "02101-1234"

    def test_clean_zip_9_digit_no_dash(self):
        """Test cleaning 9-digit ZIP without dash."""
        parser = NPPESParser()

        assert parser._clean_zip("021011234") == "02101-1234"

    def test_clean_zip_invalid(self):
        """Test cleaning invalid ZIP code."""
        parser = NPPESParser()

        assert parser._clean_zip("123") is None
        assert parser._clean_zip("") is None
        assert parser._clean_zip(None) is None

    def test_parse_date_valid(self):
        """Test parsing valid date."""
        parser = NPPESParser()

        result = parser._parse_date("01/15/2020")
        assert result == date(2020, 1, 15)

    def test_parse_date_iso_format(self):
        """Test parsing ISO format date."""
        parser = NPPESParser()

        result = parser._parse_date("2020-01-15")
        assert result == date(2020, 1, 15)

    def test_parse_date_invalid(self):
        """Test parsing invalid date."""
        parser = NPPESParser()

        assert parser._parse_date("invalid") is None
        assert parser._parse_date("") is None
        assert parser._parse_date(None) is None

    def test_parse_boolean(self):
        """Test parsing boolean values."""
        parser = NPPESParser()

        assert parser._parse_boolean("Y") is True
        assert parser._parse_boolean("YES") is True
        assert parser._parse_boolean("1") is True
        assert parser._parse_boolean("N") is False
        assert parser._parse_boolean("") is False
        assert parser._parse_boolean(None) is False

    def test_row_to_physician_valid(self, nppes_sample_data):
        """Test converting valid NPPES row to Physician."""
        parser = NPPESParser()
        row = pd.Series(nppes_sample_data)

        physician = parser._row_to_physician(row)

        assert physician is not None
        assert physician.npi == "1234567890"
        assert physician.first_name == "John"
        assert physician.last_name == "Smith"
        assert physician.middle_name == "A"
        assert physician.credential == CredentialType.MD
        assert physician.practice_state == "MA"
        assert physician.practice_zip == "02101"
        assert physician.is_sole_proprietor is True

    def test_row_to_physician_missing_npi(self, nppes_sample_data):
        """Test that missing NPI returns None."""
        parser = NPPESParser()
        nppes_sample_data["NPI"] = ""
        row = pd.Series(nppes_sample_data)

        physician = parser._row_to_physician(row)

        assert physician is None

    def test_row_to_physician_missing_name(self, nppes_sample_data):
        """Test that missing name returns None."""
        parser = NPPESParser()
        nppes_sample_data["Provider First Name"] = ""
        row = pd.Series(nppes_sample_data)

        physician = parser._row_to_physician(row)

        assert physician is None

    def test_parse_file_with_sample_data(self, nppes_sample_data, tmp_path):
        """Test parsing a sample CSV file."""
        # Create a temporary CSV file
        csv_content = """NPI,Entity Type Code,Provider Last Name (Legal Name),Provider First Name,Provider Credential Text,Provider Business Practice Location Address State Name,Provider Business Practice Location Address Postal Code,Is Sole Proprietor
1234567890,1,Smith,John,M.D.,MA,02101,Y
0987654321,1,Johnson,Jane,D.O.,CA,90210,N
1111111111,2,Hospital Corp,,,,33101,N"""

        csv_file = tmp_path / "test_nppes.csv"
        csv_file.write_text(csv_content)

        parser = NPPESParser(chunk_size=100, physicians_only=True)
        physicians = list(parser.parse_file(csv_file))

        # Should only get 2 physicians (Entity Type Code = 1)
        assert len(physicians) == 2
        assert physicians[0].npi == "1234567890"
        assert physicians[1].npi == "0987654321"

    def test_parse_file_not_found(self):
        """Test that FileNotFoundError is raised for missing file."""
        parser = NPPESParser()

        with pytest.raises(NPPESParseError, match="File not found"):
            list(parser.parse_file("/nonexistent/path/file.csv"))

    def test_parse_file_to_list_with_limit(self, tmp_path):
        """Test parse_file_to_list with limit."""
        csv_content = """NPI,Entity Type Code,Provider Last Name (Legal Name),Provider First Name,Provider Credential Text
1234567890,1,Smith,John,M.D.
0987654321,1,Johnson,Jane,D.O.
1111111111,1,Williams,Bob,M.D."""

        csv_file = tmp_path / "test_nppes.csv"
        csv_file.write_text(csv_content)

        parser = NPPESParser()
        physicians = parser.parse_file_to_list(csv_file, limit=2)

        assert len(physicians) == 2
