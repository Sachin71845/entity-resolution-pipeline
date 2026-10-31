"""
Unit and edge-case tests for validation module (src/validation.py).
"""

from pathlib import Path
import pytest
import pandas as pd

from src.ingestion import read_source_file
from src.validation import classify_records, validate_email_syntax


class TestValidationRules:
    def test_missing_source_system(self):
        df = pd.DataFrame([{
            "source_record_id": 1,
            "run_id": "test-run",
            "source_system": "",
            "source_id": "C101",
            "full_name": "Test User",
            "email": "test@example.com",
            "phone": "9876543210"
        }])
        results = classify_records(df)
        assert results[0]["validation_status"] == "REJECTED"
        assert results[0]["validation_reason"] == "missing_source_system"

    def test_missing_source_id(self):
        df = pd.DataFrame([{
            "source_record_id": 1,
            "run_id": "test-run",
            "source_system": "CRM",
            "source_id": None,
            "full_name": "Missing ID User",
            "email": "missing@example.com",
            "phone": "9876543210"
        }])
        results = classify_records(df)
        assert results[0]["validation_status"] == "REJECTED"
        assert results[0]["validation_reason"] == "missing_source_id"

    def test_invalid_email_format(self):
        assert not validate_email_syntax("invalid-email")
        assert not validate_email_syntax("user@")
        assert not validate_email_syntax("@domain.com")
        assert not validate_email_syntax("user name@domain.com")
        assert validate_email_syntax("valid.user+1@domain.co.uk")

        df = pd.DataFrame([{
            "source_record_id": 1,
            "run_id": "test-run",
            "source_system": "ECOM",
            "source_id": "E101",
            "full_name": "Bad Email",
            "email": "invalid-email",
            "phone": "9876543210"
        }])
        results = classify_records(df)
        assert results[0]["validation_status"] == "REJECTED"
        assert results[0]["validation_reason"] == "invalid_email"

    def test_unresolved_no_identifiers(self):
        df = pd.DataFrame([{
            "source_record_id": 1,
            "run_id": "test-run",
            "source_system": "CRM",
            "source_id": "C301",
            "full_name": "Unknown Person",
            "email": None,
            "phone": None
        }])
        results = classify_records(df)
        assert results[0]["validation_status"] == "UNRESOLVED"
        assert results[0]["validation_reason"] == "no_identifiers"

    def test_duplicate_source_keys_identical(self):
        df = pd.DataFrame([
            {
                "source_record_id": 1,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C101",
                "full_name": "Sachin Jadhav",
                "email": "sachin@gmail.com",
                "phone": "9876543210"
            },
            {
                "source_record_id": 2,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C101",
                "full_name": "Sachin Jadhav",
                "email": "sachin@gmail.com",
                "phone": "9876543210"
            }
        ])
        results = classify_records(df)
        assert results[0]["validation_status"] == "VALID"
        assert results[1]["validation_status"] == "DUPLICATE"
        assert results[1]["validation_reason"] == "duplicate_source_key"

    def test_duplicate_source_keys_conflicting(self):
        df = pd.DataFrame([
            {
                "source_record_id": 1,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C101",
                "full_name": "Sachin Jadhav",
                "email": "sachin@gmail.com",
                "phone": "9876543210"
            },
            {
                "source_record_id": 2,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C101",
                "full_name": "Different Name",
                "email": "different@gmail.com",
                "phone": "9876543210"
            }
        ])
        results = classify_records(df)
        assert results[0]["validation_status"] == "REJECTED"
        assert results[0]["validation_reason"] == "conflicting_duplicate_source_key"

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        results = classify_records(df)
        assert results == []

    def test_schema_mismatch_exception(self, tmp_path):
        bad_csv = tmp_path / "bad_schema.csv"
        bad_csv.write_text("wrong_col,another_col\n1,2", encoding="utf-8")
        with pytest.raises(ValueError, match="Schema mismatch"):
            read_source_file(bad_csv)

