"""
Unit tests for data normalization module (src/normalization.py).
"""

import pytest
from src.normalization import (
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_record,
    normalize_dataframe
)
import pandas as pd


class TestEmailNormalization:
    def test_lowercase_conversion(self):
        assert normalize_email("SACHIN@GMAIL.COM") == "sachin@gmail.com"
        assert normalize_email("John.Doe@Example.COM") == "john.doe@example.com"

    def test_whitespace_trimming(self):
        assert normalize_email("  user@domain.com  ") == "user@domain.com"
        assert normalize_email("\tuser@domain.com\n") == "user@domain.com"

    def test_empty_and_null_values(self):
        assert normalize_email(None) is None
        assert normalize_email("") is None
        assert normalize_email("   ") is None
        assert normalize_email("nan") is None
        assert normalize_email("null") is None


class TestNameNormalization:
    def test_whitespace_collapsing(self):
        assert normalize_name("  sachin   jadhav  ") == "Sachin Jadhav"
        assert normalize_name("rahul\t\tpatil") == "Rahul Patil"

    def test_title_casing(self):
        assert normalize_name("john doe") == "John Doe"
        assert normalize_name("ANITA SHARMA") == "Anita Sharma"

    def test_empty_and_null_names(self):
        assert normalize_name(None) is None
        assert normalize_name("") is None
        assert normalize_name("   ") is None


class TestPhoneNormalization:
    def test_clean_10_digit(self):
        assert normalize_phone("9876543210") == "9876543210"

    def test_strip_formatting_characters(self):
        assert normalize_phone("(987) 654-3210") == "9876543210"
        assert normalize_phone("987-654-3210") == "9876543210"
        assert normalize_phone("987.654.3210") == "9876543210"

    def test_international_prefix_handling(self):
        assert normalize_phone("+91 9876543210") == "9876543210"
        assert normalize_phone("+1 9876543210") == "9876543210"
        assert normalize_phone("09876543210") == "9876543210"

    def test_empty_and_null_phones(self):
        assert normalize_phone(None) is None
        assert normalize_phone("") is None
        assert normalize_phone("N/A") is None


class TestRecordAndDataframeNormalization:
    def test_normalize_record_dict(self):
        rec = {
            "full_name": "  rahul   patil  ",
            "email": " RAHUL.PATIL@GMAIL.COM ",
            "phone": "+91 9123456780"
        }
        norm = normalize_record(rec)
        assert norm["normalized_name"] == "Rahul Patil"
        assert norm["normalized_email"] == "rahul.patil@gmail.com"
        assert norm["normalized_phone"] == "9123456780"

    def test_normalize_dataframe(self):
        df = pd.DataFrame([
            {"full_name": "JOHN DOE", "email": "JD@EXAMPLE.COM", "phone": "123-456-7890"},
            {"full_name": None, "email": None, "phone": None}
        ])
        norm_df = normalize_dataframe(df)
        assert norm_df.loc[0, "normalized_name"] == "John Doe"
        assert norm_df.loc[0, "normalized_email"] == "jd@example.com"
        assert norm_df.loc[0, "normalized_phone"] == "1234567890"
        assert norm_df.loc[1, "normalized_name"] is None

